import os
from dataclasses import dataclass
from datetime import datetime, timezone, time
from loguru import logger

from backend.lib.db import get_supabase


OPT_OUT_WORDS = {"stop", "unsubscribe", "cancel", "quit", "end", "remove"}

AI_IDENTITY_PHRASES = [
    "are you a robot", "are you ai", "are you real", "are you human",
    "is this a bot", "real person", "automated", "is this automated",
    "are you a computer", "are you a machine", "are you a person",
]

CALLING_HOURS_START = time(8, 0)
CALLING_HOURS_END = time(21, 0)


@dataclass
class ComplianceResult:
    allowed: bool
    reason: str | None = None


def _is_calling_hours() -> bool:
    now_pt = datetime.now(timezone.utc).astimezone(
        __import__("zoneinfo").ZoneInfo("America/Los_Angeles")
    )
    return CALLING_HOURS_START <= now_pt.time() <= CALLING_HOURS_END


def _log_compliance_event(
    event_type: str,
    lead_id: str | None,
    outcome: str,
    blocked_reason: str | None = None,
    details: dict | None = None,
) -> None:
    try:
        sb = get_supabase()
        sb.table("compliance_log").insert({
            "event_type": event_type,
            "lead_id": lead_id,
            "outcome": outcome,
            "blocked_reason": blocked_reason,
            "details": details or {},
        }).execute()
    except Exception as e:
        logger.error("compliance_log insert failed event={} error={}", event_type, str(e))


class ComplianceEngine:
    def check_call_allowed(self, lead_id: str) -> ComplianceResult:
        try:
            sb = get_supabase()
            result = sb.table("leads").select(
                "opted_out,dnc_blocked,callable"
            ).eq("id", lead_id).single().execute()

            if not result.data:
                _log_compliance_event("call_check", lead_id, "blocked", "lead_not_found")
                return ComplianceResult(allowed=False, reason="lead_not_found")

            data = result.data

            if data.get("opted_out"):
                _log_compliance_event("call_check", lead_id, "blocked", "opted_out")
                return ComplianceResult(allowed=False, reason="opted_out")

            if data.get("dnc_blocked"):
                _log_compliance_event("call_check", lead_id, "blocked", "dnc_blocked")
                return ComplianceResult(allowed=False, reason="dnc_blocked")

            if not _is_calling_hours():
                _log_compliance_event("call_check", lead_id, "blocked", "outside_calling_hours")
                return ComplianceResult(allowed=False, reason="outside_calling_hours")

            if data.get("callable") is False:
                _log_compliance_event("call_check", lead_id, "blocked", "callable_false")
                return ComplianceResult(allowed=False, reason="callable_false")

            _log_compliance_event("call_check", lead_id, "allowed")
            return ComplianceResult(allowed=True)

        except Exception as e:
            logger.error("check_call_allowed failed lead_id={} error={}", lead_id, str(e))
            return ComplianceResult(allowed=False, reason="compliance_error")

    def check_sms_allowed(self, lead_id: str) -> ComplianceResult:
        try:
            sb = get_supabase()
            result = sb.table("leads").select(
                "opted_out,opted_out_sms"
            ).eq("id", lead_id).single().execute()

            if not result.data:
                return ComplianceResult(allowed=False, reason="lead_not_found")

            data = result.data

            if data.get("opted_out"):
                _log_compliance_event("sms_check", lead_id, "blocked", "opted_out")
                return ComplianceResult(allowed=False, reason="opted_out")

            if data.get("opted_out_sms"):
                _log_compliance_event("sms_check", lead_id, "blocked", "opted_out_sms")
                return ComplianceResult(allowed=False, reason="opted_out_sms")

            if not _is_calling_hours():
                _log_compliance_event("sms_check", lead_id, "queued", "outside_hours")
                return ComplianceResult(allowed=False, reason="outside_hours_queue")

            _log_compliance_event("sms_check", lead_id, "allowed")
            return ComplianceResult(allowed=True)

        except Exception as e:
            logger.error("check_sms_allowed failed lead_id={} error={}", lead_id, str(e))
            return ComplianceResult(allowed=False, reason="compliance_error")

    def handle_opt_out(self, lead_id: str, method: str, trigger_word: str) -> None:
        try:
            sb = get_supabase()
            sb.table("leads").update({
                "opted_out": True,
                "opted_out_at": datetime.now(timezone.utc).isoformat(),
                "opted_out_method": method,
            }).eq("id", lead_id).execute()

            _log_compliance_event(
                "opt_out",
                lead_id,
                "processed",
                details={"method": method, "trigger_word": trigger_word},
            )
            logger.info("opt_out processed lead_id={} method={} trigger={}", lead_id, method, trigger_word)
        except Exception as e:
            logger.error("handle_opt_out failed lead_id={} error={}", lead_id, str(e))

    def handle_ai_identity_question(self, transcript_text: str) -> bool:
        text_lower = transcript_text.lower()
        for phrase in AI_IDENTITY_PHRASES:
            if phrase in text_lower:
                logger.info("ai_identity_question detected text={}", transcript_text[:80])
                return True
        return False

    def check_sms_opt_out(self, message_text: str) -> str | None:
        words = message_text.lower().strip().split()
        if words and words[0] in OPT_OUT_WORDS:
            return words[0]
        return None
