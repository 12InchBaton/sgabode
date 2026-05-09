"""Buyer registration and preference management endpoints."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from deps import DbSession
from models import Buyer, Match, Listing
from schemas.buyer import BuyerCreate, BuyerOut, PreferenceIn, PreferenceOut
from services import buyer_service

router = APIRouter(prefix="/buyers", tags=["buyers"])


@router.post("/", response_model=BuyerOut, status_code=status.HTTP_201_CREATED)
async def register_buyer(payload: BuyerCreate, db: DbSession):
    buyer = await buyer_service.upsert_buyer(
        db,
        telegram_id=payload.telegram_id,
        name=payload.name,
        whatsapp_number=payload.whatsapp_number,
    )
    await db.commit()
    await db.refresh(buyer)
    return buyer


@router.get("/{buyer_id}", response_model=BuyerOut)
async def get_buyer(buyer_id: int, db: DbSession):
    result = await db.execute(select(Buyer).where(Buyer.id == buyer_id))
    buyer = result.scalar_one_or_none()
    if not buyer:
        raise HTTPException(status_code=404, detail="Buyer not found")
    return buyer


@router.post("/{buyer_id}/preferences", response_model=PreferenceOut, status_code=201)
async def save_preferences(buyer_id: int, payload: PreferenceIn, db: DbSession):
    result = await db.execute(select(Buyer).where(Buyer.id == buyer_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Buyer not found")

    pref = await buyer_service.replace_preferences(
        db, buyer_id, **payload.model_dump(exclude_none=True)
    )
    await db.commit()
    await db.refresh(pref)
    return pref


@router.patch("/{buyer_id}/preferences", response_model=PreferenceOut)
async def update_preferences(buyer_id: int, payload: PreferenceIn, db: DbSession):
    try:
        pref = await buyer_service.patch_preferences(
            db, buyer_id, **payload.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    await db.refresh(pref)
    return pref


@router.get("/{buyer_id}/preferences", response_model=PreferenceOut)
async def get_preferences(buyer_id: int, db: DbSession):
    pref = await buyer_service.get_active_preference(db, buyer_id)
    if not pref:
        raise HTTPException(status_code=404, detail="No active preference found")
    return pref


@router.get("/{buyer_id}/matches")
async def get_matches(buyer_id: int, db: DbSession):
    result = await db.execute(
        select(Match, Listing)
        .join(Listing, Listing.id == Match.listing_id)
        .where(Match.buyer_id == buyer_id)
        .order_by(Match.sent_at.desc())
        .limit(50)
    )
    return [
        {
            "match_id": m.id,
            "listing_id": l.id,
            "title": l.title,
            "asking_price": l.asking_price,
            "district": l.district,
            "interested": m.interested,
            "viewing_requested": m.viewing_requested,
            "sent_at": m.sent_at,
        }
        for m, l in result.all()
    ]
