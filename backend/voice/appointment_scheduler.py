from datetime import datetime, timedelta, timezone

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from backend.lib.db import (
    get_pending_appointment_leads,
    update_appt_reminder_flags,
    update_lead_stage,
)
from backend.alerts.sms import send_drip_sms

PACIFIC = pytz.timezone("America/Los_Angeles")

_scheduler: BackgroundScheduler | None = None


def _get_first_name(lead: dict) -> str:
    owner = lead.get("owner_name") or (lead.get("properties") or {}).get("owner_name") or ""
    parts = owner.strip().split()
    return parts[0] if parts else "there"


def _send_reminder(lead: dict, body: str) -> bool:
    phone = lead.get("owner_phone")
    if not phone:
        return False
    return send_drip_sms(to=phone, body=body, lead_id=lead["id"])


def _tick() -> None:
    try:
        leads = get_pending_appointment_leads()
    except Exception as e:
        logger.error("appt_scheduler get_leads error={}", str(e))
        return

    now_utc = datetime.now(timezone.utc)
    now_pt = datetime.now(PACIFIC)

    for lead in leads:
        try:
            _process_lead(lead, now_utc, now_pt)
        except Exception as e:
            logger.error("appt_scheduler process error lead_id={} error={}", lead.get("id"), str(e))


def _process_lead(lead: dict, now_utc: datetime, now_pt: datetime) -> None:
    lead_id = lead["id"]
    appt_raw = lead.get("appointment_at")
    if not appt_raw:
        return

    appt_dt = datetime.fromisoformat(appt_raw.replace("Z", "+00:00"))
    if appt_dt.tzinfo is None:
        appt_dt = appt_dt.replace(tzinfo=timezone.utc)

    appt_pt = appt_dt.astimezone(PACIFIC)
    first_name = _get_first_name(lead)
    prop = lead.get("properties") or {}
    address = prop.get("address", "your property")
    time_display = appt_pt.strftime("%-I:%M %p")

    day_before_sent = lead.get("appt_day_before_sent", False)
    morning_sent = lead.get("appt_morning_sent", False)
    no_show_sent = lead.get("appt_no_show_sent", False)

    hours_until = (appt_dt - now_utc).total_seconds() / 3600
    hours_since = (now_utc - appt_dt).total_seconds() / 3600

    if not day_before_sent and 12 <= hours_until <= 36:
        body = (
            f"Hey {first_name}! Sophia from San Joaquin House Buyers \u2014 "
            f"just a reminder we're stopping by {address} "
            f"tomorrow at {time_display}. "
            f"If anything comes up just text me here. "
            f"Looking forward to it!"
        )
        if _send_reminder(lead, body):
            update_appt_reminder_flags(lead_id, day_before=True)
            logger.info("appt_day_before_sent lead_id={}", lead_id)

    elif not morning_sent and 0 < hours_until <= 12 and now_pt.hour >= 8:
        body = (
            f"Hey {first_name}! Sophia \u2014 we'll be at {address} "
            f"at {time_display} today. See you soon!"
        )
        if _send_reminder(lead, body):
            update_appt_reminder_flags(lead_id, morning=True)
            logger.info("appt_morning_sent lead_id={}", lead_id)

    elif not no_show_sent and hours_since >= 2:
        body = (
            f"Hey {first_name} \u2014 Sophia here. We came by "
            f"{address} today \u2014 did we miss you? "
            f"No worries at all, just want to make sure we connect. "
            f"When works for a reschedule?"
        )
        if _send_reminder(lead, body):
            update_appt_reminder_flags(lead_id, no_show=True)
            logger.info("appt_no_show_sent lead_id={}", lead_id)


def start_appointment_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="America/Los_Angeles")
    _scheduler.add_job(_tick, "interval", minutes=15, id="appt_tick", replace_existing=True)
    _scheduler.start()
    logger.info("appointment_scheduler started interval=15min")


def stop_appointment_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("appointment_scheduler stopped")
