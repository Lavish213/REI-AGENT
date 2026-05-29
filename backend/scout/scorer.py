from datetime import datetime, timezone

from loguru import logger


SCORE_HIGH_PRIORITY = 85
SCORE_CREATE_LEAD = 50
SCORE_DRIP_ONLY = 35

_DISQUALIFY_TYPES = {
    "land", "lot", "vacant land", "acreage", "agricultural",
    "farm", "ranch", "commercial", "industrial", "mobile",
    "manufactured", "timeshare",
}
_DISQUALIFY_ADDRESS_TOKENS = {" lot ", " lots ", " acreage ", " land ", " parcel "}


def _years_owned(prop: dict) -> float | None:
    y = prop.get("years_owned")
    if y is not None:
        return float(y)
    m = prop.get("ownership_months")
    if m is not None:
        return float(m) / 12.0
    return None


def _check_disqualifiers(prop: dict) -> str | None:
    pt = (prop.get("property_type") or prop.get("land_use") or "").lower()
    if any(bad in pt for bad in _DISQUALIFY_TYPES):
        return f"property_type:{pt}"

    addr = (" " + (prop.get("address") or "").lower() + " ")
    if any(tok in addr for tok in _DISQUALIFY_ADDRESS_TOKENS):
        return f"address_token:{addr.strip()}"

    beds = prop.get("beds")
    if not beds or beds == 0:
        return "no_beds"

    sqft = prop.get("sqft")
    if not sqft or sqft < 400:
        return "sqft_too_small"

    ev = prop.get("estimated_value")
    if ev is not None:
        ev_dollars = ev / 100
        if ev_dollars < 50000:
            return f"value_too_low:{int(ev_dollars)}"
        if ev_dollars > 225000:
            return f"value_too_high:{int(ev_dollars)}"

    years = _years_owned(prop)
    if years is not None and years < 0.5:
        return "owned_under_6_months"

    return None


def _tax_delinquent_years(prop: dict) -> int:
    tax_year = prop.get("tax_year")
    if tax_year is None:
        return 0
    try:
        return max(0, datetime.now(timezone.utc).year - int(tax_year))
    except (ValueError, TypeError):
        return 0


def _motivation_score(prop: dict) -> int:
    score = 0
    distress = prop.get("distress_type", "unknown")
    vacant = bool(prop.get("vacant"))
    absentee = bool(prop.get("absentee_owner")) or distress == "absentee_owner"
    free_clear = bool(prop.get("free_and_clear")) or distress == "free_and_clear"
    pre_fc = bool(prop.get("pre_foreclosure")) or distress in ("pre_foreclosure", "notice_of_default")
    nts = bool(prop.get("nts_date")) or distress == "nts_filed"
    nod = bool(prop.get("nod_date"))
    tax_del_years = _tax_delinquent_years(prop)
    tax_del = tax_del_years > 0 or distress == "tax_delinquent" or (prop.get("tax_delinquent_amount") or 0) > 0
    lien = (prop.get("lien_amount") or 0) / 100
    code_viol = distress == "code_violation"
    mail_state = (prop.get("owner_mailing_state") or "").upper()
    equity_pct = prop.get("equity_pct") or 0

    if nts:
        score += 65
    if pre_fc:
        score += 55
    if nod and not pre_fc:
        score += 55
    if tax_del_years >= 3:
        score += 45
    elif tax_del_years in (1, 2):
        score += 30
    if lien > 5000:
        score += 25
    if code_viol:
        score += 18

    if vacant:
        score += 42

    if mail_state and mail_state != "CA":
        score += 30
    if absentee:
        score += 22
    if free_clear:
        score += 15

    years = _years_owned(prop)
    if years is not None:
        if years >= 20:
            score += 20
        elif years >= 15:
            score += 16
        elif years >= 10:
            score += 12
        elif years >= 7:
            score += 8
        elif years >= 5:
            score += 5
        elif years >= 2:
            score += 2

    if vacant and absentee:
        score += 22
    if vacant and pre_fc:
        score += 28
    if vacant and free_clear:
        score += 18
    if absentee and tax_del:
        score += 20
    if pre_fc and equity_pct >= 50:
        score += 22
    if tax_del and free_clear:
        score += 20

    if prop.get("price_reduced"):
        score += 15

    signals = sum([
        nts or pre_fc or nod,
        tax_del,
        bool(prop.get("auction_date")),
        lien > 0,
        vacant,
        absentee,
    ])
    if signals >= 4:
        score += 25
    elif signals == 3:
        score += 15

    return min(score, 100)


def _move_score(prop: dict) -> int:
    score = 0
    distress = prop.get("distress_type", "unknown")
    years = _years_owned(prop)

    if distress in ("probate", "inherited", "estate"):
        score += 8
    if distress in ("divorce", "separation"):
        score += 6
    if distress in ("pre_foreclosure", "notice_of_default", "nts_filed"):
        score += 6
    if years is not None and years >= 7:
        score += 4

    dom = prop.get("days_on_market") or 0
    price_drops = prop.get("price_drop_count") or 0
    if dom >= 30 and price_drops >= 2:
        score += 15
    elif dom >= 30:
        score += 5
    elif price_drops >= 2:
        score += 5

    return min(score, 30)


def _compute_arv(prop: dict) -> int:
    try:
        from backend.comps.homeharvest import get_comps as hh_get_comps
        result = hh_get_comps(
            address=prop.get("address", ""),
            city=prop.get("city", ""),
            state=prop.get("state", "CA"),
            beds=prop.get("beds"),
            baths=prop.get("baths"),
            sqft=prop.get("sqft"),
        )
        if result.get("arv_estimate") and result["arv_estimate"] > 0:
            prop["arv_confidence"] = result["confidence"]
            prop["comp_count"] = result["comp_count"]
            prop["price_per_sqft"] = result["price_per_sqft"]
            return result["arv_estimate"]
    except Exception as e:
        logger.warning("homeharvest arv lookup failed apn={} error={}", prop.get("apn"), str(e))

    zestimate = prop.get("zestimate")
    if zestimate and zestimate > 0:
        return int(zestimate)
    assessed = prop.get("assessed_total_value")
    if assessed and assessed > 0:
        return int(assessed / 0.80)
    ev = prop.get("estimated_value")
    if ev and ev > 0:
        return int(ev)
    return 0


def _deal_score(prop: dict, arv: int) -> int:
    score = 0
    equity_pct = prop.get("equity_pct") or 0
    free_clear = bool(prop.get("free_and_clear")) or prop.get("distress_type") == "free_and_clear"

    if free_clear:
        score += 40
    elif equity_pct >= 70:
        score += 32
    elif equity_pct >= 50:
        score += 22
    elif equity_pct >= 30:
        score += 14
    elif equity_pct >= 10:
        score += 5

    if arv > 0:
        arv_dollars = arv / 100
        if 150000 <= arv_dollars <= 200000:
            score += 25
        elif 120000 <= arv_dollars < 150000:
            score += 18
        elif 200000 < arv_dollars <= 225000:
            score += 18
        elif 80000 <= arv_dollars < 120000:
            score += 10
        elif 50000 <= arv_dollars < 80000:
            score += 5

    pt = (prop.get("property_type") or prop.get("land_use") or "").lower()
    if "single" in pt or "sfr" in pt or "residence" in pt:
        score += 12
    elif "duplex" in pt or "triplex" in pt:
        score += 10
    elif "fourplex" in pt or "4-plex" in pt or "4plex" in pt or "quadplex" in pt:
        score += 8
    elif "condo" in pt or "townhouse" in pt:
        score += 4

    year_built = prop.get("year_built")
    if year_built:
        if year_built < 1960:
            score += 10
        elif year_built < 1980:
            score += 7
        elif year_built < 2000:
            score += 4
        else:
            score += 1

    return min(score, 100)


def calculate_distress_score(prop: dict) -> int:
    reason = _check_disqualifiers(prop)
    if reason:
        prop["deal_viable"] = False
        prop["disqualified_reason"] = reason
        prop["motivation_score"] = 0
        prop["deal_score"] = 0
        prop["estimated_arv"] = 0
        prop["mao"] = 0
        logger.debug("disqualified apn={} reason={}", prop.get("apn"), reason)
        return 0

    prop["deal_viable"] = True
    prop["disqualified_reason"] = None

    motivation = _motivation_score(prop)
    arv = _compute_arv(prop)
    deal = _deal_score(prop, arv)
    mao = max(0, int(arv * 0.70) - 2500000)
    move_bonus = _move_score(prop)

    prop["motivation_score"] = motivation
    prop["deal_score"] = deal
    prop["estimated_arv"] = arv
    prop["mao"] = mao
    prop["move_score"] = move_bonus

    final = min(int(motivation * 0.65 + deal * 0.35 + move_bonus * 0.1), 100)
    logger.debug(
        "calculate_distress_score apn={} type={} motivation={} deal={} score={}",
        prop.get("apn"),
        prop.get("distress_type"),
        motivation,
        deal,
        final,
    )
    return final


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
