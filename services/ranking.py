"""
Listing ranking service.

Scores each listing against a buyer's preferences on a 0–100 scale:

  Price fit          25 pts  — how well price centres within budget
  District match     20 pts  — exact district match
  Property type      15 pts  — type in preferred list
  Bedrooms           15 pts  — exact match (7 pts if ±1)
  Floor size         10 pts  — within min/max bounds
  Build year         10 pts  — newer = higher score
  PSF value           5 pts  — within psf_max

Public surface:
    score_listing(pref, listing)         → float
    get_ranked_listings(db, pref, limit) → list[(Listing, score)]
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import BuyerPreference, Listing

logger = logging.getLogger(__name__)

_CURRENT_YEAR = datetime.now().year


def score_listing(pref: BuyerPreference, listing: Listing) -> float:
    """Return a 0–100 match score."""
    score = 0.0

    # ── Price fit (25 pts) ────────────────────────────────────────────────────
    if listing.asking_price and (pref.price_min or pref.price_max):
        p_min = pref.price_min or 0
        p_max = pref.price_max or float("inf")
        if p_min <= listing.asking_price <= p_max:
            # Bonus for being close to the midpoint
            if pref.price_min and pref.price_max:
                mid = (pref.price_min + pref.price_max) / 2
                half = (pref.price_max - pref.price_min) / 2 or 1
                deviation = abs(listing.asking_price - mid) / half
                score += max(0, 25 * (1 - deviation * 0.5))
            else:
                score += 25
        else:
            # Partial credit if within 20% over budget
            overshoot = listing.asking_price - p_max
            if p_max and 0 < overshoot <= p_max * 0.2:
                score += 8
    else:
        score += 12.5  # neutral — no price data

    # ── District (20 pts) ─────────────────────────────────────────────────────
    if not pref.districts:
        score += 20  # any district
    elif listing.district and listing.district in (pref.districts or []):
        score += 20

    # ── Property type (15 pts) ────────────────────────────────────────────────
    if not pref.property_types:
        score += 15
    elif listing.property_type in (pref.property_types or []):
        score += 15

    # ── Bedrooms (15 pts) ─────────────────────────────────────────────────────
    if not pref.bedrooms:
        score += 15
    elif listing.bedrooms is not None:
        if listing.bedrooms in (pref.bedrooms or []):
            score += 15
        elif any(abs(listing.bedrooms - b) == 1 for b in (pref.bedrooms or [])):
            score += 7  # one bedroom off

    # ── Floor size (10 pts) ───────────────────────────────────────────────────
    if listing.floor_size:
        f_min = pref.floor_size_min
        f_max = pref.floor_size_max
        if f_min and f_max:
            if f_min <= listing.floor_size <= f_max:
                score += 10
            elif listing.floor_size >= f_min:
                score += 6  # bigger than requested
        elif f_min and listing.floor_size >= f_min:
            score += 10
        elif f_max and listing.floor_size <= f_max:
            score += 10
        else:
            score += 5
    else:
        score += 5  # neutral

    # ── Build year / recency (10 pts) ─────────────────────────────────────────
    if listing.build_year:
        age = _CURRENT_YEAR - listing.build_year
        if age <= 5:
            score += 10
        elif age <= 10:
            score += 7
        elif age <= 20:
            score += 4
        else:
            score += 1
    else:
        score += 5

    # ── PSF value (5 pts) ─────────────────────────────────────────────────────
    if pref.psf_max and listing.psf:
        if listing.psf <= pref.psf_max:
            score += 5
    elif not pref.psf_max:
        score += 5  # no constraint — full credit
    # else: over psf_max → 0 pts

    return round(score, 2)


async def get_ranked_listings(
    db: AsyncSession,
    pref: BuyerPreference,
    limit: int = 10,
) -> list[tuple[Listing, float]]:
    """
    Return up to `limit` (listing, score) pairs sorted by score descending.
    Only includes listings that pass all hard preference filters.
    """
    from services.matching import preference_matches_listing

    result = await db.execute(
        select(Listing).where(Listing.status == "active")
    )
    listings = result.scalars().all()

    scored: list[tuple[Listing, float]] = []
    for listing in listings:
        if preference_matches_listing(pref, listing):
            s = score_listing(pref, listing)
            scored.append((listing, s))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]
