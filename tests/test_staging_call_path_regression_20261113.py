import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from backend.lib import db

TENANT = "00000000-0000-0000-0000-000000000001"
LEAD = "00000000-0000-0000-0000-0000000000c1"
MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"


class LegacyColumnMissing(Exception):
    code = "42703"


class RecordingQuery:
    def __init__(self, log, table, data=None, error=None):
        self.log = log
        self.table = table
        self.data = data
        self.error = error

    def __getattr__(self, name):
        def chain(*args, **kwargs):
            self.log.append((self.table, name, args))
            return self
        return chain

    def execute(self):
        if self.error:
            raise self.error
        return SimpleNamespace(data=self.data)


def tenant_client(monkeypatch, data=None, error=None):
    log = []
    raw = SimpleNamespace(table=lambda name: RecordingQuery(log, name, data, error), rpc=MagicMock())
    monkeypatch.setattr(db, "_get_client", lambda: db.TenantClient(raw))
    return log, raw


class FakeRequest:
    def __init__(self, form, contexts=None):
        self._form = form
        self.app = SimpleNamespace(state=SimpleNamespace(call_contexts=contexts if contexts is not None else {}))

    async def form(self):
        return self._form


def test_campaign_lookup_stays_tenant_scoped(monkeypatch):
    monkeypatch.delenv("TENANT_ID", raising=False)
    log, _ = tenant_client(monkeypatch, data=[{"state": "running"}])
    assert db.campaign_is_running()
    assert ("campaigns", "eq", ("tenant_id", TENANT)) in log
    assert ("campaigns", "eq", ("id", "default")) in log


def test_legacy_campaign_schema_fails_closed_before_provider(monkeypatch):
    from backend.voice import outbound
    monkeypatch.setenv("OUTBOUND_ENABLED", "true")
    monkeypatch.delenv("TENANT_ID", raising=False)
    tenant_client(monkeypatch, error=LegacyColumnMissing("column campaigns.tenant_id does not exist"))
    with patch("backend.voice.outbound._make_call") as provider, patch("backend.voice.outbound.update_lead_call_outcome") as outcome, patch("backend.compliance.compliance.ComplianceEngine.check_call_allowed") as compliance:
        result = outbound.call_lead(LEAD)
    assert result == {"success": False, "reason": "campaign_state_unavailable"}
    provider.assert_not_called()
    outcome.assert_not_called()
    compliance.assert_not_called()


@pytest.mark.parametrize("value", [None, "", "   ", "\n"])
def test_unset_or_blank_tenant_uses_default_uuid(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("TENANT_ID", raising=False)
    else:
        monkeypatch.setenv("TENANT_ID", value)
    assert db.configured_tenant_id() == TENANT


@pytest.mark.parametrize("value", ["staging", "san-joaquin-house-buyers", "00000000-0000-0000-0000-00000000000Z", "00000000-0000-0000-0000-0000000000A1", "{00000000-0000-0000-0000-000000000001}", "0"])
def test_non_uuid_tenant_is_rejected_before_any_query(monkeypatch, value):
    monkeypatch.setenv("TENANT_ID", value)
    log, _ = tenant_client(monkeypatch, data=[])
    with pytest.raises(db.TenantConfigurationError):
        db.campaign_is_running()
    assert log == []


@pytest.mark.parametrize("lead_id", ["lead-test", "", "  ", "staging-lead", "123", None, "00000000-0000-0000-0000-00000000000g"])
def test_malformed_lead_id_is_denied_without_database_lookup(monkeypatch, lead_id):
    from backend.compliance.compliance import ComplianceEngine
    lookup = MagicMock()
    monkeypatch.setattr(db, "get_lead_with_property", lookup)
    assert ComplianceEngine().check_call_allowed(lead_id).reason == "invalid_lead_id"
    assert ComplianceEngine().check_sms_allowed(lead_id).reason == "invalid_lead_id"
    lookup.assert_not_called()


def test_invalid_tenant_configuration_is_named_and_denied(monkeypatch):
    from backend.compliance.compliance import ComplianceEngine
    monkeypatch.setenv("TENANT_ID", "staging")
    lookup = MagicMock()
    monkeypatch.setattr(db, "get_lead_with_property", lookup)
    result = ComplianceEngine().check_call_allowed(LEAD)
    assert (result.allowed, result.reason) == (False, "tenant_misconfigured")
    lookup.assert_not_called()


def test_database_uuid_rejection_still_fails_closed(monkeypatch):
    from backend.compliance.compliance import ComplianceEngine

    class InvalidText(Exception):
        code = "22P02"

    monkeypatch.delenv("TENANT_ID", raising=False)
    monkeypatch.setattr(db, "get_lead_with_property", MagicMock(side_effect=InvalidText("invalid input syntax for type uuid")))
    result = ComplianceEngine().check_call_allowed(LEAD)
    assert (result.allowed, result.reason) == (False, "compliance_unavailable")


def test_accepted_call_creates_correlated_row(monkeypatch):
    from backend.voice import outbound
    monkeypatch.setenv("OUTBOUND_ENABLED", "true")
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(outbound, "_get_redis_client", lambda: redis)
    monkeypatch.setattr(outbound, "_is_calling_hours", lambda: True)
    lead = {"id": LEAD, "properties": {"callable_phones": ["+15555550101"], "distress_score": 90}}
    lifecycle = MagicMock(return_value="row")
    with patch("backend.lib.db.campaign_is_running", return_value=True), patch("backend.compliance.compliance.ComplianceEngine.check_call_allowed", return_value=SimpleNamespace(allowed=True)), patch("backend.voice.outbound.get_lead_with_property", return_value=lead), patch("backend.voice.outbound._make_call", return_value={"call_sid": "CAaccepted", "status": "queued"}), patch("backend.voice.outbound.update_lead_call_outcome"), patch("backend.lib.db.record_call_lifecycle", lifecycle):
        result = outbound.call_lead(LEAD)
    assert result["success"]
    lifecycle.assert_called_once_with(LEAD, "CAaccepted", "outbound", "initiated")


def test_accepted_call_survives_row_write_failure_and_keeps_capacity(monkeypatch):
    from backend.voice import outbound
    monkeypatch.setenv("OUTBOUND_ENABLED", "true")
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(outbound, "_get_redis_client", lambda: redis)
    monkeypatch.setattr(outbound, "_is_calling_hours", lambda: True)
    lead = {"id": LEAD, "properties": {"callable_phones": ["+15555550101"], "distress_score": 90}}
    with patch("backend.lib.db.campaign_is_running", return_value=True), patch("backend.compliance.compliance.ComplianceEngine.check_call_allowed", return_value=SimpleNamespace(allowed=True)), patch("backend.voice.outbound.get_lead_with_property", return_value=lead), patch("backend.voice.outbound._make_call", return_value={"call_sid": "CAaccepted", "status": "queued"}), patch("backend.voice.outbound.update_lead_call_outcome"), patch("backend.lib.db.record_call_lifecycle", side_effect=RuntimeError("db down")):
        result = outbound.call_lead(LEAD)
    assert result["success"]
    assert redis.zcard(outbound._REDIS_CONCURRENT_KEY) == 1


@pytest.mark.parametrize("sequence", [
    ["queued", "ringing", "in-progress", "completed"],
    ["completed", "in-progress", "ringing", "queued"],
    ["no-answer", "no-answer", "no-answer"],
    ["ringing", "busy", "ringing", "busy"],
])
def test_every_outbound_status_is_recorded_and_terminal_outcome_once_per_callback(monkeypatch, sequence):
    from backend.voice import outbound_webhook
    lifecycle = MagicMock(return_value="row")
    outcome = MagicMock()
    monkeypatch.setattr(db, "record_call_lifecycle", lifecycle)
    monkeypatch.setattr(outbound_webhook, "update_lead_call_outcome", outcome)
    with patch("backend.voice.outbound._release_call_slot"), patch("backend.voice.outbound._schedule_retry_for_disposition"):
        for status in sequence:
            response = asyncio.run(outbound_webhook.handle_outbound_status(FakeRequest({"CallSid": "CAone", "CallStatus": status, "CallDuration": "8"}), LEAD))
            assert response.status_code == 200
    assert [c.args for c in lifecycle.call_args_list] == [(LEAD, "CAone", "outbound", status, 8) for status in sequence]
    assert outcome.call_count == sum(status in outbound_webhook._TERMINAL_STATUSES for status in sequence)


def test_outbound_status_persistence_failure_still_releases_capacity_and_requests_retry(monkeypatch):
    from backend.voice import outbound_webhook
    monkeypatch.setattr(db, "record_call_lifecycle", MagicMock(side_effect=RuntimeError("db down")))
    monkeypatch.setattr(outbound_webhook, "update_lead_call_outcome", MagicMock())
    with patch("backend.voice.outbound._release_call_slot") as release, patch("backend.voice.outbound._schedule_retry_for_disposition"):
        response = asyncio.run(outbound_webhook.handle_outbound_status(FakeRequest({"CallSid": "CAone", "CallStatus": "completed", "CallDuration": "8"}), LEAD))
    assert response.status_code == 500
    release.assert_called_once()


def test_inbound_status_records_row_with_context_lead_and_cleans_context_even_on_failure(monkeypatch):
    from backend.voice import webhook
    contexts = {"CAin": SimpleNamespace(lead_id=LEAD)}
    lifecycle = MagicMock(return_value="row")
    monkeypatch.setattr(db, "record_call_lifecycle", lifecycle)
    response = asyncio.run(webhook.handle_call_status(FakeRequest({"CallSid": "CAin", "CallStatus": "in-progress", "CallDuration": "3"}, contexts)))
    assert response.status_code == 200 and "CAin" in contexts
    lifecycle.assert_called_with(LEAD, "CAin", "inbound", "in-progress", 3)
    monkeypatch.setattr(db, "record_call_lifecycle", MagicMock(side_effect=RuntimeError("db down")))
    response = asyncio.run(webhook.handle_call_status(FakeRequest({"CallSid": "CAin", "CallStatus": "completed", "CallDuration": "9"}, contexts)))
    assert response.status_code == 500
    assert "CAin" not in contexts


def test_inbound_status_without_known_lead_still_records_row(monkeypatch):
    from backend.voice import webhook
    lifecycle = MagicMock(return_value="row")
    monkeypatch.setattr(db, "record_call_lifecycle", lifecycle)
    asyncio.run(webhook.handle_call_status(FakeRequest({"CallSid": "CAanon", "CallStatus": "completed", "CallDuration": "x"}, {"CAanon": SimpleNamespace(lead_id="not-a-uuid")})))
    lifecycle.assert_called_once_with(None, "CAanon", "inbound", "completed", 0)


def test_lifecycle_and_recording_rpcs_carry_server_tenant_and_validate_identity(monkeypatch):
    monkeypatch.delenv("TENANT_ID", raising=False)
    _, raw = tenant_client(monkeypatch)
    raw.rpc.return_value.execute.return_value = SimpleNamespace(data="row")
    assert db.record_call_lifecycle(LEAD.upper(), "CAone", "outbound", "ringing", -4) == "row"
    assert raw.rpc.call_args.args == ("record_call_lifecycle", {"p_tenant_id": TENANT, "p_lead_id": LEAD, "p_call_sid": "CAone", "p_direction": "outbound", "p_status": "ringing", "p_duration": 0})
    assert db.save_recording_metadata(LEAD, "CAone", "https://example.invalid/r", "RE1", 61) == "row"
    assert raw.rpc.call_args.args[0] == "record_call_recording"
    assert raw.rpc.call_args.args[1]["p_tenant_id"] == TENANT
    raw.rpc.reset_mock()
    for bad in (("lead-test", "CAone", "outbound", "ringing"), (LEAD, "CA one", "outbound", "ringing"), (LEAD, "", "outbound", "ringing"), (LEAD, "CAone", "sideways", "ringing"), (LEAD, "CAone", "outbound", "exploded")):
        with pytest.raises(ValueError):
            db.record_call_lifecycle(*bad)
    with pytest.raises(ValueError):
        db.save_recording_metadata("lead-test", "CAone", "https://example.invalid/r", "RE1", 1)
    raw.rpc.assert_not_called()
    raw.rpc.return_value.execute.return_value = SimpleNamespace(data=None)
    with pytest.raises(RuntimeError):
        db.record_call_lifecycle(LEAD, "CAone", "outbound", "ringing")


def test_end_of_call_insert_correlates_to_existing_row(monkeypatch):
    log, _ = tenant_client(monkeypatch, data=[{"id": "row"}])
    lifecycle = MagicMock(return_value="row")
    monkeypatch.setattr(db, "record_call_lifecycle", lifecycle)
    assert db.insert_call({"lead_id": LEAD, "signalwire_call_id": "CAone", "direction": "outbound", "transcript": "hi", "call_disposition": "WARM", "created_at": "x"}) == "row"
    lifecycle.assert_called_once_with(LEAD, "CAone", "outbound", None)
    assert ("calls", "update", ({"transcript": "hi", "call_disposition": "WARM"},)) in log
    assert ("calls", "eq", ("id", "row")) in log
    assert not any(entry[1] == "insert" for entry in log)


def test_tables_created_after_tenant_migration_declare_tenant_scope():
    files = sorted(MIGRATIONS.glob("*.sql"))
    tenant_migration = next(f.name for f in files if f.name.startswith("20260911_tenant"))
    for table in sorted(db.TABLES):
        created = [f for f in files if re.search(rf"create table (if not exists )?(public\.)?{table}\s*\(", f.read_text(), re.I)]
        if not created or created[0].name < tenant_migration:
            continue
        body = re.search(rf"create table (if not exists )?(public\.)?{table}\s*\((.*?)\n\);", created[0].read_text(), re.I | re.S).group(3)
        if "tenant_id" in body:
            continue
        later = [f.name for f in files if f.name >= created[0].name and re.search(rf"alter table (if exists )?(public\.)?{table}\s+add column (if not exists )?tenant_id", f.read_text(), re.I)]
        assert later, f"{table} is tenant-scoped in db.TABLES but no migration gives it tenant_id"
