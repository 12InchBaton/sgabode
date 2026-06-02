"""
URA Private Residential Property scraper — URA Data Service API v1.

Requires URA_ACCESS_KEY env var.
Free registration: https://eservice.ura.gov.sg/maps/api/reg.html

API flow:
  1. GET insertNewToken/v1              → daily token
  2. GET invokeUraDS/v1?service=PMI_Resi_Transaction&batch=1  → sale transactions
  3. GET invokeUraDS/v1?service=PMI_Resi_Rental&batch=1       → rental contracts

Uses curl_cffi to bypass WAF (Nexusguard TLS fingerprint check).
"""

import logging
import re

from curl_cffi.requests import AsyncSession

from config import settings
from services.scrapers.utils import postal_to_district

logger = logging.getLogger(__name__)

_URA_BASE = "https://eservice.ura.gov.sg/uraDataService"

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
    start_urls = ["https://eservice.ura.gov.sg/maps/api/"]

    async def run(self) -> list[dict]:
        access_key = getattr(settings, "URA_ACCESS_KEY", None)
        if not access_key:
            logger.warning("[ura] URA_ACCESS_KEY not configured — skipping")
            return []

        async with AsyncSession(impersonate="chrome120", timeout=30) as client:
            token = await self._get_token(client, access_key)
            if not token:
                return []
            sales = await self._fetch_transactions(client, access_key, token)
            rentals = await self._fetch_rentals(client, access_key, token)
            return sales + rentals

    async def _get_token(self, client: AsyncSession, access_key: str) -> str | None:
        try:
            resp = await client.get(
                f"{_URA_BASE}/insertNewToken/v1",
                params={"accesskey": access_key},
            )
            content_type = resp.headers.get("content-type", "")
            if "json" not in content_type:
                logger.error("[ura] Token endpoint returned non-JSON (WAF block?): status=%d ct=%s body=%s",
                             resp.status_code, content_type, resp.text[:200])
                return None
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
        self, client: AsyncSession, access_key: str, token: str
    ) -> list[dict]:
        results = []
        try:
            resp = await client.get(
                f"{_URA_BASE}/invokeUraDS/v1",
                params={"service": "PMI_Resi_Transaction", "batch": "1"},
                headers={"AccessKey": access_key, "Token": token},
            )
            data = resp.json()

            if data.get("Status") != "Success":
                logger.warning("[ura] API error: %s", data.get("Message", "unknown"))
                return []

            for project in data.get("Result") or []:
                results.extend(self._parse_project(project))

        except Exception as exc:
            logger.error("[ura] Fetch error: %s", exc)

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

                build_year = None
                yr_m = re.search(r"from\s+(\d{4})", tenure_raw)
                if yr_m:
                    build_year = int(yr_m.group(1))

                floor_range = txn.get("floorRange", "")
                floor_level = None
                fl_m = re.match(r"(\d+)-(\d+)", floor_range)
                if fl_m:
                    floor_level = (int(fl_m.group(1)) + int(fl_m.group(2))) // 2

                contract_date = txn.get("contractDate", "")
                type_of_sale_code = str(txn.get("typeOfSale", "3"))
                type_labels = {"1": "New Sale", "2": "Sub Sale", "3": "Resale"}
                type_label = type_labels.get(type_of_sale_code, "Resale")

                external_id = (
                    f"ura-{project_name}-{floor_range}-{area_sqm}-{contract_date}"
                    .replace(" ", "-")
                    .lower()
                )

                results.append({
                    "source": "ura",
                    "source_url": "https://eservice.ura.gov.sg/maps/#",
                    "external_id": external_id,
                    "title": f"{prop_type_raw} at {project_name}, {street}",
                    "property_type": prop_type,
                    "intent": "buy",
                    "address": f"{project_name}, {street}, Singapore",
                    "district": district_num,
                    "asking_price": price,
                    "floor_size": floor_size,
                    "psf": psf,
                    "floor_level": floor_level,
                    "build_year": build_year,
                    "tenure": tenure,
                    "description": (
                        f"{prop_type_raw} transaction at {project_name}, {street}. "
                        f"{type_label}. Floor: {floor_range}. Tenure: {tenure_raw}."
                    ),
                })
            except Exception as exc:
                logger.debug("[ura] Transaction parse error: %s", exc)

        return results

    async def _fetch_rentals(
        self, client: AsyncSession, access_key: str, token: str
    ) -> list[dict]:
        results = []
        try:
            resp = await client.get(
                f"{_URA_BASE}/invokeUraDS/v1",
                params={"service": "PMI_Resi_Rental", "batch": "1"},
                headers={"AccessKey": access_key, "Token": token},
            )
            data = resp.json()

            if data.get("Status") != "Success":
                logger.warning("[ura] Rental API error: %s", data.get("Message", "unknown"))
                return []

            for project in data.get("Result") or []:
                results.extend(self._parse_rental_project(project))

        except Exception as exc:
            logger.error("[ura] Rental fetch error: %s", exc)

        results = results[:100]
        logger.info("[ura] %d rental records fetched", len(results))
        return results

    def _parse_rental_project(self, project: dict) -> list[dict]:
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
                area_sqft_raw = txn.get("areaSqft") or txn.get("area")
                area_sqm_raw = txn.get("areaSqm")
                if area_sqft_raw:
                    floor_size = float(area_sqft_raw)
                elif area_sqm_raw:
                    floor_size = round(float(area_sqm_raw) * 10.764, 1)
                else:
                    floor_size = None

                rent_raw = txn.get("rent")
                rent = float(rent_raw) if rent_raw else None
                psf = round(rent / floor_size, 2) if rent and floor_size else None

                bedrooms_raw = txn.get("noOfBedRoom")
                bedrooms = int(bedrooms_raw) if bedrooms_raw and str(bedrooms_raw).isdigit() else None

                floor_range = txn.get("floorRange", "")
                floor_level = None
                fl_m = re.match(r"(\d+)-(\d+)", floor_range)
                if fl_m:
                    floor_level = (int(fl_m.group(1)) + int(fl_m.group(2))) // 2

                lease_date = txn.get("leaseDate", "")
                external_id = (
                    f"ura-rent-{project_name}-{floor_range}-{area_sqft_raw}-{lease_date}"
                    .replace(" ", "-")
                    .lower()
                )

                rent_str = f"SGD {rent:,.0f}/mth" if rent else "POA"
                results.append({
                    "source": "ura",
                    "source_url": "https://eservice.ura.gov.sg/maps/#",
                    "external_id": external_id,
                    "title": f"{prop_type_raw} Rental at {project_name}, {street}",
                    "property_type": prop_type,
                    "intent": "rent",
                    "address": f"{project_name}, {street}, Singapore",
                    "district": district_num,
                    "asking_price": rent,
                    "floor_size": floor_size,
                    "psf": psf,
                    "bedrooms": bedrooms,
                    "floor_level": floor_level,
                    "description": (
                        f"{prop_type_raw} rental at {project_name}, {street}. "
                        f"Floor: {floor_range}. Monthly rent: {rent_str}."
                    ),
                })
            except Exception as exc:
                logger.debug("[ura] Rental parse error: %s", exc)

        return results
