from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from urllib.parse import parse_qs

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


logger = logging.getLogger(__name__)


def valid_signalwire_signature(key: str, signature: str, url: str, body: bytes) -> bool:
    if not key or not signature or not signature.isascii():
        return False
    raw = url.encode() + body
    raw_digest = hmac.new(key.encode(), raw, hashlib.sha1)
    if hmac.compare_digest(raw_digest.hexdigest(), signature) or hmac.compare_digest(
        base64.b64encode(raw_digest.digest()).decode(), signature
    ):
        return True
    try:
        params = parse_qs(body.decode(), keep_blank_values=True)
        canonical = url + "".join(name + value for name in sorted(params) for value in sorted(set(params[name])))
    except (UnicodeError, ValueError):
        return False
    expected = base64.b64encode(hmac.new(key.encode(), canonical.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)


def valid_signalwire_sha256_signature(key: str, signature: str, url: str, body: bytes) -> bool:
    if not key or not signature or not signature.isascii():
        return False
    digest = hmac.new(key.encode(), url.encode() + body, hashlib.sha256)
    return hmac.compare_digest(digest.hexdigest(), signature) or hmac.compare_digest(
        base64.b64encode(digest.digest()).decode(), signature
    )


class OperatorAuthentication(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in {"/api/operations/callback", "/api/operations/command", "/api/operations/integration", "/api/operations/delivery"} or path.startswith("/api/operations/email-holds") or path.startswith("/api/operations/price-reviews") or path.startswith("/api/operations/candidates") or path.startswith("/api/health/workflow-recovery") or path == "/api/health/data-quality" or path.startswith("/api/operations/rentcast/") or path in ("/api/operations/mail-list", "/api/operations/import-csv"):
            secret = os.environ.get("SOURCE_COMMAND_SECRET", "")
            supplied = request.headers.get("x-source-command-secret", "")
            if len(secret) < 32 or not hmac.compare_digest(secret.encode(), supplied.encode()):
                return JSONResponse({"detail": "Source service authentication required"}, status_code=401)
            return await call_next(request)
        if path == "/api/ingest/bob/brief-created":
            secret = os.environ.get("KARPATHYS_WEBHOOK_SECRET", "")
            supplied = request.headers.get("x-karpathys-secret", "")
            if not secret or not supplied or not hmac.compare_digest(secret.encode(), supplied.encode()):
                return JSONResponse({"detail": "Service authentication required"}, status_code=401)
            return await call_next(request)
        if path.startswith("/api/voice/") or path.startswith("/api/sms/inbound"):
            public = os.environ.get("PUBLIC_URL", "").rstrip("/")
            url = public + path + ("?" + request.url.query if request.url.query else "")
            key = os.environ.get("SIGNALWIRE_SIGNING_KEY", "")
            compatibility_token = os.environ.get("SIGNALWIRE_TOKEN", "")
            body = await request.body()
            sha256_signature = request.headers.get("x-signalwire-sha256-signature", "")
            signature = request.headers.get("x-signalwire-signature", "") or request.headers.get("x-twilio-signature", "")
            sha256_valid = valid_signalwire_sha256_signature(key, sha256_signature, url, body)
            compatibility_valid = valid_signalwire_signature(key, signature, url, body)
            signature_valid = sha256_valid or compatibility_valid
            if not signature_valid:
                forwarded_proto = request.headers.get("x-forwarded-proto", "")
                forwarded_host = request.headers.get("x-forwarded-host", "")
                request_url = str(request.url)
                logger.warning(
                    "signalwire_signature_rejected path=%s public_set=%s key_set=%s "
                    "sha256_header=%s sha256_length=%d compatibility_header=%s compatibility_length=%d "
                    "content_type=%s body_length=%d forwarded_proto=%s forwarded_host_matches=%s "
                    "public_sha256_valid=%s public_compatibility_valid=%s "
                    "request_url_sha256_valid=%s request_url_compatibility_valid=%s "
                    "token_sha256_valid=%s token_compatibility_valid=%s",
                    path,
                    bool(public),
                    bool(key),
                    bool(sha256_signature),
                    len(sha256_signature),
                    bool(signature),
                    len(signature),
                    request.headers.get("content-type", "").split(";", 1)[0],
                    len(body),
                    forwarded_proto,
                    bool(forwarded_host and forwarded_host == request.url.hostname),
                    sha256_valid,
                    compatibility_valid,
                    valid_signalwire_sha256_signature(key, sha256_signature, request_url, body),
                    valid_signalwire_signature(key, signature, request_url, body),
                    valid_signalwire_sha256_signature(compatibility_token, sha256_signature, url, body),
                    valid_signalwire_signature(compatibility_token, signature, url, body),
                )
            if not public or not signature_valid:
                return JSONResponse({"detail": "Invalid webhook signature"}, status_code=403)
            return await call_next(request)
        if path == "/healthz":
            return JSONResponse({"status": "ok"})
        if path in ("/api/email/webhook", "/api/email/unsubscribe", "/api/email/inbound"):
            return await call_next(request)
        supplied = request.headers.get("authorization", "")
        token = supplied.removeprefix("Bearer ") if supplied.startswith("Bearer ") else ""
        admin_token = os.environ.get("OPERATOR_API_TOKEN", "")
        if token and not token.isascii():
            return JSONResponse({"detail": "Operator authentication required"}, status_code=401)
        if token and admin_token and hmac.compare_digest(token.encode(), admin_token.encode()):
            return await call_next(request)
        if token:
            try:
                import asyncio
                from backend.lib.db import get_operator_user
                user = await asyncio.to_thread(get_operator_user, token)
                if user:
                    request.state.operator = user
                    return await call_next(request)
            except Exception:
                pass
        return JSONResponse({"detail": "Operator authentication required"}, status_code=401)
