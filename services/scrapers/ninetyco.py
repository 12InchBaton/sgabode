"""
99.co scraper — Singapore property marketplace.

⚠️  99.co's Terms of Service restrict automated scraping.
    Use responsibly: low request rate, limited pages.

Uses Playwright for JS-rendered pages.
"""

import asyncio
import logging
import re

from bs4 import BeautifulSoup
from playwright.async_api import Page

from services.scrapers.base import BaseScraper
from services.scrapers.utils import clean_text, parse_floor_size, parse_price

logger = logging.getLogger(__name__)

BASE_URL = "https://www.99.co"
MAX_PAGES = 3


class NinetyCoScraper(BaseScraper):
    source = "99co"
    start_urls = [
        f"{BASE_URL}/singapore/sale",
        f"{BASE_URL}/singapore/rent",
    ]
    request_delay = 4.0

    async def scrape_page(self, page: Page, url: str) -> list[dict]:
        intent = "rent" if "/rent" in url else "buy"
        all_listings: list[dict] = []

        for page_num in range(1, MAX_PAGES + 1):
            try:
                if page_num > 1:
                    paginated = f"{url}?page_num={page_num}"
                    await page.goto(paginated, wait_until="networkidle", timeout=30_000)
                    await asyncio.sleep(self.request_delay)

                try:
                    await page.wait_for_selector(
                        '[data-automation-id="listing-card"], '
                        '[class*="ListingCard"], [class*="listing-card"]',
                        timeout=15_000,
                    )
                except Exception:
                    logger.warning("[99co] No listing cards found on page %d", page_num)
                    break

                content = await page.content()
                listings = self._parse(content, intent)
                if not listings:
                    logger.info("[99co] No listings on page %d — stopping", page_num)
                    break

                all_listings.extend(listings)
                logger.info("[99co] Page %d: %d listings", page_num, len(listings))
                await asyncio.sleep(self.request_delay)

            except Exception as exc:
                logger.error("[99co] Page %d error: %s", page_num, exc)
                break

        return all_listings

    def _parse(self, html: str, intent: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        cards = (
            soup.select('[data-automation-id="listing-card"]')
            or soup.select('[class*="ListingCard"]')
            or soup.select('[class*="listing-card"]')
            or soup.select('[data-testid="listing-card"]')
        )
        results = []
        for card in cards:
            try:
                listing = self._parse_card(card, intent)
                if listing:
                    results.append(listing)
            except Exception as exc:
                logger.debug("[99co] Card parse error: %s", exc)
        return results

    def _parse_card(self, card, intent: str) -> dict | None:
        # Title
        title_el = (
            card.select_one('[data-automation-id="listing-title"]')
            or card.select_one('[class*="title"]')
            or card.select_one("h2, h3")
        )
        title = clean_text(title_el.get_text()) if title_el else None
        if not title:
            return None

        # URL + external ID
        link_el = card.select_one("a[href]")
        href = link_el.get("href", "") if link_el else ""
        listing_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        id_match = re.search(r"-(\d+)(?:\?|$|/)", href)
        external_id = id_match.group(1) if id_match else None

        # Price
        price_el = (
            card.select_one('[data-automation-id="listing-price"]')
            or card.select_one('[class*="price"]')
        )
        asking_price = parse_price(price_el.get_text() if price_el else None)

        # Address
        addr_el = (
            card.select_one('[data-automation-id="listing-address"]')
            or card.select_one('[class*="address"], [class*="location"]')
        )
        address = clean_text(addr_el.get_text()) if addr_el else None

        # Beds / baths / size
        bedrooms = self._extract_number(card, ["bed", "Bed"])
        bathrooms = self._extract_number(card, ["bath", "Bath"])
        size_el = (
            card.select_one('[data-automation-id="listing-floorarea"]')
            or card.select_one('[class*="size"], [class*="area"]')
        )
        floor_size = parse_floor_size(size_el.get_text() if size_el else None)
        psf = round(asking_price / floor_size, 2) if asking_price and floor_size else None

        prop_type = self._detect_type(title, address or "")

        # District from address text
        district = None
        d_match = re.search(
            r"\bD(\d{1,2})\b|[Dd]istrict\s+(\d{1,2})",
            (address or "") + " " + title,
        )
        if d_match:
            district = int(d_match.group(1) or d_match.group(2))

        # Tenure
        tenure = None
        card_text = card.get_text().lower()
        if "freehold" in card_text:
            tenure = "freehold"
        elif "999" in card_text:
            tenure = "999-year"
        elif "99" in card_text or "leasehold" in card_text:
            tenure = "99-year"

        return {
            "source": self.source,
            "source_url": listing_url,
            "external_id": external_id,
            "title": title,
            "property_type": prop_type,
            "intent": intent,
            "address": address,
            "district": district,
            "asking_price": asking_price,
            "floor_size": floor_size,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "psf": psf,
            "tenure": tenure,
            "description": "Listed on 99.co.",
        }

    def _extract_number(self, card, keywords: list[str]) -> int | None:
        text = card.get_text(" ", strip=True)
        for kw in keywords:
            m = re.search(rf"(\d+)\s*{kw}|{kw}[:\s]*(\d+)", text, re.IGNORECASE)
            if m:
                return int(m.group(1) or m.group(2))
        return None

    def _detect_type(self, title: str, address: str) -> str:
        combined = (title + " " + address).lower()
        if any(k in combined for k in ["hdb", "bto", "flat"]):
            return "hdb"
        if any(k in combined for k in ["landed", "terrace", "semi-d", "bungalow", "villa"]):
            return "landed"
        if any(k in combined for k in ["shophouse", "commercial", "office", "retail"]):
            return "commercial"
        return "condo"
