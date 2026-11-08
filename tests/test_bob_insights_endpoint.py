import pytest

from backend.lib import db


def overview(**changes):
    base = {
        'schema_version': 1,
        'generated_at': '2026-11-08T02:00:00Z',
        'graded_leads': 2,
        'blocked_leads': 1,
        'economics_unknown_leads': 0,
        'by_readiness': {'HOT_BUY': 1, 'ARCHIVED': 1},
        'by_grade': {'A': 1, 'ungraded': 1},
        'by_evidence_confidence': {'verified': 1, 'thin': 1},
        'by_lockout_class': {'price_dependent': 1},
        'deals': [{'lead_id': 'l1', 'grade': 'A', 'readiness': 'HOT_BUY', 'headroom_cents': 10200000}],
        'authority': {'quote_authorized': False, 'offer_authorized': False, 'grading_basis': 'internal_screening_policy_not_an_appraisal_or_investment_guarantee'},
    }
    base.update(changes)
    return base


def stub(monkeypatch, payload, captured=None):
    class Response:
        data = payload

    class Client:
        def rpc(self, name, params):
            if captured is not None:
                captured.update(name=name, params=params)
            return self

        def execute(self):
            return Response()

    monkeypatch.setattr(db, '_get_client', lambda: Client())


class TestOverviewContract:
    def test_a_valid_overview_is_returned(self, monkeypatch):
        stub(monkeypatch, overview())
        assert db.bob_opportunity_overview()['graded_leads'] == 2

    def test_the_rpc_is_tenant_scoped_and_bounded(self, monkeypatch):
        captured = {}
        stub(monkeypatch, overview(), captured)
        monkeypatch.setenv('TENANT_ID', '00000000-0000-0000-0000-0000000000ab')
        db.bob_opportunity_overview(10)
        assert captured['name'] == 'bob_opportunity_overview'
        assert captured['params'] == {'p_tenant_id': '00000000-0000-0000-0000-0000000000ab', 'p_limit': 10}

    @pytest.mark.parametrize('bad', [0, -1, 101, 1000])
    def test_limits_outside_the_range_are_rejected(self, monkeypatch, bad):
        stub(monkeypatch, overview())
        with pytest.raises(ValueError):
            db.bob_opportunity_overview(bad)

    @pytest.mark.parametrize('bad', [True, 1.5, '25', None])
    def test_non_integer_limits_are_rejected(self, monkeypatch, bad):
        stub(monkeypatch, overview())
        with pytest.raises(TypeError):
            db.bob_opportunity_overview(bad)

    @pytest.mark.parametrize('payload', [
        None, [], 'nope', {},
        {'schema_version': 2, 'graded_leads': 0},
    ])
    def test_a_foreign_or_unversioned_payload_is_refused(self, monkeypatch, payload):
        stub(monkeypatch, payload)
        with pytest.raises(RuntimeError):
            db.bob_opportunity_overview()

    def test_a_missing_required_key_is_refused(self, monkeypatch):
        payload = overview()
        del payload['by_readiness']
        stub(monkeypatch, payload)
        with pytest.raises(RuntimeError):
            db.bob_opportunity_overview()

    @pytest.mark.parametrize('field,value', [('deals', {}), ('deals', 'none'), ('authority', []), ('authority', 'none')])
    def test_malformed_collections_are_refused(self, monkeypatch, field, value):
        stub(monkeypatch, overview(**{field: value}))
        with pytest.raises(RuntimeError):
            db.bob_opportunity_overview()


class TestAuthorityIsNeverAccepted:
    @pytest.mark.parametrize('authority', [
        {'quote_authorized': True, 'offer_authorized': False},
        {'quote_authorized': False, 'offer_authorized': True},
        {'quote_authorized': True, 'offer_authorized': True},
        {'offer_authorized': False},
        {'quote_authorized': False},
        {'quote_authorized': 'false', 'offer_authorized': 'false'},
        {'quote_authorized': 0, 'offer_authorized': 0},
    ])
    def test_any_hint_of_authority_is_refused(self, monkeypatch, authority):
        stub(monkeypatch, overview(authority=authority))
        with pytest.raises(RuntimeError):
            db.bob_opportunity_overview()

    def test_explicit_false_on_both_is_accepted(self, monkeypatch):
        stub(monkeypatch, overview())
        result = db.bob_opportunity_overview()
        assert result['authority']['quote_authorized'] is False
        assert result['authority']['offer_authorized'] is False


class TestRouteGuards:
    def test_the_route_rejects_an_out_of_range_limit_before_touching_the_database(self):
        import inspect
        from backend.api.routes import bob
        source = inspect.getsource(bob.insights)
        assert 'limit < 1 or limit > 100' in source
        assert source.index('HTTPException') < source.index('bob_opportunity_overview')

    def test_the_route_maps_failures_to_503_not_500(self):
        import inspect
        from backend.api.routes import bob
        source = inspect.getsource(bob.insights)
        assert "status_code=503" in source
        assert "status_code=422" in source
