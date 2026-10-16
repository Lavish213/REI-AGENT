from types import SimpleNamespace

import httpx
import pytest
from backend.alerts import delivery
from backend.api.routes import email_webhook, sms_status
from backend.lib import db
from fastapi import FastAPI


@pytest.fixture
def journal(monkeypatch, tmp_path):
    monkeypatch.setenv('COMMUNICATION_JOURNAL_PATH', str(tmp_path / 'communications.sqlite3'))
    monkeypatch.setenv('WORKFLOW_JOURNAL_PATH', str(tmp_path / 'workflows.sqlite3'))
    monkeypatch.setenv('TENANT_ID', '00000000-0000-0000-0000-000000000001')


def sms(status='sent', message='SM123', recipient='+12095550100'):
    return {'MessageSid': message, 'MessageStatus': status, 'To': recipient}


def email(status='delivered', **extra):
    return {'event': status, 'email': 'seller@example.invalid', 'timestamp': 1792150000, 'sg_message_id': 'sendgrid.internal', 'sg_event_id': status + '-event', **extra}


def bind(channel='sms', lead='00000000-0000-0000-0000-000000000020'):
    recipient = '+12095550100' if channel == 'sms' else 'seller@example.invalid'
    identity, claimed, _ = db.claim_message_intent(channel, recipient, '', 'test')
    assert claimed
    db.bind_delivery_intent(identity, lead, channel, recipient)
    db.accept_message_intent(identity, 'SM123' if channel == 'sms' else 'api-header-id')
    return identity


def test_receipt_persists_through_outage_restart_and_replays_without_resending(journal, monkeypatch):
    bind()
    delivery.accept_events('sms', [sms()])
    delivery.accept_events('sms', [sms()])
    assert db.delivery_event_health()['pending'] == 1
    def unavailable():
        raise RuntimeError('private database details')
    monkeypatch.setattr(db, '_get_client', unavailable)
    assert db.recover_delivery_events()['pending'] == 1
    calls = []
    class Client:
        def rpc(self, name, args):
            assert name == 'apply_delivery_event'
            calls.append(args)
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=args['p_id']))
    monkeypatch.setattr(db, '_get_client', Client)
    assert db.recover_delivery_events()['synced'] == 1
    assert db.recover_delivery_events()['synced'] == 0
    assert len(calls) == 1 and calls[0]['p_lead'].endswith('0020')
    with db._delivery_journal() as connection:
        assert connection.execute('select error from delivery_events').fetchone()[0] is None


def test_lost_database_ack_replays_identical_event(journal, monkeypatch):
    bind()
    delivery.accept_events('sms', [sms('delivered')])
    calls = []
    class Client:
        def rpc(self, name, args):
            calls.append(args)
            def execute():
                if len(calls) == 1:
                    raise RuntimeError('ACK lost after commit')
                return SimpleNamespace(data=args['p_id'])
            return SimpleNamespace(execute=execute)
    monkeypatch.setattr(db, '_get_client', Client)
    assert db.recover_delivery_events()['pending'] == 1
    assert db.recover_delivery_events()['pending'] == 0
    assert calls[0] == calls[1]


def test_email_uses_bound_custom_argument_not_api_header_or_untrusted_lead(journal, monkeypatch):
    identity = bind('email')
    delivery.accept_events('email', [email(communication_intent=identity, lead_id='untrusted-lead')])
    seen = []
    class Client:
        def rpc(self, name, args):
            seen.append(args)
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=args['p_id']))
    monkeypatch.setattr(db, '_get_client', Client)
    assert db.recover_delivery_events()['synced'] == 1
    assert seen[0]['p_lead'].endswith('0020')


@pytest.mark.parametrize('fault', ['unknown', 'wrong_recipient', 'wrong_channel', 'wrong_tenant'])
def test_unbound_callbacks_never_change_arbitrary_leads(journal, monkeypatch, fault):
    identity = bind('email')
    data = email(communication_intent='f' * 64 if fault == 'unknown' else identity, email='different@example.invalid' if fault == 'wrong_recipient' else 'seller@example.invalid')
    if fault == 'wrong_channel':
        data = sms()
    if fault == 'wrong_tenant':
        monkeypatch.setenv('TENANT_ID', '00000000-0000-0000-0000-000000000002')
    delivery.accept_events('sms' if fault == 'wrong_channel' else 'email', [data])
    monkeypatch.setattr(db, '_get_client', lambda: pytest.fail('Unbound callback reached database'))
    assert db.recover_delivery_events()['pending'] == 1


@pytest.mark.parametrize('status', ['unsubscribe', 'group_unsubscribe', 'spamreport', 'bounce', 'dropped'])
def test_suppression_survives_database_failure_and_resubscribe_never_unblocks(journal, status):
    delivery.accept_events('email', [email(status)])
    delivery.accept_events('email', [email('group_resubscribe')])
    assert db.email_address_is_suppressed('SELLER@example.invalid')
    assert db.delivery_event_health()['pending'] == 2


def test_conflicting_replay_rolls_back_entire_batch(journal):
    delivery.accept_events('email', [email()])
    with pytest.raises(ValueError, match='conflict'):
        delivery.accept_events('email', [email('open'), email('bounce', sg_event_id='delivered-event')])
    assert db.delivery_event_health()['received'] == 1
    assert not db.email_address_is_suppressed('seller@example.invalid')


@pytest.mark.parametrize('event', [None, {}, {'MessageSid': '', 'MessageStatus': 'delivered', 'To': '+12095550100'}, sms('unknown'), sms(recipient='no'), email(timestamp=True), email(timestamp='1792150000'), email(custom_args=[]), email(sg_event_id=[]), email(sg_message_id='')])
def test_malformed_events_are_not_acknowledged_or_staged(journal, event):
    with pytest.raises((ValueError, TypeError)):
        delivery.accept_events('sms' if isinstance(event, dict) and 'MessageSid' in event else 'email', [event])
    assert db.delivery_event_health()['received'] == 0


@pytest.mark.asyncio
async def test_http_callbacks_ack_only_durable_acceptance(journal, monkeypatch):
    app = FastAPI()
    app.include_router(sms_status.router)
    app.include_router(email_webhook.router)
    monkeypatch.setattr(email_webhook, '_verify_signature', lambda *args: True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post('/voice/sms-status', data=sms())).status_code == 204
        assert (await client.post('/email/webhook', json=[email('open')])).status_code == 200
        assert (await client.post('/email/webhook', json=[email('open'), None])).status_code == 422
        assert (await client.post('/voice/sms-status', data={})).status_code == 422
        def disk_full(*args):
            raise OSError('private storage path')
        monkeypatch.setattr(db, 'stage_delivery_events', disk_full)
        assert (await client.post('/voice/sms-status', data=sms())).status_code == 503
        response = await client.post('/email/webhook', json=[email()])
        assert response.status_code == 503 and 'private' not in response.text
        monkeypatch.setattr(email_webhook, '_verify_signature', lambda *args: False)
        assert (await client.post('/email/webhook', json=[email()])).status_code == 403


def test_thousand_repeated_receipts_remain_one_event(journal):
    for _ in range(1000):
        delivery.accept_events('sms', [sms('delivered')])
    assert db.delivery_event_health()['received'] == 1


def test_receipt_survives_real_process_exit(journal):
    import subprocess
    import sys
    subprocess.run([sys.executable, '-c', "from backend.alerts.delivery import accept_events; accept_events('sms',[{'MessageSid':'SMrestart','MessageStatus':'delivered','To':'+12095550100'}])"], check=True)
    assert db.delivery_event_health()['pending'] == 1


def test_parallel_receipt_staging_retains_one_event(journal):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: delivery.accept_events('sms', [sms('delivered')]), range(40)))
    assert db.delivery_event_health()['received'] == 1


@pytest.mark.asyncio
async def test_unsigned_sms_callback_is_rejected_before_storage(journal, monkeypatch):
    from backend.api.security import OperatorAuthentication
    monkeypatch.setenv('PUBLIC_URL', 'https://source.example.invalid')
    monkeypatch.setenv('SIGNALWIRE_SIGNING_KEY', 'test-signing-key')
    app = FastAPI()
    app.add_middleware(OperatorAuthentication)
    app.include_router(sms_status.router, prefix='/api')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://source.example.invalid') as client:
        assert (await client.post('/api/voice/sms-status', data=sms())).status_code == 403
    assert db.delivery_event_health()['received'] == 0


@pytest.mark.asyncio
async def test_unavailable_receipt_storage_does_not_stop_other_service_recovery(monkeypatch):
    import asyncio
    def readonly():
        raise PermissionError('private storage detail')
    async def stop_after_retry_interval(seconds):
        assert seconds == 5
        raise asyncio.CancelledError
    monkeypatch.setattr(db, 'recover_delivery_events', readonly)
    monkeypatch.setattr(delivery.asyncio, 'sleep', stop_after_retry_interval)
    with pytest.raises(asyncio.CancelledError):
        await delivery.recover_loop()


def test_unbound_backlog_cannot_starve_new_bound_receipts(journal, monkeypatch):
    for index in range(101):
        delivery.accept_events('sms', [sms(message='unbound-' + str(index))])
    assert db.recover_delivery_events()['synced'] == 0
    bind()
    delivery.accept_events('sms', [sms('delivered')])
    class Client:
        def rpc(self, name, args):
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=args['p_id']))
    monkeypatch.setattr(db, '_get_client', Client)
    result = db.recover_delivery_events()
    assert result['synced'] == 1 and result['pending'] == 101


def test_signed_address_opt_out_without_message_id_still_persists_suppression(journal):
    delivery.accept_events('email', [email('unsubscribe', sg_message_id='')])
    assert db.email_address_is_suppressed('seller@example.invalid')
    assert db.delivery_event_health()['pending'] == 1


@pytest.mark.parametrize('status', ['unsubscribe', 'group_unsubscribe', 'spamreport'])
def test_provider_opt_out_blocks_both_call_and_sms_before_database_sync(journal, monkeypatch, status):
    from backend.compliance.compliance import ComplianceEngine
    delivery.accept_events('email', [email(status)])
    monkeypatch.setattr(db, 'get_lead_with_property', lambda _: {'id': 'lead', 'owner_email': 'SELLER@example.invalid', 'opted_out': False})
    monkeypatch.setattr(db, 'local_lead_reply_hold', lambda _: {'opted_out': False})
    engine = ComplianceEngine()
    assert engine.check_call_allowed('lead').allowed is False
    assert engine.check_sms_allowed('lead').allowed is False
    assert db.provider_email_opted_out('other@example.invalid') is False


def test_email_bounce_does_not_mislabel_all_channels_as_opted_out(journal):
    delivery.accept_events('email', [email('bounce')])
    assert db.email_address_is_suppressed('seller@example.invalid')
    assert not db.provider_email_opted_out('seller@example.invalid')
