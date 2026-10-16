import asyncio
import os
import re
import sqlite3
from uuid import UUID

import httpx
from loguru import logger
from postgrest.exceptions import APIError

from backend.karpathys import client
from backend.lib import db
from backend.voice.bob_recovery import integration_status


async def inspect_connections(challenge):
    challenge = str(UUID(challenge))
    tenant = str(UUID(os.environ.get('TENANT_ID') or '00000000-0000-0000-0000-000000000001'))
    bob = 'unavailable'
    try:
        shared, facts = await asyncio.wait_for(asyncio.gather(asyncio.to_thread(db.bob_integration_health), asyncio.to_thread(db.bob_fact_journal_health)), timeout=3)
        bob = integration_status(shared, facts)
    except (RuntimeError, ValueError, TypeError, AttributeError, KeyError, OSError, APIError, sqlite3.Error) as error:
        logger.warning('connection_bob_unavailable type={}', type(error).__name__)
    dashboard = {'status': 'unconfigured', 'receiver_id': None}
    try:
        if client.delivery_target() is not None:
            async with httpx.AsyncClient(timeout=3, follow_redirects=False) as transport:
                response = await transport.get(client._KARPATHYS_URL + '/api/v1/ingest/connection', params={'challenge': challenge}, headers={'X-Karpathys-Secret': client._KARPATHYS_SECRET})
            data = response.json() if response.is_success else {}
            if type(data.get('schema_version')) is not int or data.get('schema_version') != 1 or data.get('service') != 'karpathys-dashboard' or data.get('challenge') != challenge or data.get('source_tenant_id') != tenant or not isinstance(data.get('receiver_id'), str) or not re.fullmatch('[a-f0-9]{64}', data['receiver_id']):
                dashboard['status'] = 'invalid_receipt'
            else:
                dashboard = {'status': 'ok', 'receiver_id': data['receiver_id']}
    except (RuntimeError, ValueError, TypeError, AttributeError, KeyError, OSError, httpx.HTTPError) as error:
        dashboard['status'] = 'unavailable'
        logger.warning('connection_dashboard_unavailable type={}', type(error).__name__)
    journal = 'unavailable'
    try:
        delivery = await asyncio.wait_for(asyncio.to_thread(db.dashboard_event_journal_health), timeout=1)
        journal = 'ok' if delivery['dead'] == 0 and delivery['oldest_pending_seconds'] <= 300 else 'degraded'
    except (RuntimeError, ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
        logger.warning('connection_journal_unavailable type={}', type(error).__name__)
    return {'schema_version': 1, 'service': 'rei-sophia', 'challenge': challenge, 'tenant_id': tenant, 'bob': bob, 'dashboard': dashboard, 'dashboard_journal': journal, 'background_jobs_enabled': os.environ.get('ENABLE_BACKGROUND_JOBS', 'false').lower() == 'true', 'outbound_enabled': os.environ.get('OUTBOUND_ENABLED', 'false').lower() == 'true'}
