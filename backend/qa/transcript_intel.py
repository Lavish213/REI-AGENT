import os
import json
from loguru import logger
from anthropic import Anthropic


_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


INTEL_PROMPT = """You are analyzing a real estate sales call transcript to extract structured intelligence.

Be precise. Use only information actually stated in the transcript. Use null for anything not mentioned.

Return ONLY a valid JSON object with these exact keys:

motivation_level: integer 1-10 (1=completely unmotivated, 10=must sell immediately)
seller_motivation: string describing WHY they want to sell (null if not mentioned)
motivation_confidence: float 0.0-1.0 (confidence in motivation assessment)
price_floor: integer cents (minimum price they indicated they need, null if never mentioned)
asking_price: integer cents (price they asked for or said they want, null if not mentioned)
timeline: string (what they said about timeline in their own words, null if not mentioned)
timeline_urgency: one of "immediate" "weeks" "months" "unknown"
property_condition: one of "excellent" "good" "fair" "poor" "unknown"
occupancy: one of "owner_occupied" "tenant_occupied" "vacant" "unknown"
hot_topics: array of strings (topics causing real engagement: "roof" "divorce" "retirement" "taxes" "probate" "relocation" "financial_stress" etc.)
rapport_openers: array of strings (what made them open up: "local knowledge" "humor" "market data" "empathy" "no pressure" etc.)
competitor_mentions: array of strings (other buyers or companies named)
distress_indicators: array of strings (specific distress signals: "behind on mortgage" "facing foreclosure" "divorce" "probate" "relocation" etc.)
objections: array of strings (objections raised: "price too low" "need more time" "not ready" "talking to others" etc.)
appointment_interest: boolean (true if seller showed any interest in a walkthrough)
seller_name: string (first name if mentioned, null otherwise)
property_address: string (address mentioned in call, null if not mentioned)
next_step: string (what should happen next based on the conversation outcome)
next_best_action: string (specific concrete recommendation for the next call — not generic)
followup_priority: one of "high" "medium" "low"
lead_score: float 1.0-10.0 (overall lead quality based on this conversation)
extraction_confidence: float 0.0-1.0 (confidence in overall extraction accuracy)
call_summary: string (2 sentences max — what happened and where things stand)

TRANSCRIPT:
"""


def _compute_lead_scores(intel: dict) -> dict:
    motivation = intel.get("motivation_level") or 0
    timeline = intel.get("timeline_urgency", "unknown")
    appt = intel.get("appointment_interest") or False

    urgency = motivation
    if timeline == "immediate":
        urgency = min(urgency + 3, 10)
    elif timeline == "weeks":
        urgency = min(urgency + 1, 10)
    if appt:
        urgency = min(urgency + 2, 10)

    is_hot = (
        motivation >= 8
        or (appt and motivation >= 6)
        or timeline == "immediate"
    )

    return {
        "followup_urgency": round(urgency),
        "is_hot_lead": is_hot,
    }


def analyze_transcript(
    transcript: str,
    lead_id: str,
    call_sid: str,
    call_id_db: str | None = None,
) -> dict:
    logger.info("transcript_intel call_sid={} lead_id={}", call_sid, lead_id)

    if not transcript or len(transcript.strip()) < 50:
        logger.warning("transcript_intel too_short call_sid={}", call_sid)
        return {}

    try:
        client = _get_client()
        response = client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": INTEL_PROMPT + transcript,
            }],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        intel = json.loads(raw)

        from backend.lib.db import update_lead_transcript_intel, update_call_intel
        update_lead_transcript_intel(lead_id, intel)

        if call_id_db:
            update_call_intel(call_id_db, intel)

        derived = _compute_lead_scores(intel)
        from backend.lib.db import update_lead_intel_scores
        update_lead_intel_scores(lead_id, derived)

        if call_id_db:
            from backend.voice.events import emit_intel_events
            emit_intel_events(call_id_db, lead_id, intel)

        logger.info(
            "transcript_intel done lead_id={} motivation={} timeline={} hot={}",
            lead_id,
            intel.get("motivation_level"),
            intel.get("timeline_urgency"),
            derived.get("is_hot_lead"),
        )
        return intel

    except json.JSONDecodeError as e:
        logger.error("transcript_intel json_failed call_sid={} error={}", call_sid, str(e))
        return {}
    except Exception as e:
        logger.error("transcript_intel failed call_sid={} error={}", call_sid, str(e))
        return {}


def build_prior_call_context(lead: dict) -> str | None:
    summary = lead.get("call_summary")
    if not summary:
        return None

    price_floor = lead.get("price_floor")
    hot_topics = lead.get("hot_topics") or []
    rapport = lead.get("rapport_openers") or []
    timeline = lead.get("timeline_urgency") or "unknown"
    motivation = lead.get("motivation_level")
    next_action = lead.get("next_best_action")

    price_str = f"${price_floor // 100:,}" if price_floor else "not mentioned"
    topics_str = ", ".join(hot_topics) if hot_topics else "none noted"
    rapport_str = ", ".join(rapport) if rapport else "none noted"
    motivation_str = f"{motivation}/10" if motivation else "unknown"

    lines = [
        "PREVIOUS CALL CONTEXT:",
        summary,
        f"Price floor mentioned: {price_str}",
        f"Timeline: {timeline}",
        f"Motivation level: {motivation_str}",
        f"Hot topics: {topics_str}",
        f"Rapport openers: {rapport_str}",
    ]
    if next_action:
        lines.append(f"Recommended next action: {next_action}")
    lines.append("Use this naturally. Do not reference it directly.")

    return "\n".join(lines)
