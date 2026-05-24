"""
Price trend tool — queries the district_price_trends table populated from
historical HDB resale transactions. Gives buyers a realistic price benchmark
before they look at active listings.
"""

from database import AsyncSessionLocal
from models import DistrictPriceTrend
from sqlalchemy import select

TOOL_DEF = {
    "name": "get_price_trends",
    "description": (
        "Get historical HDB resale price trends for a specific town and flat type. "
        "Use this when the user asks about price ranges, market rates, or 'how much do X-room HDBs cost in Y'. "
        "Returns median, min, and max prices based on recent transactions. "
        "Available towns: Ang Mo Kio, Bedok, Bishan, Bukit Batok, Bukit Merah, Bukit Panjang, "
        "Bukit Timah, Central Area, Choa Chu Kang, Clementi, Geylang, Hougang, Jurong East, "
        "Jurong West, Kallang/Whampoa, Marine Parade, Pasir Ris, Punggol, Queenstown, "
        "Sembawang, Sengkang, Serangoon, Tampines, Toa Payoh, Woodlands, Yishun."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "town": {
                "type": "string",
                "description": "HDB town name in uppercase, e.g. 'BISHAN', 'ANG MO KIO', 'TOA PAYOH'",
            },
            "flat_type": {
                "type": "string",
                "description": "Flat type, e.g. '3 ROOM', '4 ROOM', '5 ROOM', 'EXECUTIVE'",
            },
        },
        "required": ["town"],
    },
}


async def execute(inputs: dict, telegram_id: int) -> str:
    town = inputs.get("town", "").upper().strip()
    flat_type = inputs.get("flat_type", "").upper().strip() if inputs.get("flat_type") else None

    async with AsyncSessionLocal() as db:
        q = select(DistrictPriceTrend).where(DistrictPriceTrend.town == town)
        if flat_type:
            q = q.where(DistrictPriceTrend.flat_type == flat_type)
        q = q.order_by(DistrictPriceTrend.flat_type)
        result = await db.execute(q)
        rows = result.scalars().all()

    if not rows:
        return (
            f"No price trend data for {town}"
            + (f" ({flat_type})" if flat_type else "")
            + ". Data may not have been scraped yet — try running the HDB trend scraper."
        )

    lines = [f"HDB resale price trends in {town.title()}:"]
    for row in rows:
        period = f"{row.period_start} to {row.period_end}" if row.period_start else "recent"
        lines.append(
            f"• {row.flat_type}: median SGD {row.median_price:,.0f} "
            f"(SGD {row.median_psf:,.0f} psf) | "
            f"range SGD {row.min_price:,.0f}–{row.max_price:,.0f} | "
            f"{row.sample_size} transactions ({period})"
        )

    return "\n".join(lines)
