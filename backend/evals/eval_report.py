from datetime import datetime, timezone
from loguru import logger


def generate_report(eval_summary: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = eval_summary.get("total", 0)
    passed = eval_summary.get("passed", 0)
    failed = eval_summary.get("failed", 0)
    pass_rate = eval_summary.get("pass_rate", 0)
    avg_score = eval_summary.get("avg_score", 0)
    results = eval_summary.get("results", [])

    lines = [
        f"SOPHIA EVAL REPORT — {now}",
        f"{'=' * 50}",
        f"Total Cases:  {total}",
        f"Passed:       {passed}",
        f"Failed:       {failed}",
        f"Pass Rate:    {pass_rate}%",
        f"Avg Score:    {avg_score}/10",
        f"",
        f"{'=' * 50}",
        f"FAILED CASES:",
        f"{'=' * 50}",
    ]

    failed_cases = [r for r in results if not r.get("passed")]
    if not failed_cases:
        lines.append("All cases passed!")
    else:
        for case in failed_cases:
            lines.append(f"")
            lines.append(f"CASE: {case['case_name']} (score: {case.get('score')}/10)")
            lines.append(f"Category: {case['category']}")
            lines.append(f"Seller said: \"{case['seller_trigger']}\"")
            lines.append(f"Sophia said: \"{case['sophia_response'][:150]}...\"")
            lines.append(f"Feedback: {case.get('feedback', 'none')}")
            failures = case.get("failure_criteria_hit", [])
            if failures:
                lines.append(f"Failures hit: {', '.join(failures)}")

    lines.extend([
        f"",
        f"{'=' * 50}",
        f"PROMPT IMPROVEMENT SUGGESTIONS:",
        f"{'=' * 50}",
    ])

    all_feedback = [r.get("feedback", "") for r in failed_cases if r.get("feedback")]
    if all_feedback:
        for i, fb in enumerate(all_feedback, 1):
            lines.append(f"{i}. {fb}")
    else:
        lines.append("No improvements needed — all cases passed.")

    report = "\n".join(lines)
    logger.info("eval report generated total={} passed={}", total, passed)
    return report


def send_report_to_owner(eval_summary: dict) -> None:
    report = generate_report(eval_summary)
    pass_rate = eval_summary.get("pass_rate", 0)
    avg_score = eval_summary.get("avg_score", 0)

    short_alert = (
        f"EVAL RESULTS\n"
        f"Pass Rate: {pass_rate}%\n"
        f"Avg Score: {avg_score}/10\n"
        f"Failed: {eval_summary.get('failed', 0)}/{eval_summary.get('total', 0)}\n"
        f"See dashboard for full report."
    )

    try:
        from backend.alerts.sms import send_alert_to_owner
        send_alert_to_owner(short_alert)
    except Exception as e:
        logger.error("eval report SMS failed error={}", str(e))
