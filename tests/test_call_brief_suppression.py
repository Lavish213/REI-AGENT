from datetime import UTC, datetime, timedelta

import pytest

from backend.voice.call_brief_loader import _valid_brief, load_brief_into_ctx

LEAD = "11111111-1111-1111-1111-111111111111"
SUPPRESSION = "suppression_not_cleared"


class Ctx:
    def __init__(self, lead_id=LEAD):
        self.lead_id = lead_id
        self._call_sid = "CA-test"
        self.call_brief = {}
        self.bob_phase = None
        self.bob_missing_box = None
        self.bob_mood_hint = None
        self.bob_avoid = []
        self.bob_escalation_rules = []
        self.bob_opener_hint = None
        self.bob_blocked_reasons = []
        self.bob_suppression_flagged = False
        self.bob_valuation = {}
        self.bob_county_context = {}
        self.bob_california_context = {}


def brief(**over):
    now = datetime.now(UTC)
    base = {
        "schema_version": "2.0",
        "lead_id": LEAD,
        "phase": "VERIFY",
        "objective": "confirm you are speaking with the property owner",
        "missing_box": "right_person",
        "mood": "unknown",
        "avoid": [],
        "escalation_rules": [],
        "opener_hint": None,
        "confidence": 0.0,
        "source": "bob_rules",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "evidence": {},
        "blocked_reasons": ["missing_verified_phone", "dial_authorization_requires_rei_preflight"],
        "ready_for_call": False,
    }
    base.update(over)
    return base


class TestBlockedReasonsReachTheContext:
    def test_reasons_are_loaded(self):
        ctx = Ctx()
        assert load_brief_into_ctx(ctx, brief()) is True
        assert ctx.bob_blocked_reasons == [
            "missing_verified_phone", "dial_authorization_requires_rei_preflight"]

    def test_absent_reasons_default_empty(self):
        ctx = Ctx()
        payload = brief()
        payload.pop("blocked_reasons")
        assert load_brief_into_ctx(ctx, payload) is True
        assert ctx.bob_blocked_reasons == []

    def test_malformed_reasons_reject_the_brief(self):
        for bad in ([{"a": 1}], ["x" * 300], [None], "not-a-list", [1, 2]):
            ctx = Ctx()
            assert load_brief_into_ctx(ctx, brief(blocked_reasons=bad)) is False
            assert ctx.bob_blocked_reasons == []

    def test_reasons_cleared_on_reject(self):
        ctx = Ctx()
        ctx.bob_blocked_reasons = ["stale"]
        ctx.bob_suppression_flagged = True
        assert load_brief_into_ctx(ctx, None) is False
        assert ctx.bob_blocked_reasons == []
        assert ctx.bob_suppression_flagged is False


class TestSuppressionFlag:
    def test_suppression_marker_sets_the_flag(self):
        ctx = Ctx()
        reasons = [SUPPRESSION, "missing_verified_phone"]
        assert load_brief_into_ctx(ctx, brief(phase="WRAP", blocked_reasons=reasons,
                                              objective="Do not contact this seller. Honor suppression.")) is True
        assert ctx.bob_suppression_flagged is True

    def test_no_marker_leaves_flag_false(self):
        ctx = Ctx()
        assert load_brief_into_ctx(ctx, brief()) is True
        assert ctx.bob_suppression_flagged is False

    def test_flag_does_not_depend_on_objective_prose(self):
        ctx = Ctx()
        load_brief_into_ctx(ctx, brief(blocked_reasons=[SUPPRESSION], objective="anything at all"))
        assert ctx.bob_suppression_flagged is True

    def test_prose_alone_does_not_set_the_flag(self):
        ctx = Ctx()
        load_brief_into_ctx(ctx, brief(objective="Do not contact this seller. Honor suppression."))
        assert ctx.bob_suppression_flagged is False

    def test_stale_flag_is_reset_before_load(self):
        ctx = Ctx()
        ctx.bob_suppression_flagged = True
        assert load_brief_into_ctx(ctx, brief()) is True
        assert ctx.bob_suppression_flagged is False


class TestExistingGuardsStillHold:
    def test_ready_for_call_true_still_rejects(self):
        ctx = Ctx()
        assert load_brief_into_ctx(ctx, brief(ready_for_call=True)) is False

    def test_expired_brief_still_rejects(self):
        now = datetime.now(UTC)
        ctx = Ctx()
        payload = brief(created_at=(now - timedelta(hours=48)).isoformat(),
                        expires_at=(now - timedelta(hours=1)).isoformat())
        assert load_brief_into_ctx(ctx, payload) is False

    def test_wrong_lead_still_rejects(self):
        ctx = Ctx(lead_id="22222222-2222-2222-2222-222222222222")
        assert load_brief_into_ctx(ctx, brief()) is False

    def test_suppression_does_not_bypass_validation(self):
        ctx = Ctx()
        payload = brief(blocked_reasons=[SUPPRESSION], ready_for_call=True)
        assert load_brief_into_ctx(ctx, payload) is False
        assert ctx.bob_suppression_flagged is False

    def test_valid_brief_helper_unchanged_for_business_snapshot(self):
        assert _valid_brief(brief(), LEAD) is True
        assert _valid_brief({}, LEAD) is False


class TestContextSurfacesSuppression:
    def _prefix(self, **over):
        pytest.importorskip("pipecat")
        from backend.voice.processors.context_tracker import CallContext
        ctx = CallContext()
        ctx.lead_id = LEAD
        load_brief_into_ctx(ctx, brief(**over))
        return ctx.build_context_prefix() if hasattr(ctx, "build_context_prefix") else None

    def test_suppression_section_present_and_overriding(self):
        text = self._prefix(phase="WRAP", blocked_reasons=[SUPPRESSION],
                            objective="Do not contact this seller. Honor suppression.")
        if text is None:
            pytest.skip("context prefix builder not exposed")
        assert "SUPPRESSION ON RECORD" in text
        assert "overrides every other instruction" in text

    def test_no_suppression_section_when_clean(self):
        text = self._prefix()
        if text is None:
            pytest.skip("context prefix builder not exposed")
        assert "SUPPRESSION ON RECORD" not in text
