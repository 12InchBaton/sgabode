"""
Matching engine — finds buyers whose active preferences match a listing.

Public surface:
    run_matching_for_listing(db, listing_id, bot=None) -> list[int]
    on_listing_created(**payload)   ← event listener, wired in services/registry.py

Notification is delegated to the 'match.created' event so this module
has zero knowledge of Telegram or any other channel.
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from database import AsyncSessionLocal
from events import bus
from models import Buyer, BuyerPreference, Listing, Match

logger = logging.getLogger(__name__)


# ── Match predicate ────────────────────────────────────────────────────────────

def _arrays_overlap(pref_arr: Optional[list], value) -> bool:
    """True if pref_arr is empty/None (= any) OR value appears in pref_arr."""
    if not pref_arr:
        return True
    if value is None:
        return False
    if isinstance(value, list):
        return bool(set(pref_arr) & set(value))
    return value in pref_arr


def preference_matches_listing(pref: BuyerPreference, listing: Listing) -> bool:
    """
    Pure, side-effect-free predicate.
    Returns True if listing satisfies all non-null preference constraints.
    """
    checks = [
        # Intent
        not pref.intent or pref.intent == listing.intent,
        # Property type
        _arrays_overlap(pref.property_types, listing.property_type),
        # Price
        pref.price_min is None or listing.asking_price is None or listing.asking_price >= pref.price_min,
        pref.price_max is None or listing.asking_price is None or listing.asking_price <= pref.price_max,
        # Floor size
        pref.floor_size_min is None or listing.floor_size is None or listing.floor_size >= pref.floor_size_min,
        pref.floor_size_max is None or listing.floor_size is None or listing.floor_size <= pref.floor_size_max,
        # Bedrooms / bathrooms / districts
        _arrays_overlap(pref.bedrooms, listing.bedrooms),
        _arrays_overlap(pref.bathrooms, listing.bathrooms),
        _arrays_overlap(pref.districts, listing.district),
        # MRT
        pref.mrt_distance_max is None or listing.mrt_distance is None or listing.mrt_distance <= pref.mrt_distance_max,
        # Tenure
        _arrays_overlap(pref.tenure, listing.tenure),
        # Floor level
        pref.floor_level_min is None or listing.floor_level is None or listing.floor_level >= pref.floor_level_min,
        pref.floor_level_max is None or listing.floor_level is None or listing.floor_level <= pref.floor_level_max,
        # Build year
        pref.build_year_min is None or listing.build_year is None or listing.build_year >= pref.build_year_min,
        # PSF
        pref.psf_min is None or listing.psf is None or listing.psf >= pref.psf_min,
        pref.psf_max is None or listing.psf is None or listing.psf <= pref.psf_max,
        # Furnishing
        _arrays_overlap(pref.furnishing, listing.furnishing),
    ]
    return all(checks)


# ── Core engine ────────────────────────────────────────────────────────────────

async def run_matching_for_listing(
    db: AsyncSession,
    listing_id: int,
    bot=None,
) -> list[int]:
    """
    Find matching buyers, upsert Match rows, emit 'match.created' for each new match.
    Returns list of newly created match IDs.

    `bot` is forwarded in the event payload so notification listeners can use it.
    Passing bot=None is fine — notifications will be silently skipped.
    """
    listing_result = await db.execute(
        select(Listing)
        .options(selectinload(Listing.media))
        .where(Listing.id == listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    if not listing or listing.status != "active":
        return []

    prefs_result = await db.execute(
        select(BuyerPreference, Buyer.telegram_id)
        .join(Buyer, Buyer.id == BuyerPreference.buyer_id)
        .where(BuyerPreference.is_active == True)
    )

    new_matches: list[tuple[int, int, int]] = []  # (match_id, buyer_id, telegram_id)

    for pref, telegram_id in prefs_result.all():
        if not preference_matches_listing(pref, listing):
            continue

        stmt = (
            pg_insert(Match)
            .values(buyer_id=pref.buyer_id, listing_id=listing_id)
            .on_conflict_do_nothing(constraint="uq_buyer_listing")
            .returning(Match.id)
        )
        row = (await db.execute(stmt)).fetchone()
        if row:
            new_matches.append((row[0], pref.buyer_id, telegram_id))

    await db.commit()

    # Emit one event per new match — notification service handles delivery
    for match_id, buyer_id, telegram_id in new_matches:
        await bus.emit(
            "match.created",
            match_id=match_id,
            buyer_id=buyer_id,
            listing_id=listing_id,
            telegram_id=telegram_id,
            bot=bot,
            listing=listing,
        )

    logger.info(
        "Listing %d: %d new match(es) created.", listing_id, len(new_matches)
    )
    return [m[0] for m in new_matches]


# ── Event listener ─────────────────────────────────────────────────────────────

async def on_listing_created(listing_id: int, **kwargs) -> None:
    """Subscribed to 'listing.created' via services/registry.py."""
    bot = kwargs.get("bot")
    async with AsyncSessionLocal() as db:
        await run_matching_for_listing(db, listing_id, bot=bot)
