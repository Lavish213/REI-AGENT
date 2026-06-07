from __future__ import annotations
from loguru import logger
from backend.contracts.call_brief import CallBrief

def load_brief_into_ctx(call_ctx, brief_dict: dict | None) -> None:
    if not brief_dict:
        brief = CallBrief.default()
        logger.debug("call_brief_loader using default brief")
    else:
        try:
            brief = CallBrief.from_dict(brief_dict)
            logger.debug("call_brief_loader loaded phase={} missing_box={}", brief.phase, brief.missing_box)
        except Exception as e:
            brief = CallBrief.default()
            logger.warning("call_brief_loader parse failed error={} using default", str(e))

    call_ctx.bob_phase = brief.phase
    call_ctx.bob_missing_box = brief.missing_box
    call_ctx.bob_mood_hint = brief.mood
    call_ctx.bob_avoid = brief.avoid
    call_ctx.bob_escalation_rules = brief.escalation
    call_ctx.bob_opener_hint = brief.opener_hint
