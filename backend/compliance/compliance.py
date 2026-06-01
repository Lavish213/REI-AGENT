from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from loguru import logger

CALLING_HOURS_START = int(os.environ.get("CALLING_HOURS_START", 9))
CALLING_HOURS_END = int(os.environ.get("CALLING_HOURS_END", 21))


@dataclass
class ComplianceResult:
    allowed: bool
    reason: str


def _is_calling_hours() -> bool:
    import pytz
    pacific = pytz.timezone("America/Los_Angeles")
    now = datetime.now(pacific)
    return CALLING_HOURS_START <= now.hour < CALLING_HOURS_END


def _check_dnc(phone: str) -> bool:
    try:
        from backend.lib.db import _get_client
        client = _get_client()
        result = client.table("dnc_list").select("id").eq("phone", phone).limit(1).execute()
        return bool(result.data)
    except Exception as e:
        logger.warning("dnc_check failed phone={} error={}", phone, str(e))
        return False


class ComplianceEngine:
    def check_call_allowed(self, lead_id: str) -> ComplianceResult:
        try:
            from backend.lib.db import get_lead_with_property
            lead = get_lead_with_property(lead_id)
            if not lead:
                return ComplianceResult(allowed=False, reason="lead_not_found")
            if lead.get("opted_out"):
                return ComplianceResult(allowed=False, reason="opted_out")
            if lead.get("dnc_blocked"):
                return ComplianceResult(allowed=False, reason="dnc_blocked")
            if not _is_calling_hours():
                return ComplianceResult(allowed=False, reason="outside_hours")
            prop = lead.get("properties") or {}
            phones = prop.get("callable_phones") or []
            if isinstance(phones, list):
                for phone in phones:
                    if phone and _check_dnc(str(phone)):
                        logger.info("dnc_match lead_id={} phone={}", lead_id, phone)
                        return ComplianceResult(allowed=False, reason="dnc_list_match")
            return ComplianceResult(allowed=True, reason="ok")
        except Exception as e:
            logger.exception("compliance_check failed lead_id={} error={}", lead_id, str(e))
            return ComplianceResult(allowed=True, reason="check_failed_allowing")

    def check_sms_allowed(self, lead_id: str) -> ComplianceResult:
        try:
            from backend.lib.db import get_lead_with_property
            lead = get_lead_with_property(lead_id)
            if not lead:
                return ComplianceResult(allowed=False, reason="lead_not_found")
            if lead.get("opted_out"):
                return ComplianceResult(allowed=False, reason="opted_out")
            if lead.get("dnc_blocked"):
                return ComplianceResult(allowed=False, reason="dnc_blocked")
            return ComplianceResult(allowed=True, reason="ok")
        except Exception as e:
            logger.exception("sms_compliance_check failed lead_id={} error={}", lead_id, str(e))
            return ComplianceResult(allowed=True, reason="check_failed_allowing")
