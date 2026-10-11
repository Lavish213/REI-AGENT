from __future__ import annotations

import os
import time

from loguru import logger

from backend.lib.db import campaign_is_running, get_leads_for_outbound
from backend.voice.outbound import call_lead


def run_campaign() -> dict:
    summary = {"called": 0, "skipped": 0, "failed": 0}
    if not campaign_is_running():
        return summary
    leads = get_leads_for_outbound(min_score=50)
    leads.sort(key=lambda lead: lead.get("composite_score") or 0, reverse=True)
    limit = min(30, max(1, int(os.environ.get("CAMPAIGN_BATCH_LIMIT", "30"))))
    spacing = max(1, int(os.environ.get("CAMPAIGN_CALL_SPACING_SECONDS", "180")))
    for lead in leads[:limit]:
        if not campaign_is_running():
            break
        result = call_lead(lead["id"])
        if result.get("success"):
            summary["called"] += 1
            time.sleep(spacing)
        else:
            summary["skipped"] += 1
    logger.info("campaign_finished results={}", summary)
    return summary
