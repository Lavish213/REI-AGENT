import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import health
from backend.api.security import OperatorAuthentication
from backend.comps import homeharvest
from backend.lib import db
from backend.scout import scorer

SECRET = 's' * 40


def house(**extra):
    base = {'apn': '1', 'address': '10 Main St', 'city': 'Stockton', 'state': 'CA', 'beds': 3, 'baths': 2, 'sqft': 1400,
            'year_built': 1965, 'property_type': 'Single Family Residence', 'estimated_value': 12000000,
            'assessed_total_value': 11500000, 'zestimate': 40000000, 'equity_pct': 100, 'distress_type': 'absentee_owner'}
    base.update(extra)
    return base


def no_comps(**kwargs):
    raise RuntimeError('blocked')


def test_no_comps_means_no_arv_and_never_assessed_value(monkeypatch):
    monkeypatch.setattr(homeharvest, 'get_comps', no_comps)
    prop = house()
    assert scorer._compute_arv(prop) is None
    assert prop['arv_confidence'] == 'needs_comps'


def test_zero_comp_estimate_still_needs_comps(monkeypatch):
    monkeypatch.setattr(homeharvest, 'get_comps', lambda **kwargs: {'arv_estimate': 0, 'confidence': 'low', 'comp_count': 0, 'price_per_sqft': 0})
    prop = house()
    assert scorer._compute_arv(prop) is None
    assert prop['arv_confidence'] == 'needs_comps'


def test_real_comps_still_price_the_house(monkeypatch):
    monkeypatch.setattr(homeharvest, 'get_comps', lambda **kwargs: {'arv_estimate': 52000000, 'confidence': 'medium', 'comp_count': 6, 'price_per_sqft': 37100})
    prop = house()
    assert scorer._compute_arv(prop) == 52000000
    assert prop['arv_confidence'] == 'medium'


def test_scoring_without_comps_stores_empty_arv_and_mao(monkeypatch):
    monkeypatch.setattr(homeharvest, 'get_comps', no_comps)
    prop = house()
    score = scorer.calculate_distress_score(prop)
    assert prop['estimated_arv'] is None and prop['mao'] is None
    assert prop['deal_viable'] is True and 0 <= score <= 100


def test_scoring_with_comps_keeps_mao_formula(monkeypatch):
    monkeypatch.setattr(homeharvest, 'get_comps', lambda **kwargs: {'arv_estimate': 40000000, 'confidence': 'high', 'comp_count': 8, 'price_per_sqft': 28500})
    prop = house()
    scorer.calculate_distress_score(prop)
    assert prop['estimated_arv'] == 40000000
    assert prop['mao'] == 40000000 * 70 // 100 - 2500000


@pytest.mark.parametrize('value', [245000, 185000, 1, 999999])
def test_dollar_sized_prices_are_rejected(value):
    with pytest.raises(ValueError, match='dollars'):
        db.require_price_cents('estimated_arv', value)


@pytest.mark.parametrize('value', [245000.0, '24500000', True])
def test_non_integer_prices_are_rejected(value):
    with pytest.raises(ValueError):
        db.require_price_cents('mao', value)


@pytest.mark.parametrize('value', [None, 0, 1000000, 52283300])
def test_cent_prices_and_empty_values_pass(value):
    db.require_price_cents('estimated_arv', value)


def test_upsert_refuses_dollars_before_touching_the_database(monkeypatch):
    def forbidden():
        raise AssertionError('database must not be called')
    monkeypatch.setattr(db, '_get_client', forbidden)
    with pytest.raises(ValueError, match='dollars'):
        db.upsert_property({'apn': '1', 'estimated_arv': 245000, 'mao': 185000})


def test_diagnostic_writer_refuses_dollars(monkeypatch):
    monkeypatch.setattr(db, '_get_client', lambda: (_ for _ in ()).throw(AssertionError('no db')))
    with pytest.raises(ValueError, match='dollars'):
        db.update_property_arv('p', 245000, 185000, 'low')


class Rows:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class Query:
    def __init__(self, rows):
        self.rows, self.start, self.end = rows, 0, None

    def select(self, *args, **kwargs):
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def limit(self, size):
        self.end = size - 1
        return self

    def execute(self):
        return Rows(self.rows[self.start:(self.end + 1 if self.end is not None else None)], len(self.rows))


class Client:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return Query(self.tables[name])


def test_data_quality_report_counts_what_matters(monkeypatch):
    properties = [
        {'id': 'a', 'distress_type': 'free_and_clear', 'estimated_arv': None, 'arv_confidence': 'needs_comps', 'assessed_total_value': 8000000},
        {'id': 'b', 'distress_type': 'free_and_clear', 'estimated_arv': 52000000, 'arv_confidence': 'medium', 'assessed_total_value': 9000000},
        {'id': 'c', 'distress_type': 'vacant', 'estimated_arv': 10000000, 'arv_confidence': None, 'assessed_total_value': 8000000},
    ]
    leads = [{'id': '1', 'owner_phone': '+12095550100', 'call_brief_generated_at': '2026-10-31T00:00:00Z'}, {'id': '2', 'owner_phone': ' ', 'call_brief_generated_at': None}]
    monkeypatch.setattr(db, '_get_client', lambda: Client({'properties': properties, 'leads': leads, 'comps': []}))
    report = db.data_quality_report()
    assert report['properties'] == 3 and report['leads'] == 2
    assert report['properties_with_comp_arv'] == 1 and report['properties_needing_comps'] == 2
    assert report['assessed_based_arv'] == 1
    assert report['leads_with_phone'] == 1 and report['leads_with_bob_brief'] == 1
    assert report['comps_rows'] == 0
    assert list(report['by_distress_type']) == ['free_and_clear', 'vacant']
    assert report['by_distress_type']['free_and_clear'] == {'properties': 2, 'with_comp_arv': 1, 'needs_comps': 1}


def test_data_quality_report_pages_past_one_thousand_rows(monkeypatch):
    properties = [{'id': str(i), 'distress_type': 'vacant', 'estimated_arv': None, 'arv_confidence': 'needs_comps', 'assessed_total_value': None} for i in range(2345)]
    monkeypatch.setattr(db, '_get_client', lambda: Client({'properties': properties, 'leads': [], 'comps': []}))
    assert db.data_quality_report()['properties'] == 2345


def app():
    application = FastAPI()
    application.add_middleware(OperatorAuthentication)
    application.include_router(health.router, prefix='/api')
    return application


def test_data_quality_route_requires_source_secret(monkeypatch):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    monkeypatch.setattr(db, 'data_quality_report', lambda: {'schema_version': 1})
    client = TestClient(app())
    assert client.get('/api/health/data-quality').status_code == 401
    assert client.get('/api/health/data-quality', headers={'x-source-command-secret': 'wrong' * 10}).status_code == 401
    response = client.get('/api/health/data-quality', headers={'x-source-command-secret': SECRET})
    assert response.status_code == 200 and response.json() == {'schema_version': 1}


def test_data_quality_route_fails_closed(monkeypatch):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    monkeypatch.setattr(db, 'data_quality_report', lambda: (_ for _ in ()).throw(RuntimeError('down')))
    response = TestClient(app()).get('/api/health/data-quality', headers={'x-source-command-secret': SECRET})
    assert response.status_code == 503


@pytest.mark.parametrize('value', [3977900, 12000000, 52283300, 90000000])
def test_tax_based_estimated_value_never_disqualifies(value, monkeypatch):
    monkeypatch.setattr(homeharvest, 'get_comps', no_comps)
    prop = house(estimated_value=value)
    scorer.calculate_distress_score(prop)
    assert prop['deal_viable'] is True and prop['disqualified_reason'] is None
