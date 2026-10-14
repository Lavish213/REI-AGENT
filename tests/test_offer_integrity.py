from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.offers import router
from backend.lib import db


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix='/api')
    return TestClient(app)


@pytest.mark.parametrize('field', ['arv_used', 'repair_estimate', 'offer_amount'])
@pytest.mark.parametrize('value', [True, 12.5, '1200', -1, 10**14 + 1])
def test_api_rejects_coerced_or_invalid_cents(client, field, value, monkeypatch):
    save = MagicMock()
    monkeypatch.setattr(db, 'create_offer', save)
    assert client.post('/api/offers', json={'lead_id': 'lead', field: value}).status_code == 422
    save.assert_not_called()


def test_property_is_loaded_by_canonical_foreign_key_not_reverse_link(monkeypatch):
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{'id': 'lead', 'property_id': 'canonical', 'tenant_id': 'tenant'}]
    monkeypatch.setattr(db, '_get_client', lambda: client)
    prop = MagicMock(return_value={'id': 'canonical', 'tenant_id': 'tenant'})
    monkeypatch.setattr(db, 'get_property_by_id', prop)
    assert db.get_lead_with_property('lead')['properties']['id'] == 'canonical'
    prop.assert_called_once_with('canonical')
    assert client.table.return_value.select.call_args.args == ('*',)


@pytest.mark.parametrize('change', ['foreign_tenant', 'other_property', 'missing_property'])
def test_offer_subject_rejects_unbound_property(change, monkeypatch):
    tenant = '00000000-0000-0000-0000-000000000001'
    lead = {'id': 'lead', 'tenant_id': tenant, 'property_id': 'canonical', 'properties': {'id': 'canonical', 'tenant_id': tenant}}
    if change == 'foreign_tenant':
        lead['tenant_id'] = 'other'
    if change == 'missing_property':
        lead['properties'] = {}
    monkeypatch.setattr(db, 'get_lead_with_property', lambda _: lead)
    with pytest.raises(ValueError):
        db.offer_subject('lead', 'other' if change == 'other_property' else None)


def test_low_value_never_creates_negative_offer(monkeypatch):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = [{'id': 'offer'}]
    monkeypatch.setattr(db, '_get_client', lambda: client)
    db.create_offer('lead', 2_000_000, 2_500_000)
    payload = client.table.return_value.insert.call_args.args[0]
    assert payload['mao_calculated'] == payload['offer_amount'] == 0


@pytest.mark.parametrize('rows', [[], [{'id': 'wrong', 'offer_status': 'sent'}], [{'id': 'offer', 'offer_status': 'draft'}]])
def test_status_update_requires_matching_saved_receipt(rows, monkeypatch):
    client = MagicMock()
    client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = rows
    monkeypatch.setattr(db, '_get_client', lambda: client)
    with pytest.raises(RuntimeError):
        db.update_offer_status('offer', 'sent')


def test_api_does_not_claim_success_when_status_write_unconfirmed(client, monkeypatch):
    monkeypatch.setattr(db, 'get_offer_by_id', lambda _: {'id': 'offer', 'lead_id': 'lead', 'property_id': 'prop'})
    monkeypatch.setattr(db, 'offer_subject', lambda *_: {'id': 'prop'})
    monkeypatch.setattr(db, 'update_offer_status', MagicMock(side_effect=RuntimeError('No receipt')))
    assert client.patch('/api/offers/offer/status', json={'status': 'sent'}).status_code == 503


def test_creation_does_not_trust_client_actor_and_requires_readback(client, monkeypatch):
    monkeypatch.setattr(db, 'offer_subject', lambda *_: {'id': 'prop', 'estimated_arv': 30_000_000})
    save = MagicMock(return_value='offer')
    monkeypatch.setattr(db, 'create_offer', save)
    monkeypatch.setattr(db, 'get_offer_by_id', lambda _: None)
    assert client.post('/api/offers', json={'lead_id': 'lead', 'created_by': 'forged-admin'}).status_code == 503
    assert save.call_args.kwargs['created_by'] == 'operator'
    assert save.call_args.kwargs['property_id'] == 'prop'


def test_authenticated_operator_is_saved_as_actor(monkeypatch):
    app = FastAPI()
    @app.middleware('http')
    async def operator(request, call_next):
        request.state.operator = SimpleNamespace(id='authenticated-operator')
        return await call_next(request)
    app.include_router(router, prefix='/api')
    monkeypatch.setattr(db, 'offer_subject', lambda *_: {'id': 'prop', 'estimated_arv': 30_000_000})
    save = MagicMock(return_value='offer')
    monkeypatch.setattr(db, 'create_offer', save)
    monkeypatch.setattr(db, 'get_offer_by_id', lambda _: {'id': 'offer', 'lead_id': 'lead', 'property_id': 'prop'})
    assert TestClient(app).post('/api/offers', json={'lead_id': 'lead', 'created_by': 'forged'}).status_code == 200
    assert save.call_args.kwargs['created_by'] == 'authenticated-operator'
