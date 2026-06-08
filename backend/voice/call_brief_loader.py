from __future__ import annotations
from loguru import logger

_PHASE_TO_STAGE = {
    "VERIFY":          "STAGE_1_QUALIFY",
    "LIGHT_DISCOVERY": "STAGE_2_DISCOVER",
    "QUALIFY":         "STAGE_3_PRECLOSE",
    "NEXT_STEP":       "STAGE_4_CLOSE",
    "WRAP":            "STAGE_5_WRAP",
}


def load_brief_into_ctx(call_ctx, brief: dict | None) -> None:
    if not brief:
        return
    call_ctx.call_brief = brief
    call_ctx.bob_phase = brief.get("phase")
    call_ctx.bob_missing_box = brief.get("missing_box")
    call_ctx.bob_mood_hint = brief.get("mood")
    call_ctx.bob_avoid = brief.get("avoid") or []
    call_ctx.bob_escalation_rules = brief.get("escalation_rules") or []
    call_ctx.bob_opener_hint = brief.get("opener_hint")
    if brief.get("phase"):
        stage = _PHASE_TO_STAGE.get(brief["phase"])
        if stage and not getattr(call_ctx, "objective", None):
            call_ctx.objective = stage
    logger.info(
        "call_brief_loaded lead_id={} phase={} box={} mood={}",
        getattr(call_ctx, "lead_id", ""),
        brief.get("phase"),
        brief.get("missing_box"),
        brief.get("mood"),
    )
