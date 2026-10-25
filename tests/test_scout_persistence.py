from types import SimpleNamespace

import pytest
from backend.lib import db
from backend.scout import cron

LEAD = '00000000-0000-0000-0000-000000000020'
PROP = '00000000-0000-0000-0000-000000000010'


@pytest.fixture
def scout(monkeypatch):
    monkeypatch.setattr(cron, '_get_latest_csv', lambda: 'fixture.csv')
    monkeypatch.setattr(cron, 'parse_csv', lambda _: [{'apn': '12345678', 'distress_score': 95, '_owner_phone': '+12095550100'}])
    monkeypatch.setattr(cron, 'score_properties', lambda rows: rows)
    monkeypatch.setattr(cron, 'MIN_ALERT_SCORE', 75)
    monkeypatch.setattr(cron, 'ALERT_PHONE', '+12095550200')
    def save(prop):
        prop['id'] = PROP
        return PROP
    monkeypatch.setattr(cron, 'upsert_property', save)
    monkeypatch.setattr(cron, 'get_lead_by_property', lambda _: None)
    monkeypatch.setattr(cron, 'insert_lead', lambda _: LEAD)
    monkeypatch.setattr(db, 'store_imported_lead_contacts', lambda *args: None)
    monkeypatch.setattr(cron, 'send_sms', lambda **kwargs: False)
    from backend.alerts import speed_to_lead
    monkeypatch.setattr(speed_to_lead, 'run_speed_to_lead', lambda _: None)
    monkeypatch.delenv('REALESTATEAPI_KEY', raising=False)


def test_failed_alert_is_not_counted_as_sent_and_lead_is_durable(scout):
    result = cron.run_scout()
    assert result['leads_confirmed'] == 1 and result['upserted'] == 1
    assert result['alerts_accepted'] == 0 and result['alerts_failed'] == 1
    assert result['status'] == 'partial'


def test_one_poison_record_does_not_prevent_later_property(scout, monkeypatch):
    monkeypatch.setattr(cron, 'parse_csv', lambda _: [{'distress_score': 90}, {'distress_score': 95}])
    calls = []
    def save(prop):
        calls.append(prop)
        if len(calls) == 1:
            raise RuntimeError('database write rejected')
        prop['id'] = PROP
        return PROP
    monkeypatch.setattr(cron, 'upsert_property', save)
    result = cron.run_scout()
    assert result['record_errors'] == 1 and result['upserted'] == 1 and result['leads_confirmed'] == 1


def test_unconfirmed_property_never_creates_lead_or_sends_alert(scout, monkeypatch):
    monkeypatch.setattr(cron, 'upsert_property', lambda _: None)
    monkeypatch.setattr(cron, 'insert_lead', lambda _: pytest.fail('unconfirmed property used'))
    monkeypatch.setattr(cron, 'send_sms', lambda **kwargs: pytest.fail('alert used before persistence'))
    result = cron.run_scout()
    assert result['upserted'] == 0 and result['leads_confirmed'] == 0 and result['record_errors'] == 1


def test_existing_lead_does_not_duplicate_or_repeat_initial_actions(scout, monkeypatch):
    monkeypatch.setattr(cron, 'get_lead_by_property', lambda _: {'id': LEAD})
    monkeypatch.setattr(cron, 'insert_lead', lambda _: pytest.fail('duplicate lead'))
    result = cron.run_scout()
    assert result['upserted'] == 1 and result['leads_confirmed'] == 0 and result['alerts_failed'] == 0


def test_imported_phone_does_not_grant_contact_authority(monkeypatch):
    writes = []
    class Query:
        def update(self, values):
            writes.append(values)
            return self
        def eq(self, *args):
            return self
        def execute(self):
            return SimpleNamespace(data=[{'id': LEAD}])
    monkeypatch.setattr(db, '_get_client', lambda: SimpleNamespace(table=lambda _: Query()))
    db.store_imported_lead_contacts(LEAD, '(209) 555-0100', 'Seller@Example.invalid')
    assert writes[0]['owner_phone'] == '+12095550100'
    assert writes[0]['owner_email'] == 'seller@example.invalid'
    assert not {'callable', 'opted_out', 'consent', 'contact_authorized'} & writes[0].keys()


def test_missing_csv_is_unconfigured_not_success(scout, monkeypatch):
    monkeypatch.setattr(cron, '_get_latest_csv', lambda: None)
    assert cron.run_scout()['status'] == 'unconfigured'


def test_scheduler_isolates_failing_scout_jobs_and_continues(monkeypatch):
    """A failed startup scan or scheduled source must not stop other jobs."""
    callbacks = []
    calls = []

    class Job:
        @property
        def hours(self):
            return self

        @property
        def day(self):
            return self

        def at(self, _time):
            return self

        def do(self, callback):
            callbacks.append(callback)
            return self

    class FakeSchedule:
        def every(self, *_args):
            return Job()

        def run_pending(self):
            for callback in callbacks:
                callback()

    def failing(name):
        def run():
            calls.append(name)
            raise RuntimeError('sensitive provider exception text')
        return run

    def succeeding(name):
        def run():
            calls.append(name)
        return run

    monkeypatch.setattr(cron, 'schedule', FakeSchedule())
    monkeypatch.setattr(cron, 'run_scout', failing('scout'))
    monkeypatch.setattr(cron, 'run_expired_scraper', failing('expired'))
    for name in ('run_rss_scraper', 'run_social_scraper', 'run_eviction_scraper',
                 'run_crmls_scraper', 'run_daily_drip_triggers'):
        monkeypatch.setattr(cron, name, succeeding(name))
    monkeypatch.setattr(cron.time, 'sleep', lambda _: (_ for _ in ()).throw(StopIteration))

    with pytest.raises(StopIteration):
        cron.start_scheduler()

    assert len(callbacks) == 7
    assert calls.count('scout') == 2  # startup plus scheduled invocation
    assert calls.count('expired') == 1
    for name in ('run_rss_scraper', 'run_social_scraper', 'run_eviction_scraper',
                 'run_crmls_scraper', 'run_daily_drip_triggers'):
        assert calls.count(name) == 1
