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


INTEL_PROMPT = """You are analyzing a real estate sales call transcript to extract intelligence for future calls.

Be precise. Use only information actually stated in the transcript. Null for anything not mentioned.

Return ONLY a valid JSON object with these exact keys:

motivation_level: integer 1-10 (1=completely unmotivated, 10=must sell immediately)
price_floor: integer dollars (minimum price they indicated they need, null if never mentioned)
timeline_urgency: one of "immediate" "weeks" "months" "unknown"
hot_topics: array of strings (topics that caused real engagement: "roof" "divorce" "retirement" "taxes" "probate" "relocation" "financial_stress" etc.)
rapport_openers: array of strings (what made them open up positively: "local knowledge" "humor" "market data" "empathy" "no pressure" etc.)
competitor_mentions: array of strings (other buyers or companies they named)
next_best_action: string (specific concrete recommendation for the next call — not generic)
call_summary: string (2 sentences max — what happened and where things stand right now)

TRANSCRIPT:
"""


def analyze_transcript(transcript: str, lead_id: str, call_sid: str) -> dict:
    logger.info("transcript_intel call_sid={} lead_id={}", call_sid, lead_id)

    if not transcript or len(transcript.strip()) < 50:
        logger.warning("transcript_intel too_short call_sid={}", call_sid)
        return {}

    try:
        client = _get_client()
        response = client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
            max_tokens=700,
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

        from backend.lib.db import update_lead_transcript_intel
        update_lead_transcript_intel(lead_id, intel)

        logger.info(
            "transcript_intel done lead_id={} motivation={} timeline={}",
            lead_id,
            intel.get("motivation_level"),
            intel.get("timeline_urgency"),
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

    price_str = f"${price_floor:,}" if price_floor else "not mentioned"
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
