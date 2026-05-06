from datetime import datetime, timezone
from loguru import logger

from backend.lib.db import (
    get_calls_for_lead,
    get_sms_for_lead,
    update_lead_engagement_scores,
    _get_client,
)

RECENCY_BANDS = [
    (7, 30),
    (30, 20),
    (90, 10),
    (float("inf"), 2),
]


def _recency_score(lead: dict) -> int:
    last_raw = lead.get("last_called_at") or lead.get("last_sms_at")
    if not last_raw:
        return 0
    try:
        last = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - last).days
        for threshold, score in RECENCY_BANDS:
            if days <= threshold:
                return score
    except Exception:
        pass
    return 0


def _intensity_score(lead: dict, calls: list, sms_messages: list) -> int:
    if lead.get("appointment_at"):
        return 40

    inbound_calls = [c for c in calls if c.get("direction") == "inbound"]
    if inbound_calls:
        return 40

    drip_replies = lead.get("drip_replies") or []
    hot_replies = [r for r in drip_replies if r.get("type") == "hot"]
    if hot_replies:
        return 30

    long_outbound = [
        c for c in calls
        if c.get("direction") == "outbound"
        and (c.get("call_duration_seconds") or 0) >= 120
    ]
    if long_outbound:
        return 20

    neutral_replies = [r for r in drip_replies if r.get("type") == "other"]
    inbound_sms = [m for m in sms_messages if m.get("direction") == "inbound"]
    if neutral_replies or inbound_sms:
        return 15

    short_outbound = [
        c for c in calls
        if c.get("direction") == "outbound"
        and 0 < (c.get("call_duration_seconds") or 0) < 120
    ]
    if short_outbound:
        return 10

    return 0


def _pattern_score(lead: dict, calls: list, sms_messages: list) -> int:
    inbound_calls = [c for c in calls if c.get("direction") == "inbound"]
    if inbound_calls:
        return 30

    answered_outbound = [
        c for c in calls
        if c.get("direction") == "outbound"
        and (c.get("call_duration_seconds") or 0) > 5
    ]
    if len(answered_outbound) >= 3:
        return 30

    drip_replies = lead.get("drip_replies") or []
    inbound_sms = [m for m in sms_messages if m.get("direction") == "inbound"]

    if len(drip_replies) >= 2 or len(inbound_sms) >= 2:
        return 25

    if len(answered_outbound) >= 1:
        return 15

    if len(drip_replies) >= 1 or len(inbound_sms) >= 1:
        return 10

    return 0


def score_lead_engagement(lead: dict, calls: list, sms_messages: list) -> dict:
    recency = _recency_score(lead)
    intensity = _intensity_score(lead, calls, sms_messages)
    pattern = _pattern_score(lead, calls, sms_messages)
    engagement = recency + intensity + pattern

    prop = lead.get("properties") or {}
    distress = prop.get("distress_score", 0)
    composite = round((distress * 0.5) + (engagement * 0.5), 2)

    return {
        "recency_score": recency,
        "intensity_score": intensity,
        "pattern_score": pattern,
        "engagement_score": engagement,
        "composite_score": composite,
    }


def refresh_engagement_for_lead(lead_id: str) -> dict | None:
    try:
        client = _get_client()
        resp = (
            client.table("leads")
            .select("*, properties(*)")
            .eq("id", lead_id)
            .limit(1)
            .execute()
        )
        if not resp.data:
            return None
        lead = resp.data[0]
        calls = get_calls_for_lead(lead_id)
        sms_messages = get_sms_for_lead(lead_id)
        scores = score_lead_engagement(lead, calls, sms_messages)
        update_lead_engagement_scores(
            lead_id,
            scores["recency_score"],
            scores["intensity_score"],
            scores["pattern_score"],
            scores["composite_score"],
        )
        logger.info(
            "engagement_refreshed lead_id={} composite={}",
            lead_id,
            scores["composite_score"],
        )
        return scores
    except Exception as e:
        logger.error("refresh_engagement_failed lead_id={} error={}", lead_id, str(e))
        return None


def refresh_all_engagement() -> int:
    try:
        client = _get_client()
        leads = (
            client.table("leads")
            .select("*, properties(*)")
            .eq("opted_out", False)
            .execute()
        )
        count = 0
        for lead in leads.data or []:
            lead_id = lead["id"]
            try:
                calls = get_calls_for_lead(lead_id)
                sms_messages = get_sms_for_lead(lead_id)
                scores = score_lead_engagement(lead, calls, sms_messages)
                update_lead_engagement_scores(
                    lead_id,
                    scores["recency_score"],
                    scores["intensity_score"],
                    scores["pattern_score"],
                    scores["composite_score"],
                )
                count += 1
            except Exception as e:
                logger.error("refresh_engagement_lead_failed lead_id={} error={}", lead_id, str(e))
        logger.info("refresh_all_engagement count={}", count)
        return count
    except Exception as e:
        logger.error("refresh_all_engagement_failed error={}", str(e))
        return 0
