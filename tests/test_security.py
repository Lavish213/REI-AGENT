from __future__ import annotations

import hashlib
import hmac
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.security import OperatorAuthentication


def test_call_webhook_accepts_signalwire_sha256_signature(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://example.com")
    monkeypatch.setenv("SIGNALWIRE_SIGNING_KEY", "key")
    app = FastAPI()
    app.add_middleware(OperatorAuthentication)

    @app.post("/api/voice/inbound")
    async def inbound():
        return {"ok": True}

    body = b"CallSid=call&From=%2B15555550100"
    url = "https://example.com/api/voice/inbound"
    signature = hmac.new(b"key", url.encode() + body, hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        response = client.post(
            "/api/voice/inbound",
            content=body,
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "x-signalwire-sha256-signature": signature,
            },
        )

    assert response.status_code == 200


def test_call_webhook_accepts_base64_raw_body_signatures(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://example.com")
    monkeypatch.setenv("SIGNALWIRE_SIGNING_KEY", "key")
    app = FastAPI()
    app.add_middleware(OperatorAuthentication)

    @app.post("/api/voice/inbound")
    async def inbound():
        return {"ok": True}

    body = b"CallSid=call&From=%2B15555550100"
    url = "https://example.com/api/voice/inbound"
    raw = url.encode() + body
    sha256_signature = base64.b64encode(hmac.new(b"key", raw, hashlib.sha256).digest()).decode()
    sha1_signature = base64.b64encode(hmac.new(b"key", raw, hashlib.sha1).digest()).decode()
    with TestClient(app) as client:
        sha256_response = client.post(
            "/api/voice/inbound",
            content=body,
            headers={"x-signalwire-sha256-signature": sha256_signature},
        )
        sha1_response = client.post(
            "/api/voice/inbound",
            content=body,
            headers={"x-signalwire-signature": sha1_signature},
        )

    assert sha256_response.status_code == 200
    assert sha1_response.status_code == 200


def test_call_webhook_falls_back_to_valid_compatibility_signature(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://example.com")
    monkeypatch.setenv("SIGNALWIRE_SIGNING_KEY", "key")
    app = FastAPI()
    app.add_middleware(OperatorAuthentication)

    @app.post("/api/voice/inbound")
    async def inbound():
        return {"ok": True}

    body = b"CallSid=call&From=%2B15555550100"
    url = "https://example.com/api/voice/inbound"
    canonical = url + "CallSidcallFrom+15555550100"
    signature = base64.b64encode(hmac.new(b"key", canonical.encode(), hashlib.sha1).digest()).decode()
    with TestClient(app) as client:
        response = client.post(
            "/api/voice/inbound",
            content=body,
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "x-signalwire-sha256-signature": "invalid",
                "x-signalwire-signature": signature,
            },
        )

    assert response.status_code == 200
