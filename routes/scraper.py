"""
Scraper management endpoints — manually trigger scrapes and view status.

POST /scraper/run              — queue all scrapers in background
POST /scraper/run/{source}     — queue one scraper in background
POST /scraper/run/{source}/now — run one scraper inline, return results immediately
GET  /scraper/schedule         — view scheduler jobs and next run times
GET  /scraper/sources          — list all registered scrapers
"""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from deps import AdminKey
from services.scrapers.runner import ALL_SCRAPERS, run_all_scrapers, run_scraper
from services.scrapers.scheduler import get_scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scraper", tags=["scraper"])

# Build source → scraper class map for lookup
_SCRAPER_MAP = {cls().source: cls for cls in ALL_SCRAPERS}


@router.post("/run")
async def trigger_all(background_tasks: BackgroundTasks, _: AdminKey):
    """Queue a full scrape of all sources in the background. Requires X-Admin-Key header."""
    background_tasks.add_task(run_all_scrapers)
    return {
        "status": "queued",
        "sources": list(_SCRAPER_MAP.keys()),
        "message": "Scrape started in background. Check logs for progress.",
    }


@router.post("/run/{source}")
async def trigger_one(source: str, background_tasks: BackgroundTasks, _: AdminKey):
    """Queue a scrape for a single source in the background. Requires X-Admin-Key header."""
    scraper_class = _SCRAPER_MAP.get(source)
    if not scraper_class:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown source '{source}'. Available: {list(_SCRAPER_MAP.keys())}",
        )
    background_tasks.add_task(run_scraper, scraper_class)
    return {"status": "queued", "source": source}


@router.post("/run/{source}/now")
async def trigger_one_inline(source: str, _: AdminKey):
    """Run a single scraper inline and return results. Requires X-Admin-Key header."""
    scraper_class = _SCRAPER_MAP.get(source)
    if not scraper_class:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown source '{source}'. Available: {list(_SCRAPER_MAP.keys())}",
        )
    logger.info("Running %s scraper inline...", source)
    summary = await run_scraper(scraper_class)
    return {"status": "completed", "result": summary}


@router.get("/schedule")
async def get_schedule(_: AdminKey):
    """Show all scheduled jobs and their next run times. Requires X-Admin-Key header."""
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return {
        "scheduler_running": scheduler.running,
        "timezone": "Asia/Singapore",
        "jobs": jobs,
    }


@router.get("/sources")
async def list_sources(_: AdminKey):
    """List all registered scraper sources. Requires X-Admin-Key header."""
    return {
        "sources": [
            {
                "source": cls().source,
                "urls": cls().start_urls,
            }
            for cls in ALL_SCRAPERS
        ]
    }
