from __future__ import annotations
import re
from loguru import logger
from pipecat.frames.frames import Frame, LLMTextFrame, TextFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_SEVERITY_EXACT = "exact_block"
_SEVERITY_WARN = "soft_warn"
_SEVERITY_REVIEW = "operator_review"

_PHRASE_RULES = [
    (re.compile(r"\bsubject[- ]to\b|\btake over.*(?:mortgage|loan|payments)\b|\bassume.*(?:the )?(?:mortgage|loan)\b", re.I), _SEVERITY_EXACT, "Let me have Alanzo follow up on the creative finance options."),
    (re.compile(r"\bnovation\b|\bnovat\b", re.I), _SEVERITY_EXACT, "Let me have Alanzo follow up on that structure."),
    (re.compile(r"\bwrap\b.*\bmortgage\b|\bwrap mortgage\b", re.I), _SEVERITY_REVIEW, None),
    (re.compile(r"\bseller financ\b|\bowner financ\b", re.I), _SEVERITY_WARN, None),
    (re.compile(r"\blease option\b|\brent to own\b", re.I), _SEVERITY_WARN, None),
]

_SAFE_DEFLECT = "Let me have Alanzo follow up with you on that one."


class ComplianceOutputFilter(FrameProcessor):
    def __init__(self, call_ctx=None):
        super().__init__()
        self._ctx = call_ctx

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (LLMTextFrame, TextFrame, TTSTextFrame)):
            text = getattr(frame, "text", "") or ""
            if not text:
                await self.push_frame(frame, direction)
                return

            if self._ctx and getattr(self._ctx, "kill_switch_active", False):
                replacement = "I want to make sure we get you the right information. Let me have someone from our team follow up with you directly."
                await self.push_frame(TextFrame(text=replacement), direction)
                logger.warning("compliance_output_filter kill_switch_blocked text_preview={!r}", text[:60])
                return

            intel_packet = getattr(self._ctx, "intel_packet", None) or {}
            strategy = intel_packet.get("strategy_context") or {}
            dnp_list = strategy.get("do_not_pitch") or []
            dnp_lower = [s.lower() for s in dnp_list]

            for text_lower in [text.lower()]:
                for dnp_term in dnp_lower:
                    if dnp_term in text_lower:
                        logger.warning("compliance_output_filter dnp_blocked term={} preview={!r}", dnp_term, text[:60])
                        self._write_gate_log("dnp_blocked", dnp_term)
                        await self.push_frame(TextFrame(text=_SAFE_DEFLECT), direction)
                        return

            for pattern, severity, replacement in _PHRASE_RULES:
                if pattern.search(text):
                    logger.warning("compliance_output_filter rule={} severity={} preview={!r}", pattern.pattern[:30], severity, text[:60])
                    self._write_gate_log(f"rule_{severity}", pattern.pattern[:30])
                    if severity == _SEVERITY_EXACT:
                        await self.push_frame(TextFrame(text=replacement or _SAFE_DEFLECT), direction)
                        return
                    elif severity == _SEVERITY_WARN:
                        if self._ctx:
                            self._ctx.runtime_instruction = "[Watch: possible creative finance term used. Deflect to Alanzo if seller asks follow-up.]"
                    elif severity == _SEVERITY_REVIEW:
                        pass

        await self.push_frame(frame, direction)

    def _write_gate_log(self, gate_result: str, gate_reason: str) -> None:
        try:
            from backend.lib.db import write_tool_gate_log
            lead_id = getattr(self._ctx, "lead_id", None) if self._ctx else None
            call_sid = getattr(self._ctx, "_call_sid", None) if self._ctx else None
            write_tool_gate_log(
                lead_id=lead_id,
                call_sid=call_sid,
                tool_name="output_filter",
                permission_level="output",
                gate_result=gate_result,
                gate_reason=gate_reason,
            )
        except Exception:
            pass
