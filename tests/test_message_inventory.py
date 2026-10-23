import json
from types import SimpleNamespace

import pytest
from backend.lib import db

TENANT = '00000000-0000-0000-0000-000000000001'
LEAD = '00000000-0000-0000-0000-000000000020'


@pytest.fixture(autouse=True)
def journal(monkeypatch, tmp_path):
    monkeypatch.setenv('COMMUNICATION_JOURNAL_PATH', str(tmp_path / 'communications.sqlite3'))
    monkeypatch.setenv('TENANT_ID', TENANT)


def create(channel='email', accepted=True, body='hello'):
    recipient = 'seller@example.invalid' if channel == 'email' else '+12095550100'
    identity, claimed, _ = db.claim_message_intent(channel, recipient, '', body)
    assert claimed
    db.bind_delivery_intent(identity, LEAD, channel, recipient)
    if accepted:
        db.accept_message_intent(identity, 'provider-' + identity[:12])
    return identity


@pytest.mark.parametrize('channel', ['sms', 'email'])
def test_no_callback_accepted_message_is_staged_and_synced_as_pending(monkeypatch, channel):
    identity = create(channel)
    assert db.message_inventory_health()['pending_projection'] == 1
    result = db.stage_message_acceptances()
    assert result['staged'] == 1 and result['pending_projection'] == 0
    assert db.stage_message_acceptances()['staged'] == 0
    received = []
    class Client:
        def rpc(self, name, args):
            received.append(args)
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=args['p_id']))
    monkeypatch.setattr(db, '_get_client', Client)
    assert db.recover_delivery_events()['synced'] == 1
    assert received[0]['p_intent'] == identity and received[0]['p_lead'] == LEAD
    assert received[0]['p_payload']['status'] == 'accepted'
    assert received[0]['p_payload']['origin'] == 'provider_acceptance'
    assert received[0]['p_payload']['accepted_at'] > 0


def test_acceptance_is_atomic_and_identical_receipt_replay_is_idempotent():
    identity = create()
    db.accept_message_intent(identity, 'provider-' + identity[:12])
    with pytest.raises(ValueError, match='conflict'):
        db.accept_message_intent(identity, 'different-receipt')
    assert db.message_inventory_health()['accepted'] == 1


def test_lost_staging_ack_and_restart_replay_same_event(monkeypatch):
    create()
    real = db.stage_delivery_events
    first = True
    def lost_ack(events):
        nonlocal first
        real(events)
        if first:
            first = False
            raise OSError('process lost after durable stage')
    monkeypatch.setattr(db, 'stage_delivery_events', lost_ack)
    with pytest.raises(OSError):
        db.stage_message_acceptances()
    assert db.message_inventory_health()['pending_projection'] == 1
    assert db.stage_message_acceptances()['staged'] == 1
    assert db.delivery_event_health()['received'] == 1


def test_legacy_accepted_rows_backfill_without_inventing_acceptance_time():
    identity = create(accepted=False)
    with db._communication_journal() as connection:
        connection.execute("UPDATE message_intents SET state='accepted',receipt='legacy-id' WHERE id=?", (identity,))
    assert db.message_inventory_health()['pending_projection'] == 1
    assert db.stage_message_acceptances()['staged'] == 1
    with db._delivery_journal() as connection:
        payload = json.loads(connection.execute('SELECT payload FROM delivery_events').fetchone()[0])
    assert payload['accepted_at'] is None


def test_uncertain_send_is_visible_and_never_accepted_or_resent():
    identity = create(accepted=False)
    assert db.stage_message_acceptances()['staged'] == 0
    assert db.message_inventory_health()['uncertain_submission'] == 1
    assert db.claim_message_intent('email', 'seller@example.invalid', '', 'hello') == (identity, False, None)
    assert db.delivery_event_health()['received'] == 0


def test_cross_tenant_acceptance_cannot_mutate_or_disclose_another_intent(monkeypatch):
    identity = create(accepted=False)
    monkeypatch.setenv('TENANT_ID', '00000000-0000-0000-0000-000000000002')
    with pytest.raises(RuntimeError, match='ownership'):
        db.accept_message_intent(identity, 'receipt')
    assert db.message_inventory_health()['accepted'] == 0
    assert db.message_inventory_health()['uncertain_submission'] == 0
    assert db.stage_message_acceptances()['staged'] == 0


@pytest.mark.parametrize('limit', [True, 0, -1, 1001])
def test_inventory_recovery_is_bounded(limit):
    with pytest.raises(ValueError):
        db.stage_message_acceptances(limit)
