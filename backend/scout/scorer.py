from datetime import datetime, timezone

from loguru import logger


SCORE_HIGH_PRIORITY = 75
SCORE_CREATE_LEAD = 50
SCORE_DRIP_ONLY = 35

_DISTRESS_BASE = {
    "nts_filed": 65,
    "pre_foreclosure": 55,
    "notice_of_default": 55,
    "tax_delinquent": 45,
    "active_lien": 30,
    "code_violation": 25,
    "vacant": 45,
    "absentee_owner": 25,
    "out_of_state_owner": 30,
    "free_and_clear": 20,
    "failed_listing": 15,
    "unknown": 0,
}


def _score_distress_type(distress_type: str) -> int:
    return _DISTRESS_BASE.get(distress_type, 0)


def _score_hold_time(prop: dict) -> int:
    years = prop.get("years_owned")
    if years is None:
        months = prop.get("ownership_months")
        if months is not None:
            years = months / 12.0
    if years is None:
        return 0
    if years >= 20:
        return 20
    if years >= 15:
        return 16
    if years >= 10:
        return 12
    if years >= 7:
        return 8
    if years >= 5:
        return 5
    if years >= 2:
        return 2
    return 0


def _score_equity(prop: dict) -> int:
    if prop.get("free_and_clear"):
        return 25
    equity_pct = prop.get("equity_pct")
    if equity_pct is None:
        return 0
    if equity_pct >= 70:
        return 20
    if equity_pct >= 50:
        return 15
    if equity_pct >= 30:
        return 10
    if equity_pct >= 10:
        return 3
    return 0


def _score_auction_proximity(auction_date_str: str | None) -> int:
    if not auction_date_str:
        return 0
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
        return 35
    if days_away <= 30:
        return 28
    if days_away <= 60:
        return 20
    if days_away <= 90:
        return 12
    return 6


def _score_tax_delinquency(prop: dict) -> int:
    score = 0
    tax_year = prop.get("tax_year")
    if tax_year is not None:
        try:
            years_delinquent = datetime.now(timezone.utc).year - int(tax_year)
            if years_delinquent >= 3:
                score += 25
            elif years_delinquent == 2:
                score += 18
            elif years_delinquent == 1:
                score += 10
        except (ValueError, TypeError):
            pass

    amount = prop.get("tax_delinquent_amount")
    if amount:
        dollars = amount / 100
        if dollars >= 20000:
            score += 10
        elif dollars >= 10000:
            score += 7
        elif dollars >= 5000:
            score += 4
        elif dollars >= 1000:
            score += 2

    return score


def _score_stack_bonuses(prop: dict) -> int:
    bonus = 0
    distress = prop.get("distress_type", "unknown")
    vacant = prop.get("vacant", False)
    absentee = distress == "absentee_owner" or prop.get("absentee_owner", False)
    free_clear = prop.get("free_and_clear", False) or distress == "free_and_clear"
    pre_fc = distress in ("pre_foreclosure", "notice_of_default")
    tax_del = distress == "tax_delinquent" or (prop.get("tax_delinquent_amount") or 0) > 0
    equity_pct = prop.get("equity_pct") or 0

    if vacant and absentee:
        bonus += 20
    if vacant and free_clear:
        bonus += 18
    if vacant and pre_fc:
        bonus += 25
    if absentee and tax_del:
        bonus += 18
    if absentee and free_clear:
        bonus += 10
    if pre_fc and equity_pct >= 50:
        bonus += 22
    if tax_del and free_clear:
        bonus += 20
    if prop.get("nod_date") and equity_pct >= 50:
        bonus += 15

    signals = sum([
        distress not in ("unknown", ""),
        (prop.get("tax_delinquent_amount") or 0) > 0,
        bool(prop.get("nod_date")),
        bool(prop.get("auction_date")),
        (prop.get("lien_amount") or 0) > 0,
        vacant,
    ])
    if signals >= 4:
        bonus += 25
    elif signals == 3:
        bonus += 15

    return bonus


def _score_property_type(prop: dict) -> int:
    pt = (prop.get("property_type") or prop.get("land_use") or "").lower()
    if "vacant land" in pt or "land" in pt:
        return 10
    if "multi" in pt or "duplex" in pt or "triplex" in pt or "fourplex" in pt:
        return 8
    if "single" in pt or "sfr" in pt or "residence" in pt:
        return 5
    if "condo" in pt or "townhouse" in pt:
        return 3
    return 0


def _score_penalties(prop: dict) -> int:
    penalty = 0
    years = prop.get("years_owned")
    if years is None:
        months = prop.get("ownership_months")
        if months is not None:
            years = months / 12.0
    if years is not None and years < 2:
        penalty += 15

    owner = (prop.get("owner_name") or "").upper()
    owner_type = (prop.get("owner_type") or "").upper()
    corporate_signals = ("LLC", "INC", "CORP", "TRUST", "LP ", "LLP", "FUND", "HOLDINGS", "PROPERTIES LLC")
    if any(s in owner for s in corporate_signals) or any(s in owner_type for s in ("LLC", "CORP", "INC", "TRUST")):
        penalty += 5

    return penalty


def calculate_distress_score(prop: dict) -> int:
    score = 0
    score += _score_distress_type(prop.get("distress_type", "unknown"))
    score += _score_hold_time(prop)
    score += _score_equity(prop)
    score += _score_auction_proximity(prop.get("auction_date"))
    score += _score_tax_delinquency(prop)
    score += _score_stack_bonuses(prop)
    score += _score_property_type(prop)
    score -= _score_penalties(prop)
    final_score = max(0, min(score, 100))
    logger.debug(
        "calculate_distress_score apn={} type={} score={}",
        prop.get("apn"),
        prop.get("distress_type"),
        final_score,
    )
    return final_score


def score_properties(properties: list[dict]) -> list[dict]:
    for prop in properties:
        prop["distress_score"] = calculate_distress_score(prop)
    scored = sorted(properties, key=lambda p: p["distress_score"], reverse=True)
    logger.info(
        "score_properties total={} top_score={}",
        len(scored),
        scored[0]["distress_score"] if scored else 0,
    )
    return scored
