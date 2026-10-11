import os
import asyncio
import random
from datetime import datetime, timezone
from loguru import logger
from anthropic import AsyncAnthropic

from backend.qa.grader import grade_call


_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


SELLER_PROFILES = [
    {
        "name": "Robert Martinez",
        "age": 67,
        "situation": "retired, behind on property taxes for 2 years, wants out",
        "motivation": "high",
        "emotional_state": "stressed but hopeful",
        "objection_style": "price focused",
        "magic_number": 185000,
    },
    {
        "name": "Sandra Johnson",
        "age": 52,
        "situation": "going through divorce, needs to sell fast, joint ownership",
        "motivation": "very high",
        "emotional_state": "emotional and urgent",
        "objection_style": "timeline focused",
        "magic_number": 210000,
    },
    {
        "name": "Mike Chen",
        "age": 45,
        "situation": "absentee landlord, tenants left, property needs work",
        "motivation": "medium",
        "emotional_state": "skeptical and analytical",
        "objection_style": "skeptical of cash buyers",
        "magic_number": 230000,
    },
    {
        "name": "Gloria Reyes",
        "age": 72,
        "situation": "inherited property from deceased husband, overwhelmed",
        "motivation": "medium",
        "emotional_state": "grieving and confused",
        "objection_style": "needs time and reassurance",
        "magic_number": 195000,
    },
    {
        "name": "Tony Williams",
        "age": 38,
        "situation": "pre-foreclosure, lost job 6 months ago, auction in 45 days",
        "motivation": "very high",
        "emotional_state": "desperate but proud",
        "objection_style": "price and ego",
        "magic_number": 175000,
    },
]

SAMPLE_PROPERTY = {
    "address": "1847 E Hammer Ln",
    "city": "Stockton",
    "zip": "95210",
    "beds": 3,
    "baths": 2,
    "sqft": 1450,
    "year_built": 1978,
    "distress_type": "pre_foreclosure",
    "equity_pct": 45,
    "estimated_arv": 31200000,
    "mao": 19340000,
    "arv_confidence": "medium",
}


def _build_seller_prompt(profile: dict, prop: dict) -> str:
    return f"""
You are {profile['name']}, a {profile['age']} year old homeowner in Stockton California.
Your situation: {profile['situation']}
Your motivation to sell: {profile['motivation']}
Your emotional state: {profile['emotional_state']}
Your objection style: {profile['objection_style']}
The minimum price you would accept: ${profile['magic_number']:,}

Your property:
Address: {prop.get('address')} {prop.get('city')}
Beds/Baths: {prop.get('beds')}/{prop.get('baths')}
Sqft: {prop.get('sqft')}

You are receiving a call from Sophia at San Joaquin House Buyers.
Respond realistically as this person. Be natural, not scripted.
Use short responses like a real phone call.
React emotionally based on your emotional state.
Push back on price if Sophia offers below your magic number.
If Sophia builds enough rapport and explains the value, you can warm up.
Never make it too easy — make Sophia work for the appointment.
Keep responses under 3 sentences like a real phone call.
""".strip()


def _build_sophia_prompt(prop: dict) -> str:
    from backend.voice.agent import _load_system_prompt
    context = f"SIMULATION: Property {prop.get('address', 'unknown')}, {prop.get('city', '')}. No real bookings or messages can be sent in this text simulation."
    return _load_system_prompt({"property_context_str": context})


async def run_simulation(
    profile: dict | None = None,
    prop: dict | None = None,
    max_turns: int = 12,
    save_to_db: bool = False,
    duration_seconds: int = 60,
    client=None,
    grade: bool = True,
) -> dict:
    profile = profile or random.choice(SELLER_PROFILES)
    prop = prop or SAMPLE_PROPERTY

    logger.info("simulation starting seller={} motivation={}", profile["name"], profile["motivation"])

    from backend.voice.agent import _build_opener, _DEFAULT_LLM_MODEL
    from backend.voice.conversation_policy import plan_turn, remember_assistant_turn
    from backend.voice.emotional_state_engine import EmotionalStateEngine
    from backend.voice.objective_engine import ObjectiveEngine
    from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor
    from backend.voice.resistance_tracker import ResistanceTracker

    if not 1 <= max_turns <= 100 or not 10 <= duration_seconds <= 600:
        raise ValueError("Invalid simulation limits")
    client = client if client is not None else _get_client()
    ctx = CallContext(is_outbound=True, awaiting_owner_confirmation=True)
    tracker = ContextTrackerProcessor(ctx)
    emotions = EmotionalStateEngine(ctx)
    resistance = ResistanceTracker(ctx)
    seller_messages = []
    sophia_messages = []
    full_transcript = []
    turn_plans = []
    turns = 0
    model = os.environ.get("VOICE_LLM_MODEL", _DEFAULT_LLM_MODEL)
    sophia_system = _build_sophia_prompt(prop)
    seller_system = _build_seller_prompt(profile, prop)
    opener = _build_opener({"is_outbound": True, "owner_first_name": profile["name"].split()[0]})
    remember_assistant_turn(ctx, opener)
    sophia_messages.append({"role": "assistant", "content": opener})
    full_transcript.append("SOPHIA: " + opener)
    seller_messages.append({"role": "user", "content": opener})
    estimated_seconds = len(opener.split()) / 2.5
    end_reason = "turn_limit"
    while turns < max_turns and estimated_seconds < duration_seconds:
        seller_response = await asyncio.wait_for(client.messages.create(
            model=model, max_tokens=150, system=seller_system, messages=seller_messages,
        ), timeout=30)
        seller_text = seller_response.content[0].text.strip()
        full_transcript.append(f"SELLER: {seller_text}")
        estimated_seconds += len(seller_text.split()) / 2.5 + 1
        sophia_messages.append({"role": "user", "content": seller_text})
        seller_messages.append({"role": "assistant", "content": seller_text})
        ctx.runtime_instruction = None
        ctx.turn_count += 1
        normalized = seller_text.replace("’", "'")
        emotions._update_emotional_state(normalized)
        resistance._update_resistance(normalized)
        tracker._analyze(normalized)
        ctx.objective = ObjectiveEngine().decide(ctx)
        plan = plan_turn(ctx, seller_text)
        ctx.response_guidance = plan.render()
        turn_plans.append({"goal": plan.goal, "question_limit": plan.question_limit})
        sophia_response = await asyncio.wait_for(client.messages.create(
            model=model, max_tokens=120,
            system=sophia_system + "\n" + ctx.build_context_prefix(),
            messages=sophia_messages,
        ), timeout=30)
        sophia_text = sophia_response.content[0].text.strip()
        full_transcript.append(f"SOPHIA: {sophia_text}")
        estimated_seconds += len(sophia_text.split()) / 2.5 + 1
        turns += 1
        remember_assistant_turn(ctx, sophia_text)
        sophia_messages.append({"role": "assistant", "content": sophia_text})
        seller_messages.append({"role": "user", "content": sophia_text})
        if plan.goal in {"stop", "decline", "wrong_person", "goodbye"}:
            end_reason = plan.goal
            break
    else:
        if estimated_seconds >= duration_seconds:
            end_reason = "estimated_duration_limit"

    transcript_str = "\n".join(full_transcript)

    scores = {}
    try:
        if grade:
            scores = await grade_call(
                transcript=transcript_str,
                lead_id="simulation",
                call_sid=f"sim_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                persist=False,
            )
    except Exception as e:
        logger.error("simulation grading failed error={}", str(e))

    result = {
        "seller_profile": profile["name"],
        "motivation": profile["motivation"],
        "turns": turns,
        "requested_window_seconds": duration_seconds,
        "estimated_speech_seconds": round(estimated_seconds, 1),
        "duration_method": "text_word_count_at_150_words_per_minute_plus_turn_gaps",
        "end_reason": end_reason,
        "model": model,
        "turn_plans": turn_plans,
        "audio_tested": False,
        "tool_execution_tested": False,
        "persisted": False,
        "transcript": transcript_str,
        "scores": scores,
        "overall_score": scores.get("overall_score", 0),
        "appointment_booked": False,
    }

    logger.info(
        "simulation complete seller={} turns={} score={} booked={}",
        profile["name"],
        result["turns"],
        result["overall_score"],
        result["appointment_booked"],
    )
    return result


async def run_batch_simulations(count: int = 5) -> list[dict]:
    logger.info("batch simulation starting count={}", count)
    results = []
    for i in range(count):
        profile = SELLER_PROFILES[i % len(SELLER_PROFILES)]
        result = await run_simulation(profile=profile)
        results.append(result)
        await asyncio.sleep(1)

    passed = sum(1 for r in results if r["overall_score"] >= 7.0)
    booked = sum(1 for r in results if r["appointment_booked"])

    logger.info(
        "batch complete total={} passed={} booked={}",
        len(results),
        passed,
        booked,
    )
    return results


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    load_dotenv()
    results = asyncio.run(run_batch_simulations(count=3))
    for r in results:
        logger.info("seller={} score={} turns={} booked={}", r["seller_profile"], r["overall_score"], r["turns"], r["appointment_booked"])
