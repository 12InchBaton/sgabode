"""Listing submission, retrieval, and matching trigger endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from deps import DbSession
from events import bus
from models import Listing, ListingMedia
from schemas.listing import ListingCreate, ListingMediaOut, ListingOut
from services import storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/listings", tags=["listings"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_psf(asking_price: Optional[float], floor_size: Optional[float]) -> Optional[float]:
    if asking_price and floor_size and floor_size > 0:
        return round(asking_price / floor_size, 2)
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=ListingOut, status_code=status.HTTP_201_CREATED)
async def create_listing(
    payload: ListingCreate,
    background_tasks: BackgroundTasks,
    db: DbSession,
):
    data = payload.model_dump(exclude_none=True)
    data["psf"] = _compute_psf(data.get("asking_price"), data.get("floor_size"))

    listing = Listing(**data)
    db.add(listing)
    await db.commit()
    await db.refresh(listing)

    # Emit event — services/registry.py decides what happens next.
    # To add a new side effect (e.g. Slack alert, CRM sync), subscribe to
    # 'listing.created' in services/registry.py without touching this file.
    background_tasks.add_task(bus.emit, "listing.created", listing_id=listing.id)
    return listing


@router.post("/{listing_id}/media", response_model=ListingMediaOut, status_code=201)
async def upload_media(
    listing_id: int,
    background_tasks: BackgroundTasks,
    db: DbSession,
    media_type: str = Form("image"),  # image | floor_plan | video | virtual_tour
    display_order: int = Form(0),
    file: UploadFile = File(...),
):
    result = await db.execute(select(Listing).where(Listing.id == listing_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Listing not found")

    file_data = await file.read()
    url = await storage.upload_file(file_data, file.filename or "upload", folder="listings")

    media = ListingMedia(
        listing_id=listing_id,
        media_type=media_type,
        url=url,
        display_order=display_order,
    )
    db.add(media)
    await db.commit()
    await db.refresh(media)

    background_tasks.add_task(
        bus.emit,
        "listing.media_uploaded",
        listing_id=listing_id,
        media_id=media.id,
        media_type=media_type,
    )
    return media


@router.get("/", response_model=list[ListingOut])
async def list_listings(
    db: DbSession,
    intent: Optional[str] = None,
    property_type: Optional[str] = None,
    district: Optional[int] = None,
    listing_status: Optional[str] = "active",
    skip: int = 0,
    limit: int = 20,
):
    query = select(Listing)
    if intent:
        query = query.where(Listing.intent == intent)
    if property_type:
        query = query.where(Listing.property_type == property_type)
    if district:
        query = query.where(Listing.district == district)
    if listing_status:
        query = query.where(Listing.status == listing_status)
    query = query.order_by(Listing.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{listing_id}", response_model=ListingOut)
async def get_listing(listing_id: int, db: DbSession):
    result = await db.execute(
        select(Listing)
        .options(selectinload(Listing.media))
        .where(Listing.id == listing_id)
    )
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


@router.post("/{listing_id}/trigger-match")
async def trigger_match(
    listing_id: int,
    background_tasks: BackgroundTasks,
    db: DbSession,
):
    """Manually re-trigger the matching engine for a listing."""
    result = await db.execute(select(Listing).where(Listing.id == listing_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Listing not found")
    background_tasks.add_task(bus.emit, "listing.created", listing_id=listing_id)
    return {"status": "matching queued", "listing_id": listing_id}


@router.patch("/{listing_id}/status")
async def update_listing_status(listing_id: int, new_status: str, db: DbSession):
    valid = {"active", "under_offer", "sold", "rented", "inactive"}
    if new_status not in valid:
        raise HTTPException(status_code=400, detail=f"Status must be one of {valid}")
    result = await db.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing.status = new_status
    await db.commit()
    return {"id": listing_id, "status": new_status}
