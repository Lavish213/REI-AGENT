from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from backend.karpathys import business, client
from backend.lib import db
from backend.scout import crmls_scraper


def source():
    return {'lead': {'id': 'lead-1', 'property_id': 'property-1', 'properties': {'id': 'property-1', 'apn': '00123456', 'address': '123 Synthetic Street'}, 'appointment_at': None, 'appointment_status': 'cancelled'}, 'offers': [{'id': 'offer-1', 'lead_id': 'lead-1', 'offer_status': 'draft', 'offer_amount': 25000000, 'repair_estimate': 2000000}]}


def test_snapshot_preserves_recorded_cents_and_cancellation_without_authority():
    result = business.build_snapshot('lead-1', source())
    assert result['offers'][0]['amount_cents'] == 25000000
    assert result['appointment']['status'] == 'cancelled'
    assert result['valuation'] is None and result['offer_authorized'] is False


def test_snapshot_rejects_cross_property_binding():
    value = source();value['lead']['properties']['id'] = 'wrong'
    with pytest.raises(ValueError):
        business.build_snapshot('lead-1', value)


@pytest.mark.asyncio
async def test_business_journal_is_independent_of_calls_and_replay_safe(tmp_path, monkeypatch):
    monkeypatch.setenv('KARPATHYS_OUTBOX_PATH', str(tmp_path / 'business.sqlite'))
    monkeypatch.setattr(client, '_KARPATHYS_URL', 'https://test.example.invalid')
    monkeypatch.setattr(client, '_KARPATHYS_SECRET', 'synthetic-only')
    monkeypatch.setattr(db, 'dashboard_business_source', lambda lead_id: source())
    assert await business.publish_business('lead:lead-1', 'lead-1')
    assert await business.publish_business('lead:lead-1', 'lead-1')
    event = db.claim_dashboard_event(client.delivery_target())
    assert event['endpoint'] == 'business'
    assert event['payload']['snapshot']['offers'][0]['amount_cents'] == 25000000
    assert db.dashboard_event_journal_health()['pending'] == 1


def test_mls_runner_saves_candidates_and_returns_saved_count(monkeypatch):
    monkeypatch.setattr(crmls_scraper, 'fetch_expired_listings', lambda: [{'apn': '00123456'}])
    monkeypatch.setattr(crmls_scraper, 'fetch_price_reduced_listings', lambda: [])
    monkeypatch.setattr(crmls_scraper, 'fetch_withdrawn_listings', lambda: [])
    save = MagicMock(return_value='lead-id')
    monkeypatch.setattr(db, 'persist_mls_candidate', save)
    assert crmls_scraper.run_crmls_scraper() == 1
    save.assert_called_once()


def test_mls_missing_parcel_never_writes_or_grants_contact(monkeypatch):
    get = MagicMock()
    monkeypatch.setattr(db, '_get_client', get)
    assert db.persist_mls_candidate({'county': 'San Joaquin', 'state': 'CA', 'address': 'Street'}) is None
    get.assert_not_called()


def test_mls_existing_property_lead_is_reused(monkeypatch):
    candidate = {'apn': '00123456', 'county': 'San Joaquin', 'state': 'CA', 'address': 'Street', 'last_list_price': 40000000}
    save = MagicMock(return_value='property-1')
    monkeypatch.setattr(db, 'upsert_listing_candidate', save)
    monkeypatch.setattr(db, 'get_lead_by_property', lambda property_id: {'id': 'existing-lead'})
    assert db.persist_mls_candidate(candidate) == 'existing-lead'
    assert save.call_args.args[0]['tenant_id'] == '00000000-0000-0000-0000-000000000001'


def test_mls_new_lead_is_not_callable_and_confirmed(monkeypatch):
    candidate = {'apn': '00123456', 'county': 'San Joaquin', 'state': 'CA', 'address': 'Street'}
    client = MagicMock()
    monkeypatch.setattr(db, '_get_client', lambda: client)
    monkeypatch.setattr(db, 'upsert_listing_candidate', lambda payload: 'property-1')
    reads = iter([None, {'id': 'saved-lead'}])
    monkeypatch.setattr(db, 'get_lead_by_property', lambda property_id: next(reads))
    client.rpc.return_value.execute.return_value.data = 'saved-lead'
    assert db.persist_mls_candidate(candidate) == 'saved-lead'
    assert client.rpc.call_args.args[0] == 'create_canonical_lead'
    assert client.rpc.call_args.args[1]['p_property_id'] == 'property-1'


@pytest.mark.asyncio
async def test_slow_dashboard_refresh_does_not_delay_spoken_tool_result(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.voice.agent import _make_tool_handler
    gate = asyncio.Event()
    async def slow(call_sid, lead_id):
        await gate.wait()
    monkeypatch.setattr('backend.voice.agent.execute_tool', lambda *args: 'Confirmed tool result')
    monkeypatch.setattr(business, 'refresh_business', slow)
    ctx = SimpleNamespace(lead_id='lead', _call_sid='sid', call_should_end=False)
    callback = AsyncMock()
    params = SimpleNamespace(arguments={}, result_callback=callback)
    await asyncio.wait_for(_make_tool_handler('book_appointment', ctx)(params), timeout=0.5)
    callback.assert_awaited_once_with('Confirmed tool result')
    gate.set()
    await ctx._business_refresh_task


def test_same_record_can_refresh_observation_without_changing_prices(monkeypatch):
    from datetime import datetime, timezone
    first = business.build_snapshot('lead-1', source())
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(business, 'datetime', Later)
    second = business.build_snapshot('lead-1', source())
    assert first['observation_hour'] != second['observation_hour']
    assert first['offers'] == second['offers']


def test_business_source_cannot_read_another_tenants_offers(monkeypatch):
    monkeypatch.setattr(db, 'get_lead_with_property', lambda lead: {'id': lead, 'tenant_id': 'other', 'properties': {'tenant_id': 'other'}})
    offers = MagicMock()
    monkeypatch.setattr(db, 'get_offers_for_lead', offers)
    with pytest.raises(ValueError, match='tenant'):
        db.dashboard_business_source('lead-1')
    offers.assert_not_called()


def test_snapshot_uses_real_reservation_not_missing_lead_status():
    value = source()
    value['lead']['appointment_status'] = None
    value['appointment'] = {'id':'reservation', 'lead_id':'lead-1', 'starts_at':'2030-01-01T18:00:00+00:00', 'status':'confirmed'}
    assert business.build_snapshot('lead-1',value)['appointment'] == {'at':'2030-01-01T18:00:00+00:00','status':'confirmed'}
    value['appointment']['lead_id'] = 'other'
    with pytest.raises(ValueError):
        business.build_snapshot('lead-1',value)


def _brief_with_opportunity(**changes):
    opportunity = {
        'schema_version': '1.0', 'grade': 'A', 'readiness': 'HOT_BUY', 'evidence_confidence': 'verified',
        'quote_authorized': False, 'offer_authorized': False, 'missing_facts': [], 'opportunity_signals': ['asking_price_below_screening_purchase_limit'],
        'contradictory_evidence': [], 'lockout_class': None, 'next_action': 'prepare_offer_for_human_approval',
        'economics': {'state': 'known', 'arv_point_cents': 46000000, 'repair_estimate_cents': 2000000, 'asking_price_cents': 20000000, 'purchase_limit_cents': 30200000, 'headroom_cents': 10200000, 'headroom_bps': 2217},
    }
    opportunity.update(changes)
    now = datetime.now(timezone.utc)
    return {
        'schema_version': '2.0', 'lead_id': 'lead-1', 'phase': 'VERIFY', 'objective': 'Confirm the right person',
        'missing_box': 'right_person', 'mood': 'guarded', 'avoid': [], 'escalation_rules': [],
        'confidence': 0.5, 'ready_for_call': False, 'blocked_reasons': [],
        'created_at': (now - timedelta(minutes=5)).isoformat(), 'expires_at': (now + timedelta(hours=12)).isoformat(),
        'evidence': {'opportunity': opportunity},
    }


def _source_with_brief(**changes):
    value = source()
    value['lead']['call_brief'] = _brief_with_opportunity(**changes)
    return value


def test_snapshot_carries_the_per_lead_opportunity_grade():
    result = business.build_snapshot('lead-1', _source_with_brief())
    opportunity = result['opportunity']
    assert opportunity['grade'] == 'A'
    assert opportunity['readiness'] == 'HOT_BUY'
    assert opportunity['arv_point_cents'] == 46000000
    assert opportunity['headroom_cents'] == 10200000
    assert opportunity['quote_authorized'] is False and opportunity['offer_authorized'] is False


def test_snapshot_opportunity_lists_are_lists_not_booleans():
    result = business.build_snapshot('lead-1', _source_with_brief())
    assert result['opportunity']['opportunity_signals'] == ['asking_price_below_screening_purchase_limit']
    assert isinstance(result['opportunity']['missing_facts'], list)


def test_snapshot_keeps_a_known_arv_when_economics_are_incomplete():
    economics = {'state': 'unknown', 'arv_point_cents': 46000000, 'repair_estimate_cents': None, 'asking_price_cents': 20000000, 'purchase_limit_cents': None, 'headroom_cents': None, 'headroom_bps': None}
    result = business.build_snapshot('lead-1', _source_with_brief(grade=None, economics=economics, missing_facts=['repair_estimate'], next_action='obtain_repair_estimate'))
    assert result['opportunity']['arv_point_cents'] == 46000000
    assert result['opportunity']['purchase_limit_cents'] is None
    assert result['opportunity']['missing_facts'] == ['repair_estimate']


@pytest.mark.parametrize('change', [
    {'quote_authorized': True},
    {'offer_authorized': True},
    {'readiness': 'APPROVED_TO_OFFER'},
    {'grade': 'Z'},
    {'evidence_confidence': 'excellent'},
    {'schema_version': '2.0'},
    {'economics': {'state': 'known', 'arv_point_cents': 1.5, 'repair_estimate_cents': 1, 'asking_price_cents': 1, 'purchase_limit_cents': 1, 'headroom_cents': 1, 'headroom_bps': 1}},
    {'economics': {'state': 'bogus'}},
])
def test_snapshot_withholds_a_malformed_or_authorized_opportunity(change):
    assert business.build_snapshot('lead-1', _source_with_brief(**change))['opportunity'] is None


def test_snapshot_without_a_brief_reports_no_opportunity():
    assert business.build_snapshot('lead-1', source())['opportunity'] is None
