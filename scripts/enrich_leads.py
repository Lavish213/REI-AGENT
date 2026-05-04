import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=False)

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.lib.batchdata import enrich_lead
from backend.lib.db import _get_client


RATE_LIMIT_DELAY = 0.5
DEFAULT_MIN_SCORE = 35


def _fetch_leads(min_score: int, limit: int | None) -> list[dict]:
    client = _get_client()
    query = (
        client.table("leads")
        .select("*, properties(*)")
        .gte("properties.distress_score", min_score)
        .order("properties(distress_score)", desc=True)
    )
    if limit:
        query = query.limit(limit)
    resp = query.execute()
    return resp.data or []


def _fetch_leads_direct(min_score: int, limit: int | None) -> list[dict]:
    client = _get_client()
    props_query = (
        client.table("properties")
        .select("id, distress_score")
        .gte("distress_score", min_score)
        .order("distress_score", desc=True)
    )
    if limit:
        props_query = props_query.limit(limit)
    props_resp = props_query.execute()
    prop_ids = [p["id"] for p in (props_resp.data or [])]

    if not prop_ids:
        return []

    leads_resp = (
        client.table("leads")
        .select("*, properties(*)")
        .in_("property_id", prop_ids)
        .execute()
    )
    return leads_resp.data or []


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich leads via BatchData")
    parser.add_argument("--limit", type=int, default=None, help="Max leads to enrich")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE, help="Min distress score")
    args = parser.parse_args()

    logger.info("enrich_leads start min_score={} limit={}", args.min_score, args.limit or "all")

    leads = _fetch_leads_direct(args.min_score, args.limit)

    if not leads:
        logger.warning("no leads found with score >= {}", args.min_score)
        sys.exit(0)

    logger.info("leads to enrich total={}", len(leads))

    enriched_count = 0
    phones_found = 0
    dnc_blocked_total = 0
    score_changes: list[tuple[str, int, int]] = []

    for i, lead in enumerate(leads):
        prop = lead.get("properties") or {}
        if not prop:
            logger.warning("lead has no property lead_id={}", lead.get("id"))
            continue

        address = prop.get("address") or "unknown"
        before_score = prop.get("distress_score", 0)

        logger.info(
            "enriching {}/{} lead_id={} address={} city={} score={}",
            i + 1,
            len(leads),
            lead.get("id"),
            address,
            prop.get("city"),
            before_score,
        )

        try:
            result = enrich_lead(lead, prop)
            after_score = result.get("distress_score") or before_score
            callable_phones = result.get("callable_phones") or []
            dnc = result.get("dnc_blocked", False)

            enriched_count += 1
            phones_found += len(callable_phones)
            if dnc:
                dnc_blocked_total += 1

            score_changes.append((address, before_score, after_score))

            logger.info(
                "enriched address={} score={}->{} callable_phones={} dnc_blocked={}",
                address,
                before_score,
                after_score,
                len(callable_phones),
                dnc,
            )
        except Exception as e:
            logger.error("enrich failed lead_id={} address={} error={}", lead.get("id"), address, str(e))

        time.sleep(RATE_LIMIT_DELAY)

    logger.info(
        "enrich_leads done enriched={}/{} phones_found={} dnc_blocked={}",
        enriched_count,
        len(leads),
        phones_found,
        dnc_blocked_total,
    )

    logger.info("--- score changes ---")
    for address, before, after in score_changes:
        delta = after - before
        sign = "+" if delta >= 0 else ""
        logger.info("address={} before={} after={} delta={}{}", address, before, after, sign, delta)


if __name__ == "__main__":
    main()
