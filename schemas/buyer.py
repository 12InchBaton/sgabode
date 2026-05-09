from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class BuyerCreate(BaseModel):
    telegram_id: int
    name: Optional[str] = None
    whatsapp_number: Optional[str] = None


class BuyerOut(BaseModel):
    id: int
    telegram_id: int
    name: Optional[str]
    whatsapp_number: Optional[str]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PreferenceIn(BaseModel):
    intent: Optional[str] = None
    property_types: Optional[list[str]] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    floor_size_min: Optional[float] = None
    floor_size_max: Optional[float] = None
    bedrooms: Optional[list[int]] = None
    bathrooms: Optional[list[int]] = None
    districts: Optional[list[int]] = None
    mrt_distance_max: Optional[int] = None
    tenure: Optional[list[str]] = None
    floor_level_min: Optional[int] = None
    floor_level_max: Optional[int] = None
    build_year_min: Optional[int] = None
    psf_min: Optional[float] = None
    psf_max: Optional[float] = None
    unit_features: Optional[list[str]] = None
    facilities: Optional[list[str]] = None
    furnishing: Optional[list[str]] = None
    keywords: Optional[str] = None
    is_active: Optional[bool] = True


class PreferenceOut(PreferenceIn):
    id: int
    buyer_id: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}
