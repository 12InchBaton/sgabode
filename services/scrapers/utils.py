"""Shared utilities for all scrapers."""

import re

# Singapore postal sector → district mapping
# Postal sector = first 2 digits of 6-digit postal code
_SECTOR_TO_DISTRICT: dict[int, int] = {
    **{s: 1  for s in [1, 2, 3, 4, 5, 6]},
    **{s: 2  for s in [7, 8]},
    **{s: 3  for s in [14, 15, 16]},
    **{s: 4  for s in [9, 10]},
    **{s: 5  for s in [11, 12, 13]},
    **{s: 6  for s in [17]},
    **{s: 7  for s in [18, 19]},
    **{s: 8  for s in [20, 21]},
    **{s: 9  for s in [22, 23]},
    **{s: 10 for s in [24, 25, 26, 27]},
    **{s: 11 for s in [28, 29, 30]},
    **{s: 12 for s in [31, 32, 33]},
    **{s: 13 for s in [34, 35, 36, 37]},
    **{s: 14 for s in [38, 39, 40, 41]},
    **{s: 15 for s in [42, 43, 44, 45]},
    **{s: 16 for s in [46, 47, 48]},
    **{s: 17 for s in [49, 50, 81]},
    **{s: 18 for s in [51, 52]},
    **{s: 19 for s in [53, 54, 55, 82]},
    **{s: 20 for s in [56, 57]},
    **{s: 21 for s in [58, 59]},
    **{s: 22 for s in [60, 61, 62, 63, 64]},
    **{s: 23 for s in [65, 66, 67, 68]},
    **{s: 24 for s in [69, 70, 71]},
    **{s: 25 for s in [72, 73]},
    **{s: 26 for s in [77, 78]},
    **{s: 27 for s in [75, 76]},
    **{s: 28 for s in [79, 80]},
}


def postal_to_district(postal_code: str | None) -> int | None:
    """Return Singapore district number from a 6-digit postal code."""
    if not postal_code:
        return None
    digits = re.sub(r"\D", "", postal_code)
    if len(digits) < 2:
        return None
    sector = int(digits[:2])
    return _SECTOR_TO_DISTRICT.get(sector)


def parse_price(text: str | None) -> float | None:
    """Extract numeric price from strings like 'S$1,200,000' or '$850k'."""
    if not text:
        return None
    text = text.upper().replace(",", "").replace("S$", "").replace("$", "").strip()
    multiplier = 1
    if text.endswith("K"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("M"):
        multiplier = 1_000_000
        text = text[:-1]
    try:
        return float(re.sub(r"[^\d.]", "", text)) * multiplier
    except ValueError:
        return None


def parse_floor_size(text: str | None) -> float | None:
    """Extract sqft number from strings like '1,200 sqft' or '900 sq ft'."""
    if not text:
        return None
    m = re.search(r"([\d,]+)\s*sq", text.lower().replace(",", ""))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def clean_text(text: str | None) -> str | None:
    if not text:
        return None
    return " ".join(text.split()).strip() or None
