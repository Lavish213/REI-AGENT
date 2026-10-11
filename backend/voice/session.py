from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaSession:
    call_sid: str
    stream_sid: str


async def read_media_session(websocket, expected_call_sid: str | None = None, authorized_scope: str | None = None) -> MediaSession:
    async def read_start():
        for _ in range(8):
            payload = json.loads(await websocket.receive_text())
            event = payload.get("event")
            if event == "connected":
                continue
            if event != "start":
                raise ValueError("Expected a media start event")
            start = payload.get("start", {})
            call_sid = start.get("callSid") or payload.get("callSid")
            stream_sid = start.get("streamSid") or payload.get("streamSid")
            if not call_sid or not stream_sid:
                raise ValueError("Media start is missing callSid or streamSid")
            if expected_call_sid and call_sid != expected_call_sid:
                raise ValueError("Media call ID does not match the authorized call")
            if authorized_scope and not validate_stream_token((start.get("customParameters") or {}).get("authorization", ""), authorized_scope):
                raise ValueError("Unauthorized media stream")
            media = start.get("mediaFormat", {})
            if media and (media.get("encoding") != "audio/x-mulaw" or int(media.get("sampleRate", 0)) != 8000 or int(media.get("channels", 0)) != 1):
                raise ValueError("This transport requires mono PCMU at 8000 Hz")
            return MediaSession(call_sid=call_sid, stream_sid=stream_sid)
        raise ValueError("Media start event missing")

    return await asyncio.wait_for(read_start(), timeout=5.0)


def issue_stream_token(scope: str) -> str:
    import base64
    import hashlib
    import hmac
    import os
    import time
    key = os.environ["SIGNALWIRE_SIGNING_KEY"]
    if not key:
        raise ValueError("SignalWire signing key is required")
    payload = base64.urlsafe_b64encode(json.dumps({"scope": scope, "expires": int(time.time()) + 60}).encode()).decode()
    digest = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + digest


def validate_stream_token(token: str, scope: str) -> bool:
    import base64
    import hashlib
    import hmac
    import os
    import time
    try:
        payload, signature = token.split(".", 1)
        key = os.environ["SIGNALWIRE_SIGNING_KEY"]
        if not key:
            return False
        expected = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data["scope"] == scope and int(time.time()) <= data["expires"] <= int(time.time()) + 60
    except (ValueError, KeyError, TypeError):
        return False
