from __future__ import annotations
from loguru import logger
from backend.lib.db import _get_client

def log_decision(
    lead_id: str,
    decision_type: str,
    inputs_used: dict,
    output: dict,
    reason_codes: list,
    confidence: float = 1.0,
    version: str = "1.0",
) -> None:
    try:
        _get_client().table("decision_records").insert({
            "lead_id": lead_id,
            "decision_type": decision_type,
            "inputs_used": inputs_used,
            "output": output,
            "reason_codes": reason_codes,
            "confidence": confidence,
            "version": version,
        }).execute()
        logger.debug("decision_logged type={} lead_id={}", decision_type, lead_id)
    except Exception as e:
        logger.warning("decision_log_failed lead_id={} error={}", lead_id, str(e))
