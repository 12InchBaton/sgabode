"""
Scraper management endpoints — manually trigger scrapes and view status.

POST /scraper/run              — run all scrapers now
POST /scraper/run/{source}     — run one scraper by source name
GET  /scraper/schedule         — view scheduler jobs and next run times
"""

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException

from services.scrapers.runner import ALL_SCRAPERS, run_all_scrapers, run_scraper
from services.scrapers.scheduler import get_scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scraper", tags=["scraper"])

# Build source → scraper class map for lookup
_SCRAPER_MAP = {cls().source: cls for cls in ALL_SCRAPERS}


@router.post("/run")
async def trigger_all(background_tasks: BackgroundTasks):
    """Trigger a full scrape of all sources in the background."""
    background_tasks.add_task(run_all_scrapers)
    return {
        "status": "queued",
        "sources": list(_SCRAPER_MAP.keys()),
        "message": "Scrape started in background. Check logs for progress.",
    }


@router.post("/run/{source}")
async def trigger_one(source: str, background_tasks: BackgroundTasks):
    """Trigger a scrape for a single source (e.g. 'hdb' or 'propertyguru')."""
    scraper_class = _SCRAPER_MAP.get(source)
    if not scraper_class:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown source '{source}'. Available: {list(_SCRAPER_MAP.keys())}",
        )
    background_tasks.add_task(run_scraper, scraper_class)
    return {"status": "queued", "source": source}


@router.get("/schedule")
async def get_schedule():
    """Show all scheduled jobs and their next run times."""
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
async def list_sources():
    """List all registered scraper sources."""
    return {
        "sources": [
            {
                "source": cls().source,
                "urls": cls().start_urls,
            }
            for cls in ALL_SCRAPERS
        ]
    }
