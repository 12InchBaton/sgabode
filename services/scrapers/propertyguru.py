"""
PropertyGuru scraper — propertyguru.com.sg/property-for-sale

⚠️  PropertyGuru's Terms of Service restrict automated scraping.
    Use responsibly: low request rate, no mass data extraction.

Scrapes listing cards from the search results pages, following
pagination up to MAX_PAGES.
"""

import asyncio
import logging
import re

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

MAX_PAGES = 5  # Limit pages per run — increase carefully
BASE_URL = "https://www.propertyguru.com.sg"


class PropertyGuruScraper(BaseScraper):
    source = "propertyguru"
    start_urls = [
        f"{BASE_URL}/property-for-sale",
        f"{BASE_URL}/property-for-rent",
    ]
    request_delay = 3.0

    async def scrape_page(self, page: Page, url: str) -> list[dict]:
        intent = "rent" if "for-rent" in url else "buy"
        all_listings: list[dict] = []

        current_url = url
        for page_num in range(1, MAX_PAGES + 1):
            try:
                if page_num > 1:
                    # PropertyGuru pagination: ?page=N
                    paginated = f"{url}?page={page_num}" if "?" not in url else f"{url}&page={page_num}"
                    await page.goto(paginated, wait_until="networkidle", timeout=30_000)
                    await asyncio.sleep(self.request_delay)
                    current_url = paginated

                # Wait for listing cards to appear
                try:
                    await page.wait_for_selector(
                        '[data-listing-id], .listing-card, [class*="listing"]',
                        timeout=15_000,
                    )
                except Exception:
                    logger.warning("[propertyguru] No listing cards found on page %d", page_num)
                    break

                content = await page.content()
                listings = self._parse_listings(content, current_url, intent)

                if not listings:
                    logger.info("[propertyguru] No listings on page %d — stopping", page_num)
                    break

                all_listings.extend(listings)
                logger.info("[propertyguru] Page %d: %d listings", page_num, len(listings))
                await asyncio.sleep(self.request_delay)

            except Exception as exc:
                logger.error("[propertyguru] Page %d error: %s", page_num, exc)
                break

        return all_listings

    def _parse_listings(self, html: str, source_url: str, intent: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        # PropertyGuru listing cards carry data-listing-id attribute
        cards = (
            soup.select("[data-listing-id]")
            or soup.select(".listing-card")
            or soup.select("[class*='ListingCard']")
            or soup.select("li[class*='listing']")
        )

        for card in cards:
            try:
                listing = self._parse_card(card, source_url, intent)
                if listing:
                    results.append(listing)
            except Exception as exc:
                logger.debug("PropertyGuru card parse error: %s", exc)

        return results

    def _parse_card(self, card, source_url: str, intent: str) -> dict | None:
        # ── External ID ───────────────────────────────────────────────────────
        external_id = (
            card.get("data-listing-id")
            or card.get("data-id")
            or card.get("id", "").replace("listing-", "")
        )

        # ── URL ───────────────────────────────────────────────────────────────
        link_el = card.select_one("a[href*='/property-']") or card.select_one("a[href]")
        if link_el:
            href = link_el.get("href", "")
            listing_url = href if href.startswith("http") else f"{BASE_URL}{href}"
            if not external_id:
                id_match = re.search(r"-(\d+)(?:\?|$|/)", href)
                external_id = id_match.group(1) if id_match else None
        else:
            listing_url = source_url

        # ── Title ─────────────────────────────────────────────────────────────
        title_el = (
            card.select_one("h3")
            or card.select_one("h2")
            or card.select_one("[class*='title']")
            or card.select_one("[class*='name']")
        )
        title = clean_text(title_el.get_text()) if title_el else None
        if not title:
            return None

        # ── Price ─────────────────────────────────────────────────────────────
        price_el = (
            card.select_one("[class*='price']")
            or card.select_one("[data-price]")
        )
        price_text = price_el.get_text() if price_el else None
        if not price_text and price_el:
            price_text = price_el.get("data-price")
        asking_price = parse_price(price_text)

        # ── Address / location ────────────────────────────────────────────────
        addr_el = (
            card.select_one("[class*='address']")
            or card.select_one("[class*='location']")
            or card.select_one("[class*='district']")
        )
        address = clean_text(addr_el.get_text()) if addr_el else None

        # ── Beds / baths ──────────────────────────────────────────────────────
        bedrooms = self._extract_number(card, ["bed", "bedroom", "room"])
        bathrooms = self._extract_number(card, ["bath", "bathroom"])

        # ── Floor size ────────────────────────────────────────────────────────
        size_el = (
            card.select_one("[class*='size']")
            or card.select_one("[class*='sqft']")
            or card.select_one("[class*='floor-area']")
        )
        floor_size = parse_floor_size(size_el.get_text() if size_el else None)

        # PSF
        psf_el = card.select_one("[class*='psf']")
        psf = parse_price(psf_el.get_text() if psf_el else None)
        if not psf and asking_price and floor_size and floor_size > 0:
            psf = round(asking_price / floor_size, 2)

        # ── Property type ─────────────────────────────────────────────────────
        prop_type = self._detect_property_type(title, address or "")

        # ── District ──────────────────────────────────────────────────────────
        district = None
        # Try to extract district from address (e.g. "D10", "District 10")
        d_match = re.search(r"\bD(\d{1,2})\b|[Dd]istrict\s+(\d{1,2})", address or title or "")
        if d_match:
            district = int(d_match.group(1) or d_match.group(2))

        # ── Tenure ────────────────────────────────────────────────────────────
        tenure = None
        card_text = card.get_text().lower()
        if "freehold" in card_text:
            tenure = "freehold"
        elif "999" in card_text:
            tenure = "999-year"
        elif "99" in card_text or "leasehold" in card_text:
            tenure = "99-year"

        # ── Agent ─────────────────────────────────────────────────────────────
        agent_el = card.select_one("[class*='agent']")
        agent_name = clean_text(agent_el.get_text()) if agent_el else None

        return {
            "source": self.source,
            "source_url": listing_url,
            "external_id": str(external_id) if external_id else None,
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
            "description": f"Listed on PropertyGuru. Agent: {agent_name}" if agent_name else "Listed on PropertyGuru.",
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_number(self, card, keywords: list[str]) -> int | None:
        """Find a number adjacent to a bedroom/bathroom label."""
        text = card.get_text(" ", strip=True)
        for kw in keywords:
            pattern = rf"(\d+)\s*{kw}|{kw}[:\s]*(\d+)"
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                val = m.group(1) or m.group(2)
                return int(val)
        return None

    def _detect_property_type(self, title: str, address: str) -> str:
        combined = (title + " " + address).lower()
        if any(k in combined for k in ["hdb", " bto ", "flat"]):
            return "hdb"
        if any(k in combined for k in ["condo", "condominium", "apartment", "residences", "suites"]):
            return "condo"
        if any(k in combined for k in ["landed", "terrace", "semi-d", "bungalow", "villa", "townhouse"]):
            return "landed"
        if any(k in combined for k in ["shophouse", "commercial", "office", "retail"]):
            return "commercial"
        return "condo"  # default for private property on PropertyGuru
