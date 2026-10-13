from types import SimpleNamespace
from unittest.mock import patch

import fakeredis
import httpx
import pytest

from backend.voice import outbound


@pytest.fixture
def provider_env(monkeypatch):
    for name, value in {"SIGNALWIRE_PROJECT_ID": "project-test", "SIGNALWIRE_TOKEN": "token-test", "SIGNALWIRE_PHONE": "+15555550100", "SIGNALWIRE_SPACE": "test.signalwire.com", "PUBLIC_URL": "https://example.test"}.items():
        monkeypatch.setenv(name, value)


def dial_with_transport(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with patch.object(outbound.httpx, "Client", return_value=client), patch("backend.alerts.phone_pool.pick_number_for_lead", return_value="+15555550100"):
        return outbound._make_call("+15555550101", "lead-test")


@pytest.mark.parametrize("payload", [{"sid": "CA-accepted", "status": "queued"}, {"call_sid": "CA-accepted", "status": "queued"}])
def test_provider_request_and_json_acknowledgement(provider_env, payload):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(201, json=payload)
    assert dial_with_transport(handler) == {"call_sid": "CA-accepted", "status": "queued"}
    assert requests[0].url.host == "test.signalwire.com"
    assert b"StatusCallback=" in requests[0].content
    assert b"RecordingStatusCallback=" in requests[0].content
    assert requests[0].extensions["timeout"]["read"] == 20


def test_provider_xml_acknowledgement(provider_env):
    result = dial_with_transport(lambda request: httpx.Response(201, text="<Response><Sid>CA-xml</Sid><Status>queued</Status></Response>"))
    assert result["call_sid"] == "CA-xml"


@pytest.mark.parametrize("payload", [{}, {"sid": True}, {"sid": []}, {"sid": "CA/bad"}, {"sid": " "}, {"sid": "x" * 129}, []])
def test_missing_or_poisoned_provider_acknowledgement_is_uncertain(provider_env, payload):
    with pytest.raises(outbound.ProviderCallUncertainError):
        dial_with_transport(lambda request: httpx.Response(201, json=payload))


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_failure_is_not_proof_that_dial_was_rejected(provider_env, status):
    with pytest.raises(outbound.ProviderCallUncertainError):
        dial_with_transport(lambda request: httpx.Response(status))


@pytest.mark.parametrize("status", [400, 401, 403, 422, 429])
def test_explicit_rejection_is_reported(provider_env, status):
    with pytest.raises(httpx.HTTPStatusError):
        dial_with_transport(lambda request: httpx.Response(status))


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout, httpx.ReadError])
def test_transport_loss_requires_reconciliation(provider_env, error):
    def handler(request):
        raise error("Injected transport loss", request=request)
    with pytest.raises(outbound.ProviderCallUncertainError):
        dial_with_transport(handler)


def test_uncertain_dial_does_not_free_capacity_or_redial(monkeypatch):
    monkeypatch.setenv("OUTBOUND_ENABLED", "true")
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(outbound, "_get_redis_client", lambda: client)
    monkeypatch.setattr(outbound, "_is_calling_hours", lambda: True)
    lead = {"id": "lead-test", "properties": {"callable_phones": ["+15555550101"], "distress_score": 90}}
    with patch("backend.lib.db.campaign_is_running", return_value=True), patch("backend.compliance.compliance.ComplianceEngine.check_call_allowed", return_value=SimpleNamespace(allowed=True)), patch.object(outbound, "get_lead_with_property", return_value=lead), patch.object(outbound, "_make_call", side_effect=outbound.ProviderCallUncertainError("Lost acknowledgement")) as dial:
        result = outbound.call_lead("lead-test")
        second = outbound.call_lead("lead-test")
    assert not result["success"]
    assert result["requires_reconciliation"]
    assert second["reason"] == "call_in_progress"
    assert dial.call_count == 1
    assert client.zcard(outbound._REDIS_CONCURRENT_KEY) == 1


def test_active_lookup_preserves_expired_generation_for_atomic_cleanup(monkeypatch):
    import time
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(outbound, "_get_redis_client", lambda: client)
    assert outbound._acquire_call_slot("old", "old-generation")
    assert outbound._bind_call_slot("old", "old-generation", "CA-old")
    client.zadd(outbound._REDIS_CONCURRENT_KEY, {"old": time.time() - 1})
    assert not outbound._check_active_call("old")
    assert client.zscore(outbound._REDIS_CONCURRENT_KEY, "old") is not None
    assert outbound._acquire_call_slot("new", "new-generation")
    assert client.hget(outbound._REDIS_OWNERS_KEY, "old") is None
    assert client.hget(outbound._REDIS_CALLS_KEY, "old") is None
