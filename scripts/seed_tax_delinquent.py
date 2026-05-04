import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=False)

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.scout.tax_scraper import scrape_tax_delinquent
from backend.scout.scorer import calculate_distress_score, SCORE_CREATE_LEAD, SCORE_HIGH_PRIORITY, SCORE_DRIP_ONLY
from backend.lib.db import upsert_property, insert_lead, get_lead_by_property


def main() -> None:
    logger.info("seed_tax_delinquent start")

    props = scrape_tax_delinquent()

    if not props:
        logger.warning("no properties scraped — exiting")
        sys.exit(0)

    logger.info("scraped total={}", len(props))

    for prop in props:
        prop["distress_score"] = calculate_distress_score(prop)

    viable = [p for p in props if p.get("deal_viable")]
    disqualified = [p for p in props if not p.get("deal_viable")]

    logger.info("viable={} disqualified={}", len(viable), len(disqualified))

    reason_counts: dict[str, int] = defaultdict(int)
    for p in disqualified:
        raw = p.get("disqualified_reason") or "unknown"
        reason_counts[raw.split(":")[0]] += 1
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        logger.info("disqualified reason={} count={}", reason, count)

    high = [p for p in viable if p["distress_score"] >= SCORE_HIGH_PRIORITY]
    mid = [p for p in viable if SCORE_CREATE_LEAD <= p["distress_score"] < SCORE_HIGH_PRIORITY]
    drip = [p for p in viable if SCORE_DRIP_ONLY <= p["distress_score"] < SCORE_CREATE_LEAD]
    skip = [p for p in viable if p["distress_score"] < SCORE_DRIP_ONLY]
    logger.info(
        "score_dist high={} create_lead={} drip={} skip={}",
        len(high), len(mid), len(drip), len(skip),
    )

    for p in sorted(viable, key=lambda x: x["distress_score"], reverse=True)[:10]:
        logger.info(
            "top apn={} address={} city={} score={}",
            p.get("apn"), p.get("address"), p.get("city"), p.get("distress_score"),
        )

    upserted = 0
    errors = 0
    for prop in props:
        try:
            upsert_property(prop)
            upserted += 1
            if upserted % 50 == 0:
                logger.info("upsert progress {}/{}", upserted, len(props))
        except Exception as e:
            logger.error("upsert failed apn={} error={}", prop.get("apn"), str(e))
            errors += 1

    logger.info("upsert done upserted={} errors={}", upserted, errors)

    from backend.lib.db import _get_client as _db

    lead_eligible = [p for p in viable if p["distress_score"] >= SCORE_CREATE_LEAD]
    leads_created = 0
    leads_skipped = 0

    for prop in lead_eligible:
        try:
            db_row = _db().table("properties").select("id").eq("apn", prop["apn"]).limit(1).execute()
            if not db_row.data:
                logger.warning("property missing after upsert apn={}", prop["apn"])
                continue
            property_id = db_row.data[0]["id"]
            existing = get_lead_by_property(property_id)
            if existing:
                leads_skipped += 1
                continue
            insert_lead(property_id)
            leads_created += 1
            logger.info(
                "lead created apn={} address={} score={}",
                prop["apn"], prop.get("address"), prop["distress_score"],
            )
        except Exception as e:
            logger.error("lead creation failed apn={} error={}", prop.get("apn"), str(e))

    logger.info("leads_created={} leads_skipped={}", leads_created, leads_skipped)
    logger.info("done upserted={} leads_created={}", upserted, leads_created)


if __name__ == "__main__":
    main()
