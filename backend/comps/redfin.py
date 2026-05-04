import httpx
from loguru import logger


REDFIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.redfin.com/",
}

REDFIN_BASE = "https://www.redfin.com"
RADIUS_MILES = 0.5
MONTHS_BACK = 6


def _search_address(address: str, city: str, state: str) -> str | None:
    query = f"{address} {city} {state}"
    url = f"{REDFIN_BASE}/stingray/do/location-autocomplete"
    params = {
        "location": query,
        "start": 0,
        "count": 1,
        "v": 2,
    }
    try:
        with httpx.Client(headers=REDFIN_HEADERS, timeout=10) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            text = response.text
            if text.startswith("{}&&"):
                text = text[4:]
            import json
            data = json.loads(text)
            results = data.get("payload", {}).get("sections", [])
            for section in results:
                for row in section.get("rows", []):
                    if row.get("type") == 2:
                        return row.get("url")
            return None
    except Exception as e:
        logger.error("redfin address search failed address={} error={}", address, str(e))
        return None


def _get_comps_from_region(region_url: str, beds: int | None, baths: float | None, sqft: int | None) -> list[dict]:
    url = f"{REDFIN_BASE}/stingray/api/gis-csv"

    bed_min = max((beds or 1) - 1, 1)
    bed_max = (beds or 3) + 1
    sqft_min = int((sqft or 1000) * 0.7)
    sqft_max = int((sqft or 1000) * 1.3)

    params = {
        "al": 1,
        "market": "norcal",
        "num_beds": bed_min,
        "max_num_beds": bed_max,
        "min_sqft": sqft_min,
        "max_sqft": sqft_max,
        "status": 9,
        "sold_within_days": MONTHS_BACK * 30,
        "v": 8,
    }

    try:
        with httpx.Client(headers=REDFIN_HEADERS, timeout=15) as client:
            response = client.get(url, params=params)
            response.raise_for_status()

            import csv
            import io
            reader = csv.DictReader(io.StringIO(response.text))
            comps = []
            for row in reader:
                price_str = row.get("PRICE", "").replace("$", "").replace(",", "").strip()
                sqft_str = row.get("SQUARE FEET", "").replace(",", "").strip()
                try:
                    price = int(float(price_str)) if price_str else None
                    sqft_val = int(float(sqft_str)) if sqft_str else None
                    if price and sqft_val:
                        comps.append({
                            "address": row.get("ADDRESS", ""),
                            "sold_price": price,
                            "sqft": sqft_val,
                            "beds": int(float(row.get("BEDS", 0) or 0)),
                            "baths": float(row.get("BATHS", 0) or 0),
                            "sold_date": row.get("SOLD DATE", ""),
                            "price_per_sqft": int(price / sqft_val),
                        })
                except (ValueError, ZeroDivisionError):
                    continue
            return comps
    except Exception as e:
        logger.error("redfin comps fetch failed error={}", str(e))
        return []


def get_comps(
    address: str,
    city: str,
    state: str,
    beds: int | None = None,
    baths: float | None = None,
    sqft: int | None = None,
) -> list[dict]:
    logger.info("get_comps address={} {}, {}", address, city, state)

    region_url = _search_address(address, city, state)
    if not region_url:
        logger.warning("get_comps could not find region for address={}", address)
        return []

    comps = _get_comps_from_region(region_url, beds, baths, sqft)
    logger.info("get_comps found={} comps for address={}", len(comps), address)
    return comps
