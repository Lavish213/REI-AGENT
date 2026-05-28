import os
import math
from datetime import datetime, timezone
from loguru import logger

MAO_MULTIPLIER = float(os.environ.get("MAO_MULTIPLIER", 0.70))
MAO_REPAIR_BUFFER = int(os.environ.get("MAO_REPAIR_BUFFER", 25000))

_STALE_DAYS = 180
_DISTANT_MILES = 0.75


def _median(values):
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    return sorted_vals[mid]


def _std_dev(values):
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _days_since(date_str):
    if not date_str:
        return None
    try:
        sold = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - sold).days
    except Exception:
        return None


def _recency_weight(days_old):
    if days_old is None:
        return 0.5
    if days_old > _STALE_DAYS:
        return 0.5
    return 1.0


def _confidence(comp_count, price_variance, stale_count, distant_count):
    if comp_count < 3:
        return "low"
    score = comp_count
    if price_variance > 0.15:
        score -= 1
    if stale_count > comp_count // 2:
        score -= 1
    if distant_count > comp_count // 2:
        score -= 1
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def calculate_arv(comps, subject_sqft):
    if not comps:
        logger.warning("calculate_arv called with no comps")
        return {"arv": None, "mao": None, "confidence": "low", "comp_count": 0,
                "price_per_sqft": None, "price_variance": None, "neighborhood_liquidity": 0, "comp_strength": "none"}

    prices_per_sqft = []
    weights = []
    stale_count = 0
    distant_count = 0

    for comp in comps:
        sold_price = comp.get("sold_price")
        sqft = comp.get("sqft")
        if not (sold_price and sqft and sqft > 0):
            continue

        ppsf = sold_price / sqft
        days_old = _days_since(comp.get("sold_date") or comp.get("date_sold"))
        distance = comp.get("distance_miles")

        w = _recency_weight(days_old)
        if days_old and days_old > _STALE_DAYS:
            stale_count += 1
        if distance and distance > _DISTANT_MILES:
            distant_count += 1
            w *= 0.75

        prices_per_sqft.append(ppsf)
        weights.append(w)

    if not prices_per_sqft:
        logger.warning("calculate_arv no valid price/sqft from comps")
        return {"arv": None, "mao": None, "confidence": "low", "comp_count": len(comps),
                "price_per_sqft": None, "price_variance": None, "neighborhood_liquidity": len(comps), "comp_strength": "none"}

    total_weight = sum(weights)
    weighted_ppsf = sum(p * w for p, w in zip(prices_per_sqft, weights)) / total_weight

    if subject_sqft and subject_sqft > 0:
        arv_dollars = weighted_ppsf * subject_sqft
    else:
        sold_prices = [c["sold_price"] for c in comps if c.get("sold_price")]
        arv_dollars = _median(sold_prices) if sold_prices else 0

    std = _std_dev(prices_per_sqft)
    mean_ppsf = sum(prices_per_sqft) / len(prices_per_sqft)
    price_variance = (std / mean_ppsf) if mean_ppsf > 0 else 0.0
    confidence = _confidence(len(prices_per_sqft), price_variance, stale_count, distant_count)

    if price_variance < 0.05 and len(prices_per_sqft) >= 5:
        comp_strength = "strong"
    elif price_variance < 0.12 and len(prices_per_sqft) >= 3:
        comp_strength = "moderate"
    else:
        comp_strength = "weak"

    arv_cents = int(arv_dollars * 100)
    repair_buffer_cents = MAO_REPAIR_BUFFER * 100
    mao_cents = max(int((arv_cents * MAO_MULTIPLIER) - repair_buffer_cents), 0)

    logger.info("calculate_arv comps={} ppsf={:.2f} arv=${:.0f} mao=${:.0f} confidence={} variance={:.3f} strength={}",
                len(comps), weighted_ppsf, arv_dollars, mao_cents / 100, confidence, price_variance, comp_strength)

    return {"arv": arv_cents, "mao": mao_cents, "confidence": confidence,
            "comp_count": len(prices_per_sqft), "price_per_sqft": int(weighted_ppsf * 100),
            "price_variance": round(price_variance, 4), "neighborhood_liquidity": len(comps),
            "comp_strength": comp_strength, "stale_comp_count": stale_count, "distant_comp_count": distant_count}
