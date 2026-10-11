from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytz
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipecat.frames.frames import (
    EndFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TextFrame,
    TranscriptionFrame,
    TTSTextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from backend.api.security import OperatorAuthentication, valid_signalwire_signature
from backend.voice.objective_engine import ObjectiveEngine
from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor, _extract_price_cents
from backend.voice.processors.sentence_streamer import SentenceStreamProcessor
from backend.voice.scheduling import callback_slot, local_slot
from backend.voice.session import issue_stream_token, read_media_session, validate_stream_token


D = FrameDirection.DOWNSTREAM


@pytest.mark.asyncio
async def test_sentence_is_spoken_before_response_finishes():
    processor = SentenceStreamProcessor(enable_direct_mode=True)
    processor.push_frame = AsyncMock()
    await processor.process_frame(LLMTextFrame("Got it. What day works?"), D)
    spoken = [args[0].text for args, _ in processor.push_frame.call_args_list if isinstance(args[0], TTSTextFrame)]
    assert spoken == ["Got it. ", "What day works? "]


@pytest.mark.asyncio
async def test_interruption_stress_does_not_leak_previous_turn():
    processor = SentenceStreamProcessor(enable_direct_mode=True)
    processor.push_frame = AsyncMock()
    for _ in range(1000):
        await processor.process_frame(LLMTextFrame("Stale unfinished answer"), D)
        await processor.process_frame(InterruptionFrame(), D)
        await processor.process_frame(LLMTextFrame("New answer."), D)
        await processor.process_frame(LLMFullResponseEndFrame(), D)
    spoken = [args[0].text for args, _ in processor.push_frame.call_args_list if isinstance(args[0], TTSTextFrame)]
    assert len(spoken) == 1000
    assert all(text == "New answer. " for text in spoken)
    assert processor._buffer == ""


@pytest.mark.asyncio
async def test_non_llm_frames_pass_without_becoming_speech():
    processor = SentenceStreamProcessor(enable_direct_mode=True)
    processor.push_frame = AsyncMock()
    frame = TextFrame("Tool data")
    await processor.process_frame(frame, D)
    processor.push_frame.assert_awaited_once_with(frame, D)
    assert not processor._buffer


@pytest.mark.asyncio
async def test_runaway_unpunctuated_output_has_bounded_buffer():
    processor = SentenceStreamProcessor(enable_direct_mode=True)
    processor.push_frame = AsyncMock()
    for _ in range(100):
        await processor.process_frame(LLMTextFrame("word " * 100), D)
        assert len(processor._buffer) <= 1200


@pytest.mark.parametrize("date,time,exception", [
    ("2030-02-30", "10:00", ValueError),
    ("2026-03-08", "02:30", pytz.NonExistentTimeError),
    ("2026-11-01", "01:30", pytz.AmbiguousTimeError),
    ("2020-01-01", "10:00", ValueError),
])
def test_invalid_scheduling_rejected(date, time, exception):
    with pytest.raises(exception):
        local_slot(date, time)


def test_explicit_callback_keeps_pacific_and_stores_utc():
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    slot = callback_slot({"date": "2026-10-13", "time": "14:30"}, now)
    assert slot.strftime("%H:%M %Z") == "14:30 PDT"
    assert slot.astimezone(timezone.utc).hour == 21


@pytest.mark.parametrize("inp", [{}, {"day_of_week": "tuesday"}, {"delay_hours": -1}, {"delay_hours": 0}])
def test_callback_does_not_invent_time(inp):
    with pytest.raises(ValueError):
        callback_slot(inp)


@pytest.mark.parametrize("disposition", ["HOT", "WARM", "COLD"])
def test_interest_is_not_a_completed_next_step(disposition):
    ctx = CallContext(disposition=disposition)
    assert ObjectiveEngine().decide(ctx) != "STAGE_5_WRAP"


def test_slots_support_actual_owner_and_scheduling_state():
    ctx = CallContext()
    ctx.owner_confirmed = True
    ctx.pre_close_done = True
    ctx.appointment_set = True
    ctx._dnc_flagged = True
    assert ObjectiveEngine().decide(ctx) == "STAGE_5_WRAP"


@pytest.mark.parametrize("text", ["My address is 1234 Main Street", "Built in 1998", "The loan is 150000", "No rush, take your time"])
def test_other_numbers_do_not_become_an_offer(text):
    assert _extract_price_cents(text) is None


@pytest.mark.parametrize("text,expected", [("My asking price is 150000", 15000000), ("I'd take $175,000", 17500000), ("Around 200 thousand", 20000000)])
def test_explicit_price_uses_cents(text, expected):
    assert _extract_price_cents(text) == expected


def test_context_injection_preserves_caller_and_tool_blocks():
    original = [{"role": "system", "content": "Base"}, {"role": "user", "content": "Yes, Tuesday works"}, {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "x", "input": {}}]}]
    context = SimpleNamespace(messages=list(original))
    tracker = ContextTrackerProcessor(CallContext(), context)
    for _ in range(100):
        tracker._inject_context_prefix()
    assert context.messages[2:] == original[1:]
    assert len(context.messages) == 4
    assert context.messages[1]["role"] == "system"


@pytest.mark.asyncio
async def test_first_outbound_response_is_not_swallowed():
    ctx = CallContext(is_outbound=True)
    tracker = ContextTrackerProcessor(ctx)
    tracker.push_frame = AsyncMock()
    frame = TranscriptionFrame("Yes, speaking", "seller", "now")
    await tracker.process_frame(frame, D)
    tracker.push_frame.assert_awaited_once_with(frame, D)
    assert ctx.owner_confirmed
    assert ctx._opener_fired


@pytest.mark.asyncio
async def test_first_outbound_opt_out_is_persisted_and_ends():
    task = SimpleNamespace(queue_frames=AsyncMock())
    ctx = CallContext(is_outbound=True, seller_phone="+15555550100", lead_id="lead", _task_ref=task)
    tracker = ContextTrackerProcessor(ctx)
    tracker.push_frame = AsyncMock()
    with patch("backend.voice.tools.execute_tool") as persist:
        await tracker.process_frame(TranscriptionFrame("Stop calling me", "seller", "now"), D)
    persist.assert_called_once_with("honor_stop_request", {"verbatim": "Stop calling me"}, ctx)
    assert ctx.call_should_end
    assert isinstance(task.queue_frames.call_args.args[0][-1], EndFrame)
    tracker.push_frame.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_session_routes_stream_id_not_call_id():
    ws = SimpleNamespace(receive_text=AsyncMock(side_effect=[json.dumps({"event": "connected"}), json.dumps({"event": "start", "streamSid": "MZstream", "start": {"callSid": "CAcall"}})]))
    session = await read_media_session(ws, "CAcall")
    assert session.call_sid == "CAcall"
    assert session.stream_sid == "MZstream"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"event": "start", "start": {"callSid": "wrong", "streamSid": "stream"}},
    {"event": "start", "start": {"callSid": "call"}},
    {"event": "media"},
    {"event": "start", "start": {"callSid": "call", "streamSid": "stream", "mediaFormat": {"encoding": "audio/x-L16", "sampleRate": 16000, "channels": 1}}},
])
async def test_invalid_media_sessions_fail_closed(payload):
    ws = SimpleNamespace(receive_text=AsyncMock(return_value=json.dumps(payload)))
    with pytest.raises(ValueError):
        await read_media_session(ws, "call")


def test_media_token_scope_and_tamper_protection(monkeypatch):
    monkeypatch.setenv("SIGNALWIRE_SIGNING_KEY", "test-key")
    token = issue_stream_token("inbound:call")
    assert validate_stream_token(token, "inbound:call")
    assert not validate_stream_token(token, "outbound:lead")
    assert not validate_stream_token(token + "tamper", "inbound:call")
    assert not validate_stream_token("", "inbound:call")


def test_compatibility_webhook_signature_rejects_tampering():
    url = "https://example.com/api/voice/inbound"
    body = b"CallSid=call&From=%2B15555550100"
    canonical = url + "CallSidcallFrom+15555550100"
    signature = base64.b64encode(hmac.new(b"key", canonical.encode(), hashlib.sha1).digest()).decode()
    assert valid_signalwire_signature("key", signature, url, body)
    assert not valid_signalwire_signature("key", signature, url, body + b"0")
    assert not valid_signalwire_signature("", signature, url, body)


def test_operator_routes_require_credentials(monkeypatch):
    monkeypatch.setenv("OPERATOR_API_TOKEN", "private-test-token")
    app = FastAPI()
    app.add_middleware(OperatorAuthentication)
    @app.get("/api/private")
    async def private():
        return {"ok": True}
    with TestClient(app) as client:
        assert client.get("/api/private").status_code == 401
        assert client.get("/api/private", headers={"Authorization": "Bearer private-test-token"}).status_code == 200
        assert client.post("/api/voice/inbound").status_code == 403
        assert client.get("/healthz").status_code == 200


def test_csv_can_be_read_from_uploaded_stream():
    from backend.scout.parser import parse_csv
    rows = parse_csv(io.StringIO("apn,address,city,state\n123,123 Main St,Stockton,CA\n"))
    assert rows[0]["address"] == "123 Main St"


def test_failed_sms_does_not_claim_success():
    from backend.voice.tools import _send_followup_sms
    with patch("backend.voice.tools.send_sms", return_value=False):
        assert "not sent" in _send_followup_sms({"to": "+15555550100", "message": "hello"})


def test_failed_booking_does_not_change_call_state():
    from backend.voice.tools import _book_appointment
    ctx = CallContext()
    with patch("backend.lib.db.reserve_voice_appointment", side_effect=RuntimeError("unavailable")):
        result = _book_appointment({"lead_id": "lead", "address": "123 Main", "date": "2026-10-15", "time": "10:00", "confirmed": True}, ctx)
    assert "not booked" in result
    assert not ctx.appointment_set


def test_tool_cannot_modify_another_lead():
    from backend.voice.tools import execute_tool
    ctx = CallContext(lead_id="bound")
    with patch("backend.voice.tools._preflight_gate") as gate:
        assert "follow up" in execute_tool("set_disposition", {"lead_id": "other", "disposition": "HOT"}, ctx)
    gate.assert_not_called()


def test_compliance_failure_blocks_outbound():
    from backend.compliance.compliance import ComplianceEngine
    with patch("backend.lib.db.get_lead_with_property", side_effect=RuntimeError("DB unavailable")):
        assert not ComplianceEngine().check_call_allowed("lead").allowed
        assert not ComplianceEngine().check_sms_allowed("lead").allowed


@pytest.mark.asyncio
async def test_live_pipeline_can_construct_without_network(monkeypatch):
    from backend.voice import agent
    from starlette.websockets import WebSocket
    for name in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "HTTP_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-only")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    monkeypatch.setenv("VOICE_TTS_PROVIDER", "deepgram")
    ws = WebSocket({"type": "websocket", "path": "/test", "headers": []}, AsyncMock(), AsyncMock())
    runner = AsyncMock()
    with patch.object(agent, "PipelineRunner", return_value=runner), patch.object(agent, "_handle_call_end", new_callable=AsyncMock):
        await agent.run_sophia_agent(ws, "call", {"stream_sid": "stream"})
    task = runner.run.call_args.args[0]
    def flatten(processor):
        children = getattr(processor, "_processors", None)
        if children:
            return [name for child in children for name in flatten(child)]
        return [type(processor).__name__]
    names = flatten(task._pipeline)
    await task._pipeline.cleanup()
    assert "SpeechChunker" not in names
    assert "BotSpeakingSTTMuteProcessor" not in names
    assert "PhoneEQProcessor" not in names
    assert names.index("SentenceStreamProcessor") < names.index("ComplianceOutputFilter") < names.index("DeepgramTTSService")
    assert names.index("ContextStateProcessor") < names.index("AnthropicLLMService")


def test_missing_pricing_permissions_do_not_authorize_offers():
    from backend.voice.tools import _preflight_gate
    ctx = CallContext(lead_id="lead")
    assert _preflight_gate("send_offer_summary", SimpleNamespace(lead_id="lead", call_sid="call"), ctx)["blocked"]
    assert _preflight_gate("get_offer_range", SimpleNamespace(lead_id="lead", call_sid="call"), ctx)["blocked"]


@pytest.mark.asyncio
async def test_phone_serializer_uses_validated_stream_for_audio_and_clear():
    from pipecat.frames.frames import OutputAudioRawFrame
    from pipecat.serializers.twilio import TwilioFrameSerializer
    serializer = TwilioFrameSerializer(stream_sid="stream-not-call", params=TwilioFrameSerializer.InputParams(auto_hang_up=False))
    clear = json.loads(await serializer.serialize(InterruptionFrame()))
    assert clear == {"event": "clear", "streamSid": "stream-not-call"}
    audio = json.loads(await serializer.serialize(OutputAudioRawFrame(audio=b"\x00\x00" * 160, sample_rate=8000, num_channels=1)))
    assert audio["streamSid"] == "stream-not-call"
    assert len(base64.b64decode(audio["media"]["payload"])) == 160


@pytest.mark.asyncio
async def test_numeric_reply_reaches_conversation():
    from backend.voice.processors.input_guard import InputGuardProcessor
    processor = InputGuardProcessor(CallContext())
    processor.push_frame = AsyncMock()
    frame = TranscriptionFrame("150000", "seller", "now")
    await processor.process_frame(frame, D)
    processor.push_frame.assert_awaited_once_with(frame, D)


@pytest.mark.asyncio
@pytest.mark.parametrize("frame_type", [TextFrame, TTSSpeakFrame])
async def test_stage_directions_are_removed_from_all_speaking_paths(frame_type):
    from backend.voice.processors.speech_output import SpeechOutputProcessor
    processor = SpeechOutputProcessor()
    processor.push_frame = AsyncMock()
    frame = frame_type("[sympathetic] I'm sorry to hear that.")
    await processor.process_frame(frame, D)
    assert frame.text == "I'm sorry to hear that."


def test_unsubscribe_token_is_scoped_and_tamper_protected(monkeypatch):
    from backend.alerts.email import create_unsubscribe_token, verify_unsubscribe_token
    monkeypatch.setenv("EMAIL_UNSUBSCRIBE_SECRET", "test-only")
    token = create_unsubscribe_token("lead", "seller@example.com")
    assert verify_unsubscribe_token(token) == ("lead", "seller@example.com")
    assert verify_unsubscribe_token(token + "tamper") is None


def test_atomic_capacity_limits_100_concurrent_attempts(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import fakeredis
    from backend.voice import outbound
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(outbound, "_get_redis_client", lambda: redis)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda i: outbound._acquire_call_slot(f"lead-{i}"), range(100)))
    assert sum(results) == 3
    assert not outbound._acquire_call_slot("lead-0")
    for i in range(100):
        outbound._release_call_slot(f"lead-{i}")
    assert redis.zcard(outbound._REDIS_CONCURRENT_KEY) == 0
    assert outbound._acquire_call_slot("fresh")


def test_capacity_failure_blocks_dialing(monkeypatch):
    from backend.voice import outbound
    monkeypatch.setattr(outbound, "_get_redis_client", lambda: None)
    assert not outbound._acquire_call_slot("lead")


@pytest.mark.parametrize("text", ["I don't want to sell", "I'm not selling it", "I never want to sell my home"])
def test_negated_intent_does_not_lock_sales_path(text):
    ctx = CallContext()
    ContextTrackerProcessor(ctx)._analyze(text)
    assert not ctx.intent_locked


def test_no_rush_does_not_force_fast_conversation():
    ctx = CallContext()
    ContextTrackerProcessor(ctx)._analyze("There's no rush, I'm not in a hurry")
    assert ctx.seller_energy == "calm"


def test_preclose_advances_only_after_real_question_and_agreement():
    ctx = CallContext()
    tracker = ContextTrackerProcessor(ctx)
    tracker._analyze("Yes")
    assert not ctx.pre_close_done
    ctx._walkthrough_asked = True
    tracker._analyze("Yes, sounds good")
    assert ctx.pre_close_done


def test_pending_callback_survives_failed_attempt():
    from backend.api.main import _run_pending_followups
    callback = {"id": "lead", "callback_scheduled_at": "2026-10-12T18:00:00Z"}
    with patch("backend.lib.db.campaign_is_running", return_value=True), patch("backend.lib.db.claim_due_call_followups", return_value=[]), patch("backend.lib.db.claim_due_callbacks", return_value=[callback]), patch("backend.voice.outbound.call_lead", return_value={"success": False}), patch("backend.lib.db.finish_callback_claim") as finish:
        _run_pending_followups()
    finish.assert_called_once_with("lead", callback["callback_scheduled_at"], False)


@pytest.mark.asyncio
async def test_spanish_stt_configuration_is_applied():
    from backend.voice.agent import _create_stt_service
    service = await _create_stt_service("test-only", True)
    assert str(service._settings.language) in ("es", "Language.ES")


@pytest.mark.asyncio
async def test_cartesia_provider_constructs_from_explicit_configuration(monkeypatch):
    from backend.voice.agent import _build_tts
    from pipecat.services.cartesia.tts import CartesiaTTSService
    monkeypatch.setenv("VOICE_TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "test-only")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "test-voice")
    service = await _build_tts(CallContext())
    assert isinstance(service, CartesiaTTSService)
    assert service._settings.voice == "test-voice"


def test_followup_requires_exact_time_and_saved_row():
    from backend.voice.tools import _schedule_followup

    with patch("backend.voice.tools.create_followup") as save:
        assert "exact" in _schedule_followup({"lead_id": "lead", "callback_time": "tomorrow"})
        save.assert_not_called()
    when = (datetime.now(timezone.utc) + __import__("datetime").timedelta(days=1)).isoformat()
    with patch("backend.voice.tools.create_followup", return_value=None):
        assert "No callback" in _schedule_followup({"lead_id": "lead", "callback_time": when})
    with patch("backend.voice.tools.create_followup", return_value="saved") as save:
        assert "scheduled" in _schedule_followup({"lead_id": "lead", "callback_time": when})
        assert save.call_args.kwargs["scheduled_at"] == when


@pytest.fixture(autouse=True)
def isolate_voice_audit_writes(monkeypatch):
    monkeypatch.setattr("backend.lib.db.write_tool_gate_log", lambda *args, **kwargs: None)


def test_outbound_disabled_prevents_provider_and_database_access(monkeypatch):
    from backend.voice.outbound import call_lead

    monkeypatch.setenv("OUTBOUND_ENABLED", "false")
    with patch("backend.voice.outbound.get_lead_with_property") as load:
        assert call_lead("lead")["reason"] == "outbound_disabled"
    load.assert_not_called()
