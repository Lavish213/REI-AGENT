import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from backend.scout.court_scraper import run_weekly_scrape
from backend.lib.db import get_leads_for_drip_start, start_lead_drip
from backend.alerts.drip import SEQUENCES, _render, _is_in_hours
from backend.alerts.sms import send_drip_sms


def main() -> None:
    logger.info("seed_court_leads starting")

    result = run_weekly_scrape()

    print("\n=== COURT SCRAPE RESULTS ===")
    print(f"Total matched:   {result['total']}")
    print(f"Divorce leads:   {result['divorce']}")
    print(f"Probate leads:   {result['probate']}")
    print(f"Failed to save:  {result['failed']}")

    if result["total"] == 0:
        print("No new court leads found.")
        print("=============================\n")
        return

    new_leads = get_leads_for_drip_start(min_score=0)
    court_leads = [
        l for l in new_leads
        if (l.get("properties") or {}).get("distress_type") in ("divorce", "probate")
    ]

    logger.info("court_leads_for_drip count={}", len(court_leads))

    started = 0
    now = datetime.now(timezone.utc).isoformat()

    for lead in court_leads:
        prop = lead.get("properties") or {}
        distress_type = prop.get("distress_type", "probate")
        sequence_name = "divorce_probate"
        phone = lead.get("owner_phone")

        if not phone:
            continue

        sequence = SEQUENCES.get(sequence_name, [])
        if not sequence:
            continue

        day0_template = sequence[0][1]
        body = _render(day0_template, lead, prop)
        if "reply stop" not in body.lower():
            body = body + " Reply STOP to opt out"

        ok = send_drip_sms(to=phone, body=body, lead_id=lead["id"])
        if ok:
            start_lead_drip(lead["id"], sequence_name, now, initial_day=0)
            started += 1

    print(f"\nDrip started for: {started} court leads")
    print("Sequence: divorce_probate")
    print("=============================\n")


if __name__ == "__main__":
    if not _is_in_hours():
        print("Outside TCPA hours (8am-9pm PT). Run during business hours.")
        sys.exit(1)
    main()
