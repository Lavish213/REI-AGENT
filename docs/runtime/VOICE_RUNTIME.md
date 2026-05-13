# Voice Runtime

## Overview

Sophia's voice runtime is a Pipecat 1.1.0 pipeline running over a FastAPI WebSocket connection, bridged from SignalWire via the Twilio-compatible streaming protocol.

## Call Lifecycle

```
SignalWire PSTN → SignalWire LaML webhook → /api/voice/inbound
→ WebSocket established at /voice/stream/{call_sid}
→ preload_call_context() runs in threadpool (property lookup, comps, OSM enrichment)
→ run_sophia_agent(websocket, call_sid, call_context)
  → stream_sid captured from SignalWire "start" event (loop up to 5 tries)
  → SellerMemory loaded from DB
  → System prompt assembled (sophia_core.md + property context + memory)
  → Pipecat Pipeline started
  → on_client_connected → LLM seeded with [call started] → Sophia speaks greeting
  → Turn loop: Seller speaks → STT → processors → LLM → TTS → Speaker
  → on_client_disconnected → pipeline cancelled
  → _handle_call_end(): transcript built, DB persisted, QA graded async
```

## Inbound vs Outbound

**Inbound:** Seller calls SIGNALWIRE_PHONE → webhook fires → context preloaded in background → WebSocket agent starts.

**Outbound:** `call_lead(lead_id)` → SignalWire REST call to seller phone → answered → outbound-webhook routes to WebSocket → `outbound_voice_stream` → `run_sophia_agent`.

## Boss Mode

If caller == OWNER_PHONE, `boss_mode=True`. System prompt switches to briefing mode. Sophia gives pipeline summary instead of seller acquisition flow.

## Latency Expectations

| Component | Target | Slow threshold |
|---|---|---|
| STT (Deepgram) | < 200ms | > 400ms |
| LLM (Haiku/Groq) | < 300ms | > 600ms |
| TTS (ElevenLabs) | < 200ms | > 400ms |
| End-to-end response | < 600ms | > 1000ms |

LatencyTracker logs each turn breakdown. LATENCY_TARGET_MS env var (default 800ms) controls warning threshold.

## Runtime Invariants

- All money values are integers (cents). Never floats.
- MAO = (ARV * 0.70) - 2500000 (in cents)
- stream_sid must come from SignalWire "start" event, not call_sid fallback
- STT is muted while bot is speaking (BotSpeakingSTTMuteProcessor)
- Context compression triggers at turn 6 if messages > 6 (compress_context via asyncio.to_thread)
- Seller memory capped at 10 call summaries
- All DB access through backend/lib/db.py only

## Error Recovery

- stream_sid capture timeout → fallback to call_sid with warning log
- Preload failure → fallback context "No property context available"
- QA grading failure → logged, call record preserved
- Transcript intel failure → logged, non-blocking
- Seller memory save failure → logged, non-blocking
- LLM failure → Pipecat pipeline error propagates to runner, call ends, _handle_call_end fires

## Observability

- Loguru: all runtime events logged with structured key=value pairs
- Langfuse: call start/end traces, tool execution events, turn generations (requires LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY)
- DB traces table: per-turn latency and token usage
- DB latency_benchmarks table: STT/LLM/TTS breakdown per turn
