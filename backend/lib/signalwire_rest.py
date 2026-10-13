from __future__ import annotations

import os
import re

import httpx


def signalwire_post(resource: str, data: dict) -> dict:
    space = os.environ["SIGNALWIRE_SPACE"].removeprefix("https://").rstrip("/")
    if not re.fullmatch(r"[a-zA-Z0-9-]+\.signalwire\.com", space):
        raise ValueError("Invalid SignalWire space hostname")
    project = os.environ["SIGNALWIRE_PROJECT_ID"]
    token = os.environ["SIGNALWIRE_TOKEN"]
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            f"https://{space}/api/laml/2010-04-01/Accounts/{project}/{resource}",
            auth=(project, token),
            data=data,
        )
        response.raise_for_status()
        result = response.json()
    if not result.get("sid"):
        raise RuntimeError("SignalWire did not acknowledge the request")
    return result
