"""
HDB Rental scraper — data.gov.sg official API.

Dataset: HDB Rental Contracts (approved rental applications)
No Playwright needed — pure httpx API calls.
"""

import logging
import re

import httpx

from services.scrapers.utils import town_to_district

logger = logging.getLogger(__name__)

_DATASET_ID = "d_c9f57187485a0d3dd361c01c9775d2d9"
_API_BASE = "https://data.gov.sg/api/action/datastore_search"

_FLAT_TYPE_MAP = {
    "1 ROOM":           (1, "hdb"),
    "2 ROOM":           (2, "hdb"),
    "3 ROOM":           (3, "hdb"),
    "4 ROOM":           (4, "hdb"),
    "5 ROOM":           (5, "hdb"),
    "EXECUTIVE":        (5, "hdb"),
    "MULTI-GENERATION": (6, "hdb"),
}


class HDBRentalScraper:
    """Fetches HDB rental transactions from data.gov.sg."""

    source = "hdb_rental"
    start_urls = ["https://data.gov.sg/datasets/d_c9f57187485a0d3dd361c01c9775d2d9/view"]

    async def run(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    _API_BASE,
                    params={
                        "resource_id": _DATASET_ID,
                        "limit": 100,
                        "sort": "_id desc",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.error("[hdb_rental] Fetch error: %s", exc)
                return []

        if not data.get("success"):
            logger.warning("[hdb_rental] API returned success=False: %s", data)
            return []

        records = data.get("result", {}).get("records", [])
        results = [r for rec in records if (r := self._parse_record(rec))]
        logger.info("[hdb_rental] %d records fetched", len(results))
        return results

    def _parse_record(self, rec: dict) -> dict | None:
        try:
            flat_type = rec.get("flat_type", "").upper().strip()
            bedrooms, prop_type = _FLAT_TYPE_MAP.get(flat_type, (None, "hdb"))

            town = rec.get("town", "").strip()
            block = rec.get("block", "").strip()
            street = rec.get("street_name", "").strip()
            storey_range = rec.get("storey_range", "")
            floor_area_sqm = rec.get("floor_area_sqm")
            monthly_rent = rec.get("monthly_rent")
            lease_commence = rec.get("lease_commence_date")
            approval_date = rec.get("approval_date", "")

            if not town and not street:
                return None

            address = f"Blk {block} {street}, {town}, Singapore".strip(", ")
            floor_size_sqft = round(float(floor_area_sqm) * 10.764, 1) if floor_area_sqm else None
            rent = float(monthly_rent) if monthly_rent else None
            district = town_to_district(town)

            floor_level = None
            m = re.match(r"(\d+)\s+TO\s+(\d+)", storey_range)
            if m:
                floor_level = (int(m.group(1)) + int(m.group(2))) // 2

            external_id = (
                f"hdb-rent-{block}-{street}-{flat_type}-{approval_date}"
                .replace(" ", "-")
                .lower()
            )
            title = f"{flat_type.title()} HDB Rental at {street.title()}, {town.title()}"

            rent_str = f"SGD {rent:,.0f}/mth" if rent else "POA"
            description = (
                f"{flat_type.title()} HDB rental flat in {town.title()}. "
                f"Floor area: {floor_area_sqm} sqm ({floor_size_sqft} sqft). "
                f"Storey: {storey_range}. Monthly rent: {rent_str}."
            )

            return {
                "source": self.source,
                "source_url": "https://www.hdb.gov.sg/residential/renting-a-flat",
                "external_id": external_id,
                "title": title,
                "property_type": prop_type,
                "intent": "rent",
                "address": address,
                "district": district,
                "asking_price": rent,
                "floor_size": floor_size_sqft,
                "bedrooms": bedrooms,
                "floor_level": floor_level,
                "build_year": int(lease_commence) if lease_commence else None,
                "tenure": "99-year",
                "description": description,
            }
        except Exception as exc:
            logger.debug("[hdb_rental] Parse error: %s | record: %s", exc, rec)
            return None
