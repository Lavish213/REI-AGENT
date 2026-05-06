import os
from datetime import datetime, timezone

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from backend.lib.db import (
    get_active_drip_leads,
    update_lead_drip_progress,
    complete_lead_drip,
    mark_lead_opted_out,
    pause_lead_drip,
    append_drip_reply,
    get_lead_by_owner_phone,
    insert_sms,
)
from backend.alerts.sms import send_drip_sms, send_alert_to_owner

PACIFIC = pytz.timezone("America/Los_Angeles")

SEQUENCES: dict[str, list[tuple[int, str]]] = {
    "seller": [
        (0, "Hey are you the owner of {address}? - Sophia"),
        (3, "Hey {first_name} \u2014 Sophia again. We're still looking in your area. Close in 14 days, no repairs, we cover closing costs. Still open to an offer on {address}?"),
        (7, "Hi {first_name}, just checking in \u2014 has anything changed with {address}? No pressure at all, just want to help if timing works. - Sophia SJ House Buyers"),
        (14, "{first_name} \u2014 managing a property is a lot. If {address} has become more burden than it's worth, we make it easy. Cash, as-is, your timeline. Interested? - Sophia"),
        (21, "Hey {first_name}! Sophia here. Properties in your area are moving fast. Wanted to see if you'd like to know what {address} could sell for cash. Takes 5 min. Worth a chat?"),
        (30, "{first_name} \u2014 last follow up from me on {address}. If cash offer, fast close, zero hassle sounds right \u2014 just reply YES and I'll call you today. - Sophia, San Joaquin House Buyers"),
        (45, "Hey {first_name}, Sophia from SJ House Buyers. It's been a while \u2014 still own {address}? Market changed a lot. Might be worth a quick convo."),
        (60, "{first_name} \u2014 Sophia one last time. If you ever want a fast cash offer on {address} just text me back. Hope you're doing well. \U0001f3e1"),
    ],
    "pre_foreclosure": [
        (0, "Hey {first_name} \u2014 this is Sophia with San Joaquin House Buyers. I may be able to help with {address}. Can we talk today? Reply STOP to opt out."),
        (1, "{first_name} \u2014 time may be critical for {address}. We buy fast, stop the clock, and put cash in your pocket. Call or text back today. - Sophia"),
        (3, "Hey {first_name} \u2014 Sophia again. We've helped others in similar situations keep their credit and walk away with cash. Worth a 5 min call?"),
        (5, "{first_name} \u2014 last reach out on this. Options exist but windows close fast. Reply YES if you want to talk. - Sophia"),
    ],
    "tax_delinquent": [
        (0, "Hi {first_name} \u2014 are you the owner of {address}? We may be able to help with the tax situation. - Sophia"),
        (3, "Hey {first_name}, Sophia w/ SJ House Buyers. We buy properties even with back taxes \u2014 we handle everything at closing. Would you want to hear an offer?"),
        (7, "{first_name} \u2014 tax situations on {address} can be resolved fast with a cash sale. No out of pocket costs. Still interested? - Sophia"),
    ],
    "absentee_owner": [
        (0, "Hey \u2014 are you still the owner of {address}? - Sophia, SJ House Buyers"),
        (5, "Hey {first_name} \u2014 Sophia here. Managing a property from a distance is tough. We buy as-is, fast, cash. Would an offer on {address} interest you?"),
        (14, "{first_name} \u2014 quick check in on {address}. If it's become more headache than it's worth we'd love to make it simple. - Sophia SJ House Buyers"),
    ],
    "divorce_probate": [
        (0, "Hi {first_name} \u2014 my name is Sophia with San Joaquin House Buyers. I may be able to help with the property on {address}. Do you have a moment to chat?"),
        (5, "Hey {first_name}, Sophia again. We specialize in making property sales simple during complicated times. Fast, private, no hassle. Would that be helpful right now?"),
        (14, "{first_name} \u2014 just checking in. Whenever the time is right for {address} we're here. No pressure. - Sophia"),
    ],
    "vacancy": [
        (0, "Hey \u2014 is {address} still your property? Sophia w/ SJ House Buyers. Would love to make an offer."),
        (3, "{first_name} \u2014 vacant properties can be a liability. We buy as-is, handle everything, close fast. Cash offer on {address}?"),
    ],
    "buyer": [
        (0, "Hey {first_name}! Sophia w/ San Joaquin House Buyers. Great meeting you today! Are you looking for move-in ready or open to a great deal on a fixer?"),
        (3, "Hey {first_name} \u2014 Sophia here. Do you have a home to sell before buying? We make that easy \u2014 fast cash sale so you can move without the stress."),
        (7, "{first_name} \u2014 any questions about what you saw? I find off-market deals too. Would you want first look at below-market properties?"),
    ],
    "investor": [
        (0, "Hey {first_name}! Sophia with SJ House Buyers. We get off-market deals regularly in Stockton/Lodi. What's your buy criteria? ARV range + areas?"),
        (7, "{first_name} \u2014 Sophia. Got a deal in {city}. Interested? I'll send details."),
    ],
    "call_followup": [
        (0, "Hey {first_name}! Sophia here \u2014 great chatting with you about {address}. I'll follow up with more info shortly. Feel free to text me anytime!"),
    ],
    "seller_es": [
        (0, "Oye \u2014 \u00bferes el due\u00f1o de {address}? - Sophia"),
        (3, "Hola {first_name} \u2014 Sophia otra vez. Seguimos buscando en tu \u00e1rea. Cerramos en 14 d\u00edas, sin reparaciones. \u00bfA\u00fan te interesa?"),
        (7, "Hey {first_name}, \u00bfalgo cambi\u00f3 con {address}? Sin presi\u00f3n \u2014 solo quiero ayudar si el tiempo es bueno. - Sophia"),
        (14, "Oye {first_name} \u2014 manejar una propiedad es mucho trabajo. Si {address} ya es m\u00e1s carga que beneficio, lo hacemos f\u00e1cil. Cash, as-is, tu tiempo. \u00bfTe interesa?"),
        (30, "{first_name} \u2014 \u00faltimo mensaje de mi parte sobre {address}. Si quieres una oferta cash r\u00e1pida, solo responde S\u00cd y te llamo hoy."),
    ],
}

DAY0_YES_REPLY = (
    "Hey {first_name}! Sophia w/ San Joaquin House Buyers. We buy as-is cash no repairs no agent. "
    "Would you take a quick offer on {address}? Reply STOP to opt out"
)

DAY0_YES_REPLY_ES = (
    "Qué bueno! Sophia con San Joaquin House Buyers. Compramos as-is, cash, rapido. "
    "\u00bfTe interesa una oferta? Reply STOP pa' salir"
)

DISTRESS_TO_SEQUENCE: dict[str, str] = {
    "pre_foreclosure": "pre_foreclosure",
    "tax_delinquent": "tax_delinquent",
    "absentee_owner": "absentee_owner",
    "divorce": "divorce_probate",
    "probate": "divorce_probate",
    "vacancy": "vacancy",
}

HOT_KEYWORDS = {"yes", "interested", "call me", "info", "yeah", "sure", "ok", "okay",
                "yep", "call", "definitely", "si", "sí", "claro", "órale", "sale"}
OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "quit", "cancel", "end", "optout", "opt out", "opt-out"}

_scheduler: BackgroundScheduler | None = None


def get_sequence_name(distress_type: str | None) -> str:
    if not distress_type:
        return "seller"
    return DISTRESS_TO_SEQUENCE.get(distress_type.lower(), "seller")


def _get_first_name(lead: dict, prop: dict) -> str:
    owner = lead.get("owner_name") or (prop or {}).get("owner_name") or ""
    parts = owner.strip().split()
    return parts[0] if parts else "there"


def _render(template: str, lead: dict, prop: dict) -> str:
    prop = prop or {}
    return template.format(
        first_name=_get_first_name(lead, prop),
        address=prop.get("address", "your property"),
        city=prop.get("city", ""),
        beds=prop.get("beds", ""),
        baths=prop.get("baths", ""),
        arv=str(int((prop.get("estimated_arv") or 0) / 100)),
        mao=str(int((prop.get("mao") or 0) / 100)),
    )


def _is_in_hours() -> bool:
    now_pt = datetime.now(PACIFIC)
    start = int(os.environ.get("CALLING_HOURS_START", 8))
    end = int(os.environ.get("CALLING_HOURS_END", 21))
    return start <= now_pt.hour < end


def _process_lead(lead: dict) -> None:
    lead_id = lead["id"]
    phone = lead.get("owner_phone")

    if not phone:
        return

    last_sms_raw = lead.get("last_sms_at")
    if last_sms_raw:
        last_sent = datetime.fromisoformat(last_sms_raw.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last_sent).total_seconds()
        if elapsed < 86400:
            return

    sequence_name = lead.get("drip_sequence") or "seller"
    sequence = SEQUENCES.get(sequence_name, SEQUENCES["seller"])

    drip_started_raw = lead.get("drip_started_at")
    if not drip_started_raw:
        return

    started = datetime.fromisoformat(drip_started_raw.replace("Z", "+00:00"))
    days_elapsed = (datetime.now(timezone.utc) - started).days

    current_day = lead.get("drip_day")
    if current_day is None:
        current_day = -1

    next_step: tuple[int, str] | None = None
    for day, template in sequence:
        if day > current_day and days_elapsed >= day:
            next_step = (day, template)
            break

    if next_step is None:
        all_sent = all(day <= current_day for day, _ in sequence)
        if all_sent:
            complete_lead_drip(lead_id)
        return

    day, template = next_step
    prop = lead.get("properties") or {}
    body = _render(template, lead, prop)

    is_first_message = current_day < 0
    if is_first_message and "reply stop" not in body.lower():
        body = body + " Reply STOP to opt out"

    sent = send_drip_sms(to=phone, body=body, lead_id=lead_id)
    if sent:
        update_lead_drip_progress(lead_id, day, datetime.now(timezone.utc).isoformat())
        logger.info("drip_sent lead_id={} day={} sequence={}", lead_id, day, sequence_name)


def _tick() -> None:
    if not _is_in_hours():
        return

    try:
        leads = get_active_drip_leads()
    except Exception as e:
        logger.error("drip_tick get_leads error={}", str(e))
        return

    for lead in leads:
        try:
            _process_lead(lead)
        except Exception as e:
            logger.error("drip_tick process error lead_id={} error={}", lead.get("id"), str(e))


def handle_inbound_reply(from_phone: str, body: str, message_sid: str) -> str:
    body_stripped = body.strip()
    body_lower = body_stripped.lower()

    lead = get_lead_by_owner_phone(from_phone)

    insert_sms({
        "lead_id": lead["id"] if lead else None,
        "direction": "inbound",
        "body": body_stripped,
        "signalwire_message_id": message_sid,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    })

    if any(kw in body_lower for kw in OPT_OUT_KEYWORDS):
        if lead:
            mark_lead_opted_out(lead["id"])
            logger.info("opt_out lead_id={} phone={}", lead.get("id"), from_phone)
        return "opted_out"

    if not lead:
        logger.warning("inbound_sms no lead found phone={}", from_phone)
        return "logged"

    lead_id = lead["id"]
    prop = lead.get("properties") or {}
    first_name = _get_first_name(lead, prop)
    address = prop.get("address", "your property")
    score = prop.get("distress_score", 0)
    current_day = lead.get("drip_day", -1)
    sequence_name = lead.get("drip_sequence", "seller")
    is_spanish = "es" in sequence_name

    if any(kw in body_lower for kw in HOT_KEYWORDS):
        pause_lead_drip(lead_id)
        from backend.lib.db import pause_lead_email
        pause_lead_email(lead_id)
        append_drip_reply(lead_id, {
            "body": body_stripped,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "type": "hot",
        })

        if current_day <= 0:
            if is_spanish:
                response_body = DAY0_YES_REPLY_ES.format(first_name=first_name, address=address)
            else:
                response_body = DAY0_YES_REPLY.format(first_name=first_name, address=address)
        else:
            if is_spanish:
                response_body = f"\u00a1Qu\u00e9 bueno! Te llamo pronto. \u00bfCu\u00e1l es el mejor momento hoy? - Sophia"
            else:
                response_body = "Great! I'll give you a call shortly. What's the best time today? - Sophia"

        send_drip_sms(to=from_phone, body=response_body, lead_id=lead_id)

        alert = (
            f"\U0001f525 HOT REPLY from {first_name} re {address}:\n"
            f"'{body_stripped}'\n"
            f"Score: {score}\n"
            f"Call them: {from_phone}"
        )
        send_alert_to_owner(alert)

        logger.info("hot_reply lead_id={} phone={}", lead_id, from_phone)
        return "hot_reply"

    pause_lead_drip(lead_id)
    from backend.lib.db import pause_lead_email
    pause_lead_email(lead_id)
    append_drip_reply(lead_id, {
        "body": body_stripped,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "type": "other",
    })

    alert = (
        f"\U0001f4ac REPLY from {first_name} re {address}:\n"
        f"'{body_stripped}'\n"
        f"Call them: {from_phone}"
    )
    send_alert_to_owner(alert)

    logger.info("reply_paused_drip lead_id={} phone={}", lead_id, from_phone)
    return "paused"


def send_appointment_reminder(lead_id: str, phone: str, first_name: str, address: str, appointment_dt: datetime) -> bool:
    dt_str = appointment_dt.strftime("%A at %-I:%M %p")
    body = f"Hey {first_name}! Quick reminder \u2014 we're stopping by {address} tomorrow at {appointment_dt.strftime('%-I:%M %p')}. See you then! - Sophia \U0001f3e1"
    return send_drip_sms(to=phone, body=body, lead_id=lead_id)


def send_post_call_sms(lead_id: str, phone: str, first_name: str, address: str) -> bool:
    body = f"Hey {first_name}! Sophia here \u2014 great chatting with you about {address}. I'll follow up with more info shortly. Feel free to text me anytime!"
    return send_drip_sms(to=phone, body=body, lead_id=lead_id)


def send_appointment_confirmed_sms(lead_id: str, phone: str, first_name: str, address: str, date_str: str, time_str: str) -> bool:
    body = f"{first_name} \u2014 confirmed! We'll be at {address} on {date_str} at {time_str}. Looking forward to it. - Sophia San Joaquin House Buyers"
    return send_drip_sms(to=phone, body=body, lead_id=lead_id)


def start_drip_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="America/Los_Angeles")
    _scheduler.add_job(_tick, "interval", minutes=15, id="drip_tick", replace_existing=True)
    _scheduler.start()
    logger.info("drip_scheduler started interval=15min")

    from backend.alerts.email import start_email_scheduler
    from backend.alerts.speed_to_lead import start_speed_to_lead_scheduler
    start_email_scheduler(existing_scheduler=_scheduler)
    start_speed_to_lead_scheduler(existing_scheduler=_scheduler)


def stop_drip_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("drip_scheduler stopped")


def send_birthday_message(lead_id: str, first_name: str, phone: str) -> bool:
    from backend.alerts.sms import send_sms
    from backend.compliance.compliance import ComplianceEngine

    engine = ComplianceEngine()
    result = engine.check_sms_allowed(lead_id)
    if not result.allowed:
        logger.info("birthday_sms blocked lead_id={} reason={}", lead_id, result.reason)
        return False

    message = f"Happy birthday {first_name}! Hope you're having a great day. - Sophia, SJ House Buyers"
    return send_sms(phone, message)


def send_purchase_anniversary_message(lead_id: str, first_name: str, phone: str, address: str) -> bool:
    from backend.alerts.sms import send_sms
    from backend.compliance.compliance import ComplianceEngine

    engine = ComplianceEngine()
    result = engine.check_sms_allowed(lead_id)
    if not result.allowed:
        logger.info("anniversary_sms blocked lead_id={} reason={}", lead_id, result.reason)
        return False

    message = f"Hey {first_name} \u2014 hope life's been good since you bought on {address}. If you ever want to know what it's worth now just let us know! - Sophia"
    return send_sms(phone, message)


def send_wedding_anniversary_message(lead_id: str, first_name: str, spouse_name: str, phone: str) -> bool:
    from backend.alerts.sms import send_sms
    from backend.compliance.compliance import ComplianceEngine

    engine = ComplianceEngine()
    result = engine.check_sms_allowed(lead_id)
    if not result.allowed:
        logger.info("wedding_anniversary_sms blocked lead_id={} reason={}", lead_id, result.reason)
        return False

    message = f"Hey {first_name} \u2014 hope you and {spouse_name} are having a wonderful anniversary! - Sophia, San Joaquin House Buyers"
    return send_sms(phone, message)


def run_daily_drip_triggers() -> None:
    from datetime import date
    from backend.lib.db import get_supabase

    today = date.today()
    sb = get_supabase()

    try:
        result = sb.table("leads").select(
            "id,first_name,phone,birthday,wedding_anniversary,home_purchase_anniversary,spouse_name,address"
        ).not_.is_("phone", "null").execute()

        for lead in (result.data or []):
            lead_id = lead["id"]
            first_name = lead.get("first_name") or "there"
            phone = lead.get("phone", "")
            if not phone:
                continue

            birthday_str = lead.get("birthday")
            if birthday_str:
                try:
                    bday = date.fromisoformat(birthday_str)
                    if bday.month == today.month and bday.day == today.day:
                        send_birthday_message(lead_id, first_name, phone)
                except Exception:
                    pass

            wedding_str = lead.get("wedding_anniversary")
            if wedding_str:
                try:
                    wanniv = date.fromisoformat(wedding_str)
                    if wanniv.month == today.month and wanniv.day == today.day:
                        spouse = lead.get("spouse_name") or "your spouse"
                        send_wedding_anniversary_message(lead_id, first_name, spouse, phone)
                except Exception:
                    pass

            purchase_str = lead.get("home_purchase_anniversary")
            if purchase_str:
                try:
                    panniv = date.fromisoformat(purchase_str)
                    if panniv.month == today.month and panniv.day == today.day:
                        address = lead.get("address") or "your property"
                        send_purchase_anniversary_message(lead_id, first_name, phone, address)
                except Exception:
                    pass
    except Exception as e:
        logger.error("run_daily_drip_triggers failed error={}", str(e))
