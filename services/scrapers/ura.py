"""
URA Private Residential Property scraper — URA Data Service API.

Requires URA_ACCESS_KEY env var.
Free registration: https://www.ura.gov.sg/maps/api/

API flow:
  1. POST insertNewToken.action   → daily token
  2. GET  invokeUraDS?service=PMI_Resi_Transaction&batch=1  → transaction data
"""

import logging
import re

import httpx

from config import settings
from services.scrapers.utils import postal_to_district

logger = logging.getLogger(__name__)

_URA_BASE = "https://www.ura.gov.sg/uraDataService"

_PROP_TYPE_MAP = {
    "Condominium":            "condo",
    "Apartment":              "condo",
    "Executive Condominium":  "condo",
    "Detached House":         "landed",
    "Semi-Detached House":    "landed",
    "Terrace House":          "landed",
    "Strata Detached House":  "landed",
    "Strata Semi-Detached":   "landed",
    "Strata Terrace":         "landed",
}


class URAScraper:
    """Fetches private residential property transactions from the URA Data Service API."""

    source = "ura"
    start_urls = ["https://www.ura.gov.sg/maps/api/"]

    async def run(self) -> list[dict]:
        access_key = getattr(settings, "URA_ACCESS_KEY", None)
        if not access_key:
            logger.warning("[ura] URA_ACCESS_KEY not configured — skipping")
            return []

        async with httpx.AsyncClient(timeout=30) as client:
            token = await self._get_token(client, access_key)
            if not token:
                return []
            return await self._fetch_transactions(client, access_key, token)

    async def _get_token(self, client: httpx.AsyncClient, access_key: str) -> str | None:
        try:
            resp = await client.get(
                f"{_URA_BASE}/insertNewToken.action",
                params={"accesskey": access_key},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("Status") == "Success":
                token = data.get("Result")
                logger.info("[ura] Token obtained")
                return token
            logger.warning("[ura] Token error: %s", data)
            return None
        except Exception as exc:
            logger.error("[ura] Failed to get token: %s", exc)
            return None

    async def _fetch_transactions(
        self, client: httpx.AsyncClient, access_key: str, token: str
    ) -> list[dict]:
        results = []
        try:
            resp = await client.get(
                f"{_URA_BASE}/invokeUraDS",
                params={"service": "PMI_Resi_Transaction", "batch": "1"},
                headers={"AccessKey": access_key, "Token": token},
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("Status") != "Success":
                logger.warning("[ura] API error: %s", data.get("Message", "unknown"))
                return []

            for project in data.get("Result") or []:
                results.extend(self._parse_project(project))

        except Exception as exc:
            logger.error("[ura] Fetch error: %s", exc)

        # Keep only 100 most recent (already newest-first from API)
        results = results[:100]
        logger.info("[ura] %d transaction records fetched", len(results))
        return results

    def _parse_project(self, project: dict) -> list[dict]:
        results = []
        project_name = project.get("project", "").strip()
        street = project.get("street", "").strip()
        district_raw = project.get("district")
        prop_type_raw = project.get("propertyType", "")
        prop_type = _PROP_TYPE_MAP.get(prop_type_raw, "condo")

        district_num = None
        if district_raw:
            try:
                district_num = int(district_raw)
            except (ValueError, TypeError):
                pass

        for txn in project.get("transaction") or []:
            try:
                area_sqm = float(txn.get("area", 0) or 0)
                floor_size = round(area_sqm * 10.764, 1) if area_sqm else None
                price_raw = txn.get("price")
                price = float(price_raw) if price_raw else None
                psf = round(price / floor_size, 2) if price and floor_size else None

                tenure_raw = txn.get("tenure", "")
                if "freehold" in tenure_raw.lower():
                    tenure = "freehold"
                elif "999" in tenure_raw:
                    tenure = "999-year"
                else:
                    tenure = "99-year"

                # Extract lease start year from tenure string e.g. "99 yrs lease commencing from 1996"
                build_year = None
                yr_m = re.search(r"from\s+(\d{4})", tenure_raw)
                if yr_m:
                    build_year = int(yr_m.group(1))

                floor_range = txn.get("floorRange", "")
                floor_level = None
                fl_m = re.match(r"(\d+)-(\d+)", floor_range)
                if fl_m:
                    floor_level = (int(fl_m.group(1)) + int(fl_m.group(2))) // 2

                contract_date = txn.get("contractDate", "")  # YYMM
                type_of_sale_code = str(txn.get("typeOfSale", "3"))
                type_labels = {"1": "New Sale", "2": "Sub Sale", "3": "Resale"}
                type_label = type_labels.get(type_of_sale_code, "Resale")
                intent = "buy"

                external_id = (
                    f"ura-{project_name}-{floor_range}-{area_sqm}-{contract_date}"
                    .replace(" ", "-")
                    .lower()
                )

                title = f"{prop_type_raw} at {project_name}, {street}"
                description = (
                    f"{prop_type_raw} transaction at {project_name}, {street}. "
                    f"{type_label}. Floor: {floor_range}. Tenure: {tenure_raw}."
                )

                results.append({
                    "source": "ura",
                    "source_url": "https://www.ura.gov.sg/maps/#",
                    "external_id": external_id,
                    "title": title,
                    "property_type": prop_type,
                    "intent": intent,
                    "address": f"{project_name}, {street}, Singapore",
                    "district": district_num,
                    "asking_price": price,
                    "floor_size": floor_size,
                    "psf": psf,
                    "floor_level": floor_level,
                    "build_year": build_year,
                    "tenure": tenure,
                    "description": description,
                })
            except Exception as exc:
                logger.debug("[ura] Transaction parse error: %s", exc)

        return results
