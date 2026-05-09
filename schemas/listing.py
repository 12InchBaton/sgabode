from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ListingCreate(BaseModel):
    title: str
    description: Optional[str] = None
    property_type: str
    intent: str  # buy | rent
    address: Optional[str] = None
    postal_code: Optional[str] = None
    district: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    asking_price: Optional[float] = None
    floor_size: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    floor_level: Optional[int] = None
    total_floors: Optional[int] = None
    build_year: Optional[int] = None
    tenure: Optional[str] = None
    nearest_mrt: Optional[str] = None
    mrt_distance: Optional[int] = None
    unit_features: Optional[list[str]] = None
    facilities: Optional[list[str]] = None
    furnishing: Optional[str] = None
    source: Optional[str] = "manual"
    source_url: Optional[str] = None
    external_id: Optional[str] = None
    submitted_by: Optional[int] = None  # agent_id


class ListingOut(BaseModel):
    id: int
    title: Optional[str]
    property_type: Optional[str]
    intent: Optional[str]
    address: Optional[str]
    district: Optional[int]
    asking_price: Optional[float]
    floor_size: Optional[float]
    bedrooms: Optional[int]
    bathrooms: Optional[int]
    psf: Optional[float]
    status: Optional[str]
    ai_summary: Optional[str]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ListingMediaOut(BaseModel):
    id: int
    listing_id: int
    media_type: str
    url: str
    display_order: int

    model_config = {"from_attributes": True}
