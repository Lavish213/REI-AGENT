# Pipeline Order

## Canonical Processor Order

```
transport.input()           ← SignalWire mulaw 8kHz PCM in, resampled to 16kHz
stt                         ← Deepgram nova-2, emits TranscriptionFrame
stt_mute_proc               ← BotSpeakingSTTMuteProcessor: sends STTMuteFrame UPSTREAM during bot speech
interruption_proc           ← InterruptionAckProcessor: InterruptionFrame → TTSSpeakFrame ack ("Oh— yeah?")
emotion_proc                ← EmotionDetectorProcessor: TranscriptionFrame → calls on_emotion callback
ai_identity_proc            ← AIIdentityProcessor: "are you a bot?" → forces TTSTextFrame disclosure (once)
context_tracker             ← ContextTrackerProcessor: extracts signals, injects context prefix into sys msg, triggers compress on turn 6
backchannel_proc            ← BackchannelProcessor: monitors user speech, injects "Mhm"/"Yeah" clips after 4s
context_aggregator.user()   ← LLMContextAggregatorPair: accumulates TranscriptionFrames, emits LLMContextFrame on VAD stop
llm                         ← AnthropicLLMService (haiku) or OpenAILLMService (Groq fallback): emits LLMTextFrame stream
sentence_streamer           ← SentenceStreamProcessor: buffers LLMTextFrame → flushes on sentence/comma boundaries → TTSTextFrame
fair_housing_filter         ← FairHousingFilter: replaces demographic/steering language in LLMTextFrame/TextFrame
tts                         ← ElevenLabsTTSService (canonical) or OrpheusTTSService (Together AI fallback): TTSTextFrame → TTSAudioRawFrame
latency_proc_tts            ← LatencyTrackerProcessor: measures UserStopped→STT→TTS_start→TTS_audio timing
transport_output            ← Sends TwilioFrameSerializer-encoded mulaw back to SignalWire WebSocket
context_aggregator.asst()   ← Accumulates assistant responses back into LLMContext
```

## Frame Flow Notes

- `STTMuteFrame(mute=True)` travels **UPSTREAM** from `stt_mute_proc` to `stt`
- `InterruptionFrame` from transport/VAD travels downstream through all processors
- `TTSSpeakFrame` from `interruption_proc` bypasses sentence_streamer, goes direct to TTS
- `TTSTextFrame` from `ai_identity_proc` flows downstream past LLM to TTS
- `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame` flow downstream from TTS, trigger `stt_mute_proc`

## VAD Configuration

```python
SileroVADAnalyzer(
    confidence=0.7,
    start_secs=0.2,
    stop_secs=0.2,
    min_volume=0.6,
)
```

## Processors NOT in Pipeline (Supporting)

- `BreathInjectorProcessor` — built but not active (would add PCM breath before TTS response)
- `FillerProcessor` — built but not active
- `PhoneEQProcessor` — built but not active (EQ + compressor for phone audio texture)
- `RoomToneProcessor` — built but not active

## LLM Context Seed

```python
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user",   "content": "[call started]"},
]
```

Anthropic API requires at least one user turn before first assistant response. `[call started]` serves as the trigger for Sophia's opening greeting.

## Audio Sample Rates

| Direction | Rate | Format |
|---|---|---|
| SignalWire → Pipecat | 8kHz mulaw → resampled 16kHz PCM | audio_in_sample_rate=16000 |
| Deepgram STT | 16kHz PCM | nova-2, en-US or es |
| ElevenLabs TTS | 16kHz PCM | eleven_turbo_v2_5, pcm_16000 |
| Pipecat → SignalWire | 16kHz PCM → mulaw | TwilioFrameSerializer |
