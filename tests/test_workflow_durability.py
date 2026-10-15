import concurrent.futures
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.lib import db
from backend.alerts import speed_to_lead, inbound_email


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKFLOW_JOURNAL_PATH', str(tmp_path / 'workflows.sqlite3'))
    monkeypatch.setenv('COMMUNICATION_JOURNAL_PATH', str(tmp_path / 'messages.sqlite3'))
    return datetime.now(timezone.utc)


def test_schedule_survives_reopen_and_concurrent_claims(journal):
    schedule = [journal + timedelta(days=i) for i in range(5)]
    db.stage_speed_touches('lead', schedule)
    db.stage_speed_touches('lead', [date + timedelta(hours=1) for date in schedule])
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(lambda _: db.claim_workflow_job(journal.timestamp() + 1), range(20)))
    owned = [job for job in jobs if job]
    assert len(owned) == 1
    assert not db.finish_workflow_job(owned[0]['id'], 'foreign', 'completed')
    assert db.finish_workflow_job(owned[0]['id'], owned[0]['lease'], 'completed')
    assert db.workflow_journal_health()['jobs'] == {'completed': 1, 'pending': 4}


def test_crashed_claim_quarantines_without_redial(journal):
    db.stage_speed_touches('lead', [journal] + [journal + timedelta(days=i) for i in range(1,5)])
    first = db.claim_workflow_job(journal.timestamp() + 1)
    assert first
    assert db.claim_workflow_job(journal.timestamp() + 602) is None
    assert db.workflow_journal_health()['requires_review'] == 1


def test_reply_is_bound_durable_and_remote_retry_is_idempotent(journal, monkeypatch):
    tenant = '00000000-0000-0000-0000-000000000001'
    monkeypatch.setattr(db, 'get_lead_with_property', lambda _: {'id':'lead', 'tenant_id':tenant, 'owner_email':'seller@example.invalid'})
    token = db.register_email_thread('lead', 'seller@example.invalid')
    payload = {'event_id':'event', 'thread_token':token, 'sender':'seller@example.invalid', 'sender_verified':True, 'text':'Tuesday works'}
    receipt = db.stage_inbound_email(payload)
    assert db.stage_inbound_email(payload)['duplicate']
    with pytest.raises(ValueError):
        db.stage_inbound_email({**payload, 'sender':'stranger@example.invalid'})
    with pytest.raises(ValueError):
        db.stage_inbound_email({**payload, 'text':'conflict'})
    client = MagicMock()
    client.rpc.return_value.execute.side_effect = RuntimeError('offline')
    monkeypatch.setattr(db, '_get_client', lambda: client)
    assert db.recover_inbound_email() == {'applied':0,'pending':1}
    client.rpc.return_value.execute.side_effect = None
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=receipt['receipt_id'])
    assert db.recover_inbound_email() == {'applied':1,'pending':0}
    assert db.recover_inbound_email() == {'applied':0,'pending':0}


def test_stop_email_is_suppressed_during_database_outage(journal, monkeypatch):
    monkeypatch.setattr(db, 'get_lead_with_property', lambda _: {'tenant_id':'00000000-0000-0000-0000-000000000001', 'owner_email':'seller@example.invalid'})
    token = db.register_email_thread('lead', 'seller@example.invalid')
    monkeypatch.setattr(db, '_get_client', MagicMock(side_effect=RuntimeError('offline')))
    inbound_email.accept_reply({'event_id':'stop', 'thread_token':token, 'sender':'seller@example.invalid', 'sender_verified':True, 'text':'STOP'})
    assert db.email_address_is_suppressed('seller@example.invalid')


def test_touch_respects_authority_and_cooldown(journal, monkeypatch):
    lead = {'owner_phone':'+12095550123','callable':True}
    monkeypatch.setattr(speed_to_lead, 'get_lead_with_property', lambda _: lead)
    call = MagicMock(return_value={'success':False,'reason':'cooldown'})
    monkeypatch.setattr('backend.voice.outbound.call_lead', call)
    assert speed_to_lead._run_touch('lead',1)['status'] == 'skipped'
    call.assert_called_once_with('lead', bypass_cooldown=False)
    call.reset_mock()
    lead['callable'] = False
    assert speed_to_lead._run_touch('lead',2)['status'] == 'skipped'
    call.assert_not_called()


def test_inbound_adapter_signature_covers_exact_body_and_fresh_timestamp(monkeypatch):
    import hashlib
    import hmac
    import time
    monkeypatch.setenv('INBOUND_EMAIL_ADAPTER_SECRET','x'*32)
    body = b'{"event_id":"synthetic"}'
    stamp = str(int(time.time()))
    signature = hmac.new(b'x'*32,stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
    assert inbound_email.verify_adapter(body,stamp,signature)
    assert not inbound_email.verify_adapter(body+b' ',stamp,signature)
    assert not inbound_email.verify_adapter(body,str(int(stamp)-301),signature)
    monkeypatch.delenv('INBOUND_EMAIL_ADAPTER_SECRET')
    assert not inbound_email.verify_adapter(body,stamp,signature)


@pytest.mark.parametrize('text', ['STOP', '\n stop\t', 'unsubscribe', 'remove me', 'do not contact me'])
def test_stop_holds_all_lead_channels_before_remote_write(journal, monkeypatch, text):
    from backend.compliance.compliance import ComplianceEngine
    from backend.alerts import email
    lead = {'id':'lead', 'tenant_id':'00000000-0000-0000-0000-000000000001', 'owner_email':'seller@example.invalid'}
    monkeypatch.setattr(db, 'get_lead_with_property', lambda _: lead)
    token = db.register_email_thread('lead', lead['owner_email'])
    db.stage_inbound_email({'event_id':'stop', 'thread_token':token, 'sender':lead['owner_email'], 'sender_verified':True, 'text':text})
    assert db.local_lead_reply_hold('lead') == {'email_paused':True, 'opted_out':True}
    assert ComplianceEngine().check_call_allowed('lead').reason == 'opted_out'
    assert ComplianceEngine().check_sms_allowed('lead').reason == 'opted_out'
    assert db.email_address_is_suppressed(lead['owner_email'])
    monkeypatch.setenv('OUTBOUND_ENABLED', 'true')
    provider = MagicMock()
    monkeypatch.setattr('httpx.post', provider)
    assert not email.send_email(lead['owner_email'], 'subject', 'body', 'lead')
    assert not email.send_email('other@example.invalid', 'subject', 'body', 'lead')
    provider.assert_not_called()


def test_reply_pauses_drip_during_outage_without_granting_global_optout(journal, monkeypatch):
    from backend.alerts import email
    monkeypatch.setattr(db, 'get_lead_with_property', lambda _: {'tenant_id':'00000000-0000-0000-0000-000000000001', 'owner_email':'seller@example.invalid'})
    token = db.register_email_thread('lead', 'seller@example.invalid')
    db.stage_inbound_email({'event_id':'reply', 'thread_token':token, 'sender':'seller@example.invalid', 'sender_verified':True, 'text':'Tuesday works'})
    assert db.local_lead_reply_hold('lead') == {'email_paused':True, 'opted_out':False}
    assert not db.email_address_is_suppressed('seller@example.invalid')
    sender = MagicMock(return_value=True)
    monkeypatch.setattr(email, 'send_email', sender)
    assert not email.send_drip_email('seller@example.invalid', 'follow up', 'body', 'lead')
    sender.assert_not_called()
    assert db.local_lead_reply_hold('other') == {'email_paused':False, 'opted_out':False}
    monkeypatch.setenv('TENANT_ID', '00000000-0000-0000-0000-000000000002')
    assert db.local_lead_reply_hold('lead') == {'email_paused':False, 'opted_out':False}
    assert not db.local_reply_email_blocked('seller@example.invalid')


def test_stop_hold_survives_crash_between_journals_and_recovery(journal, monkeypatch):
    monkeypatch.setattr(db, 'get_lead_with_property', lambda _: {'tenant_id':'00000000-0000-0000-0000-000000000001', 'owner_email':'seller@example.invalid'})
    token = db.register_email_thread('lead', 'seller@example.invalid')
    payload = {'event_id':'stop', 'thread_token':token, 'sender':' \nSELLER@example.invalid\t', 'sender_verified':True, 'text':'STOP'}
    monkeypatch.setattr(db, 'suppress_email_address', MagicMock(side_effect=RuntimeError('second journal unavailable')))
    with pytest.raises(RuntimeError):
        inbound_email.accept_reply(payload)
    assert db.local_reply_email_blocked(' SELLER@example.invalid ')
    assert db.local_lead_reply_hold('lead')['opted_out']
    receipt = db.stage_inbound_email(payload)
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=receipt['receipt_id'])
    monkeypatch.setattr(db, '_get_client', lambda:client)
    assert db.recover_inbound_email()['applied'] == 1
    assert db.local_lead_reply_hold('lead')['opted_out']
    with pytest.raises(ValueError):
        db.stage_inbound_email({**payload, 'text':'Tuesday works'})
    assert db.local_lead_reply_hold('lead')['opted_out']


def test_unavailable_hold_denies_calls_sms_and_drip(journal, monkeypatch):
    from backend.compliance.compliance import ComplianceEngine
    from backend.alerts import email
    monkeypatch.setattr(db, 'get_lead_with_property', lambda _: {'id':'lead'})
    monkeypatch.setattr(db, 'local_lead_reply_hold', MagicMock(side_effect=OSError('journal unavailable')))
    assert ComplianceEngine().check_call_allowed('lead').reason == 'compliance_unavailable'
    assert ComplianceEngine().check_sms_allowed('lead').reason == 'compliance_unavailable'
    sender = MagicMock()
    monkeypatch.setattr(email, 'send_email', sender)
    assert not email.send_drip_email('seller@example.invalid', 'subject', 'body', 'lead')
    sender.assert_not_called()
