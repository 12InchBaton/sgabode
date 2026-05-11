"""
SGAbode FastAPI application entry point.

To add new route domains:   → routes/registry.py
To add new event listeners: → services/registry.py
Neither file changes here.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routes.registry import ROUTERS
from services.registry import register_all as register_service_listeners
from services.scrapers.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)

app = FastAPI(
    title="SGAbode API",
    description="Singapore property discovery platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in ROUTERS:
    app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    register_service_listeners()
    start_scheduler()


@app.on_event("shutdown")
async def shutdown() -> None:
    stop_scheduler()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "SGAbode API"}
