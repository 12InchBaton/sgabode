"""
APScheduler setup — runs all scrapers on a cron schedule.

Default schedule:
  - Full scrape every 6 hours
  - Status-only refresh every 2 hours (checks if active listings are still live)

Started from main.py startup event.
Stopped on app shutdown.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.scrapers.runner import run_all_scrapers

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="Asia/Singapore")


def start_scheduler() -> None:
    """Register jobs and start the scheduler. Called once at app startup."""

    _scheduler.add_job(
        run_all_scrapers,
        trigger=IntervalTrigger(hours=6),
        id="full_scrape",
        name="Full property scrape (all sources)",
        replace_existing=True,
        max_instances=1,  # Never run two scrapes at once
    )

    _scheduler.start()
    logger.info("Scraper scheduler started — full scrape every 6 hours (Asia/Singapore).")


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scraper scheduler stopped.")


def get_scheduler() -> AsyncIOScheduler:
    return _scheduler
