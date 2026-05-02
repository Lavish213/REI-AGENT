import os
from datetime import datetime, timezone

from loguru import logger


DISTRESS_TYPE_WEIGHTS = {
    "notice_of_default": 30,
    "pre_foreclosure": 25,
    "tax_lien": 22,
    "code_violation": 12,
    "failed_listing": 10,
    "absentee_owner": 8,
    "vacant": 8,
    "free_and_clear": 5,
    "unknown": 0,
}


def _score_distress_type(distress_type: str) -> int:
    return DISTRESS_TYPE_WEIGHTS.get(distress_type, 0)


def _score_equity(equity_pct: float | None) -> int:
    if equity_pct is None:
        return 0
    if equity_pct >= 60:
        return 25
    if equity_pct >= 40:
        return 18
    if equity_pct >= 20:
        return 10
    if equity_pct >= 5:
        return 4
    return 0


def _score_auction_proximity(auction_date_str: str | None) -> int:
    if auction_date_str is None:
        return 0
    try:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
            try:
                auction_date = datetime.strptime(auction_date_str, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        else:
            return 0

        days_away = (auction_date - datetime.now(timezone.utc)).days

        if days_away < 0:
            return 0
        if days_away <= 14:
            return 30
        if days_away <= 30:
            return 25
        if days_away <= 60:
            return 18
        if days_away <= 90:
            return 10
        return 5
    except Exception:
        return 0


def _score_tax_delinquency(tax_delinquent_amount: int | None) -> int:
    if tax_delinquent_amount is None:
        return 0
    dollars = tax_delinquent_amount / 100
    if dollars >= 20000:
        return 15
    if dollars >= 10000:
        return 10
    if dollars >= 5000:
        return 7
    if dollars >= 1000:
        return 4
    return 2


def _score_stacked_signals(prop: dict) -> int:
    signals = 0
    if prop.get("distress_type") and prop["distress_type"] != "unknown":
        signals += 1
    if prop.get("tax_delinquent_amount") and prop["tax_delinquent_amount"] > 0:
        signals += 1
    if prop.get("nod_date"):
        signals += 1
    if prop.get("auction_date"):
        signals += 1
    if prop.get("lien_amount") and prop["lien_amount"] > 0:
        signals += 1
    return min((signals - 1) * 5, 15) if signals > 1 else 0


def calculate_distress_score(prop: dict) -> int:
    score = 0

    score += _score_distress_type(prop.get("distress_type", "unknown"))
    score += _score_equity(prop.get("equity_pct"))
    score += _score_auction_proximity(prop.get("auction_date"))
    score += _score_tax_delinquency(prop.get("tax_delinquent_amount"))
    score += _score_stacked_signals(prop)

    final_score = min(score, 100)
    logger.debug(
        "calculate_distress_score apn={} type={} score={}",
        prop.get("apn"),
        prop.get("distress_type"),
        final_score
    )
    return final_score


def score_properties(properties: list[dict]) -> list[dict]:
    for prop in properties:
        prop["distress_score"] = calculate_distress_score(prop)
    scored = sorted(properties, key=lambda p: p["distress_score"], reverse=True)
    logger.info("score_properties total={} top_score={}", len(scored), scored[0]["distress_score"] if scored else 0)
    return scored
