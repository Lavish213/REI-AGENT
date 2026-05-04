import io
import re
import time
from typing import Any

import httpx
import pdfplumber
from bs4 import BeautifulSoup
from loguru import logger


SJGOV_AUCTION_URL = "https://www.sjgov.org/department/ttc/tax/redemption/public-auction"
SJMAP_QUERY_URL = "https://sjmap.org/server/rest/services/Apps/DistrictViewerSvc/MapServer/10/query"

_APN_PATTERN = re.compile(r"\b(\d{3}-\d{3}-\d{2})\b")
_REQUEST_DELAY = 0.5

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _fetch_pdf_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if ".pdf" not in href.lower():
            continue
        if href.startswith("http"):
            links.append(href)
        elif href.startswith("/"):
            links.append(f"https://www.sjgov.org{href}")
    return links


def _extract_apns_from_pdf(pdf_bytes: bytes) -> list[str]:
    apns: list[str] = []
    seen: set[str] = set()
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for match in _APN_PATTERN.finditer(text):
                    raw = match.group(1)
                    clean = raw.replace("-", "")
                    if clean not in seen:
                        seen.add(clean)
                        apns.append(clean)
    except Exception as e:
        logger.warning("pdf parse error={}", str(e))
    logger.debug("extract_apns found={}", len(apns))
    return apns


def _fetch_parcel(apn_clean: str, client: httpx.Client) -> dict[str, Any] | None:
    params = {
        "where": f"APN='{apn_clean}'",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        resp = client.get(SJMAP_QUERY_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features") or []
        if not features:
            logger.debug("sjmap no result apn={}", apn_clean)
            return None
        return features[0].get("attributes") or {}
    except Exception as e:
        logger.warning("sjmap fetch failed apn={} error={}", apn_clean, str(e))
        return None


def _to_property(attrs: dict[str, Any], apn_clean: str) -> dict[str, Any]:
    land = attrs.get("LAND_VALUE") or 0
    improvement = attrs.get("IMPROVEMENT_VALUE") or 0
    assessed_cents = int((land + improvement) * 100) if (land + improvement) > 0 else None

    apn_dash = (attrs.get("APN_DASH") or "").strip()
    apn_stored = apn_dash.replace("-", "").upper() if apn_dash else apn_clean.upper()

    address_raw = (attrs.get("SITUSADDRESS") or "").strip().title() or None
    city_raw = (attrs.get("SITUSCITYNAME") or "").strip().title() or None
    zip_raw = str(attrs.get("SITUSZIP") or "").strip() or None

    beds_raw = attrs.get("BEDROOMS")
    beds = int(beds_raw) if beds_raw else None

    sqft_raw = attrs.get("TOTALLIV_AREA")
    sqft = int(sqft_raw) if sqft_raw else None

    year_raw = attrs.get("YEAR_BUILT")
    year_built = int(year_raw) if year_raw else None

    owner = (attrs.get("OWNENAME") or "").strip().title() or None
    mail_addr = (attrs.get("MAILADDRESS") or "").strip().title() or None

    return {
        "apn": apn_stored,
        "address": address_raw,
        "city": city_raw,
        "state": "CA",
        "zip": zip_raw,
        "county": "San Joaquin",
        "owner_name": owner,
        "owner_mailing_address": mail_addr,
        "assessed_total_value": assessed_cents,
        "year_built": year_built,
        "beds": beds,
        "sqft": sqft,
        "distress_type": "tax_delinquent",
        "status": "new",
    }


def scrape_tax_delinquent() -> list[dict[str, Any]]:
    properties: list[dict[str, Any]] = []

    with httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True) as client:
        try:
            resp = client.get(SJGOV_AUCTION_URL)
            resp.raise_for_status()
        except Exception as e:
            logger.error("fetch auction page failed error={}", str(e))
            return []

        pdf_links = _fetch_pdf_links(resp.text)
        logger.info("auction page pdf_links={}", len(pdf_links))

        all_apns: list[str] = []
        seen_apns: set[str] = set()

        for pdf_url in pdf_links:
            try:
                pdf_resp = client.get(pdf_url, timeout=60)
                pdf_resp.raise_for_status()
                apns = _extract_apns_from_pdf(pdf_resp.content)
                for apn in apns:
                    if apn not in seen_apns:
                        seen_apns.add(apn)
                        all_apns.append(apn)
                logger.info("pdf={} apns={}", pdf_url.split("/")[-1][:60], len(apns))
            except Exception as e:
                logger.warning("pdf fetch failed url={} error={}", pdf_url, str(e))
            time.sleep(_REQUEST_DELAY)

        logger.info("unique APNs total={}", len(all_apns))

        for i, apn in enumerate(all_apns):
            attrs = _fetch_parcel(apn, client)
            if attrs:
                prop = _to_property(attrs, apn)
                if prop.get("address"):
                    properties.append(prop)
                else:
                    logger.debug("skipping apn={} no address in sjmap", apn)
            if i > 0 and i % 50 == 0:
                logger.info("sjmap progress {}/{}", i, len(all_apns))
            time.sleep(_REQUEST_DELAY)

    logger.info("scrape_tax_delinquent complete total={}", len(properties))
    return properties
