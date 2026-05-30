import os
from datetime import datetime, timezone

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from backend.lib.db import (
    get_active_email_leads,
    update_lead_email_progress,
    pause_lead_email,
    complete_lead_email,
)

PACIFIC = pytz.timezone("America/Los_Angeles")

EMAIL_SEQUENCES: list[tuple[int, str, str]] = [
    (
        0,
        "Interested in {address}",
        (
            "Hi {first_name} — I'm a local buyer in Stockton and came across your property "
            "on {address}. We pay cash, close fast, and buy as-is. Worth a quick conversation?\n\n"
            "- Sophia\n"
            "San Joaquin House Buyers\n"
            "{phone}"
        ),
    ),
    (
        7,
        "Market update for {neighborhood}",
        (
            "Hey {first_name} — Sophia again with San Joaquin House Buyers.\n\n"
            "Properties in {neighborhood} have been moving quickly lately. "
            "Your place on {address} might be in a stronger position than you think.\n\n"
            "Still open to a quick conversation?\n\n"
            "- Sophia\n"
            "{phone}"
        ),
    ),
    (
        21,
        "We just closed nearby",
        (
            "Hey {first_name} — Sophia with San Joaquin House Buyers.\n\n"
            "We just closed on a property similar to yours in {neighborhood} last month. "
            "Owner walked away in 18 days — no repairs, no agent fees, zero hassle.\n\n"
            "Still open to a conversation about {address}?\n\n"
            "- Sophia\n"
            "{phone}"
        ),
    ),
    (
        45,
        "Last note from me",
        (
            "Hey {first_name} — Sophia, last note from me on {address}.\n\n"
            "If a fast cash offer, easy close, and no hassle ever sounds right — "
            "just reply and I'll get you a number. Hope you're doing well.\n\n"
            "- Sophia\n"
            "San Joaquin House Buyers\n"
            "{phone}"
        ),
    ),
]

_scheduler: BackgroundScheduler | None = None


def _get_first_name(lead: dict, prop: dict) -> str:
    owner = lead.get("owner_name") or (prop or {}).get("owner_name") or ""
    parts = owner.strip().split()
    return parts[0] if parts else "there"


def _render(template: str, lead: dict, prop: dict) -> str:
    prop = prop or {}
    return template.format(
        first_name=_get_first_name(lead, prop),
        address=prop.get("address", "your property"),
        neighborhood=prop.get("city", "your area"),
        phone=os.environ.get("SIGNALWIRE_PHONE", ""),
    )


def _is_in_hours() -> bool:
    now_pt = datetime.now(PACIFIC)
    start = int(os.environ.get("CALLING_HOURS_START", 8))
    end = int(os.environ.get("CALLING_HOURS_END", 21))
    return start <= now_pt.hour < end


def send_email(to: str, subject: str, body: str) -> bool:
    sendgrid_key = os.environ.get("SENDGRID_API_KEY", "")
    if not sendgrid_key or sendgrid_key.startswith("placeholder"):
        logger.warning("SendGrid not configured skipping email to={}", to)
        return False

    try:
        import httpx
        response = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {sendgrid_key}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": to}]}],
                "from": {
                    "email": os.environ.get("BUSINESS_EMAIL", "sophia@sanjoaquinhousebuyers.com"),
                    "name": os.environ.get("BUSINESS_NAME", "San Joaquin House Buyers"),
                },
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
                "reply_to": {
                    "email": os.environ.get("BUSINESS_EMAIL", "sophia@sanjoaquinhousebuyers.com"),
                },
            },
            timeout=10,
        )
        response.raise_for_status()
        logger.info("email sent to={} subject={}", to, subject)
        return True
    except Exception as e:
        logger.error("email failed to={} error={}", to, str(e))
        return False


def send_drip_email(to: str, subject: str, body: str, lead_id: str) -> bool:
    sent = send_email(to, subject, body)
    if sent:
        logger.info("drip_email sent to={} lead_id={} subject={}", to, lead_id, subject)
    return sent


def _process_email_lead(lead: dict) -> None:
    lead_id = lead["id"]
    email = lead.get("owner_email")
    if not email:
        return

    last_email_raw = lead.get("last_email_at")
    if last_email_raw:
        last_sent = datetime.fromisoformat(last_email_raw.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last_sent).total_seconds()
        if elapsed < 86400:
            return

    current_day = lead.get("email_day")
    if current_day is None:
        current_day = -1

    prop = lead.get("properties") or {}
    now_utc = datetime.now(timezone.utc)

    if lead.get("drip_started_at"):
        started = datetime.fromisoformat(
            lead["drip_started_at"].replace("Z", "+00:00")
        )
        days_elapsed = (now_utc - started).days
    else:
        days_elapsed = 0

    next_step: tuple[int, str, str] | None = None
    for day, subject_tmpl, body_tmpl in EMAIL_SEQUENCES:
        if day > current_day and days_elapsed >= day:
            next_step = (day, subject_tmpl, body_tmpl)
            break

    if next_step is None:
        all_sent = all(day <= current_day for day, _, _ in EMAIL_SEQUENCES)
        if all_sent:
            complete_lead_email(lead_id)
        return

    day, subject_tmpl, body_tmpl = next_step
    subject = _render(subject_tmpl, lead, prop)
    body = _render(body_tmpl, lead, prop)

    sent = send_drip_email(to=email, subject=subject, body=body, lead_id=lead_id)
    if sent:
        update_lead_email_progress(lead_id, day, now_utc.isoformat())
        logger.info("email_drip_sent lead_id={} day={}", lead_id, day)


def handle_email_reply(lead_id: str, from_email: str, body: str) -> None:
    from backend.alerts.sms import send_alert_to_owner
    from backend.lib.db import _get_client

    pause_lead_email(lead_id)

    client = _get_client()
    resp = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    )
    lead = resp.data[0] if resp.data else {}
    prop = (lead.get("properties") or {}) if lead else {}
    first_name = _get_first_name(lead, prop)
    address = prop.get("address", "unknown property")

    alert = (
        f"\U0001f4e7 EMAIL REPLY from {first_name} re {address}:\n"
        f"From: {from_email}\n"
        f"'{body[:300]}'"
    )
    send_alert_to_owner(alert)
    logger.info("email_reply_handled lead_id={} from={}", lead_id, from_email)


def _email_tick() -> None:
    if not _is_in_hours():
        return
    try:
        leads = get_active_email_leads()
    except Exception as e:
        logger.error("email_tick get_leads error={}", str(e))
        return

    for lead in leads:
        try:
            _process_email_lead(lead)
        except Exception as e:
            logger.error("email_tick process error lead_id={} error={}", lead.get("id"), str(e))


def send_walkthrough_confirmation_email(
    to: str,
    owner_name: str,
    address: str,
    appointment_str: str,
) -> bool:
    subject = f"Walkthrough Confirmed — {address}"
    body = (
        f"Hey {owner_name},\n\n"
        f"Just confirming your walkthrough appointment:\n\n"
        f"Address: {address}\n"
        f"Date/Time: {appointment_str}\n\n"
        f"Alanzo will be there to take a look. The walkthrough usually takes about 20 minutes.\n\n"
        f"If anything changes just reply to this email or text us at "
        f"{os.environ.get('AGENT_PHONE', '')}.\n\n"
        f"Talk soon,\n"
        f"Sophia\n"
        f"{os.environ.get('BUSINESS_NAME', 'San Joaquin House Buyers')}\n"
        f"{os.environ.get('AGENT_PHONE', '')}"
    )
    return send_email(to=to, subject=subject, body=body)


def send_weekly_report_email(report_text: str) -> bool:
    owner_email = os.environ.get("BUSINESS_EMAIL", "")
    if not owner_email:
        logger.warning("no owner email configured for weekly report")
        return False
    subject = f"REI Agent Weekly Report — {__import__('datetime').date.today()}"
    return send_email(to=owner_email, subject=subject, body=report_text)


def start_email_scheduler(existing_scheduler: BackgroundScheduler | None = None) -> None:
    global _scheduler
    if existing_scheduler is not None:
        existing_scheduler.add_job(
            _email_tick,
            "interval",
            minutes=30,
            id="email_drip_tick",
            replace_existing=True,
        )
        logger.info("email_scheduler added to existing scheduler interval=30min")
        return
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="America/Los_Angeles")
    _scheduler.add_job(
        _email_tick,
        "interval",
        minutes=30,
        id="email_drip_tick",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("email_scheduler started interval=30min")


def stop_email_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("email_scheduler stopped")


def send_offer_summary_email(to, first_name, address, offer_low, offer_high, lead_id=""):
    subject = f"Cash Offer Summary — {address}"
    body = (
        f"Hi {first_name},\n\n"
        f"Thanks for chatting today.\n\n"
        f"Property: {address}\n"
        f"Cash offer range: ${offer_low:,} – ${offer_high:,}\n"
        f"As-is, no repairs, fast close (14 days)\n"
        f"No agent fees or commissions\n\n"
        f"Reply or call/text to schedule a walkthrough.\n\n"
        f"— Sophia\nSan Joaquin House Buyers\n"
        f"{os.environ.get('SIGNALWIRE_PHONE', '')}"
    )
    return send_email(to=to, subject=subject, body=body)
