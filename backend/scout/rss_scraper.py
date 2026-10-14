import json
import os
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx
from loguru import logger

from backend.lib.db import save_source_candidate


RSS_FEEDS = []
SAN_JOAQUIN_ZIPS = [
    "95201", "95202", "95203", "95204", "95205", "95206", "95207", "95208",
    "95209", "95210", "95211", "95212", "95215", "95219", "95220", "95240",
    "95241", "95242", "95330", "95336", "95337", "95366", "95376", "95377",
    "95378",
]


def configured_feeds():
    feeds = json.loads(os.environ.get('SCOUT_RSS_FEEDS', '[]'))
    if not isinstance(feeds, list) or len(feeds) > 30:
        raise ValueError('Bounded approved RSS registry required')
    for value in feeds:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Approved HTTPS RSS source required')
    return feeds


def scrape_price_reductions(zip_codes):
    results = []
    for template in configured_feeds() or RSS_FEEDS:
        for zip_code in zip_codes if '{zip_code}' in template else ['']:
            source = template.format(zip_code=zip_code)
            try:
                with httpx.Client(timeout=10, follow_redirects=False) as client:
                    with client.stream('GET', source) as response:
                        response.raise_for_status()
                        raw = bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 2000000:
                                raise ValueError('RSS source response budget exceeded')
                root = ElementTree.fromstring(raw)
                entries = root.findall('.//item') or root.findall('{http://www.w3.org/2005/Atom}entry')
                for entry in entries[:200]:
                    title = entry.findtext('title') or entry.findtext('{http://www.w3.org/2005/Atom}title') or ''
                    link = entry.findtext('link')
                    if not link:
                        element = entry.find('{http://www.w3.org/2005/Atom}link')
                        link = element.get('href') if element is not None else None
                    if title and link:
                        results.append({'source_ref': link, 'source_url': source, 'source_text': title[:2000], 'source_zip_query': zip_code, 'property_verified': False})
            except Exception as error:
                logger.warning('rss_source_failed type={}', type(error).__name__)
    return results


def run_rss_scraper():
    count = 0
    for candidate in scrape_price_reductions(SAN_JOAQUIN_ZIPS):
        try:
            save_source_candidate('rss', candidate)
            count += 1
        except Exception as error:
            logger.warning('rss_candidate_failed type={}', type(error).__name__)
    return count
