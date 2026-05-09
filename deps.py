"""
Shared FastAPI dependency aliases.

Import from here instead of repeating Depends(get_db) in every route file.

Example:
    from deps import DbSession

    @router.get("/")
    async def my_route(db: DbSession):
        ...
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db

# Typed alias for an injected async DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]
