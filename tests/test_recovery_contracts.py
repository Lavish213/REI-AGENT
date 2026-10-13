import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.main import _run_pending_followups
from backend.api.routes.live import _sanitize_call_context
from backend.lib import db
from backend.qa import grader
from backend.voice.appointment_scheduler import PACIFIC, _process_lead
from backend.voice.outbound_webhook import _build_outbound_context, handle_recording_status


def test_followup_failure_does_not_abandon_remaining_leases():
    followups = [{"id": "f1", "lead_id": "l1", "claim_token": "t1"}, {"id": "f2", "lead_id": "l2", "claim_token": "t2"}]
    callbacks = [{"id": "l3", "callback_scheduled_at": "2030-01-01", "callback_claim_token": "t3"}]
    with patch.object(db, "campaign_is_running", return_value=True), patch.object(db, "claim_due_call_followups", return_value=followups), patch.object(db, "claim_due_callbacks", return_value=callbacks), patch("backend.voice.outbound.call_lead", side_effect=[RuntimeError("provider down"), {"success": True}, {"success": True}]) as dial, patch.object(db, "finish_followup_claim", side_effect=[RuntimeError("database down"), None]) as finish, patch.object(db, "finish_callback_claim") as callback_finish:
        _run_pending_followups()
    assert dial.call_count == 3
    assert finish.call_args_list[1].args == ("f2", True, "t2")
    callback_finish.assert_called_once_with("l3", "2030-01-01", True, "t3")


@pytest.mark.parametrize("function,args", [(db.finish_followup_claim, ("f", True)), (db.finish_callback_claim, ("l", "2030-01-01", True))])
def test_unowned_completion_denied(function, args):
    with patch.object(db, "_get_client") as client, pytest.raises(ValueError):
        function(*args)
    client.assert_not_called()


@pytest.mark.parametrize("success", [False, True])
def test_completion_compare_and_swap_requires_generation(success):
    client = MagicMock()
    with patch.object(db, "_get_client", return_value=client):
        db.finish_followup_claim("f", success, "generation")
        db.finish_callback_claim("l", "date", success, "generation")
    assert client.table.return_value.update.return_value.eq.return_value.eq.return_value.eq.call_args.args == ("callback_claim_token", "generation")


def test_outbound_context_converts_cents_once():
    context = _build_outbound_context({"id": "l"}, {"estimated_arv": 35000115, "mao": 22000025}, "Alex", "Test St")
    assert "ARV: $350,001.15" in context
    assert "MAO: $220,000.25" in context
    assert "$35,000,115" not in context


def test_live_state_includes_outbound_property():
    result = _sanitize_call_context("CA", {"lead": {"id": "l", "properties": {"address": "Test St", "city": "Stockton"}}}, None)
    assert result["address"] == "Test St"
    assert result["city"] == "Stockton"


@pytest.mark.parametrize("hours", [2, 20, -3])
def test_appointment_messages_only_make_supported_claims(hours):
    now = datetime(2030, 1, 1, 23, tzinfo=timezone.utc)
    lead = {"id": "l", "owner_phone": "+15555550100", "appointment_at": (now + timedelta(hours=hours)).isoformat(), "properties": {"address": "Test St"}}
    with patch("backend.voice.appointment_scheduler._send_reminder", return_value=True) as send, patch("backend.voice.appointment_scheduler.update_appt_reminder_flags") as update:
        _process_lead(lead, now, now.astimezone(PACIFIC))
    assert send.call_count == 1
    body = send.call_args.args[1]
    assert "We came by" not in body
    assert "tomorrow" not in body
    assert "January" in body or "December" in body
    assert update.call_count == 1


@pytest.mark.parametrize("state", [{"opted_out": True}, {"appointment_status": "cancelled"}])
def test_cancelled_or_suppressed_appointment_gets_no_reminder(state):
    now = datetime(2030, 1, 1, 23, tzinfo=timezone.utc)
    lead = {"id": "l", "appointment_at": (now + timedelta(hours=2)).isoformat(), **state}
    with patch("backend.voice.appointment_scheduler._send_reminder") as send:
        _process_lead(lead, now, now.astimezone(PACIFIC))
    send.assert_not_called()


@pytest.mark.asyncio
async def test_recording_failure_returns_retryable_status():
    request = SimpleNamespace(form=AsyncMock(return_value={"CallSid": "CA", "RecordingUrl": "https://provider/recording", "RecordingStatus": "completed"}))
    with patch.object(db, "save_recording_metadata", side_effect=RuntimeError("database down")):
        response = await handle_recording_status(request, "lead")
    assert response.status_code == 500


def qa_response(scores):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="submit_grades", input=scores)])


def valid_scores():
    return {"qualification": 9, "offer_quality": None, "objection_handling": 7, "appointment_booking": 8, "tone": 10, "goal_completion": 6, "call_summary": "Seller agreed to a walkthrough", "failures": []}


@pytest.mark.asyncio
async def test_grades_map_to_their_actual_metrics():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=qa_response(valid_scores()))))
    with patch.object(grader, "_get_client", return_value=client), patch.object(db, "save_call_grade") as save:
        scores = await grader.grade_call("Seller: " + "A recorded conversation. " * 4, "lead", "CA")
    assert scores["overall_score"] == 8
    fields = save.call_args.args[1]
    assert fields["score_qualification"] == 9
    assert fields["score_offer_quality"] is None
    assert fields["score_objection_handling"] == 7
    assert fields["score_appointment_booking"] == 8
    assert "25 year old" not in client.messages.create.call_args.kwargs["messages"][0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [-1, 11, True, "9", float("nan"), float("inf"), None])
async def test_bad_qa_scores_do_not_pollute_dashboard(value):
    scores = valid_scores()
    scores["qualification"] = value
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=qa_response(scores))))
    with patch.object(grader, "_get_client", return_value=client), patch.object(db, "save_call_grade") as save:
        result = await grader.grade_call("A recorded conversation. " * 4, "lead", "CA")
    assert result == {}
    save.assert_not_called()


@pytest.mark.asyncio
async def test_post_call_work_is_awaited_before_return():
    from backend.voice.agent import _handle_call_end
    context = SimpleNamespace(messages=[])
    ctx = SimpleNamespace(transcript_events=[{"role": "user", "content": "Let's talk about my house"}], disposition="WARM", turn_count=1)
    finished = []
    async def work(*args, **kwargs):
        await asyncio.sleep(0.01)
        finished.append(True)
    with patch("backend.voice.agent._persist_call_result", new=AsyncMock(return_value="call")), patch("backend.voice.agent._run_qa_async", side_effect=work), patch("backend.voice.agent._run_transcript_intel_async", side_effect=work), patch("backend.observability.trace_call_end"), patch("backend.karpathys.emitter.emit_call_completed", new=AsyncMock()):
        await _handle_call_end("CA", {"lead": {"id": "lead"}}, context, ctx)
    assert len(finished) == 2


@pytest.mark.asyncio
async def test_capacity_monitor_survives_transient_failure_and_ends_on_loss():
    from backend.voice.agent import _monitor_call_capacity
    task = SimpleNamespace(cancel=AsyncMock())
    with patch("backend.voice.outbound._renew_call_slot", side_effect=[False, False, True, False, False, False]) as renew:
        await asyncio.wait_for(_monitor_call_capacity(task, "lead", "CA", interval=0.001), timeout=1)
    assert renew.call_count == 6
    task.cancel.assert_awaited_once()


@pytest.mark.parametrize("value", ["59", "3001", "bad", "", "-1"])
def test_invalid_call_limit_fails_closed(value, monkeypatch):
    from backend.voice.agent import _maximum_call_seconds
    monkeypatch.setenv("VOICE_MAX_CALL_SECONDS", value)
    with pytest.raises(ValueError):
        _maximum_call_seconds()


def test_capacity_renewal_cannot_revive_expired_or_wrong_call():
    import time
    import fakeredis
    from backend.voice import outbound
    client = fakeredis.FakeRedis()
    with patch.object(outbound, "_get_redis_client", return_value=client):
        assert outbound._acquire_call_slot("lead", "owner")
        assert outbound._bind_call_slot("lead", "owner", "CA")
        assert not outbound._renew_call_slot("lead", "wrong")
        assert outbound._renew_call_slot("lead", "CA")
        client.zadd(outbound._REDIS_CONCURRENT_KEY, {"lead": time.time() - 1})
        assert not outbound._renew_call_slot("lead", "CA")
        assert outbound._acquire_call_slot("lead", "new-owner")
        assert outbound._bind_call_slot("lead", "new-owner", "CA-new")
        assert not outbound._renew_call_slot("lead", "CA")
        assert outbound._renew_call_slot("lead", "CA-new")


def test_expired_appointment_does_not_trigger_outreach():
    now = datetime(2030, 1, 1, 23, tzinfo=timezone.utc)
    lead = {"id": "l", "appointment_at": (now - timedelta(days=30)).isoformat()}
    with patch("backend.voice.appointment_scheduler._send_reminder") as send:
        _process_lead(lead, now, now.astimezone(PACIFIC))
    send.assert_not_called()


def test_reminder_query_excludes_cancelled_and_stale_bookings():
    candidates = [{"id": "confirmed", "appointment_at": "2030-01-01T10:00:00-08:00"}, {"id": "cancelled", "appointment_at": "2030-01-01T18:00:00Z"}, {"id": "stale", "appointment_at": "2030-01-01T18:00:00Z"}, {"id": "malformed", "appointment_at": "bad"}]
    confirmed = [{"lead_id": "confirmed", "starts_at": "2030-01-01T18:00:00Z"}, {"lead_id": "stale", "starts_at": "2030-01-02T18:00:00Z"}]
    client = MagicMock()
    leads_query = MagicMock()
    leads_query.select.return_value.eq.return_value.not_.is_.return_value.execute.return_value.data = candidates
    bookings_query = MagicMock()
    bookings_query.select.return_value.eq.return_value.execute.return_value.data = confirmed
    client.table.side_effect = [leads_query, bookings_query]
    with patch.object(db, "_get_client", return_value=client):
        assert [row["id"] for row in db.get_pending_appointment_leads()] == ["confirmed"]


def test_missing_lease_token_never_dials():
    with patch.object(db, "campaign_is_running", return_value=True), patch.object(db, "claim_due_call_followups", return_value=[{"id": "f", "lead_id": "l"}]), patch.object(db, "claim_due_callbacks", return_value=[{"id": "l"}]), patch("backend.voice.outbound.call_lead") as dial:
        _run_pending_followups()
    dial.assert_not_called()


def test_callback_claim_still_runs_when_followup_claim_fails():
    callback = {"id": "l", "callback_scheduled_at": "date", "callback_claim_token": "t"}
    with patch.object(db, "campaign_is_running", return_value=True), patch.object(db, "claim_due_call_followups", side_effect=RuntimeError("RPC unavailable")), patch.object(db, "claim_due_callbacks", return_value=[callback]), patch("backend.voice.outbound.call_lead", return_value={"success": True}) as dial, patch.object(db, "finish_callback_claim"):
        _run_pending_followups()
    dial.assert_called_once_with("l", bypass_cooldown=True)
