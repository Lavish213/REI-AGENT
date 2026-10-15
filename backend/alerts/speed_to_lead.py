import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from backend.lib.db import (
    get_lead_with_property,
    update_lead_speed_to_lead,
    start_lead_drip,
)

PACIFIC = ZoneInfo("America/Los_Angeles")
_scheduler: BackgroundScheduler | None = None


def _is_calling_hours() -> bool:
    now_pt = datetime.now(PACIFIC)
    start = int(os.environ.get("CALLING_HOURS_START", 8))
    end = int(os.environ.get("CALLING_HOURS_END", 21))
    return start <= now_pt.hour < end


def _next_9am_pt() -> datetime:
    now_pt = datetime.now(PACIFIC)
    target = now_pt.replace(hour=9, minute=0, second=0, microsecond=0)
    if now_pt.hour >= 9:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


def _next_10am_pt() -> datetime:
    now_pt = datetime.now(PACIFIC)
    target = now_pt.replace(hour=10, minute=0, second=0, microsecond=0)
    if now_pt.hour >= 10:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


def _next_1pm_day2_pt() -> datetime:
    now_pt = datetime.now(PACIFIC)
    target = (
        now_pt.replace(hour=13, minute=0, second=0, microsecond=0)
        + timedelta(days=2)
    )
    return target.astimezone(timezone.utc)


def _next_2pm_day2_pt() -> datetime:
    now_pt = datetime.now(PACIFIC)
    target = (
        now_pt.replace(hour=14, minute=0, second=0, microsecond=0)
        + timedelta(days=2)
    )
    return target.astimezone(timezone.utc)


def _contact_made(lead: dict) -> bool:
    outcome = lead.get("last_call_outcome", "")
    if outcome in ("answered", "appointment_booked"):
        return True
    replies = lead.get("drip_replies") or []
    return len(replies) > 0


def _get_first_name(lead: dict, prop: dict) -> str:
    name = lead.get("first_name") or lead.get("owner_name") or (prop or {}).get("owner_name") or ""
    parts = name.strip().split()
    return parts[0] if parts else "there"


def _run_touch(lead_id: str, touch_number: int) -> dict:
    lead = get_lead_with_property(lead_id)
    if not lead or lead.get("opted_out") or lead.get("dnc_blocked") or lead.get("speed_to_lead_completed") or _contact_made(lead):
        return {"status": "skipped"}
    if not lead.get("owner_phone") or lead.get("callable") is not True:
        return {"status": "skipped", "reason": "contact_authority_unavailable"}
    from backend.voice.outbound import call_lead
    result = call_lead(lead_id, bypass_cooldown=False)
    if result.get("success") is not True:
        return {"status": "skipped", "reason": result.get("reason") or result.get("error") or "call_not_accepted"}
    update_lead_speed_to_lead(lead_id, (lead.get("speed_to_lead_attempts") or 0) + 1, completed=touch_number == 5)
    if touch_number == 5:
        from backend.alerts.drip import get_sequence_name
        start_lead_drip(lead_id, get_sequence_name((lead.get("properties") or {}).get("distress_type")), datetime.now(timezone.utc).isoformat(), initial_day=-1)
    return {"status": "completed"}


def run_speed_to_lead(lead_id: str) -> None:
    global _scheduler

    lead = get_lead_with_property(lead_id)
    if not lead:
        logger.warning("stl run lead_not_found lead_id={}", lead_id)
        return

    if lead.get("speed_to_lead_completed"):
        logger.debug("stl already_completed lead_id={}", lead_id)
        return

    prop = lead.get("properties") or {}
    if prop.get("distress_score", 0) < 50:
        logger.debug("stl score_too_low lead_id={}", lead_id)
        return

    from backend.lib import db
    now = datetime.now(timezone.utc)
    db.stage_speed_touches(lead_id, [now, now + timedelta(minutes=30), now + timedelta(hours=2), _next_10am_pt(), _next_1pm_day2_pt()])
    recover_speed_touches()


def recover_speed_touches(limit=20):
    from backend.lib import db
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Bounded recovery batch required")
    db.recover_inbound_email()
    db.recover_email_resumptions()
    outcomes = {"completed": 0, "skipped": 0, "deferred": 0, "quarantined": 0}
    for _ in range(limit):
        job = db.claim_workflow_job()
        if job is None:
            break
        try:
            if not _is_calling_hours():
                db.finish_workflow_job(job['id'], job['lease'], 'pending', due=_next_9am_pt().timestamp())
                outcomes['deferred'] += 1
                continue
            lead = get_lead_with_property(job['lead_id'])
            if not lead or lead.get('opted_out') or lead.get('dnc_blocked') or lead.get('speed_to_lead_completed') or _contact_made(lead):
                state = 'skipped'
            else:
                state = _run_touch(job['lead_id'], job['payload']['touch'])['status']
            if not db.finish_workflow_job(job['id'], job['lease'], state):
                raise RuntimeError("Workflow outcome ownership lost")
            outcomes[state] += 1
        except Exception as error:
            db.finish_workflow_job(job['id'], job['lease'], 'quarantined', type(error).__name__)
            outcomes['quarantined'] += 1
            logger.error("speed_touch_quarantined job_id={} type={}", job['id'], type(error).__name__)
    return outcomes


def start_speed_to_lead_scheduler(
    existing_scheduler: BackgroundScheduler | None = None,
) -> BackgroundScheduler:
    global _scheduler
    if existing_scheduler is not None:
        _scheduler = existing_scheduler
        _scheduler.add_job(recover_speed_touches, "interval", seconds=30, id="durable_speed_recovery", replace_existing=True, max_instances=1)
        logger.info("stl using_existing_scheduler")
        return _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="America/Los_Angeles")
    _scheduler.add_job(recover_speed_touches, "interval", seconds=30, id="durable_speed_recovery", replace_existing=True, max_instances=1)
    _scheduler.start()
    logger.info("stl scheduler started")
    return _scheduler


def stop_speed_to_lead_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("stl scheduler stopped")
