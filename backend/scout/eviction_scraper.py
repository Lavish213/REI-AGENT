import httpx
from loguru import logger

SJCOURTS_SEARCH_URL = "https://www.sjcourts.org/divisions/civil/civil-case-search/"

EVICTION_CASE_TYPES = ["UD", "unlawful detainer"]


def scrape_eviction_filings() -> list[dict]:
    leads = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed, eviction_scraper limited")
        BeautifulSoup = None

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        with httpx.Client(headers=headers, timeout=20.0, follow_redirects=True) as client:
            resp = client.get(SJCOURTS_SEARCH_URL)
            resp.raise_for_status()

            if BeautifulSoup is None:
                logger.info(
                    "eviction_scraper: sjcourts.org reachable but bs4 unavailable "
                    "— install beautifulsoup4 for full parsing"
                )
                return leads

            soup = BeautifulSoup(resp.text, "html.parser")

            rows = soup.select("table tr") or soup.select(".case-row")
            for row in rows[1:]:
                cols = row.select("td")
                if len(cols) < 3:
                    continue

                case_number = cols[0].get_text(strip=True)
                case_type = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                filed_date = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                parties = cols[3].get_text(strip=True) if len(cols) > 3 else ""

                is_ud = any(
                    ct.lower() in (case_type + " " + case_number).lower()
                    for ct in EVICTION_CASE_TYPES
                )
                if not is_ud:
                    continue

                lead = {
                    "address": parties,
                    "city": "Stockton",
                    "state": "CA",
                    "county": "San Joaquin",
                    "distress_type": "eviction_filing",
                    "status": "new",
                    "case_number": case_number,
                    "nod_date": filed_date,
                }
                leads.append(lead)

            if not rows:
                logger.info(
                    "eviction_scraper: sjcourts.org requires authentication for case search "
                    "— module ready for integration when credentials are available"
                )

    except httpx.HTTPStatusError as e:
        logger.warning(
            "eviction_scraper http error status={} url={} — site may require login",
            e.response.status_code,
            SJCOURTS_SEARCH_URL,
        )
    except Exception as e:
        logger.error("eviction_scraper failed error={}", str(e))

    return leads


def run_eviction_scraper() -> int:
    leads = scrape_eviction_filings()
    logger.info("eviction_scraper run complete count={}", len(leads))
    return len(leads)
