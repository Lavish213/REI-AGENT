from unittest.mock import patch, MagicMock, call as mock_call


# ──────────────────────────────────────────────────────────────────
# Canonical state + constant definitions
# ──────────────────────────────────────────────────────────────────

class TestWorkflowStates:
    EXPECTED_STATES = [
        "new_lead", "active_contact", "followup_required",
        "appointment_pending", "appointment_confirmed",
        "negotiation", "under_review", "dead_lead", "closed",
    ]

    def test_all_canonical_states_defined(self):
        from backend.workflows.engine import WORKFLOW_STATES
        for state in self.EXPECTED_STATES:
            assert state in WORKFLOW_STATES, f"Missing state: {state}"

    def test_no_duplicate_states(self):
        from backend.workflows.engine import WORKFLOW_STATES
        assert len(WORKFLOW_STATES) == len(set(WORKFLOW_STATES))

    def test_disposition_state_map_covers_all_dispositions(self):
        from backend.workflows.engine import DISPOSITION_STATE_MAP
        for disposition in ("HOT", "WARM", "COLD", "DEAD"):
            assert disposition in DISPOSITION_STATE_MAP

    def test_disposition_state_map_values_valid(self):
        from backend.workflows.engine import DISPOSITION_STATE_MAP, WORKFLOW_STATES
        for val in DISPOSITION_STATE_MAP.values():
            assert val in WORKFLOW_STATES

    def test_stage_workflow_map_values_valid(self):
        from backend.workflows.engine import STAGE_WORKFLOW_MAP, WORKFLOW_STATES
        for val in STAGE_WORKFLOW_MAP.values():
            assert val in WORKFLOW_STATES

    def test_stage_workflow_map_covers_all_lead_stages(self):
        from backend.workflows.engine import STAGE_WORKFLOW_MAP
        for stage in ("new", "contacted", "offer_made", "walkthrough_booked",
                      "under_contract", "closed", "dead"):
            assert stage in STAGE_WORKFLOW_MAP


class TestAllEventConstants:
    EXPECTED_EVENTS = [
        # Batch C
        "transcript_completed", "summary_generated", "lead_scored",
        "property_detected", "motivation_detected", "appointment_detected",
        "followup_required",
        # Batch D
        "workflow_created", "workflow_updated", "followup_created",
        "appointment_created", "appointment_confirmed", "lead_escalated",
        "operator_action", "pipeline_stage_changed", "callback_scheduled",
        "hot_lead_detected",
    ]

    def test_all_events_defined(self):
        import backend.voice.events as ev
        for event in self.EXPECTED_EVENTS:
            const = event.upper()
            assert hasattr(ev, const), f"Missing event constant: {const}"
            assert getattr(ev, const) == event

    def test_no_duplicate_values(self):
        import backend.voice.events as ev
        values = [getattr(ev, e.upper()) for e in self.EXPECTED_EVENTS]
        assert len(values) == len(set(values))

    def test_emit_event_accepts_none_call_id(self):
        """Operator events have no call_id."""
        with patch("backend.lib.db.insert_call_event") as mock_insert:
            from backend.voice.events import emit_event
            emit_event("operator_action", None, "lead-1", {"action": "test"})
            mock_insert.assert_called_once_with(
                call_id=None,
                lead_id="lead-1",
                event_type="operator_action",
                payload={"action": "test"},
            )


# ──────────────────────────────────────────────────────────────────
# Workflow engine: trigger_from_call_outcome
# ──────────────────────────────────────────────────────────────────

class TestWorkflowTrigger:
    def _trigger(self, disposition, intel, mock_transition, mock_followup):
        from backend.workflows.engine import trigger_from_call_outcome
        with patch("backend.lib.db.insert_call_event"), \
             patch("backend.lib.db.insert_workflow_transition", mock_transition), \
             patch("backend.lib.db.create_followup", mock_followup):
            return trigger_from_call_outcome("call-1", "lead-1", disposition, intel)

    def test_hot_disposition_maps_to_appointment_pending(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value="fu-1")
        state = self._trigger("HOT", {}, mock_t, mock_f)
        assert state == "appointment_pending"

    def test_warm_disposition_maps_to_followup_required(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value="fu-1")
        state = self._trigger("WARM", {}, mock_t, mock_f)
        assert state == "followup_required"

    def test_cold_disposition_maps_to_followup_required(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value="fu-1")
        state = self._trigger("COLD", {}, mock_t, mock_f)
        assert state == "followup_required"

    def test_dead_disposition_maps_to_dead_lead(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value=None)
        state = self._trigger("DEAD", {}, mock_t, mock_f)
        assert state == "dead_lead"

    def test_appointment_interest_overrides_cold_disposition(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value="fu-1")
        state = self._trigger("COLD", {"appointment_interest": True}, mock_t, mock_f)
        assert state == "appointment_pending"

    def test_appointment_interest_overrides_warm_disposition(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value="fu-1")
        state = self._trigger("WARM", {"appointment_interest": True}, mock_t, mock_f)
        assert state == "appointment_pending"

    def test_no_disposition_defaults_to_active_contact(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value=None)
        state = self._trigger(None, {}, mock_t, mock_f)
        assert state == "active_contact"

    def test_followup_auto_created_for_warm(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value="fu-1")
        self._trigger("WARM", {"next_step": "Call back next week"}, mock_t, mock_f)
        mock_f.assert_called_once()
        call_kwargs = mock_f.call_args[1] if mock_f.call_args[1] else mock_f.call_args[0]
        # followup should be created for followup_required state

    def test_followup_auto_created_for_hot(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value="fu-1")
        self._trigger("HOT", {}, mock_t, mock_f)
        mock_f.assert_called_once()

    def test_no_followup_for_dead_disposition(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value=None)
        self._trigger("DEAD", {}, mock_t, mock_f)
        mock_f.assert_not_called()

    def test_no_followup_for_no_disposition(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value=None)
        self._trigger(None, {}, mock_t, mock_f)
        mock_f.assert_not_called()

    def test_workflow_transition_called_with_call_outcome_source(self):
        mock_t = MagicMock(return_value=True)
        mock_f = MagicMock(return_value=None)
        with patch("backend.lib.db.insert_call_event"), \
             patch("backend.lib.db.insert_workflow_transition", mock_t), \
             patch("backend.lib.db.create_followup", mock_f):
            from backend.workflows.engine import trigger_from_call_outcome
            trigger_from_call_outcome("call-1", "lead-1", "WARM", {})
        mock_t.assert_called_once()
        kwargs = mock_t.call_args.kwargs if mock_t.call_args.kwargs else {}
        args = mock_t.call_args.args if mock_t.call_args.args else ()
        # trigger_source should be call_outcome
        all_args = list(args) + list(kwargs.values())
        assert "call_outcome" in str(mock_t.call_args)

    def test_returns_string_state(self):
        mock_t = MagicMock(return_value=False)
        mock_f = MagicMock(return_value=None)
        state = self._trigger("WARM", {}, mock_t, mock_f)
        assert isinstance(state, str)
        assert state in ["new_lead", "active_contact", "followup_required",
                         "appointment_pending", "appointment_confirmed",
                         "negotiation", "under_review", "dead_lead", "closed"]


# ──────────────────────────────────────────────────────────────────
# Followup priority derivation
# ──────────────────────────────────────────────────────────────────

class TestFollowupPriority:
    def _priority(self, intel):
        from backend.workflows.engine import _followup_priority_from_intel
        return _followup_priority_from_intel(intel)

    def test_high_motivation_gives_high_priority(self):
        assert self._priority({"motivation_level": 9}) == "high"
        assert self._priority({"motivation_level": 8}) == "high"

    def test_is_hot_lead_gives_high_priority(self):
        assert self._priority({"is_hot_lead": True, "motivation_level": 3}) == "high"

    def test_medium_motivation_gives_medium(self):
        assert self._priority({"motivation_level": 5}) == "medium"

    def test_explicit_followup_priority_high(self):
        assert self._priority({"followup_priority": "high", "motivation_level": 4}) == "high"

    def test_low_motivation_no_signals_gives_low(self):
        assert self._priority({"motivation_level": 1}) == "low"

    def test_empty_intel_gives_low(self):
        assert self._priority({}) == "low"

    def test_none_motivation_with_no_signals_gives_low(self):
        assert self._priority({"motivation_level": None}) == "low"


# ──────────────────────────────────────────────────────────────────
# Operator state transitions
# ──────────────────────────────────────────────────────────────────

class TestOperatorTransitions:
    def test_valid_state_transitions_all_states(self):
        from backend.workflows.engine import WORKFLOW_STATES
        with patch("backend.lib.db.insert_workflow_transition") as mock_t, \
             patch("backend.lib.db.insert_call_event"):
            from backend.workflows.engine import transition_state
            for state in WORKFLOW_STATES:
                mock_t.reset_mock()
                transition_state("lead-1", state)
                mock_t.assert_called_once()

    def test_invalid_state_raises_value_error(self):
        import pytest
        from backend.workflows.engine import transition_state
        with pytest.raises(ValueError, match="Invalid workflow state"):
            transition_state("lead-1", "invalid_state_xyz")

    def test_invalid_state_does_not_call_db(self):
        with patch("backend.lib.db.insert_workflow_transition") as mock_t:
            from backend.workflows.engine import transition_state
            try:
                transition_state("lead-1", "not_a_state")
            except ValueError:
                pass
            mock_t.assert_not_called()

    def test_transition_state_uses_operator_source(self):
        with patch("backend.lib.db.insert_workflow_transition") as mock_t, \
             patch("backend.lib.db.insert_call_event"):
            from backend.workflows.engine import transition_state
            transition_state("lead-1", "followup_required")
        assert "operator" in str(mock_t.call_args)


# ──────────────────────────────────────────────────────────────────
# Karoathys state snapshot
# ──────────────────────────────────────────────────────────────────

class TestKaroathysSnapshot:
    def test_snapshot_has_required_keys(self):
        with patch("backend.lib.db.get_pipeline_by_workflow_state", return_value={}), \
             patch("backend.lib.db.get_hot_leads_queue", return_value=[]), \
             patch("backend.lib.db.get_pending_followups", return_value=[]), \
             patch("backend.lib.db.get_appointment_queue", return_value=[]), \
             patch("backend.lib.db.get_workflow_activity", return_value=[]):
            from backend.workflows.engine import get_karoathys_state_snapshot
            snap = get_karoathys_state_snapshot()

        required_keys = ["schema_version", "karoathys_compat", "timestamp",
                         "system", "pipeline", "hot_leads", "followup_queue",
                         "recent_events", "intelligence_primitives"]
        for key in required_keys:
            assert key in snap, f"Missing key: {key}"

    def test_snapshot_karoathys_compat_true(self):
        with patch("backend.lib.db.get_pipeline_by_workflow_state", return_value={}), \
             patch("backend.lib.db.get_hot_leads_queue", return_value=[]), \
             patch("backend.lib.db.get_pending_followups", return_value=[]), \
             patch("backend.lib.db.get_appointment_queue", return_value=[]), \
             patch("backend.lib.db.get_workflow_activity", return_value=[]):
            from backend.workflows.engine import get_karoathys_state_snapshot
            snap = get_karoathys_state_snapshot()
        assert snap["karoathys_compat"] is True

    def test_snapshot_system_counts_structure(self):
        pipeline = {"active_contact": 3, "dead_lead": 2, "closed": 1}
        with patch("backend.lib.db.get_pipeline_by_workflow_state", return_value=pipeline), \
             patch("backend.lib.db.get_hot_leads_queue", return_value=[{"id": "x"}]), \
             patch("backend.lib.db.get_pending_followups", return_value=[{"id": "y"}, {"id": "z"}]), \
             patch("backend.lib.db.get_appointment_queue", return_value=[]), \
             patch("backend.lib.db.get_workflow_activity", return_value=[]):
            from backend.workflows.engine import get_karoathys_state_snapshot
            snap = get_karoathys_state_snapshot()
        assert snap["system"]["hot_leads"] == 1
        assert snap["system"]["pending_followups"] == 2
        assert snap["system"]["active_workflows"] == 3  # dead + closed excluded

    def test_snapshot_intelligence_primitives(self):
        with patch("backend.lib.db.get_pipeline_by_workflow_state", return_value={}), \
             patch("backend.lib.db.get_hot_leads_queue", return_value=[]), \
             patch("backend.lib.db.get_pending_followups", return_value=[]), \
             patch("backend.lib.db.get_appointment_queue", return_value=[]), \
             patch("backend.lib.db.get_workflow_activity", return_value=[]):
            from backend.workflows.engine import get_karoathys_state_snapshot
            snap = get_karoathys_state_snapshot()
        prims = snap["intelligence_primitives"]
        assert prims["transcript_chunks_enabled"] is True
        assert prims["intel_extraction_enabled"] is True
        assert prims["followup_urgency_scoring"] is True
        assert prims["hot_lead_detection"] is True


# ──────────────────────────────────────────────────────────────────
# Workflow metadata includes karoathys_compat
# ──────────────────────────────────────────────────────────────────

class TestKaroathysCompatMetadata:
    def test_trigger_workflow_includes_karoathys_compat(self):
        with patch("backend.lib.db.insert_call_event"), \
             patch("backend.lib.db.insert_workflow_transition") as mock_t, \
             patch("backend.lib.db.create_followup", return_value=None):
            mock_t.return_value = True
            from backend.workflows.engine import trigger_from_call_outcome
            trigger_from_call_outcome("call-1", "lead-1", "WARM", {})
        call_kwargs = mock_t.call_args[1] if mock_t.call_args[1] else {}
        metadata = call_kwargs.get("metadata") or {}
        assert metadata.get("karoathys_compat") is True

    def test_transition_state_includes_karoathys_compat(self):
        with patch("backend.lib.db.insert_workflow_transition") as mock_t, \
             patch("backend.lib.db.insert_call_event"):
            from backend.workflows.engine import transition_state
            transition_state("lead-1", "followup_required", metadata={"operator": "test"})
        call_kwargs = mock_t.call_args[1] if mock_t.call_args[1] else {}
        metadata = call_kwargs.get("metadata") or {}
        assert metadata.get("karoathys_compat") is True


# ──────────────────────────────────────────────────────────────────
# Pipeline movement + event propagation
# ──────────────────────────────────────────────────────────────────

class TestPipelineMovement:
    def test_dead_disposition_emits_workflow_event(self):
        emitted = []
        with patch("backend.lib.db.insert_call_event", side_effect=lambda **kw: emitted.append(kw)), \
             patch("backend.lib.db.insert_workflow_transition", return_value=True), \
             patch("backend.lib.db.create_followup", return_value=None):
            from backend.workflows.engine import trigger_from_call_outcome
            trigger_from_call_outcome("call-1", "lead-1", "DEAD", {})
        event_types = [e["event_type"] for e in emitted]
        assert any("workflow" in et for et in event_types)

    def test_hot_lead_intel_emits_hot_lead_detected(self):
        emitted = []
        with patch("backend.lib.db.insert_call_event", side_effect=lambda **kw: emitted.append(kw)), \
             patch("backend.lib.db.insert_workflow_transition", return_value=True), \
             patch("backend.lib.db.create_followup", return_value=None):
            from backend.workflows.engine import trigger_from_call_outcome
            trigger_from_call_outcome(
                "call-1", "lead-1", "WARM",
                {"is_hot_lead": True, "motivation_level": 9},
            )
        event_types = [e["event_type"] for e in emitted]
        assert "hot_lead_detected" in event_types

    def test_appointment_interest_emits_appointment_detected(self):
        emitted = []
        with patch("backend.lib.db.insert_call_event", side_effect=lambda **kw: emitted.append(kw)), \
             patch("backend.lib.db.insert_workflow_transition", return_value=True), \
             patch("backend.lib.db.create_followup", return_value=None):
            from backend.workflows.engine import trigger_from_call_outcome
            trigger_from_call_outcome("call-1", "lead-1", "HOT", {"appointment_interest": True})
        event_types = [e["event_type"] for e in emitted]
        assert "appointment_detected" in event_types

    def test_workflow_created_emitted_when_state_is_new(self):
        emitted = []
        with patch("backend.lib.db.insert_call_event", side_effect=lambda **kw: emitted.append(kw)), \
             patch("backend.lib.db.insert_workflow_transition", return_value=True), \
             patch("backend.lib.db.create_followup", return_value=None):
            from backend.workflows.engine import trigger_from_call_outcome
            trigger_from_call_outcome("call-1", "lead-1", "WARM", {})
        event_types = [e["event_type"] for e in emitted]
        assert "workflow_created" in event_types

    def test_workflow_updated_emitted_when_state_unchanged(self):
        emitted = []
        with patch("backend.lib.db.insert_call_event", side_effect=lambda **kw: emitted.append(kw)), \
             patch("backend.lib.db.insert_workflow_transition", return_value=False), \
             patch("backend.lib.db.create_followup", return_value=None):
            from backend.workflows.engine import trigger_from_call_outcome
            trigger_from_call_outcome("call-1", "lead-1", "WARM", {})
        event_types = [e["event_type"] for e in emitted]
        assert "workflow_updated" in event_types
