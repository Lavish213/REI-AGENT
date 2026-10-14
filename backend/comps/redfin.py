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
    logger.warning('legacy_redfin_comps_disabled_missing_verified_region_contract')
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
