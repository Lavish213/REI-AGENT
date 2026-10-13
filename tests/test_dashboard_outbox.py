import asyncio
import concurrent.futures
import json
import os
import sqlite3
import subprocess
import sys
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.karpathys import client, emitter, outbox
from backend.lib import db


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / 'dashboard.sqlite3'
    monkeypatch.setenv('KARPATHYS_OUTBOX_PATH', str(path))
    monkeypatch.setattr(client, '_KARPATHYS_URL', 'https://dashboard.example.invalid')
    monkeypatch.setattr(client, '_KARPATHYS_SECRET', 'synthetic-only')
    monkeypatch.setattr(db, '_get_client', lambda: (_ for _ in ()).throw(AssertionError('No Supabase dependency for journal recovery')))
    return path


def stage(endpoint='call', sid='provider-1', **extra):
    return db.stage_dashboard_event(endpoint, {'call_sid': sid, **extra}, client.delivery_target())


def receipt(sid='provider-1'):
    return {'schema_version': 1, 'persisted': True, 'receipt_id': 'synthetic-receipt', 'call_sid': sid}


def change(path, sql, params=()):
    with sqlite3.connect(path) as connection:
        connection.execute(sql, params)


def test_journal_is_durable_and_replay_safe(journal):
    first = stage(occurred_at='first')
    assert stage(occurred_at='later') == first
    assert db.dashboard_event_journal_health()['pending'] == 1
    claimed = db.claim_dashboard_event(client.delivery_target())
    assert claimed['event_id'] == first
    assert db.finish_dashboard_event(first, claimed['lease'], receipt())
    assert stage(occurred_at='later-again') == first
    assert db.dashboard_event_journal_health()['delivered'] == 1
    with sqlite3.connect(journal) as connection:
        row = connection.execute('select payload,receipt from dashboard_events').fetchone()
    assert row[0] == '{}'
    assert json.loads(row[1])['receipt_id'] == 'synthetic-receipt'
    assert journal.stat().st_mode & 0o777 == 0o600


def test_conflicting_replays_are_visible_and_preserve_original(journal):
    stage(lead_id='original')
    with pytest.raises(ValueError, match='Conflicting'):
        stage(lead_id='wrong')
    assert db.claim_dashboard_event(client.delivery_target())['payload']['lead_id'] == 'original'


def test_call_creation_precedes_early_turn_and_only_one_event_per_call_is_leased(journal):
    turn = stage('turn', speaker='user', text='Please call later', turn_index=0)
    assert db.claim_dashboard_event(client.delivery_target()) is None
    root = stage()
    claimed = db.claim_dashboard_event(client.delivery_target())
    assert claimed['event_id'] == root
    assert db.claim_dashboard_event(client.delivery_target()) is None
    db.finish_dashboard_event(root, claimed['lease'], receipt())
    claimed = db.claim_dashboard_event(client.delivery_target())
    assert claimed['event_id'] == turn


def test_same_call_event_order_blocks_due_later_events_during_retry(journal):
    stage()
    root = db.claim_dashboard_event(client.delivery_target())
    db.finish_dashboard_event(root['event_id'], root['lease'], receipt())
    stage('turn', speaker='user', text='Hello', turn_index=0)
    stage('complete')
    turn = db.claim_dashboard_event(client.delivery_target())
    db.finish_dashboard_event(turn['event_id'], turn['lease'], None)
    assert db.claim_dashboard_event(client.delivery_target()) is None


def test_unrelated_call_can_progress_during_another_calls_retry(journal):
    stage()
    first = db.claim_dashboard_event(client.delivery_target())
    db.finish_dashboard_event(first['event_id'], first['lease'], None)
    second = stage(sid='provider-2')
    assert db.claim_dashboard_event(client.delivery_target())['event_id'] == second


def test_expired_owner_cannot_acknowledge_reclaimed_event(journal):
    stage()
    old = db.claim_dashboard_event(client.delivery_target())
    change(journal, 'update dashboard_events set leased_until=0')
    new = db.claim_dashboard_event(client.delivery_target())
    assert new['lease'] != old['lease']
    assert not db.finish_dashboard_event(old['event_id'], old['lease'], receipt())
    assert db.finish_dashboard_event(new['event_id'], new['lease'], receipt())


@pytest.mark.parametrize('body', [{}, {'persisted': False}, {'schema_version': True, 'persisted': True, 'receipt_id': 'r', 'call_sid': 'provider-1'}, {'schema_version': 1, 'persisted': True, 'receipt_id': 'r', 'call_sid': 'wrong'}, {'schema_version': 1, 'persisted': True, 'receipt_id': '', 'call_sid': 'provider-1'}])
def test_invalid_acknowledgements_never_delete_or_deliver(journal, body):
    stage()
    event = db.claim_dashboard_event(client.delivery_target())
    with pytest.raises(ValueError):
        db.finish_dashboard_event(event['event_id'], event['lease'], body)
    assert db.dashboard_event_journal_health()['pending'] == 1


def test_expired_event_and_orphaned_turn_remain_visible_for_operator(journal):
    stage('turn', speaker='user', text='Hello', turn_index=0)
    change(journal, 'update dashboard_events set expires=0')
    assert db.claim_dashboard_event(client.delivery_target()) is None
    health = db.dashboard_event_journal_health()
    assert health['dead'] == 1 and health['errors']['delivery_expired'] == 1
    assert health['failed_events'][0]['endpoint'] == 'turn'


def test_dead_call_blocks_dependent_events_and_can_be_explicitly_retried(journal):
    root = stage()
    stage('ended')
    event = db.claim_dashboard_event(client.delivery_target())
    db.finish_dashboard_event(root, event['lease'], None, 'payload_rejected', True)
    assert db.claim_dashboard_event(client.delivery_target()) is None
    assert db.dashboard_event_journal_health()['dead'] == 2
    assert db.retry_dashboard_event(root, client.delivery_target())
    assert not db.retry_dashboard_event(root, client.delivery_target())
    assert db.claim_dashboard_event(client.delivery_target())['event_id'] == root


def test_destination_change_never_forwards_stored_payload_to_new_server(journal):
    key = stage()
    other = 'f' * 64
    assert db.claim_dashboard_event(other) is None
    assert db.dashboard_event_journal_health()['errors']['destination_changed'] == 1
    assert not db.retry_dashboard_event(key, other)
    assert db.retry_dashboard_event(key, client.delivery_target())


def test_multithread_producers_deduplicate_actual_sqlite(journal):
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        keys = list(pool.map(lambda _: stage(), range(100)))
    assert len(set(keys)) == 1
    assert db.dashboard_event_journal_health()['pending'] == 1


def test_many_workers_lease_distinct_events_without_duplicate_ownership(journal):
    for number in range(64):
        stage(sid=f'provider-{number}')
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(pool.map(lambda _: db.claim_dashboard_event(client.delivery_target()), range(128)))
    ids = [row['event_id'] for row in rows if row]
    assert len(ids) == len(set(ids)) == 64
    assert db.dashboard_event_journal_health()['leased'] == 64


def test_process_exit_after_commit_preserves_event_for_next_process(journal):
    code = "from backend.lib.db import stage_dashboard_event; import os; stage_dashboard_event('call', {'call_sid': 'crash-call'}, 'a'*64); os._exit(7)"
    result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ), capture_output=True, timeout=15)
    assert result.returncode == 7, result.stderr.decode()
    event = db.claim_dashboard_event('a' * 64)
    assert event['call_sid'] == 'crash-call'


@pytest.mark.asyncio
async def test_emitter_only_stages_and_never_waits_for_http(journal, monkeypatch):
    send = AsyncMock(side_effect=AssertionError('Producer must not perform HTTP'))
    monkeypatch.setattr(client, 'send_event', send)
    assert await emitter.emit_call_created('provider-1', {'lead': {'id': 'external-lead'}})
    send.assert_not_awaited()
    assert db.dashboard_event_journal_health()['pending'] == 1


@pytest.mark.asyncio
async def test_worker_outage_retains_event_then_restarts_and_delivers(journal, monkeypatch):
    stage()
    send = AsyncMock(side_effect=[{'receipt': None, 'error': 'transport_unavailable', 'permanent': False}, {'receipt': receipt(), 'error': None, 'permanent': False}])
    monkeypatch.setattr(client, 'send_event', send)
    assert (await outbox.recover_events())['retrying'] == 1
    assert db.dashboard_event_journal_health()['pending'] == 1
    assert (await outbox.recover_events())['delivered'] == 0
    change(journal, 'update dashboard_events set due=0')
    assert (await outbox.recover_events())['delivered'] == 1
    assert db.dashboard_event_journal_health()['pending'] == 0


@pytest.mark.asyncio
async def test_crash_after_server_ack_replays_identically_after_lease_expiry(journal, monkeypatch):
    stage()
    requests = []
    async def send(endpoint, payload):
        requests.append((endpoint, payload))
        return {'receipt': receipt(), 'error': None, 'permanent': False}
    monkeypatch.setattr(client, 'send_event', send)
    original = db.finish_dashboard_event
    def crash(*args, **kwargs):
        raise OSError('synthetic process loss')
    monkeypatch.setattr(db, 'finish_dashboard_event', crash)
    with pytest.raises(OSError):
        await outbox.recover_events(1)
    monkeypatch.setattr(db, 'finish_dashboard_event', original)
    change(journal, 'update dashboard_events set leased_until=0')
    assert (await outbox.recover_events(1))['delivered'] == 1
    assert requests[0] == requests[1]


@pytest.mark.asyncio
async def test_permanent_rejection_is_visible_not_infinite_retry(journal, monkeypatch):
    stage()
    monkeypatch.setattr(client, 'send_event', AsyncMock(return_value={'receipt': None, 'error': 'payload_rejected', 'permanent': True}))
    assert (await outbox.recover_events())['dead'] == 1
    assert db.dashboard_event_journal_health()['dead'] == 1


@pytest.mark.asyncio
async def test_worker_cancellation_keeps_owned_event_for_lease_recovery(journal, monkeypatch):
    stage()
    monkeypatch.setattr(client, 'send_event', AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await outbox.recover_events()
    assert db.dashboard_event_journal_health()['pending'] == 1
    assert db.dashboard_event_journal_health()['leased'] == 1


@pytest.mark.asyncio
async def test_missing_journal_fails_configured_startup(monkeypatch):
    monkeypatch.delenv('KARPATHYS_OUTBOX_PATH', raising=False)
    monkeypatch.setattr(client, '_KARPATHYS_URL', 'https://dashboard.example.invalid')
    monkeypatch.setattr(client, '_KARPATHYS_SECRET', 'synthetic')
    with pytest.raises(RuntimeError, match='persistent path'):
        await outbox.start_recovery()


@pytest.mark.asyncio
async def test_disabled_bridge_starts_no_worker(monkeypatch):
    monkeypatch.setattr(client, '_KARPATHYS_URL', '')
    assert await outbox.start_recovery() is None


@pytest.mark.parametrize('url', ['https://user:secret@example.invalid', 'https://example.invalid/path', 'https://example.invalid?secret=x', 'file:///tmp/events', 'http://public.example.invalid'])
def test_invalid_destination_rejected_before_persistence(journal, monkeypatch, url):
    monkeypatch.setattr(client, '_KARPATHYS_URL', url)
    monkeypatch.delenv('KARPATHYS_ALLOW_INSECURE_INTERNAL_HTTP', raising=False)
    with pytest.raises(ValueError):
        client.delivery_target()
    assert not journal.exists()


def test_private_journal_rejects_symlink(journal, tmp_path, monkeypatch):
    target = tmp_path / 'real.sqlite3'
    target.touch()
    journal.symlink_to(target)
    with pytest.raises(RuntimeError, match='non-symlink'):
        stage()


def test_dead_payload_and_health_do_not_expose_secrets(journal):
    stage()
    event = db.claim_dashboard_event(client.delivery_target())
    db.finish_dashboard_event(event['event_id'], event['lease'], None, 'password=private', True)
    health = json.dumps(db.dashboard_event_journal_health())
    assert 'password' not in health and 'synthetic-only' not in health
    assert db.dashboard_event_journal_health()['errors']['worker_failed'] == 1
