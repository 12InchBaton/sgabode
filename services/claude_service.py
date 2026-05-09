"""
Claude API integration.

Public surface:
    generate_listing_summary(listing_dict)  → (summary, layout_notes)
    analyze_floor_plan(image_url)           → layout_notes
    parse_preference_update(message, prefs) → dict of changed fields
    generate_unit_card_caption(listing_dict, match_id) → Markdown string

Event listeners (wired in services/registry.py):
    on_listing_created_ai(**payload)
    on_floor_plan_uploaded(**payload)
"""

import base64
import json
import logging
from datetime import datetime, timezone

import httpx
from anthropic import AsyncAnthropic

from config import settings
from database import AsyncSessionLocal

logger = logging.getLogger(__name__)

_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
MODEL = "claude-opus-4-6"


# ── Core API calls ─────────────────────────────────────────────────────────────

async def generate_listing_summary(listing: dict) -> tuple[str, str]:
    """Return (ai_summary, ai_layout_notes) for a listing dict."""
    prompt = f"""You are a Singapore real estate copywriter. Write a compelling, factual listing summary.

Listing details:
- Title: {listing.get('title', '')}
- Property type: {listing.get('property_type', '')}
- Intent: {listing.get('intent', '')}
- Address: {listing.get('address', '')}
- District: D{listing.get('district', '')}
- Asking price: SGD {listing.get('asking_price', '')}
- Floor size: {listing.get('floor_size', '')} sqft
- PSF: SGD {listing.get('psf', '')}
- Bedrooms: {listing.get('bedrooms', '')}
- Bathrooms: {listing.get('bathrooms', '')}
- Floor level: {listing.get('floor_level', '')} / {listing.get('total_floors', '')}
- Build year: {listing.get('build_year', '')}
- Tenure: {listing.get('tenure', '')}
- Nearest MRT: {listing.get('nearest_mrt', '')} ({listing.get('mrt_distance', '')}m)
- Furnishing: {listing.get('furnishing', '')}
- Unit features: {', '.join(listing.get('unit_features') or [])}
- Facilities: {', '.join(listing.get('facilities') or [])}
- Description: {listing.get('description', '')}

Respond with JSON only:
{{
  "summary": "3-4 sentence engaging summary highlighting key selling points",
  "layout_notes": "Brief notes on layout, space utilisation, and suitability (1-2 sentences)"
}}"""

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    text = _strip_fences(response.content[0].text)
    try:
        data = json.loads(text)
        return data.get("summary", ""), data.get("layout_notes", "")
    except json.JSONDecodeError:
        logger.warning("Claude returned non-JSON summary")
        return text, ""


async def analyze_floor_plan(image_url: str) -> str:
    """Download a floor plan image and return layout notes via vision API."""
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(image_url)
            resp.raise_for_status()
            image_bytes = resp.content
            content_type = resp.headers.get("content-type", "image/jpeg")
    except Exception as exc:
        logger.error("Failed to download floor plan from %s: %s", image_url, exc)
        return ""

    image_b64 = base64.standard_b64encode(image_bytes).decode()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": content_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Analyse this Singapore property floor plan. "
                            "Describe: overall layout flow, room sizes relative to each other, "
                            "natural light potential, storage, and any unusual features. "
                            "Keep it under 80 words, plain text."
                        ),
                    },
                ],
            }
        ],
    )
    return response.content[0].text.strip()


async def parse_preference_update(message: str, current_prefs: dict) -> dict:
    """
    Parse a buyer's natural language preference update.
    Returns only the fields that should change.
    """
    prompt = f"""You are helping a Singapore property buyer update their search preferences.

Current preferences:
{json.dumps(current_prefs, indent=2, default=str)}

Buyer's message: "{message}"

Extract what the buyer wants to change. Valid preference fields:
- intent: "buy" or "rent"
- property_types: list from ["hdb","condo","landed","commercial"]
- price_min, price_max: numbers in SGD
- floor_size_min, floor_size_max: numbers in sqft
- bedrooms: list of integers (e.g. [2,3])
- bathrooms: list of integers
- districts: list of integers 1-28
- mrt_distance_max: integer metres
- tenure: list from ["freehold","99-year","999-year"]
- floor_level_min, floor_level_max: integers
- build_year_min: integer
- psf_min, psf_max: numbers
- unit_features: list of strings (e.g. ["balcony","study","high ceiling"])
- facilities: list of strings (e.g. ["pool","gym","bbq"])
- furnishing: list from ["unfurnished","partial","fully"]
- keywords: freeform string

Respond with JSON of ONLY the fields that should change.
If nothing changes, return {{}}.
Example: {{"price_max": 1500000, "bedrooms": [3, 4]}}"""

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = _strip_fences(response.content[0].text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Claude returned non-JSON preference update")
        return {}


async def generate_unit_card_caption(listing: dict, match_id: int) -> str:
    """Build a Telegram-friendly Markdown caption for a matched unit."""
    price_str = f"SGD {listing['asking_price']:,.0f}" if listing.get("asking_price") else "POA"
    psf_str = f" (${listing['psf']:,.0f} psf)" if listing.get("psf") else ""
    mrt_str = (
        f"{listing['nearest_mrt']} · {listing['mrt_distance']}m"
        if listing.get("nearest_mrt")
        else ""
    )
    lines = [
        f"🏠 *{listing.get('title', 'New Listing')}*",
        "",
        f"💰 {price_str}{psf_str}",
        f"📐 {listing.get('floor_size', '?')} sqft  🛏 {listing.get('bedrooms', '?')}BR  🚿 {listing.get('bathrooms', '?')}BA",
        f"📍 {listing.get('address', '')}  D{listing.get('district', '')}",
    ]
    if mrt_str:
        lines.append(f"🚇 {mrt_str}")
    if listing.get("tenure"):
        lines.append(f"📜 {listing['tenure'].title()}  🏗 {listing.get('build_year', '?')}")
    if listing.get("ai_summary"):
        lines += ["", listing["ai_summary"]]
    lines += ["", f"👍 /like_{match_id}   👎 /skip_{match_id}   📅 /view_{match_id}"]
    return "\n".join(lines)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


# ── Event listeners (wired in services/registry.py) ──────────────────────────

async def on_listing_created_ai(listing_id: int, **kwargs) -> None:
    """Subscribed to 'listing.created'. Generates and persists AI summary."""
    from models import Listing  # local to avoid circular at import time

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        result = await db.execute(select(Listing).where(Listing.id == listing_id))
        listing = result.scalar_one_or_none()
        if not listing:
            return

        listing_dict = {c.name: getattr(listing, c.name) for c in Listing.__table__.columns}
        try:
            summary, layout_notes = await generate_listing_summary(listing_dict)
            listing.ai_summary = summary
            listing.ai_layout_notes = layout_notes
            listing.ai_generated_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("AI summary generated for listing %d.", listing_id)
        except Exception as exc:
            logger.warning("AI enrichment failed for listing %d: %s", listing_id, exc)


async def on_floor_plan_uploaded(listing_id: int, media_id: int, media_type: str, **kwargs) -> None:
    """Subscribed to 'listing.media_uploaded'. Analyses floor plans via vision."""
    if media_type != "floor_plan":
        return

    from models import Listing, ListingMedia  # local to avoid circular
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ListingMedia).where(ListingMedia.id == media_id)
        )
        media = result.scalar_one_or_none()
        if not media:
            return

        try:
            notes = await analyze_floor_plan(media.url)
            if notes:
                listing_result = await db.execute(
                    select(Listing).where(Listing.id == listing_id)
                )
                listing = listing_result.scalar_one_or_none()
                if listing:
                    existing = listing.ai_layout_notes or ""
                    listing.ai_layout_notes = f"{notes}\n{existing}".strip()
                    await db.commit()
                    logger.info("Floor plan analysed for listing %d.", listing_id)
        except Exception as exc:
            logger.warning("Floor plan analysis failed for listing %d: %s", listing_id, exc)
