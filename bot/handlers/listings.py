"""
Listing interaction handlers: /like_N, /skip_N, /view_N, /liked, /help.

Exposes register(app) so bot/handlers/registry.py can wire it in.
"""

import logging
import re

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from database import AsyncSessionLocal
from models import Buyer, Listing, Match, ViewingRequest
from sqlalchemy import select

logger = logging.getLogger(__name__)


# ── Shared DB helper ──────────────────────────────────────────────────────────

async def _get_match_for_user(telegram_id: int, match_id: int):
    """Return (buyer, match) or (None, None) if not found / not owned."""
    async with AsyncSessionLocal() as db:
        buyer_result = await db.execute(select(Buyer).where(Buyer.telegram_id == telegram_id))
        buyer = buyer_result.scalar_one_or_none()
        if not buyer:
            return None, None, db
        match_result = await db.execute(
            select(Match).where(Match.id == match_id, Match.buyer_id == buyer.id)
        )
        return buyer, match_result.scalar_one_or_none(), db


# ── /like_N ───────────────────────────────────────────────────────────────────

async def like_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = re.match(r"/like_(\d+)", update.message.text or "")
    if not m:
        return
    match_id = int(m.group(1))

    async with AsyncSessionLocal() as db:
        buyer_r = await db.execute(select(Buyer).where(Buyer.telegram_id == update.effective_user.id))
        buyer = buyer_r.scalar_one_or_none()
        if not buyer:
            await update.message.reply_text("Register first with /start.")
            return
        match_r = await db.execute(
            select(Match).where(Match.id == match_id, Match.buyer_id == buyer.id)
        )
        match = match_r.scalar_one_or_none()
        if not match:
            await update.message.reply_text("Match not found.")
            return
        match.interested = True
        match.skipped = False
        match.opened = True
        await db.commit()

    await update.message.reply_text(
        f"❤️ Saved! Want to book a viewing? /view_{match_id}"
    )


# ── /skip_N ───────────────────────────────────────────────────────────────────

async def skip_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = re.match(r"/skip_(\d+)", update.message.text or "")
    if not m:
        return
    match_id = int(m.group(1))

    async with AsyncSessionLocal() as db:
        buyer_r = await db.execute(select(Buyer).where(Buyer.telegram_id == update.effective_user.id))
        buyer = buyer_r.scalar_one_or_none()
        if not buyer:
            return
        match_r = await db.execute(
            select(Match).where(Match.id == match_id, Match.buyer_id == buyer.id)
        )
        match = match_r.scalar_one_or_none()
        if not match:
            await update.message.reply_text("Match not found.")
            return
        match.interested = False
        match.skipped = True
        match.opened = True
        await db.commit()

    await update.message.reply_text("👎 Skipped.")


# ── /view_N ───────────────────────────────────────────────────────────────────

async def request_viewing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = re.match(r"/view_(\d+)", update.message.text or "")
    if not m:
        return
    match_id = int(m.group(1))

    async with AsyncSessionLocal() as db:
        buyer_r = await db.execute(select(Buyer).where(Buyer.telegram_id == update.effective_user.id))
        buyer = buyer_r.scalar_one_or_none()
        if not buyer:
            await update.message.reply_text("Register first with /start.")
            return
        match_r = await db.execute(
            select(Match).where(Match.id == match_id, Match.buyer_id == buyer.id)
        )
        match = match_r.scalar_one_or_none()
        if not match:
            await update.message.reply_text("Match not found.")
            return
        if match.viewing_requested:
            await update.message.reply_text("You've already requested a viewing for this listing.")
            return

        listing_r = await db.execute(select(Listing).where(Listing.id == match.listing_id))
        listing = listing_r.scalar_one_or_none()

        vr = ViewingRequest(
            match_id=match.id,
            buyer_id=buyer.id,
            listing_id=match.listing_id,
            agent_id=listing.submitted_by if listing else None,
        )
        db.add(vr)
        match.viewing_requested = True
        match.interested = True
        await db.commit()

    await update.message.reply_text(
        "📅 *Viewing request submitted!*\n"
        "The agent will contact you shortly.",
        parse_mode="Markdown",
    )


# ── /liked ────────────────────────────────────────────────────────────────────

async def show_liked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as db:
        buyer_r = await db.execute(
            select(Buyer).where(Buyer.telegram_id == update.effective_user.id)
        )
        buyer = buyer_r.scalar_one_or_none()
        if not buyer:
            await update.message.reply_text("Register first with /start.")
            return

        rows = (await db.execute(
            select(Match, Listing)
            .join(Listing, Listing.id == Match.listing_id)
            .where(Match.buyer_id == buyer.id, Match.interested == True)
            .order_by(Match.sent_at.desc())
            .limit(10)
        )).all()

    if not rows:
        await update.message.reply_text("You haven't liked any listings yet.")
        return

    lines = ["*Your liked listings:*\n"]
    for match, listing in rows:
        price = f"SGD {listing.asking_price:,.0f}" if listing.asking_price else "POA"
        action = "viewing requested ✅" if match.viewing_requested else f"/view_{match.id}"
        lines.append(f"• {listing.title or 'Listing'} — {price} ({action})")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /help ─────────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*ProPad Commands*\n\n"
        "/start — set up or reset your preferences\n"
        "/preferences — view your current preferences\n"
        "/update — update preferences via natural language\n"
        "/liked — listings you've liked\n"
        "/like\\_<id> — like a matched listing\n"
        "/skip\\_<id> — skip a matched listing\n"
        "/view\\_<id> — request a viewing\n"
        "/help — show this message",
        parse_mode="Markdown",
    )


# ── Registration hook ─────────────────────────────────────────────────────────

def register(app: Application) -> None:
    """Called by bot/handlers/registry.py."""
    app.add_handler(CommandHandler("liked", show_liked))
    app.add_handler(CommandHandler("help", help_command))
    # Pattern-matched commands for /like_N, /skip_N, /view_N
    app.add_handler(MessageHandler(filters.Regex(r"^/like_\d+"), like_listing))
    app.add_handler(MessageHandler(filters.Regex(r"^/skip_\d+"), skip_listing))
    app.add_handler(MessageHandler(filters.Regex(r"^/view_\d+"), request_viewing))
