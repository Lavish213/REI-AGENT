from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

PACKET_SCHEMA_VERSION = "1.0"

PACKET_STATES = frozenset([
    "draft",
    "system_assembled",
    "bob_enriched",
    "in_call_active",
    "stale",
    "conflicted",
    "operator_locked",
    "approved",
    "fallback",
    "expired",
])

ACTION_LEVELS = frozenset([
    "ask_only",
    "discuss_concept",
    "send_summary",
    "quote_range",
    "book_appointment",
    "ask_operator_required",
    "blocked",
])

GATED_TOOLS = frozenset([
    "set_disposition",
    "send_offer_summary",
    "send_followup_email",
    "collect_and_send_email",
    "book_appointment",
    "get_offer_range",
    "drop_voicemail",
])

ALWAYS_ALLOWED_TOOLS = frozenset([
    "end_call",
    "honor_stop_request",
])

DEFAULT_FALLBACK_PERMISSIONS: dict[str, dict] = {
    "book_appointment":        {"level": "book_appointment", "scope": "call", "granted_by": "fallback"},
    "schedule_followup":       {"level": "book_appointment", "scope": "call", "granted_by": "fallback"},
    "send_offer_summary":      {"level": "blocked",          "scope": "call", "granted_by": "fallback", "reason": "system_degraded"},
    "get_offer_range":         {"level": "blocked",          "scope": "call", "granted_by": "fallback", "reason": "system_degraded"},
    "send_followup_email":     {"level": "blocked",          "scope": "call", "granted_by": "fallback", "reason": "system_degraded"},
    "collect_and_send_email":  {"level": "blocked",          "scope": "call", "granted_by": "fallback", "reason": "system_degraded"},
    "drop_voicemail":          {"level": "blocked",          "scope": "call", "granted_by": "fallback", "reason": "system_degraded"},
}

DEFAULT_DENY_PERMISSIONS: dict[str, dict] = {
    "book_appointment":        {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "send_offer_summary":      {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "get_offer_range":         {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "send_followup_email":     {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "collect_and_send_email":  {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "drop_voicemail":          {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "send_followup_sms":       {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "schedule_followup":       {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "schedule_callback":       {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "set_disposition":         {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "transfer_call":           {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
    "ask_operator":            {"level": "blocked", "scope": "call", "granted_by": "deny_default", "reason": "no_intel_packet"},
}


def migrate_packet(raw: dict) -> dict:
    v = raw.get("schema_version", "0.0")
    if v == PACKET_SCHEMA_VERSION:
        return raw
    raw.setdefault("action_permissions", {})
    raw.setdefault("conflict_flags", [])
    raw.setdefault("safe_for_live_call", False)
    raw.setdefault("packet_state", "system_assembled")
    raw.setdefault("pending_update", None)
    raw["schema_version"] = PACKET_SCHEMA_VERSION
    return raw


def get_permission_level(packet: dict, tool_name: str) -> str:
    if tool_name in ALWAYS_ALLOWED_TOOLS:
        return "allowed"
    if not isinstance(packet, dict):
        return "blocked"
    perms = packet.get("action_permissions") or {}
    perm = perms.get(tool_name) or {}
    level = perm.get("level")
    if not isinstance(level, str) or not level:
        return "blocked"
    return level


def is_permission_expired(perm: dict) -> bool:
    from datetime import datetime, timezone
    expires_at = perm.get("expires_at")
    if not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except Exception:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > exp


def build_prompt_intel_slice(packet: dict) -> str:
    if not packet or packet.get("packet_state") in ("missing", "expired", "fallback"):
        return ""
    strategy = packet.get("strategy_context") or {}
    negotiation = packet.get("negotiation_context") or {}
    compliance = packet.get("compliance_context") or {}
    simulation = packet.get("simulation_intelligence") or {}

    parts = ["## Pre-call acquisition intelligence"]

    primary = strategy.get("primary_strategy")
    if primary:
        backup = strategy.get("backup_strategy", "")
        parts.append(f"Strategy: {primary}" + (f" | Backup: {backup}" if backup else ""))

    max_offer = strategy.get("max_offer")
    if max_offer:
        parts.append(f"Max offer authority: ${int(max_offer):,}")

    tone = negotiation.get("recommended_tone")
    if tone:
        parts.append(f"Tone: {tone}")

    dnp = strategy.get("do_not_pitch") or []
    if dnp:
        parts.append(f"Do NOT pitch: {', '.join(dnp)}")

    objections = negotiation.get("likely_objections") or simulation.get("likely_reactions") or []
    if objections:
        parts.append(f"Watch for: {', '.join(objections[:4])}")

    walkaway = negotiation.get("walkaway_conditions") or []
    if walkaway:
        parts.append(f"Walkaway if: {', '.join(walkaway[:2])}")

    approval_threshold = compliance.get("requires_human_approval_above")
    if approval_threshold:
        parts.append(f"Approval required above: ${int(approval_threshold):,}")

    state = packet.get("packet_state", "system_assembled")
    version = packet.get("packet_version", 1)
    parts.append(f"Intel: {state} v{version}")

    if packet.get("conflict_flags"):
        parts.append("⚠️ CONFLICT DETECTED — ask operator before strategy discussion")

    return "\n".join(parts)
