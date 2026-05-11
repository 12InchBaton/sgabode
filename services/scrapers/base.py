"""Abstract base scraper using Playwright for JS-rendered sites."""

import asyncio
import logging
from abc import ABC, abstractmethod

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

logger = logging.getLogger(__name__)

# Realistic browser headers to reduce bot detection
_HEADERS = {
    "Accept-Language": "en-SG,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}


class BaseScraper(ABC):
    """
    Base class for all property scrapers.

    Subclasses implement:
        source        : str  — matches Listing.source column
        start_urls    : list[str]  — pages to scrape
        scrape_page() : async method that receives a Playwright Page and returns list[dict]

    Each dict must have at minimum: title, property_type, intent.
    All other Listing fields are optional but enrich matches.
    """

    source: str = "unknown"
    start_urls: list[str] = []
    # Seconds to wait between page loads — be respectful
    request_delay: float = 2.0

    @abstractmethod
    async def scrape_page(self, page: Page, url: str) -> list[dict]:
        """Scrape one URL and return a list of raw listing dicts."""
        ...

    async def run(self) -> list[dict]:
        """
        Launch browser, visit every start_url, collect all listings.
        Returns list of raw dicts ready for the runner to upsert.
        """
        all_listings: list[dict] = []

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context: BrowserContext = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                extra_http_headers=_HEADERS,
                viewport={"width": 1280, "height": 900},
            )
            # Mask webdriver flag
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            for url in self.start_urls:
                page: Page = await context.new_page()
                try:
                    logger.info("[%s] Scraping %s", self.source, url)
                    await page.goto(url, wait_until="networkidle", timeout=30_000)
                    await asyncio.sleep(self.request_delay)
                    listings = await self.scrape_page(page, url)
                    logger.info("[%s] Found %d listings at %s", self.source, len(listings), url)
                    all_listings.extend(listings)
                except Exception as exc:
                    logger.error("[%s] Failed to scrape %s: %s", self.source, url, exc)
                finally:
                    await page.close()
                await asyncio.sleep(self.request_delay)

            await browser.close()

        return all_listings
