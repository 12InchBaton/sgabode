"""
Buyer onboarding ConversationHandler — collects preferences step by step.

Exposes register(app) so bot/handlers/registry.py can wire it in without
touching bot/bot.py.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import AsyncSessionLocal
from services.buyer_service import upsert_buyer, replace_preferences

logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
(
    GET_NAME,
    GET_WHATSAPP,
    GET_INTENT,
    GET_PROPERTY_TYPES,
    GET_PRICE_RANGE,
    GET_BEDROOMS,
    GET_BATHROOMS,
    GET_DISTRICTS,
    GET_MRT_DISTANCE,
    GET_FURNISHING,
    CONFIRM,
) = range(11)


# ── Keyboards ─────────────────────────────────────────────────────────────────

def _intent_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Buy", callback_data="intent_buy"),
            InlineKeyboardButton("Rent", callback_data="intent_rent"),
        ]
    ])


def _property_type_kb():
    types = ["hdb", "condo", "landed", "commercial"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t.upper(), callback_data=f"pt_{t}") for t in types],
        [InlineKeyboardButton("✅ Done", callback_data="pt_done")],
    ])


def _furnishing_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Any", callback_data="furn_any"),
            InlineKeyboardButton("Unfurnished", callback_data="furn_unfurnished"),
        ],
        [
            InlineKeyboardButton("Partial", callback_data="furn_partial"),
            InlineKeyboardButton("Fully", callback_data="furn_fully"),
        ],
        [InlineKeyboardButton("✅ Done", callback_data="furn_done")],
    ])


def _yesno_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Yes, looks good!", callback_data="confirm_yes"),
            InlineKeyboardButton("Start over", callback_data="confirm_no"),
        ]
    ])


def _format_prefs(data: dict) -> str:
    return "\n".join([
        "*Your preferences:*",
        f"• Intent: {data.get('intent', '—')}",
        f"• Property types: {', '.join(data.get('property_types', [])) or '—'}",
        f"• Price: SGD {data.get('price_min', 0):,.0f} – {data.get('price_max', 0):,.0f}",
        f"• Bedrooms: {data.get('bedrooms', []) or 'any'}",
        f"• Bathrooms: {data.get('bathrooms', []) or 'any'}",
        f"• Districts: {data.get('districts', []) or 'any'}",
        f"• Max MRT distance: {data.get('mrt_distance_max') or '—'} m",
        f"• Furnishing: {', '.join(data.get('furnishing', [])) or 'any'}",
    ])


# ── Step handlers ─────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Welcome to *ProPad* — Singapore's smartest property discovery bot!\n\n"
        "Let's set up your profile. What's your name?",
        parse_mode="Markdown",
    )
    return GET_NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        f"Nice to meet you, {context.user_data['name']}! 🎉\n\n"
        "What's your WhatsApp number? (e.g. +6591234567)\n"
        "Or /skip to skip.",
    )
    return GET_WHATSAPP


async def get_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["whatsapp_number"] = update.message.text.strip()
    await update.message.reply_text(
        "Are you looking to *buy* or *rent*?",
        parse_mode="Markdown",
        reply_markup=_intent_kb(),
    )
    return GET_INTENT


async def skip_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Are you looking to *buy* or *rent*?",
        parse_mode="Markdown",
        reply_markup=_intent_kb(),
    )
    return GET_INTENT


async def get_intent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["intent"] = query.data.split("_")[1]
    context.user_data["property_types"] = []
    await query.edit_message_text(
        "Which property types? Tap to select, then ✅ Done.",
        reply_markup=_property_type_kb(),
    )
    return GET_PROPERTY_TYPES


async def get_property_types(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "pt_done":
        if not context.user_data.get("property_types"):
            await query.answer("Please select at least one type.", show_alert=True)
            return GET_PROPERTY_TYPES
        await query.edit_message_text(
            "What's your *price range* (SGD)?\nFormat: `500000-1200000`",
            parse_mode="Markdown",
        )
        return GET_PRICE_RANGE

    pt = query.data.replace("pt_", "")
    types: list = context.user_data.setdefault("property_types", [])
    if pt in types:
        types.remove(pt)
    else:
        types.append(pt)

    await query.edit_message_text(
        f"Selected: *{', '.join(types) or 'none'}*\nTap more or ✅ Done.",
        parse_mode="Markdown",
        reply_markup=_property_type_kb(),
    )
    return GET_PROPERTY_TYPES


async def get_price_range(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", "").replace(" ", "")
    try:
        lo, hi = (float(p) for p in text.split("-"))
        context.user_data.update(price_min=lo, price_max=hi)
    except (ValueError, TypeError):
        await update.message.reply_text("Please use the format `500000-1200000`.", parse_mode="Markdown")
        return GET_PRICE_RANGE
    await update.message.reply_text(
        "How many *bedrooms*? (e.g. `2,3` or `any`)", parse_mode="Markdown"
    )
    return GET_BEDROOMS


async def get_bedrooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text == "any":
        context.user_data["bedrooms"] = []
    else:
        try:
            context.user_data["bedrooms"] = [int(x.strip()) for x in text.split(",")]
        except ValueError:
            await update.message.reply_text("Enter numbers like `2,3` or `any`.", parse_mode="Markdown")
            return GET_BEDROOMS
    await update.message.reply_text("How many *bathrooms*? (e.g. `1,2` or `any`)", parse_mode="Markdown")
    return GET_BATHROOMS


async def get_bathrooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text == "any":
        context.user_data["bathrooms"] = []
    else:
        try:
            context.user_data["bathrooms"] = [int(x.strip()) for x in text.split(",")]
        except ValueError:
            await update.message.reply_text("Enter numbers like `1,2` or `any`.", parse_mode="Markdown")
            return GET_BATHROOMS
    await update.message.reply_text(
        "Which *districts*? (1-28, comma-separated, or `any`)\ne.g. `9,10,11`",
        parse_mode="Markdown",
    )
    return GET_DISTRICTS


async def get_districts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text == "any":
        context.user_data["districts"] = []
    else:
        try:
            context.user_data["districts"] = [int(x.strip()) for x in text.split(",")]
        except ValueError:
            await update.message.reply_text("Enter district numbers like `9,10,11` or `any`.", parse_mode="Markdown")
            return GET_DISTRICTS
    await update.message.reply_text("Max distance from MRT? (metres, e.g. `500`, or `any`)")
    return GET_MRT_DISTANCE


async def get_mrt_distance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    context.user_data["mrt_distance_max"] = None if text == "any" else int(text) if text.isdigit() else None
    await update.message.reply_text("Furnishing preference?", reply_markup=_furnishing_kb())
    return GET_FURNISHING


async def get_furnishing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data in ("furn_done", "furn_any"):
        context.user_data.setdefault("furnishing", [])
        await query.edit_message_text(
            _format_prefs(context.user_data) + "\n\nDoes this look right?",
            parse_mode="Markdown",
            reply_markup=_yesno_kb(),
        )
        return CONFIRM

    furn = query.data.replace("furn_", "")
    furnishing: list = context.user_data.setdefault("furnishing", [])
    if furn in furnishing:
        furnishing.remove(furn)
    else:
        furnishing.append(furn)

    await query.edit_message_text(
        f"Selected: *{', '.join(furnishing) or 'none'}*\nTap more or ✅ Done.",
        parse_mode="Markdown",
        reply_markup=_furnishing_kb(),
    )
    return GET_FURNISHING


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_no":
        await query.edit_message_text("No problem! Send /start to begin again.")
        return ConversationHandler.END

    telegram_id = update.effective_user.id
    data = context.user_data

    async with AsyncSessionLocal() as db:
        buyer = await upsert_buyer(
            db,
            telegram_id=telegram_id,
            name=data.get("name"),
            whatsapp_number=data.get("whatsapp_number"),
        )
        await replace_preferences(
            db,
            buyer.id,
            intent=data.get("intent"),
            property_types=data.get("property_types", []),
            price_min=data.get("price_min"),
            price_max=data.get("price_max"),
            bedrooms=data.get("bedrooms", []),
            bathrooms=data.get("bathrooms", []),
            districts=data.get("districts", []),
            mrt_distance_max=data.get("mrt_distance_max"),
            furnishing=data.get("furnishing", []),
            is_active=True,
        )
        await db.commit()

    await query.edit_message_text(
        "✅ *Preferences saved!*\n\n"
        "I'll notify you when a matching listing appears.\n\n"
        "/preferences — view your profile\n"
        "/update — update via natural language\n"
        "/help — all commands",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Onboarding cancelled. Send /start to begin again.")
    return ConversationHandler.END


# ── Handler builder + registration hook ──────────────────────────────────────

def _build() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GET_WHATSAPP: [
                CommandHandler("skip", skip_whatsapp),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_whatsapp),
            ],
            GET_INTENT: [CallbackQueryHandler(get_intent, pattern="^intent_")],
            GET_PROPERTY_TYPES: [CallbackQueryHandler(get_property_types, pattern="^pt_")],
            GET_PRICE_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_price_range)],
            GET_BEDROOMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bedrooms)],
            GET_BATHROOMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bathrooms)],
            GET_DISTRICTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_districts)],
            GET_MRT_DISTANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_mrt_distance)],
            GET_FURNISHING: [CallbackQueryHandler(get_furnishing, pattern="^furn_")],
            CONFIRM: [CallbackQueryHandler(confirm, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )


def register(app: Application) -> None:
    """Called by bot/handlers/registry.py — never import from bot.py directly."""
    app.add_handler(_build())
