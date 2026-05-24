"""
HDB Price Trend Scraper — uses the official data.gov.sg API.

Fetches historical resale transactions (NOT active listings — those are
already sold) and computes median price/PSF per town and flat type.

Results are stored in the `district_price_trends` table and used by the
bot to answer price trend questions like "what do 4-room HDBs cost in Bishan?".

Active HDB for-sale listings come from SRX and 99.co scrapers instead.
"""

import asyncio
import logging
import statistics

import httpx

from services.scrapers.utils import town_to_district

logger = logging.getLogger(__name__)

_DATASETS = [
    # Resale flat prices from Jan 2017 onwards (most current)
    "d_8b84c4ee58e3cfc0ece0d773c8ca6abc",
]

_API_BASE = "https://data.gov.sg/api/action/datastore_search"

_ALL_TOWNS = [
    "ANG MO KIO", "BEDOK", "BISHAN", "BUKIT BATOK", "BUKIT MERAH",
    "BUKIT PANJANG", "BUKIT TIMAH", "CENTRAL AREA", "CHOA CHU KANG",
    "CLEMENTI", "GEYLANG", "HOUGANG", "JURONG EAST", "JURONG WEST",
    "KALLANG/WHAMPOA", "MARINE PARADE", "PASIR RIS", "PUNGGOL",
    "QUEENSTOWN", "SEMBAWANG", "SENGKANG", "SERANGOON", "TAMPINES",
    "TOA PAYOH", "WOODLANDS", "YISHUN",
]

_FLAT_TYPE_MAP = {
    "1 ROOM":           1,
    "2 ROOM":           2,
    "3 ROOM":           3,
    "4 ROOM":           4,
    "5 ROOM":           5,
    "EXECUTIVE":        5,
    "MULTI-GENERATION": 6,
}

# Fetch last N months of transactions per town for trend accuracy
MONTHS_LOOKBACK = 12
RECORDS_PER_TOWN = 200  # enough to compute meaningful medians


class HDBTrendScraper:
    """
    Fetches HDB resale transactions and stores aggregated price trends.
    Does NOT insert into the listings table.
    """

    source = "hdb_trend"
    start_urls = ["https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view"]

    async def run(self) -> list[dict]:
        """
        Fetch transactions, compute medians per town+flat_type, return as dicts.
        The runner calls upsert on district_price_trends instead of listings.
        """
        # Collect raw transactions per town
        town_data: dict[str, list[dict]] = {t: [] for t in _ALL_TOWNS}

        async with httpx.AsyncClient(timeout=30) as client:
            for town in _ALL_TOWNS:
                records = await self._fetch_town(client, town)
                town_data[town] = records
                await asyncio.sleep(0.3)

        # Compute trends
        trends = []
        for town, records in town_data.items():
            if not records:
                continue
            by_flat: dict[str, list[dict]] = {}
            for r in records:
                ft = r.get("flat_type", "").upper().strip()
                by_flat.setdefault(ft, []).append(r)

            for flat_type, txns in by_flat.items():
                prices = []
                psfs = []
                months = []
                for t in txns:
                    try:
                        price = float(t.get("resale_price", 0))
                        sqm = float(t.get("floor_area_sqm", 0))
                        if price > 0 and sqm > 0:
                            sqft = sqm * 10.764
                            prices.append(price)
                            psfs.append(round(price / sqft, 2))
                        month = t.get("month", "")
                        if month:
                            months.append(month)
                    except (ValueError, TypeError):
                        continue

                if not prices:
                    continue

                months_sorted = sorted(months)
                trends.append({
                    "town": town,
                    "district": town_to_district(town),
                    "flat_type": flat_type,
                    "bedrooms": _FLAT_TYPE_MAP.get(flat_type),
                    "sample_size": len(prices),
                    "median_price": round(statistics.median(prices)),
                    "median_psf": round(statistics.median(psfs), 2),
                    "min_price": round(min(prices)),
                    "max_price": round(max(prices)),
                    "period_start": months_sorted[0] if months_sorted else None,
                    "period_end": months_sorted[-1] if months_sorted else None,
                })

        logger.info("[hdb_trend] Computed %d town+flat_type trends", len(trends))
        return trends

    async def _fetch_town(self, client: httpx.AsyncClient, town: str) -> list[dict]:
        """Fetch up to RECORDS_PER_TOWN most recent transactions for a town."""
        try:
            resp = await client.get(
                _API_BASE,
                params={
                    "resource_id": _DATASETS[0],
                    "limit": RECORDS_PER_TOWN,
                    "sort": "_id desc",
                    "filters": f'{{"town": "{town}"}}',
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("success") is False:
                return []
            return data.get("result", {}).get("records", [])
        except Exception as exc:
            logger.error("[hdb_trend] Fetch error for town=%s: %s", town, exc)
            return []


# Keep HDBPortalScraper as an alias so runner.py import doesn't break
HDBPortalScraper = HDBTrendScraper
