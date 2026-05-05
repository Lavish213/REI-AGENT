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
for San Joaquin House Buyers. Sophia handles inbound and outbound calls from
distressed property owners. Her goal is to qualify sellers and book walkthroughs.

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

Also determine these boolean and numeric fields:

opener_completed: true if caller stayed past ~15 seconds and opener finished
reached_discovery: true if Sophia asked open-ended questions about situation
reached_qualification: true if Sophia asked about mortgage, price expectation, or timeline
reached_pitch: true if Sophia gave a verbal offer or pitch
appointment_offered: true if Sophia explicitly asked for a walkthrough
appointment_booked: true if seller agreed to a walkthrough time
objections_count: integer count of distinct objections raised by seller
objections_handled_count: integer count of objections Sophia addressed well
talk_ratio_sophia: float 0.0-1.0 estimating fraction of words spoken by Sophia (0.35-0.45 is ideal)
phase_reached: string — furthest phase reached: PERMISSION, CURIOSITY_HOOK, DISCOVERY, QUALIFY, PITCH, or CLOSE
sentiment_arc: string describing how caller emotion changed across call, e.g. "skeptical→interested→warm" or "warm→frustrated" or "neutral throughout"

Also identify:
failures: list of specific moments the call failed (be very specific)
prompt_suggestions: list of specific changes to Sophia's prompt that would fix failures
call_summary: one sentence summary of what happened
overall_score: exact average of all 6 metrics rounded to 1 decimal

Return ONLY a valid JSON object with these exact keys:
qualification, offer_quality, objection_handling, appointment_booking,
tone, goal_completion, opener_completed, reached_discovery, reached_qualification,
reached_pitch, appointment_offered, appointment_booked, objections_count,
objections_handled_count, talk_ratio_sophia, phase_reached, sentiment_arc,
failures, prompt_suggestions, call_summary, overall_score

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
