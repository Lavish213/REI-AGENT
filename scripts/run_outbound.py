import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from backend.lib.db import get_leads_for_outbound, schedule_callback
from backend.voice.outbound import call_lead, _is_calling_hours

MAX_CALLS_PER_RUN = 30
CALL_SPACING_SECONDS = 180
SCORE_TIERS = [
    (85, "S-tier"),
    (70, "A-tier"),
    (50, "B-tier"),
]


def _sort_leads(leads: list[dict]) -> list[dict]:
    for lead in leads:
        prop = lead.get("properties") or {}
        distress = prop.get("distress_score") or 0
        engagement = lead.get("engagement_score") or 0
        existing_composite = lead.get("composite_score")
        if existing_composite is None:
            lead["composite_score"] = int(distress * 0.5 + engagement * 0.5)

    def priority(lead: dict) -> tuple:
        callback_at = lead.get("callback_scheduled_at")
        if callback_at:
            try:
                cb_dt = datetime.fromisoformat(callback_at.replace("Z", "+00:00"))
                if cb_dt <= datetime.now(timezone.utc):
                    return (0, 0)
            except Exception:
                pass

        composite = lead.get("composite_score") or 0

        if composite >= 85:
            tier = 1
        elif composite >= 70:
            tier = 2
        else:
            tier = 3

        return (tier, -composite)

    return sorted(leads, key=priority)


def run_campaign() -> dict:
    if not _is_calling_hours():
        logger.warning("run_outbound outside_hours skipping")
        print("Outside calling hours (8am-9pm PT). Exiting.")
        return {"total": 0, "called": 0, "skipped": 0, "failed": 0}

    logger.info("run_outbound campaign starting max_calls={}", MAX_CALLS_PER_RUN)

    all_leads = get_leads_for_outbound(min_score=50)
    sorted_leads = _sort_leads(all_leads)
    batch = sorted_leads[:MAX_CALLS_PER_RUN]

    logger.info("run_outbound eligible={} batch={}", len(all_leads), len(batch))

    called = 0
    skipped = 0
    failed = 0
    results = []

    for i, lead in enumerate(batch):
        if not _is_calling_hours():
            logger.warning("run_outbound hours_ended stopping at call={}", i)
            break

        lead_id = lead["id"]
        prop = lead.get("properties") or {}
        score = prop.get("distress_score", 0)
        address = prop.get("address", "unknown")

        result = call_lead(lead_id)

        if result.get("success"):
            called += 1
            logger.info("outbound_call_placed lead_id={} score={} address={}", lead_id, score, address)
            results.append({
                "lead_id": lead_id,
                "score": score,
                "address": address,
                "sid": result.get("call_sid"),
            })

            if i < len(batch) - 1:
                time.sleep(CALL_SPACING_SECONDS)
        else:
            reason = result.get("reason", "unknown")
            if reason in ("outside_hours", "call_in_progress"):
                skipped += 1
            else:
                failed += 1
            logger.warning("outbound_call_skipped lead_id={} reason={}", lead_id, reason)

    summary = {
        "total_eligible": len(all_leads),
        "batch_size": len(batch),
        "called": called,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }
    logger.info("run_outbound campaign_complete called={} skipped={} failed={}", called, skipped, failed)
    return summary


def main() -> None:
    summary = run_campaign()

    print("\n=== OUTBOUND DIALER RESULTS ===")
    print(f"Total eligible:  {summary['total_eligible']}")
    print(f"Batch size:      {summary['batch_size']}")
    print(f"Calls placed:    {summary['called']}")
    print(f"Skipped:         {summary['skipped']}")
    print(f"Failed:          {summary['failed']}")

    if summary["results"]:
        print("\nCalls placed:")
        for r in summary["results"]:
            print(f"  Score {r['score']:3d} | {r['address']} | {r['lead_id'][:8]}...")

    print("================================\n")


if __name__ == "__main__":
    main()
