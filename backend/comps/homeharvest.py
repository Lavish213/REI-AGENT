from loguru import logger

try:
    from homeharvest import scrape_property
    _HH_AVAILABLE = True
except ImportError:
    _HH_AVAILABLE = False
    logger.warning("homeharvest not installed — comps fallback to assessed value")


def get_comps(
    address: str,
    city: str,
    state: str,
    beds: int | None,
    baths: int | None,
    sqft: int | None = None,
) -> dict:
    if not _HH_AVAILABLE:
        return _fallback(sqft)

    try:
        df = scrape_property(
            location=f"{city}, {state}",
            listing_type="sold",
            past_days=90,
            radius=0.5,
        )
    except Exception as e:
        logger.error("homeharvest scrape_property failed city={} error={}", city, str(e))
        return _fallback(sqft)

    if df is None or df.empty:
        logger.warning("homeharvest returned no results city={}", city)
        return _fallback(sqft)

    df = df.copy()

    if beds is not None:
        df = df[
            df["beds"].notna() &
            (df["beds"] >= beds - 1) &
            (df["beds"] <= beds + 1)
        ]

    if "style" in df.columns:
        sfr_styles = {"SINGLE_FAMILY", "SFR", "HOUSE", "RANCH", "COLONIAL", "TUDOR"}
        df = df[df["style"].str.upper().isin(sfr_styles) | df["style"].isna()]

    if df.empty:
        logger.warning("homeharvest: all comps filtered out address={}", address)
        return _fallback(sqft)

    price_col = "sold_price" if "sold_price" in df.columns else "list_price"
    df = df[df[price_col].notna() & (df[price_col] > 0)]
    df = df[df["sqft"].notna() & (df["sqft"] > 0)]

    if df.empty:
        return _fallback(sqft)

    df["ppsf"] = df[price_col] / df["sqft"]

    avg_ppsf = df["ppsf"].mean()
    min_price = int(df[price_col].min())
    max_price = int(df[price_col].max())
    comp_count = len(df)

    arv_estimate = 0
    if sqft and sqft > 0:
        arv_estimate = int(avg_ppsf * sqft * 100)
    elif comp_count > 0:
        arv_estimate = int(df[price_col].median() * 100)

    close_df = df
    if "distance" in df.columns:
        close_df = df[df["distance"].notna() & (df["distance"] <= 0.25)]

    if len(close_df) >= 3:
        confidence = "HIGH"
    elif comp_count >= 3:
        confidence = "MEDIUM"
    elif comp_count >= 1:
        confidence = "LOW"
    else:
        return _fallback(sqft)

    logger.info(
        "homeharvest comps address={} count={} ppsf={:.2f} arv={} confidence={}",
        address,
        comp_count,
        avg_ppsf,
        arv_estimate,
        confidence,
    )

    return {
        "arv_estimate": arv_estimate,
        "comp_count": comp_count,
        "price_per_sqft": int(avg_ppsf * 100),
        "confidence": confidence,
        "comp_range_low": int(min_price * 100),
        "comp_range_high": int(max_price * 100),
        "source": "homeharvest",
    }


def _fallback(sqft: int | None) -> dict:
    return {
        "arv_estimate": 0,
        "comp_count": 0,
        "price_per_sqft": 0,
        "confidence": "NONE",
        "comp_range_low": 0,
        "comp_range_high": 0,
        "source": "fallback",
    }


def trigger_arv_computation(property_id: str, address: str, sqft: int | None = None) -> None:
    import asyncio
    try:
        comps = pull_comps(address)
        if not comps:
            logger.warning("trigger_arv_computation no comps found address={}", address)
            return
        from backend.comps.calculator import calculate_arv
        result = calculate_arv(comps, sqft)
        if result.get("arv"):
            from backend.lib.db import update_property_arv
            update_property_arv(property_id, result)
            logger.info(
                "arv_computed property_id={} arv=${:.0f} confidence={}",
                property_id,
                result["arv"] / 100,
                result["confidence"],
            )
    except Exception as e:
        logger.warning("trigger_arv_computation failed property_id={} error={}", property_id, str(e))
