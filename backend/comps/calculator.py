import os
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from loguru import logger

MAO_MULTIPLIER = Decimal(os.environ.get("MAO_MULTIPLIER", "0.70"))
if not MAO_MULTIPLIER.is_finite() or not 0 < MAO_MULTIPLIER <= 1:
    raise ValueError("Invalid screening multiplier")
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
        return (datetime.now(timezone.utc).date() - sold.date()).days
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

    accepted_prices = []
    seen = set()
    for comp in comps:
        if not isinstance(comp, dict):
            continue
        identity = (comp.get('sale_id') or comp.get('address'), comp.get('sold_date') or comp.get('date_sold'))
        if not identity[0]:
            identity = (str(comp.get('sold_price')), str(comp.get('sqft')), identity[1])
        if identity in seen:
            continue
        seen.add(identity)
        sold_price = comp.get("sold_price")
        sqft = comp.get("sqft")
        if type(sold_price) not in (int, float) or type(sqft) not in (int, float) or not math.isfinite(sold_price) or not math.isfinite(sqft) or sold_price <= 0 or sqft <= 0:
            continue

        ppsf = sold_price / sqft
        days_old = _days_since(comp.get("sold_date") or comp.get("date_sold"))
        if days_old is not None and days_old < 0:
            continue
        accepted_prices.append(sold_price)
        distance = comp.get("distance_miles")

        w = _recency_weight(days_old)
        if days_old is None or days_old > _STALE_DAYS:
            stale_count += 1
        if type(distance) in (int, float) and math.isfinite(distance) and distance > _DISTANT_MILES:
            distant_count += 1
            w *= 0.75

        prices_per_sqft.append(ppsf)
        weights.append(w)

    if not prices_per_sqft:
        logger.warning("calculate_arv no valid price/sqft from comps")
        return {"arv": None, "mao": None, "confidence": "low", "comp_count": 0,
                "price_per_sqft": None, "price_variance": None, "neighborhood_liquidity": 0, "comp_strength": "none"}

    total_weight = sum(weights)
    weighted_ppsf = sum(p * w for p, w in zip(prices_per_sqft, weights)) / total_weight

    if type(subject_sqft) in (int, float) and math.isfinite(subject_sqft) and subject_sqft > 0:
        arv_dollars = weighted_ppsf * subject_sqft
    else:
        sold_prices = accepted_prices
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

    arv_cents = int((Decimal(str(arv_dollars)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    repair_buffer_cents = MAO_REPAIR_BUFFER * 100
    mao_cents = max(int(Decimal(arv_cents) * Decimal(str(MAO_MULTIPLIER))) - repair_buffer_cents, 0)

    logger.info("calculate_arv comps={} ppsf={:.2f} arv=${:.0f} mao=${:.0f} confidence={} variance={:.3f} strength={}",
                len(comps), weighted_ppsf, arv_dollars, mao_cents / 100, confidence, price_variance, comp_strength)

    return {"method": "unreviewed_ppsf_diagnostic", "quote_authorized": False, "offer_authorized": False, "production_ready": False, "arv": arv_cents, "mao": mao_cents, "confidence": confidence,
            "comp_count": len(prices_per_sqft), "price_per_sqft": int(weighted_ppsf * 100),
            "price_variance": round(price_variance, 4), "neighborhood_liquidity": len(prices_per_sqft),
            "comp_strength": comp_strength, "stale_comp_count": stale_count, "distant_comp_count": distant_count}
