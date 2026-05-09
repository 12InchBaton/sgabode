"""Viewing request endpoints."""

from fastapi import APIRouter, HTTPException

from deps import DbSession
from models import Match, ViewingRequest
from schemas.viewing import ViewingCreate, ViewingOut, ViewingStatusUpdate
from sqlalchemy import select

router = APIRouter(prefix="/viewing-requests", tags=["viewing"])

_VALID_STATUSES = {"pending", "confirmed", "cancelled", "completed"}


@router.post("/", response_model=ViewingOut, status_code=201)
async def create_viewing_request(payload: ViewingCreate, db: DbSession):
    match_result = await db.execute(select(Match).where(Match.id == payload.match_id))
    match = match_result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    vr = ViewingRequest(**payload.model_dump(exclude_none=True))
    db.add(vr)
    match.viewing_requested = True
    await db.commit()
    await db.refresh(vr)
    return vr


@router.get("/{request_id}", response_model=ViewingOut)
async def get_viewing_request(request_id: int, db: DbSession):
    result = await db.execute(select(ViewingRequest).where(ViewingRequest.id == request_id))
    vr = result.scalar_one_or_none()
    if not vr:
        raise HTTPException(status_code=404, detail="Viewing request not found")
    return vr


@router.patch("/{request_id}", response_model=ViewingOut)
async def update_viewing_status(request_id: int, payload: ViewingStatusUpdate, db: DbSession):
    if payload.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {_VALID_STATUSES}")
    result = await db.execute(select(ViewingRequest).where(ViewingRequest.id == request_id))
    vr = result.scalar_one_or_none()
    if not vr:
        raise HTTPException(status_code=404, detail="Viewing request not found")
    vr.status = payload.status
    await db.commit()
    await db.refresh(vr)
    return vr
