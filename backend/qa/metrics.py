from loguru import logger
from backend.lib.db import _get_client


def get_agent_performance_summary(days: int = 7) -> dict:
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    db = _get_client()
    response = (
        db.table("calls")
        .select(
            "score_qualification, score_offer_quality, score_objection_handling,"
            "score_appointment_booking, score_tone, score_goal_completion, score_overall"
        )
        .gte("created_at", cutoff)
        .not_.is_("score_overall", "null")
        .execute()
    )

    calls = response.data
    if not calls:
        logger.warning("get_agent_performance_summary no graded calls in last {} days", days)
        return {}

    def avg(key: str) -> float:
        vals = [c[key] for c in calls if c.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    summary = {
        "total_calls": len(calls),
        "avg_qualification": avg("score_qualification"),
        "avg_offer_quality": avg("score_offer_quality"),
        "avg_objection_handling": avg("score_objection_handling"),
        "avg_appointment_booking": avg("score_appointment_booking"),
        "avg_tone": avg("score_tone"),
        "avg_goal_completion": avg("score_goal_completion"),
        "avg_overall": avg("score_overall"),
        "period_days": days,
    }

    logger.info(
        "agent performance summary days={} calls={} avg_overall={}",
        days,
        len(calls),
        summary["avg_overall"],
    )
    return summary


def get_qa_trend(weeks: int = 4) -> list[dict]:
    from datetime import datetime, timezone, timedelta
    db = _get_client()
    trend = []

    for i in range(weeks):
        week_end = datetime.now(timezone.utc) - timedelta(weeks=i)
        week_start = week_end - timedelta(weeks=1)

        response = (
            db.table("calls")
            .select("score_overall")
            .gte("created_at", week_start.isoformat())
            .lte("created_at", week_end.isoformat())
            .not_.is_("score_overall", "null")
            .execute()
        )

        scores = [c["score_overall"] for c in response.data if c.get("score_overall")]
        avg = round(sum(scores) / len(scores), 2) if scores else None

        trend.append({
            "week": f"Week -{i}",
            "week_start": week_start.date().isoformat(),
            "avg_score": avg,
            "call_count": len(scores),
        })

    trend.reverse()
    logger.info("get_qa_trend weeks={}", weeks)
    return trend
