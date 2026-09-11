from __future__ import annotations

import os
from dataclasses import dataclass

from loguru import logger

IDENTITY_KEYS = frozenset({
    "lead_id",
    "tenant_id",
    "seller_phone",
    "to",
    "email",
    "owner_email",
    "phone",
    "address",
    "call_sid",
})

STOP_TOOL = "honor_stop_request"

SIDE_EFFECT_TOOLS = frozenset({
    "set_disposition",
    "book_appointment",
    "send_followup_sms",
    "send_followup_email",
    "send_offer_summary",
    "collect_and_send_email",
    "drop_voicemail",
    "schedule_followup",
    "schedule_callback",
    "transfer_call",
    "ask_operator",
    "get_offer_range",
})


class ContextResolutionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedContext:
    lead_id: str
    call_sid: str
    tenant_id: str
    seller_phone: str
    seller_email: str
    address: str

    def server_values(self) -> dict[str, str]:
        return {
            "lead_id": self.lead_id,
            "tenant_id": self.tenant_id,
            "seller_phone": self.seller_phone,
            "to": self.seller_phone,
            "email": self.seller_email,
            "owner_email": self.seller_email,
            "phone": self.seller_phone,
            "address": self.address,
            "call_sid": self.call_sid,
        }


def outbound_enabled() -> bool:
    return os.environ.get("OUTBOUND_ENABLED", "false").strip().lower() == "true"


def configured_tenant() -> str:
    return os.environ.get("TENANT_ID", "").strip()


def _resolve_tenant(lead: dict, lead_id: str) -> str:
    system_tenant = configured_tenant()
    if not system_tenant:
        raise ContextResolutionError("no_configured_tenant")

    lead_tenant = str(lead.get("tenant_id") or "").strip()
    if not lead_tenant:
        raise ContextResolutionError("no_tenant_on_lead")

    if lead_tenant != system_tenant:
        raise ContextResolutionError("tenant_mismatch")

    return lead_tenant


def _normalize_phone(raw: str | None) -> str:
    if not raw:
        return ""
    digits = "".join(c for c in str(raw) if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    return ""


def resolve(call_ctx) -> ResolvedContext:
    from backend.lib import db

    if call_ctx is None:
        raise ContextResolutionError("no_call_context")

    lead_id = (getattr(call_ctx, "lead_id", "") or "").strip()
    if not lead_id:
        raise ContextResolutionError("no_lead_id")

    call_sid = (getattr(call_ctx, "_call_sid", "") or "").strip()
    if not call_sid:
        raise ContextResolutionError("no_call_sid")

    lead = db.get_lead_with_property(lead_id)
    if not lead:
        raise ContextResolutionError("lead_not_found")

    tenant_id = _resolve_tenant(lead, lead_id)

    seller_phone = _normalize_phone(
        lead.get("owner_phone") or getattr(call_ctx, "seller_phone", "")
    )
    if not seller_phone:
        raise ContextResolutionError("no_verified_contact_point")

    seller_email = (lead.get("owner_email") or "").strip()

    prop = lead.get("properties") or {}
    if isinstance(prop, list):
        prop = prop[0] if prop else {}
    address = (prop.get("address") or lead.get("address") or "").strip()

    return ResolvedContext(
        lead_id=lead_id,
        call_sid=call_sid,
        tenant_id=tenant_id,
        seller_phone=seller_phone,
        seller_email=seller_email,
        address=address,
    )


def sanitize(tool_name: str, tool_input: dict | None, resolved: ResolvedContext) -> dict:
    supplied = dict(tool_input or {})
    server = resolved.server_values()

    for key in IDENTITY_KEYS:
        if key not in supplied:
            continue
        model_value = str(supplied.get(key) or "").strip()
        server_value = server.get(key, "")
        if model_value and _differs(key, model_value, server_value):
            logger.warning(
                "tool_identity_rejected tool={} field={} call_sid={} lead_id={}",
                tool_name,
                key,
                resolved.call_sid,
                resolved.lead_id,
            )
        supplied.pop(key, None)

    clean = {k: v for k, v in supplied.items() if k not in IDENTITY_KEYS}
    clean.update({k: v for k, v in server.items() if v})
    return clean


def _differs(key: str, model_value: str, server_value: str) -> bool:
    if not server_value:
        return True
    if key in ("seller_phone", "to", "phone"):
        return _normalize_phone(model_value) != server_value
    return model_value.strip().lower() != server_value.strip().lower()


def redact(tool_input: dict | None) -> str:
    if not tool_input:
        return "[]"
    return "[" + ",".join(sorted(str(k) for k in tool_input)) + "]"
