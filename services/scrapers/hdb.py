"""
HDB scraper — uses the official data.gov.sg API.

No Playwright needed — pure httpx API calls.
Overrides BaseScraper.run() entirely.

Datasets used (multiple to get full coverage):
  - Resale flat prices from 2017 onwards
  - Resale flat prices 2015-2016
"""

import logging
import re

import httpx

from services.scrapers.utils import postal_to_district, town_to_district

logger = logging.getLogger(__name__)

# data.gov.sg resource IDs for HDB resale prices
# Multiple datasets cover different year ranges
_DATASETS = [
    # Resale flat prices from Jan 2017 onwards (most current)
    "d_8b84c4ee58e3cfc0ece0d773c8ca6abc",
    # Resale flat prices Jan 2015 - Dec 2016
    "d_ea9ed51da2787afaf8e51f7e75f84abb",
]

_API_BASE = "https://data.gov.sg/api/action/datastore_search"

_FLAT_TYPE_MAP = {
    "1 ROOM":          (1, "hdb"),
    "2 ROOM":          (2, "hdb"),
    "3 ROOM":          (3, "hdb"),
    "4 ROOM":          (4, "hdb"),
    "5 ROOM":          (5, "hdb"),
    "EXECUTIVE":       (5, "hdb"),
    "MULTI-GENERATION":(6, "hdb"),
}


class HDBPortalScraper:
    """
    Fetches HDB resale transactions from data.gov.sg.
    Does NOT use Playwright — pure API.
    """

    source = "hdb"
    start_urls = ["https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view"]

    async def run(self) -> list[dict]:
        """Fetch from data.gov.sg API and return list of listing dicts."""
        all_listings: list[dict] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for resource_id in _DATASETS:
                listings = await self._fetch_dataset(client, resource_id)
                all_listings.extend(listings)
                logger.info(
                    "[hdb] Dataset %s: %d records fetched", resource_id, len(listings)
                )

        logger.info("[hdb] Total: %d listings fetched", len(all_listings))
        return all_listings

    async def _fetch_dataset(self, client: httpx.AsyncClient, resource_id: str) -> list[dict]:
        """Fetch up to 100 most recent records from one dataset."""
        results = []
        try:
            resp = await client.get(
                _API_BASE,
                params={
                    "resource_id": resource_id,
                    "limit": 100,
                    "sort": "_id desc",  # most recent first
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("success") is False:
                logger.warning("[hdb] API returned success=False for %s: %s", resource_id, data)
                return []

            records = data.get("result", {}).get("records", [])
            if not records:
                logger.warning("[hdb] No records in dataset %s", resource_id)
                return []

            for rec in records:
                listing = self._parse_record(rec)
                if listing:
                    results.append(listing)

        except httpx.HTTPStatusError as exc:
            logger.error("[hdb] HTTP error for dataset %s: %s", resource_id, exc)
        except Exception as exc:
            logger.error("[hdb] Failed to fetch dataset %s: %s", resource_id, exc)

        return results

    def _parse_record(self, rec: dict) -> dict | None:
        try:
            flat_type = rec.get("flat_type", "").upper().strip()
            bedrooms, prop_type = _FLAT_TYPE_MAP.get(flat_type, (None, "hdb"))

            town = rec.get("town", "").strip()
            street = rec.get("street_name", "").strip()
            block = rec.get("block", "").strip()
            postal = str(rec.get("postal_code", "") or "").strip()
            floor_area_sqm = rec.get("floor_area_sqm")
            resale_price = rec.get("resale_price")
            storey_range = rec.get("storey_range", "")
            lease_commence = rec.get("lease_commence_date")
            month = rec.get("month", "")
            flat_model = rec.get("flat_model", "").strip()
            remaining_lease = rec.get("remaining_lease", "")

            if not town and not street:
                return None

            address = f"Blk {block} {street}, {town}, Singapore {postal}".strip(", ")
            floor_size_sqft = round(float(floor_area_sqm) * 10.764, 1) if floor_area_sqm else None
            price = float(resale_price) if resale_price else None
            psf = round(price / floor_size_sqft, 2) if price and floor_size_sqft else None
            district = postal_to_district(postal) if postal else town_to_district(town)

            # Parse storey range midpoint e.g. "07 TO 09" → 8
            floor_level = None
            m = re.match(r"(\d+)\s+TO\s+(\d+)", storey_range)
            if m:
                floor_level = (int(m.group(1)) + int(m.group(2))) // 2

            external_id = (
                f"hdb-{block}-{street}-{flat_type}-{month}"
                .replace(" ", "-")
                .lower()
            )

            title = f"{flat_type.title()} HDB at {street.title()}, {town.title()}"
            if flat_model:
                title += f" ({flat_model.title()})"

            description = (
                f"{flat_type.title()} HDB resale flat in {town.title()}. "
                f"Floor area: {floor_area_sqm} sqm ({floor_size_sqft} sqft). "
                f"Storey: {storey_range}. "
            )
            if remaining_lease:
                description += f"Remaining lease: {remaining_lease}."

            return {
                "source": self.source,
                "source_url": "https://homes.hdb.gov.sg/home/finding-a-flat",
                "external_id": external_id,
                "title": title,
                "property_type": prop_type,
                "intent": "buy",
                "address": address,
                "postal_code": postal or None,
                "district": district,
                "asking_price": price,
                "floor_size": floor_size_sqft,
                "bedrooms": bedrooms,
                "psf": psf,
                "floor_level": floor_level,
                "build_year": int(lease_commence) if lease_commence else None,
                "tenure": "99-year",
                "description": description,
            }

        except Exception as exc:
            logger.debug("[hdb] Record parse error: %s | record: %s", exc, rec)
            return None
