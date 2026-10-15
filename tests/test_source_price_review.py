from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.lib import db


@pytest.fixture
def price_review(monkeypatch):
    row = {'id': 'a'*32, 'lead_id': 'lead', 'call_sid': 'call', 'approval_type': 'price_review', 'requested_action': 'get_offer_range', 'status': 'pending', 'expires_at': (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat(), 'context_snapshot': {}}
    client = MagicMock()
    query = client.table.return_value
    for name in ('select', 'eq', 'gt', 'order', 'range', 'limit'):
        getattr(query, name).return_value = query
    query.execute.return_value = SimpleNamespace(data=[row])
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=row['id'])
    monkeypatch.setattr(db, '_get_client', lambda: client)
    monkeypatch.setattr(db, 'offer_subject', lambda _: {'id': 'property', 'address': 'Synthetic property'})
    return row, client


def test_reviewed_source_decision_is_bound_to_property_action_and_actor(price_review):
    row, client = price_review
    item = db.list_source_price_reviews()['items'][0]
    body = {'actor_id': '00000000-0000-0000-0000-000000000099', 'status': 'approved', 'reason': 'Reviewed current sales and repairs', 'fingerprint': item['fingerprint'], 'offer_low_cents': 25000000, 'offer_high_cents': 27000000}
    result = db.resolve_source_price_review(row['id'], body)
    assert result['persisted'] and result['approval_id'] == row['id']
    arguments = client.rpc.call_args.args[1]
    assert arguments['p_expected']['property_id'] == 'property'
    assert arguments['p_expected']['requested_action'] == 'get_offer_range'
    assert arguments['p_actor'] == body['actor_id']
    row['context_snapshot'] = {'changed': True}
    client.rpc.reset_mock()
    with pytest.raises(ValueError, match='changed'):
        db.resolve_source_price_review(row['id'], body)
    client.rpc.assert_not_called()


@pytest.mark.parametrize('low,high', [(True, 10000), (10000, 9999), (10001, 20000), (None, None), (-100, 10000), (10000, 10**15)])
def test_invalid_source_price_ranges_never_reach_rpc(price_review, low, high):
    row, client = price_review
    with pytest.raises(ValueError):
        db.resolve_source_price_review(row['id'], {'actor_id': '00000000-0000-0000-0000-000000000099', 'status': 'approved', 'reason': 'Reviewed current sales', 'fingerprint': 'f'*64, 'offer_low_cents': low, 'offer_high_cents': high})
    client.rpc.assert_not_called()


def test_unconfirmed_source_resolution_is_not_success(price_review):
    row, client = price_review
    item = db.list_source_price_reviews()['items'][0]
    client.rpc.return_value.execute.return_value = SimpleNamespace(data='different')
    with pytest.raises(RuntimeError, match='not confirmed'):
        db.resolve_source_price_review(row['id'], {'actor_id': '00000000-0000-0000-0000-000000000099', 'status': 'rejected', 'reason': 'Comparable evidence insufficient', 'fingerprint': item['fingerprint'], 'offer_low_cents': None, 'offer_high_cents': None})


@pytest.mark.parametrize('receipt', [None, 123, 'not-a-source-receipt'])
def test_price_request_requires_real_source_identity(monkeypatch, receipt):
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=receipt)
    monkeypatch.setattr(db, '_get_client', lambda: client)
    with pytest.raises(RuntimeError, match='not confirmed'):
        db.create_approval_request('lead', 'call', 'price_review', 'get_offer_range')
    client.table.assert_not_called()
