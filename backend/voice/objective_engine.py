from __future__ import annotations


class ObjectiveEngine:
    def decide(self, call_ctx) -> str:
        if getattr(call_ctx, "disposition", None) == "DEAD" or getattr(call_ctx, "call_should_end", False):
            return "STAGE_5_WRAP"
        if getattr(call_ctx, "appointment_set", False) or getattr(call_ctx, "callback_set", False):
            return "STAGE_5_WRAP"
        if getattr(call_ctx, "trust_score", 5.0) < 3.0:
            return "TRUST_REPAIR"
        if getattr(call_ctx, "emotional_state", "NEUTRAL") in {"DISTRESSED", "GRIEVING", "OVERWHELMED"}:
            return "EMOTIONAL_HOLD"
        if getattr(call_ctx, "resistance_level", "NONE") == "BLOCKING" and not getattr(call_ctx, "resistance_softening", False):
            return "HANDLE_OBJECTION"
        verified_contact = getattr(call_ctx, "owner_confirmed", False) or getattr(call_ctx, "address_known", False)
        intent = getattr(call_ctx, "intent_locked", False) or bool(getattr(call_ctx, "motivation_signals", []))
        if not verified_contact or not intent:
            return "STAGE_1_QUALIFY"
        if getattr(call_ctx, "pre_close_done", False):
            return "STAGE_4_CLOSE"
        condition = getattr(call_ctx, "condition_known", False) or bool(getattr(call_ctx, "property_issues", []))
        if not getattr(call_ctx, "motivation_signals", []) or not condition or not getattr(call_ctx, "timeline_mentioned", None):
            return "STAGE_2_DISCOVER"
        return "STAGE_3_PRECLOSE"
