from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta
from loguru import logger

_STALE_HOURS = 24


def _is_stale(assembled_at: str | None) -> bool:
    if not assembled_at:
        return True
    try:
        dt = datetime.fromisoformat(assembled_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() > _STALE_HOURS * 3600
    except Exception:
        return True


def _detect_conflicts(bob_max_offer: int | None, comp_arv: int | None, seller_price_floor: int | None) -> list[dict]:
    flags = []
    if bob_max_offer and comp_arv:
        if comp_arv < bob_max_offer * 0.85:
            flags.append({"type": "COMP_BELOW_MAX_OFFER", "bob_max": bob_max_offer, "comp_arv": comp_arv})
    if bob_max_offer and seller_price_floor:
        if seller_price_floor > bob_max_offer:
            flags.append({"type": "SELLER_ABOVE_MAX_OFFER", "bob_max": bob_max_offer, "seller_floor": seller_price_floor})
    if comp_arv and seller_price_floor:
        spread = comp_arv - seller_price_floor
        if spread < 3000000:
            flags.append({"type": "SPREAD_TOO_THIN", "spread_cents": spread})
    return flags


def assemble_intel_packet(lead_id: str) -> dict:
    from backend.lib.db import load_intel_packet, save_intel_packet, write_packet_event, _get_client
    from backend.contracts.intel_packet import (
        PACKET_SCHEMA_VERSION, DEFAULT_OPEN_PERMISSIONS, migrate_packet, PACKET_STATES
    )

    now = datetime.now(timezone.utc).isoformat()
    existing = load_intel_packet(lead_id)

    if existing:
        existing = migrate_packet(existing)
        state = existing.get("packet_state", "system_assembled")
        if state in ("operator_locked", "bob_enriched") and not _is_stale(existing.get("assembled_at")):
            logger.info("intel_assembler using existing packet lead_id={} state={}", lead_id, state)
            return existing

    client = _get_client()

    lead_resp = client.table("leads").select(
        "id,owner_first_name,owner_name,owner_email,owner_phone,disposition,"
        "motivation_level,timeline_urgency,hot_topics,call_summary,price_floor,"
        "next_best_action,drip_sequence,call_attempts,call_summaries,"
        "objections_raised,competitor_mentions"
    ).eq("id", lead_id).limit(1).execute()
    lead = lead_resp.data[0] if lead_resp.data else {}

    prop_resp = client.table("properties").select(
        "address,city,state,zip,distress_type,distress_score,"
        "estimated_arv,mao,arv_confidence,beds,baths,sqft,year_built,"
        "equity_pct,lien_amount,tax_delinquent_amount,auction_date"
    ).eq("lead_id", lead_id).limit(1).execute()
    prop = prop_resp.data[0] if prop_resp.data else {}

    motivation = lead.get("motivation_level")
    call_summary = lead.get("call_summary") or ""
    hot_topics = lead.get("hot_topics") or []
    price_floor_cents = lead.get("price_floor")
    price_floor = price_floor_cents // 100 if price_floor_cents else None
    objections = lead.get("objections_raised") or []
    timeline = lead.get("timeline_urgency")
    disposition = lead.get("disposition", "").upper()

    arv_cents = prop.get("estimated_arv")
    mao_cents = prop.get("mao")
    arv = arv_cents // 100 if arv_cents else None
    mao = mao_cents // 100 if mao_cents else None
    arv_confidence = prop.get("arv_confidence", "low")

    seller_profile = {
        "motivation": {"value": motivation, "source": "transcript_intel", "updated_at": now},
        "timeline": {"value": timeline, "source": "transcript_intel", "updated_at": now},
        "hot_topics": {"value": hot_topics, "source": "transcript_intel", "updated_at": now},
        "call_summary": {"value": call_summary, "source": "transcript_intel", "updated_at": now},
        "objections": {"value": objections, "source": "transcript_intel", "updated_at": now},
        "disposition": {"value": disposition, "source": "call_ctx", "updated_at": now},
        "call_attempts": {"value": lead.get("call_attempts", 0), "source": "db", "updated_at": now},
    }

    property_profile = {
        "address": {"value": prop.get("address"), "source": "db", "updated_at": now},
        "arv": {"value": arv, "source": "comps", "updated_at": now, "confidence": arv_confidence},
        "mao": {"value": mao, "source": "comps", "updated_at": now},
        "distress_type": {"value": prop.get("distress_type"), "source": "db", "updated_at": now},
        "distress_score": {"value": prop.get("distress_score"), "source": "db", "updated_at": now},
        "equity_pct": {"value": prop.get("equity_pct"), "source": "db", "updated_at": now},
        "auction_date": {"value": prop.get("auction_date"), "source": "db", "updated_at": now},
    }

    bob_packet = existing or {}
    bob_strategy = bob_packet.get("strategy_context") or {}
    bob_max_offer = bob_strategy.get("max_offer")

    conflict_flags = _detect_conflicts(
        bob_max_offer=bob_max_offer,
        comp_arv=arv,
        seller_price_floor=price_floor,
    )

    action_permissions = bob_packet.get("action_permissions") or DEFAULT_OPEN_PERMISSIONS.copy()

    if conflict_flags:
        for tool in ("book_appointment", "send_offer_summary", "get_offer_range", "send_followup_email"):
            action_permissions[tool] = {"level": "ask_operator_required", "scope": "call", "granted_by": "conflict_resolver", "reason": conflict_flags[0]["type"]}

    strategy_context = {**bob_packet.get("strategy_context", {})}
    if not strategy_context.get("primary_strategy"):
        distress = prop.get("distress_type", "")
        if "pre_foreclosure" in distress or "tax" in distress:
            strategy_context["primary_strategy"] = "cash"
        elif "free_and_clear" in distress or "absentee" in distress:
            strategy_context["primary_strategy"] = "seller_finance_or_cash"
        else:
            strategy_context["primary_strategy"] = "cash"

    negotiation_context = {**bob_packet.get("negotiation_context", {})}
    if not negotiation_context.get("likely_objections") and objections:
        negotiation_context["likely_objections"] = objections[:5]
    if not negotiation_context.get("recommended_tone"):
        if motivation and int(motivation) >= 8:
            negotiation_context["recommended_tone"] = "educational_low_pressure"
        elif disposition == "COLD":
            negotiation_context["recommended_tone"] = "warm_check_in"
        else:
            negotiation_context["recommended_tone"] = "curious_discovery"

    compliance_context = {**bob_packet.get("compliance_context", {})}
    compliance_context.setdefault("fair_housing_safe", True)
    compliance_context.setdefault("escalation_triggers", ["lawsuit", "attorney", "sue", "legal action", "discrimination"])

    source_map = bob_packet.get("source_map", {})
    source_map.update({
        "seller_profile": "transcript_intel",
        "property_profile": "comps_db",
        "strategy_context": "bob" if bob_packet.get("strategy_context") else "system",
        "negotiation_context": "bob" if bob_packet.get("negotiation_context") else "system",
        "compliance_context": "bob" if bob_packet.get("compliance_context") else "system",
        "action_permissions": "bob" if bob_packet.get("action_permissions") else "system",
    })

    has_conflict = bool(conflict_flags)
    packet_state = bob_packet.get("packet_state", "system_assembled")
    if packet_state not in ("operator_locked", "bob_enriched"):
        packet_state = "conflicted" if has_conflict else "system_assembled"

    packet = {
        "lead_id": lead_id,
        "packet_state": packet_state,
        "packet_version": (existing or {}).get("packet_version", 1),
        "schema_version": PACKET_SCHEMA_VERSION,
        "seller_profile": seller_profile,
        "property_profile": property_profile,
        "strategy_context": strategy_context,
        "negotiation_context": negotiation_context,
        "simulation_intelligence": bob_packet.get("simulation_intelligence", {}),
        "compliance_context": compliance_context,
        "action_permissions": action_permissions,
        "source_map": source_map,
        "conflict_flags": conflict_flags,
        "safe_for_live_call": bob_packet.get("safe_for_live_call", True),
        "assembled_at": now,
    }

    try:
        save_intel_packet(packet)
        if conflict_flags:
            write_packet_event(
                lead_id=lead_id,
                call_sid="",
                event_type="conflict_detected",
                after_state={"conflict_flags": conflict_flags},
                triggered_by="assembler",
            )
    except Exception as e:
        logger.warning("intel_assembler save failed lead_id={} error={}", lead_id, str(e))

    logger.info("intel_assembler assembled lead_id={} state={} conflicts={}", lead_id, packet_state, len(conflict_flags))
    return packet
