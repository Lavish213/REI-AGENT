from unittest.mock import patch


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _make_messages(turns: list[tuple[str, str]]) -> list[dict]:
    """Build LLM context messages from (role, text) pairs."""
    msgs = [
        {"role": "system", "content": "You are Sophia."},
        {"role": "user", "content": "[call started]"},
    ]
    for role, text in turns:
        msgs.append({"role": role, "content": text})
    return msgs


# ──────────────────────────────────────────────────────────────────
# Transcript construction
# ──────────────────────────────────────────────────────────────────

class TestTranscriptBuilding:
    def _build_flat(self, messages):
        from backend.voice.agent import _build_transcript
        return _build_transcript(messages)

    def _build_chunks(self, messages):
        from backend.voice.agent import _build_transcript_chunks
        return _build_transcript_chunks(messages)

    def test_flat_transcript_skips_system_and_start(self):
        msgs = _make_messages([("user", "Hello"), ("assistant", "Hi there")])
        flat = self._build_flat(msgs)
        assert "You are Sophia" not in flat
        assert "[call started]" not in flat
        assert "SELLER: Hello" in flat
        assert "SOPHIA: Hi there" in flat

    def test_flat_transcript_correct_speakers(self):
        msgs = _make_messages([
            ("user", "Want to sell"),
            ("assistant", "Tell me more"),
            ("user", "Need quick close"),
        ])
        flat = self._build_flat(msgs)
        lines = flat.splitlines()
        assert lines[0].startswith("SELLER:")
        assert lines[1].startswith("SOPHIA:")
        assert lines[2].startswith("SELLER:")

    def test_chunks_exclude_system_and_start(self):
        msgs = _make_messages([("user", "Hi"), ("assistant", "Hello")])
        chunks = self._build_chunks(msgs)
        speakers = [c["speaker"] for c in chunks]
        assert "SYSTEM" not in speakers
        for c in chunks:
            assert c["text"] != "[call started]"

    def test_chunks_speaker_mapping(self):
        msgs = _make_messages([
            ("user", "I want to sell"),
            ("assistant", "Great, tell me more"),
        ])
        chunks = self._build_chunks(msgs)
        assert len(chunks) == 2
        assert chunks[0]["speaker"] == "SELLER"
        assert chunks[1]["speaker"] == "SOPHIA"

    def test_chunks_sequential_order(self):
        msgs = _make_messages([
            ("user", "A"),
            ("assistant", "B"),
            ("user", "C"),
            ("assistant", "D"),
        ])
        chunks = self._build_chunks(msgs)
        orders = [c["sequence_order"] for c in chunks]
        assert orders == sorted(orders)
        assert orders == list(range(len(chunks)))

    def test_chunks_chunk_type_final(self):
        msgs = _make_messages([("user", "Test")])
        chunks = self._build_chunks(msgs)
        assert all(c["chunk_type"] == "final" for c in chunks)

    def test_empty_messages_returns_empty(self):
        msgs = [{"role": "system", "content": "You are Sophia."}]
        flat = self._build_flat(msgs)
        chunks = self._build_chunks(msgs)
        assert flat == ""
        assert chunks == []

    def test_deterministic_ordering(self):
        msgs = _make_messages([("user", "A"), ("assistant", "B"), ("user", "C")])
        chunks1 = self._build_chunks(msgs)
        chunks2 = self._build_chunks(msgs)
        assert [c["sequence_order"] for c in chunks1] == [c["sequence_order"] for c in chunks2]
        assert [c["text"] for c in chunks1] == [c["text"] for c in chunks2]

    def test_flat_and_chunks_text_consistency(self):
        msgs = _make_messages([
            ("user", "I need to sell fast"),
            ("assistant", "I understand, tell me about the property"),
        ])
        flat = self._build_flat(msgs)
        chunks = self._build_chunks(msgs)
        for chunk in chunks:
            assert chunk["text"] in flat

    def test_no_duplicate_sequence_orders(self):
        msgs = _make_messages([
            ("user", "Turn 1"),
            ("assistant", "Turn 2"),
            ("user", "Turn 3"),
            ("assistant", "Turn 4"),
        ])
        chunks = self._build_chunks(msgs)
        orders = [c["sequence_order"] for c in chunks]
        assert len(orders) == len(set(orders))


# ──────────────────────────────────────────────────────────────────
# Transcript recovery
# ──────────────────────────────────────────────────────────────────

class TestTranscriptRecovery:
    def test_reconstruct_from_chunks(self):
        chunks = [
            {"speaker": "SELLER", "text": "Hi there", "sequence_order": 0},
            {"speaker": "SOPHIA", "text": "Hello!", "sequence_order": 1},
            {"speaker": "SELLER", "text": "Want to sell", "sequence_order": 2},
        ]
        lines = [f"{c['speaker']}: {c['text']}" for c in chunks]
        reconstructed = "\n".join(lines)
        assert "SELLER: Hi there" in reconstructed
        assert "SOPHIA: Hello!" in reconstructed
        assert reconstructed.index("SELLER: Hi there") < reconstructed.index("SELLER: Want to sell")

    def test_reconstruct_preserves_order(self):
        chunks = [
            {"speaker": "SOPHIA", "text": "B", "sequence_order": 1},
            {"speaker": "SELLER", "text": "A", "sequence_order": 0},
        ]
        sorted_chunks = sorted(chunks, key=lambda c: c["sequence_order"])
        lines = [f"{c['speaker']}: {c['text']}" for c in sorted_chunks]
        reconstructed = "\n".join(lines)
        assert reconstructed.index("SELLER: A") < reconstructed.index("SOPHIA: B")


# ──────────────────────────────────────────────────────────────────
# Extraction schema validation
# ──────────────────────────────────────────────────────────────────

class TestExtractionSchema:
    REQUIRED_FIELDS = [
        "motivation_level", "seller_motivation", "motivation_confidence",
        "price_floor", "asking_price", "timeline", "timeline_urgency",
        "property_condition", "occupancy", "hot_topics", "rapport_openers",
        "competitor_mentions", "distress_indicators", "objections",
        "appointment_interest", "seller_name", "property_address",
        "next_step", "next_best_action", "followup_priority",
        "lead_score", "extraction_confidence", "call_summary",
    ]

    def test_intel_prompt_contains_all_required_fields(self):
        from backend.qa.transcript_intel import INTEL_PROMPT
        for field in self.REQUIRED_FIELDS:
            assert field in INTEL_PROMPT, f"INTEL_PROMPT missing field: {field}"

    def test_timeline_urgency_valid_values(self):
        from backend.qa.transcript_intel import INTEL_PROMPT
        for val in ("immediate", "weeks", "months", "unknown"):
            assert val in INTEL_PROMPT

    def test_followup_priority_valid_values(self):
        from backend.qa.transcript_intel import INTEL_PROMPT
        for val in ("high", "medium", "low"):
            assert val in INTEL_PROMPT

    def test_property_condition_valid_values(self):
        from backend.qa.transcript_intel import INTEL_PROMPT
        for val in ("excellent", "good", "fair", "poor", "unknown"):
            assert val in INTEL_PROMPT

    def test_occupancy_valid_values(self):
        from backend.qa.transcript_intel import INTEL_PROMPT
        for val in ("owner_occupied", "tenant_occupied", "vacant", "unknown"):
            assert val in INTEL_PROMPT


# ──────────────────────────────────────────────────────────────────
# Lead scoring derivation
# ──────────────────────────────────────────────────────────────────

class TestLeadScoreDerivation:
    def _score(self, intel):
        from backend.qa.transcript_intel import _compute_lead_scores
        return _compute_lead_scores(intel)

    def test_high_motivation_immediate_timeline_is_hot(self):
        result = self._score({"motivation_level": 9, "timeline_urgency": "immediate"})
        assert result["is_hot_lead"] is True
        assert result["followup_urgency"] >= 9

    def test_low_motivation_unknown_timeline_not_hot(self):
        result = self._score({"motivation_level": 3, "timeline_urgency": "unknown"})
        assert result["is_hot_lead"] is False
        assert result["followup_urgency"] <= 5

    def test_appointment_interest_boosts_urgency(self):
        base = self._score({"motivation_level": 6, "timeline_urgency": "months"})
        with_appt = self._score({"motivation_level": 6, "timeline_urgency": "months", "appointment_interest": True})
        assert with_appt["followup_urgency"] > base["followup_urgency"]

    def test_appointment_interest_with_moderate_motivation_is_hot(self):
        result = self._score({"motivation_level": 7, "timeline_urgency": "weeks", "appointment_interest": True})
        assert result["is_hot_lead"] is True

    def test_urgency_capped_at_10(self):
        result = self._score({
            "motivation_level": 10,
            "timeline_urgency": "immediate",
            "appointment_interest": True,
        })
        assert result["followup_urgency"] <= 10

    def test_missing_fields_default_gracefully(self):
        result = self._score({})
        assert result["followup_urgency"] == 0
        assert result["is_hot_lead"] is False

    def test_weeks_timeline_boosts_urgency(self):
        base = self._score({"motivation_level": 5, "timeline_urgency": "unknown"})
        weeks = self._score({"motivation_level": 5, "timeline_urgency": "weeks"})
        assert weeks["followup_urgency"] > base["followup_urgency"]


# ──────────────────────────────────────────────────────────────────
# Linkage validation
# ──────────────────────────────────────────────────────────────────

class TestCallLinkage:
    def test_call_data_includes_property_id(self):
        lead = {"id": "lead-1", "property_id": "prop-2"}
        call_data = {
            "lead_id": lead["id"],
            "property_id": lead.get("property_id"),
            "signalwire_call_id": "sid-abc",
        }
        assert call_data["property_id"] == "prop-2"
        assert call_data["lead_id"] == "lead-1"

    def test_call_data_without_property_id_is_none(self):
        lead = {"id": "lead-1"}
        call_data = {
            "lead_id": lead["id"],
            "property_id": lead.get("property_id"),
        }
        assert call_data["property_id"] is None

    def test_chunks_reference_correct_call_id(self):
        call_id = "call-uuid-123"
        lead_id = "lead-uuid-456"
        chunks = [
            {"speaker": "SELLER", "text": "Hi", "chunk_type": "final", "sequence_order": 0, "confidence": None},
        ]
        rows = [
            {
                "call_id": call_id,
                "lead_id": lead_id,
                "speaker": c["speaker"],
                "text": c["text"],
                "chunk_type": c["chunk_type"],
                "sequence_order": c["sequence_order"],
                "confidence": c.get("confidence"),
            }
            for c in chunks
        ]
        assert all(r["call_id"] == call_id for r in rows)
        assert all(r["lead_id"] == lead_id for r in rows)


# ──────────────────────────────────────────────────────────────────
# Event system
# ──────────────────────────────────────────────────────────────────

class TestEventSystem:
    def test_canonical_event_constants_defined(self):
        from backend.voice.events import (
            TRANSCRIPT_COMPLETED, SUMMARY_GENERATED, LEAD_SCORED,
            PROPERTY_DETECTED, MOTIVATION_DETECTED, APPOINTMENT_DETECTED,
            FOLLOWUP_REQUIRED,
        )
        events = [
            TRANSCRIPT_COMPLETED, SUMMARY_GENERATED, LEAD_SCORED,
            PROPERTY_DETECTED, MOTIVATION_DETECTED, APPOINTMENT_DETECTED,
            FOLLOWUP_REQUIRED,
        ]
        assert all(isinstance(e, str) and len(e) > 0 for e in events)
        assert len(set(events)) == len(events)

    @patch("backend.lib.db.insert_call_event")
    def test_emit_event_calls_insert(self, mock_insert):
        from backend.voice.events import emit_event
        emit_event("transcript_completed", "call-1", "lead-1", {"chunk_count": 5})
        mock_insert.assert_called_once_with(
            call_id="call-1",
            lead_id="lead-1",
            event_type="transcript_completed",
            payload={"chunk_count": 5},
        )

    @patch("backend.lib.db.insert_call_event")
    def test_emit_event_survives_db_error(self, mock_insert):
        mock_insert.side_effect = Exception("DB down")
        from backend.voice.events import emit_event
        emit_event("lead_scored", "call-1")  # should not raise

    @patch("backend.lib.db.insert_call_event")
    def test_emit_intel_events_motivation_detected(self, mock_insert):
        from backend.voice.events import emit_intel_events
        intel = {
            "motivation_level": 8,
            "timeline_urgency": "weeks",
            "call_summary": "Good call",
            "followup_priority": "high",
            "next_step": "call back Monday",
        }
        emit_intel_events("call-1", "lead-1", intel)
        call_types = [call.kwargs["event_type"] for call in mock_insert.call_args_list]
        assert "motivation_detected" in call_types
        assert "summary_generated" in call_types
        assert "followup_required" in call_types

    @patch("backend.lib.db.insert_call_event")
    def test_emit_intel_events_appointment_detected(self, mock_insert):
        from backend.voice.events import emit_intel_events
        intel = {"appointment_interest": True, "call_summary": "s", "followup_priority": "high"}
        emit_intel_events("call-1", "lead-1", intel)
        call_types = [call.kwargs["event_type"] for call in mock_insert.call_args_list]
        assert "appointment_detected" in call_types

    @patch("backend.lib.db.insert_call_event")
    def test_emit_intel_events_empty_intel_no_emit(self, mock_insert):
        from backend.voice.events import emit_intel_events
        emit_intel_events("call-1", "lead-1", {})
        mock_insert.assert_not_called()


# ──────────────────────────────────────────────────────────────────
# Prior call context builder (regression)
# ──────────────────────────────────────────────────────────────────

class TestPriorCallContext:
    def test_no_summary_returns_none(self):
        from backend.qa.transcript_intel import build_prior_call_context
        assert build_prior_call_context({}) is None

    def test_with_summary_includes_context(self):
        from backend.qa.transcript_intel import build_prior_call_context
        lead = {
            "call_summary": "Seller is motivated, divorce situation",
            "motivation_level": 8,
            "timeline_urgency": "weeks",
            "price_floor": 18000000,
            "hot_topics": ["divorce", "timeline"],
        }
        ctx = build_prior_call_context(lead)
        assert "PREVIOUS CALL CONTEXT" in ctx
        assert "divorce" in ctx
        assert "8/10" in ctx
        assert "weeks" in ctx
        assert "$180,000" in ctx

    def test_price_floor_formats_as_dollars(self):
        from backend.qa.transcript_intel import build_prior_call_context
        lead = {"call_summary": "s", "price_floor": 25000000}
        ctx = build_prior_call_context(lead)
        assert "$250,000" in ctx
