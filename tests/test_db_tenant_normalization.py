import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.modules.setdefault("loguru", SimpleNamespace(logger=MagicMock()))
sys.modules.setdefault(
    "supabase",
    SimpleNamespace(create_client=MagicMock(), Client=object, ClientOptions=MagicMock()),
)

from backend.lib import db


def test_tenant_client_normalizes_configured_tenant_whitespace(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "00000000-0000-0000-0000-0000000000a1\n")

    class Query:
        def upsert(self, payload, **_kwargs):
            assert payload["tenant_id"] == "00000000-0000-0000-0000-0000000000a1"
            return self

    client = db.TenantClient(SimpleNamespace(table=lambda _: Query()))
    client.table("dnc_list").upsert({"tenant_id": "00000000-0000-0000-0000-0000000000a1", "phone": "+12098814144"})
