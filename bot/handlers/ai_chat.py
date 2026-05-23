"""
AI-powered catch-all conversation handler.

Routes every free-text message (not claimed by a ConversationHandler) through
Claude with tool use. Handles onboarding, property search, preference updates,
and general questions — all in natural language.

Registered LAST in the handler registry so ConversationHandlers
(e.g. /update) and explicit command handlers always take priority.
"""

import json
import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from database import AsyncSessionLocal
from models import Listing
from services.buyer_service import (
    get_active_preference,
    get_buyer_by_telegram_id,
    patch_preferences,
    replace_preferences,
    upsert_buyer,
)
from services.ranking import get_ranked_listings
from services.nearby import get_nearby
import services.claude_service as claude_svc
from sqlalchemy import select

logger = logging.getLogger(__name__)

MAX_HISTORY = 30  # max messages stored per user

SYSTEM_PROMPT = """You are SGAbode, a friendly and knowledgeable Singapore property discovery assistant on Telegram.

Your role:
1. Onboard new users — learn their name (and optional WhatsApp) then save it with save_profile.
2. Understand their property preferences through natural conversation, then save them with save_preferences.
3. Show matching listings on demand via get_recommendations or search_listings.
4. Answer questions about Singapore's property market, districts, MRT lines, prices, and tenure.

Singapore districts (D1–D28):
D1 Raffles Place/Marina Bay, D2 Anson/Tanjong Pagar, D3 Queenstown/Tiong Bahru,
D4 Telok Blangah/Harbourfront, D5 Pasir Panjang/Clementi, D6 High Street/Beach Road,
D7 Middle Road/Golden Mile, D8 Little India, D9 Orchard/River Valley,
D10 Ardmore/Bukit Timah/Holland, D11 Novena/Thomson, D12 Balestier/Toa Payoh,
D13 Macpherson/Braddell, D14 Geylang/Eunos, D15 Katong/Joo Chiat/Amber,
D16 Bedok/Upper East Coast, D17 Loyang/Changi, D18 Tampines/Pasir Ris,
D19 Serangoon/Hougang/Punggol, D20 Bishan/Ang Mo Kio, D21 Clementi Park/Ulu Pandan,
D22 Jurong, D23 Bukit Panjang/Choa Chu Kang, D24 Lim Chu Kang/Tengah,
D25 Kranji/Woodgrove, D26 Upper Thomson/Springleaf, D27 Yishun/Sembawang, D28 Seletar

Property types: hdb, condo, landed, commercial
Intent: buy or rent
Furnishing: unfurnished, partial, fully

Behaviour guidelines:
- Be conversational and warm — not robotic or form-like.
- Collect information naturally; don't bombard the user with questions all at once.
- Ask 1–2 questions at a time and build the profile progressively.
- After saving preferences, automatically show recommendations.
- When listing properties, be concise: title, price, size (sqft), bedrooms, district.
- Keep responses short (3–5 sentences) unless displaying listings.
- If the user says "show me listings", "find me properties", "what's available", etc. — call search_listings or get_recommendations immediately.
- If the user asks about what's nearby a listing (coffee shops, parks, malls, MRT, schools, dog parks, etc.) — call search_nearby_amenities. If you don't have a listing ID yet, call search_listings first to find one.
- For nearby searches, default radius is 800m (~10 min walk). If user says "walking distance" use 800m, "short drive" use 2000m.
- Remind users they can use /like_N, /skip_N, /view_N on individual listing cards sent by the bot.
- For available commands, mention /recommend, /preferences, /liked, /help."""

TOOLS = [
    {
        "name": "save_profile",
        "description": "Save the buyer's name and optional WhatsApp number. Call this as soon as you learn the user's name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Buyer's full name"},
                "whatsapp_number": {
                    "type": "string",
                    "description": "WhatsApp number with country code, e.g. +6591234567. Optional.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "save_preferences",
        "description": (
            "Save or update the buyer's property search preferences. "
            "Only include fields the user has explicitly mentioned. "
            "Can be called multiple times as more information is collected."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": ["buy", "rent"]},
                "property_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["hdb", "condo", "landed", "commercial"]},
                },
                "price_min": {"type": "number", "description": "Minimum price in SGD"},
                "price_max": {"type": "number", "description": "Maximum price in SGD"},
                "bedrooms": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Acceptable bedroom counts, e.g. [2, 3]",
                },
                "bathrooms": {"type": "array", "items": {"type": "integer"}},
                "districts": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": 28},
                },
                "mrt_distance_max": {
                    "type": "integer",
                    "description": "Max walking distance from nearest MRT in metres",
                },
                "furnishing": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["unfurnished", "partial", "fully"]},
                },
            },
        },
    },
    {
        "name": "get_buyer_profile",
        "description": "Retrieve the buyer's current saved profile and preferences.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recommendations",
        "description": (
            "Get top property listings ranked for this buyer based on their saved preferences. "
            "Use this when the user asks for recommendations or 'show me what matches'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of results to return (1–10). Default 5.",
                    "default": 5,
                }
            },
        },
    },
    {
        "name": "search_nearby_amenities",
        "description": (
            "Search for nearby amenities around a specific property listing. "
            "Use this when the user asks what's nearby a listing — e.g. 'is there a coffee shop near listing 5?', "
            "'are there dog parks nearby?', 'how far is the nearest mall?', "
            "'what schools are within walking distance?'. "
            "Always call get_recommendations or search_listings first to know the listing ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "integer",
                    "description": "The listing ID to search around",
                },
                "amenity_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of amenity types to search for. Examples: "
                        "'cafe', 'coffee shop', 'hawker centre', 'mall', 'shopping mall', "
                        "'supermarket', 'park', 'dog park', 'playground', 'gym', "
                        "'mrt', 'bus stop', 'school', 'childcare', 'clinic', 'hospital', 'pharmacy'"
                    ),
                },
                "radius_metres": {
                    "type": "integer",
                    "description": "Search radius in metres. Default 800 (10-min walk). Max 2000.",
                    "default": 800,
                },
            },
            "required": ["listing_id", "amenity_types"],
        },
    },
    {
        "name": "search_listings",
        "description": (
            "Search active property listings with optional filters. "
            "Use when the user asks to browse or search with specific criteria "
            "that may differ from their saved preferences."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": ["buy", "rent"]},
                "property_type": {
                    "type": "string",
                    "enum": ["hdb", "condo", "landed", "commercial"],
                },
                "max_price": {"type": "number"},
                "min_bedrooms": {"type": "integer"},
                "district": {"type": "integer"},
                "limit": {"type": "integer", "default": 5},
            },
        },
    },
]


# ── Tool implementations ──────────────────────────────────────────────────────

async def _execute_tool(name: str, inputs: dict, telegram_id: int) -> str:
    if name == "save_profile":
        async with AsyncSessionLocal() as db:
            await upsert_buyer(
                db,
                telegram_id=telegram_id,
                name=inputs.get("name"),
                whatsapp_number=inputs.get("whatsapp_number"),
            )
            await db.commit()
        return f"Profile saved: name={inputs.get('name')!r}"

    if name == "save_preferences":
        async with AsyncSessionLocal() as db:
            buyer = await get_buyer_by_telegram_id(db, telegram_id)
            if not buyer:
                buyer = await upsert_buyer(db, telegram_id=telegram_id)
                await db.flush()
            existing = await get_active_preference(db, buyer.id)
            if existing:
                await patch_preferences(db, buyer.id, **inputs)
            else:
                await replace_preferences(db, buyer.id, **inputs, is_active=True)
            await db.commit()
        return f"Preferences saved: {json.dumps(inputs)}"

    if name == "get_buyer_profile":
        async with AsyncSessionLocal() as db:
            buyer = await get_buyer_by_telegram_id(db, telegram_id)
            if not buyer:
                return "No profile found — user has not registered yet."
            pref = await get_active_preference(db, buyer.id)
            profile: dict = {"name": buyer.name, "whatsapp_number": buyer.whatsapp_number}
            if pref:
                profile["preferences"] = {
                    "intent": pref.intent,
                    "property_types": pref.property_types,
                    "price_min": pref.price_min,
                    "price_max": pref.price_max,
                    "bedrooms": pref.bedrooms,
                    "bathrooms": pref.bathrooms,
                    "districts": pref.districts,
                    "mrt_distance_max": pref.mrt_distance_max,
                    "furnishing": pref.furnishing,
                }
            else:
                profile["preferences"] = None
        return json.dumps(profile, default=str)

    if name == "get_recommendations":
        limit = min(max(inputs.get("limit", 5), 1), 10)
        async with AsyncSessionLocal() as db:
            buyer = await get_buyer_by_telegram_id(db, telegram_id)
            if not buyer:
                return "No profile found. Ask the user to share their preferences first."
            pref = await get_active_preference(db, buyer.id)
            if not pref:
                return "No preferences saved yet. Collect preferences first."
            ranked = await get_ranked_listings(db, pref, limit=limit)

        if not ranked:
            return "No listings match the current preferences."

        lines = [f"Top {len(ranked)} recommendations:"]
        for i, (listing, score) in enumerate(ranked, 1):
            price = f"SGD {listing.asking_price:,.0f}" if listing.asking_price else "POA"
            br = f"{listing.bedrooms}BR" if listing.bedrooms is not None else "?"
            sz = f"{listing.floor_size:,.0f} sqft" if listing.floor_size else "? sqft"
            lines.append(
                f"{i}. {listing.title or 'Listing'} — {price} · "
                f"{br} · {sz} · D{listing.district or '?'} · Score {score:.0f}/100"
            )
        return "\n".join(lines)

    if name == "search_nearby_amenities":
        listing_id = inputs.get("listing_id")
        amenity_types = inputs.get("amenity_types", [])
        radius = inputs.get("radius_metres", 800)

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Listing).where(Listing.id == listing_id))
            listing = result.scalar_one_or_none()

        if not listing:
            return f"Listing {listing_id} not found."

        return await get_nearby(
            address=listing.address or "",
            postal=listing.postal_code,
            lat=listing.latitude,
            lng=listing.longitude,
            amenity_types=amenity_types,
            radius_metres=radius,
        )

    if name == "search_listings":
        async with AsyncSessionLocal() as db:
            q = select(Listing).where(Listing.status == "active")
            if inputs.get("intent"):
                q = q.where(Listing.intent == inputs["intent"])
            if inputs.get("property_type"):
                q = q.where(Listing.property_type == inputs["property_type"])
            if inputs.get("max_price"):
                q = q.where(Listing.asking_price <= inputs["max_price"])
            if inputs.get("min_bedrooms"):
                q = q.where(Listing.bedrooms >= inputs["min_bedrooms"])
            if inputs.get("district"):
                q = q.where(Listing.district == inputs["district"])
            q = q.limit(inputs.get("limit", 5))
            result = await db.execute(q)
            listings = result.scalars().all()

        if not listings:
            return "No active listings found for those criteria."

        lines = [f"Found {len(listings)} listing(s):"]
        for lst in listings:
            price = f"SGD {lst.asking_price:,.0f}" if lst.asking_price else "POA"
            br = f"{lst.bedrooms}BR" if lst.bedrooms is not None else "?"
            sz = f"{lst.floor_size:,.0f} sqft" if lst.floor_size else "? sqft"
            lines.append(
                f"• {lst.title or 'Listing'} — {price} · "
                f"{br} · {sz} · D{lst.district or '?'}"
            )
        return "\n".join(lines)

    return f"Unknown tool: {name!r}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_trim(messages: list[dict], max_len: int) -> list[dict]:
    """
    Trim history to at most max_len entries, but only cut at a 'user' message
    whose content is a plain string (a real user turn, not a tool_result payload).
    This prevents splitting tool-use / tool-result pairs, which would cause
    the next API call to reject the malformed history.
    """
    if len(messages) <= max_len:
        return messages
    trimmed = messages[-max_len:]
    # Walk forward until we find the first real user message (string content)
    for i, msg in enumerate(trimmed):
        if msg["role"] == "user" and isinstance(msg.get("content"), str):
            return trimmed[i:]
    # Fallback: return as-is (better than losing all history)
    return trimmed


# ── Message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route any free-text message through Claude with tool use."""
    telegram_id = update.effective_user.id
    user_text = (update.message.text or "").strip()
    if not user_text:
        return

    history: list[dict] = context.user_data.setdefault("ai_history", [])
    history.append({"role": "user", "content": user_text})

    # The Anthropic API requires the first message to be from the user.
    # Strip any leading assistant messages that might sneak in (e.g. from /start seed edge cases).
    api_messages = history
    first_user = next((i for i, m in enumerate(history) if m["role"] == "user"), None)
    if first_user and first_user > 0:
        api_messages = history[first_user:]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    async def tool_executor(tool_name: str, tool_input: dict) -> str:
        return await _execute_tool(tool_name, tool_input, telegram_id)

    try:
        reply, updated_history = await claude_svc.run_chat_turn(
            messages=api_messages,
            tools=TOOLS,
            system=SYSTEM_PROMPT,
            tool_executor=tool_executor,
        )
        # Trim history safely: never split a tool-use/tool-result exchange.
        # Always start from a "user" message (not a tool_result payload).
        context.user_data["ai_history"] = _safe_trim(updated_history, MAX_HISTORY)

        if reply:
            await update.message.reply_text(reply)
    except Exception as exc:
        logger.error("AI chat error for user %d: %s", telegram_id, exc, exc_info=True)
        await update.message.reply_text(
            "Sorry, I hit an error. Try again or use /help for available commands."
        )


# ── Registration hook ─────────────────────────────────────────────────────────

def register(app: Application) -> None:
    """Must be registered LAST — catches all text not claimed by other handlers."""
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
