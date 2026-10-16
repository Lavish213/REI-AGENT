from __future__ import annotations

import asyncio
import os
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

from backend.lib import db

router = APIRouter()


@router.get('/operations/integration')
async def integration(challenge: UUID):
    from backend.karpathys.connections import inspect_connections
    return await inspect_connections(str(challenge))


@router.post('/ingest/bob/brief-created')
async def brief_created(payload: dict, idempotency_key: str = Header(default='')):
    try:
        UUID(idempotency_key)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail='Invalid event key')
    if payload.get('event_id') != idempotency_key or payload.get('tenant_id') != os.environ.get('TENANT_ID', '00000000-0000-0000-0000-000000000001') or payload.get('event_type') != 'call_brief_created' or payload.get('schema_version') != '2.0':
        raise HTTPException(status_code=422, detail='Invalid event binding')
    try:
        accepted = await asyncio.to_thread(db.accept_bob_brief_event, idempotency_key, payload)
    except Exception:
        raise HTTPException(status_code=503, detail='Event persistence unavailable')
    if not accepted:
        raise HTTPException(status_code=409, detail='Event does not match committed Bob output')
    return {'status': 'persisted', 'event_id': idempotency_key}


@router.get('/bob/health')
async def health():
    try:
        shared = await asyncio.to_thread(db.bob_integration_health)
        local = await asyncio.to_thread(db.bob_fact_journal_health)
    except Exception:
        raise HTTPException(status_code=503, detail='Bob integration unavailable')
    from backend.voice.bob_recovery import integration_status
    return {'status': integration_status(shared, local), 'shared': shared, 'facts': local}


@router.get('/operations/delivery')
async def provider_delivery_overview():
    import asyncio
    from fastapi import HTTPException
    from backend.lib import db
    try:
        return await asyncio.to_thread(db.delivery_overview)
    except Exception as error:
        raise HTTPException(503, 'Provider delivery evidence unavailable') from error
