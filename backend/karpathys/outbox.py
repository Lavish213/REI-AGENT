import asyncio

from loguru import logger

from backend.karpathys import client
from backend.lib import db


async def enqueue_event(endpoint, payload):
    target = client.delivery_target()
    if target is None:
        return False
    event_id = await asyncio.to_thread(db.stage_dashboard_event, endpoint, payload, target)
    logger.debug("dashboard_event_queued event_id={} endpoint={}", event_id, endpoint)
    return True


async def recover_events(limit=20):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid dashboard recovery batch")
    target = client.delivery_target()
    result = {"delivered": 0, "retrying": 0, "dead": 0, "unowned": 0}
    if target is None:
        return result
    for _ in range(limit):
        event = await asyncio.to_thread(db.claim_dashboard_event, target)
        if event is None:
            break
        try:
            outcome = await client.send_event(event["endpoint"], event["payload"])
            saved = await asyncio.to_thread(db.finish_dashboard_event, event["event_id"], event["lease"], outcome["receipt"], outcome["error"], outcome["permanent"])
            key = "unowned" if not saved else "delivered" if outcome["receipt"] else "dead" if outcome["permanent"] else "retrying"
            result[key] += 1
            if key != "delivered":
                logger.warning("dashboard_event_delivery event_id={} state={}", event["event_id"], key)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("dashboard_event_worker_failed event_id={} type={}", event["event_id"], type(error).__name__)
            await asyncio.to_thread(db.finish_dashboard_event, event["event_id"], event["lease"], None, "worker_failed")
            result["retrying"] += 1
    return result


async def recovery_loop():
    cycles = 0
    refresh_offset = 0
    while True:
        try:
            if cycles % 12 == 0:
                try:
                    from backend.karpathys.business import publish_business
                    lead_ids = await asyncio.to_thread(db.dashboard_lead_refresh_ids, refresh_offset)
                    refresh_offset = refresh_offset + 100 if len(lead_ids) == 100 else 0
                    for lead_id in lead_ids:
                        await publish_business('lead:' + lead_id, lead_id)
                except Exception as error:
                    logger.warning("business_refresh_failed type={}", type(error).__name__)
            cycles += 1
            await recover_events()
            health = await asyncio.to_thread(db.dashboard_event_journal_health)
            if health["dead"] or health["oldest_pending_seconds"] > 300:
                logger.warning("dashboard_delivery_degraded pending={} dead={} oldest_seconds={}", health["pending"], health["dead"], int(health["oldest_pending_seconds"]))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("dashboard_delivery_recovery_failed type={}", type(error).__name__)
        await asyncio.sleep(5)


async def start_recovery():
    if client.delivery_target() is None:
        return None
    await asyncio.to_thread(db.dashboard_event_journal_health)
    return asyncio.create_task(recovery_loop())
