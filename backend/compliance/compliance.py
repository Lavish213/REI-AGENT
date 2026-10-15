from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from loguru import logger


@dataclass
class ComplianceResult:
    allowed: bool
    reason: str


def _is_calling_hours() -> bool:
    import pytz

    pacific = pytz.timezone("America/Los_Angeles")
    now = datetime.now(pacific)
    start = int(os.environ.get("CALLING_HOURS_START", 9))
    end = int(os.environ.get("CALLING_HOURS_END", 21))
    return start <= now.hour < end


def _check_dnc(phone: str) -> bool:
    try:
        from backend.lib.db import phone_is_do_not_call
        return phone_is_do_not_call(phone)
    except Exception as e:
        logger.warning("dnc_check failed phone={} error={}", phone, str(e))
        raise RuntimeError("DNC verification unavailable") from e


class ComplianceEngine:
    def check_call_allowed(self, lead_id: str) -> ComplianceResult:
        try:
            from backend.lib.db import get_lead_with_property, local_lead_reply_hold

            lead = get_lead_with_property(lead_id)
            if not lead:
                return ComplianceResult(allowed=False, reason="lead_not_found")
            if lead.get("opted_out") or local_lead_reply_hold(lead_id)["opted_out"]:
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
            return ComplianceResult(allowed=False, reason="compliance_unavailable")

    def handle_opt_out(
        self,
        lead_id: str,
        method: str,
        trigger_word: str = "",
        channel: str = "all",
        contact_point: str = "",
        source: str = "inbound",
        call_sid: str | None = None,
    ) -> None:
        from backend.lib import db

        tenant_id = os.environ.get("TENANT_ID", "").strip()
        point = (contact_point or "").strip()

        if point and "@" not in point:
            db.try_write("opt_out_local_journal", db.stage_contact_suppression, tenant_id or "00000000-0000-0000-0000-000000000001", point, lead_id, method, call_sid)

        if not point:
            lead = db.get_lead_with_property(lead_id) or {}
            point = lead.get("owner_phone") or lead.get("owner_email") or ""

        if tenant_id and point:
            db.try_write(
                "opt_out_evidence",
                db.record_suppression_event,
                tenant_id=tenant_id,
                lead_id=lead_id,
                contact_point=point,
                contact_type="email" if "@" in point else "phone",
                channel=channel,
                method=method,
                source=source,
                reason=trigger_word or method,
                call_sid=call_sid,
                verbatim=trigger_word,
                actor="system",
            )
        else:
            logger.error(
                "opt_out_evidence_not_recorded lead_id={} tenant_set={} contact_found={}",
                lead_id,
                bool(tenant_id),
                bool(point),
            )

        db.try_write("opt_out_flag", db.mark_lead_opted_out, lead_id)

        logger.info(
            "opt_out_handled lead_id={} method={} channel={}", lead_id, method, channel
        )

    def check_sms_allowed(self, lead_id: str) -> ComplianceResult:
        try:
            from backend.lib.db import get_lead_with_property, local_lead_reply_hold

            lead = get_lead_with_property(lead_id)
            if not lead:
                return ComplianceResult(allowed=False, reason="lead_not_found")
            if lead.get("opted_out") or local_lead_reply_hold(lead_id)["opted_out"]:
                return ComplianceResult(allowed=False, reason="opted_out")
            if lead.get("dnc_blocked"):
                return ComplianceResult(allowed=False, reason="dnc_blocked")
            return ComplianceResult(allowed=True, reason="ok")
        except Exception as e:
            logger.exception("sms_compliance_check failed lead_id={} error={}", lead_id, str(e))
            return ComplianceResult(allowed=False, reason="compliance_unavailable")
