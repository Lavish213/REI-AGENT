import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from backend.lib.db import get_leads_for_drip_start, start_lead_drip
from backend.alerts.drip import get_sequence_name, SEQUENCES, _render, _is_in_hours
from backend.alerts.sms import send_drip_sms

MIN_SCORE = 35


def main() -> None:
    logger.info("start_drip beginning min_score={}", MIN_SCORE)

    leads = get_leads_for_drip_start(MIN_SCORE)
    logger.info("eligible leads count={}", len(leads))

    counts: dict[str, int] = {}
    sent = 0
    skipped = 0

    now = datetime.now(timezone.utc).isoformat()

    for lead in leads:
        prop = lead.get("properties") or {}
        distress_type = prop.get("distress_type")
        sequence_name = get_sequence_name(distress_type)
        phone = lead.get("owner_phone")

        if not phone:
            skipped += 1
            continue

        sequence = SEQUENCES.get(sequence_name, SEQUENCES["seller"])
        if not sequence:
            skipped += 1
            continue

        day0_template = sequence[0][1]
        body = _render(day0_template, lead, prop)

        if "reply stop" not in body.lower():
            body = body + " Reply STOP to opt out"

        lead_id = lead["id"]

        ok = send_drip_sms(to=phone, body=body, lead_id=lead_id)

        if ok:
            start_lead_drip(lead_id, sequence_name, now, initial_day=0)
            counts[sequence_name] = counts.get(sequence_name, 0) + 1
            sent += 1
        else:
            skipped += 1

    logger.info("start_drip complete sent={} skipped={}", sent, skipped)

    print("\n=== DRIP SEEDING RESULTS ===")
    print(f"Total leads processed: {len(leads)}")
    print(f"Messages sent:         {sent}")
    print(f"Skipped (no phone):    {skipped}")
    print("\nLeads per sequence:")
    for seq, count in sorted(counts.items()):
        print(f"  {seq}: {count}")
    print("============================\n")


if __name__ == "__main__":
    if not _is_in_hours():
        print("Outside TCPA hours (8am-9pm PT). Run during business hours.")
        sys.exit(1)
    main()
