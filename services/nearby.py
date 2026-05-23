"""
Nearby amenities service.

Uses:
  - OneMap Singapore API (free, no key) for geocoding address → lat/lng
  - OpenStreetMap Overpass API (free) for nearby place search

Public surface:
    get_nearby(listing, amenity_types, radius_metres) → str  (human-readable summary)
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_ONEMAP_SEARCH = "https://www.onemap.gov.sg/api/common/elastic/search"
_OVERPASS_API = "https://overpass-api.de/api/interpreter"

# Map user-friendly terms → OSM tags to query
# Each entry is a list of (key, value) pairs tried in one Overpass union
_AMENITY_MAP: dict[str, list[tuple[str, str]]] = {
    # Food & drink
    "cafe":             [("amenity", "cafe")],
    "coffee shop":      [("amenity", "cafe"), ("amenity", "fast_food")],
    "hawker":           [("amenity", "food_court"), ("amenity", "hawker_centre")],
    "hawker centre":    [("amenity", "food_court"), ("amenity", "hawker_centre")],
    "restaurant":       [("amenity", "restaurant")],
    "food":             [("amenity", "cafe"), ("amenity", "restaurant"), ("amenity", "food_court"), ("amenity", "fast_food")],

    # Shopping
    "mall":             [("shop", "mall"), ("building", "retail")],
    "shopping mall":    [("shop", "mall"), ("building", "retail")],
    "supermarket":      [("shop", "supermarket")],
    "grocery":          [("shop", "supermarket"), ("shop", "convenience")],
    "minimart":         [("shop", "convenience")],

    # Parks & recreation
    "park":             [("leisure", "park"), ("leisure", "garden")],
    "dog park":         [("leisure", "dog_park"), ("leisure", "park")],
    "playground":       [("leisure", "playground")],
    "gym":              [("leisure", "fitness_centre"), ("amenity", "gym")],
    "swimming pool":    [("leisure", "swimming_pool")],
    "sports":           [("leisure", "sports_centre"), ("leisure", "fitness_centre")],

    # Transport
    "mrt":              [("railway", "station"), ("station", "subway")],
    "bus stop":         [("highway", "bus_stop")],
    "bus":              [("highway", "bus_stop")],

    # Education
    "school":           [("amenity", "school")],
    "primary school":   [("amenity", "school")],
    "childcare":        [("amenity", "childcare"), ("amenity", "kindergarten")],
    "kindergarten":     [("amenity", "kindergarten")],

    # Healthcare
    "clinic":           [("amenity", "clinic"), ("amenity", "doctors")],
    "hospital":         [("amenity", "hospital")],
    "pharmacy":         [("amenity", "pharmacy")],

    # General
    "bank":             [("amenity", "bank")],
    "atm":              [("amenity", "atm")],
    "library":          [("amenity", "library")],
    "place of worship": [("amenity", "place_of_worship")],
    "mosque":           [("amenity", "place_of_worship"), ("religion", "muslim")],
    "temple":           [("amenity", "place_of_worship")],
    "church":           [("amenity", "place_of_worship")],
}


async def _geocode_onemap(address: str, postal: Optional[str] = None) -> Optional[tuple[float, float]]:
    """Return (lat, lng) for a Singapore address using OneMap API."""
    search_val = postal or address
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _ONEMAP_SEARCH,
                params={"searchVal": search_val, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                r = results[0]
                return float(r["LATITUDE"]), float(r["LONGITUDE"])
    except Exception as exc:
        logger.warning("OneMap geocode failed for %r: %s", search_val, exc)
    return None


def _build_overpass_query(lat: float, lng: float, tags: list[tuple[str, str]], radius: int) -> str:
    """Build an Overpass QL query for the given OSM tags within radius of a point."""
    parts = []
    for key, val in tags:
        parts.append(f'node["{key}"="{val}"](around:{radius},{lat},{lng});')
        parts.append(f'way["{key}"="{val}"](around:{radius},{lat},{lng});')
    union = "\n  ".join(parts)
    return f"""
[out:json][timeout:15];
(
  {union}
);
out center 20;
""".strip()


async def _query_overpass(query: str) -> list[dict]:
    """Run an Overpass query and return the list of elements."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(_OVERPASS_API, data={"data": query})
            resp.raise_for_status()
            return resp.json().get("elements", [])
    except Exception as exc:
        logger.warning("Overpass query failed: %s", exc)
        return []


def _element_name(el: dict) -> Optional[str]:
    """Extract a display name from an OSM element."""
    tags = el.get("tags", {})
    return tags.get("name") or tags.get("brand") or tags.get("operator")


def _element_distance(el: dict, lat: float, lng: float) -> float:
    """Rough distance in metres using equirectangular approximation."""
    import math
    el_lat = el.get("lat") or el.get("center", {}).get("lat", lat)
    el_lng = el.get("lon") or el.get("center", {}).get("lon", lng)
    dlat = (el_lat - lat) * 111320
    dlng = (el_lng - lng) * 111320 * math.cos(math.radians(lat))
    return round((dlat ** 2 + dlng ** 2) ** 0.5)


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
    """
    # Step 1: get coordinates
    coords = None
    if lat and lng:
        coords = (lat, lng)
    else:
        coords = await _geocode_onemap(address, postal)

    if not coords:
        return "Could not determine the property location for nearby search."

    clat, clng = coords
    radius_metres = min(radius_metres, 2000)  # cap at 2km

    # Step 2: for each requested amenity type, query Overpass
    all_results: list[str] = []

    for amenity in amenity_types:
        key = amenity.lower().strip()
        tags = _AMENITY_MAP.get(key)

        # Fuzzy fallback: find closest key
        if not tags:
            for k in _AMENITY_MAP:
                if key in k or k in key:
                    tags = _AMENITY_MAP[k]
                    break

        if not tags:
            all_results.append(f"**{amenity.title()}**: No search category found for this type.")
            continue

        query = _build_overpass_query(clat, clng, tags, radius_metres)
        elements = await _query_overpass(query)

        if not elements:
            all_results.append(f"**{amenity.title()}**: None found within {radius_metres}m.")
            continue

        # Sort by distance and take top 5
        scored = sorted(
            [(el, _element_distance(el, clat, clng)) for el in elements],
            key=lambda x: x[1],
        )[:5]

        names = []
        for el, dist in scored:
            name = _element_name(el)
            if name:
                names.append(f"{name} (~{dist}m)")
            else:
                names.append(f"Unnamed ({dist}m)")

        all_results.append(f"**{amenity.title()}** within {radius_metres}m: {', '.join(names)}")

    if not all_results:
        return "No amenity results found."

    header = f"Nearby amenities (within {radius_metres}m of {address}):\n"
    return header + "\n".join(f"• {r}" for r in all_results)
