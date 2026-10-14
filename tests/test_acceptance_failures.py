from starlette.requests import Request
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.lib import db
from backend.voice import tools


def test_end_call_does_not_claim_failed_stage_update(monkeypatch):
    monkeypatch.setattr(tools, 'update_lead_stage', MagicMock(side_effect=RuntimeError('offline')))
    result = tools._end_call({'lead_id': 'lead-1', 'reason': 'other'})
    assert 'updated to' not in result
    assert 'failed' in result.lower()


def test_end_call_without_lead_does_not_claim_stage_update():
    assert 'updated to' not in tools._end_call({'reason': 'other'})


def test_operator_without_number_never_implies_permission(monkeypatch):
    monkeypatch.delenv('OWNER_PHONE', raising=False)
    result = tools._ask_operator({'question': 'Can I quote this price?'})
    assert 'best judgment' not in result
    assert 'not approved' in result.lower()


def test_operator_failed_delivery_never_waits_or_approves(monkeypatch):
    monkeypatch.setenv('OWNER_PHONE', '+12095550123')
    monkeypatch.setattr(db, 'create_operator_query', MagicMock(return_value='op_test'), raising=False)
    monkeypatch.setattr('backend.alerts.sms.send_sms', MagicMock(return_value=False))
    result = tools._ask_operator({'question': 'Can I quote this price?'})
    assert 'not approved' in result.lower()


def test_approval_insert_failure_cannot_become_pending(monkeypatch):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.side_effect = RuntimeError('offline')
    monkeypatch.setattr(db, '_get_client', lambda: client)
    with pytest.raises(RuntimeError):
        db.create_approval_request('lead-1', 'call-1', 'price', 'get_offer_range')


@pytest.mark.parametrize('status', ['pending', 'typo', '', None])
def test_approval_resolution_rejects_invalid_status(monkeypatch, status):
    client = MagicMock()
    monkeypatch.setattr(db, '_get_client', lambda: client)
    with pytest.raises(ValueError):
        db.resolve_approval_request('id', 'dashboard', status)
    client.table.assert_not_called()


def test_resolution_without_changed_row_cannot_claim_success(monkeypatch):
    client = MagicMock()
    query = client.table.return_value.update.return_value
    query.eq.return_value = query
    query.gt.return_value = query
    query.execute.return_value.data = []
    monkeypatch.setattr(db, '_get_client', lambda: client)
    with pytest.raises(ValueError):
        db.resolve_approval_request('id', 'dashboard', 'approved')


@pytest.mark.asyncio
async def test_approval_route_requires_explicit_decision():
    from fastapi import HTTPException
    from backend.api.routes.intel import resolve_approval
    with pytest.raises(HTTPException) as exc:
        await resolve_approval('id', {}, Request({'type': 'http'}))
    assert exc.value.status_code == 422


def test_failed_transfer_keeps_agent_on_call(monkeypatch):
    monkeypatch.setenv('OWNER_PHONE', '+12095550123')
    monkeypatch.setattr('backend.lib.signalwire_rest.signalwire_post', MagicMock(side_effect=TimeoutError()))
    ctx = SimpleNamespace(_call_sid='call-1', call_should_end=False)
    assert 'failed' in tools._transfer_call({}, ctx).lower()
    assert ctx.call_should_end is False


def test_operator_persistence_failure_never_sends_message(monkeypatch):
    monkeypatch.setenv('OWNER_PHONE', '+12095550123')
    monkeypatch.setattr(db, 'create_operator_query', MagicMock(side_effect=RuntimeError('offline')))
    send = MagicMock()
    monkeypatch.setattr('backend.alerts.sms.send_sms', send)
    assert 'not approved' in tools._ask_operator({'question': 'Price?'})
    send.assert_not_called()


def test_unkeyed_operator_answer_cannot_attach_to_latest_call(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(db, '_get_client', lambda: client)
    assert db.record_operator_reply('yes') is False
    client.table.assert_not_called()


def test_operator_queries_have_unique_ids(monkeypatch):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = [{'id': 'saved'}]
    monkeypatch.setattr(db, '_get_client', lambda: client)
    assert db.create_operator_query('lead', 'Q', '') != db.create_operator_query('lead', 'Q', '')


def test_keyed_reply_requires_pending_recent_request(monkeypatch):
    client = MagicMock()
    query = client.table.return_value.update.return_value
    query.eq.return_value = query
    query.gt.return_value = query
    query.execute.return_value.data = []
    monkeypatch.setattr(db, '_get_client', lambda: client)
    assert db.record_operator_reply('op_' + 'a' * 32 + ' yes') is False
    query.eq.assert_any_call('status', 'pending')
    assert query.gt.call_args.args[0] == 'created_at'


@pytest.mark.asyncio
@pytest.mark.parametrize('error,code', [(RuntimeError('offline'), 503), (ValueError('expired'), 409)])
async def test_approval_route_reports_resolution_failure(monkeypatch, error, code):
    from fastapi import HTTPException
    from backend.api.routes.intel import resolve_approval
    monkeypatch.setattr(db, 'resolve_approval_request', MagicMock(side_effect=error))
    with pytest.raises(HTTPException) as exc:
        await resolve_approval('id', {'status': 'approved'}, Request({'type': 'http'}))
    assert exc.value.status_code == code


@pytest.mark.asyncio
async def test_approval_route_uses_server_actor(monkeypatch):
    from backend.api.routes.intel import resolve_approval
    resolve = MagicMock(return_value={'id': 'id'})
    monkeypatch.setattr(db, 'resolve_approval_request', resolve)
    await resolve_approval('id', {'status': 'rejected', 'approved_by': 'forged-owner'}, Request({'type': 'http'}))
    assert resolve.call_args.args[1] == 'shared_operator'


@pytest.mark.parametrize('phone', ['', '+12095550123'])
def test_stop_failure_is_truthful_and_still_ends_call(monkeypatch, phone):
    monkeypatch.setattr(db, 'try_write', MagicMock(return_value=False))
    resolved = SimpleNamespace(seller_phone=phone, lead_id='lead', call_sid='call', tenant_id='tenant')
    ctx = SimpleNamespace(stop_requested=False, call_should_end=False, runtime_instruction='old')
    result = tools._honor_stop_request({'verbatim': 'stop'}, resolved, ctx)
    assert "you're removed" not in result.lower()
    assert "won't hear from us again" not in result.lower()
    assert ctx.stop_requested and ctx.call_should_end
    assert ctx.runtime_instruction is None
