import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import properties as property_routes
from backend.api.security import OperatorAuthentication
from backend.comps import rentcast
from backend.lib import db

SECRET = 's' * 40


class Budget:
    def __init__(self, cap=50):
        self.cap = cap
        self.calls = []
        self.finished = {}

    def reserve(self, property_id, cap):
        if len(self.calls) >= min(cap, self.cap, 50):
            return None
        self.calls.append(property_id)
        return len(self.calls)

    def finish(self, call_id, status, outcome):
        assert call_id not in self.finished
        self.finished[call_id] = (status, outcome)

    def usage(self):
        return {'used': len(self.calls), 'hard_cap': 50, 'window_days': 31}


@pytest.fixture
def budget(monkeypatch):
    state = Budget()
    monkeypatch.setattr(db, 'reserve_rentcast_call', state.reserve)
    monkeypatch.setattr(db, 'finish_rentcast_call', state.finish)
    monkeypatch.setattr(db, 'rentcast_usage', state.usage)
    monkeypatch.setenv('RENTCAST_ENABLED', 'true')
    monkeypatch.setenv('RENTCAST_API_KEY', 'k' * 32)
    monkeypatch.delenv('RENTCAST_MONTHLY_CAP', raising=False)
    return state


def prop(index=0):
    return {'id': f'p{index}', 'address': f'{index} Main St', 'city': 'Stockton', 'state': 'CA', 'zip': '95205', 'beds': 3, 'baths': 2, 'sqft': 1400, 'property_type': 'Single Family Residence'}


def transport(status=200, body=None, seen=None):
    def handle(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if body is not None else {'price': 450000, 'priceRangeLow': 400000, 'priceRangeHigh': 500000, 'comparables': []})
    return httpx.MockTransport(handle)


def test_disabled_by_default_sends_nothing(monkeypatch, budget):
    monkeypatch.delenv('RENTCAST_ENABLED')
    seen = []
    with pytest.raises(rentcast.RentcastDisabled):
        rentcast.value_estimate(prop(), transport(seen=seen))
    with pytest.raises(rentcast.RentcastDisabled):
        rentcast.price_batch(5, transport(seen=seen))
    assert seen == [] and budget.calls == []


def test_enabled_without_key_is_disabled(monkeypatch, budget):
    monkeypatch.setenv('RENTCAST_API_KEY', '  ')
    assert rentcast.enabled() is False


@pytest.mark.parametrize('raw,expected', [('50', 50), ('1000', 50), ('10', 10), ('-3', 0), ('abc', 0), ('', 0)])
def test_monthly_cap_never_exceeds_fifty(monkeypatch, raw, expected):
    monkeypatch.setenv('RENTCAST_MONTHLY_CAP', raw)
    assert rentcast.monthly_cap() == expected


def test_reservation_happens_before_request_and_is_finished(budget):
    seen = []
    data = rentcast.value_estimate(prop(), transport(seen=seen))
    assert data['price'] == 450000
    assert len(seen) == 1 and budget.calls == ['p0']
    assert budget.finished == {1: (200, 'ok')}
    request = seen[0]
    assert request.method == 'GET'
    assert request.url.path == '/v1/avm/value'
    assert request.headers['x-api-key'] == 'k' * 32
    assert request.url.params['address'] == '0 Main St, Stockton, CA 95205'
    assert request.url.params['propertyType'] == 'Single Family'


def test_no_budget_means_no_request(budget):
    budget.cap = 0
    seen = []
    with pytest.raises(rentcast.BudgetExhausted):
        rentcast.value_estimate(prop(), transport(seen=seen))
    assert seen == []


def test_lower_configured_cap_stops_early(monkeypatch, budget):
    monkeypatch.setenv('RENTCAST_MONTHLY_CAP', '3')
    seen = []
    monkeypatch.setattr(db, 'rentcast_candidates', lambda limit: [prop(i) for i in range(limit)])
    monkeypatch.setattr(db, 'save_rentcast_valuation', lambda property_id, data: 0)
    result = rentcast.price_batch(10, transport(seen=seen))
    assert len(seen) == 3 and result['priced'] == 3 and result['stopped'] == 'budget_exhausted'


def test_batch_never_exceeds_fifty_requests(monkeypatch, budget):
    seen = []
    monkeypatch.setattr(db, 'rentcast_candidates', lambda limit: [prop(i) for i in range(500)])
    monkeypatch.setattr(db, 'save_rentcast_valuation', lambda property_id, data: 0)
    rentcast.price_batch(50, transport(seen=seen))
    result = rentcast.price_batch(50, transport(seen=seen))
    assert len(seen) == 50 and result['stopped'] == 'budget_exhausted' and result['priced'] == 0
    assert rentcast.price_batch(10_000, transport(seen=seen))['requested'] == 50
    assert len(seen) == 50


def test_not_found_is_counted_and_marked(monkeypatch, budget):
    marked = []
    monkeypatch.setattr(db, 'rentcast_candidates', lambda limit: [prop()])
    monkeypatch.setattr(db, 'mark_rentcast_no_data', marked.append)
    result = rentcast.price_batch(1, transport(status=404, body={}))
    assert result['no_data'] == 1 and marked == ['p0']
    assert budget.finished == {1: (404, 'no_data')}


@pytest.mark.parametrize('status', [401, 403, 429])
def test_rejection_stops_the_batch(monkeypatch, budget, status):
    seen = []
    monkeypatch.setattr(db, 'rentcast_candidates', lambda limit: [prop(i) for i in range(limit)])
    result = rentcast.price_batch(10, transport(status=status, body={}, seen=seen))
    assert len(seen) == 1 and result['errors'] == 1 and str(status) in result['stopped']
    assert budget.finished == {1: (status, 'error')}


def test_network_failure_is_finished_and_counted_without_retry(budget):
    attempts = []

    def explode(request):
        attempts.append(request)
        raise httpx.ConnectTimeout('slow')
    with pytest.raises(httpx.HTTPError):
        rentcast.value_estimate(prop(), httpx.MockTransport(explode))
    assert len(attempts) == 1 and budget.calls == ['p0'] and budget.finished == {1: (None, 'error')}


def test_server_error_does_not_retry(budget):
    seen = []
    with pytest.raises(RuntimeError):
        rentcast.value_estimate(prop(), transport(status=500, body={}, seen=seen))
    assert len(seen) == 1 and budget.finished == {1: (500, 'error')}


def test_request_params_skip_bad_values():
    params = rentcast.request_params({'address': '1 A St', 'city': 'Lodi', 'beds': True, 'baths': 0, 'sqft': 'big', 'land_use': 'Condominium'})
    assert params == {'address': '1 A St, Lodi, CA', 'compCount': 20, 'maxRadius': 5, 'daysOld': 270, 'propertyType': 'Condo'}


class Query:
    def __init__(self, store, table):
        self.store, self.table, self.op, self.payload, self.filters = store, table, None, None, []

    def update(self, payload):
        self.op, self.payload = 'update', payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.op, self.payload, self.conflict = 'upsert', payload, on_conflict
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def execute(self):
        self.store.append((self.table, self.op, self.payload, self.filters, getattr(self, 'conflict', None)))
        return type('R', (), {'data': [{'id': 'p0'}]})()


class Client:
    def __init__(self):
        self.writes = []

    def table(self, name):
        return Query(self.writes, name)


def test_save_valuation_uses_cents_and_listing_comps(monkeypatch):
    client = Client()
    monkeypatch.setattr(db, '_get_client', lambda: client)
    saved = db.save_rentcast_valuation('p0', {'price': 452000, 'priceRangeLow': 400000.4, 'priceRangeHigh': 500000, 'comparables': [
        {'id': 'c1', 'formattedAddress': '2 B St', 'price': 440000, 'status': 'Inactive', 'listingType': 'Standard', 'listedDate': '2026-05-01T00:00:00.000Z', 'bedrooms': 3, 'bathrooms': 2, 'squareFootage': 1350, 'distance': 0.4, 'correlation': 0.98},
        {'price': 1},
    ]})
    assert saved == 1
    table, op, payload, filters, _ = client.writes[0]
    assert (table, op, filters) == ('properties', 'update', [('id', 'p0')])
    assert payload['estimated_arv'] == 45200000
    assert payload['mao'] == 45200000 * 70 // 100 - 2500000
    assert payload['arv_confidence'] == 'rentcast_avm'
    diagnostic = payload['valuation_diagnostic']
    assert diagnostic['basis'] == 'listing_prices_not_recorded_sales'
    assert diagnostic['offer_authorized'] is False and diagnostic['quote_authorized'] is False
    assert diagnostic['low_cents'] == 40000040
    table, op, rows, _, conflict = client.writes[1]
    assert (table, op, conflict) == ('comps', 'upsert', 'subject_property_id,source,source_ref')
    assert rows[0]['comp_kind'] == 'listing' and rows[0]['list_price_cents'] == 44000000
    assert 'sold_price' not in rows[0] and rows[0]['listed_date'] == '2026-05-01'


@pytest.mark.parametrize('price', [None, 0, -5, True, 'big', 5000])
def test_save_valuation_rejects_unusable_prices(monkeypatch, price):
    client = Client()
    monkeypatch.setattr(db, '_get_client', lambda: client)
    with pytest.raises(ValueError):
        db.save_rentcast_valuation('p0', {'price': price})
    assert client.writes == []


def test_rescore_without_arv_keeps_existing_valuation(monkeypatch):
    client = Client()
    monkeypatch.setattr(db, '_get_client', lambda: client)
    db.upsert_property({'apn': '1', 'address': '1 A St', 'estimated_arv': None, 'mao': None, 'arv_confidence': 'needs_comps'})
    payload = client.writes[0][2]
    assert 'estimated_arv' not in payload and 'mao' not in payload and 'arv_confidence' not in payload


class RpcClient:
    def __init__(self, data):
        self.data, self.calls = data, []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return self

    def execute(self):
        return type('R', (), {'data': self.data})()


def test_db_reserve_clamps_cap(monkeypatch):
    client = RpcClient(7)
    monkeypatch.setattr(db, '_get_client', lambda: client)
    assert db.reserve_rentcast_call('p0', 9999) == 7
    assert db.reserve_rentcast_call('p0', -4) == 7
    assert [call[1]['p_cap'] for call in client.calls] == [50, 0]


@pytest.mark.parametrize('data', [None, True, '7', {}])
def test_db_reserve_refusal_is_none(monkeypatch, data):
    monkeypatch.setattr(db, '_get_client', lambda: RpcClient(data))
    assert db.reserve_rentcast_call('p0', 50) is None


def app():
    application = FastAPI()
    application.add_middleware(OperatorAuthentication)
    application.include_router(property_routes.router, prefix='/api')
    return TestClient(application)


def test_endpoints_require_source_secret(monkeypatch, budget):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    client = app()
    assert client.get('/api/operations/rentcast/usage').status_code == 401
    assert client.post('/api/operations/rentcast/price', json={'limit': 1}).status_code == 401
    assert client.get('/api/operations/rentcast/usage', headers={'x-source-command-secret': 'x' * 40}).status_code == 401


def test_usage_endpoint(monkeypatch, budget):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    response = app().get('/api/operations/rentcast/usage', headers={'x-source-command-secret': SECRET})
    assert response.status_code == 200
    assert response.json() == {'used': 0, 'hard_cap': 50, 'window_days': 31, 'enabled': True, 'configured_cap': 50}


@pytest.mark.parametrize('limit', [0, 51, True, '5', None, 2.5])
def test_price_endpoint_validates_limit(monkeypatch, budget, limit):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    response = app().post('/api/operations/rentcast/price', json={'limit': limit}, headers={'x-source-command-secret': SECRET})
    assert response.status_code == 422
    assert budget.calls == []


def test_price_endpoint_disabled_is_409(monkeypatch, budget):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    monkeypatch.setenv('RENTCAST_ENABLED', 'false')
    response = app().post('/api/operations/rentcast/price', json={'limit': 5}, headers={'x-source-command-secret': SECRET})
    assert response.status_code == 409 and budget.calls == []
