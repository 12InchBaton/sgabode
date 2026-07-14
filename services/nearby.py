"""
Nearby amenities service.

Uses:
  - OneMap Singapore API (free, no key) for geocoding address → lat/lng
  - Google Places API (Nearby Search) for amenity search

Public surface:
    get_nearby(listing, amenity_types, radius_metres) → str  (human-readable summary)
"""

import logging
import math
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_ONEMAP_SEARCH = "https://www.onemap.gov.sg/api/common/elastic/search"
_GOOGLE_PLACES_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

# Map user-friendly terms → Google Places types
# https://developers.google.com/maps/documentation/places/web-service/supported_types
_AMENITY_MAP: dict[str, list[str]] = {
    # Food & drink
    "cafe":             ["cafe"],
    "coffee shop":      ["cafe"],
    "hawker":           ["meal_takeaway", "food_court"],
    "hawker centre":    ["meal_takeaway", "food_court"],
    "restaurant":       ["restaurant"],
    "food":             ["restaurant", "cafe", "meal_takeaway", "food_court"],

    # Shopping
    "mall":             ["shopping_mall"],
    "shopping mall":    ["shopping_mall"],
    "supermarket":      ["supermarket", "grocery_or_supermarket"],
    "grocery":          ["supermarket", "grocery_or_supermarket", "convenience_store"],
    "minimart":         ["convenience_store"],

    # Parks & recreation
    "park":             ["park"],
    "dog park":         ["park"],
    "playground":       ["playground", "park"],
    "gym":              ["gym", "health"],
    "swimming pool":    ["swimming_pool"],
    "sports":           ["stadium", "gym", "health"],

    # Transport
    "mrt":              ["subway_station", "train_station"],
    "bus stop":         ["bus_station"],
    "bus":              ["bus_station"],

    # Education
    "school":           ["school", "primary_school", "secondary_school"],
    "primary school":   ["primary_school", "school"],
    "childcare":        ["child_care_agency"],
    "kindergarten":     ["kindergarten"],

    # Healthcare
    "clinic":           ["doctor", "health"],
    "hospital":         ["hospital"],
    "pharmacy":         ["pharmacy", "drugstore"],

    # General
    "bank":             ["bank"],
    "atm":              ["atm"],
    "library":          ["library"],
    "place of worship": ["place_of_worship"],
    "mosque":           ["mosque"],
    "temple":           ["hindu_temple", "place_of_worship"],
    "church":           ["church"],
}


async def _geocode_onemap(address: str, postal: Optional[str] = None) -> Optional[tuple[float, float]]:
    """
    Return (lat, lng) for a Singapore address using OneMap API.
    Tries in order: postal code → full address → street only.
    """
    import re
    candidates = []
    if postal and len(postal) == 6 and postal.isdigit():
        candidates.append(postal)
    if address:
        candidates.append(address)
        street_only = re.sub(r"^Blk\s+\w+\s+", "", address, flags=re.IGNORECASE).split(",")[0].strip()
        if street_only and street_only != address:
            candidates.append(street_only)

    async with httpx.AsyncClient(timeout=10) as client:
        for search_val in candidates:
            try:
                resp = await client.get(
                    _ONEMAP_SEARCH,
                    params={"searchVal": search_val, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1},
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                if results:
                    r = results[0]
                    lat, lng = float(r["LATITUDE"]), float(r["LONGITUDE"])
                    if 1.15 <= lat <= 1.50 and 103.6 <= lng <= 104.1:
                        logger.info("OneMap geocoded %r → (%.5f, %.5f)", search_val, lat, lng)
                        return lat, lng
            except Exception as exc:
                logger.warning("OneMap geocode failed for %r: %s", search_val, exc)
    return None


async def _query_google_places(
    lat: float, lng: float, place_types: list[str], radius: int, api_key: str
) -> list[dict]:
    """
    Query Google Places Nearby Search for each place type and return combined results.
    Deduplicates by place_id.
    """
    seen: set[str] = set()
    results: list[dict] = []

    async with httpx.AsyncClient(timeout=15) as client:
        for place_type in place_types:
            try:
                resp = await client.get(
                    _GOOGLE_PLACES_URL,
                    params={
                        "location": f"{lat},{lng}",
                        "radius": radius,
                        "type": place_type,
                        "key": api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") not in ("OK", "ZERO_RESULTS"):
                    logger.warning("[google_places] API status: %s", data.get("status"))
                    continue

                for place in data.get("results", []):
                    place_id = place.get("place_id")
                    if place_id and place_id not in seen:
                        seen.add(place_id)
                        results.append(place)

            except Exception as exc:
                logger.warning("[google_places] Query failed for type=%s: %s", place_type, exc)

    return results


def _haversine_metres(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Distance in metres between two lat/lng points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _walk_time(metres: int) -> str:
    mins = round(metres / 80)  # ~80m/min walking pace
    return f"~{mins} min walk" if mins > 0 else "on your doorstep"


async def get_nearby(
    address: str,
    postal: Optional[str],
    lat: Optional[float],
    lng: Optional[float],
    amenity_types: list[str],
    radius_metres: int = 800,
) -> str:
    """
    Return a human-readable summary of nearby amenities for a listing.
    Uses stored lat/lng if available, otherwise geocodes via OneMap.
    Uses Google Places API for amenity search.
    """
    api_key = getattr(settings, "GOOGLE_PLACES_API_KEY", "")
    if not api_key:
        return (
            "TOOL_ERROR: GOOGLE_PLACES_API_KEY is not configured. "
            "Tell the user the nearby search is unavailable and suggest they check Google Maps directly."
        )

    # Step 1: get coordinates
    coords = None
    if lat and lng:
        coords = (lat, lng)
    else:
        coords = await _geocode_onemap(address, postal)

    if not coords:
        return (
            f"TOOL_ERROR: Could not geocode the property address ({address!r}, postal={postal!r}). "
            "Tell the user the nearby search failed and suggest they check Google Maps directly."
        )

    clat, clng = coords
    radius_metres = min(radius_metres, 2000)  # cap at 2km

    # Step 2: for each amenity type, query Google Places
    all_results: list[str] = []

    for amenity in amenity_types:
        key = amenity.lower().strip()
        place_types = _AMENITY_MAP.get(key)

        # Fuzzy fallback
        if not place_types:
            for k in _AMENITY_MAP:
                if key in k or k in key:
                    place_types = _AMENITY_MAP[k]
                    break

        if not place_types:
            all_results.append(f"**{amenity.title()}**: Unknown amenity type.")
            continue

        places = await _query_google_places(clat, clng, place_types, radius_metres, api_key)

        if not places:
            all_results.append(f"**{amenity.title()}**: None found within {radius_metres}m.")
            continue

        # Sort by distance, take top 5
        scored = []
        for p in places:
            loc = p.get("geometry", {}).get("location", {})
            plat, plng = loc.get("lat"), loc.get("lng")
            if plat and plng:
                dist = _haversine_metres(clat, clng, plat, plng)
                scored.append((p, dist))

        scored.sort(key=lambda x: x[1])
        top = scored[:5]

        names = []
        for p, dist in top:
            name = p.get("name", "Unnamed")
            names.append(f"{name} ({_walk_time(dist)})")

        all_results.append(f"**{amenity.title()}** within {radius_metres}m: {', '.join(names)}")

    if not all_results:
        return "No amenity results found."

    header = f"Nearby amenities (within {radius_metres}m of {address}):\n"
    return header + "\n".join(f"• {r}" for r in all_results)
