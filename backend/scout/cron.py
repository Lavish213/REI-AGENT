import os
import time
import schedule
from datetime import datetime, timezone
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from backend.lib.db import (
    upsert_property,
    get_new_properties_since,
    insert_lead,
    get_lead_by_property,
)
from backend.scout.parser import parse_csv
from backend.scout.scorer import score_properties
from backend.alerts.formatter import format_lead_alert
from backend.alerts.sms import send_sms
from backend.scout.expired import run_expired_scraper
from backend.scout.rss_scraper import run_rss_scraper
from backend.scout.social_scraper import run_social_scraper
from backend.scout.eviction_scraper import run_eviction_scraper
from backend.scout.crmls_scraper import run_crmls_scraper
from backend.alerts.drip import run_daily_drip_triggers


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "data")
MIN_ALERT_SCORE = int(os.environ.get("MIN_DISTRESS_SCORE_FOR_ALERT", 75))
ALERT_PHONE = os.environ.get("ALERT_PHONE", "")
INTERVAL_HOURS = int(os.environ.get("SCOUT_CRON_INTERVAL_HOURS", 6))


def _get_latest_csv() -> str | None:
    if not os.path.exists(DATA_DIR):
        logger.warning("data dir not found: {}", DATA_DIR)
        return None
    csvs = [
        f for f in os.listdir(DATA_DIR)
        if f.endswith(".csv")
    ]
    if not csvs:
        logger.warning("no CSV files found in {}", DATA_DIR)
        return None
    csvs.sort(reverse=True)
    return os.path.join(DATA_DIR, csvs[0])


def run_scout() -> None:
    logger.info("scout run started at {}", datetime.now(timezone.utc).isoformat())

    csv_path = _get_latest_csv()
    if not csv_path:
        logger.error("no CSV to process — drop a Propwire export into scripts/data/")
        return

    logger.info("processing CSV: {}", csv_path)
    properties = parse_csv(csv_path)

    if not properties:
        logger.warning("parser returned 0 properties")
        return

    scored = score_properties(properties)

    upserted = 0
    leads_created = 0
    alerts_sent = 0

    for prop in scored:
        upsert_property(prop)
        upserted += 1

        if prop["distress_score"] >= MIN_ALERT_SCORE:
            existing_lead = get_lead_by_property(prop.get("id", ""))
            if not existing_lead and prop.get("id"):
                lead_id = insert_lead(prop["id"])
                leads_created += 1

                csv_phone = prop.pop("_owner_phone", None)
                csv_phone_2 = prop.pop("_owner_phone_2", None)
                csv_email = prop.pop("_owner_email", None)
                if csv_phone or csv_email:
                    try:
                        from backend.lib.db import _get_client
                        from datetime import datetime, timezone
                        lead_upd = {"updated_at": datetime.now(timezone.utc).isoformat()}
                        if csv_phone:
                            lead_upd["owner_phone"] = csv_phone
                            lead_upd["callable"] = True
                        if csv_email:
                            lead_upd["owner_email"] = csv_email
                        _get_client().table("leads").update(lead_upd).eq("id", lead_id).execute()
                        logger.info("csv_phone_stored lead_id={}", lead_id)
                    except Exception as ph_err:
                        logger.warning("csv_phone_store failed error={}", str(ph_err))

                if ALERT_PHONE:
                    message = format_lead_alert(prop)
                    send_sms(to=ALERT_PHONE, body=message)
                    alerts_sent += 1

                if prop["distress_score"] >= 50:
                    try:
                        from backend.alerts.speed_to_lead import run_speed_to_lead
                        run_speed_to_lead(lead_id)
                        logger.info("speed_to_lead triggered lead_id={} score={}", lead_id, prop["distress_score"])
                    except Exception as e:
                        logger.error("speed_to_lead trigger failed lead_id={} error={}", lead_id, str(e))

                if prop.get("distress_score", 0) >= 35:
                    realestateapi_key = os.environ.get("REALESTATEAPI_KEY")
                    if realestateapi_key:
                        try:
                            from backend.lib.batchdata import enrich_lead_realestateapi
                            lead_id_for_enrich = prop.get("lead_id") or prop.get("id")
                            if lead_id_for_enrich:
                                enrich_lead_realestateapi(lead_id_for_enrich)
                        except Exception as enrich_err:
                            logger.warning("auto_enrichment failed lead_id={} error={}", prop.get("lead_id"), str(enrich_err))

    logger.info(
        "scout run complete upserted={} leads={} alerts={}",
        upserted,
        leads_created,
        alerts_sent
    )


def _safe(fn):
    def wrapped():
        try:
            fn()
        except Exception as e:
            logger.error("scheduler job failed fn={} error={}", fn.__name__, str(e))
    return wrapped


def start_scheduler() -> None:
    logger.info("starting scout scheduler every {} hours", INTERVAL_HOURS)
    schedule.every(INTERVAL_HOURS).hours.do(run_scout)
    schedule.every().day.at("07:00").do(run_expired_scraper)
    schedule.every().day.at("06:00").do(_safe(run_rss_scraper))
    schedule.every().day.at("07:00").do(_safe(run_social_scraper))
    schedule.every().day.at("07:30").do(_safe(run_eviction_scraper))
    schedule.every().day.at("07:00").do(_safe(run_crmls_scraper))
    schedule.every().day.at("08:00").do(_safe(run_daily_drip_triggers))
    run_scout()
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    start_scheduler()
