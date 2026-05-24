"""
Scraper runner — two separate pipelines:

LISTING SCRAPERS (active for-sale/rent units):
  SRX, 99.co, PropertyGuru, URA, HDB Rental
  → upsert into `listings` table, emit listing.created

TREND SCRAPERS (historical transactions for price context):
  HDB resale transactions
  → upsert into `district_price_trends` table, never touch listings

To add a listing scraper: add to LISTING_SCRAPERS.
To add a trend scraper:   add to TREND_SCRAPERS.
"""

import logging
from datetime import datetime, timezone
from typing import Type

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from events import bus
from models import DistrictPriceTrend, Listing
from services.scrapers.hdb import HDBTrendScraper
from services.scrapers.hdb_rental import HDBRentalScraper
from services.scrapers.ninetyco import NinetyCoScraper
from services.scrapers.propertyguru import PropertyGuruScraper
from services.scrapers.srx import SRXScraper
from services.scrapers.ura import URAScraper

logger = logging.getLogger(__name__)

# ── Active listing scrapers (shown to buyers) ─────────────────────────────────
LISTING_SCRAPERS: list = [
    SRXScraper,
    NinetyCoScraper,
    HDBRentalScraper,
    URAScraper,
    PropertyGuruScraper,
]

# ── Price trend scrapers (historical data for context only) ───────────────────
TREND_SCRAPERS: list = [
    HDBTrendScraper,
]

# Kept for backwards-compat with routes/scraper.py which uses ALL_SCRAPERS
ALL_SCRAPERS: list = LISTING_SCRAPERS + TREND_SCRAPERS

# Fields safe to update on an existing listing
_UPDATABLE_FIELDS = {
    "title", "asking_price", "floor_size", "psf", "bedrooms", "bathrooms",
    "address", "district", "postal_code", "tenure", "floor_level",
    "build_year", "description", "source_url", "furnishing",
    "unit_features", "facilities", "nearest_mrt", "mrt_distance",
}


# ── Listing upsert ────────────────────────────────────────────────────────────

async def _upsert_listing(db: AsyncSession, raw: dict) -> tuple[int | None, bool]:
    """Insert or update a listing. Returns (listing_id, is_new)."""
    source = raw.get("source")
    external_id = raw.get("external_id")
    if not raw.get("title"):
        return None, False

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
        changed = False
        for field in _UPDATABLE_FIELDS:
            new_val = raw.get(field)
            if new_val is not None and getattr(existing, field) != new_val:
                setattr(existing, field, new_val)
                changed = True
        if existing.status == "inactive":
            existing.status = "active"
            changed = True
        if changed:
            existing.updated_at = datetime.now(timezone.utc)
        return existing.id, False

    insert_data = {k: v for k, v in raw.items() if v is not None}
    insert_data.setdefault("status", "active")
    insert_data.setdefault("intent", "buy")
    listing = Listing(**{k: v for k, v in insert_data.items() if hasattr(Listing, k)})
    db.add(listing)
    await db.flush()
    return listing.id, True


async def _mark_stale_inactive(db: AsyncSession, source: str, seen_ids: list[str]) -> int:
    """Mark listings no longer found on source as inactive."""
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


# ── Price trend upsert ────────────────────────────────────────────────────────

async def _upsert_trend(db: AsyncSession, raw: dict) -> bool:
    """Insert or update a district price trend row. Returns True if changed."""
    town = raw.get("town")
    flat_type = raw.get("flat_type")
    if not town or not flat_type:
        return False

    result = await db.execute(
        select(DistrictPriceTrend).where(
            DistrictPriceTrend.town == town,
            DistrictPriceTrend.flat_type == flat_type,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        for field in ("district", "bedrooms", "sample_size", "median_price",
                      "median_psf", "min_price", "max_price", "period_start", "period_end"):
            setattr(existing, field, raw.get(field))
        return True

    db.add(DistrictPriceTrend(**{k: v for k, v in raw.items() if hasattr(DistrictPriceTrend, k)}))
    return True


# ── Runners ───────────────────────────────────────────────────────────────────

async def run_scraper(scraper_class) -> dict:
    """
    Run one scraper. Automatically routes to the right pipeline based on source name.
    Returns a summary dict.
    """
    scraper = scraper_class()
    source = scraper.source
    is_trend = source.endswith("_trend")

    summary = {"source": source, "new": 0, "updated": 0, "deactivated": 0, "errors": 0}
    logger.info("Starting scraper: %s", source)

    try:
        raw_results = await scraper.run()
    except Exception as exc:
        logger.error("Scraper %s crashed: %s", source, exc)
        summary["errors"] += 1
        return summary

    if is_trend:
        # Trend pipeline — write to district_price_trends
        async with AsyncSessionLocal() as db:
            for raw in raw_results:
                try:
                    await _upsert_trend(db, raw)
                    summary["updated"] += 1
                except Exception as exc:
                    logger.warning("Trend upsert failed: %s", exc)
                    summary["errors"] += 1
            await db.commit()
        logger.info("Trend scraper %s done: %d rows upserted", source, summary["updated"])

    else:
        # Listing pipeline — write to listings, emit events
        seen_external_ids: list[str] = []
        new_listing_ids: list[int] = []

        async with AsyncSessionLocal() as db:
            for raw in raw_results:
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

            summary["deactivated"] = await _mark_stale_inactive(db, source, seen_external_ids)
            await db.commit()

        for listing_id in new_listing_ids:
            await bus.emit("listing.created", listing_id=listing_id)

        logger.info(
            "Listing scraper %s done: +%d new, ~%d updated, -%d deactivated, %d errors",
            source, summary["new"], summary["updated"], summary["deactivated"], summary["errors"],
        )

    return summary


async def run_all_scrapers() -> list[dict]:
    """Run all listing scrapers then all trend scrapers. Returns summaries."""
    summaries = []
    for scraper_class in LISTING_SCRAPERS + TREND_SCRAPERS:
        summary = await run_scraper(scraper_class)
        summaries.append(summary)
    return summaries
