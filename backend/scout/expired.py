from loguru import logger

try:
    from homeharvest import scrape_property
    _HH_AVAILABLE = True
except ImportError:
    _HH_AVAILABLE = False
    logger.warning("homeharvest not installed — expired scraper disabled")

from backend.lib.db import _get_client as _db


_LOCATION = "San Joaquin County, CA"
_EXPIRED_DOM = 60
_PRICE_DROP_PCT = 5.0


def _upsert_distress(row: dict, distress_type: str) -> None:
    client = _db()
    apn = str(row.get("mls") or row.get("property_url") or "").strip()
    if not apn:
        return

    def _safe_str(val, default="") -> str:
        if val is None or str(val) in ("nan", "<NA>", "NA", "None"):
            return default
        return str(val).strip()

    def _safe_int(val, default=0) -> int:
        try:
            return int(val) if val is not None and str(val) not in ("nan", "<NA>", "NA", "None") else default
        except (ValueError, TypeError):
            return default

    def _safe_float(val) -> float | None:
        try:
            return float(val) if val is not None and str(val) not in ("nan", "<NA>", "NA", "None") else None
        except (ValueError, TypeError):
            return None

    address = _safe_str(row.get("street"))
    city = _safe_str(row.get("city"))
    state = _safe_str(row.get("state"), "CA")
    zip_code = _safe_str(row.get("zip_code"))
    list_price = _safe_int(row.get("list_price"))
    dom = _safe_int(row.get("days_on_market"))
    beds = _safe_int(row.get("beds")) or None
    baths = _safe_float(row.get("full_baths"))
    sqft = _safe_int(row.get("sqft")) or None
    year_built = _safe_int(row.get("year_built")) or None

    existing = (
        client.table("properties")
        .select("id, last_list_price, price_reduced")
        .eq("apn", apn)
        .limit(1)
        .execute()
    )

    price_reduced = False
    if existing.data:
        last_price = existing.data[0].get("last_list_price") or 0
        if last_price > 0 and list_price > 0:
            drop_pct = (last_price - list_price) / last_price * 100
            if drop_pct >= _PRICE_DROP_PCT:
                price_reduced = True
                logger.info(
                    "price_reduced apn={} prev={} curr={} drop={:.1f}%",
                    apn, last_price, list_price, drop_pct,
                )

    payload = {
        "apn": apn,
        "address": address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "distress_type": distress_type,
        "distress_score": 57,
        "deal_viable": True,
        "days_on_market": dom,
        "last_list_price": list_price,
        "price_reduced": price_reduced,
    }

    if beds is not None:
        payload["beds"] = beds
    if baths is not None:
        payload["baths"] = baths
    if sqft is not None:
        payload["sqft"] = sqft
    if year_built is not None:
        payload["year_built"] = year_built

    client.table("properties").upsert(payload, on_conflict="apn").execute()
    logger.debug("upserted apn={} distress_type={} price_reduced={}", apn, distress_type, price_reduced)


def run_expired_scraper() -> None:
    if not _HH_AVAILABLE:
        logger.error("run_expired_scraper called but homeharvest not installed")
        return

    logger.info("run_expired_scraper started location={}", _LOCATION)

    try:
        df = scrape_property(
            location=_LOCATION,
            listing_type="for_sale",
            past_days=180,
        )
    except Exception as e:
        logger.error("homeharvest for_sale scrape failed error={}", str(e))
        return

    if df is None or df.empty:
        logger.warning("run_expired_scraper: no listings returned")
        return

    logger.info("run_expired_scraper raw_count={}", len(df))

    expired_count = 0
    fsbo_count = 0

    for _, row in df.iterrows():
        dom = row.get("days_on_market")
        raw_agent = row.get("agent_name")
        agent = "" if (raw_agent is None or str(raw_agent) in ("nan", "<NA>", "NA")) else str(raw_agent).strip()
        is_fsbo = not agent

        if is_fsbo:
            _upsert_distress(row, "fsbo")
            fsbo_count += 1
        elif dom is not None and int(dom) >= _EXPIRED_DOM:
            _upsert_distress(row, "expired_listing")
            expired_count += 1

    logger.info(
        "run_expired_scraper complete expired={} fsbo={}",
        expired_count,
        fsbo_count,
    )
