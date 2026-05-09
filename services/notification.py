"""
Notification service — sends Telegram unit cards to buyers.

Consumed by the event bus (see services/registry.py).
To add a new channel (email, push, SMS), add a new listener in services/registry.py
and implement the send logic here or in a new services/email_notification.py etc.
"""

import logging

from services.claude_service import generate_unit_card_caption

logger = logging.getLogger(__name__)


async def send_unit_card(
    bot,
    telegram_id: int,
    listing: object,
    match_id: int,
) -> None:
    """Send a formatted unit card (photo + caption) to a buyer on Telegram."""
    listing_dict = {
        c.name: getattr(listing, c.name)
        for c in listing.__table__.columns
    }
    try:
        caption = await generate_unit_card_caption(listing_dict, match_id)
    except Exception as exc:
        logger.warning("Caption generation failed for match %d: %s", match_id, exc)
        caption = f"New matching listing: {listing.title}"

    try:
        photo_url = next(
            (m.url for m in (listing.media or []) if m.media_type == "image"),
            None,
        )
        if photo_url:
            await bot.send_photo(
                chat_id=telegram_id,
                photo=photo_url,
                caption=caption,
                parse_mode="Markdown",
            )
        else:
            await bot.send_message(
                chat_id=telegram_id,
                text=caption,
                parse_mode="Markdown",
            )
    except Exception as exc:
        logger.warning(
            "Failed to send unit card to telegram_id=%s (match %d): %s",
            telegram_id,
            match_id,
            exc,
        )


async def on_match_created(
    match_id: int,
    buyer_id: int,
    listing_id: int,
    telegram_id: int,
    **kwargs,
) -> None:
    """
    Event listener for 'match.created'.
    Requires the bot instance to be passed via kwargs.
    Registered in services/registry.py.
    """
    bot = kwargs.get("bot")
    listing = kwargs.get("listing")
    if not bot or not listing:
        logger.debug(
            "Skipping Telegram notification for match %d — bot or listing not provided.",
            match_id,
        )
        return

    await send_unit_card(bot, telegram_id, listing, match_id)
