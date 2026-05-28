import os
import json
from datetime import datetime, timezone
from loguru import logger
from anthropic import AsyncAnthropic

from backend.lib.db import insert_call
from backend.alerts.sms import send_alert_to_owner


_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


GRADING_PROMPT = """
You are a quality assessor for Sophia Reyes, a 25 year old AI voice agent
for San Joaquin House Buyers. Sophia handles inbound and outbound calls from
distressed property owners. Her goal is to qualify sellers and book walkthroughs.

Grade this call transcript on exactly these 6 metrics from 0 to 10:

1. QUALIFICATION (0-10)
2. OFFER_QUALITY (0-10)
3. OBJECTION_HANDLING (0-10)
4. APPOINTMENT_BOOKING (0-10)
5. TONE (0-10)
6. GOAL_COMPLETION (0-10)

Also: opener_completed, reached_discovery, reached_qualification, reached_pitch,
appointment_offered, appointment_booked, objections_count, objections_handled_count,
talk_ratio_sophia, phase_reached, sentiment_arc, failures, prompt_suggestions,
call_summary, overall_score.

TRANSCRIPT:
"""


async def grade_call(transcript: str, lead_id: str, call_sid: str) -> dict:
    logger.info("grade_call call_sid={} lead_id={}", call_sid, lead_id)

    if not transcript or len(transcript.strip()) < 50:
        logger.warning("grade_call transcript too short call_sid={}", call_sid)
        return {}

    try:
        client = _get_client()

        grade_tool = {
            "name": "submit_grades",
            "description": "Submit the QA grades for this call",
            "input_schema": {
                "type": "object",
                "properties": {
                    "qualification": {"type": "number"},
                    "offer_quality": {"type": "number"},
                    "objection_handling": {"type": "number"},
                    "appointment_booking": {"type": "number"},
                    "tone": {"type": "number"},
                    "goal_completion": {"type": "number"},
                    "opener_completed": {"type": "boolean"},
                    "reached_discovery": {"type": "boolean"},
                    "reached_qualification": {"type": "boolean"},
                    "reached_pitch": {"type": "boolean"},
                    "appointment_offered": {"type": "boolean"},
                    "appointment_booked": {"type": "boolean"},
                    "objections_count": {"type": "integer"},
                    "objections_handled_count": {"type": "integer"},
                    "talk_ratio_sophia": {"type": "number"},
                    "phase_reached": {"type": "string"},
                    "sentiment_arc": {"type": "string"},
                    "failures": {"type": "array", "items": {"type": "string"}},
                    "prompt_suggestions": {"type": "array", "items": {"type": "string"}},
                    "call_summary": {"type": "string"},
                    "overall_score": {"type": "number"},
                },
                "required": ["qualification", "offer_quality", "objection_handling",
                             "appointment_booking", "tone", "goal_completion",
                             "call_summary", "overall_score"],
            },
        }

        response = await client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
            max_tokens=1000,
            tools=[grade_tool],
            tool_choice={"type": "tool", "name": "submit_grades"},
            messages=[{"role": "user", "content": GRADING_PROMPT + transcript}],
        )

        scores = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_grades":
                scores = block.input
                break

        if not scores:
            logger.error("grade_call no tool_use block returned call_sid={}", call_sid)
            return {}

        call_update = {
            "score_qualification": scores.get("qualification"),
            "score_offer_quality": scores.get("offer_quality"),
            "score_objection_handling": scores.get("objection_handling"),
            "score_appointment_booking": scores.get("appointment_booking"),
            "score_tone": scores.get("tone"),
            "score_goal_completion": scores.get("goal_completion"),
            "score_overall": scores.get("overall_score"),
            "failures": scores.get("failures", []),
            "prompt_suggestions": scores.get("prompt_suggestions", []),
            "summary": scores.get("call_summary", ""),
            "opener_completed": scores.get("opener_completed"),
            "reached_discovery": scores.get("reached_discovery"),
            "reached_qualification": scores.get("reached_qualification"),
            "reached_pitch": scores.get("reached_pitch"),
            "appointment_offered": scores.get("appointment_offered"),
            "appointment_booked": scores.get("appointment_booked"),
            "objections_count": scores.get("objections_count"),
            "objections_handled": scores.get("objections_handled_count"),
            "talk_ratio_sophia": scores.get("talk_ratio_sophia"),
            "phase_reached": scores.get("phase_reached"),
            "sentiment_arc": scores.get("sentiment_arc"),
        }

        from backend.lib.db import _get_client as get_db
        db = get_db()
        db.table("calls").update(call_update).eq("signalwire_call_id", call_sid).execute()

        overall = scores.get("overall_score", 10)
        if overall < 6.0:
            failures = scores.get("failures", [])
            failure_preview = " | ".join(failures[:2]) if failures else "see dashboard"
            alert = f"LOW QA CALL\nScore: {overall}/10\nIssues: {failure_preview}\nCall: {call_sid}"
            send_alert_to_owner(alert)
            logger.warning("low QA score={} call_sid={}", overall, call_sid)

        logger.info("grade_call complete call_sid={} overall={}", call_sid, overall)
        return scores

    except Exception as e:
        logger.error("grade_call failed call_sid={} error={}", call_sid, str(e))
        return {}
