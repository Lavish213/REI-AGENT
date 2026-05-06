import time

import httpx
from loguru import logger

CRAIGSLIST_URL = "https://stockton.craigslist.org/d/real-estate-by-owner/search/reo"

FSBO_KEYWORDS = [
    "cash",
    "as-is",
    "motivated",
    "must sell",
    "price reduced",
    "inherited",
    "estate sale",
    "no agents",
    "by owner",
]


def _keyword_score(text: str) -> int:
    lower = text.lower()
    return sum(1 for kw in FSBO_KEYWORDS if kw in lower)


def scrape_craigslist_fsbo() -> list[dict]:
    leads = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed, social_scraper skipped")
        return leads

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        with httpx.Client(headers=headers, timeout=15.0, follow_redirects=True) as client:
            resp = client.get(CRAIGSLIST_URL)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            listings = (
                soup.select(".result-row")
                or soup.select("li.cl-static-search-result")
                or soup.select("li[data-pid]")
            )

            for listing in listings[:20]:
                title_el = (
                    listing.select_one(".result-title")
                    or listing.select_one("a.cl-app-anchor")
                    or listing.select_one("a")
                )
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                url = title_el.get("href", "")
                if not url.startswith("http"):
                    url = "https://stockton.craigslist.org" + url

                description_el = listing.select_one(".result-hood") or listing.select_one(".meta")
                description = description_el.get_text(strip=True) if description_el else ""

                lead = {
                    "address": title,
                    "city": "Stockton",
                    "state": "CA",
                    "county": "San Joaquin",
                    "distress_type": "fsbo",
                    "status": "new",
                    "social_source": "craigslist",
                    "social_post_url": url,
                }
                leads.append(lead)
                time.sleep(1)

    except Exception as e:
        logger.error("craigslist_scrape failed error={}", str(e))

    logger.info("social_scraper craigslist leads={}", len(leads))
    return leads


def run_social_scraper() -> int:
    leads = scrape_craigslist_fsbo()
    logger.info("social_scraper run complete count={}", len(leads))
    return len(leads)
