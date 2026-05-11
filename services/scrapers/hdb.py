"""
HDB scraper — homes.hdb.gov.sg

Scrapes two sources:
  1. HDB Flat Portal resale listings (homes.hdb.gov.sg)
  2. data.gov.sg HDB resale transactions API (official, no scraping needed)

The data.gov.sg API is used for recent resale transactions as it is
officially provided and much more reliable than screen-scraping.
The Playwright scraper targets the HDB flat listings page for
current active listings.
"""

import asyncio
import json
import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import Page

from services.scrapers.base import BaseScraper
from services.scrapers.utils import (
    clean_text,
    parse_floor_size,
    parse_price,
    postal_to_district,
)

logger = logging.getLogger(__name__)

# data.gov.sg dataset resource ID for HDB resale flat prices
_DATAGOV_RESALE_URL = (
    "https://data.gov.sg/api/action/datastore_search"
    "?resource_id=f1765b54-a209-4718-8d38-a39237f502b3"
    "&limit=100&sort=month%20desc"
)

# HDB flat types → our property_type / bedroom mapping
_FLAT_TYPE_MAP = {
    "1 ROOM": (1, "hdb"),
    "2 ROOM": (2, "hdb"),
    "3 ROOM": (3, "hdb"),
    "4 ROOM": (4, "hdb"),
    "5 ROOM": (5, "hdb"),
    "EXECUTIVE": (5, "hdb"),
    "MULTI-GENERATION": (6, "hdb"),
}


class HDBPortalScraper(BaseScraper):
    """
    Scrapes active HDB resale listings from the HDB Flat Portal.
    Falls back to the data.gov.sg API for recent transaction data.
    """

    source = "hdb"
    start_urls = [
        "https://homes.hdb.gov.sg/home/finding-a-flat",
    ]
    request_delay = 3.0

    async def scrape_page(self, page: Page, url: str) -> list[dict]:
        listings: list[dict] = []

        # ── Strategy 1: Try to navigate to resale search results ─────────────
        try:
            # Look for links to resale flat listings
            await page.wait_for_selector("a", timeout=10_000)
            content = await page.content()
            soup = BeautifulSoup(content, "lxml")

            # Find links to resale/flat listing pages
            resale_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if any(k in href.lower() for k in ["resale", "flat", "listing", "search"]):
                    if href.startswith("http"):
                        resale_links.append(href)
                    elif href.startswith("/"):
                        resale_links.append(f"https://homes.hdb.gov.sg{href}")

            # Try to scrape the first resale listing page found
            for link in resale_links[:2]:
                try:
                    sub_page = await page.context.new_page()
                    await sub_page.goto(link, wait_until="networkidle", timeout=25_000)
                    await asyncio.sleep(2)
                    sub_content = await sub_page.content()
                    parsed = self._parse_listing_page(sub_content, link)
                    listings.extend(parsed)
                    await sub_page.close()
                except Exception as exc:
                    logger.warning("HDB sub-page failed: %s", exc)

        except Exception as exc:
            logger.warning("HDB portal scrape failed, falling back to API: %s", exc)

        # ── Strategy 2: data.gov.sg official API (always runs) ───────────────
        api_listings = await self._fetch_datagov_resale()
        listings.extend(api_listings)

        return listings

    def _parse_listing_page(self, html: str, source_url: str) -> list[dict]:
        """Parse HDB listing cards from HTML."""
        soup = BeautifulSoup(html, "lxml")
        results = []

        # Generic card selectors — adjust if HDB updates their markup
        cards = (
            soup.select(".listing-card")
            or soup.select("[class*='flat-card']")
            or soup.select("[class*='property-card']")
            or soup.select("article")
        )

        for card in cards:
            try:
                title = clean_text(card.select_one("h2, h3, .title, [class*='title']") and
                                   card.select_one("h2, h3, .title, [class*='title']").get_text())
                price_el = card.select_one("[class*='price'], .price")
                address_el = card.select_one("[class*='address'], .address, [class*='location']")
                size_el = card.select_one("[class*='size'], [class*='sqft'], [class*='floor']")

                if not title and not address_el:
                    continue

                listing: dict = {
                    "source": self.source,
                    "source_url": source_url,
                    "property_type": "hdb",
                    "intent": "buy",
                    "title": title,
                    "address": clean_text(address_el.get_text()) if address_el else None,
                    "asking_price": parse_price(price_el.get_text() if price_el else None),
                    "floor_size": parse_floor_size(size_el.get_text() if size_el else None),
                }

                # External ID from card link
                link = card.select_one("a[href]")
                if link:
                    href = link["href"]
                    listing["source_url"] = (
                        href if href.startswith("http") else f"https://homes.hdb.gov.sg{href}"
                    )
                    id_match = re.search(r"[?&/](\d{6,})", href)
                    listing["external_id"] = id_match.group(1) if id_match else None

                # Compute PSF
                if listing.get("asking_price") and listing.get("floor_size"):
                    listing["psf"] = round(listing["asking_price"] / listing["floor_size"], 2)

                results.append(listing)
            except Exception as exc:
                logger.debug("HDB card parse error: %s", exc)

        return results

    async def _fetch_datagov_resale(self) -> list[dict]:
        """
        Pull recent resale transactions from data.gov.sg.
        These are actual completed transactions — intent is 'buy' (resale market).
        """
        results = []
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(_DATAGOV_RESALE_URL)
                resp.raise_for_status()
                data = resp.json()

            records = data.get("result", {}).get("records", [])
            for rec in records:
                flat_type = rec.get("flat_type", "").upper().strip()
                bedrooms, prop_type = _FLAT_TYPE_MAP.get(flat_type, (None, "hdb"))
                town = rec.get("town", "")
                street = rec.get("street_name", "")
                block = rec.get("block", "")
                postal = rec.get("postal_code") or rec.get("postal", "")
                floor_area = rec.get("floor_area_sqm")
                resale_price = rec.get("resale_price")
                storey_range = rec.get("storey_range", "")  # e.g. "07 TO 09"
                lease_commence = rec.get("lease_commence_date")
                month = rec.get("month", "")  # e.g. "2024-03"

                address = f"Blk {block} {street}, {town}, Singapore".strip()
                floor_size_sqft = round(float(floor_area) * 10.764, 1) if floor_area else None
                price = float(resale_price) if resale_price else None
                psf = round(price / floor_size_sqft, 2) if price and floor_size_sqft else None
                district = postal_to_district(str(postal)) if postal else None

                # Parse storey range to get floor level midpoint
                floor_level = None
                storey_match = re.match(r"(\d+)\s+TO\s+(\d+)", storey_range)
                if storey_match:
                    floor_level = (int(storey_match.group(1)) + int(storey_match.group(2))) // 2

                external_id = f"hdb-{block}-{street}-{flat_type}-{month}".replace(" ", "-").lower()

                listing = {
                    "source": self.source,
                    "source_url": "https://homes.hdb.gov.sg/home/finding-a-flat",
                    "external_id": external_id,
                    "title": f"{flat_type.title()} HDB at {street.title()}, {town.title()}",
                    "property_type": prop_type,
                    "intent": "buy",
                    "address": address,
                    "postal_code": str(postal) if postal else None,
                    "district": district,
                    "asking_price": price,
                    "floor_size": floor_size_sqft,
                    "bedrooms": bedrooms,
                    "psf": psf,
                    "floor_level": floor_level,
                    "build_year": int(lease_commence) if lease_commence else None,
                    "tenure": "99-year",
                    "description": (
                        f"{flat_type.title()} HDB resale flat in {town.title()}. "
                        f"Floor area {floor_area} sqm ({floor_size_sqft} sqft). "
                        f"Storey range: {storey_range}."
                    ),
                }
                results.append(listing)

        except Exception as exc:
            logger.error("data.gov.sg API fetch failed: %s", exc)

        return results
