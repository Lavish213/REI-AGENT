import time
from urllib.parse import quote

import httpx
from loguru import logger


_cache: dict[str, int | None] = {}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_last_request: float = 0.0
_DELAY = 3.0


def _throttle() -> None:
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < _DELAY:
        time.sleep(_DELAY - elapsed)
    _last_request = time.time()


def _try_zillow(address: str, city: str, state: str, zip_code: str) -> int | None:
    full = f"{address}, {city}, {state} {zip_code}"
    search_query_state = (
        '{"pagination":{},"isMapVisible":false,"filterState":{"sortSelection":{"value":"globalrelevanceex"}},'
        '"isListVisible":true,"mapZoom":11,"usersSearchTerm":"' + full.replace('"', "") + '"}'
    )
    url = "https://www.zillow.com/search/GetSearchPageState.htm"
    params = {
        "searchQueryState": search_query_state,
        "wants": '{"cat1":["listResults"],"cat2":["total"]}',
        "requestId": "1",
    }
    try:
        _throttle()
        resp = httpx.get(url, params=params, headers=_HEADERS, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return None
        data = resp.json()
        results = data.get("cat1", {}).get("searchResults", {}).get("listResults", [])
        for r in results:
            zestimate = r.get("zestimate") or r.get("hdpData", {}).get("homeInfo", {}).get("zestimate")
            if zestimate:
                return int(zestimate * 100)
    except Exception as e:
        logger.debug("zillow failed address={} error={}", address, str(e))
    return None


def _try_redfin(address: str, city: str, state: str, zip_code: str) -> int | None:
    full = quote(f"{address}, {city}, {state} {zip_code}")
    url = f"https://www.redfin.com/stingray/do/location-autocomplete?location={full}&start=0&count=1&v=2"
    try:
        _throttle()
        resp = httpx.get(url, headers=_HEADERS, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return None
        text = resp.text
        if text.startswith("{}&&"):
            text = text[4:]
        import json
        data = json.loads(text)
        items = data.get("payload", {}).get("exactMatch") or {}
        url_path = items.get("url")
        if not url_path:
            rows = data.get("payload", {}).get("sections", [{}])
            for section in rows:
                for row in section.get("rows", []):
                    url_path = row.get("url")
                    if url_path:
                        break
                if url_path:
                    break
        if not url_path:
            return None

        _throttle()
        detail_url = f"https://www.redfin.com/stingray/api/home/details/initialInfo?path={url_path}&accessLevel=1"
        resp2 = httpx.get(detail_url, headers=_HEADERS, timeout=10, follow_redirects=True)
        if resp2.status_code != 200:
            return None
        text2 = resp2.text
        if text2.startswith("{}&&"):
            text2 = text2[4:]
        data2 = json.loads(text2)
        avm = (
            data2.get("payload", {})
            .get("avm", {})
            .get("predictedValue")
        )
        if avm:
            return int(avm * 100)
    except Exception as e:
        logger.debug("redfin failed address={} error={}", address, str(e))
    return None


def get_zestimate(address: str, city: str, state: str, zip_code: str) -> int | None:
    key = f"{address}|{city}|{state}|{zip_code}".lower()
    if key in _cache:
        return _cache[key]

    result = _try_zillow(address, city, state, zip_code)
    if result is None:
        result = _try_redfin(address, city, state, zip_code)

    _cache[key] = result
    if result:
        logger.debug("zestimate address={} value={}", address, result)
    else:
        logger.debug("zestimate not found address={}", address)
    return result
