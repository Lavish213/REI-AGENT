import os
import time
import schedule
from datetime import datetime, timezone
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from backend.lib.db import (
    upsert_property,
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


def run_scout() -> dict:
    from backend.lib import db
    report = {'status': 'ok', 'upserted': 0, 'leads_created': 0, 'alerts_accepted': 0, 'alerts_failed': 0, 'record_errors': 0, 'contact_errors': 0}
    csv_path = _get_latest_csv()
    if not csv_path:
        return {**report, 'status': 'unconfigured'}
    scored = score_properties(parse_csv(csv_path))
    if not scored:
        return {**report, 'status': 'empty'}
    for original in scored:
        prop = dict(original)
        try:
            property_id = upsert_property(prop)
            if not property_id or prop.get('id') != property_id:
                raise RuntimeError('Property persistence unconfirmed')
            report['upserted'] += 1
            if prop['distress_score'] < MIN_ALERT_SCORE or get_lead_by_property(property_id):
                continue
            lead_id = insert_lead(property_id)
            if not lead_id:
                raise RuntimeError('Lead persistence unconfirmed')
            report['leads_created'] += 1
        except Exception as error:
            report['record_errors'] += 1
            logger.warning('scout_record_failed type={}', type(error).__name__)
            continue
        csv_phone = prop.pop('_owner_phone', None)
        prop.pop('_owner_phone_2', None)
        csv_email = prop.pop('_owner_email', None)
        if csv_phone or csv_email:
            try:
                db.store_imported_lead_contacts(lead_id, csv_phone, csv_email)
            except Exception as error:
                report['contact_errors'] += 1
                logger.warning('scout_contact_failed type={}', type(error).__name__)
        if ALERT_PHONE:
            try:
                accepted = send_sms(to=ALERT_PHONE, body=format_lead_alert(prop))
            except Exception as error:
                accepted = False
                logger.warning('scout_alert_failed type={}', type(error).__name__)
            report['alerts_accepted' if accepted else 'alerts_failed'] += 1
        try:
            from backend.alerts.speed_to_lead import run_speed_to_lead
            run_speed_to_lead(lead_id)
        except Exception as error:
            logger.warning('scout_speed_to_lead_failed type={}', type(error).__name__)
        if os.environ.get('REALESTATEAPI_KEY'):
            try:
                from backend.lib.batchdata import enrich_lead_realestateapi
                enrich_lead_realestateapi(lead_id)
            except Exception as error:
                logger.warning('scout_enrichment_failed type={}', type(error).__name__)
    if report['record_errors'] or report['contact_errors'] or report['alerts_failed']:
        report['status'] = 'partial'
    logger.info('scout_run_result result={}', report)
    return report


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


def run_scout_cycle() -> None:
    logger.info('scout_cycle starting')
    for source in (run_scout, run_rss_scraper, run_expired_scraper, run_social_scraper, run_eviction_scraper, run_crmls_scraper):
        try:
            source()
        except Exception as error:
            logger.warning('scout_source_failed source={} type={}', source.__name__, type(error).__name__)
    logger.info('scout_cycle complete')
