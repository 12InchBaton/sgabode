"""
Buyer session service — persists AI conversation history to the database.

This allows the bot to remember the conversation across restarts and redeployments.
Each buyer has one session row identified by telegram_id.

Public surface:
    load_history(telegram_id)              -> list[dict]
    save_history(telegram_id, messages)    -> None
    clear_history(telegram_id)             -> None
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import BuyerSession

logger = logging.getLogger(__name__)

MAX_STORED_MESSAGES = 30  # cap stored history to keep DB rows small


async def load_history(telegram_id: int) -> list[dict]:
    """Load the stored conversation history for a user. Returns [] if none."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BuyerSession).where(BuyerSession.telegram_id == telegram_id)
        )
        session = result.scalar_one_or_none()
        if not session or not session.history:
            return []
        try:
            return json.loads(session.history)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt session history for telegram_id=%d — resetting.", telegram_id)
            return []


async def save_history(telegram_id: int, messages: list[dict]) -> None:
    """Persist conversation history for a user, trimmed to MAX_STORED_MESSAGES."""
    # Keep only the tail to avoid unbounded growth
    trimmed = messages[-MAX_STORED_MESSAGES:] if len(messages) > MAX_STORED_MESSAGES else messages
    try:
        serialized = json.dumps(trimmed, default=str)
    except (TypeError, ValueError) as exc:
        logger.warning("Could not serialize history for telegram_id=%d: %s", telegram_id, exc)
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BuyerSession).where(BuyerSession.telegram_id == telegram_id)
        )
        session = result.scalar_one_or_none()
        if session:
            session.history = serialized
        else:
            db.add(BuyerSession(telegram_id=telegram_id, history=serialized))
        await db.commit()


async def clear_history(telegram_id: int) -> None:
    """Clear the conversation history for a user (called on /start)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BuyerSession).where(BuyerSession.telegram_id == telegram_id)
        )
        session = result.scalar_one_or_none()
        if session:
            session.history = "[]"
            await db.commit()
