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
from backend.alerts.sms import send_drip_sms

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
    owner = lead.get("owner_name") or (prop or {}).get("owner_name") or ""
    parts = owner.strip().split()
    return parts[0] if parts else "there"


def _run_touch(lead_id: str, touch_number: int) -> None:
    lead = get_lead_with_property(lead_id)
    if not lead:
        logger.warning("stl touch lead_not_found lead_id={} touch={}", lead_id, touch_number)
        return

    if lead.get("opted_out") or lead.get("dnc_blocked"):
        logger.info("stl touch skipped opted_out lead_id={} touch={}", lead_id, touch_number)
        return

    if lead.get("speed_to_lead_completed"):
        return

    if touch_number > 1 and _contact_made(lead):
        logger.info("stl contact_made skipping touch={} lead_id={}", touch_number, lead_id)
        return

    prop = lead.get("properties") or {}
    phone = lead.get("owner_phone")
    first_name = _get_first_name(lead, prop)
    address = prop.get("address", "your property")
    current_attempts = lead.get("speed_to_lead_attempts") or 0

    if touch_number == 1:
        update_lead_speed_to_lead(lead_id, current_attempts + 1, completed=False)
        if _is_calling_hours() and phone:
            from backend.voice.outbound import call_lead
            result = call_lead(lead_id, bypass_cooldown=True)
            logger.info("stl touch=1 call lead_id={} success={}", lead_id, result.get("success"))
        elif phone:
            body = (
                f"Hey — are you the owner of {address}? "
                "This is Sophia, San Joaquin House Buyers."
            )
            send_drip_sms(to=phone, body=body, lead_id=lead_id)
            logger.info("stl touch=1 sms sent lead_id={}", lead_id)

    elif touch_number == 2:
        update_lead_speed_to_lead(lead_id, current_attempts + 1, completed=False)
        if phone:
            from backend.voice.outbound import call_lead
            result = call_lead(lead_id, bypass_cooldown=True)
            logger.info("stl touch=2 vm_call lead_id={} success={}", lead_id, result.get("success"))

    elif touch_number == 3:
        update_lead_speed_to_lead(lead_id, current_attempts + 1, completed=False)
        if _is_calling_hours() and phone:
            from backend.voice.outbound import call_lead
            result = call_lead(lead_id, bypass_cooldown=True)
            logger.info("stl touch=3 call lead_id={} success={}", lead_id, result.get("success"))

    elif touch_number == 4:
        update_lead_speed_to_lead(lead_id, current_attempts + 1, completed=False)
        if phone:
            from backend.voice.outbound import call_lead
            result = call_lead(lead_id, bypass_cooldown=True)
            logger.info("stl touch=4 call lead_id={} success={}", lead_id, result.get("success"))
            body = (
                f"Hey {first_name} — Sophia with San Joaquin House Buyers. "
                f"Tried to reach you about {address}. "
                "We buy as-is, cash, fast close. Worth a quick chat? Call or text back."
            )
            send_drip_sms(to=phone, body=body, lead_id=lead_id)
            logger.info("stl touch=4 sms sent lead_id={}", lead_id)

    elif touch_number == 5:
        update_lead_speed_to_lead(lead_id, current_attempts + 1, completed=True)
        if phone:
            from backend.voice.outbound import call_lead
            result = call_lead(lead_id, bypass_cooldown=True)
            logger.info("stl touch=5 vm_call lead_id={} success={}", lead_id, result.get("success"))

        now = datetime.now(timezone.utc).isoformat()
        from backend.alerts.drip import get_sequence_name
        sequence = get_sequence_name(prop.get("distress_type"))
        start_lead_drip(lead_id, sequence, now, initial_day=-1)
        logger.info("stl entering_drip lead_id={} sequence={}", lead_id, sequence)


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

    _run_touch(lead_id, 1)

    if _scheduler is None:
        logger.warning("stl scheduler not running lead_id={} touches 2-5 skipped", lead_id)
        return

    now_utc = datetime.now(timezone.utc)
    touch2_at = now_utc + timedelta(minutes=30)
    touch3_at = now_utc + timedelta(hours=2)
    touch4_at = _next_9am_pt()
    touch5_at = _next_2pm_day2_pt()
    prefix = f"stl_{lead_id}"

    _scheduler.add_job(
        _run_touch,
        "date",
        run_date=touch2_at,
        args=[lead_id, 2],
        id=f"{prefix}_t2",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_touch,
        "date",
        run_date=touch3_at,
        args=[lead_id, 3],
        id=f"{prefix}_t3",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_touch,
        "date",
        run_date=touch4_at,
        args=[lead_id, 4],
        id=f"{prefix}_t4",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_touch,
        "date",
        run_date=touch5_at,
        args=[lead_id, 5],
        id=f"{prefix}_t5",
        replace_existing=True,
    )
    logger.info(
        "stl scheduled lead_id={} t2={} t3={} t4={} t5={}",
        lead_id,
        touch2_at.isoformat(),
        touch3_at.isoformat(),
        touch4_at.isoformat(),
        touch5_at.isoformat(),
    )


def start_speed_to_lead_scheduler(
    existing_scheduler: BackgroundScheduler | None = None,
) -> BackgroundScheduler:
    global _scheduler
    if existing_scheduler is not None:
        _scheduler = existing_scheduler
        logger.info("stl using_existing_scheduler")
        return _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="America/Los_Angeles")
    _scheduler.start()
    logger.info("stl scheduler started")
    return _scheduler


def stop_speed_to_lead_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("stl scheduler stopped")
