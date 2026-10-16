from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from backend.api.routes.bob import router
from backend.api.security import OperatorAuthentication
from backend.karpathys import connections


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['none', 'nonce', 'tenant', 'receiver', 'schema', 'http', 'bob', 'journal', 'disabled'])
async def test_round_trip_checks_bound_authentication_and_reports_degraded_edges(monkeypatch, fault):
    tenant = '00000000-0000-0000-0000-000000000001'
    monkeypatch.setenv('TENANT_ID', tenant)
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', 'command-secret-' * 4)
    monkeypatch.setenv('OUTBOUND_ENABLED', 'false')
    monkeypatch.setattr(connections.client, '_KARPATHYS_URL', 'https://dashboard.example.invalid')
    monkeypatch.setattr(connections.client, '_KARPATHYS_SECRET', 'events-secret-' * 4)
    monkeypatch.setattr(connections.db, 'bob_integration_health', lambda: {'worker': {'completed_at': datetime.now(UTC).isoformat(), 'errors': 1 if fault == 'bob' else 0}})
    monkeypatch.setattr(connections.db, 'bob_fact_journal_health', lambda: {'dead': 0, 'oldest_pending_seconds': 0})
    monkeypatch.setattr(connections.db, 'dashboard_event_journal_health', lambda: {'dead': 1 if fault == 'journal' else 0, 'oldest_pending_seconds': 0})
    if fault == 'disabled':
        monkeypatch.setattr(connections.client, '_KARPATHYS_URL', '')
    native = httpx.AsyncClient
    requests = []
    def receive(request):
        requests.append(request)
        assert request.headers['X-Karpathys-Secret'] == 'events-secret-' * 4
        assert request.url.path == '/api/v1/ingest/connection'
        data = {'schema_version': True if fault == 'schema' else 1, 'service': 'karpathys-dashboard', 'challenge': str(uuid4()) if fault == 'nonce' else request.url.params['challenge'], 'source_tenant_id': str(uuid4()) if fault == 'tenant' else tenant, 'receiver_id': 'bad' if fault == 'receiver' else 'a' * 64}
        return httpx.Response(503 if fault == 'http' else 200, json=data)
    monkeypatch.setattr(connections.httpx, 'AsyncClient', lambda **kwargs: native(transport=httpx.MockTransport(receive)))
    app = FastAPI()
    app.add_middleware(OperatorAuthentication)
    app.include_router(router, prefix='/api')
    challenge = str(uuid4())
    async with native(transport=httpx.ASGITransport(app=app), base_url='http://test') as transport:
        denied = await transport.get('/api/operations/integration?challenge=' + challenge)
        assert denied.status_code == 401
        assert requests == []
        response = await transport.get('/api/operations/integration?challenge=' + challenge, headers={'X-Source-Command-Secret': 'command-secret-' * 4})
    assert response.status_code == 200
    data = response.json()
    assert data['challenge'] == challenge and data['tenant_id'] == tenant
    assert data['outbound_enabled'] is False
    assert data['bob'] == ('degraded' if fault == 'bob' else 'ok')
    assert data['dashboard_journal'] == ('degraded' if fault == 'journal' else 'ok')
    assert data['dashboard']['status'] == ('unconfigured' if fault == 'disabled' else 'invalid_receipt' if fault in {'nonce','tenant','receiver','schema','http'} else 'ok')
    assert 'events-secret' not in response.text and 'command-secret' not in response.text


@pytest.mark.asyncio
async def test_missing_bob_schema_or_worker_is_unavailable_and_local_storage_failure_is_visible(monkeypatch):
    monkeypatch.setattr(connections.client, 'delivery_target', lambda: None)
    def offline():
        raise RuntimeError('private database detail')
    monkeypatch.setattr(connections.db, 'bob_integration_health', offline)
    monkeypatch.setattr(connections.db, 'bob_fact_journal_health', offline)
    monkeypatch.setattr(connections.db, 'dashboard_event_journal_health', offline)
    result = await connections.inspect_connections(str(uuid4()))
    assert result['bob'] == result['dashboard_journal'] == 'unavailable'
    assert 'private database detail' not in str(result)
