from database import AsyncSessionLocal
from models import Listing
from sqlalchemy import select

TOOL_DEF = {
    "name": "search_listings",
    "description": (
        "Search active property listings with optional filters. "
        "Use when the user asks to browse or search with specific criteria "
        "that may differ from their saved preferences."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["buy", "rent"]},
            "property_type": {
                "type": "string",
                "enum": ["hdb", "condo", "landed", "commercial"],
            },
            "max_price": {"type": "number"},
            "min_bedrooms": {"type": "integer"},
            "district": {"type": "integer"},
            "limit": {"type": "integer", "default": 5},
        },
    },
}


async def execute(inputs: dict, telegram_id: int) -> str:
    async with AsyncSessionLocal() as db:
        q = select(Listing).where(Listing.status == "active")
        if inputs.get("intent"):
            q = q.where(Listing.intent == inputs["intent"])
        if inputs.get("property_type"):
            q = q.where(Listing.property_type == inputs["property_type"])
        if inputs.get("max_price"):
            q = q.where(Listing.asking_price <= inputs["max_price"])
        if inputs.get("min_bedrooms"):
            q = q.where(Listing.bedrooms >= inputs["min_bedrooms"])
        if inputs.get("district"):
            q = q.where(Listing.district == inputs["district"])
        q = q.limit(inputs.get("limit", 5))
        result = await db.execute(q)
        listings = result.scalars().all()

    if not listings:
        return "No active listings found for those criteria."

    lines = [f"Found {len(listings)} listing(s):"]
    for lst in listings:
        price = f"SGD {lst.asking_price:,.0f}" if lst.asking_price else "POA"
        br = f"{lst.bedrooms}BR" if lst.bedrooms is not None else "?"
        sz = f"{lst.floor_size:,.0f} sqft" if lst.floor_size else "? sqft"
        lines.append(
            f"• {lst.title or 'Listing'} — {price} · "
            f"{br} · {sz} · D{lst.district or '?'}"
        )
    return "\n".join(lines)
