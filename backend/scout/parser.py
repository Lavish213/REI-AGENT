import csv
import os
from typing import Any

from loguru import logger


FIELD_MAP = {
    "apn": ["apn", "parcel_number", "assessor_parcel_number", "parcel"],
    "address": ["property_address", "address", "situs_address", "street_address"],
    "city": ["city", "property_city", "situs_city"],
    "state": ["state", "property_state", "situs_state"],
    "zip": ["zip", "zipcode", "zip_code", "property_zip", "postal_code"],
    "county": ["county", "county_name"],
    "owner_name": ["owner_name", "owner", "owner_1", "mailing_owner"],
    "beds": ["beds", "bedrooms", "bed_count", "no_bedrooms"],
    "baths": ["baths", "bathrooms", "bath_count", "no_bathrooms"],
    "sqft": ["sqft", "square_feet", "living_sqft", "building_sqft", "gross_sqft"],
    "year_built": ["year_built", "yr_built", "build_year"],
    "distress_type": ["distress_type", "lead_type", "list_type", "tag"],
    "equity_pct": ["equity_pct", "equity_percent", "equity_%", "estimated_equity_percent"],
    "lien_amount": ["lien_amount", "total_liens", "lien_balance"],
    "tax_delinquent_amount": ["tax_delinquent_amount", "delinquent_tax", "tax_delinquency"],
    "nod_date": ["nod_date", "notice_of_default_date", "nod_recording_date"],
    "auction_date": ["auction_date", "foreclosure_auction_date", "trustee_sale_date"],
    "last_sale_price": ["last_sale_price", "last_sold_price", "prior_sale_price"],
}


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "").replace("/", "_")


def _find_value(row: dict[str, str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in row:
            val = row[candidate].strip()
            if val and val.lower() not in ("", "n/a", "null", "none", "-"):
                return val
    return None


def _parse_int(val: str | None) -> int | None:
    if val is None:
        return None
    cleaned = val.replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def _parse_float(val: str | None) -> float | None:
    if val is None:
        return None
    cleaned = val.replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_date(val: str | None) -> str | None:
    if val is None:
        return None
    val = val.strip()
    if not val or val.lower() in ("n/a", "null", "none", "-"):
        return None
    return val


def _normalize_distress_type(raw: str | None) -> str:
    if raw is None:
        return "unknown"
    raw_lower = raw.lower()
    if "pre" in raw_lower and "foreclosure" in raw_lower:
        return "pre_foreclosure"
    if "tax" in raw_lower and ("lien" in raw_lower or "delinquent" in raw_lower):
        return "tax_lien"
    if "nod" in raw_lower or "notice of default" in raw_lower:
        return "notice_of_default"
    if "absentee" in raw_lower:
        return "absentee_owner"
    if "vacant" in raw_lower:
        return "vacant"
    if "failed" in raw_lower or "expired" in raw_lower:
        return "failed_listing"
    if "code" in raw_lower and "violation" in raw_lower:
        return "code_violation"
    if "free" in raw_lower and "clear" in raw_lower:
        return "free_and_clear"
    return raw_lower.replace(" ", "_")


def _to_cents(val: str | None) -> int | None:
    parsed = _parse_float(val)
    if parsed is None:
        return None
    return int(parsed * 100)


def parse_csv(file_path: str) -> list[dict[str, Any]]:
    if not os.path.exists(file_path):
        logger.error("CSV file not found: {}", file_path)
        return []

    properties = []
    seen_apns: set[str] = set()
    skipped = 0
    parsed = 0

    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            logger.error("CSV has no headers: {}", file_path)
            return []

        normalized_fieldnames = {
            _normalize_header(h): h
            for h in reader.fieldnames
            if h is not None
        }

        for row in reader:
            normalized_row = {
                _normalize_header(k): v
                for k, v in row.items()
                if k is not None
            }

            address_raw = _find_value(normalized_row, FIELD_MAP["address"])
            if not address_raw:
                skipped += 1
                continue

            apn_raw = _find_value(normalized_row, FIELD_MAP["apn"])
            apn = apn_raw.replace("-", "").replace(" ", "").upper() if apn_raw else None

            if apn and apn in seen_apns:
                skipped += 1
                continue
            if apn:
                seen_apns.add(apn)

            distress_raw = _find_value(normalized_row, FIELD_MAP["distress_type"])
            equity_raw = _find_value(normalized_row, FIELD_MAP["equity_pct"])

            prop = {
                "apn": apn,
                "address": address_raw,
                "city": _find_value(normalized_row, FIELD_MAP["city"]),
                "state": _find_value(normalized_row, FIELD_MAP["state"]) or "CA",
                "zip": _find_value(normalized_row, FIELD_MAP["zip"]),
                "county": _find_value(normalized_row, FIELD_MAP["county"]) or "San Joaquin",
                "owner_name": _find_value(normalized_row, FIELD_MAP["owner_name"]),
                "beds": _parse_int(_find_value(normalized_row, FIELD_MAP["beds"])),
                "baths": _parse_float(_find_value(normalized_row, FIELD_MAP["baths"])),
                "sqft": _parse_int(_find_value(normalized_row, FIELD_MAP["sqft"])),
                "year_built": _parse_int(_find_value(normalized_row, FIELD_MAP["year_built"])),
                "distress_type": _normalize_distress_type(distress_raw),
                "equity_pct": _parse_float(equity_raw),
                "lien_amount": _to_cents(_find_value(normalized_row, FIELD_MAP["lien_amount"])),
                "tax_delinquent_amount": _to_cents(_find_value(normalized_row, FIELD_MAP["tax_delinquent_amount"])),
                "nod_date": _parse_date(_find_value(normalized_row, FIELD_MAP["nod_date"])),
                "auction_date": _parse_date(_find_value(normalized_row, FIELD_MAP["auction_date"])),
                "last_sale_price": _to_cents(_find_value(normalized_row, FIELD_MAP["last_sale_price"])),
                "status": "new",
            }

            properties.append(prop)
            parsed += 1

    logger.info("parse_csv file={} parsed={} skipped={}", file_path, parsed, skipped)
    return properties
