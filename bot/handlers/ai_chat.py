"""
AI-powered catch-all conversation handler.

Routes every free-text message (not claimed by a ConversationHandler) through
Claude with tool use. Handles onboarding, property search, preference updates,
and general questions — all in natural language.

Registered LAST in the handler registry so ConversationHandlers
(e.g. /update) and explicit command handlers always take priority.
"""

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import services.claude_service as claude_svc
from bot.tools.registry import TOOLS, execute_tool
from services.session_service import load_history, save_history

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

    # Load history: use in-memory cache if available, else restore from DB (survives restarts).
    if "ai_history" not in context.user_data:
        context.user_data["ai_history"] = await load_history(telegram_id)

    history: list[dict] = context.user_data["ai_history"]
    history.append({"role": "user", "content": user_text})

    # The Anthropic API requires the first message to be from the user.
    # Strip any leading assistant messages that might sneak in (e.g. from /start seed edge cases).
    api_messages = history
    first_user = next((i for i, m in enumerate(history) if m["role"] == "user"), None)
    if first_user and first_user > 0:
        api_messages = history[first_user:]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    async def tool_executor(tool_name: str, tool_input: dict) -> str:
        return await execute_tool(tool_name, tool_input, telegram_id)

    try:
        reply, updated_history = await claude_svc.run_chat_turn(
            messages=api_messages,
            tools=TOOLS,
            system=SYSTEM_PROMPT,
            tool_executor=tool_executor,
        )
        # Trim safely — never split a tool-use/tool-result pair.
        trimmed = _safe_trim(updated_history, MAX_HISTORY)
        context.user_data["ai_history"] = trimmed

        # Persist to DB so history survives bot restarts and redeployments.
        await save_history(telegram_id, trimmed)

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
