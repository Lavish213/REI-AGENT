import pytest
from unittest.mock import MagicMock, patch


def _make_ctx(**kwargs):
    from backend.voice.processors.context_tracker import CallContext
    ctx = CallContext()
    for k, v in kwargs.items():
        setattr(ctx, k, v)
    return ctx


class TestPreflightGate:
    def test_always_allowed_tools_pass(self):
        from backend.voice.tools import _preflight_gate
        ctx = _make_ctx(lead_id="test123", fallback_mode=False, conflict_active=False, intel_packet={})
        for tool in ["end_call", "transfer_call", "ask_operator", "set_disposition"]:
            result = _preflight_gate(tool, {}, ctx)
            assert not result["blocked"], f"{tool} should always be allowed"

    def test_fallback_mode_blocks_risky_tools(self):
        from backend.voice.tools import _preflight_gate
        from backend.contracts.intel_packet import DEFAULT_FALLBACK_PERMISSIONS
        ctx = _make_ctx(lead_id="test123", fallback_mode=True, conflict_active=False, intel_packet={"action_permissions": DEFAULT_FALLBACK_PERMISSIONS})
        result = _preflight_gate("send_offer_summary", {"lead_id": "test123"}, ctx)
        assert result["blocked"]
        assert "system" in result["message"].lower() or "follow" in result["message"].lower()

    def test_conflict_active_blocks_offer_tools(self):
        from backend.voice.tools import _preflight_gate
        ctx = _make_ctx(lead_id="test123", fallback_mode=False, conflict_active=True, intel_packet={})
        with patch("backend.lib.db.create_approval_request", return_value="appr123"), \
             patch("backend.lib.db.write_tool_gate_log"):
            result = _preflight_gate("get_offer_range", {"lead_id": "test123"}, ctx)
        assert result["blocked"]

    def test_blocked_permission_level(self):
        from backend.voice.tools import _preflight_gate
        packet = {"action_permissions": {"get_offer_range": {"level": "blocked", "scope": "call", "granted_by": "bob"}}}
        ctx = _make_ctx(lead_id="test123", fallback_mode=False, conflict_active=False, intel_packet=packet)
        with patch("backend.lib.db.write_tool_gate_log"):
            result = _preflight_gate("get_offer_range", {"lead_id": "test123"}, ctx)
        assert result["blocked"]

    def test_ask_only_level_returns_message(self):
        from backend.voice.tools import _preflight_gate
        packet = {"action_permissions": {"get_offer_range": {"level": "ask_only", "scope": "call", "granted_by": "system"}}}
        ctx = _make_ctx(lead_id="test123", fallback_mode=False, conflict_active=False, intel_packet=packet)
        with patch("backend.lib.db.write_tool_gate_log"):
            result = _preflight_gate("get_offer_range", {"lead_id": "test123"}, ctx)
        assert result["blocked"]
        assert "Alanzo" in result["message"] or "follow" in result["message"].lower()

    def test_open_permission_passes(self):
        from backend.voice.tools import _preflight_gate
        from backend.contracts.intel_packet import DEFAULT_OPEN_PERMISSIONS
        ctx = _make_ctx(lead_id="test123", fallback_mode=False, conflict_active=False, intel_packet={"action_permissions": DEFAULT_OPEN_PERMISSIONS})
        with patch("backend.lib.db.write_tool_gate_log"):
            result = _preflight_gate("get_offer_range", {"lead_id": "test123"}, ctx)
        assert not result["blocked"]


class TestConflictDetection:
    def test_seller_above_max_offer(self):
        from backend.lib.intel_assembler import _detect_conflicts
        flags = _detect_conflicts(bob_max_offer=340000, comp_arv=380000, seller_price_floor=390000)
        types = [f["type"] for f in flags]
        assert "SELLER_ABOVE_MAX_OFFER" in types

    def test_comp_below_max_offer(self):
        from backend.lib.intel_assembler import _detect_conflicts
        flags = _detect_conflicts(bob_max_offer=340000, comp_arv=280000, seller_price_floor=None)
        types = [f["type"] for f in flags]
        assert "COMP_BELOW_MAX_OFFER" in types

    def test_spread_too_thin(self):
        from backend.lib.intel_assembler import _detect_conflicts
        flags = _detect_conflicts(bob_max_offer=None, comp_arv=310000, seller_price_floor=308000)
        types = [f["type"] for f in flags]
        assert "SPREAD_TOO_THIN" in types

    def test_no_conflict_clean_deal(self):
        from backend.lib.intel_assembler import _detect_conflicts
        flags = _detect_conflicts(bob_max_offer=340000, comp_arv=420000, seller_price_floor=280000)
        assert flags == []


class TestPacketSchema:
    def test_migrate_old_packet(self):
        from backend.contracts.intel_packet import migrate_packet, PACKET_SCHEMA_VERSION
        old = {"lead_id": "x", "seller_profile": {}}
        result = migrate_packet(old)
        assert result["schema_version"] == PACKET_SCHEMA_VERSION
        assert "action_permissions" in result
        assert "conflict_flags" in result

    def test_get_permission_level_defaults(self):
        from backend.contracts.intel_packet import get_permission_level
        packet = {}
        assert get_permission_level(packet, "get_offer_range") == "blocked"

    def test_permission_expiry(self):
        from backend.contracts.intel_packet import is_permission_expired
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        assert is_permission_expired({"expires_at": past})
        assert not is_permission_expired({"expires_at": future})
        assert not is_permission_expired({})


class TestKillSwitch:
    def test_kill_switch_triggers_on_escalation_word(self):
        from backend.voice.processors.analysis_callbacks import AnalysisCallbackProcessor
        ctx = _make_ctx(
            lead_id="test123",
            intel_packet={"compliance_context": {"escalation_triggers": ["lawsuit", "attorney"]}},
            kill_switch_active=False,
        )
        processor = AnalysisCallbackProcessor.__new__(AnalysisCallbackProcessor)
        processor._ctx = ctx
        processor._check_kill_switch("I'm going to talk to my attorney about this")
        assert ctx.kill_switch_active

    def test_kill_switch_does_not_trigger_on_safe_text(self):
        from backend.voice.processors.analysis_callbacks import AnalysisCallbackProcessor
        ctx = _make_ctx(
            lead_id="test123",
            intel_packet={"compliance_context": {"escalation_triggers": ["lawsuit", "attorney"]}},
            kill_switch_active=False,
        )
        processor = AnalysisCallbackProcessor.__new__(AnalysisCallbackProcessor)
        processor._ctx = ctx
        processor._check_kill_switch("Yeah I'm thinking about selling sometime this year")
        assert not ctx.kill_switch_active


class TestIdempotency:
    def test_idem_key_deterministic(self):
        from backend.lib.db import _idem_key
        k1 = _idem_key("lead123", "call456", "call_completed")
        k2 = _idem_key("lead123", "call456", "call_completed")
        assert k1 == k2

    def test_idem_key_different_inputs(self):
        from backend.lib.db import _idem_key
        k1 = _idem_key("lead123", "call456", "call_completed")
        k2 = _idem_key("lead123", "call456", "turn_signals")
        assert k1 != k2
