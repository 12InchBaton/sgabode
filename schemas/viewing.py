from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ViewingCreate(BaseModel):
    match_id: int
    buyer_id: int
    listing_id: int
    agent_id: Optional[int] = None
    preferred_date: Optional[datetime] = None
    notes: Optional[str] = None


class ViewingStatusUpdate(BaseModel):
    status: str  # pending | confirmed | cancelled | completed


class ViewingOut(BaseModel):
    id: int
    match_id: int
    buyer_id: int
    listing_id: int
    agent_id: Optional[int]
    status: str
    preferred_date: Optional[datetime]
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
