import asyncio
import sys
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.modules.setdefault("loguru", SimpleNamespace(logger=MagicMock()))

from backend.voice.webhook import _preload_and_store
from backend.voice.execution_context import DEFAULT_TENANT_ID, resolve_for_stop


def test_failed_preload_preserves_provider_phone_for_stop_request():
    app = SimpleNamespace(state=SimpleNamespace())
    preloader = ModuleType("backend.voice.preloader")
    preloader.preload_boss_context = MagicMock()
    preloader.preload_call_context = MagicMock(side_effect=RuntimeError("database unavailable"))
    with patch.dict(sys.modules, {"backend.voice.preloader": preloader}):
        asyncio.run(_preload_and_store(app, "call-1", "+1 (209) 881-4144"))

    assert app.state.call_contexts["call-1"]["normalized_phone"] == "2098814144"


def test_stop_request_uses_database_default_tenant_when_unconfigured(monkeypatch):
    monkeypatch.delenv("TENANT_ID", raising=False)
    context = SimpleNamespace(lead_id="", _call_sid="call-1", seller_phone="+12098814144")

    resolved = resolve_for_stop(context)

    assert resolved.tenant_id == DEFAULT_TENANT_ID
