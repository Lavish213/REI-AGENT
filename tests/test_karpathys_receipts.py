from unittest.mock import AsyncMock

import httpx
import pytest

from backend.karpathys import client, events


def transport(monkeypatch, response, requests):
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, **kwargs):
            requests.append(url)
            return response
    monkeypatch.setattr(client, "_KARPATHYS_URL", "https://dashboard.example.invalid")
    monkeypatch.setattr(client, "_KARPATHYS_SECRET", "synthetic")
    monkeypatch.setattr(client.httpx, "AsyncClient", Client)
    monkeypatch.setattr(client.asyncio, "sleep", AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,path", [("call", "/api/v1/ingest/call"), ("sophia/disposition-action", "/api/v1/sophia/disposition-action")])
async def test_exact_routes_require_a_matching_persisted_receipt(monkeypatch, endpoint, path):
    requests = []
    transport(monkeypatch, httpx.Response(200, json={"persisted": True, "schema_version": 1, "receipt_id": "receipt", "call_sid": "call-one"}), requests)
    assert await client.post_event(endpoint, {"call_sid": "call-one"})
    assert requests == ["https://dashboard.example.invalid" + path]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"status": "ok"}, {"persisted": False}, {"persisted": True, "schema_version": 1, "receipt_id": "receipt", "call_sid": "wrong-call"}, {"persisted": True, "schema_version": True, "receipt_id": "receipt", "call_sid": "call-one"}])
async def test_http_success_without_a_valid_receipt_is_failure(monkeypatch, body):
    requests = []
    transport(monkeypatch, httpx.Response(200, json=body), requests)
    assert not await client.post_event("call", {"call_sid": "call-one"})
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 404, 409, 429, 500, 503])
async def test_provider_faults_never_acknowledge_delivery(monkeypatch, status):
    requests = []
    transport(monkeypatch, httpx.Response(status, json={"persisted": True}), requests)
    assert not await client.post_event("call", {"call_sid": "call-one"})
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_unknown_endpoint_cannot_redirect_the_shared_secret(monkeypatch):
    requests = []
    transport(monkeypatch, httpx.Response(200, json={}), requests)
    assert not await client.post_event("../../external", {"call_sid": "call-one"})
    assert requests == []


def test_transcript_payload_preserves_the_actual_chunks():
    chunks = [{"speaker": "user", "text": "Please call tomorrow", "turn_index": 0}]
    payload = events.transcript_completed("call", "remote-call-id", "remote-lead-id", 1, chunks)
    assert payload["chunks"] == chunks and payload["chunk_count"] == 1
