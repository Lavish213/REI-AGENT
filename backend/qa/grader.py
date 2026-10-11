import os
import math
import asyncio
from loguru import logger
from anthropic import AsyncAnthropic

from backend.alerts.sms import send_alert_to_owner


_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


GRADING_PROMPT = """
You assess Sophia, an AI voice assistant for San Joaquin House Buyers.
Evaluate only evidence in this transcript. Grade each tool metric from 0 to 10.
Qualification measures ownership, property condition, motivation, timeline and price discovery.
Offer quality measures verified, appropriately qualified price discussion without invented authority.
Objection handling measures listening and direct answers without pressure.
Appointment booking measures an explicit agreed date/time and truthful confirmation; proposing a visit is not booking.
Tone measures warm, concise, responsive language without repetitive filler or false personal claims.
Goal completion measures progress toward the seller's stated goal, including honoring stop requests.
Use null for offer quality, objection handling or appointment booking when there was no relevant opportunity.
Do not infer audible naturalness, latency or interruption quality from text alone.

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
                    "qualification": {"type": "number", "minimum": 0, "maximum": 10},
                    "offer_quality": {"type": ["number", "null"], "minimum": 0, "maximum": 10},
                    "objection_handling": {"type": ["number", "null"], "minimum": 0, "maximum": 10},
                    "appointment_booking": {"type": ["number", "null"], "minimum": 0, "maximum": 10},
                    "tone": {"type": "number", "minimum": 0, "maximum": 10},
                    "goal_completion": {"type": "number", "minimum": 0, "maximum": 10},
                    "call_summary": {"type": "string"},
                    "failures": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["qualification", "offer_quality", "objection_handling", "appointment_booking", "tone", "goal_completion", "call_summary", "failures"],
                "additionalProperties": False,
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

        required = ("qualification", "offer_quality", "objection_handling", "appointment_booking", "tone", "goal_completion")
        nullable = {"offer_quality", "objection_handling", "appointment_booking"}
        for name in required:
            value = scores.get(name)
            if value is None and name in nullable and name in scores:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10:
                raise ValueError(f"Invalid QA score: {name}")
        if not isinstance(scores.get("call_summary"), str) or not isinstance(scores.get("failures"), list) or not all(isinstance(item, str) for item in scores["failures"]):
            raise ValueError("Invalid QA evidence")
        values = [scores[name] for name in required if scores[name] is not None]
        overall = round(sum(values) / len(values), 2)
        scores["overall_score"] = overall
        call_update = {
            "score_qualification": scores["qualification"],
            "score_offer_quality": scores["offer_quality"],
            "score_objection_handling": scores["objection_handling"],
            "score_appointment_booking": scores["appointment_booking"],
            "score_overall": overall,
            "summary": scores["call_summary"],
        }
        from backend.lib.db import save_call_grade
        await asyncio.to_thread(save_call_grade, call_sid, call_update)

        if overall < 6.0:
            failures = scores.get("failures", [])
            failure_preview = " | ".join(failures[:2]) if failures else "see dashboard"
            alert = f"LOW QA CALL\nScore: {overall}/10\nIssues: {failure_preview}\nCall: {call_sid}"
            await asyncio.to_thread(send_alert_to_owner, alert)
            logger.warning("low QA score={} call_sid={}", overall, call_sid)

        logger.info("grade_call complete call_sid={} overall={}", call_sid, overall)
        return scores

    except Exception as e:
        logger.error("grade_call failed call_sid={} error={}", call_sid, str(e))
        return {}
