"""
Preference management handlers: /preferences, /update (natural language via Claude).

Exposes register(app) so bot/handlers/registry.py can wire it in.
"""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import AsyncSessionLocal
from models import BuyerPreference
from services.buyer_service import get_buyer_by_telegram_id, get_active_preference, patch_preferences
from services.claude_service import parse_preference_update
from sqlalchemy import select

logger = logging.getLogger(__name__)

AWAITING_UPDATE_MSG = 1


# ── /preferences ─────────────────────────────────────────────────────────────

async def show_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as db:
        buyer = await get_buyer_by_telegram_id(db, update.effective_user.id)
        if not buyer:
            await update.message.reply_text("Register first with /start.")
            return
        pref = await get_active_preference(db, buyer.id)

    if not pref:
        await update.message.reply_text("No preferences set. Send /start.")
        return

    def _f(val):
        if val is None:
            return "—"
        if isinstance(val, list):
            return ", ".join(str(v) for v in val) if val else "any"
        return str(val)

    lines = [
        "*Your current preferences:*\n",
        f"• Intent: {_f(pref.intent)}",
        f"• Property types: {_f(pref.property_types)}",
        f"• Price: SGD {pref.price_min or 0:,.0f} – {pref.price_max or 0:,.0f}",
        f"• Floor size: {_f(pref.floor_size_min)} – {_f(pref.floor_size_max)} sqft",
        f"• Bedrooms: {_f(pref.bedrooms)}",
        f"• Bathrooms: {_f(pref.bathrooms)}",
        f"• Districts: {_f(pref.districts)}",
        f"• Max MRT distance: {_f(pref.mrt_distance_max)} m",
        f"• Tenure: {_f(pref.tenure)}",
        f"• Floor level: {_f(pref.floor_level_min)} – {_f(pref.floor_level_max)}",
        f"• Build year min: {_f(pref.build_year_min)}",
        f"• PSF: {_f(pref.psf_min)} – {_f(pref.psf_max)}",
        f"• Unit features: {_f(pref.unit_features)}",
        f"• Facilities: {_f(pref.facilities)}",
        f"• Furnishing: {_f(pref.furnishing)}",
        f"• Keywords: {_f(pref.keywords)}",
        "",
        "Send /update to change anything in plain English.",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /update ───────────────────────────────────────────────────────────────────

async def update_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Tell me what you'd like to change, e.g.:\n\n"
        "• _3-bed condo in D9/10/11 under $3M_\n"
        "• _Add pool requirement, max PSF 2000_\n"
        "• _Freehold only_\n\n"
        "Or /cancel to abort.",
        parse_mode="Markdown",
    )
    return AWAITING_UPDATE_MSG


async def update_apply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message.text.strip()

    async with AsyncSessionLocal() as db:
        buyer = await get_buyer_by_telegram_id(db, update.effective_user.id)
        if not buyer:
            await update.message.reply_text("Register first with /start.")
            return ConversationHandler.END

        pref = await get_active_preference(db, buyer.id)
        if not pref:
            await update.message.reply_text("No preferences found. Send /start first.")
            return ConversationHandler.END

        current = {
            c.name: getattr(pref, c.name)
            for c in BuyerPreference.__table__.columns
            if c.name not in ("id", "buyer_id", "created_at", "updated_at", "is_active")
        }

        await update.message.reply_text("🤔 Analysing...")

        try:
            updates = await parse_preference_update(message, current)
        except Exception as exc:
            logger.error("Claude preference parse failed: %s", exc)
            await update.message.reply_text(
                "Sorry, I couldn't process that. Try again or use /preferences."
            )
            return ConversationHandler.END

        if not updates:
            await update.message.reply_text(
                "I couldn't identify any changes. Try being more specific."
            )
            return ConversationHandler.END

        await patch_preferences(db, buyer.id, **updates)
        await db.commit()

    change_lines = [f"• {k}: {v}" for k, v in updates.items()]
    await update.message.reply_text(
        "✅ *Updated!*\n\n" + "\n".join(change_lines) + "\n\nUse /preferences to see full profile.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def update_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Update cancelled.")
    return ConversationHandler.END


# ── Registration hook ─────────────────────────────────────────────────────────

def register(app: Application) -> None:
    """Called by bot/handlers/registry.py."""
    app.add_handler(CommandHandler("preferences", show_preferences))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("update", update_start)],
        states={
            AWAITING_UPDATE_MSG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, update_apply)
            ],
        },
        fallbacks=[CommandHandler("cancel", update_cancel)],
    ))
