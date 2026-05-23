from database import AsyncSessionLocal
from services.buyer_service import get_active_preference, get_buyer_by_telegram_id
from services.ranking import get_ranked_listings

TOOL_DEF = {
    "name": "get_recommendations",
    "description": (
        "Get top property listings ranked for this buyer based on their saved preferences. "
        "Use this when the user asks for recommendations or 'show me what matches'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of results to return (1–10). Default 5.",
                "default": 5,
            }
        },
    },
}


async def execute(inputs: dict, telegram_id: int) -> str:
    limit = min(max(inputs.get("limit", 5), 1), 10)
    async with AsyncSessionLocal() as db:
        buyer = await get_buyer_by_telegram_id(db, telegram_id)
        if not buyer:
            return "No profile found. Ask the user to share their preferences first."
        pref = await get_active_preference(db, buyer.id)
        if not pref:
            return "No preferences saved yet. Collect preferences first."
        ranked = await get_ranked_listings(db, pref, limit=limit)

    if not ranked:
        return "No listings match the current preferences."

    lines = [f"Top {len(ranked)} recommendations:"]
    for i, (listing, score) in enumerate(ranked, 1):
        price = f"SGD {listing.asking_price:,.0f}" if listing.asking_price else "POA"
        br = f"{listing.bedrooms}BR" if listing.bedrooms is not None else "?"
        sz = f"{listing.floor_size:,.0f} sqft" if listing.floor_size else "? sqft"
        lines.append(
            f"{i}. {listing.title or 'Listing'} — {price} · "
            f"{br} · {sz} · D{listing.district or '?'} · Score {score:.0f}/100"
        )
    return "\n".join(lines)
