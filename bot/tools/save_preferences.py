import json

from database import AsyncSessionLocal
from services.buyer_service import (
    get_active_preference,
    get_buyer_by_telegram_id,
    patch_preferences,
    replace_preferences,
    upsert_buyer,
)

TOOL_DEF = {
    "name": "save_preferences",
    "description": (
        "Save or update the buyer's property search preferences. "
        "Only include fields the user has explicitly mentioned. "
        "Can be called multiple times as more information is collected."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["buy", "rent"]},
            "property_types": {
                "type": "array",
                "items": {"type": "string", "enum": ["hdb", "condo", "landed", "commercial"]},
            },
            "price_min": {"type": "number", "description": "Minimum price in SGD"},
            "price_max": {"type": "number", "description": "Maximum price in SGD"},
            "bedrooms": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Acceptable bedroom counts, e.g. [2, 3]",
            },
            "bathrooms": {"type": "array", "items": {"type": "integer"}},
            "districts": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1, "maximum": 28},
            },
            "mrt_distance_max": {
                "type": "integer",
                "description": "Max walking distance from nearest MRT in metres",
            },
            "furnishing": {
                "type": "array",
                "items": {"type": "string", "enum": ["unfurnished", "partial", "fully"]},
            },
        },
    },
}


async def execute(inputs: dict, telegram_id: int) -> str:
    async with AsyncSessionLocal() as db:
        buyer = await get_buyer_by_telegram_id(db, telegram_id)
        if not buyer:
            buyer = await upsert_buyer(db, telegram_id=telegram_id)
            await db.flush()
        existing = await get_active_preference(db, buyer.id)
        if existing:
            await patch_preferences(db, buyer.id, **inputs)
        else:
            await replace_preferences(db, buyer.id, **inputs, is_active=True)
        await db.commit()
    return f"Preferences saved: {json.dumps(inputs)}"
