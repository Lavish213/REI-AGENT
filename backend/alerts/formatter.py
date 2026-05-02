import os
from datetime import datetime, timezone

from loguru import logger


def _dollars(cents: int | None) -> str:
    if cents is None:
        return "N/A"
    return f"${cents / 100:,.0f}"


def _days_until(date_str: str | None) -> str:
    if date_str is None:
        return "N/A"
    try:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
            try:
                target = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                days = (target - datetime.now(timezone.utc)).days
                if days < 0:
                    return "PAST"
                return f"{days}d"
            except ValueError:
                continue
        return "N/A"
    except Exception:
        return "N/A"


def format_lead_alert(prop: dict) -> str:
    score = prop.get("distress_score", 0)
    address = prop.get("address", "Unknown")
    city = prop.get("city", "")
    zip_code = prop.get("zip", "")
    distress = prop.get("distress_type", "unknown").replace("_", " ").title()
    arv = _dollars(prop.get("estimated_arv"))
    mao = _dollars(prop.get("mao"))
    auction = prop.get("auction_date")
    auction_str = f"Auction in {_days_until(auction)}" if auction else "No auction date"
    owner = prop.get("owner_name", "Unknown")

    message = (
        f"NEW LEAD {score}/100\n"
        f"{address} {city} {zip_code}\n"
        f"{distress}\n"
        f"ARV: {arv} | MAO: {mao}\n"
        f"{auction_str}\n"
        f"Owner: {owner}"
    )

    logger.debug("format_lead_alert address={}", address)
    return message


def format_walkthrough_confirmation(lead: dict, prop: dict, appointment_dt: datetime) -> str:
    address = prop.get("address", "Unknown")
    city = prop.get("city", "")
    owner = lead.get("owner_name", prop.get("owner_name", ""))
    dt_str = appointment_dt.strftime("%A %b %-d at %-I:%M %p")
    arv = _dollars(prop.get("estimated_arv"))
    mao = _dollars(prop.get("mao"))

    message = (
        f"WALKTHROUGH BOOKED\n"
        f"{owner}\n"
        f"{address} {city}\n"
        f"{dt_str}\n"
        f"ARV: {arv} | MAO: {mao}"
    )

    logger.debug("format_walkthrough_confirmation address={}", address)
    return message


def format_sms_drip_day1(prop: dict, owner_first_name: str) -> str:
    address = prop.get("address", "your property")
    return (
        f"Hey {owner_first_name}, this is Sophia with San Joaquin House Buyers. "
        f"We buy houses cash in Stockton and we're interested in {address}. "
        f"Would you consider an offer? No pressure either way. "
        f"Reply STOP to opt out."
    )


def format_sms_drip_day2(owner_first_name: str) -> str:
    return (
        f"Hey {owner_first_name}, just following up from San Joaquin House Buyers. "
        f"Totally understand if timing isn't right. "
        f"We close fast and handle everything as-is if you ever want to chat. "
        f"Reply STOP to opt out."
    )


def format_sms_drip_final(owner_first_name: str) -> str:
    return (
        f"Hey {owner_first_name}, last message from Sophia at San Joaquin House Buyers. "
        f"If you ever want a no-pressure cash offer on your property just text or call "
        f"{os.environ.get('AGENT_PHONE', '')}. "
        f"Reply STOP to opt out."
    )


def format_appointment_reminder(owner_first_name: str, appointment_dt: datetime) -> str:
    dt_str = appointment_dt.strftime("%A at %-I:%M %p")
    return (
        f"Hey {owner_first_name}! Just a reminder we'll be at your place "
        f"{dt_str}. Let us know if anything changes! "
        f"- Sophia, San Joaquin House Buyers"
    )


def format_qa_alert(call_id: str, score: float, failures: list[str]) -> str:
    failure_str = " | ".join(failures[:2]) if failures else "none"
    return (
        f"LOW QA CALL\n"
        f"Score: {score}/10\n"
        f"Call: {call_id}\n"
        f"Issues: {failure_str}"
    )
