"""
Scraper runner — upserts scraped listings into the database.

Logic:
  - New listing (source + external_id not seen before) → INSERT + emit listing.created
  - Existing listing → UPDATE price/status fields, keep ai_summary
  - Listings from a source that were active but not seen in this run → mark inactive
"""

import logging
from datetime import datetime, timezone
from typing import Type

from sqlalchemy import select, and_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from events import bus
from models import Listing
from services.scrapers.base import BaseScraper
from services.scrapers.hdb import HDBPortalScraper
from services.scrapers.hdb_rental import HDBRentalScraper
from services.scrapers.ninetyco import NinetyCoScraper
from services.scrapers.propertyguru import PropertyGuruScraper
from services.scrapers.ura import URAScraper

logger = logging.getLogger(__name__)

# All registered scrapers — add new scrapers here
ALL_SCRAPERS: list = [
    HDBPortalScraper,
    HDBRentalScraper,
    URAScraper,
    NinetyCoScraper,
    PropertyGuruScraper,
]

# Fields that are safe to update on an existing listing
_UPDATABLE_FIELDS = {
    "title", "asking_price", "floor_size", "psf", "bedrooms", "bathrooms",
    "address", "district", "postal_code", "tenure", "floor_level",
    "build_year", "description", "source_url", "furnishing",
    "unit_features", "facilities", "nearest_mrt", "mrt_distance",
}


async def _upsert_listing(db: AsyncSession, raw: dict) -> tuple[int | None, bool]:
    """
    Insert or update a listing row.
    Returns (listing_id, is_new).
    Returns (None, False) if the raw dict is invalid.
    """
    source = raw.get("source")
    external_id = raw.get("external_id")
    title = raw.get("title")

    if not title:
        return None, False

    # Check if we've seen this listing before
    existing = None
    if source and external_id:
        result = await db.execute(
            select(Listing).where(
                Listing.source == source,
                Listing.external_id == external_id,
            )
        )
        existing = result.scalar_one_or_none()

    if existing:
        # Update mutable fields
        changed = False
        for field in _UPDATABLE_FIELDS:
            new_val = raw.get(field)
            if new_val is not None and getattr(existing, field) != new_val:
                setattr(existing, field, new_val)
                changed = True

        # If listing was marked inactive and we see it again, reactivate
        if existing.status == "inactive":
            existing.status = "active"
            changed = True

        if changed:
            existing.updated_at = datetime.now(timezone.utc)

        return existing.id, False

    # New listing
    insert_data = {k: v for k, v in raw.items() if v is not None}
    insert_data.setdefault("status", "active")
    insert_data.setdefault("intent", "buy")

    listing = Listing(**{k: v for k, v in insert_data.items()
                         if hasattr(Listing, k)})
    db.add(listing)
    await db.flush()  # get listing.id without committing
    return listing.id, True


async def _mark_stale_inactive(db: AsyncSession, source: str, seen_ids: list[str]) -> int:
    """
    Any listing from this source that was active and NOT in seen_ids
    gets marked inactive — it's no longer on the site.
    Returns count of listings deactivated.
    """
    if not seen_ids:
        return 0

    result = await db.execute(
        select(Listing).where(
            Listing.source == source,
            Listing.status == "active",
            Listing.external_id.notin_(seen_ids),
        )
    )
    stale = result.scalars().all()
    for listing in stale:
        listing.status = "inactive"
        listing.updated_at = datetime.now(timezone.utc)

    return len(stale)


async def run_scraper(scraper_class: Type[BaseScraper]) -> dict:
    """
    Run one scraper end-to-end.
    Returns a summary dict: {source, new, updated, deactivated, errors}.
    """
    scraper = scraper_class()
    source = scraper.source
    summary = {"source": source, "new": 0, "updated": 0, "deactivated": 0, "errors": 0}

    logger.info("Starting scraper: %s", source)
    try:
        raw_listings = await scraper.run()
    except Exception as exc:
        logger.error("Scraper %s crashed: %s", source, exc)
        summary["errors"] += 1
        return summary

    seen_external_ids: list[str] = []
    new_listing_ids: list[int] = []

    async with AsyncSessionLocal() as db:
        for raw in raw_listings:
            try:
                listing_id, is_new = await _upsert_listing(db, raw)
                if listing_id is None:
                    continue
                if raw.get("external_id"):
                    seen_external_ids.append(raw["external_id"])
                if is_new:
                    summary["new"] += 1
                    new_listing_ids.append(listing_id)
                else:
                    summary["updated"] += 1
            except Exception as exc:
                logger.warning("Upsert failed for %s listing: %s", source, exc)
                summary["errors"] += 1

        # Deactivate listings no longer on the site
        summary["deactivated"] = await _mark_stale_inactive(db, source, seen_external_ids)
        await db.commit()

    # Emit listing.created for new listings so matching + AI runs
    for listing_id in new_listing_ids:
        await bus.emit("listing.created", listing_id=listing_id)

    logger.info(
        "Scraper %s done: +%d new, ~%d updated, -%d deactivated, %d errors",
        source, summary["new"], summary["updated"], summary["deactivated"], summary["errors"],
    )
    return summary


async def run_all_scrapers() -> list[dict]:
    """Run every registered scraper sequentially and return summaries."""
    summaries = []
    for scraper_class in ALL_SCRAPERS:
        summary = await run_scraper(scraper_class)
        summaries.append(summary)
    return summaries
