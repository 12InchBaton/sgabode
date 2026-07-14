"""
SRX (Singapore Real Estate Exchange) scraper.

Uses SRX's public listing search API — covers HDB, condo, and landed
active-for-sale and for-rent listings with real asking prices.

No API key required. No Playwright needed — pure httpx.
Note: unofficial endpoint, may change without notice.
"""

import asyncio
import logging
import re

from curl_cffi.requests import AsyncSession

from services.scrapers.utils import cap_per_district, postal_to_district

logger = logging.getLogger(__name__)

_API_BASE = "https://www.srx.com.sg/listing/search"
_LISTING_BASE = "https://www.srx.com.sg"
_PAGE_SIZE = 30
_MAX_PAGES = 3

_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-SG,en;q=0.9",
    "Referer": "https://www.srx.com.sg/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# SRX property type codes → our schema
_PROP_TYPE_MAP = {
    "HDB": "hdb",
    "Condo": "condo",
    "Apartment": "condo",
    "EC": "condo",          # Executive Condo
    "Landed": "landed",
    "Terrace": "landed",
    "Semi-D": "landed",
    "Bungalow": "landed",
    "Shophouse": "commercial",
    "Commercial": "commercial",
}


class SRXScraper:
    """Fetches active listings from SRX's search API."""

    source = "srx"
    start_urls = ["https://www.srx.com.sg/"]

    async def run(self) -> list[dict]:
        all_listings: list[dict] = []
        async with AsyncSession(impersonate="chrome120", timeout=30) as client:
            for intent_code, intent in (("S", "buy"), ("R", "rent")):
                listings = await self._fetch_intent(client, intent_code, intent)
                all_listings.extend(listings)
                logger.info("[srx] %s: %d listings", intent, len(listings))
                await asyncio.sleep(2)
        all_listings = cap_per_district(all_listings)
        logger.info("[srx] Total: %d listings", len(all_listings))
        return all_listings

    async def _fetch_intent(
        self, client: AsyncSession, intent_code: str, intent: str
    ) -> list[dict]:
        results = []

        for page in range(1, _MAX_PAGES + 1):
            try:
                params = {
                    "listingType": intent_code,
                    "listingCat": "residential",
                    "pageNum": page,
                    "maxResult": _PAGE_SIZE,
                }
                resp = await client.get(_API_BASE, params=params, headers=_HEADERS)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                if hasattr(exc, "response") and exc.response is not None:
                    logger.warning("[srx] HTTP %d on page %d (%s)", exc.response.status_code, page, intent)
                break
                else:
                    logger.error("[srx] Fetch error page %d (%s): %s", page, intent, exc)
                break

            listings_raw = (
                data.get("data", {}).get("listings")
                or data.get("listings")
                or data.get("result")
                or []
            )
            if not listings_raw:
                logger.info("[srx] No listings on page %d (%s) — stopping", page, intent)
                break

            for raw in listings_raw:
                parsed = self._parse_listing(raw, intent)
                if parsed:
                    results.append(parsed)

            await asyncio.sleep(1.5)

        return results

    def _parse_listing(self, raw: dict, intent: str) -> dict | None:
        try:
            listing_id = str(raw.get("id") or raw.get("listingId") or raw.get("listing_id") or "")
            if not listing_id:
                return None

            title = (
                raw.get("name")
                or raw.get("title")
                or raw.get("projectName")
                or raw.get("project_name")
                or ""
            ).strip()
            if not title:
                return None

            # Address
            addr_parts = []
            for key in ("address", "streetName", "street_name", "projectName"):
                val = raw.get(key, "")
                if val and val not in addr_parts:
                    addr_parts.append(val)
            address = ", ".join(addr_parts[:2]) or None

            # Postal / district
            postal = str(raw.get("postalCode") or raw.get("postal_code") or "")
            district = None
            district_raw = raw.get("district") or raw.get("districtCode")
            if district_raw:
                m = re.search(r"\d+", str(district_raw))
                if m:
                    district = int(m.group())
            if not district and postal:
                district = postal_to_district(postal)

            # Price
            price = None
            for key in ("askingPrice", "asking_price", "price", "monthlyRent", "monthly_rent"):
                val = raw.get(key)
                if val:
                    try:
                        price = float(str(val).replace(",", ""))
                        break
                    except (ValueError, TypeError):
                        pass

            # Size + PSF
            floor_size = None
            for key in ("floorAreaSqft", "floor_area_sqft", "sizeSqft", "size_sqft", "areaSqft"):
                val = raw.get(key)
                if val:
                    try:
                        floor_size = float(str(val).replace(",", ""))
                        break
                    except (ValueError, TypeError):
                        pass
            if not floor_size:
                for key in ("floorAreaSqm", "floor_area_sqm", "areaSqm"):
                    val = raw.get(key)
                    if val:
                        try:
                            floor_size = round(float(val) * 10.764, 1)
                            break
                        except (ValueError, TypeError):
                            pass

            psf_raw = raw.get("psf") or raw.get("pricePerSqft")
            psf = None
            if psf_raw:
                try:
                    psf = float(str(psf_raw).replace(",", ""))
                except (ValueError, TypeError):
                    pass
            if not psf and price and floor_size:
                psf = round(price / floor_size, 2)

            # Rooms
            bedrooms = raw.get("bedroom") or raw.get("bedrooms") or raw.get("noOfBedrooms")
            bathrooms = raw.get("bathroom") or raw.get("bathrooms") or raw.get("noOfBathrooms")
            bedrooms = int(bedrooms) if bedrooms is not None else None
            bathrooms = int(bathrooms) if bathrooms is not None else None

            # Property type
            type_raw = (
                raw.get("propertyType")
                or raw.get("property_type")
                or raw.get("category")
                or ""
            )
            prop_type = "condo"
            for key, val in _PROP_TYPE_MAP.items():
                if key.lower() in str(type_raw).lower():
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

            build_year = raw.get("builtYear") or raw.get("built_year") or raw.get("completionYear")
            floor_level = raw.get("floorLevel") or raw.get("floor_level") or raw.get("storey")

            furnishing_raw = (raw.get("furnishing") or raw.get("furnishedType") or "").lower()
            if "fully" in furnishing_raw or furnishing_raw == "full":
                furnishing = "fully"
            elif "partial" in furnishing_raw:
                furnishing = "partial"
            elif "unfurnished" in furnishing_raw or furnishing_raw in ("no", "none"):
                furnishing = "unfurnished"
            else:
                furnishing = None

            listing_url = (
                raw.get("listingUrl")
                or raw.get("url")
                or f"{_LISTING_BASE}/listing/{listing_id}"
            )
            if listing_url and not listing_url.startswith("http"):
                listing_url = f"{_LISTING_BASE}{listing_url}"

            return {
                "source": self.source,
                "source_url": listing_url,
                "external_id": listing_id,
                "title": title,
                "property_type": prop_type,
                "intent": intent,
                "address": address,
                "postal_code": postal or None,
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
                "description": f"Listed on SRX. {raw.get('remarks', '') or ''}".strip(),
            }

        except Exception as exc:
            logger.debug("[srx] Parse error: %s | raw: %s", exc, str(raw)[:200])
            return None
