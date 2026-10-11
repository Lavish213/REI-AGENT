from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pipecat.frames.frames import CancelFrame, EndFrame, InterruptionFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection

from backend.api.security import OperatorAuthentication, valid_signalwire_signature
from backend.contracts.intel_packet import GATED_TOOLS
from backend.voice.execution_context import ResolvedContext, sanitize
from backend.voice.processors.context_tracker import CallContext
from backend.voice.processors.sentence_streamer import SentenceStreamProcessor
from backend.voice.scheduling import PACIFIC, local_slot
from backend.voice.session import read_media_session, validate_stream_token
from backend.voice.tools import _preflight_gate


D = FrameDirection.DOWNSTREAM
RESOLVED = ResolvedContext("lead-test", "CA-test", "tenant-test", "+15555550101", "seller@example.com", "100 Test Ave")
NOW = datetime(2026, 10, 11, 14, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolate_external_effects(monkeypatch):
    monkeypatch.setenv("OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("TENANT_ID", "tenant-test")
    monkeypatch.setattr("backend.lib.db.write_tool_gate_log", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.lib.db.create_approval_request", lambda *args, **kwargs: "approval-test")


@pytest.mark.parametrize("tool", sorted(GATED_TOOLS))
@pytest.mark.parametrize("packet", [None, {}, [], "bad", 3, {"safe_for_live_call": False}, {"safe_for_live_call": "true", "action_permissions": {}}, {"safe_for_live_call": True, "action_permissions": []}, {"safe_for_live_call": True, "action_permissions": "bad"}])
def test_permission_matrix_denies_missing_and_malformed_packets(tool, packet):
    ctx = CallContext(intel_packet=packet)
    assert _preflight_gate(tool, RESOLVED, ctx)["blocked"]


@pytest.mark.parametrize("tool", sorted(GATED_TOOLS))
@pytest.mark.parametrize("level", [None, "", "admin", "allowed", "send_everything", 1, True, [], {}])
def test_permission_matrix_denies_unknown_levels(tool, level):
    packet = {"safe_for_live_call": True, "action_permissions": {tool: {"level": level}}}
    assert _preflight_gate(tool, RESOLVED, CallContext(intel_packet=packet))["blocked"]


@pytest.mark.parametrize("tool,level", [("book_appointment", "book_appointment"), ("schedule_callback", "book_appointment"), ("get_available_appointments", "read_availability"), ("send_followup_sms", "send_summary"), ("transfer_call", "transfer_call"), ("ask_operator", "ask_operator")])
@pytest.mark.parametrize("mutation", ["expired", "malformed_expiry", "unsafe", "disabled", "wrong_action", "non_boolean_safe"])
def test_valid_action_becomes_denied_after_authority_mutation(tool, level, mutation, monkeypatch):
    packet = {"safe_for_live_call": True, "action_permissions": {tool: {"level": level, "scope": "call"}}}
    if mutation == "expired": packet["action_permissions"][tool]["expires_at"] = "2000-01-01T00:00:00Z"
    if mutation == "malformed_expiry": packet["action_permissions"][tool]["expires_at"] = "not-a-date"
    if mutation == "unsafe": packet["safe_for_live_call"] = False
    if mutation == "non_boolean_safe": packet["safe_for_live_call"] = "false"
    if mutation == "disabled": monkeypatch.setenv("OUTBOUND_ENABLED", "false")
    if mutation == "wrong_action": packet["action_permissions"][tool]["level"] = "quote_range" if level != "quote_range" else "send_summary"
    result = _preflight_gate(tool, RESOLVED, CallContext(intel_packet=packet))
    assert result["blocked"] or (mutation == "disabled" and tool == "get_available_appointments")


@pytest.mark.parametrize("payload", [None, [], 42, "hello", {}, {"event": "start", "start": []}, {"event": "start", "start": "x"}, {"event": "start", "start": {"callSid": [], "streamSid": "MZ-test"}}, {"event": "start", "start": {"callSid": "CA-test", "streamSid": {}}}])
async def test_media_protocol_rejects_invalid_shapes(payload):
    socket = SimpleNamespace(receive_text=AsyncMock(return_value=json.dumps(payload)))
    with pytest.raises(ValueError):
        await read_media_session(socket)


@pytest.mark.parametrize("field,value", [("encoding", "audio/pcm"), ("sampleRate", 16000), ("channels", 2), ("sampleRate", []), ("channels", True)])
async def test_media_protocol_rejects_codec_mutations(field, value):
    media = {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}
    media[field] = value
    socket = SimpleNamespace(receive_text=AsyncMock(return_value=json.dumps({"event": "start", "start": {"callSid": "CA-test", "streamSid": "MZ-test", "mediaFormat": media}})))
    with pytest.raises(ValueError): await read_media_session(socket)


@pytest.mark.parametrize("payload", [None, [], "x", {}, {"scope": "call", "expires": "bad"}, {"scope": "call", "expires": True}, {"scope": [], "expires": 0}, {"scope": "wrong", "expires": 0}])
def test_signed_but_malformed_tokens_deny_without_crashing(payload, monkeypatch):
    monkeypatch.setenv("SIGNALWIRE_SIGNING_KEY", "test-key")
    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = hmac.new(b"test-key", data.encode(), hashlib.sha256).hexdigest()
    assert not validate_stream_token(data + "." + signature, "call")


@pytest.mark.parametrize("signature", ["é", "🤯", "\x00", "", "a" * 10000])
def test_provider_signature_garbage_does_not_crash(signature):
    assert not valid_signalwire_signature("test-key", signature, "https://example.test/hook", b"From=%2B15555550101")


@pytest.mark.parametrize("frame_type", [CancelFrame, EndFrame, InterruptionFrame, LLMFullResponseStartFrame])
async def test_control_frames_clear_pending_speech(frame_type):
    p = SentenceStreamProcessor(enable_direct_mode=True)
    p.push_frame = AsyncMock()
    await p.process_frame(LLMTextFrame("Unfinished old thought"), D)
    await p.process_frame(frame_type(), D)
    await p.process_frame(LLMTextFrame("Fresh."), D)
    await p.process_frame(LLMFullResponseEndFrame(), D)
    assert [args[0].text for args, _ in p.push_frame.call_args_list if isinstance(args[0], TTSTextFrame)] == ["Fresh. "]


@pytest.mark.parametrize("size", [1201, 5000, 10000, 100000])
async def test_single_large_frame_cannot_leave_unbounded_speech_buffer(size):
    p = SentenceStreamProcessor(enable_direct_mode=True)
    p.push_frame = AsyncMock()
    await p.process_frame(LLMTextFrame("x" * size), D)
    assert len(p._buffer) <= 1200
    await p.process_frame(LLMFullResponseEndFrame(), D)
    assert sum(len(args[0].text.strip()) for args, _ in p.push_frame.call_args_list if isinstance(args[0], TTSTextFrame)) == size


async def test_decimal_split_between_llm_chunks_is_not_spoken_as_two_numbers():
    p = SentenceStreamProcessor(enable_direct_mode=True)
    p.push_frame = AsyncMock()
    await p.process_frame(LLMTextFrame("The amount is $150."), D)
    await p.process_frame(LLMTextFrame("50. Is that right?"), D)
    await p.process_frame(LLMFullResponseEndFrame(), D)
    text = "".join(args[0].text for args, _ in p.push_frame.call_args_list if isinstance(args[0], TTSTextFrame))
    assert "$150.50" in text


@pytest.mark.parametrize("day", range(1, 180))
def test_calendar_roundtrip_across_entire_booking_horizon(day):
    target = (NOW + timedelta(days=day)).astimezone(PACIFIC).replace(hour=10, minute=0, second=0, microsecond=0)
    slot = local_slot(target.strftime("%Y-%m-%d"), "10:00", NOW)
    assert slot.astimezone(timezone.utc).astimezone(PACIFIC) == target


@pytest.mark.parametrize("tool", ["send_followup_sms", "send_followup_email", "book_appointment", "schedule_callback"])
def test_identity_fuzz_never_changes_bound_destinations(tool):
    rng = random.Random(1729)
    for _ in range(250):
        supplied = {k: str(rng.getrandbits(64)) for k in ["lead_id", "tenant_id", "to", "email", "phone", "address", "call_sid"]}
        clean = sanitize(tool, supplied, RESOLVED)
        assert clean["lead_id"] == RESOLVED.lead_id
        assert clean["address"] == RESOLVED.address
        assert clean["to"] == (RESOLVED.seller_email if tool == "send_followup_email" else RESOLVED.seller_phone)


def test_redis_repeated_contention_and_duplicate_leads(monkeypatch):
    from backend.voice import outbound
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(outbound, "_get_redis_client", lambda: client)
    with ThreadPoolExecutor(max_workers=32) as pool:
        for cycle in range(20):
            candidates = [f"lead-{cycle}-{i % 12}" for i in range(128)]
            admitted = list(pool.map(outbound._acquire_call_slot, candidates))
            assert sum(admitted) == 3
            assert client.zcard(outbound._REDIS_CONCURRENT_KEY) == 3
            for lead in client.zrange(outbound._REDIS_CONCURRENT_KEY, 0, -1): outbound._release_call_slot(lead)
    assert client.zcard(outbound._REDIS_CONCURRENT_KEY) == 0


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
def test_provider_http_failures_cannot_become_acknowledgments(status, monkeypatch):
    import httpx
    from backend.lib.signalwire_rest import signalwire_post
    monkeypatch.setenv("SIGNALWIRE_SPACE", "test.signalwire.com")
    monkeypatch.setenv("SIGNALWIRE_PROJECT_ID", "project-test")
    monkeypatch.setenv("SIGNALWIRE_TOKEN", "token-test")
    response = httpx.Response(status, request=httpx.Request("POST", "https://test.signalwire.com"), json={"sid": "fake"})
    with patch("backend.lib.signalwire_rest.httpx.Client") as client:
        client.return_value.__enter__.return_value.post.return_value = response
        with pytest.raises(httpx.HTTPStatusError): signalwire_post("Messages.json", {})


@pytest.mark.parametrize("mutation", ["none", "body", "time", "signature", "missing_key"])
def test_sendgrid_real_ecdsa_contract(mutation, monkeypatch):
    import time
    from backend.api.routes.email_webhook import _verify_signature
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setenv("SENDGRID_WEBHOOK_PUBLIC_KEY", base64.b64encode(public).decode())
    timestamp = str(int(time.time()))
    body = b'[{"event":"delivered","email":"seller@example.com"}]'
    signature = base64.b64encode(key.sign(timestamp.encode() + body, ec.ECDSA(hashes.SHA256()))).decode()
    if mutation == "body": body += b" "
    if mutation == "time": timestamp = str(int(timestamp) - 301)
    if mutation == "signature": signature = base64.b64encode(b"broken").decode()
    if mutation == "missing_key": monkeypatch.delenv("SENDGRID_WEBHOOK_PUBLIC_KEY")
    assert _verify_signature(body, signature, timestamp) == (mutation == "none")


@pytest.mark.parametrize("path", ["/api/health", "/docs", "/openapi.json", "/api/calls", "/api/evals", "/api/appointments/availability"])
def test_admin_route_matrix(path, monkeypatch):
    monkeypatch.setenv("OPERATOR_API_TOKEN", "operator-test")
    app = FastAPI()
    app.add_middleware(OperatorAuthentication)
    @app.get(path)
    def endpoint(): return {"ok": True}
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        with patch("backend.lib.db.get_operator_user", return_value=None):
            assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer operator-test"}).status_code == 200


def test_signed_webhook_body_survives_authentication(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://example.test")
    monkeypatch.setenv("SIGNALWIRE_SIGNING_KEY", "test-key")
    app = FastAPI()
    app.add_middleware(OperatorAuthentication)
    @app.post("/api/voice/test")
    async def hook(request: Request): return {"body": (await request.body()).decode()}
    body = "CallSid=CA-test&From=%2B15555550101"
    url = "https://example.test/api/voice/test"
    signature = hmac.new(b"test-key", url.encode() + body.encode(), hashlib.sha1).hexdigest()
    with TestClient(app) as client:
        response = client.post("/api/voice/test", content=body, headers={"x-signalwire-signature": signature})
        assert response.status_code == 200
        assert response.json()["body"] == body


@pytest.mark.parametrize("tool", sorted(GATED_TOOLS))
@pytest.mark.parametrize("permission", ["book_appointment", [], True, 1, {"level": "book_appointment", "expires_at": []}])
def test_permission_objects_reject_malformed_shapes(tool, permission):
    packet = {"safe_for_live_call": True, "action_permissions": {tool: permission}}
    assert _preflight_gate(tool, RESOLVED, CallContext(intel_packet=packet))["blocked"]


@pytest.mark.parametrize("tool", ["book_appointment", "send_followup_sms", "schedule_callback", "transfer_call", "get_offer_range"])
def test_human_review_kill_switch_blocks_side_effects(tool):
    levels = {"book_appointment": "book_appointment", "send_followup_sms": "send_summary", "schedule_callback": "book_appointment", "transfer_call": "transfer_call", "get_offer_range": "quote_range"}
    ctx = CallContext(kill_switch_active=True, intel_packet={"safe_for_live_call": True, "action_permissions": {tool: {"level": levels[tool], "scope": "call"}}})
    assert _preflight_gate(tool, RESOLVED, ctx)["blocked"]


@pytest.mark.parametrize("value,expected", [("1.15", 115), ("1.005", 101), ("$1,234.56", 123456), ("NaN", None), ("inf", None), ("-inf", None), ("bad", None), (None, None)])
def test_import_money_exactness_and_nonfinite_rejection(value, expected):
    from backend.scout.parser import _to_cents
    assert _to_cents(value) == expected


@pytest.mark.parametrize("text,expected", [("The price is $150.50", 15050), ("I'm asking 350.5k", 35050000), ("My mortgage is $120,000, asking $400,000", 40000000), ("I owe $120,000 on my mortgage", None), ("I'm asking $-100,000", None), ("I'm asking $350,000", 35000000)])
def test_price_state_distinguishes_asking_from_debt_and_decimal_amounts(text, expected):
    from backend.voice.processors.context_tracker import _extract_price_cents
    assert _extract_price_cents(text) == expected


@pytest.mark.parametrize("text", ["I'm not free and clear", "No, the mortgage is not paid off", "I don't own it outright"])
def test_negated_equity_does_not_claim_free_and_clear(text):
    from backend.voice.processors.context_tracker import ContextTrackerProcessor
    ctx = CallContext()
    ContextTrackerProcessor(ctx)._analyze(text)
    assert not ctx.free_and_clear


def test_corrected_mortgage_replaces_earlier_state():
    from backend.voice.processors.context_tracker import ContextTrackerProcessor
    ctx = CallContext()
    p = ContextTrackerProcessor(ctx)
    p._analyze("I have a mortgage")
    p._analyze("Actually I paid it off, the property is free and clear")
    assert ctx.free_and_clear
    assert ctx.mortgage_status == "clear"


@pytest.mark.parametrize("text", ["¿Eres una IA?", "¿Eres un robot?", "¿Estoy hablando con una persona real?", "Is this artificial intelligence?", "Are you automated?"])
def test_identity_questions_cover_both_supported_languages(text):
    from backend.voice.processors.ai_identity import _AI_QUESTION
    assert _AI_QUESTION.search(text)


@pytest.mark.parametrize("comp", [{"sold_price": -100, "sqft": 1000}, {"sold_price": float("nan"), "sqft": 1000}, {"sold_price": float("inf"), "sqft": 1000}, {"sold_price": "bad", "sqft": 1000}, {"sold_price": 100000, "sqft": "bad"}])
def test_invalid_comps_cannot_create_offer_authority(comp):
    from backend.comps.calculator import calculate_arv
    result = calculate_arv([comp], 1000)
    assert result["arv"] is None
    assert result["mao"] is None


@pytest.mark.parametrize("price", [1.15, 100.01, 1234.56, 333333.33, 999999.99])
def test_mao_uses_exact_integer_cents_formula(price):
    from backend.comps.calculator import calculate_arv
    result = calculate_arv([{"sold_price": price, "sqft": 1000}], 1000)
    assert result["arv"] == int(__import__("decimal").Decimal(str(price)) * 100)
    assert result["mao"] == max(result["arv"] * 70 // 100 - 2500000, 0)


async def test_media_handshake_timeout_cancels_reader():
    import time
    cancelled = asyncio.Event()
    async def stalled():
        try: await asyncio.Event().wait()
        finally: cancelled.set()
    started = time.monotonic()
    with pytest.raises(asyncio.TimeoutError): await read_media_session(SimpleNamespace(receive_text=stalled))
    assert 4.8 < time.monotonic() - started < 6
    assert cancelled.is_set()


@pytest.mark.parametrize("text", ["Don't call me again", "Please stop contacting me", "Lose my number", "No me vuelvas a llamar", "Quítame de tu lista"])
async def test_opt_out_variations_stop_before_more_conversation(text):
    from backend.voice.processors.context_tracker import ContextTrackerProcessor
    from pipecat.frames.frames import TranscriptionFrame
    ctx = CallContext(lead_id="lead-test", seller_phone="+15555550101", _task_ref=SimpleNamespace(queue_frames=AsyncMock()))
    p = ContextTrackerProcessor(ctx)
    p.push_frame = AsyncMock()
    with patch("backend.voice.tools.execute_tool") as stop:
        await p.process_frame(TranscriptionFrame(text, "seller", "now"), D)
    assert ctx.call_should_end
    stop.assert_called_once_with("honor_stop_request", {"verbatim": text}, ctx)
    p.push_frame.assert_not_awaited()


def test_real_redis_contention_and_expiration(monkeypatch, tmp_path):
    import shutil
    import socket
    import subprocess
    import time
    from pathlib import Path
    import redis
    from backend.voice import outbound
    binary = shutil.which("redis-server")
    if not binary:
        redislite = pytest.importorskip("redislite")
        binary = str(Path(redislite.__file__).parent / "bin" / "redis-server")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([binary, "--bind", "127.0.0.1", "--port", str(port), "--save", "", "--appendonly", "no", "--dir", str(tmp_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = redis.Redis(host="127.0.0.1", port=port, decode_responses=True, socket_timeout=1)
    try:
        for _ in range(100):
            try:
                if client.ping(): break
            except redis.ConnectionError: time.sleep(0.02)
        else: pytest.fail("Local Redis did not start")
        monkeypatch.setattr(outbound, "_get_redis_client", lambda: client)
        with ThreadPoolExecutor(max_workers=64) as pool:
            for cycle in range(30):
                results = list(pool.map(outbound._acquire_call_slot, [f"lead-{cycle}-{i % 40}" for i in range(256)]))
                assert sum(results) == 3
                assert client.zcard(outbound._REDIS_CONCURRENT_KEY) == 3
                for lead in client.zrange(outbound._REDIS_CONCURRENT_KEY, 0, -1): outbound._release_call_slot(lead)
        client.zadd(outbound._REDIS_CONCURRENT_KEY, {"expired": time.time() - 1})
        assert outbound._acquire_call_slot("fresh")
        assert client.zscore(outbound._REDIS_CONCURRENT_KEY, "expired") is None
        assert not outbound._acquire_call_slot("fresh")
        assert client.ttl(outbound._REDIS_CONCURRENT_KEY) > 0
    finally:
        client.close()
        process.terminate()
        process.wait(timeout=5)


def test_nonascii_bearer_is_rejected_without_server_error(monkeypatch):
    monkeypatch.setenv("OPERATOR_API_TOKEN", "test-key")
    app = FastAPI()
    app.add_middleware(OperatorAuthentication)
    @app.get("/api/test")
    def endpoint(): return {"ok": True}
    with TestClient(app) as client:
        assert client.get("/api/test", headers={b"authorization": b"Bearer \xe9"}).status_code == 401


def test_offer_quote_converts_cents_and_never_exceeds_ceiling():
    from backend.voice.tools import _get_offer_range
    lead = {"properties": {"estimated_arv": 35000000, "mao": 20000000, "arv_confidence": "high"}}
    with patch("backend.lib.db.get_lead_with_property", return_value=lead):
        result = _get_offer_range({"lead_id": "lead-test", "address": "100 Test Ave"})
    assert "$190,000" in result
    assert "$200,000" in result
    assert "19,000,000" not in result


def test_offer_send_does_not_trust_model_supplied_price():
    from backend.voice.tools import _send_offer_summary
    lead = {"properties": {"estimated_arv": 35000000, "mao": 20000000, "arv_confidence": "high"}}
    with patch("backend.lib.db.get_lead_with_property", return_value=lead), patch("backend.alerts.sms.send_sms", return_value=True) as send:
        _send_offer_summary({"lead_id": "lead-test", "seller_phone": "+15555550101", "offer_low": 9000000, "offer_high": 99999999})
    body = send.call_args.kwargs["body"]
    assert "$200,000" in body
    assert "$99,999,999" not in body


def test_human_approval_threshold_compares_cents_to_cents():
    packet = {"safe_for_live_call": True, "action_permissions": {"get_offer_range": {"level": "quote_range"}}, "compliance_context": {"requires_human_approval_above": 30000000}}
    ctx = CallContext(intel_packet=packet, last_price_mentioned=35000000)
    assert _preflight_gate("get_offer_range", RESOLVED, ctx)["blocked"]
    assert ctx.approval_pending == "approval-test"


def test_prompt_intel_formats_cent_amounts_as_dollars():
    from backend.contracts.intel_packet import build_prompt_intel_slice
    text = build_prompt_intel_slice({"packet_state": "approved", "strategy_context": {"max_offer": 20000000}, "compliance_context": {"requires_human_approval_above": 30000000}})
    assert "$200,000.00" in text
    assert "$300,000.00" in text


async def test_ten_thousand_interruption_cycles_do_not_replay_stale_text():
    p = SentenceStreamProcessor(enable_direct_mode=True)
    spoken = []
    async def capture(frame, direction):
        if isinstance(frame, TTSTextFrame): spoken.append(frame.text)
    p.push_frame = capture
    for _ in range(10000):
        await p.process_frame(LLMTextFrame("This answer should never finish"), D)
        await p.process_frame(InterruptionFrame(), D)
        await p.process_frame(LLMTextFrame("Fresh reply."), D)
        await p.process_frame(LLMFullResponseEndFrame(), D)
    assert len(spoken) == 10000
    assert set(spoken) == {"Fresh reply. "}
    assert not p._buffer


@pytest.mark.parametrize("action,failure", [("book_appointment", False), ("book_appointment", True), ("schedule_callback", False), ("schedule_callback", True)])
def test_server_bound_tools_and_saved_state(action, failure, monkeypatch):
    from backend.voice.tools import execute_tool
    lead = {"id": "lead-test", "tenant_id": "tenant-test", "owner_phone": "+15555550101", "properties": {"address": "100 Test Ave"}}
    packet = {"safe_for_live_call": True, "action_permissions": {action: {"level": "book_appointment", "scope": "call"}}}
    ctx = CallContext(lead_id="lead-test", _call_sid="CA-test", intel_packet=packet)
    tomorrow = (datetime.now(PACIFIC) + timedelta(days=1)).strftime("%Y-%m-%d")
    args = {"date": tomorrow, "time": "10:00", "confirmed": True, "lead_id": "attacker", "address": "attacker address", "seller_phone": "+15555550999"}
    saver = "reserve_voice_appointment" if action == "book_appointment" else "save_callback"
    with patch("backend.lib.db.get_lead_with_property", return_value=lead), patch("backend.lib.db." + saver, side_effect=RuntimeError("DB outage") if failure else None, return_value="saved-test") as save, patch("backend.voice.tools.send_sms", return_value=False):
        result = execute_tool(action, args, ctx)
    assert save.call_args.args[0] == "lead-test"
    if action == "book_appointment":
        assert save.call_args.args[2] == "100 Test Ave"
        assert ctx.appointment_set == (not failure)
        if not failure: assert "not sent" in result
    else:
        assert ctx.callback_set == (not failure)
    if failure: assert "not" in result.lower()


def test_old_callback_cannot_release_newer_attempt(monkeypatch):
    import time
    from backend.voice import outbound
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(outbound, "_get_redis_client", lambda: client)
    assert outbound._acquire_call_slot("lead-test", "old-generation")
    assert outbound._bind_call_slot("lead-test", "old-generation", "CA-old")
    client.zadd(outbound._REDIS_CONCURRENT_KEY, {"lead-test": time.time() - 1})
    assert outbound._acquire_call_slot("lead-test", "new-generation")
    assert outbound._bind_call_slot("lead-test", "new-generation", "CA-new")
    assert client.ttl(outbound._REDIS_CALLS_KEY) > 0
    assert not outbound._release_call_slot("lead-test", call_sid="CA-old")
    assert not outbound._release_call_slot("lead-test", attempt_token="old-generation")
    assert not outbound._release_call_slot("lead-test")
    assert client.zcard(outbound._REDIS_CONCURRENT_KEY) == 1
    assert outbound._release_call_slot("lead-test", call_sid="CA-new")
    assert client.zcard(outbound._REDIS_CONCURRENT_KEY) == 0


def test_delayed_provider_bind_cannot_overwrite_newer_generation(monkeypatch):
    import time
    from backend.voice import outbound
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(outbound, "_get_redis_client", lambda: client)
    assert outbound._acquire_call_slot("lead-test", "old")
    client.zadd(outbound._REDIS_CONCURRENT_KEY, {"lead-test": time.time() - 1})
    assert outbound._acquire_call_slot("lead-test", "new")
    assert not outbound._bind_call_slot("lead-test", "old", "CA-old")
    assert outbound._bind_call_slot("lead-test", "new", "CA-new")


def test_real_backend_route_inventory_is_protected(monkeypatch):
    import importlib
    monkeypatch.setenv("ENABLE_BACKGROUND_JOBS", "false")
    monkeypatch.setenv("OPERATOR_API_TOKEN", "operator-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    app = importlib.import_module("backend.api.main").app
    with TestClient(app) as client:
        checked = 0
        for path, operations in app.openapi()["paths"].items():
            methods = {method.upper() for method in operations}
            if not path.startswith("/api/") or path.startswith("/api/voice/") or path.startswith("/api/sms/inbound") or path in {"/api/email/webhook", "/api/email/unsubscribe"}:
                continue
            for method in methods & {"GET", "POST", "PATCH", "DELETE"}:
                response = client.request(method, path.replace("{lead_id}", "test").replace("{call_id}", "test"))
                assert response.status_code == 401, (method, path, response.status_code)
                checked += 1
        assert checked >= 20
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/health").status_code == 401


def test_accepted_provider_call_keeps_capacity_when_database_write_fails(monkeypatch):
    from backend.voice import outbound
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(outbound, "_get_redis_client", lambda: client)
    monkeypatch.setattr(outbound, "_is_calling_hours", lambda: True)
    lead = {"id": "lead-test", "properties": {"callable_phones": ["+15555550101"], "distress_score": 90}}
    with patch("backend.lib.db.campaign_is_running", return_value=True), patch("backend.compliance.compliance.ComplianceEngine.check_call_allowed", return_value=SimpleNamespace(allowed=True)), patch("backend.voice.outbound.get_lead_with_property", return_value=lead), patch("backend.voice.outbound._make_call", return_value={"call_sid": "CA-accepted", "status": "queued"}), patch("backend.voice.outbound.update_lead_call_outcome", side_effect=RuntimeError("DB outage")):
        result = outbound.call_lead("lead-test")
    assert result["success"]
    assert client.zcard(outbound._REDIS_CONCURRENT_KEY) == 1
    assert not outbound._acquire_call_slot("lead-test", "duplicate")
    assert outbound._release_call_slot("lead-test", call_sid="CA-accepted")
