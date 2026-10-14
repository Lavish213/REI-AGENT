from loguru import logger
from decimal import Decimal, InvalidOperation

try:
    from homeharvest import scrape_property
    _HH_AVAILABLE = True
except ImportError:
    _HH_AVAILABLE = False
    logger.warning("homeharvest not installed — expired scraper disabled")

from backend.lib.db import persist_mls_candidate


_LOCATION = "San Joaquin County, CA"


def _upsert_distress(row: dict, distress_type: str) -> None:
    apn = str(row.get("apn") or "").strip().replace("-", "")
    county = str(row.get("county") or "").strip().lower()
    if len(apn) != 8 or not apn.isascii() or not apn.isdigit() or apn == "00000000" or county not in {"san joaquin", "san joaquin county"} or row.get("state") != "CA":
        logger.warning("listing_candidate_missing_canonical_parcel_or_county")
        return False

    def _safe_str(val, default="") -> str:
        if val is None or str(val) in ("nan", "<NA>", "NA", "None"):
            return default
        return str(val).strip()

    def _safe_int(val, default=0) -> int:
        try:
            return int(val) if val is not None and str(val) not in ("nan", "<NA>", "NA", "None") else default
        except (ValueError, TypeError, OverflowError):
            return default

    def _safe_float(val) -> float | None:
        try:
            return float(val) if val is not None and str(val) not in ("nan", "<NA>", "NA", "None") else None
        except (ValueError, TypeError, OverflowError):
            return None

    address = _safe_str(row.get("street"))
    city = _safe_str(row.get("city"))
    state = _safe_str(row.get("state"), "CA")
    zip_code = _safe_str(row.get("zip_code"))
    try:
        price = Decimal(str(row.get("list_price")))
        if not price.is_finite() or price <= 0 or price > 10**12 or price * 100 != (price * 100).to_integral_value():
            return False
        list_price_cents = int(price * 100)
    except (InvalidOperation, ValueError, TypeError):
        return False
    dom = _safe_int(row.get("days_on_market"))
    beds = _safe_int(row.get("beds")) or None
    baths = _safe_float(row.get("full_baths"))
    sqft = _safe_int(row.get("sqft")) or None
    year_built = _safe_int(row.get("year_built")) or None

    payload = {
        "apn": apn,
        "address": address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "distress_type": distress_type,
        "distress_score": 57,
        "deal_viable": False,
        "days_on_market": dom,
        "last_list_price": list_price_cents,
        "price_reduced": False,
        "county": "San Joaquin",
    }

    if beds is not None:
        payload["beds"] = beds
    if baths is not None:
        payload["baths"] = baths
    if sqft is not None:
        payload["sqft"] = sqft
    if year_built is not None:
        payload["year_built"] = year_built

    if not persist_mls_candidate(payload):
        return False
    logger.debug("listing_candidate_saved apn={} type={}", apn, distress_type)
    return True


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
        status = str(row.get("status") or "").strip().lower()
        is_fsbo = row.get("is_fsbo") is True
        if is_fsbo:
            fsbo_count += int(bool(_upsert_distress(row, "fsbo")))
        elif status == "expired":
            expired_count += int(bool(_upsert_distress(row, "expired_listing")))

    logger.info(
        "run_expired_scraper complete expired={} fsbo={}",
        expired_count,
        fsbo_count,
    )
