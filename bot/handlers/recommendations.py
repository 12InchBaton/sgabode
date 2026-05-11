"""
/recommend — fetch top-ranked listings for the user's preferences and
send each as a card with an AI-generated reason.
"""

import logging

from sqlalchemy import select
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from database import AsyncSessionLocal
from models import Buyer, BuyerPreference, Listing
from services.ranking import get_ranked_listings
from services.claude_service import generate_recommendation_reason

logger = logging.getLogger(__name__)

MAX_RECS = 10


async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    async with AsyncSessionLocal() as db:
        buyer_r = await db.execute(
            select(Buyer).where(Buyer.telegram_id == telegram_id)
        )
        buyer = buyer_r.scalar_one_or_none()
        if not buyer:
            await update.message.reply_text(
                "Set up your preferences first with /start."
            )
            return

        pref_r = await db.execute(
            select(BuyerPreference).where(
                BuyerPreference.buyer_id == buyer.id,
                BuyerPreference.is_active == True,
            )
        )
        pref = pref_r.scalar_one_or_none()
        if not pref:
            await update.message.reply_text(
                "No active preferences found. Use /start to set them up."
            )
            return

        await update.message.reply_text("🔍 Finding your top recommendations...")

        ranked = await get_ranked_listings(db, pref, limit=MAX_RECS)

    if not ranked:
        await update.message.reply_text(
            "No matching listings found. Try /update to broaden your preferences, "
            "or ask an admin to trigger a scrape."
        )
        return

    pref_dict = {
        "intent": pref.intent,
        "property_types": pref.property_types,
        "price_min": pref.price_min,
        "price_max": pref.price_max,
        "bedrooms": pref.bedrooms,
        "districts": pref.districts,
    }

    await update.message.reply_text(
        f"🏆 *Your Top {len(ranked)} Picks*\n\n"
        "Ranked by how well each listing matches your preferences:",
        parse_mode="Markdown",
    )

    for rank, (listing, score) in enumerate(ranked, start=1):
        listing_dict = {
            c.name: getattr(listing, c.name) for c in Listing.__table__.columns
        }

        try:
            reason = await generate_recommendation_reason(listing_dict, pref_dict, rank)
        except Exception as exc:
            logger.warning("Recommendation reason failed: %s", exc)
            reason = "Strong match for your search criteria."

        price_str = (
            f"SGD {listing.asking_price:,.0f}" if listing.asking_price else "POA"
        )
        psf_str = f" · ${listing.psf:,.0f} psf" if listing.psf else ""
        size_str = f"{listing.floor_size:,.0f} sqft" if listing.floor_size else "?"
        br_str = f"{listing.bedrooms}BR" if listing.bedrooms else "?"
        district_str = f"D{listing.district}" if listing.district else "?"

        card = (
            f"*#{rank} — {listing.title}*\n"
            f"💰 {price_str}{psf_str}\n"
            f"📐 {size_str}  🛏 {br_str}\n"
            f"📍 {district_str} · {listing.address or '—'}\n"
            f"📜 {listing.tenure or '?'} · Built {listing.build_year or '?'}\n"
            f"\n✨ _{reason}_\n"
            f"\n🏅 Match score: {score:.0f}/100"
        )
        if listing.source_url:
            card += f"\n🔗 {listing.source_url}"

        await update.message.reply_text(
            card, parse_mode="Markdown", disable_web_page_preview=True
        )

    await update.message.reply_text(
        "Refine your search with /update, or /liked to see your saved listings."
    )


def register(app: Application) -> None:
    """Called by bot/handlers/registry.py."""
    app.add_handler(CommandHandler("recommend", recommend))
