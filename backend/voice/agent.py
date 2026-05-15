import os
import re
import json
import base64
import asyncio
from datetime import datetime, timezone
from loguru import logger

from pipecat.frames.frames import AudioRawFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

from backend.voice.tools import SOPHIA_TOOLS, execute_tool
from backend.qa.grader import grade_call
from backend.lib.db import insert_call, update_lead_for_disposition
from backend.voice.processors.context_tracker import CallContext


VOICE_MODE = os.getenv("VOICE_MODE", "baseline")


SPANISH_MARKERS = [
    "hola", "oye", "buenos", "buenas", "sí", "si ", "no entiendo",
    "habla español", "español", "hablas", "habla", "mira", "órale",
    "sale", "qué onda", "andale", "ándale", "neta", "ahorita",
]

_MD_STRIP_PATTERN = re.compile(r"^#{1,3}\s+|[*`]|^---+$", re.MULTILINE)
_THINKING_PATTERN = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)

_INTERNAL_STARTS = (
    "the caller", "i need to", "i should", "my goal",
    "react first", "ask permission", "they seem", "i want to",
    "let me think", "i'll handle", "i'm going to",
    "note:", "step ", "phase ",
)


def _is_internal_thought(text: str) -> bool:
    if not text or not text.strip():
        return True
    lower = text.strip().lower()
    if "<thinking>" in lower or "</thinking>" in lower:
        return True
    if re.match(r"^\d+[\.\)]\s", lower):
        return True
    if lower.startswith(("- ", "* ", "• ")):
        return True
    if "\n\n" in text:
        return True
    for pattern in _INTERNAL_STARTS:
        if lower.startswith(pattern):
            return True
    return False


def _clean_llm_output(text: str) -> str:
    text = _THINKING_PATTERN.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _detect_spanish(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in SPANISH_MARKERS)


def _strip_markdown(text: str) -> str:
    text = _MD_STRIP_PATTERN.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _load_system_prompt(property_context_str: str, spanish: bool = False) -> str:
    prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")

    core_path = os.path.join(prompts_dir, "sophia_core.md")
    with open(core_path) as f:
        base_prompt = f.read().strip()

    if spanish:
        extended_path = os.path.join(prompts_dir, "sophia_extended.md")
        if os.path.exists(extended_path):
            with open(extended_path) as f:
                base_prompt = base_prompt + "\n\n" + f.read().strip()
        base_prompt += (
            "\n\nLANGUAGE MODE: SPANISH DETECTED\n\n"
            "The caller is speaking Spanish. Switch fully to Spanish now. "
            "Use Sophia's California Spanish voice. Natural, Central Valley Latina. "
            "Not textbook Spanish. Mix English words when natural. End responses with questions."
        )

    base_prompt = _strip_markdown(base_prompt)
    return f"{base_prompt}\n\nCALLER PROPERTY CONTEXT\n\n{property_context_str}"


def _get_extended_prompt_path() -> str:
    prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")
    return os.path.join(prompts_dir, "sophia_extended.md")


def _load_boss_prompt(briefing: str) -> str:
    return f"""You are Sophia Reyes, acquisitions coordinator for San Joaquin House Buyers.
You are talking to Angelo — your boss, Alanzo. This is a private check-in call.

Be casual, direct, and natural. No seller persona. No scripts.
You know the full pipeline. You give him real numbers and real talk.
You can look up any property by address if he asks.
You answer questions about specific leads, scores, ARVs, MAOs, call history.
Keep answers tight. Angelo is busy.

PIPELINE BRIEFING

{briefing}"""


def _build_tools_schema() -> ToolsSchema:
    schemas = []
    for tool in SOPHIA_TOOLS:
        props = tool["input_schema"]["properties"]
        required = tool["input_schema"].get("required", [])
        schemas.append(FunctionSchema(
            name=tool["name"],
            description=tool["description"],
            properties=props,
            required=required,
        ))
    return ToolsSchema(standard_tools=schemas)


def _make_tool_handler(tool_name: str, call_ctx=None, lf_trace=None):
    async def handler(params: FunctionCallParams) -> None:
        result = execute_tool(tool_name, dict(params.arguments), call_ctx=call_ctx, lf_trace=lf_trace)
        await params.result_callback(result)
    return handler


class _InstrumentedElevenLabsTTSService(ElevenLabsTTSService):
    """Subclass that logs every raw ElevenLabs WebSocket message at WARNING level
    before Pipecat parses it, so we can see exactly what arrives in Railway logs.
    The full parsing logic below is reproduced verbatim from pipecat source."""

    async def _receive_messages(self):
        from pipecat.frames.frames import TTSAudioRawFrame
        from pipecat.services.elevenlabs.tts import (
            _strip_leading_space,
            calculate_word_times,
        )

        async for message in self._get_websocket():
            msg = json.loads(message)

            # RAW INSTRUMENTATION — log everything at WARNING so it appears in Railway
            received_ctx_id = msg.get("contextId")
            all_keys = list(msg.keys())
            has_audio = "audio" in msg
            has_audio_b64 = "audio_base64" in msg
            has_alignment = "normalizedAlignment" in msg
            is_final_val = msg.get("isFinal")
            has_error = "error" in msg or "message" in msg
            audio_bytes = len(base64.b64decode(msg["audio"])) if has_audio else 0
            ctx_available = self.audio_context_available(received_ctx_id)
            active_ctx = self.get_active_audio_context_id()

            logger.warning(
                "EL_WS_RAW contextId={} keys={} has_audio={} audio_bytes={} "
                "has_audio_base64={} has_alignment={} isFinal={} has_error={} "
                "ctx_available={} active_ctx={}",
                received_ctx_id,
                all_keys,
                has_audio,
                audio_bytes,
                has_audio_b64,
                has_alignment,
                is_final_val,
                has_error,
                ctx_available,
                active_ctx,
            )
            if has_error:
                logger.warning(
                    "EL_WS_ERROR error={} message={}",
                    msg.get("error"),
                    msg.get("message"),
                )

            # --- Verbatim pipecat parse logic below ---
            if msg.get("isFinal") is True:
                continue

            if not self.audio_context_available(received_ctx_id):
                if self.get_active_audio_context_id() == received_ctx_id:
                    logger.warning(
                        "EL_WS_CTX_RECREATE contextId={} — delayed message, recreating",
                        received_ctx_id,
                    )
                    await self.create_audio_context(received_ctx_id)
                else:
                    logger.warning(
                        "EL_WS_CTX_DROP contextId={} active={} — unavailable context, dropping audio",
                        received_ctx_id,
                        self.get_active_audio_context_id(),
                    )
                    continue

            if msg.get("audio"):
                audio = base64.b64decode(msg["audio"])
                frame = TTSAudioRawFrame(audio, self.sample_rate, 1, context_id=received_ctx_id)
                await self.append_to_audio_context(received_ctx_id, frame)

            if msg.get("normalizedAlignment"):
                alignment = _strip_leading_space(
                    msg["normalizedAlignment"],
                    ("chars", "charStartTimesMs", "charDurationsMs"),
                )
                word_times, self._partial_word, self._partial_word_start_time = (
                    calculate_word_times(
                        alignment,
                        self._cumulative_time,
                        self._partial_word,
                        self._partial_word_start_time,
                    )
                )

                if word_times:
                    await self.add_word_timestamps(word_times, received_ctx_id)

                    char_start_times_ms = alignment.get("charStartTimesMs", [])
                    char_durations_ms = alignment.get("charDurationsMs", [])

                    if char_start_times_ms and char_durations_ms:
                        chunk_end_time_ms = char_start_times_ms[-1] + char_durations_ms[-1]
                        self._cumulative_time += chunk_end_time_ms / 1000.0
                    else:
                        self._cumulative_time = word_times[-1][1]


async def _build_tts(call_ctx_ref):
    provider = os.environ.get("TTS_PROVIDER", "openai").lower()
    logger.warning("TTS_PROVIDER={}", provider)

    if provider == "elevenlabs":
        from pipecat.services.elevenlabs.tts import output_format_from_sample_rate
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "")
        model = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")
        if not api_key:
            logger.error("ELEVENLABS_API_KEY missing — TTS will fail")
        if not voice_id:
            logger.error("ELEVENLABS_VOICE_ID missing — TTS will fail")
        resolved_format = output_format_from_sample_rate(16000)
        logger.warning(
            "ELEVENLABS_TTS_INIT voice_id={} model={} sample_rate=16000 resolved_output_format={}",
            voice_id, model, resolved_format,
        )
        tts = _InstrumentedElevenLabsTTSService(
            api_key=api_key,
            settings=ElevenLabsTTSService.Settings(
                voice=voice_id,
                model=model,
            ),
            sample_rate=16000,
        )
        logger.warning("TTS_ACTIVE provider=elevenlabs voice_id={} model={}", voice_id, model)
        return tts

    # Default: OpenAI TTS (confirmed working — caller heard audio)
    from pipecat.services.openai.tts import OpenAITTSService
    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.environ.get("OPENAI_TTS_VOICE", "alloy")
    if not api_key:
        logger.error("OPENAI_API_KEY missing — TTS will fail")
    # OpenAI TTS natively outputs 24kHz PCM. Pass sample_rate=24000 so frames
    # are correctly labeled; pipecat transport resamples to audio_out_sample_rate.
    tts = OpenAITTSService(
        api_key=api_key,
        settings=OpenAITTSService.Settings(
            model=model,
            voice=voice,
        ),
        sample_rate=24000,
    )
    logger.warning("TTS_ACTIVE provider=openai model={} voice={}", model, voice)
    return tts


async def _create_stt_service(api_key: str, spanish: bool) -> DeepgramSTTService:
    language = "es" if spanish else "en-US"
    model = "base"

    logger.info(
        "deepgram stt initializing model={} language={}",
        model, language,
    )

    try:
        stt = DeepgramSTTService(
            api_key=api_key,
            settings=DeepgramSTTService.Settings(
                model=model,
                language=language,
                punctuate=True,
                interim_results=False,
                endpointing=200,
            ),
        )
        logger.info("deepgram stt service created successfully model={}", model)
        return stt
    except Exception as e:
        logger.error(
            "deepgram stt init FAILED error={} params=model:{} language:{} punctuate:True interim_results:False endpointing:200",
            str(e), model, language,
        )
        raise


class _OutboundAudioDebugLogger(FrameProcessor):
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, AudioRawFrame):
            logger.info(
                "outbound audio frame bytes={} sample_rate={}",
                len(frame.audio),
                frame.sample_rate,
            )
        await self.push_frame(frame, direction)


class TTSFrameProbe(FrameProcessor):
    _TTS_FRAME_TYPES = frozenset([
        "TTSAudioRawFrame",
        "OutputAudioRawFrame",
        "TTSStartedFrame",
        "TTSStoppedFrame",
        "ErrorFrame",
    ])

    async def process_frame(self, frame, direction):
        frame_type = type(frame).__name__
        if frame_type in self._TTS_FRAME_TYPES:
            logger.warning("TTS_PROBE frame={} direction={}", frame_type, direction)
            if hasattr(frame, "audio"):
                logger.warning(
                    "TTS_AUDIO size={} sample_rate={}",
                    len(frame.audio),
                    getattr(frame, "sample_rate", "unknown"),
                )
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class AudioTypeProbe(FrameProcessor):
    async def process_frame(self, frame, direction):
        logger.info(
            "FRAME_PROBE type={} sample_rate={} channels={} has_audio={}",
            type(frame).__name__,
            getattr(frame, "sample_rate", None),
            getattr(frame, "num_channels", None),
            hasattr(frame, "audio"),
        )
        await self.push_frame(frame, direction)


class AudioDebugProcessor(FrameProcessor):
    async def process_frame(self, frame, direction):
        from pipecat.frames.frames import OutputAudioRawFrame, TTSAudioRawFrame
        if isinstance(frame, (AudioRawFrame, OutputAudioRawFrame, TTSAudioRawFrame)) or hasattr(frame, "audio"):
            logger.warning(
                "AUDIO_DEBUG_BEFORE_TRANSPORT frame_type={} direction={} has_audio={} size={} sample_rate={}",
                type(frame).__name__,
                direction,
                hasattr(frame, "audio"),
                len(frame.audio) if hasattr(frame, "audio") else "no_audio",
                getattr(frame, "sample_rate", None),
            )
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class _LoggingWebSocket:
    def __init__(self, ws):
        self._ws = ws
        self._send_count = 0

    async def send_text(self, data: str) -> None:
        self._send_count += 1
        try:
            parsed = json.loads(data)
            event = parsed.get("event", "unknown")
            if event == "media":
                payload_len = len(parsed.get("media", {}).get("payload", ""))
                if self._send_count <= 3:
                    logger.warning(
                        "WS_SEND_TEXT count={} event=media payload_len={}",
                        self._send_count, payload_len,
                    )
                elif self._send_count == 4:
                    logger.warning("WS_SEND_TEXT media packets continuing count>3 suppressing further logs")
            else:
                logger.warning("WS_SEND_TEXT count={} event={}", self._send_count, event)
        except Exception as parse_err:
            logger.warning("WS_SEND_TEXT count={} parse_error={} len={}", self._send_count, parse_err, len(data))
        try:
            await self._ws.send_text(data)
        except Exception as send_err:
            logger.error("WS_SEND_TEXT_FAILED count={} error={}", self._send_count, str(send_err))
            raise

    def __getattr__(self, name):
        return getattr(self._ws, name)


class _LoggingTwilioSerializer(TwilioFrameSerializer):
    _packet_count = 0

    async def serialize(self, frame):
        frame_type = type(frame).__name__
        if isinstance(frame, AudioRawFrame):
            self.__class__._packet_count += 1
            count = self.__class__._packet_count
            logger.warning(
                "SERIALIZER_ENTER frame_type={} count={} bytes={} sample_rate={}",
                frame_type,
                count,
                len(frame.audio),
                getattr(frame, "sample_rate", "unknown"),
            )

        result = await super().serialize(frame)

        if isinstance(frame, AudioRawFrame):
            if result is None:
                logger.error(
                    "SERIALIZER_NONE frame_type={} count={} bytes={} sample_rate={} — likely sample rate or encoding mismatch",
                    frame_type,
                    self.__class__._packet_count,
                    len(frame.audio),
                    getattr(frame, "sample_rate", "unknown"),
                )
            else:
                try:
                    parsed = json.loads(result)
                    event = parsed.get("event", "unknown")
                    payload_len = len(parsed.get("media", {}).get("payload", ""))
                    if self.__class__._packet_count <= 3:
                        logger.warning(
                            "SERIALIZER_OK count={} event={} streamSid={} payload_len={}",
                            self.__class__._packet_count,
                            event,
                            parsed.get("streamSid", "?"),
                            payload_len,
                        )
                except Exception as e:
                    logger.warning("SERIALIZER_JSON_PARSE_FAILED error={}", str(e))

        return result


async def run_sophia_agent(
    websocket,
    call_sid: str,
    call_context: dict,
    startup_clips: dict = None,
    metrics_store: dict = None,
) -> None:
    logger.info("sophia agent starting call_sid={}", call_sid)

    from backend.observability import trace_call_start
    lf_trace = trace_call_start(call_sid, call_context)

    stream_sid = call_sid
    stream_sid_source = "fallback_call_sid"
    try:
        for i in range(10):
            message = await asyncio.wait_for(websocket.receive(), timeout=5.0)
            if "text" in message:
                raw = message["text"]
            elif "bytes" in message:
                raw = message["bytes"].decode("utf-8")
            else:
                logger.warning("ws_unknown_frame_type keys={}", list(message.keys()))
                continue
            msg = json.loads(raw)
            event_type = msg.get("event")
            logger.debug("ws_event i={} type={}", i, event_type)
            if event_type == "start":
                start_obj = msg.get("start", {})
                top_level_sid = msg.get("streamSid")
                nested_sid = start_obj.get("streamSid")
                if top_level_sid:
                    stream_sid = top_level_sid
                    stream_sid_source = "top_level"
                elif nested_sid:
                    stream_sid = nested_sid
                    stream_sid_source = "nested_start"
                else:
                    stream_sid = call_sid
                    stream_sid_source = "fallback_call_sid"
                break
    except asyncio.TimeoutError:
        logger.warning("ws_start_event_timeout call_sid={}", call_sid)
    except Exception as e:
        logger.warning("ws_start_event_error error={}", str(e))

    logger.info(
        "stream_routing stream_sid={} call_sid={} source={}",
        stream_sid, call_sid, stream_sid_source,
    )

    spanish_detected = call_context.get("spanish_detected", False)

    lead = call_context.get("lead")
    seller_memory = None
    if lead and lead.get("id"):
        from backend.voice.memory import SellerMemory
        seller_memory = SellerMemory.load(lead["id"])

    if call_context.get("boss_mode"):
        system_prompt = _load_boss_prompt(call_context.get("briefing", "No briefing available."))
    else:
        system_prompt = _load_system_prompt(
            call_context.get("property_context_str", "No property context available."),
            spanish=spanish_detected,
        )

    if seller_memory:
        memory_ctx = seller_memory.to_prompt_context()
        if memory_ctx:
            system_prompt = system_prompt + "\n\n" + memory_ctx

    from backend.voice.prompt_budget import apply_budget
    system_prompt = apply_budget(system_prompt)

    logger.info("transport init stream_sid={} call_sid={}", stream_sid, call_sid)

    logging_ws = _LoggingWebSocket(websocket)
    logger.warning("WS_PROXY installed call_sid={}", call_sid)

    transport = FastAPIWebsocketTransport(
        websocket=logging_ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_enabled=True,
            audio_out_sample_rate=16000,
            add_wav_header=False,
            serializer=_LoggingTwilioSerializer(
                stream_sid=stream_sid,
                params=TwilioFrameSerializer.InputParams(
                    auto_hang_up=False,
                ),
            ),
        ),
    )

    stt = await _create_stt_service(os.environ["DEEPGRAM_API_KEY"], spanish_detected)

    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        logger.warning(
            "GROQ_API_KEY is set: tool calls silently fail with Groq llama models. "
            "Sophia will speak but cannot set_disposition, schedule_followup, or use other tools. "
            "Unset GROQ_API_KEY and set ANTHROPIC_API_KEY for full tool support."
        )
        from pipecat.services.openai.llm import OpenAILLMService
        llm = OpenAILLMService(
            api_key=groq_key,
            base_url="https://api.groq.com/openai/v1",
            model="llama-3.3-70b-versatile",
            max_tokens=80,
        )
        logger.info("voice llm using groq model=llama-3.3-70b-versatile")
    else:
        voice_model = os.environ.get("VOICE_LLM_MODEL", "claude-haiku-4-5-20251001")
        llm = AnthropicLLMService(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            settings=AnthropicLLMService.Settings(
                model=voice_model,
                enable_prompt_caching=True,
                max_tokens=80,
            ),
        )
        logger.info("voice llm model={}", voice_model)

    call_ctx = CallContext()

    # Register runtime metrics for live operator overlay (G23)
    if metrics_store is not None:
        metrics_store[call_sid] = call_ctx

    for tool in SOPHIA_TOOLS:
        llm.register_function(tool["name"], _make_tool_handler(tool["name"], call_ctx, lf_trace))

    tts = await _build_tts(call_ctx)

    transport_output = transport.output()

    tts_frame_probe = TTSFrameProbe()

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": "[call started]",
        },
    ]

    context = LLMContext(messages=messages, tools=_build_tools_schema())

    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    confidence=0.7,
                    start_secs=0.2,
                    stop_secs=0.5,
                    min_volume=0.6,
                ),
            ),
        ),
    )

    # MINIMAL pipeline — all custom processors disabled for audio isolation test
    # Re-enable one-by-one after base audio confirmed working
    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        tts,
        tts_frame_probe,
        transport_output,
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_connected(transport, client):
        logger.info("client connected call_sid={}", call_sid)
        await task.queue_frames([context_aggregator.user()._get_context_frame()])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(transport, client):
        logger.info("client disconnected call_sid={}", call_sid)
        await task.cancel()

    runner = PipelineRunner()

    try:
        await runner.run(task)
    except Exception as e:
        logger.error("sophia agent error call_sid={} error={}", call_sid, str(e))
    finally:
        await _handle_call_end(call_sid, call_context, context, call_ctx, seller_memory, lf_trace)


async def _handle_call_end(
    call_sid: str,
    call_context: dict,
    context: LLMContext,
    call_ctx=None,
    seller_memory=None,
    lf_trace=None,
) -> None:
    logger.info("handling call end call_sid={}", call_sid)

    try:
        transcript = _build_transcript(context.messages)
        disposition = call_ctx.disposition if call_ctx else None

        if seller_memory and transcript:
            try:
                seller_memory.add_call_summary(f"Call {call_sid[:8]}: {transcript[:200]}")
                seller_memory.save()
            except Exception as mem_err:
                logger.error("seller_memory save failed error={}", str(mem_err))

        lead = call_context.get("lead")
        if lead:
            call_data = {
                "lead_id": lead["id"],
                "property_id": lead.get("property_id"),
                "signalwire_call_id": call_sid,
                "direction": "inbound",
                "transcript": transcript,
                "call_disposition": disposition,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            call_id_db = insert_call(call_data)

            if call_id_db:
                chunks = _build_transcript_chunks(context.messages)
                if chunks:
                    from backend.lib.db import insert_transcript_chunks
                    insert_transcript_chunks(call_id_db, lead["id"], chunks)
                from backend.voice.events import emit_event, TRANSCRIPT_COMPLETED
                emit_event(TRANSCRIPT_COMPLETED, call_id_db, lead["id"], {"chunk_count": len(chunks)})

            if disposition:
                update_lead_for_disposition(lead["id"], disposition)

            asyncio.create_task(
                _run_qa_async(transcript, lead["id"], call_sid)
            )
            asyncio.create_task(
                _run_transcript_intel_async(transcript, lead["id"], call_sid, call_id_db, disposition)
            )

        from backend.observability import trace_call_end
        turn_count = call_ctx.turn_count if call_ctx else 0
        trace_call_end(lf_trace, call_sid, disposition, len(transcript), turn_count)

    except Exception as e:
        logger.error("handle_call_end error call_sid={} error={}", call_sid, str(e))


async def _run_qa_async(transcript: str, lead_id: str, call_sid: str) -> None:
    try:
        await asyncio.to_thread(grade_call, transcript, lead_id, call_sid)
        logger.info("QA grading complete call_sid={}", call_sid)
    except Exception as e:
        logger.error("QA grading failed call_sid={} error={}", call_sid, str(e))


async def _run_transcript_intel_async(
    transcript: str,
    lead_id: str,
    call_sid: str,
    call_id_db: str | None = None,
    disposition: str | None = None,
) -> None:
    try:
        from backend.qa.transcript_intel import analyze_transcript
        intel = await asyncio.to_thread(analyze_transcript, transcript, lead_id, call_sid, call_id_db)
        if intel and call_id_db and lead_id:
            from backend.workflows.engine import trigger_from_call_outcome
            await asyncio.to_thread(trigger_from_call_outcome, call_id_db, lead_id, disposition, intel)
        logger.info("transcript_intel complete call_sid={}", call_sid)
    except Exception as e:
        logger.error("transcript_intel failed call_sid={} error={}", call_sid, str(e))


def _build_transcript(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str) and role in ("user", "assistant"):
            if content == "[call started]":
                continue
            speaker = "SELLER" if role == "user" else "SOPHIA"
            lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def _build_transcript_chunks(messages: list[dict]) -> list[dict]:
    chunks = []
    seq = 0
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not isinstance(content, str) or role not in ("user", "assistant"):
            continue
        if content == "[call started]":
            continue
        speaker = "SELLER" if role == "user" else "SOPHIA"
        chunks.append({
            "speaker": speaker,
            "text": content,
            "chunk_type": "final",
            "sequence_order": seq,
            "confidence": None,
        })
        seq += 1
    return chunks
