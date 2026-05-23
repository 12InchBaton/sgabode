"""
Shared FastAPI dependency aliases.

Import from here instead of repeating Depends(get_db) in every route file.

Example:
    from deps import DbSession, AdminKey

    @router.get("/")
    async def my_route(db: DbSession):
        ...

    @router.post("/admin/action")
    async def admin_action(db: DbSession, _: AdminKey):
        ...
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db

# Typed alias for an injected async DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]

# ── Admin API key auth ────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def _require_admin_key(key: str = Security(_api_key_header)) -> str:
    """
    Dependency that enforces admin API key auth.
    Pass key in the X-Admin-Key header.
    If ADMIN_API_KEY is not configured, access is denied (fail-secure).
    """
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key not configured on server.",
        )
    if key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin API key. Pass it in X-Admin-Key header.",
        )
    return key


AdminKey = Annotated[str, Depends(_require_admin_key)]
