import concurrent.futures
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.lib import db


TENANT = "00000000-0000-0000-0000-000000000001"
PHONE = "+12095550123"


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "suppression.sqlite3"
    monkeypatch.setenv("CONTACT_SUPPRESSION_PATH", str(path))
    monkeypatch.setenv("TENANT_ID", TENANT)
    monkeypatch.setattr(db, "_get_client", MagicMock(side_effect=RuntimeError("Datastore outage")))
    return path


def due(path):
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE contact_suppression SET due=0,leased_until=0")


class Remote:
    def __init__(self):
        self.tables = {"dnc_list": {}, "suppression_events": {}}
        self.writes = 0
        self.lose_ack = False
        self.on_write = None

    def table(self, name):
        remote = self
        class Query:
            def __init__(self):
                self.filters = {}
                self.row = None
                self.operation = "select"

            def select(self, fields):
                return self

            def eq(self, field, value):
                self.filters[field] = value
                return self

            def limit(self, value):
                return self

            def upsert(self, row, on_conflict):
                assert name == "dnc_list"
                self.row = row
                self.operation = "upsert"
                return self

            def insert(self, row):
                self.row = row
                self.operation = "insert"
                return self

            def execute(self):
                if self.row:
                    key = self.row.get("id") or self.row["phone"]
                    if self.operation == "insert":
                        assert key not in remote.tables[name]
                    remote.tables[name][key] = dict(self.row)
                    if name == "suppression_events":
                        remote.writes += 1
                        if remote.on_write:
                            remote.on_write()
                        if remote.lose_ack:
                            remote.lose_ack = False
                            raise RuntimeError("Lost acknowledgement after committed insert")
                    return SimpleNamespace(data=[dict(self.row)])
                rows = [row for row in remote.tables[name].values() if all(row.get(k) == v for k, v in self.filters.items())]
                return SimpleNamespace(data=rows)
        return Query()


def test_stop_is_durable_without_remote_and_survives_hard_process_exit(journal):
    code = f"from backend.lib import db; import os; db.stage_contact_suppression('{TENANT}', '{PHONE}'); os._exit(7)"
    result = subprocess.run([sys.executable, "-c", code], env=dict(os.environ), capture_output=True, timeout=30)
    assert result.returncode == 7, result.stderr.decode()
    assert db.phone_is_do_not_call("(209) 555-0123")
    db._get_client.assert_not_called()
    assert journal.stat().st_mode & 0o777 == 0o600


def test_duplicate_and_concurrent_stop_requests_have_one_recovery_identity(journal):
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: db.stage_contact_suppression(TENANT, PHONE), range(100)))
    assert all(results)
    assert db.suppression_journal_health() == {"total": 1, "pending": 1}


def test_outage_retry_preserves_phone_block_after_recovery(journal, monkeypatch):
    db.stage_contact_suppression(TENANT, PHONE, "first-lead")
    assert db.recover_contact_suppressions()["retrying"] == 1
    assert db.phone_is_do_not_call(PHONE)
    assert db.recover_contact_suppressions()["recovered"] == 0
    remote = Remote()
    monkeypatch.setattr(db, "_get_client", lambda: remote)
    due(journal)
    assert db.recover_contact_suppressions()["recovered"] == 1
    assert db.suppression_journal_health() == {"total": 1, "pending": 0}
    assert db.local_phone_suppressed(PHONE)
    assert db.stage_contact_suppression(TENANT, PHONE, "alternate-lead")
    assert db.phone_is_do_not_call(PHONE)
    assert db.recover_contact_suppressions()["recovered"] == 0


def test_commit_then_lost_ack_reuses_append_only_remote_evidence(journal, monkeypatch):
    db.stage_contact_suppression(TENANT, PHONE)
    remote = Remote()
    remote.lose_ack = True
    monkeypatch.setattr(db, "_get_client", lambda: remote)
    assert db.recover_contact_suppressions()["retrying"] == 1
    due(journal)
    assert db.recover_contact_suppressions()["recovered"] == 1
    assert remote.writes == 1


def test_stale_worker_cannot_mark_new_generation_complete(journal, monkeypatch):
    db.stage_contact_suppression(TENANT, PHONE)
    remote = Remote()
    def replace_owner():
        with sqlite3.connect(journal) as connection:
            connection.execute("UPDATE contact_suppression SET lease='new-generation'")
    remote.on_write = replace_owner
    monkeypatch.setattr(db, "_get_client", lambda: remote)
    assert db.recover_contact_suppressions()["unowned"] == 1
    assert db.suppression_journal_health()["pending"] == 1
    assert db.local_phone_suppressed(PHONE)


def test_tenant_switch_does_not_forward_previous_business_evidence(journal, monkeypatch):
    db.stage_contact_suppression(TENANT, PHONE)
    monkeypatch.setenv("TENANT_ID", "00000000-0000-0000-0000-000000000002")
    assert db.recover_contact_suppressions()["recovered"] == 0
    db._get_client.assert_not_called()


def test_mismatched_remote_receipt_never_completes_pending_recovery(journal, monkeypatch):
    db.stage_contact_suppression(TENANT, PHONE)
    with sqlite3.connect(journal) as connection:
        event_id = connection.execute("SELECT event_id FROM contact_suppression").fetchone()[0]
    remote = Remote()
    remote.tables["suppression_events"][event_id] = {"id": event_id, "tenant_id": TENANT, "action": "suppressed", "contact_point": "+12095550999"}
    monkeypatch.setattr(db, "_get_client", lambda: remote)
    assert db.recover_contact_suppressions()["retrying"] == 1
    assert db.suppression_journal_health()["pending"] == 1
    assert db.local_phone_suppressed(PHONE)


def test_sms_stop_is_saved_before_lookup_or_message_logging(journal, monkeypatch):
    from backend.alerts import drip
    monkeypatch.setattr(drip, "get_lead_by_owner_phone", MagicMock(side_effect=RuntimeError("Outage")))
    logging = MagicMock(side_effect=AssertionError("STOP must precede inbound logging"))
    monkeypatch.setattr(drip, "insert_sms", logging)
    assert drip.handle_inbound_reply(PHONE, "STOP", "provider-sid") == "opted_out"
    assert db.local_phone_suppressed(PHONE)
    logging.assert_not_called()


def test_all_sms_paths_deny_suppressed_phone_even_without_lead_or_with_hours_bypass(journal, monkeypatch):
    from backend.alerts import sms
    db.stage_contact_suppression(TENANT, PHONE)
    provider = MagicMock(side_effect=AssertionError("Suppressed phone reached provider"))
    monkeypatch.setattr(sms, "signalwire_post", provider)
    assert not sms.send_sms(PHONE, "synthetic", lead_id="other-lead", bypass_hours=True)
    assert not sms.send_sms(PHONE, "synthetic", bypass_hours=True)
    provider.assert_not_called()


def test_call_adapter_denies_suppressed_phone_before_provider_configuration(journal):
    from backend.voice import outbound
    db.stage_contact_suppression(TENANT, PHONE)
    with pytest.raises(RuntimeError, match="suppressed"):
        outbound._make_call(PHONE, "other-lead")


def test_unavailable_local_journal_denies_sms(journal, monkeypatch):
    from backend.alerts import sms
    monkeypatch.setenv("CONTACT_SUPPRESSION_PATH", "relative.sqlite3")
    provider = MagicMock()
    monkeypatch.setattr(sms, "signalwire_post", provider)
    assert not sms.send_sms(PHONE, "synthetic", bypass_hours=True)
    provider.assert_not_called()


def test_unacknowledged_sms_stop_does_not_claim_unsubscribe(monkeypatch):
    from backend.alerts import drip
    monkeypatch.delenv("CONTACT_SUPPRESSION_PATH", raising=False)
    monkeypatch.setattr(db, "add_to_dnc", lambda *args: None)
    monkeypatch.setattr(db, "phone_is_do_not_call", lambda phone: False)
    with pytest.raises(RuntimeError, match="not acknowledged"):
        drip.handle_inbound_reply(PHONE, "STOP", "provider-sid")


@pytest.mark.asyncio
async def test_outbound_startup_requires_persistent_suppression_journal(monkeypatch):
    from backend.api import main
    monkeypatch.setenv("OUTBOUND_ENABLED", "true")
    monkeypatch.delenv("CONTACT_SUPPRESSION_PATH", raising=False)
    with pytest.raises(RuntimeError, match="persistent path"):
        async with main.lifespan(main.app):
            pytest.fail("Outbound startup accepted missing durable suppression")


@pytest.mark.parametrize("phone", ["", "wrong", "+12", "+12095550123extension4"])
def test_invalid_phone_never_creates_suppression(journal, phone):
    with pytest.raises(ValueError):
        db.stage_contact_suppression(TENANT, phone)
    assert not journal.exists()
