import os
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

from backend.scout.scorer import calculate_distress_score


_BASE_V1 = "https://api.batchdata.com/api/v1"
_BASE_V3 = "https://api.batchdata.com/api/v3"
_TIMEOUT = 30

_LOOKUP_DATASETS = [
    "core",
    "contact",
    "valuation",
    "mortgage-liens",
    "deed",
    "demographic",
    "foreclosure",
    "listing",
    "permit",
    "batchrank",
    "owner",
    "quicklist",
]


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['BATCHDATA_API_KEY']}",
        "Content-Type": "application/json",
    }


def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(url, json=body, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def lookup_property(address: str, city: str, state: str, zip_code: str) -> dict[str, Any]:
    body = {
        "requests": [
            {
                "address": {
                    "street": address,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                }
            }
        ],
        "options": {
            "skipTrace": True,
            "datasets": _LOOKUP_DATASETS,
        },
    }
    try:
        data = _post(f"{_BASE_V1}/property/lookup/all-attributes", body)
        properties = data.get("results", {}).get("properties") or []
        if not properties:
            logger.warning("lookup_property no result address={} city={}", address, city)
            return {}
        return properties[0]
    except Exception as e:
        logger.error("lookup_property failed address={} city={} error={}", address, city, str(e))
        return {}


def skip_trace(address: str, city: str, state: str, zip_code: str) -> dict[str, Any]:
    body = {
        "requests": [
            {
                "propertyAddress": {
                    "street": address,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                }
            }
        ],
        "options": {
            "includeTCPABlacklistedPhones": True,
        },
    }
    try:
        data = _post(f"{_BASE_V3}/property/skip-trace", body)
        results = data.get("result", {}).get("data") or []
        if not results:
            logger.warning("skip_trace no result address={}", address)
            return {}
        return results[0]
    except Exception as e:
        logger.error("skip_trace failed address={} error={}", address, str(e))
        return {}


def scrub_phone(phone: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "phone": phone,
        "callable": False,
        "dnc": False,
        "tcpa": False,
        "valid": False,
        "line_type": "unknown",
    }

    try:
        dnc_resp = _post(f"{_BASE_V1}/phone/dnc", {"requests": [phone]})
        phone_rows = dnc_resp.get("results", {}).get("phoneNumbers") or []
        if phone_rows:
            result["dnc"] = bool(phone_rows[0].get("dnc", False))
        if result["dnc"]:
            logger.debug("scrub_phone dnc=True phone={}", phone)
            return result
    except Exception as e:
        logger.warning("scrub_phone dnc check failed phone={} error={}", phone, str(e))
        return result

    try:
        tcpa_resp = _post(f"{_BASE_V1}/phone/tcpa", {"requests": [phone]})
        phone_rows = tcpa_resp.get("results", {}).get("phoneNumbers") or []
        if phone_rows:
            result["tcpa"] = bool(phone_rows[0].get("tcpa", False))
        if result["tcpa"]:
            logger.debug("scrub_phone tcpa=True phone={}", phone)
            return result
    except Exception as e:
        logger.warning("scrub_phone tcpa check failed phone={} error={}", phone, str(e))
        return result

    try:
        verify_resp = _post(f"{_BASE_V1}/phone/verification", {"requests": [phone]})
        phone_rows = verify_resp.get("results", {}).get("phoneNumbers") or []
        if phone_rows:
            r = phone_rows[0]
            not_found = bool(r.get("notFound", False))
            result["valid"] = not not_found
            result["line_type"] = r.get("type") or "unknown"
            result["callable"] = bool(r.get("reachable", False)) and not not_found
    except Exception as e:
        logger.warning("scrub_phone verify failed phone={} error={}", phone, str(e))

    return result


def _cents(dollars: float | int | None) -> int | None:
    if dollars is None:
        return None
    try:
        return int(float(dollars) * 100)
    except (ValueError, TypeError):
        return None


def _compute_years_owned(deed_history: list[dict]) -> float | None:
    if not deed_history:
        return None
    try:
        dates = []
        for deed in deed_history:
            raw = deed.get("saleDate") or deed.get("recordingDate")
            if raw:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                dates.append(dt)
        if not dates:
            return None
        most_recent = max(dates)
        return round((datetime.now(timezone.utc) - most_recent).days / 365.25, 2)
    except Exception:
        return None


def _extract_phones_from_lookup(bd_data: dict) -> list[str]:
    phones: list[str] = []
    seen: set[str] = set()

    for source in [
        bd_data.get("persons") or [],
        (bd_data.get("contact") or {}).get("persons") or [],
    ]:
        for person in source:
            for ph in (person.get("phones") or []):
                num = str(ph.get("number") or "").strip()
                if len(num) >= 10 and num not in seen:
                    seen.add(num)
                    phones.append(num)

    return phones


def _extract_phones_from_skip_trace(st_data: dict) -> list[str]:
    phones: list[str] = []
    seen: set[str] = set()
    for person in (st_data.get("persons") or []):
        for ph in (person.get("phones") or []):
            num = str(ph.get("number") or "").strip()
            if len(num) >= 10 and num not in seen:
                seen.add(num)
                phones.append(num)
    return phones


def _extract_email_from_skip_trace(st_data: dict) -> str | None:
    for person in (st_data.get("persons") or []):
        emails = person.get("emails") or []
        if emails:
            return emails[0].get("email")
    return None


def enrich_lead(lead: dict[str, Any], prop: dict[str, Any]) -> dict[str, Any]:
    prop = dict(prop)
    lead = dict(lead)

    address = prop.get("address") or ""
    city = prop.get("city") or ""
    state = prop.get("state") or "CA"
    zip_code = prop.get("zip") or ""

    bd_data = lookup_property(address, city, state, zip_code)

    if bd_data:
        valuation = bd_data.get("valuation") or {}
        building = bd_data.get("building") or {}
        owner_obj = bd_data.get("owner") or {}
        mailing = owner_obj.get("mailingAddress") or {}
        quick = bd_data.get("quickLists") or {}
        foreclosure = bd_data.get("foreclosure") or {}
        deed_history = bd_data.get("deedHistory") or []
        open_lien = bd_data.get("openLien") or {}
        mortgage_history = bd_data.get("mortgageHistory") or []
        batchrank = bd_data.get("batchrank") or {}
        listing = bd_data.get("listing") or {}

        ev = valuation.get("estimatedValue")
        if ev:
            prop["estimated_value"] = _cents(ev)

        equity_pct = valuation.get("equityPercent")
        if equity_pct is not None:
            prop["equity_pct"] = float(equity_pct)

        mortgages_obj = open_lien.get("mortgages") or {}
        first_mort = mortgages_obj.get("first") or {}
        mort_balance = first_mort.get("amount") or first_mort.get("loanAmount")
        if not mort_balance and mortgage_history:
            mort_balance = mortgage_history[0].get("loanAmount")
        if mort_balance:
            prop["open_mortgage_balance"] = _cents(mort_balance)

        junior_total = 0
        for key, val in mortgages_obj.items():
            if key != "first" and isinstance(val, dict):
                amt = val.get("amount") or val.get("loanAmount") or 0
                try:
                    junior_total += int(float(amt) * 100)
                except (ValueError, TypeError):
                    pass
        if junior_total:
            prop["lien_amount"] = junior_total

        prop["pre_foreclosure"] = bool(quick.get("preforeclosure"))

        if quick.get("noticeOfDefault") or foreclosure.get("noticeOfDefaultDate"):
            nod = foreclosure.get("noticeOfDefaultDate") or foreclosure.get("nodDate") or foreclosure.get("recordingDate")
            if nod:
                prop["nod_date"] = str(nod)[:10]

        if quick.get("noticeOfSale") or foreclosure.get("noticeOfSaleDate"):
            nts = foreclosure.get("noticeOfSaleDate") or foreclosure.get("ntsDate")
            if nts:
                prop["nts_date"] = str(nts)[:10]

        auction = foreclosure.get("auctionDate") or foreclosure.get("scheduledAuctionDate")
        if auction:
            prop["auction_date"] = str(auction)[:10]

        beds = building.get("bedroomCount") or building.get("bedrooms")
        if beds:
            prop["beds"] = int(beds)

        baths = building.get("bathroomCount") or building.get("calculatedBathroomCount")
        if baths:
            prop["baths"] = float(baths)

        sqft = building.get("livingAreaSquareFeet") or building.get("totalBuildingAreaSquareFeet")
        if sqft:
            prop["sqft"] = int(sqft)

        year_built = building.get("yearBuilt")
        if year_built:
            prop["year_built"] = int(year_built)

        owner_name = owner_obj.get("fullName")
        if owner_name:
            prop["owner_name"] = str(owner_name).title()

        mail_street = mailing.get("street") or mailing.get("streetNoUnit")
        if mail_street:
            prop["owner_mailing_address"] = str(mail_street)

        mail_state = mailing.get("state")
        if mail_state:
            prop["owner_mailing_state"] = str(mail_state).upper()

        mail_city = mailing.get("city")
        if mail_city:
            prop["owner_mailing_city"] = str(mail_city).title()

        prop["absentee_owner"] = bool(quick.get("absenteeOwner"))

        years = _compute_years_owned(deed_history)
        if years is not None:
            prop["years_owned"] = years

        br_score = batchrank.get("score") or batchrank.get("rank") or batchrank.get("batchRank")
        if br_score is not None:
            prop["batchrank_score"] = int(br_score)

        dom = (
            listing.get("daysOnMarket")
            or (listing.get("activeListing") or {}).get("daysOnMarket")
            or (listing.get("currentListing") or {}).get("daysOnMarket")
        )
        if dom is not None:
            prop["days_on_market"] = int(dom)

        phones = _extract_phones_from_lookup(bd_data)
    else:
        phones = []

    owner_email = None
    if not phones:
        logger.info("enrich_lead no phones from lookup, trying skip_trace address={}", address)
        st_data = skip_trace(address, city, state, zip_code)
        phones = _extract_phones_from_skip_trace(st_data)
        owner_email = _extract_email_from_skip_trace(st_data)

    callable_phones: list[dict[str, Any]] = []
    dnc_blocked_count = 0
    first_callable: str | None = None

    for phone in phones:
        scrub = scrub_phone(phone)
        if scrub.get("dnc"):
            dnc_blocked_count += 1
            continue
        if scrub.get("tcpa"):
            continue
        if scrub.get("callable"):
            callable_phones.append({
                "number": phone,
                "line_type": scrub.get("line_type", "unknown"),
                "valid": scrub.get("valid", False),
            })
            if first_callable is None:
                first_callable = phone

    prop["callable_phones"] = callable_phones
    prop["enriched_at"] = datetime.now(timezone.utc).isoformat()

    lead["callable"] = len(callable_phones) > 0
    lead["dnc_blocked"] = dnc_blocked_count > 0
    if first_callable:
        lead["owner_phone"] = first_callable
    if owner_email:
        lead["owner_email"] = owner_email

    old_score = prop.get("distress_score", 0)
    prop["distress_score"] = calculate_distress_score(prop)

    logger.info(
        "enrich_lead address={} score_before={} score_after={} callable={} dnc_blocked={}",
        address,
        old_score,
        prop["distress_score"],
        len(callable_phones),
        dnc_blocked_count,
    )

    from backend.lib.db import upsert_property, _get_client

    upsert_property(prop)

    client = _get_client()
    lead_update: dict[str, Any] = {
        "callable": lead["callable"],
        "dnc_blocked": lead["dnc_blocked"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if lead.get("owner_phone"):
        lead_update["owner_phone"] = lead["owner_phone"]
    if lead.get("owner_email"):
        lead_update["owner_email"] = lead["owner_email"]

    client.table("leads").update(lead_update).eq("id", lead["id"]).execute()
    logger.debug("enrich_lead lead updated lead_id={}", lead["id"])

    return {**lead, **prop}
