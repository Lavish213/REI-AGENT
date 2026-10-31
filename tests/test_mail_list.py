import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import properties as property_routes
from backend.api.security import OperatorAuthentication
from backend.lib import db

SECRET = 's' * 40

LEADS = [
    {'id': 'l1', 'property_id': 'p1', 'owner_name': 'Ann Owner', 'opted_out': False, 'ownership_denied': False},
    {'id': 'l2', 'property_id': 'p2', 'owner_name': None, 'opted_out': False, 'ownership_denied': False},
    {'id': 'l3', 'property_id': 'p3', 'owner_name': 'Opted Out', 'opted_out': True, 'ownership_denied': False},
    {'id': 'l4', 'property_id': 'p4', 'owner_name': 'Not Owner', 'opted_out': False, 'ownership_denied': True},
    {'id': 'l5', 'property_id': 'p5', 'owner_name': 'No Mail', 'opted_out': False, 'ownership_denied': False},
    {'id': 'l6', 'property_id': 'p6', 'owner_name': 'Bad Deal', 'opted_out': False, 'ownership_denied': False},
    {'id': 'l7', 'property_id': None, 'owner_name': 'Loose', 'opted_out': False, 'ownership_denied': False},
]


def prop(key, **extra):
    base = {'id': key, 'address': key + ' Main St', 'city': 'Stockton', 'state': 'CA', 'zip': '95205', 'owner_name': 'Prop Owner',
            'owner_mailing_address': '1 Mail Rd', 'owner_mailing_city': 'Lodi', 'owner_mailing_state': 'CA', 'owner_mailing_zip': '95240',
            'estimated_arv': None, 'mao': None, 'arv_confidence': 'needs_comps', 'distress_type': 'vacant', 'distress_score': 50, 'deal_viable': True}
    base.update(extra)
    return base


PROPERTIES = [
    prop('p1', estimated_arv=45000000, mao=29000000, arv_confidence='rentcast_avm', distress_score=60),
    prop('p2', distress_score=90),
    prop('p3', estimated_arv=45000000, arv_confidence='rentcast_avm'),
    prop('p4', estimated_arv=45000000, arv_confidence='rentcast_avm'),
    prop('p5', owner_mailing_address='  ', estimated_arv=45000000, arv_confidence='rentcast_avm'),
    prop('p6', deal_viable=False, estimated_arv=45000000, arv_confidence='rentcast_avm'),
    prop('p8', estimated_arv=45000000, arv_confidence='rentcast_avm'),
]


@pytest.fixture
def data(monkeypatch):
    tables = {'leads': LEADS, 'properties': PROPERTIES}
    monkeypatch.setattr(db, '_scan_rows', lambda table, columns, **kwargs: [dict(row) for row in tables[table]])


def test_priced_only_excludes_unpriced_opted_out_denied_unmailable_and_unviable(data):
    rows = db.mail_list(True)
    assert [row['lead_id'] for row in rows] == ['l1']
    row = rows[0]
    assert row['owner_name'] == 'Ann Owner' and row['mailing_address'] == '1 Mail Rd' and row['value_cents'] == 45000000
    assert row['mao_cents'] == 29000000 and row['value_source'] == 'rentcast_avm'


def test_all_leads_sorted_by_score_and_unpriced_values_blank(data):
    rows = db.mail_list(False)
    assert [row['lead_id'] for row in rows] == ['l2', 'l1']
    assert rows[0]['owner_name'] == 'Prop Owner' and rows[0]['value_cents'] is None and rows[0]['mao_cents'] is None


def client():
    application = FastAPI()
    application.add_middleware(OperatorAuthentication)
    application.include_router(property_routes.router, prefix='/api')
    return TestClient(application)


def test_endpoint_requires_source_secret(monkeypatch, data):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    assert client().get('/api/operations/mail-list').status_code == 401


def test_endpoint_returns_rows(monkeypatch, data):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    response = client().get('/api/operations/mail-list?priced_only=false', headers={'x-source-command-secret': SECRET})
    assert response.status_code == 200
    body = response.json()
    assert body['schema_version'] == 1 and body['priced_only'] is False and body['count'] == 2


def test_import_requires_source_secret(monkeypatch):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    response = client().post('/api/operations/import-csv', files={'file': ('a.csv', b'x', 'text/csv')})
    assert response.status_code == 401


@pytest.mark.parametrize('name,content', [('a.txt', b'x'), ('a.csv', b''), ('a.csv', b'x' * (10 * 1024 * 1024 + 1))])
def test_import_rejects_bad_files(monkeypatch, name, content):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    monkeypatch.setattr(property_routes, '_process_csv', lambda *args: pytest.fail('must not process'))
    response = client().post('/api/operations/import-csv', files={'file': (name, content, 'text/csv')}, headers={'x-source-command-secret': SECRET})
    assert response.status_code == 400


def test_import_processes_csv_with_leads(monkeypatch):
    monkeypatch.setenv('SOURCE_COMMAND_SECRET', SECRET)
    seen = []
    monkeypatch.setattr(property_routes, '_process_csv', lambda text, min_score, create: seen.append((text, min_score, create)) or {'parsed': 1, 'upserted': 1, 'scored': 1, 'leads_created': 1, 'skipped_score': 0, 'errors': 0})
    response = client().post('/api/operations/import-csv', files={'file': ('propwire.csv', '﻿Address\n1 A St\n'.encode('utf-8'), 'text/csv')}, headers={'x-source-command-secret': SECRET})
    assert response.status_code == 200 and response.json()['leads_created'] == 1
    assert seen == [('Address\n1 A St\n', 0, True)]
