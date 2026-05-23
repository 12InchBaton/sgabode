"""
99.co scraper — uses the internal JSON search API (XHR).

⚠️  99.co's Terms of Service restrict automated scraping.
    Use responsibly: low request rate, limited results per run.

No Playwright needed — pure httpx calls to the internal search endpoint.
Note: internal API endpoints may change without notice.
"""

import asyncio
import logging
import re

import httpx

from services.scrapers.utils import postal_to_district

logger = logging.getLogger(__name__)

_API_BASE = "https://www.99.co/api/v10/listings/search"
_LISTING_BASE = "https://www.99.co"
_PAGE_SIZE = 30
_MAX_PAGES = 3  # up to 90 listings per intent

_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-SG,en;q=0.9",
    "Referer": "https://www.99.co/singapore/sale",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Origin": "https://www.99.co",
}

_PROP_TYPE_MAP = {
    "hdb":        "hdb",
    "condo":      "condo",
    "apartment":  "condo",
    "landed":     "landed",
    "commercial": "commercial",
}


class NinetyCoScraper:
    """Fetches listings from 99.co's internal search API."""

    source = "99co"
    start_urls = [
        "https://www.99.co/singapore/sale",
        "https://www.99.co/singapore/rent",
    ]

    async def run(self) -> list[dict]:
        all_listings: list[dict] = []
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS, follow_redirects=True) as client:
            for listing_type in ("sale", "rent"):
                listings = await self._fetch_intent(client, listing_type)
                all_listings.extend(listings)
                logger.info("[99co] %s: %d listings fetched", listing_type, len(listings))
                await asyncio.sleep(2)
        logger.info("[99co] Total: %d listings", len(all_listings))
        return all_listings

    async def _fetch_intent(self, client: httpx.AsyncClient, listing_type: str) -> list[dict]:
        intent = "rent" if listing_type == "rent" else "buy"
        results = []

        for page in range(1, _MAX_PAGES + 1):
            try:
                params = {
                    "listing_type": listing_type,
                    "property_segments": "residential",
                    "page_num": page,
                    "page_size": _PAGE_SIZE,
                    "show_cluster_preview": "true",
                    "summary_only": "false",
                }
                resp = await client.get(_API_BASE, params=params)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                logger.warning("[99co] HTTP %d on page %d (%s)", exc.response.status_code, page, listing_type)
                break
            except Exception as exc:
                logger.error("[99co] Fetch error page %d (%s): %s", page, listing_type, exc)
                break

            listings_raw = (
                data.get("data", {}).get("listings")
                or data.get("listings")
                or []
            )
            if not listings_raw:
                logger.info("[99co] No listings on page %d (%s) — stopping", page, listing_type)
                break

            for raw in listings_raw:
                parsed = self._parse_listing(raw, intent)
                if parsed:
                    results.append(parsed)

            await asyncio.sleep(1.5)

        return results

    def _parse_listing(self, raw: dict, intent: str) -> dict | None:
        try:
            listing_id = str(raw.get("id") or raw.get("listing_id") or "")
            if not listing_id:
                return None

            title = (raw.get("name") or raw.get("title") or "").strip()
            if not title:
                return None

            # Address
            address_parts = []
            if raw.get("address_name"):
                address_parts.append(raw["address_name"])
            elif raw.get("address"):
                address_parts.append(raw["address"])
            if raw.get("district_name"):
                address_parts.append(raw["district_name"])
            address = ", ".join(address_parts) or None

            # Price
            price = None
            for key in ("asking_price_cents", "price_cents"):
                if raw.get(key):
                    price = float(raw[key]) / 100
                    break
            if price is None:
                for key in ("asking_price", "price"):
                    if raw.get(key):
                        price = float(raw[key])
                        break

            # Size + PSF
            floor_size = None
            for key in ("floor_area_sqft", "area_sqft", "size_sqft"):
                if raw.get(key):
                    floor_size = float(raw[key])
                    break
            if not floor_size:
                sqm = raw.get("floor_area_sqm") or raw.get("area_sqm")
                if sqm:
                    floor_size = round(float(sqm) * 10.764, 1)

            psf = round(price / floor_size, 2) if price and floor_size else None

            # Rooms
            bedrooms = raw.get("bedroom_count") or raw.get("bedrooms")
            bathrooms = raw.get("bathroom_count") or raw.get("bathrooms")
            bedrooms = int(bedrooms) if bedrooms is not None else None
            bathrooms = int(bathrooms) if bathrooms is not None else None

            # District
            district = None
            district_code = raw.get("district_code") or raw.get("district")
            if district_code:
                m = re.search(r"\d+", str(district_code))
                if m:
                    district = int(m.group())
            if not district:
                postal = str(raw.get("postal_code") or "")
                district = postal_to_district(postal)

            # Property type
            raw_type = (
                raw.get("main_category")
                or raw.get("property_type")
                or raw.get("sub_category")
                or ""
            ).lower()
            prop_type = "condo"
            for key, val in _PROP_TYPE_MAP.items():
                if key in raw_type:
                    prop_type = val
                    break

            # Tenure
            tenure_raw = (raw.get("tenure") or "").lower()
            if "freehold" in tenure_raw:
                tenure = "freehold"
            elif "999" in tenure_raw:
                tenure = "999-year"
            elif "99" in tenure_raw or "leasehold" in tenure_raw:
                tenure = "99-year"
            else:
                tenure = None

            build_year = raw.get("completion_year") or raw.get("built_year")
            floor_level = raw.get("floor_level") or raw.get("storey")
            furnishing_raw = (raw.get("furnishing") or "").lower()
            if "fully" in furnishing_raw:
                furnishing = "fully"
            elif "partial" in furnishing_raw:
                furnishing = "partial"
            elif "unfurnished" in furnishing_raw or furnishing_raw == "no":
                furnishing = "unfurnished"
            else:
                furnishing = None

            listing_url = f"{_LISTING_BASE}/singapore/{'for-rent' if intent == 'rent' else 'for-sale'}/{listing_id}"
            url_slug = raw.get("url_slug") or raw.get("slug")
            if url_slug:
                listing_url = f"{_LISTING_BASE}{url_slug}" if url_slug.startswith("/") else f"{_LISTING_BASE}/{url_slug}"

            return {
                "source": self.source,
                "source_url": listing_url,
                "external_id": listing_id,
                "title": title,
                "property_type": prop_type,
                "intent": intent,
                "address": address,
                "postal_code": str(raw.get("postal_code") or "") or None,
                "district": district,
                "asking_price": price,
                "floor_size": floor_size,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "psf": psf,
                "floor_level": int(floor_level) if floor_level else None,
                "build_year": int(build_year) if build_year else None,
                "tenure": tenure,
                "furnishing": furnishing,
                "description": f"Listed on 99.co. {raw.get('description', '')}".strip(),
            }

        except Exception as exc:
            logger.debug("[99co] Parse error: %s | raw: %s", exc, str(raw)[:200])
            return None
