import time

from loguru import logger

from backend.lib.db import upsert_property

SAN_JOAQUIN_ZIPS = [
    "95201", "95202", "95203", "95204", "95205", "95206", "95207", "95208",
    "95209", "95210", "95211", "95212", "95215", "95219", "95220", "95240",
    "95241", "95242", "95330", "95336", "95337", "95366", "95376", "95377",
    "95378",
]

RSS_FEEDS = [
    "https://www.realtor.com/rss/priceReduction/zip/{zip_code}",
]


def scrape_price_reductions(zip_codes: list[str]) -> list[dict]:
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed, rss_scraper skipped")
        return []

    results = []

    for zip_code in zip_codes:
        for feed_template in RSS_FEEDS:
            feed_url = feed_template.format(zip_code=zip_code)
            try:
                feed = feedparser.parse(feed_url)
                entries = feed.get("entries", [])
                for entry in entries:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    summary = entry.get("summary", "")

                    prop = {
                        "address": title,
                        "city": "Stockton",
                        "state": "CA",
                        "zip": zip_code,
                        "county": "San Joaquin",
                        "distress_type": "price_reduction",
                        "status": "new",
                        "social_post_url": link,
                        "social_source": "rss",
                    }
                    results.append(prop)

                logger.info(
                    "rss_scraper zip={} feed_entries={}", zip_code, len(entries)
                )
                time.sleep(3)

            except Exception as e:
                logger.error(
                    "rss_scraper feed fetch failed zip={} url={} error={}",
                    zip_code,
                    feed_url,
                    str(e),
                )

    return results


def run_rss_scraper() -> int:
    props = scrape_price_reductions(SAN_JOAQUIN_ZIPS)
    count = 0
    for prop in props:
        try:
            upsert_property(prop)
            count += 1
        except Exception as e:
            logger.error(
                "rss_scraper upsert failed address={} error={}",
                prop.get("address"),
                str(e),
            )
    logger.info("rss_scraper run complete count={}", count)
    return count
