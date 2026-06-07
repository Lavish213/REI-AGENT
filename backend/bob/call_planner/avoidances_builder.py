from __future__ import annotations
from loguru import logger

_BASE_AVOIDS = [
    "specific offer amounts",
    "ARV or after-repair value",
    "legal advice",
]

_CONDITION_AVOIDS = {
    "foreclosure": ["foreclosure timeline details", "redemption period advice"],
    "probate": ["probate legal process", "attorney referrals"],
    "divorce": ["taking sides", "mentioning the other party negatively"],
    "tax_delinquent": ["exact tax amounts owed", "county auction timelines"],
    "distressed": ["pressure or urgency language"],
    "tired_landlord": ["tenant legal rights advice"],
}

def build_avoids(lead: dict, situation_label: str = "unknown") -> list[str]:
    avoids = list(_BASE_AVOIDS)

    situation_extras = _CONDITION_AVOIDS.get(situation_label, [])
    avoids.extend(situation_extras)

    props = lead.get("properties") or lead
    if props.get("has_agent") or props.get("listed"):
        avoids.append("asking them to cancel their listing")

    if props.get("mortgage_status") == "underwater":
        avoids.append("creative finance pitches — no equity present")

    logger.debug("avoidances_builder situation={} avoids_count={}", situation_label, len(avoids))
    return avoids
