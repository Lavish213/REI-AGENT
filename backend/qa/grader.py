import os
import json
from datetime import datetime, timezone
from loguru import logger
from anthropic import Anthropic

from backend.lib.db import insert_call
from backend.alerts.sms import send_alert_to_owner


_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


GRADING_PROMPT = """
You are a quality assessor for Sophia Reyes, a 25 year old AI voice agent
for San Joaquin House Buyers. Sophia handles inbound calls from distressed
property owners and her goal is to qualify sellers and book walkthroughs.

Grade this call transcript on exactly these 6 metrics from 0 to 10:

1. QUALIFICATION (0-10)
   Did Sophia ask about seller motivation, timeline, property condition?
   Did she learn why they might sell and what their situation is?

2. OFFER_QUALITY (0-10)
   If appropriate, did Sophia give a verbal price range?
   Was it based on property data? Did she anchor correctly?
   If no offer was appropriate yet, score 7 as neutral.

3. OBJECTION_HANDLING (0-10)
   Did Sophia handle price objections, competitor mentions, hesitation well?
   Did she use empathy before pivoting? Did she stay calm under pressure?

4. APPOINTMENT_BOOKING (0-10)
   Did Sophia attempt to book a walkthrough when appropriate?
   Did she ask directly and handle scheduling objections?
   If seller was clearly not ready, score 7 as neutral.

5. TONE (0-10)
   Did Sophia sound like a real 25 year old woman from Stockton?
   Did she use natural California speech (like, yeah, totally)?
   Did she react before responding? Did she slow down for emotional moments?
   Did she avoid corporate language? Did she sound human not robotic?

6. GOAL_COMPLETION (0-10)
   Did the call achieve its purpose?
   Either: appointment booked, offer discussed, or clear next step set.

Also identify:
- FAILURES: List specific moments the call failed (be very specific)
- PROMPT_SUGGESTIONS: Specific changes to Sophia's prompt that would fix failures
- CALL_SUMMARY: One sentence summary of what happened
- OVERALL_SCORE: Exact average of all 6 metrics rounded to 1 decimal

Return ONLY a valid JSON object with these exact keys:
qualification, offer_quality, objection_handling, appointment_booking,
tone, goal_completion, failures, prompt_suggestions, call_summary, overall_score

No preamble. No explanation. Only the JSON object.

TRANSCRIPT:
"""


def grade_call(transcript: str, lead_id: str, call_sid: str) -> dict:
    logger.info("grade_call call_sid={} lead_id={}", call_sid, lead_id)

    if not transcript or len(transcript.strip()) < 50:
        logger.warning("grade_call transcript too short call_sid={}", call_sid)
        return {}

    try:
        client = _get_client()
        response = client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": GRADING_PROMPT + transcript,
            }],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        scores = json.loads(raw)

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
        }

        from backend.lib.db import _get_client as get_db
        db = get_db()
        db.table("calls").update(call_update).eq(
            "signalwire_call_id", call_sid
        ).execute()

        overall = scores.get("overall_score", 10)
        if overall < 6.0:
            failures = scores.get("failures", [])
            failure_preview = " | ".join(failures[:2]) if failures else "see dashboard"
            alert = (
                f"LOW QA CALL\n"
                f"Score: {overall}/10\n"
                f"Issues: {failure_preview}\n"
                f"Call: {call_sid}"
            )
            send_alert_to_owner(alert)
            logger.warning("low QA score={} call_sid={}", overall, call_sid)

        logger.info(
            "grade_call complete call_sid={} overall={}",
            call_sid,
            overall,
        )
        return scores

    except json.JSONDecodeError as e:
        logger.error("grade_call JSON parse failed call_sid={} error={}", call_sid, str(e))
        return {}
    except Exception as e:
        logger.error("grade_call failed call_sid={} error={}", call_sid, str(e))
        return {}
