from __future__ import annotations
from loguru import logger

_BASE_ESCALATIONS = [
    "exact offer request on first call",
    "legal questions about title or probate",
    "seller requests to speak with a human immediately",
]

_SITUATION_ESCALATIONS: dict[str, list[str]] = {
    "foreclosure": ["auction date within 30 days", "redemption period question"],
    "probate": ["probate still open and seller wants to close fast"],
    "distressed": ["mentions of inability to pay bills or utilities"],
    "divorce": ["one party says the other does not know about the sale"],
    "tax_delinquent": ["county has already scheduled auction"],
}

def build_escalations(lead: dict, situation_label: str = "unknown") -> list[str]:
    escalations = list(_BASE_ESCALATIONS)

    situation_extras = _SITUATION_ESCALATIONS.get(situation_label, [])
    escalations.extend(situation_extras)

    props = lead.get("properties") or lead
    distress = int((props.get("distress_score") or 0))
    if distress >= 80:
        escalations.append("high distress score — consider immediate human handoff")

    logger.debug("escalation_rules situation={} count={}", situation_label, len(escalations))
    return escalations
