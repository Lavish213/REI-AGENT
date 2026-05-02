import os
import asyncio
from datetime import datetime, timezone
from loguru import logger
from anthropic import Anthropic

from backend.evals.eval_cases import get_all_cases, get_cases_by_category


_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _load_sophia_prompt() -> str:
    prompts_dir = os.path.join(os.path.dirname(__file__), "..", "voice", "prompts")
    parts = []
    for filename in ["sophia_system.md", "sophia_scenarios.md", "sophia_scripts.md"]:
        filepath = os.path.join(prompts_dir, filename)
        if os.path.exists(filepath):
            with open(filepath) as f:
                parts.append(f.read().strip())
    return "\n\n---\n\n".join(parts)


def _build_eval_prompt(case: dict) -> str:
    sophia_prompt = _load_sophia_prompt()
    success_criteria = "\n".join(f"- {c}" for c in case["success_criteria"])
    failure_criteria = "\n".join(f"- {c}" for c in case["failure_criteria"])

    return f"""
{sophia_prompt}

---

EVAL CONTEXT:
You are being tested on this specific scenario: {case['description']}
The seller will say: "{case['seller_trigger']}"

Respond as Sophia would respond to that exact seller statement.
Be natural. Be in character. Use California speech patterns.
Keep response under 4 sentences.
""".strip()


def _grade_response(case: dict, sophia_response: str) -> dict:
    client = _get_client()

    success_criteria = "\n".join(f"- {c}" for c in case["success_criteria"])
    failure_criteria = "\n".join(f"- {c}" for c in case["failure_criteria"])

    grading_prompt = f"""
You are grading an AI voice agent named Sophia who handles real estate seller calls.

SCENARIO: {case['description']}
SELLER SAID: "{case['seller_trigger']}"
SOPHIA RESPONDED: "{sophia_response}"

SUCCESS CRITERIA (each one present = better score):
{success_criteria}

FAILURE CRITERIA (each one present = worse score):
{failure_criteria}

Grade Sophia's response from 0-10 where:
10 = all success criteria met, no failure criteria present
7-9 = most success criteria met, minor issues
4-6 = some success criteria met, some failure criteria present
0-3 = failed multiple success criteria or hit failure criteria

Return ONLY a JSON object with these keys:
score (int 0-10)
passed (boolean, true if score >= 7)
success_criteria_met (list of strings from success criteria that were met)
failure_criteria_hit (list of strings from failure criteria that were triggered)
feedback (one sentence on how to improve)

No preamble. JSON only.
"""

    try:
        response = client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=500,
            messages=[{"role": "user", "content": grading_prompt}],
        )
        import json
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        logger.error("eval grading failed case={} error={}", case["name"], str(e))
        return {
            "score": 0,
            "passed": False,
            "success_criteria_met": [],
            "failure_criteria_hit": [],
            "feedback": f"Grading error: {str(e)[:100]}",
        }


async def run_eval_case(case: dict) -> dict:
    client = _get_client()
    eval_prompt = _build_eval_prompt(case)

    try:
        response = client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=300,
            messages=[
                {"role": "user", "content": eval_prompt},
            ],
        )
        sophia_response = response.content[0].text.strip()
    except Exception as e:
        logger.error("eval response generation failed case={} error={}", case["name"], str(e))
        sophia_response = ""

    grade = _grade_response(case, sophia_response)

    result = {
        "case_name": case["name"],
        "category": case["category"],
        "description": case["description"],
        "seller_trigger": case["seller_trigger"],
        "sophia_response": sophia_response,
        **grade,
    }

    logger.info(
        "eval case={} score={} passed={}",
        case["name"],
        grade.get("score"),
        grade.get("passed"),
    )
    return result


async def run_all_evals(category: str = "") -> dict:
    cases = get_cases_by_category(category) if category else get_all_cases()
    logger.info("running evals count={} category={}", len(cases), category or "all")

    results = []
    for case in cases:
        result = await run_eval_case(case)
        results.append(result)
        await asyncio.sleep(0.5)

    passed = sum(1 for r in results if r.get("passed"))
    avg_score = sum(r.get("score", 0) for r in results) / len(results) if results else 0

    summary = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results) * 100, 1) if results else 0,
        "avg_score": round(avg_score, 2),
        "run_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }

    try:
        from backend.lib.db import _get_client as get_db
        db = get_db()
        db.table("eval_runs").insert({
            "total_cases": summary["total"],
            "passed": summary["passed"],
            "failed": summary["failed"],
            "pass_rate": summary["pass_rate"],
            "avg_score": summary["avg_score"],
            "created_at": summary["run_at"],
        }).execute()
    except Exception as e:
        logger.error("eval run save failed error={}", str(e))

    logger.info(
        "evals complete total={} passed={} avg={}",
        summary["total"],
        summary["passed"],
        summary["avg_score"],
    )
    return summary
