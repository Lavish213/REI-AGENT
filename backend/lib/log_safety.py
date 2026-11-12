from __future__ import annotations

import hashlib


def pii_ref(value: object, kind: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return f"{kind}:missing"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{digest}"


def error_type(error: BaseException) -> str:
    return type(error).__name__
