from __future__ import annotations

import base64
import hashlib
import hmac
import os
from urllib.parse import parse_qs

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def valid_signalwire_signature(key: str, signature: str, url: str, body: bytes) -> bool:
    if not key or not signature or not signature.isascii():
        return False
    raw = url.encode() + body
    raw_signature = hmac.new(key.encode(), raw, hashlib.sha1).hexdigest()
    if hmac.compare_digest(raw_signature, signature):
        return True
    try:
        params = parse_qs(body.decode(), keep_blank_values=True)
        canonical = url + "".join(name + value for name in sorted(params) for value in sorted(set(params[name])))
    except (UnicodeError, ValueError):
        return False
    expected = base64.b64encode(hmac.new(key.encode(), canonical.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)


class OperatorAuthentication(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/voice/") or path.startswith("/api/sms/inbound"):
            public = os.environ.get("PUBLIC_URL", "").rstrip("/")
            url = public + path + ("?" + request.url.query if request.url.query else "")
            signature = request.headers.get("x-signalwire-signature", "") or request.headers.get("x-twilio-signature", "")
            if not public or not valid_signalwire_signature(os.environ.get("SIGNALWIRE_SIGNING_KEY", ""), signature, url, await request.body()):
                return JSONResponse({"detail": "Invalid webhook signature"}, status_code=403)
            return await call_next(request)
        if path == "/healthz":
            return JSONResponse({"status": "ok"})
        if path in ("/api/email/webhook", "/api/email/unsubscribe"):
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
