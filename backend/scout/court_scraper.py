import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from backend.lib.db import upsert_property, insert_lead, get_lead_by_property

COURT_BASE = "https://www.sjcourts.org"
COURT_CASE_SEARCH = f"{COURT_BASE}/online-services/case-summary/"
SJMAP_PARCEL_URL = "https://sjmap.org/arcgis/rest/services/Assessor/Assessor_Parcels/MapServer/0/query"

TARGET_CASE_TYPES = ("FL", "PR")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _search_cases(case_type: str, client: httpx.Client) -> list[dict]:
    results = []
    try:
        resp = client.get(COURT_CASE_SEARCH, params={"caseType": case_type}, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        rows = soup.select("table tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            case_num = cells[0].get_text(strip=True)
            party = cells[1].get_text(strip=True)
            filed = cells[2].get_text(strip=True)
            status = cells[3].get_text(strip=True)

            if not case_num or case_type not in case_num:
                continue

            results.append({
                "case_number": case_num,
                "party_name": party,
                "filing_date": filed,
                "status": status,
                "case_type": case_type,
            })

        logger.info("court_scraper case_type={} found={}", case_type, len(results))
    except Exception as e:
        logger.error("court_scraper search_cases case_type={} error={}", case_type, str(e))

    return results


def _lookup_property_by_owner(owner_name: str, client: httpx.Client) -> Optional[dict]:
    if not owner_name or len(owner_name) < 3:
        return None

    parts = owner_name.strip().split()
    if not parts:
        return None

    last_name = parts[-1].upper()

    try:
        params = {
            "where": f"UPPER(OWNER1) LIKE '%{last_name}%'",
            "outFields": "SITUS_ADDR,SITUS_CITY,SITUS_ZIP,APN,OWNER1,LAND_USE",
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": "5",
        }
        resp = client.get(SJMAP_PARCEL_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        if not features:
            return None

        feat = features[0]["attributes"]
        return {
            "address": feat.get("SITUS_ADDR", "").title(),
            "city": feat.get("SITUS_CITY", "").title(),
            "zip": str(feat.get("SITUS_ZIP", "")),
            "apn": str(feat.get("APN", "")),
            "owner_name": feat.get("OWNER1", "").title(),
            "land_use": feat.get("LAND_USE", ""),
        }
    except Exception as e:
        logger.error("court_scraper arcgis lookup owner={} error={}", owner_name, str(e))
        return None


def _parse_party_name(party_text: str) -> str:
    if " vs " in party_text.lower():
        return party_text.split(" vs ")[0].strip()
    if " v. " in party_text.lower():
        return party_text.split(" v. ")[0].strip()
    if "," in party_text:
        return party_text.split(",")[0].strip()
    return party_text.strip()


def scrape_new_filings() -> list[dict]:
    found: list[dict] = []

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
        for case_type in TARGET_CASE_TYPES:
            cases = _search_cases(case_type, client)
            time.sleep(1)

            for case in cases:
                raw_party = case["party_name"]
                owner_name = _parse_party_name(raw_party)

                prop_data = _lookup_property_by_owner(owner_name, client)
                time.sleep(0.5)

                if prop_data:
                    case["resolved_property"] = prop_data
                    found.append(case)
                    logger.debug(
                        "court_match case={} owner={} address={}",
                        case["case_number"], owner_name, prop_data.get("address"),
                    )

    logger.info("court_scraper scrape_complete matched={}", len(found))
    return found


def upsert_court_lead(case: dict) -> Optional[str]:
    prop = case.get("resolved_property")
    if not prop:
        return None

    apn = prop.get("apn", "")
    if not apn:
        return None

    case_type = case.get("case_type", "")
    distress_type = "divorce" if case_type == "FL" else "probate"

    property_data = {
        "apn": apn,
        "address": prop.get("address", ""),
        "city": prop.get("city", ""),
        "zip": prop.get("zip", ""),
        "owner_name": prop.get("owner_name", ""),
        "distress_type": distress_type,
        "distress_score": 65,
        "land_use": prop.get("land_use", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        upsert_property(property_data)
        logger.info("upsert_court_property apn={} type={}", apn, distress_type)

        from backend.lib.db import get_properties_by_score, _get_client

        client_db = _get_client()
        resp = client_db.table("properties").select("id").eq("apn", apn).limit(1).execute()
        if not resp.data:
            return None

        property_id = resp.data[0]["id"]
        existing = get_lead_by_property(property_id)
        if existing:
            return existing["id"]

        lead_id = insert_lead(property_id)
        logger.info("insert_court_lead lead_id={} distress={}", lead_id, distress_type)
        return lead_id

    except Exception as e:
        logger.error("upsert_court_lead apn={} error={}", apn, str(e))
        return None


def run_weekly_scrape() -> dict[str, int]:
    logger.info("court_scraper weekly_scrape starting")
    cases = scrape_new_filings()

    divorce_count = 0
    probate_count = 0
    failed = 0

    for case in cases:
        lead_id = upsert_court_lead(case)
        if lead_id:
            if case.get("case_type") == "FL":
                divorce_count += 1
            else:
                probate_count += 1
        else:
            failed += 1

    result = {
        "divorce": divorce_count,
        "probate": probate_count,
        "failed": failed,
        "total": len(cases),
    }
    logger.info("court_scraper weekly_scrape result={}", result)
    return result
