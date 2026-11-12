from __future__ import annotations

import hashlib
import hmac
import secrets


_LOG_REFERENCE_KEY = secrets.token_bytes(32)


def pii_ref(value: object, kind: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return f"{kind}:missing"
    digest = hmac.new(_LOG_REFERENCE_KEY, normalized.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
    return f"{kind}:{digest}"


def error_type(error: BaseException) -> str:
    return type(error).__name__
