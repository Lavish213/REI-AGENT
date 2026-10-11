from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import sqlite3
import concurrent.futures
import pytest
from backend.lib import db
from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor
from backend.voice.bob_recovery import integration_status

LEAD = '11111111-1111-1111-1111-111111111111'
TENANT = '00000000-0000-0000-0000-000000000001'


def fact(confirmed=True):
    return {'right_person': {'confirmed': confirmed, 'source': 'transcript_verified', 'verified_at': datetime.now(timezone.utc).isoformat(), 'call_sid': 'call-1'}}


@pytest.fixture
def spool(tmp_path, monkeypatch):
    path = tmp_path/'facts.sqlite3'
    monkeypatch.setenv('VOICE_FACT_OUTBOX_PATH', str(path))
    monkeypatch.setenv('TENANT_ID', TENANT)
    return path


def test_journal_survives_connection_restart_and_only_ack_deletes(spool, monkeypatch):
    item = fact()
    key = db.stage_bob_call_facts(LEAD, 'call-1', item)
    assert db.stage_bob_call_facts(LEAD, 'call-1', item) == key
    assert db.bob_fact_journal_health()['pending'] == 1
    client = MagicMock()
    client.rpc.return_value.execute.return_value.data = False
    monkeypatch.setattr(db, '_get_client', lambda: client)
    assert db.flush_bob_call_fact_outbox()['failed'] == 1
    assert db.bob_fact_journal_health()['pending'] == 1
    connection = sqlite3.connect(spool)
    connection.execute('UPDATE facts SET due=0')
    connection.commit()
    connection.close()
    client.rpc.return_value.execute.return_value.data = True
    assert db.flush_bob_call_fact_outbox()['delivered'] == 1
    assert client.rpc.call_args.args[1]['p_event_id'] == key
    assert db.bob_fact_journal_health()['pending'] == 0
    assert spool.stat().st_mode & 0o777 == 0o600


def test_concurrent_spooling_deduplicates_actual_sqlite(spool):
    item = fact()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _: db.stage_bob_call_facts(LEAD, 'call-1', item), range(32)))
    assert len(set(keys)) == 1
    assert db.bob_fact_journal_health()['pending'] == 1


def test_outage_retains_facts_without_losing_newer_denial(spool, monkeypatch):
    db.stage_bob_call_facts(LEAD, 'call-1', fact())
    db.stage_bob_call_facts(LEAD, 'call-1', fact(False))
    client = MagicMock()
    client.rpc.return_value.execute.side_effect = TimeoutError('offline')
    monkeypatch.setattr(db, '_get_client', lambda: client)
    assert db.flush_bob_call_fact_outbox()['failed'] == 2
    assert db.bob_fact_journal_health()['pending'] == 2


def test_journal_tenant_boundary(spool, monkeypatch):
    db.stage_bob_call_facts(LEAD, 'call-1', fact())
    monkeypatch.setenv('TENANT_ID', '00000000-0000-0000-0000-000000000002')
    client = MagicMock()
    monkeypatch.setattr(db, '_get_client', lambda: client)
    assert db.flush_bob_call_fact_outbox()['delivered'] == 0
    client.rpc.assert_not_called()
    assert db.bob_fact_journal_health()['pending'] == 0


@pytest.mark.parametrize('key,value', [('confirmed', 1), ('source', 'inferred'), ('call_sid', 'other'), ('verified_at', 'bad'), ('verified_at', datetime.now().isoformat()), ('verified_at', (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())])
def test_bad_facts_never_enter_journal(spool, key, value):
    item = fact()
    item['right_person'][key] = value
    with pytest.raises((ValueError, TypeError)):
        db.stage_bob_call_facts(LEAD, 'call-1', item)


def test_expired_undelivered_fact_is_visible_dead_letter(spool, monkeypatch):
    import json
    db.stage_bob_call_facts(LEAD, 'call-1', fact())
    item = fact()
    item['right_person']['verified_at'] = (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    connection = sqlite3.connect(spool)
    connection.execute('UPDATE facts SET payload=?', (json.dumps(item),))
    connection.commit()
    connection.close()
    client = MagicMock()
    monkeypatch.setattr(db, '_get_client', lambda: client)
    assert db.flush_bob_call_fact_outbox()['expired'] == 1
    client.rpc.assert_not_called()
    assert db.bob_fact_journal_health()['dead'] == 1


def test_unrelated_turn_does_not_refresh_old_evidence():
    ctx = CallContext()
    ctx._call_sid = 'call-1'
    tracker = ContextTrackerProcessor(ctx)
    tracker._analyze('I own the property. I am relocating.')
    before = dict(ctx.bob_verified_facts)
    tracker._analyze('Can you repeat that?')
    assert ctx.bob_verified_facts == before


def test_wrong_address_cannot_rebind_canonical_property():
    ctx = CallContext()
    ctx._call_sid = 'call-1'
    ctx.property_address = '123 Main Street'
    tracker = ContextTrackerProcessor(ctx)
    tracker._analyze('The house at 999 Other Street')
    tracker._analyze('The house at 999 Other Street')
    assert ctx.property_address == '123 Main Street'
    assert 'property_confirmed' not in ctx.bob_verified_facts


@pytest.mark.parametrize('fault', ['worker', 'quarantined_jobs', 'dead_events', 'stale_briefs', 'dead_facts', 'old_facts'])
def test_health_exposes_missing_heartbeat_and_queues(fault):
    shared = {'worker': {'completed_at': datetime.now(timezone.utc).isoformat(), 'errors': 0}}
    local = {}
    assert integration_status(shared, local) == 'ok'
    if fault == 'worker':
        shared['worker'] = None
    elif fault == 'dead_facts':
        local['dead'] = 1
    elif fault == 'old_facts':
        local['oldest_pending_seconds'] = 121
    else:
        shared[fault] = 1
    assert integration_status(shared, local) == 'degraded'


@pytest.mark.asyncio
async def test_journal_processor_keeps_voice_frame_flowing_when_disk_is_busy(monkeypatch):
    import asyncio
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from backend.voice.processors.bob_fact_journal import BobFactJournalProcessor
    ctx = CallContext()
    ctx.lead_id, ctx._call_sid, ctx.bob_verified_facts = LEAD, 'call-1', fact()
    processor = BobFactJournalProcessor(ctx)
    delivered = []
    async def push(frame, direction):
        delivered.append(frame)
    processor.push_frame = push
    from threading import Event
    disk_busy = Event()
    monkeypatch.setattr(db, 'stage_bob_call_facts', lambda *args: disk_busy.wait(2))
    monkeypatch.setattr(db, 'flush_bob_call_fact_outbox', lambda *args: {})
    frame = TranscriptionFrame('hello', 'u', 'now')
    await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
    assert delivered == [frame]
    disk_busy.set()
    await asyncio.wait_for(processor._writer, 2)
    assert processor._saved == ctx.bob_verified_facts


@pytest.mark.parametrize('secret,supplied,code', [('', '', 401), ('expected', '', 401), ('expected', 'wrong', 401), ('expected', 'expected', 200)])
def test_bob_receipt_route_service_auth_and_persisted_ack(monkeypatch, secret, supplied, code):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    monkeypatch.setenv('KARPATHYS_WEBHOOK_SECRET', secret)
    monkeypatch.setenv('ENABLE_BACKGROUND_JOBS', 'false')
    monkeypatch.setattr(db, 'accept_bob_brief_event', lambda *args: True)
    key = '33333333-3333-3333-3333-333333333333'
    payload = {'event_id': key, 'tenant_id': TENANT, 'event_type': 'call_brief_created', 'schema_version': '2.0'}
    response = TestClient(app).post('/api/ingest/bob/brief-created', json=payload, headers={'X-Karpathys-Secret': supplied, 'Idempotency-Key': key})
    assert response.status_code == code
    if code == 200:
        assert response.json() == {'status': 'persisted', 'event_id': key}


@pytest.mark.parametrize('result,code', [(False, 409), (RuntimeError('offline'), 503)])
def test_bob_receipt_never_acknowledges_unpersisted_event(monkeypatch, result, code):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    monkeypatch.setenv('KARPATHYS_WEBHOOK_SECRET', 'expected')
    monkeypatch.setenv('ENABLE_BACKGROUND_JOBS', 'false')
    def accept(*args):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(db, 'accept_bob_brief_event', accept)
    key = '33333333-3333-3333-3333-333333333333'
    payload = {'event_id': key, 'tenant_id': TENANT, 'event_type': 'call_brief_created', 'schema_version': '2.0'}
    response = TestClient(app).post('/api/ingest/bob/brief-created', json=payload, headers={'X-Karpathys-Secret': 'expected', 'Idempotency-Key': key})
    assert response.status_code == code


def test_bob_health_is_operator_protected(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    monkeypatch.delenv('OPERATOR_API_TOKEN', raising=False)
    assert TestClient(app).get('/api/bob/health').status_code == 401


@pytest.mark.parametrize('text', ['If I own the property, could you buy it?', 'My neighbor is moving next month.', 'Maybe the house needs repairs.', 'Does the roof need repairs?', 'What does foreclosure mean?', 'The tenant is great.'])
def test_questions_and_hypotheticals_are_not_verified_checklist_facts(text):
    ctx = CallContext()
    ctx._call_sid = 'call-1'
    ContextTrackerProcessor(ctx)._analyze(text)
    assert not any(item['confirmed'] for item in ctx.bob_verified_facts.values())


@pytest.mark.asyncio
@pytest.mark.parametrize('text,confirmed', [('Yes I can hear you', False), ('This is a bad time', False), ('yes', True), ('Yeah, speaking', True)])
async def test_hearing_confirmation_is_not_owner_identity(text, confirmed):
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    ctx = CallContext()
    ctx.is_outbound = True
    ctx.awaiting_owner_confirmation = True
    ctx._call_sid = 'call-1'
    processor = ContextTrackerProcessor(ctx)
    async def push(*args):
        return None
    processor.push_frame = push
    await processor.process_frame(TranscriptionFrame(text, 'u', 'now'), FrameDirection.DOWNSTREAM)
    assert ctx.owner_confirmed is confirmed
    assert ('right_person' in ctx.bob_verified_facts) is confirmed


@pytest.mark.asyncio
async def test_fact_recovery_starts_with_campaign_jobs_disabled(spool, monkeypatch):
    import asyncio
    from backend.api import main
    from fastapi import FastAPI
    monkeypatch.setenv('ENABLE_BACKGROUND_JOBS', 'false')
    flushed = []
    monkeypatch.setattr(main, '_flush_bob_facts', lambda: flushed.append(True))
    async with main.lifespan(FastAPI()):
        for _ in range(20):
            if flushed:
                break
            await asyncio.sleep(.01)
        assert flushed


def test_hard_process_exit_after_commit_preserves_journal(spool):
    import subprocess
    import sys
    code = "import os;from backend.lib import db;from datetime import datetime,timezone;db.stage_bob_call_facts('"+LEAD+"','call-1',{'condition':{'confirmed':True,'source':'transcript_verified','verified_at':datetime.now(timezone.utc).isoformat(),'call_sid':'call-1'}});os._exit(23)"
    result = subprocess.run([sys.executable, '-c', code], timeout=10)
    assert result.returncode == 23
    assert db.bob_fact_journal_health()['pending'] == 1


def test_crash_during_delivery_retains_owned_row_for_replay(spool, monkeypatch):
    import subprocess
    import sys
    code = "import os;from backend.lib import db;from datetime import datetime,timezone;db.stage_bob_call_facts('"+LEAD+"','call-1',{'condition':{'confirmed':True,'source':'transcript_verified','verified_at':datetime.now(timezone.utc).isoformat(),'call_sid':'call-1'}});db._get_client=lambda:type('Client',(),{'rpc':lambda *args:type('Request',(),{'execute':lambda *args:os._exit(24)})()})();db.flush_bob_call_fact_outbox()"
    result = subprocess.run([sys.executable, '-c', code], timeout=10)
    assert result.returncode == 24
    client = MagicMock()
    client.rpc.return_value.execute.return_value.data = True
    monkeypatch.setattr(db, '_get_client', lambda: client)
    assert db.flush_bob_call_fact_outbox()['delivered'] == 0
    with sqlite3.connect(spool) as connection:
        key = connection.execute('SELECT id FROM facts').fetchone()[0]
        connection.execute('UPDATE facts SET leased_until=0')
    assert db.flush_bob_call_fact_outbox()['delivered'] == 1
    assert client.rpc.call_args.args[1]['p_event_id'] == key


def test_capacity_failure_retains_existing_evidence(spool):
    key = db.stage_bob_call_facts(LEAD, 'call-1', fact())
    with sqlite3.connect(spool) as connection:
        connection.execute("WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<9999) INSERT INTO facts(id,tenant_id,lead_id,call_sid,payload,created,due) SELECT cast(x as TEXT),?,?,?,'{}',0,0 FROM n", (TENANT, LEAD, 'call-1'))
    with pytest.raises(RuntimeError, match='full'):
        db.stage_bob_call_facts(LEAD, 'call-1', fact(False))
    with sqlite3.connect(spool) as connection:
        assert connection.execute('SELECT count(*) FROM facts').fetchone()[0] == 10000
        assert connection.execute('SELECT 1 FROM facts WHERE id=?', (key,)).fetchone()
