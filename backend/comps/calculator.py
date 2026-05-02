import os
from loguru import logger


MAO_MULTIPLIER = float(os.environ.get("MAO_MULTIPLIER", 0.70))
MAO_REPAIR_BUFFER = int(os.environ.get("MAO_REPAIR_BUFFER", 25000))


def _median(values: list[float]) -> float:
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    return sorted_vals[mid]


def _confidence(comp_count: int) -> str:
    if comp_count >= 5:
        return "high"
    if comp_count >= 3:
        return "medium"
    return "low"


def calculate_arv(comps: list[dict], subject_sqft: int | None) -> dict:
    if not comps:
        logger.warning("calculate_arv called with no comps")
        return {
            "arv": None,
            "mao": None,
            "confidence": "low",
            "comp_count": 0,
            "price_per_sqft": None,
        }

    prices_per_sqft = []
    for comp in comps:
        sold_price = comp.get("sold_price")
        sqft = comp.get("sqft")
        if sold_price and sqft and sqft > 0:
            prices_per_sqft.append(sold_price / sqft)

    if not prices_per_sqft:
        logger.warning("calculate_arv no valid price/sqft from comps")
        return {
            "arv": None,
            "mao": None,
            "confidence": "low",
            "comp_count": len(comps),
            "price_per_sqft": None,
        }

    median_ppsf = _median(prices_per_sqft)

    if subject_sqft and subject_sqft > 0:
        arv_dollars = median_ppsf * subject_sqft
    else:
        sold_prices = [c["sold_price"] for c in comps if c.get("sold_price")]
        arv_dollars = _median(sold_prices) if sold_prices else 0

    arv_cents = int(arv_dollars * 100)
    repair_buffer_cents = MAO_REPAIR_BUFFER * 100
    mao_cents = int((arv_cents * MAO_MULTIPLIER) - repair_buffer_cents)
    mao_cents = max(mao_cents, 0)

    confidence = _confidence(len(prices_per_sqft))

    logger.info(
        "calculate_arv comps={} ppsf={:.2f} arv=${:.0f} mao=${:.0f} confidence={}",
        len(comps),
        median_ppsf,
        arv_dollars,
        mao_cents / 100,
        confidence,
    )

    return {
        "arv": arv_cents,
        "mao": mao_cents,
        "confidence": confidence,
        "comp_count": len(prices_per_sqft),
        "price_per_sqft": int(median_ppsf * 100),
    }
