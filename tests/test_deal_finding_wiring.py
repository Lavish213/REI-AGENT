import pytest

from backend.lib import db


class TestOrphanedScrapersAreWired:
    def test_tax_scraper_has_a_persisting_entrypoint(self):
        from backend.scout import tax_scraper
        assert callable(tax_scraper.run_tax_scraper)

    def test_tax_scraper_is_in_the_scout_cycle(self):
        import inspect
        from backend.scout import cron
        assert "run_tax_scraper" in inspect.getsource(cron.run_scout_cycle)

    def test_tax_scraper_is_in_the_standalone_scheduler(self):
        import inspect
        from backend.scout import cron
        assert "run_tax_scraper" in inspect.getsource(cron.start_scheduler)

    def test_court_and_buyer_discovery_have_scheduled_jobs(self):
        import inspect
        from backend.api import main
        source = inspect.getsource(main)
        assert 'id="court_scrape"' in source
        assert 'id="buyer_discovery"' in source

    def test_weekly_jobs_are_weekly_not_daily(self):
        import inspect
        from backend.api import main
        source = inspect.getsource(main)
        assert source.count('day_of_week="mon"') >= 2


class TestTaxCandidatePersistence:
    def _rows(self, monkeypatch, scraped):
        saved = []
        monkeypatch.setattr(db, "save_source_candidate",
                            lambda source, payload: saved.append((source, payload)) or "id-1",
                            raising=False)
        from backend.scout import tax_scraper
        monkeypatch.setattr(tax_scraper, "scrape_tax_delinquent", lambda: scraped)
        return saved, tax_scraper.run_tax_scraper()

    def test_candidate_gets_an_attributable_source_ref(self, monkeypatch):
        saved, count = self._rows(monkeypatch, [{"apn": "094220390", "address": "7313 Tristan Cir"}])
        assert count == 1
        source, payload = saved[0]
        assert source == "tax_delinquent"
        assert payload["source_ref"] == "sjgov:ttc-public-auction:094220390"

    def test_source_ref_is_required_by_the_persistence_layer(self, monkeypatch):
        saved, _ = self._rows(monkeypatch, [{"apn": "094220390"}])
        assert saved[0][1].get("source_ref")

    def test_candidate_without_apn_is_skipped_not_guessed(self, monkeypatch):
        saved, count = self._rows(monkeypatch, [{"address": "no apn here"}])
        assert count == 0
        assert saved == []

    def test_one_bad_candidate_does_not_abort_the_run(self, monkeypatch):
        calls = []

        def flaky(source, payload):
            calls.append(payload["apn"])
            if payload["apn"] == "bad":
                raise RuntimeError("persistence down")
            return "id"

        monkeypatch.setattr(db, "save_source_candidate", flaky, raising=False)
        from backend.scout import tax_scraper
        monkeypatch.setattr(tax_scraper, "scrape_tax_delinquent",
                            lambda: [{"apn": "good1"}, {"apn": "bad"}, {"apn": "good2"}])
        assert tax_scraper.run_tax_scraper() == 2
        assert calls == ["good1", "bad", "good2"]

    def test_payload_is_not_mutated(self, monkeypatch):
        original = {"apn": "094220390", "address": "x"}
        saved, _ = self._rows(monkeypatch, [original])
        assert "source_ref" not in original
        assert saved[0][1]["source_ref"]


class TestOutboundQueuePriority:
    def _queue(self, monkeypatch, rows):
        class Resp:
            data = rows

        class Q:
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def or_(self, *a, **k): return self
            def order(self, *a, **k): return self
            def limit(self, *a, **k): return self
            def execute(self): return Resp()

        monkeypatch.setattr(db, "_get_client", lambda: type("C", (), {"table": lambda s, n: Q()})())
        return db.get_leads_for_outbound(min_score=50)

    def _lead(self, lead_id, score, **flags):
        row = {"id": lead_id, "properties": {"distress_score": score,
               "estimated_arv": 40000000, "callable_phones": ["+12094771234"]}}
        row.update(flags)
        return row

    def test_priority_callback_outranks_a_higher_distress_score(self, monkeypatch):
        rows = [self._lead("cold-90", 90), self._lead("callback-55", 55, priority_callback=True)]
        order = [r["id"] for r in self._queue(monkeypatch, rows)]
        assert order[0] == "callback-55", "a seller who asked for a callback must be called first"

    def test_escalated_outranks_score_but_not_callback(self, monkeypatch):
        rows = [self._lead("cold-99", 99),
                self._lead("escalated-50", 50, escalated=True),
                self._lead("callback-51", 51, priority_callback=True)]
        order = [r["id"] for r in self._queue(monkeypatch, rows)]
        assert order == ["callback-51", "escalated-50", "cold-99"]

    def test_score_still_orders_within_a_tier(self, monkeypatch):
        rows = [self._lead("a", 60, priority_callback=True), self._lead("b", 95, priority_callback=True)]
        order = [r["id"] for r in self._queue(monkeypatch, rows)]
        assert order == ["b", "a"]

    def test_queue_is_bounded(self):
        import inspect
        source = inspect.getsource(db.get_leads_for_outbound)
        assert ".limit(" in source, "unbounded outbound query"

    def test_queue_orders_priority_at_the_database(self):
        import inspect
        source = inspect.getsource(db.get_leads_for_outbound)
        assert 'order("priority_callback"' in source

    def test_database_ordering_matches_the_final_sort_keys(self):
        import inspect
        source = inspect.getsource(db.get_leads_for_outbound)
        for column in ("priority_callback", "escalated", "composite_score"):
            assert f'order("{column}"' in source, (
                f"{column} is a final sort key, so the truncating query must order by it "
                "or .limit() will discard rows the sort would have ranked first"
            )

    def test_database_order_precedes_the_limit(self):
        import inspect
        source = inspect.getsource(db.get_leads_for_outbound)
        assert source.index(".limit(") > source.index('order("composite_score"')


class TestConfigDiscoverability:
    @pytest.mark.parametrize("name", [
        "SCOUT_RSS_FEEDS", "CRMLS_API_KEY", "CRMLS_MEMBER_ID",
        "REALESTATEAPI_KEY", "BATCHDATA_API_KEY", "ALERT_PHONE",
    ])
    def test_scraper_config_is_declared(self, name):
        from pathlib import Path
        text = Path(__file__).resolve().parents[1].joinpath(".env.example").read_text()
        assert f"{name}=" in text, f"{name} is read by code but undeclared in .env.example"


class TestOutboundQueueLimitParsing:
    def test_unset_uses_default(self, monkeypatch):
        monkeypatch.delenv("OUTBOUND_QUEUE_LIMIT", raising=False)
        assert db._outbound_queue_limit() == db._OUTBOUND_QUEUE_LIMIT_DEFAULT

    def test_blank_uses_default(self, monkeypatch):
        monkeypatch.setenv("OUTBOUND_QUEUE_LIMIT", "   ")
        assert db._outbound_queue_limit() == db._OUTBOUND_QUEUE_LIMIT_DEFAULT

    def test_valid_value_is_honored(self, monkeypatch):
        monkeypatch.setenv("OUTBOUND_QUEUE_LIMIT", "25")
        assert db._outbound_queue_limit() == 25

    def test_malformed_value_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("OUTBOUND_QUEUE_LIMIT", "not-a-number")
        assert db._outbound_queue_limit() == db._OUTBOUND_QUEUE_LIMIT_DEFAULT

    def test_zero_and_negative_fall_back_to_default(self, monkeypatch):
        for value in ("0", "-1", "-500"):
            monkeypatch.setenv("OUTBOUND_QUEUE_LIMIT", value)
            assert db._outbound_queue_limit() == db._OUTBOUND_QUEUE_LIMIT_DEFAULT

    def test_module_level_limit_is_a_positive_int(self):
        assert isinstance(db._OUTBOUND_QUEUE_LIMIT, int)
        assert db._OUTBOUND_QUEUE_LIMIT >= 1
