from database import AsyncSessionLocal
from services.buyer_service import upsert_buyer

TOOL_DEF = {
    "name": "save_profile",
    "description": "Save the buyer's name and optional WhatsApp number. Call this as soon as you learn the user's name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Buyer's full name"},
            "whatsapp_number": {
                "type": "string",
                "description": "WhatsApp number with country code, e.g. +6591234567. Optional.",
            },
        },
        "required": ["name"],
    },
}


async def execute(inputs: dict, telegram_id: int) -> str:
    async with AsyncSessionLocal() as db:
        await upsert_buyer(
            db,
            telegram_id=telegram_id,
            name=inputs.get("name"),
            whatsapp_number=inputs.get("whatsapp_number"),
        )
        await db.commit()
    return f"Profile saved: name={inputs.get('name')!r}"
