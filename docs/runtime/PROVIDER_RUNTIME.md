# Provider Runtime

## Canonical Providers

| Layer | Provider | Env Vars | Fallback |
|---|---|---|---|
| Telephony | SignalWire | SIGNALWIRE_PROJECT_ID, SIGNALWIRE_TOKEN, SIGNALWIRE_SPACE, SIGNALWIRE_PHONE | None — hard requirement |
| STT | Deepgram | DEEPGRAM_API_KEY | None |
| LLM (voice) | Anthropic Claude | ANTHROPIC_API_KEY, VOICE_LLM_MODEL (default: claude-haiku-4-5-20251001) | Groq (GROQ_API_KEY) |
| LLM (QA/grading) | Anthropic Claude | ANTHROPIC_API_KEY, LLM_MODEL (default: claude-sonnet-4-6) | None |
| TTS | ElevenLabs | ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL | Orpheus via Together AI (TOGETHER_AI_API_KEY) |
| Persistence | Supabase | SUPABASE_URL, SUPABASE_SERVICE_KEY | None — hard requirement |
| Enrichment | BatchData | BATCHDATA_API_KEY | None (leads stay unenriched) |
| Observability | Langfuse | LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST | Silently disabled |
| SMS | SignalWire | (same as telephony) | None |

**Cartesia is deprecated.** No Cartesia imports or SDK dependencies remain in the codebase. The string `cartesia/orpheus-3b-0.1-ft` in `orpheus_tts.py` is the Together AI model identifier, not a Cartesia SDK reference.

## LLM Routing Logic

```python
if GROQ_API_KEY:
    llm = OpenAILLMService(
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
        max_tokens=80,
    )
else:
    llm = AnthropicLLMService(
        model=VOICE_LLM_MODEL,  # default: claude-haiku-4-5-20251001
        max_tokens=80,
    )
```

Groq path uses OpenAI-compatible API. Tools are NOT registered on the Groq path — `llm.register_function` is only called on the Anthropic path.

**Risk:** If GROQ_API_KEY is set, tool calls (book_appointment, set_disposition, etc.) will silently fail. Groq should only be used when tools are not required (testing, high-volume without booking).

## TTS Routing Logic

```python
if TOGETHER_AI_API_KEY:
    tts = OrpheusTTSService(voice="leah", sample_rate=24000)
else:
    tts = ElevenLabsTTSService(
        voice=ELEVENLABS_VOICE_ID,
        model=ELEVENLABS_MODEL,  # eleven_turbo_v2_5
        sample_rate=16000,
    )
```

ElevenLabs is the canonical production TTS. Orpheus (Together AI) is an alternative voice. Note: Orpheus sample_rate is 24000 vs ElevenLabs 16000 — the pipeline handles resampling for SignalWire output.

## Deepgram STT Configuration

```python
DeepgramSTTService(
    model="base",
    language="en-US",   # "es" if spanish_detected
    punctuate=True,
    interim_results=False,
    endpointing=200,    # 200ms silence = utterance end
)
```

## SignalWire Stream Protocol

- Inbound: POST `/api/voice/inbound` → returns LaML `<Connect><Stream url="wss://.../voice/stream/{call_sid}" /></Connect>`
- WebSocket receives: `connected` event, then `start` event (contains streamSid), then `media` events (base64 mulaw chunks)
- WebSocket sends: media events with base64 mulaw chunks back to caller
- `TwilioFrameSerializer` handles encoding/decoding on both directions
- `stream_sid` from `start.streamSid` must be used in outbound media frames (not call_sid)

## Backchannel Clip Pre-generation

At startup, `pregenerate_backchannel_clips()` calls ElevenLabs API to generate 8 short phrases ("Mhm", "Yeah", etc.) as PCM bytes. Stored in `app.state.backchannel_clips` and passed to each agent call. If startup generation fails, clips are generated per-call as fallback.

## Compliance Enforcement

All outbound calls check `ComplianceEngine.check_call_allowed()` before dialing:
1. `opted_out` flag
2. `dnc_blocked` flag
3. Calling hours (8am–9pm PT, America/Los_Angeles)
4. `callable` flag

All outbound SMS check `ComplianceEngine.check_sms_allowed()`. TCPA hours enforced by `send_sms()` regardless.

## Environment Validation

`GET /api/health` validates:
- Supabase connection (test query)
- SignalWire config (env vars present)
- Anthropic API key (list models call)
- Deepgram API key (token validation)
- ElevenLabs API key (voices list call)

Run health check after deploy to confirm all providers are operational.
