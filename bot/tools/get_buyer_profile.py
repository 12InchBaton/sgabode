import json

from database import AsyncSessionLocal
from services.buyer_service import get_active_preference, get_buyer_by_telegram_id

TOOL_DEF = {
    "name": "get_buyer_profile",
    "description": "Retrieve the buyer's current saved profile and preferences.",
    "input_schema": {"type": "object", "properties": {}},
}


async def execute(inputs: dict, telegram_id: int) -> str:
    async with AsyncSessionLocal() as db:
        buyer = await get_buyer_by_telegram_id(db, telegram_id)
        if not buyer:
            return "No profile found — user has not registered yet."
        pref = await get_active_preference(db, buyer.id)
        profile: dict = {"name": buyer.name, "whatsapp_number": buyer.whatsapp_number}
        if pref:
            profile["preferences"] = {
                "intent": pref.intent,
                "property_types": pref.property_types,
                "price_min": pref.price_min,
                "price_max": pref.price_max,
                "bedrooms": pref.bedrooms,
                "bathrooms": pref.bathrooms,
                "districts": pref.districts,
                "mrt_distance_max": pref.mrt_distance_max,
                "furnishing": pref.furnishing,
            }
        else:
            profile["preferences"] = None
    return json.dumps(profile, default=str)
