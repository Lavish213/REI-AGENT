import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=False)

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.scout.scorer import calculate_distress_score, SCORE_CREATE_LEAD, SCORE_HIGH_PRIORITY, SCORE_DRIP_ONLY
from backend.lib.db import upsert_property, insert_lead, get_lead_by_property

CSV_PATH = Path(__file__).parent / "data" / "propwire_export.csv"
LEAD_SCORE_THRESHOLD = SCORE_CREATE_LEAD


def _int_cents(val: str) -> int | None:
    val = val.strip()
    if not val:
        return None
    try:
        return int(float(val) * 100)
    except (ValueError, TypeError):
        return None


def _int_val(val: str) -> int | None:
    val = val.strip()
    if not val:
        return None
    try:
        f = float(val)
        return int(f) if f != 0 else None
    except (ValueError, TypeError):
        return None


def _float_val(val: str) -> float | None:
    val = val.strip()
    if not val:
        return None
    try:
        f = float(val)
        return f if f != 0.0 else None
    except (ValueError, TypeError):
        return None


def _str_val(val: str) -> str | None:
    v = val.strip()
    return v if v else None


def _owner_name(row: dict) -> str | None:
    first = row.get("Owner 1 First Name", "").strip().title()
    last = row.get("Owner 1 Last Name", "").strip().title()
    if first or last:
        return f"{first} {last}".strip()
    return None


def _distress_type(row: dict) -> str:
    status = row.get("Status", "").strip().lower()
    if "foreclosure" in status or "default" in status:
        return "notice_of_default"
    if row.get("Default Amount", "").strip():
        return "pre_foreclosure"
    if row.get("Auction Date", "").strip():
        return "pre_foreclosure"
    if row.get("Vacant?", "").strip() == "1":
        return "vacant"
    prop_city = row.get("City", "").strip().upper()
    mail_city = row.get("Owner Mailing City", "").strip().upper()
    mail_state = row.get("Owner Mailing State", "").strip().upper()
    prop_state = row.get("State", "").strip().upper()
    if mail_city and mail_state and (mail_city != prop_city or mail_state != prop_state):
        return "absentee_owner"
    mortgage = row.get("Open Mortgage Balance", "").strip()
    if not mortgage or float(mortgage or 0) == 0:
        return "free_and_clear"
    return "unknown"


def _parse_row(row: dict) -> dict:
    equity_pct = _float_val(row.get("Estimated Equity Percent", ""))

    return {
        "apn": row.get("APN", "").strip(),
        "address": row.get("Address", "").strip().title(),
        "city": row.get("City", "").strip().title(),
        "state": row.get("State", "").strip().upper(),
        "zip": row.get("Zip", "").strip(),
        "county": _str_val(row.get("County", "")),
        "sqft": _int_val(row.get("Living Square Feet", "")),
        "year_built": _int_val(row.get("Year Built", "")),
        "lot_acres": _float_val(row.get("Lot (Acres)", "")),
        "lot_sqft": _int_val(row.get("Lot (Square Feet)", "")),
        "land_use": _str_val(row.get("Land Use", "")),
        "property_type": _str_val(row.get("Property Type", "")),
        "beds": _int_val(row.get("Bedrooms", "")),
        "baths": _float_val(row.get("Bathrooms", "")),
        "owner_name": _owner_name(row),
        "owner_mailing_address": _str_val(row.get("Owner Mailing Address", "")),
        "owner_mailing_city": _str_val(row.get("Owner Mailing City", "")),
        "owner_mailing_state": _str_val(row.get("Owner Mailing State", "")),
        "ownership_months": _int_val(row.get("Ownership Length (Months)", "")),
        "owner_type": _str_val(row.get("Owner Type", "")),
        "vacant": row.get("Vacant?", "").strip() == "1",
        "estimated_value": _int_cents(row.get("Estimated Value", "")),
        "estimated_equity": _int_cents(row.get("Estimated Equity", "")),
        "equity_pct": equity_pct,
        "open_mortgage_balance": _int_cents(row.get("Open Mortgage Balance", "")),
        "last_sale_date": _str_val(row.get("Last Sale Date", "")),
        "last_sale_amount": _int_cents(row.get("Last Sale Amount", "")),
        "tax_amount": _int_cents(row.get("Tax Amount", "")),
        "assessed_total_value": _int_cents(row.get("Assessed Total Value", "")),
        "market_value": _int_cents(row.get("Market Value", "")),
        "default_amount": _int_cents(row.get("Default Amount", "")),
        "opening_bid": _int_cents(row.get("Opening bid", "")),
        "auction_date": _str_val(row.get("Auction Date", "")),
        "auction_courthouse": _str_val(row.get("Auction Courthouse", "")),
        "distress_type": _distress_type(row),
        "tax_delinquent_amount": _int_cents(row.get("Default Amount", "")),
    }


def main() -> None:
    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found at {CSV_PATH}")
        sys.exit(1)

    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} rows from {CSV_PATH.name}")

    parsed = []
    for row in rows:
        prop = _parse_row(row)
        if not prop["apn"]:
            logger.warning("skipping row with no APN address={}", prop.get("address"))
            continue
        prop["distress_score"] = calculate_distress_score(prop)
        parsed.append(prop)

    print(f"Parsed {len(parsed)} rows with APNs")

    disqualified = [p for p in parsed if not p.get("deal_viable")]
    viable = [p for p in parsed if p.get("deal_viable")]

    print(f"\n--- DISQUALIFIED: {len(disqualified)} ---")
    reason_counts: dict[str, int] = defaultdict(int)
    for p in disqualified:
        raw = p.get("disqualified_reason") or "unknown"
        bucket = raw.split(":")[0]
        reason_counts[bucket] += 1
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    print(f"\n--- SCORE DISTRIBUTION ({len(viable)} viable) ---")
    high = [p for p in viable if p["distress_score"] >= SCORE_HIGH_PRIORITY]
    mid = [p for p in viable if SCORE_CREATE_LEAD <= p["distress_score"] < SCORE_HIGH_PRIORITY]
    drip = [p for p in viable if SCORE_DRIP_ONLY <= p["distress_score"] < SCORE_CREATE_LEAD]
    skip = [p for p in viable if p["distress_score"] < SCORE_DRIP_ONLY]
    print(f"  {SCORE_HIGH_PRIORITY}+  high priority: {len(high)}")
    print(f"  {SCORE_CREATE_LEAD}-{SCORE_HIGH_PRIORITY - 1}  create lead:   {len(mid)}")
    print(f"  {SCORE_DRIP_ONLY}-{SCORE_CREATE_LEAD - 1}  drip only:     {len(drip)}")
    print(f"  <{SCORE_DRIP_ONLY}  skip:           {len(skip)}")

    print(f"\n--- TOP 10 ---")
    for p in sorted(viable, key=lambda x: x["distress_score"], reverse=True)[:10]:
        arv_str = f"ARV=${p.get('estimated_arv', 0) // 100:,}" if p.get("estimated_arv") else "ARV=?"
        print(f"  [{p['distress_score']}] {p['address']}, {p['city']} | {p['distress_type']} | {arv_str}")

    print(f"\n--- UPSERTING {len(parsed)} properties ---")
    upserted = 0
    errors = 0
    for prop in parsed:
        try:
            upsert_property(prop)
            upserted += 1
            if upserted % 50 == 0:
                print(f"  upserted {upserted}/{len(parsed)}...")
        except Exception as e:
            logger.error("upsert failed apn={} error={}", prop.get("apn"), str(e))
            errors += 1

    print(f"Upserted {upserted} ({errors} errors)")

    lead_eligible = [p for p in viable if p["distress_score"] >= LEAD_SCORE_THRESHOLD]
    print(f"\n--- LEADS (score >= {LEAD_SCORE_THRESHOLD}, viable only): {len(lead_eligible)} eligible ---")

    from backend.lib.db import _get_client as _db

    leads_created = 0
    leads_skipped = 0
    for prop in lead_eligible:
        try:
            db_row = _db().table("properties").select("id").eq("apn", prop["apn"]).limit(1).execute()
            if not db_row.data:
                logger.warning("property not found after upsert apn={}", prop["apn"])
                continue
            property_id = db_row.data[0]["id"]
            existing = get_lead_by_property(property_id)
            if existing:
                leads_skipped += 1
                continue
            insert_lead(property_id)
            leads_created += 1
            print(f"  lead: {prop['address']}, {prop['city']} (score={prop['distress_score']})")
        except Exception as e:
            logger.error("lead creation failed apn={} error={}", prop.get("apn"), str(e))

    print(f"\nLeads created: {leads_created} (skipped existing: {leads_skipped})")
    print(f"\nDone. {upserted} properties seeded, {leads_created} leads created.")


if __name__ == "__main__":
    main()
