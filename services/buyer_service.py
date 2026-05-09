"""
Buyer service — all buyer and preference business logic.

Used by both the REST API routes and the Telegram bot handlers
so the logic never has to be duplicated.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Buyer, BuyerPreference


async def get_buyer_by_telegram_id(db: AsyncSession, telegram_id: int) -> Buyer | None:
    result = await db.execute(select(Buyer).where(Buyer.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def upsert_buyer(
    db: AsyncSession,
    *,
    telegram_id: int,
    name: str | None = None,
    whatsapp_number: str | None = None,
) -> Buyer:
    """Create buyer if not exists, otherwise update mutable fields."""
    buyer = await get_buyer_by_telegram_id(db, telegram_id)
    if not buyer:
        buyer = Buyer(telegram_id=telegram_id, name=name, whatsapp_number=whatsapp_number)
        db.add(buyer)
        await db.flush()  # populate buyer.id without committing
    else:
        if name is not None:
            buyer.name = name
        if whatsapp_number is not None:
            buyer.whatsapp_number = whatsapp_number
    return buyer


async def get_active_preference(db: AsyncSession, buyer_id: int) -> BuyerPreference | None:
    result = await db.execute(
        select(BuyerPreference).where(
            BuyerPreference.buyer_id == buyer_id,
            BuyerPreference.is_active == True,
        )
    )
    return result.scalar_one_or_none()


async def replace_preferences(
    db: AsyncSession,
    buyer_id: int,
    **fields,
) -> BuyerPreference:
    """
    Deactivate all existing preferences for buyer and create a fresh one.
    Pass preference fields as kwargs.
    """
    old = await db.execute(
        select(BuyerPreference).where(
            BuyerPreference.buyer_id == buyer_id,
            BuyerPreference.is_active == True,
        )
    )
    for pref in old.scalars():
        pref.is_active = False

    new_pref = BuyerPreference(buyer_id=buyer_id, **fields)
    db.add(new_pref)
    await db.flush()
    return new_pref


async def patch_preferences(
    db: AsyncSession,
    buyer_id: int,
    **fields,
) -> BuyerPreference:
    """Update specific fields on the active preference row."""
    pref = await get_active_preference(db, buyer_id)
    if not pref:
        raise ValueError(f"No active preference for buyer_id={buyer_id}")
    for field, value in fields.items():
        if hasattr(pref, field):
            setattr(pref, field, value)
    return pref
