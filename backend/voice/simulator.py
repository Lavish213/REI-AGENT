import os
import asyncio
import random
from datetime import datetime, timezone
from loguru import logger
from anthropic import Anthropic

from backend.qa.grader import grade_call


_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
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
    prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")
    parts = []
    for filename in ["sophia_system.md", "sophia_scenarios.md", "sophia_scripts.md"]:
        filepath = os.path.join(prompts_dir, filename)
        if os.path.exists(filepath):
            with open(filepath) as f:
                parts.append(f.read().strip())

    base = "\n\n---\n\n".join(parts)

    arv = f"${prop.get('estimated_arv', 0) / 100:,.0f}"
    mao = f"${prop.get('mao', 0) / 100:,.0f}"

    context = f"""
CALLER PROPERTY CONTEXT
Address: {prop.get('address')} {prop.get('city')} {prop.get('zip')}
Beds/Baths: {prop.get('beds')}/{prop.get('baths')}
Sqft: {prop.get('sqft')}
Year Built: {prop.get('year_built')}
Distress: {prop.get('distress_type', '').replace('_', ' ').title()}
Equity: {prop.get('equity_pct')}%
Estimated ARV: {arv}
Your Max Offer MAO: {mao}
Anchor above MAO. Never reveal MAO directly.
""".strip()

    return f"{base}\n\n---\n\n{context}"


async def run_simulation(
    profile: dict | None = None,
    prop: dict | None = None,
    max_turns: int = 12,
    save_to_db: bool = True,
) -> dict:
    profile = profile or random.choice(SELLER_PROFILES)
    prop = prop or SAMPLE_PROPERTY

    logger.info("simulation starting seller={} motivation={}", profile["name"], profile["motivation"])

    client = _get_client()
    seller_messages = []
    sophia_messages = []
    full_transcript = []

    sophia_system = _build_sophia_prompt(prop)
    seller_system = _build_seller_prompt(profile, prop)

    sophia_messages.append({
        "role": "assistant",
        "content": "San Joaquin House Buyers, this is Sophia!",
    })
    full_transcript.append("SOPHIA: San Joaquin House Buyers, this is Sophia!")

    seller_messages.append({
        "role": "user",
        "content": "San Joaquin House Buyers, this is Sophia!",
    })

    for turn in range(max_turns):
        seller_response = client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=150,
            system=seller_system,
            messages=seller_messages,
        )
        seller_text = seller_response.content[0].text.strip()
        full_transcript.append(f"SELLER: {seller_text}")
        logger.debug("turn={} SELLER: {}", turn, seller_text)

        sophia_messages.append({"role": "user", "content": seller_text})
        seller_messages.append({"role": "assistant", "content": seller_text})

        sophia_response = client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=200,
            system=sophia_system,
            messages=sophia_messages,
        )
        sophia_text = sophia_response.content[0].text.strip()
        full_transcript.append(f"SOPHIA: {sophia_text}")
        logger.debug("turn={} SOPHIA: {}", turn, sophia_text)

        sophia_messages.append({"role": "assistant", "content": sophia_text})
        seller_messages.append({"role": "user", "content": sophia_text})

        end_signals = [
            "see you then", "talk soon", "have a good", "thanks for calling",
            "we'll be there", "look forward", "confirmed", "appointment"
        ]
        if any(signal in sophia_text.lower() for signal in end_signals):
            logger.info("simulation ending early — appointment booked turn={}", turn)
            break

        not_interested = ["not interested", "stop calling", "take me off", "don't call"]
        if any(signal in seller_text.lower() for signal in not_interested):
            logger.info("simulation ending early — seller not interested turn={}", turn)
            break

    transcript_str = "\n".join(full_transcript)

    scores = {}
    try:
        scores = grade_call(
            transcript=transcript_str,
            lead_id="simulation",
            call_sid=f"sim_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        )
    except Exception as e:
        logger.error("simulation grading failed error={}", str(e))

    result = {
        "seller_profile": profile["name"],
        "motivation": profile["motivation"],
        "turns": len(full_transcript) // 2,
        "transcript": transcript_str,
        "scores": scores,
        "overall_score": scores.get("overall_score", 0),
        "appointment_booked": any(
            "see you" in line.lower() or "confirmed" in line.lower()
            for line in full_transcript
            if line.startswith("SOPHIA:")
        ),
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
        print(f"\n{r['seller_profile']} — Score: {r['overall_score']}/10 — Booked: {r['appointment_booked']}")
        print(f"Turns: {r['turns']}")
