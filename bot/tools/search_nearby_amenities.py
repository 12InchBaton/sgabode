from database import AsyncSessionLocal
from models import Listing
from services.nearby import get_nearby
from sqlalchemy import select

TOOL_DEF = {
    "name": "search_nearby_amenities",
    "description": (
        "Search for nearby amenities around a specific property listing. "
        "Use this when the user asks what's nearby a listing — e.g. 'is there a coffee shop near listing 5?', "
        "'are there dog parks nearby?', 'how far is the nearest mall?', "
        "'what schools are within walking distance?'. "
        "Always call get_recommendations or search_listings first to know the listing ID."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "listing_id": {
                "type": "integer",
                "description": "The listing ID to search around",
            },
            "amenity_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of amenity types to search for. Examples: "
                    "'cafe', 'coffee shop', 'hawker centre', 'mall', 'shopping mall', "
                    "'supermarket', 'park', 'dog park', 'playground', 'gym', "
                    "'mrt', 'bus stop', 'school', 'childcare', 'clinic', 'hospital', 'pharmacy'"
                ),
            },
            "radius_metres": {
                "type": "integer",
                "description": "Search radius in metres. Default 800 (10-min walk). Max 2000.",
                "default": 800,
            },
        },
        "required": ["listing_id", "amenity_types"],
    },
}


async def execute(inputs: dict, telegram_id: int) -> str:
    listing_id = inputs.get("listing_id")
    amenity_types = inputs.get("amenity_types", [])
    radius = inputs.get("radius_metres", 800)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Listing).where(Listing.id == listing_id))
        listing = result.scalar_one_or_none()

    if not listing:
        return f"Listing {listing_id} not found."

    return await get_nearby(
        address=listing.address or "",
        postal=listing.postal_code,
        lat=listing.latitude,
        lng=listing.longitude,
        amenity_types=amenity_types,
        radius_metres=radius,
    )
