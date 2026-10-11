from __future__ import annotations
import argparse
import time
from datetime import datetime, timezone
from loguru import logger
from backend.lib import db


def integration_status(shared, local, interval_seconds=300):
    worker = shared.get('worker') or {}
    try:
        completed = datetime.fromisoformat(worker['completed_at'].replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc)-completed).total_seconds()
        healthy_worker = completed.tzinfo is not None and 0 <= age <= interval_seconds*2+60 and worker.get('errors') == 0
    except (KeyError, ValueError, TypeError, AttributeError):
        healthy_worker = False
    if not healthy_worker or shared.get('quarantined_jobs', 0) or shared.get('dead_events', 0) or shared.get('stale_briefs', 0) or local.get('dead', 0) or local.get('oldest_pending_seconds', 0) > 120:
        return 'degraded'
    return 'ok'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--health', action='store_true')
    args = parser.parse_args()
    if args.health:
        shared, local = db.bob_integration_health(), db.bob_fact_journal_health()
        state = integration_status(shared, local)
        logger.info('bob_integration_health status={} shared={} journal={}', state, shared, local)
        return int(state != 'ok')
    while True:
        try:
            result = db.flush_bob_call_fact_outbox()
            logger.info('bob_fact_recovery results={}', result)
        except Exception as error:
            logger.error('bob_fact_recovery_failed type={}', type(error).__name__)
            if args.once:
                return 1
        else:
            if args.once:
                return int(bool(result['failed'] or result['expired']))
        time.sleep(30)


if __name__ == '__main__':
    raise SystemExit(main())
