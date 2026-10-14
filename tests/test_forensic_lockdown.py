import concurrent.futures
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.comps.calculator import calculate_arv
from backend.contracts.intel_packet import is_permission_expired
from backend.lib import db


def test_missing_expiry_denies():
    assert is_permission_expired({})


@pytest.mark.parametrize('seed', range(1000))
def test_duplicate_and_invalid_sales_cannot_inflate_evidence(seed):
    price = 100000 + seed * 97
    valid = {'sale_id': str(seed), 'sold_price': price, 'sqft': 1000, 'sold_date': datetime.now(timezone.utc).date().isoformat()}
    result = calculate_arv([valid] * 6 + [{'sold_price': True, 'sqft': 1000}, {'sold_price': -price, 'sqft': 1000}], 1000)
    assert result['comp_count'] == 1
    assert result['confidence'] == 'low'
    assert result['arv'] == price * 100
    assert result['mao'] >= 0
    assert result['quote_authorized'] is False


def test_invalid_sales_do_not_reenter_fallback():
    result = calculate_arv([{'sold_price': 100000, 'sqft': 1000}, {'sold_price': 900000000, 'sqft': 0}], None)
    assert result['arv'] == 10000000


def test_parallel_message_claim_is_once_and_receipt_survives_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv('COMMUNICATION_JOURNAL_PATH', str(tmp_path / 'messages.sqlite3'))
    def claim(_):
        return db.claim_message_intent('sms', '+12095550100', '', 'test', 'lead')
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(24)))
    assert sum(claimed for _, claimed, _ in results) == 1
    identity = results[0][0]
    db.accept_message_intent(identity, 'provider-sid')
    assert claim(0) == (identity, False, 'provider-sid')


def test_suppression_is_durable_and_normalized(tmp_path, monkeypatch):
    monkeypatch.setenv('COMMUNICATION_JOURNAL_PATH', str(tmp_path / 'messages.sqlite3'))
    db.suppress_email_address('Person@Example.invalid')
    assert db.email_address_is_suppressed('person@example.invalid')


def test_tenant_query_rejects_cross_tenant_write(monkeypatch):
    monkeypatch.setenv('TENANT_ID', 'mine')
    class Query:
        def update(self, payload):
            return self
        def eq(self, key, value):
            assert (key, value) == ('tenant_id', 'mine')
            return self
        def execute(self):
            return SimpleNamespace(data=[])
    client = db.TenantClient(SimpleNamespace(table=lambda _: Query()))
    with pytest.raises(ValueError):
        client.table('leads').update({'tenant_id': 'other'})
    with pytest.raises(RuntimeError):
        client.table('leads').update({'stage': 'new'}).execute()
