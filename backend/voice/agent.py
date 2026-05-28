from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    AudioRawFrame,
    BotStoppedSpeakingFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from backend.lib.db import insert_call, update_lead_for_disposition
from backend.qa.grader import grade_call
from backend.voice.deal_heat_scorer import DealHeatScorer
from backend.voice.emotional_state_engine import EmotionalStateEngine
from backend.voice.fatigue_detector import FatigueDetector
from backend.voice.microstate_engine import MicrostateEngine
from backend.voice.momentum_tracker import MomentumTracker
from backend.voice.objective_engine import ObjectiveEngine
from backend.voice.processors.analysis_callbacks import AnalysisCallbackProcessor
from backend.voice.processors.backchannel import BackchannelProcessor
from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor
from backend.voice.processors.interruption import InterruptionAckProcessor
from backend.voice.processors.stt_mute import BotSpeakingSTTMuteProcessor
from backend.voice.resistance_tracker import ResistanceTracker
from backend.voice.runtime_orchestrator import RuntimeOrchestrator
from backend.voice.seller_profile_engine import SellerProfileEngine
from backend.voice.silence_handler import SilenceHandler
from backend.voice.speech_chunker import SpeechChunker
from backend.voice.tools import SOPHIA_TOOLS, execute_tool
from backend.voice.trust_tracker import TrustTracker
from backend.voice.turn_controller import TurnController

_MD_STRIP_PATTERN = re.compile(r"^#{1,3}\s+|[*`]|^---+$", re.MULTILINE)

_DEFAULT_LLM_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_DEEPGRAM_MODEL = "nova-3"
_DEFAULT_CARTESIA_MODEL = "sonic-3"

_MAX_QA_TIMEOUT = 30.0
_MAX_TRANSCRIPT_INTEL_TIMEOUT = 60.0
_MAX_WORKFLOW_TIMEOUT = 15.0
_STREAM_SID_TIMEOUT = 2.0
_STREAM_SID_MAX_READS = 5

if os.environ.get("GROQ_API_KEY", "").strip():
    import sys
    print(
        "CRITICAL: GROQ_API_KEY is set. Tools (book_appointment, set_disposition, "
        "end_call, transfer_call) will NOT work on the Groq LLM path. "
        "Unset GROQ_API_KEY to restore full functionality.",
        file=sys.stderr,
    )

_SITUATION_OPENERS = {
    "inherited_property": "I'm sorry for your loss first of all.",
    "probate": "I'm sorry for your loss first of all.",
    "preforeclosure": "I know this might be a tough time.",
    "tired_landlord": "Hey — you still own that rental?",
    "divorce": "I know things might be a bit complicated right now.",
}


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} missing")
    return value


def _strip_markdown(text: str) -> str:
    text = _MD_STRIP_PATTERN.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_opener(call_context: dict[str, Any]) -> str:
    is_outbound = bool(call_context.get("is_outbound"))
    name = (call_context.get("owner_first_name") or "").strip()
    address = (call_context.get("address") or "").strip()
    situation = (call_context.get("situation_label") or "").strip()
    situation_opener = _SITUATION_OPENERS.get(situation, "")

    if not is_outbound:
        base = "San Joaquin House Buyers — hey, this is Sophia. Just so you know, this call may be recorded."
        if situation_opener:
            return f"{base} {situation_opener}"
        return base

    if name and address:
        base = (
            f"Hey — is this {name}? "
            "Hey, it's Sophia. "
            "I know this is kinda random. "
            f"I was looking at your place on {address}. "
            "You got like two minutes?"
        )
    elif address:
        base = (
            "Hey, it's Sophia. "
            "I know this is kinda random. "
            f"I was looking at the place on {address}. "
            "You got like two minutes?"
        )
    else:
        base = (
            "Hey, it's Sophia with San Joaquin House Buyers. "
            "I know this is kinda random. "
            "You got like two minutes?"
        )

    if situation_opener:
        return f"{situation_opener} {base}"
    return base


def _load_prompt_file(prompts_dir: str, filename: str) -> str:
    path = os.path.join(prompts_dir, filename)
    if not os.path.exists(path):
        logger.warning("prompt file missing path={}", path)
        return ""
    with open(path, encoding="utf-8") as file:
        return file.read().strip()


def _load_system_prompt(call_context: dict[str, Any], spanish: bool = False) -> str:
    from backend.voice.prompt_budget import apply_budget
    prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")

    prompt_parts = [_load_prompt_file(prompts_dir, "sophia_core.md")]

    if spanish:
        prompt_parts.append(_load_prompt_file(prompts_dir, "sophia_extended.md"))
        prompt_parts.append(
            "LANGUAGE MODE: SPANISH DETECTED\n\n"
            "The caller is speaking Spanish. "
            "Switch fully to Spanish now. "
            "Use Sophia's natural Central Valley California Spanish. "
            "Do not sound like textbook Spanish. "
            "Code-switch only when natural. "
            "Keep responses short and conversational."
        )

    base_prompt = "\n\n".join(part for part in prompt_parts if part)
    opener = _build_opener(call_context)
    property_context_str = call_context.get("property_context_str", "Caller: unknown. Address: unknown. Call type: inbound.")

    full_prompt = (
        f"{base_prompt}\n\n"
        f"CALLER PROPERTY CONTEXT\n\n"
        f"{property_context_str}\n\n"
        f"OPENER\n\n"
        f"{opener}"
    )

    full_prompt = apply_budget(full_prompt)
    full_prompt = _strip_markdown(full_prompt)
    return full_prompt


def _load_boss_prompt(briefing: str) -> str:
    return f"""You are Sophia Reyes, acquisitions coordinator for San Joaquin House Buyers.

You are talking to Angelo, your boss.
This is a private owner check-in call.

Be casual, direct, and natural.
No seller persona.
No scripts.

You know the pipeline.
You give real numbers and real talk.

You can answer questions about:
- specific leads
- scores
- ARVs
- MAOs
- call history
- follow-up status

Keep answers tight.
Angelo is busy.

PIPELINE BRIEFING

{briefing}""".strip()


def _build_tools_schema() -> ToolsSchema:
    schemas: list[FunctionSchema] = []
    for tool in SOPHIA_TOOLS:
        input_schema = tool.get("input_schema", {})
        schemas.append(
            FunctionSchema(
                name=tool["name"],
                description=tool["description"],
                properties=input_schema.get("properties", {}),
                required=input_schema.get("required", []),
            )
        )
    return ToolsSchema(standard_tools=schemas)


def _make_tool_handler(tool_name: str, call_ctx: CallContext | None = None, lf_trace=None):
    async def handler(params: FunctionCallParams) -> None:
        try:
            result = await asyncio.to_thread(
                execute_tool,
                tool_name,
                dict(params.arguments),
                call_ctx,
                lf_trace,
            )
        except Exception as error:
            logger.exception("tool execution failed tool={} error={}", tool_name, str(error))
            result = {"success": False, "error": str(error)}
        await params.result_callback(result)
    return handler


async def _build_tts(call_ctx_ref: CallContext) -> CartesiaTTSService:
    api_key = _require_env("CARTESIA_API_KEY")
    voice_id = _require_env("CARTESIA_VOICE_ID")
    model = os.environ.get("CARTESIA_MODEL", _DEFAULT_CARTESIA_MODEL)

    logger.info("tts active provider=cartesia model={} voice_id={} sample_rate=8000", model, voice_id)

    return CartesiaTTSService(
        api_key=api_key,
        sample_rate=8000,
        settings=CartesiaTTSService.Settings(
            voice=voice_id,
            model=model,
            generation_config=GenerationConfig(
                speed=1.05,
                volume=1.1,
            ),
        ),
    )


async def _create_stt_service(api_key: str, spanish: bool) -> DeepgramSTTService:
    language = "es" if spanish else "en-US"
    model = os.environ.get("DEEPGRAM_MODEL", _DEFAULT_DEEPGRAM_MODEL)

    logger.info("deepgram stt initializing model={} language={}", model, language)

    return DeepgramSTTService(
        api_key=api_key,
        sample_rate=16000,
        ttfs_p99_latency=0.8,
        settings=DeepgramSTTService.Settings(
            model=model,
            language=language,
            punctuate=True,
            interim_results=True,
            endpointing=300,
            numerals=True,
            smart_format=True,
        ),
    )


class TTSFrameProbe(FrameProcessor):
    _LIFECYCLE_TYPES = frozenset(["TTSStartedFrame", "TTSStoppedFrame", "ErrorFrame"])
    _AUDIO_TYPES = frozenset(["TTSAudioRawFrame", "OutputAudioRawFrame"])

    def __init__(self):
        super().__init__()
        self._audio_logged = 0

    async def process_frame(self, frame, direction: FrameDirection):
        frame_type = type(frame).__name__

        if frame_type in self._LIFECYCLE_TYPES:
            logger.debug("tts_probe frame={} direction={}", frame_type, direction)
        elif frame_type in self._AUDIO_TYPES and self._audio_logged < 3:
            self._audio_logged += 1
            logger.debug(
                "tts_probe audio frame={} size={} sample_rate={} count={}",
                frame_type,
                len(frame.audio) if hasattr(frame, "audio") else 0,
                getattr(frame, "sample_rate", "unknown"),
                self._audio_logged,
            )

        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class BotSpeakingMonitor(FrameProcessor):
    def __init__(self, silence_handler: SilenceHandler):
        super().__init__()
        self._sh = silence_handler

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStoppedSpeakingFrame):
            self._sh.start_timer()
            logger.debug("bot_speaking_monitor bot_stopped_speaking")
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._sh.cancel_timer()
            self._sh.reset_consecutive()
            logger.debug("bot_speaking_monitor user_started_speaking")
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
                    logger.debug(
                        "ws_send_text count={} event=media payload_len={}",
                        self._send_count,
                        payload_len,
                    )
            else:
                logger.debug("ws_send_text count={} event={}", self._send_count, event)
        except Exception:
            logger.debug("ws_send_text non_json len={}", len(data))
        await self._ws.send_text(data)

    def __getattr__(self, name):
        return getattr(self._ws, name)


class _LoggingTwilioSerializer(TwilioFrameSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._packet_count = 0

    async def serialize(self, frame):
        if isinstance(frame, AudioRawFrame):
            self._packet_count += 1
            if self._packet_count <= 3:
                logger.debug(
                    "serializer_enter count={} bytes={} sample_rate={}",
                    self._packet_count,
                    len(frame.audio),
                    getattr(frame, "sample_rate", "unknown"),
                )

        result = await super().serialize(frame)

        if isinstance(frame, AudioRawFrame) and result is None:
            logger.error(
                "serializer_none count={} sample_rate={}",
                self._packet_count,
                getattr(frame, "sample_rate", "unknown"),
            )

        return result


async def run_sophia_agent(
    websocket,
    call_sid: str,
    call_context: dict[str, Any],
    startup_clips: dict | None = None,
    metrics_store: dict | None = None,
) -> None:
    del startup_clips

    logger.info("sophia agent starting call_sid={}", call_sid)

    from backend.observability import trace_call_start
    lf_trace = trace_call_start(call_sid, call_context)

    stream_sid = await _read_stream_sid(websocket=websocket, call_sid=call_sid)

    spanish_detected = bool(call_context.get("spanish_detected"))
    lead = call_context.get("lead")
    seller_memory = None

    if lead and lead.get("id"):
        from backend.voice.memory import SellerMemory
        seller_memory = SellerMemory.load(lead["id"])

    if call_context.get("boss_mode"):
        system_prompt = _load_boss_prompt(call_context.get("briefing", "No briefing available."))
    else:
        system_prompt = _load_system_prompt(call_context, spanish=spanish_detected)

    if seller_memory:
        memory_ctx = seller_memory.to_prompt_context()
        if memory_ctx:
            system_prompt += "\n\n" + memory_ctx

    from backend.voice.prompt_budget import apply_budget
    system_prompt = apply_budget(system_prompt)

    logging_ws = _LoggingWebSocket(websocket)

    transport = FastAPIWebsocketTransport(
        websocket=logging_ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_enabled=True,
            audio_out_sample_rate=8000,
            add_wav_header=False,
            serializer=_LoggingTwilioSerializer(
                stream_sid=stream_sid,
                params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
            ),
        ),
    )

    stt = await _create_stt_service(_require_env("DEEPGRAM_API_KEY"), spanish_detected)

    voice_model = os.environ.get("VOICE_LLM_MODEL", _DEFAULT_LLM_MODEL)

    llm = AnthropicLLMService(
        api_key=_require_env("ANTHROPIC_API_KEY"),
        settings=AnthropicLLMService.Settings(
            model=voice_model,
            enable_prompt_caching=True,
            max_tokens=300,
            temperature=0.3,
        ),
    )

    logger.info("voice llm model={}", voice_model)

    call_ctx = CallContext()
    if call_context.get("address"):
        call_ctx.address_known = True
    if call_context.get("situation_label"):
        call_ctx.situation_label = call_context["situation_label"]
    if call_context.get("initial_trust_score"):
        call_ctx.trust_score = float(call_context["initial_trust_score"])

    if metrics_store is not None:
        metrics_store[call_sid] = call_ctx

    boss_mode = bool(call_context.get("boss_mode", False))

    if not boss_mode:
        for tool in SOPHIA_TOOLS:
            llm.register_function(
                tool["name"],
                _make_tool_handler(tool["name"], call_ctx, lf_trace),
            )

    tts = await _build_tts(call_ctx)

    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    ]

    context = LLMContext(
        messages=messages,
        tools=_build_tools_schema() if not boss_mode else None,
    )

    stt_mute = BotSpeakingSTTMuteProcessor()
    backchannel_processor = BackchannelProcessor(call_ctx=call_ctx)
    interruption_ack = InterruptionAckProcessor()
    emotional_engine = EmotionalStateEngine(call_ctx)
    trust_tracker = TrustTracker(call_ctx)
    resistance_tracker = ResistanceTracker(call_ctx)
    momentum_tracker = MomentumTracker(call_ctx)
    fatigue_detector = FatigueDetector(call_ctx)
    deal_heat_scorer = DealHeatScorer(call_ctx)
    seller_profile_engine = SellerProfileEngine(call_ctx)
    microstate_engine = MicrostateEngine(call_ctx)
    objective_engine = ObjectiveEngine()
    runtime_orchestrator = RuntimeOrchestrator()
    context_tracker = ContextTrackerProcessor(call_ctx=call_ctx, llm_context=context)
    context_tracker.set_objective_engine(objective_engine)
    analysis_callbacks = AnalysisCallbackProcessor(
        call_ctx=call_ctx,
        emotional_engine=emotional_engine,
        trust_tracker=trust_tracker,
        resistance_tracker=resistance_tracker,
        momentum_tracker=momentum_tracker,
        fatigue_detector=fatigue_detector,
        deal_heat_scorer=deal_heat_scorer,
        seller_profile_engine=seller_profile_engine,
        microstate_engine=microstate_engine,
        runtime_orchestrator=runtime_orchestrator,
    )
    turn_controller = TurnController(call_ctx)
    speech_chunker = SpeechChunker(call_ctx)

    silence_handler = SilenceHandler(call_ctx, task=None)
    bot_speaking_monitor = BotSpeakingMonitor(silence_handler)

    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(
                sample_rate=16000,
                params=VADParams(
                    confidence=0.7,
                    start_secs=0.2,
                    stop_secs=0.3,
                    min_volume=0.6,
                ),
            ),
            user_turn_stop_timeout=0.4,
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt_mute,
            stt,
            backchannel_processor,
            interruption_ack,
            emotional_engine,
            trust_tracker,
            resistance_tracker,
            momentum_tracker,
            fatigue_detector,
            deal_heat_scorer,
            seller_profile_engine,
            microstate_engine,
            context_tracker,
            analysis_callbacks,
            context_aggregator.user(),
            turn_controller,
            llm,
            speech_chunker,
            tts,
            TTSFrameProbe(),
            transport.output(),
            bot_speaking_monitor,
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            aggregation_timeout=0.3,
        ),
    )

    silence_handler._task = task

    @transport.event_handler("on_client_connected")
    async def on_connected(transport, client):
        del transport, client
        logger.info("client connected call_sid={}", call_sid)
        from backend.karpathys import emitter
        asyncio.create_task(emitter.emit_call_created(call_sid, call_context))
        await asyncio.sleep(0.35)
        await task.queue_frames([TTSSpeakFrame(_build_opener(call_context))])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(transport, client):
        del transport, client
        logger.info("client disconnected call_sid={}", call_sid)
        from backend.karpathys import emitter
        asyncio.create_task(emitter.emit_call_ended(call_sid))
        await task.cancel()

    runner = PipelineRunner()

    try:
        await runner.run(task)
    except asyncio.CancelledError:
        logger.warning("sophia agent cancelled call_sid={}", call_sid)
        raise
    except Exception as error:
        logger.exception("sophia agent error call_sid={} error={}", call_sid, str(error))
    finally:
        await _handle_call_end(
            call_sid=call_sid,
            call_context=call_context,
            context=context,
            call_ctx=call_ctx,
            seller_memory=seller_memory,
            lf_trace=lf_trace,
        )


async def _read_stream_sid(websocket, call_sid: str) -> str:
    stream_sid = call_sid
    stream_sid_source = "fallback_call_sid"

    try:
        for index in range(_STREAM_SID_MAX_READS):
            message = await asyncio.wait_for(
                websocket.receive(), timeout=_STREAM_SID_TIMEOUT
            )

            if "text" in message:
                raw = message["text"]
            elif "bytes" in message:
                raw = message["bytes"].decode("utf-8")
            else:
                logger.debug("ws_unknown_frame_type keys={}", list(message.keys()))
                continue

            payload = json.loads(raw)
            event_type = payload.get("event")
            logger.debug("ws_event index={} type={}", index, event_type)

            if event_type != "start":
                continue

            start_obj = payload.get("start", {})
            top_level_sid = payload.get("streamSid")
            nested_sid = start_obj.get("streamSid")

            if top_level_sid:
                stream_sid = top_level_sid
                stream_sid_source = "top_level"
            elif nested_sid:
                stream_sid = nested_sid
                stream_sid_source = "nested_start"

            break

    except asyncio.TimeoutError:
        logger.warning("ws_start_event_timeout call_sid={}", call_sid)
    except Exception as error:
        logger.exception("ws_start_event_error error={}", str(error))

    logger.info(
        "stream_routing stream_sid={} call_sid={} source={}",
        stream_sid,
        call_sid,
        stream_sid_source,
    )

    return stream_sid


async def _handle_call_end(
    call_sid: str,
    call_context: dict[str, Any],
    context: LLMContext,
    call_ctx: CallContext | None = None,
    seller_memory=None,
    lf_trace=None,
) -> None:
    logger.info("handling call end call_sid={}", call_sid)

    try:
        transcript = _build_transcript(context.messages)
        disposition = call_ctx.disposition if call_ctx else None

        if seller_memory and transcript:
            try:
                summary_label = (
                    f"Call {call_sid[:8]}: "
                    f"disposition={disposition or 'unknown'} "
                    f"turns={getattr(call_ctx, 'turn_count', 0)}"
                )
                seller_memory.add_call_summary(summary_label)
                await asyncio.to_thread(seller_memory.save)
            except Exception as error:
                logger.exception("seller_memory save failed error={}", str(error))

        lead = call_context.get("lead")
        call_id_db = None

        if lead:
            call_id_db = await _persist_call_result(
                call_sid=call_sid,
                lead=lead,
                transcript=transcript,
                disposition=disposition,
            )

            asyncio.create_task(_run_qa_async(transcript, lead["id"], call_sid))
            asyncio.create_task(
                _run_transcript_intel_async(
                    transcript=transcript,
                    lead_id=lead["id"],
                    call_sid=call_sid,
                    call_id_db=call_id_db,
                    disposition=disposition,
                )
            )

        from backend.observability import trace_call_end
        trace_call_end(
            lf_trace,
            call_sid,
            disposition,
            len(transcript),
            call_ctx.turn_count if call_ctx else 0,
        )

        from backend.karpathys import emitter
        await emitter.emit_call_completed(
            call_sid=call_sid,
            disposition=disposition,
            turn_count=call_ctx.turn_count if call_ctx else 0,
            transcript_length=len(transcript),
        )

    except Exception as error:
        logger.exception("handle_call_end error call_sid={} error={}", call_sid, str(error))


async def _handle_orchestrator_decision(
    call_ctx: CallContext,
    orchestrator: RuntimeOrchestrator,
    task: PipelineTask,
) -> None:
    decision = orchestrator.decide(call_ctx)

    if decision.objective_override:
        call_ctx.objective = decision.objective_override

    if decision.inject_instruction:
        call_ctx.runtime_instruction = decision.inject_instruction

    if decision.response_length_cap:
        call_ctx.orchestrator_length_cap = decision.response_length_cap

    if decision.end_call:
        logger.info("orchestrator end_call reason={}", decision.end_reason)
        call_ctx.call_should_end = True
        try:
            await task.queue_frames([TTSSpeakFrame("Okay. Thanks for picking up. Talk soon.")])
        except Exception:
            pass


async def _persist_call_result(
    call_sid: str,
    lead: dict[str, Any],
    transcript: str,
    disposition: str | None,
) -> str | None:
    direction = "outbound" if lead.get("is_outbound") else "inbound"

    call_data = {
        "lead_id": lead["id"],
        "property_id": lead.get("property_id"),
        "signalwire_call_id": call_sid,
        "direction": direction,
        "transcript": transcript,
        "call_disposition": disposition,
        "created_at": datetime.now(UTC).isoformat(),
    }

    call_id_db = await asyncio.to_thread(insert_call, call_data)
    if not call_id_db:
        return None

    chunks = _build_transcript_chunks_from_text(transcript)

    if chunks:
        from backend.lib.db import insert_transcript_chunks
        await asyncio.to_thread(insert_transcript_chunks, call_id_db, lead["id"], chunks)

        from backend.voice.events import TRANSCRIPT_COMPLETED, emit_event
        emit_event(TRANSCRIPT_COMPLETED, call_id_db, lead["id"], {"chunk_count": len(chunks)})

        from backend.karpathys import emitter
        await emitter.emit_transcript_completed(
            call_sid=call_sid,
            call_id_db=call_id_db,
            lead_id=lead["id"],
            chunk_count=len(chunks),
        )

    if disposition:
        await asyncio.to_thread(update_lead_for_disposition, lead["id"], disposition)

    return call_id_db


async def _run_qa_async(transcript: str, lead_id: str, call_sid: str) -> None:
    try:
        await asyncio.wait_for(
            asyncio.to_thread(grade_call, transcript, lead_id, call_sid),
            timeout=_MAX_QA_TIMEOUT,
        )
        logger.info("qa grading complete call_sid={}", call_sid)
    except asyncio.TimeoutError:
        logger.error("qa grading timeout call_sid={}", call_sid)
    except Exception as error:
        logger.exception("qa grading failed call_sid={} error={}", call_sid, str(error))


async def _run_transcript_intel_async(
    transcript: str,
    lead_id: str,
    call_sid: str,
    call_id_db: str | None = None,
    disposition: str | None = None,
) -> None:
    try:
        from backend.qa.transcript_intel import analyze_transcript

        intel = await asyncio.wait_for(
            asyncio.to_thread(analyze_transcript, transcript, lead_id, call_sid, call_id_db),
            timeout=_MAX_TRANSCRIPT_INTEL_TIMEOUT,
        )

        if intel and call_id_db and lead_id:
            from backend.workflows.engine import trigger_from_call_outcome
            await asyncio.wait_for(
                asyncio.to_thread(
                    trigger_from_call_outcome, call_id_db, lead_id, disposition, intel
                ),
                timeout=_MAX_WORKFLOW_TIMEOUT,
            )

        logger.info("transcript_intel complete call_sid={}", call_sid)
    except asyncio.TimeoutError:
        logger.error("transcript_intel timeout call_sid={}", call_sid)
    except Exception as error:
        logger.exception("transcript_intel failed call_sid={} error={}", call_sid, str(error))


def _build_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = message.get("role", "")
        content = message.get("content", "")
        if (
            not isinstance(content, str)
            or role not in ("user", "assistant")
            or content == "[call started]"
        ):
            continue
        speaker = "SELLER" if role == "user" else "SOPHIA"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def _build_transcript_chunks(
    transcript_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    sequence_order = 0
    for message in transcript_messages:
        role = message.get("role", "")
        content = message.get("content", "")
        if (
            not isinstance(content, str)
            or role not in ("user", "assistant")
            or content == "[call started]"
        ):
            continue
        speaker = "SELLER" if role == "user" else "SOPHIA"
        chunks.append({
            "speaker": speaker,
            "text": content,
            "chunk_type": "final",
            "sequence_order": sequence_order,
            "confidence": None,
        })
        sequence_order += 1
    return chunks


def _build_transcript_chunks_from_text(transcript: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for sequence_order, line in enumerate(transcript.splitlines()):
        if not line.strip():
            continue
        if line.startswith("SELLER:"):
            speaker = "SELLER"
            text = line.removeprefix("SELLER:").strip()
        elif line.startswith("SOPHIA:"):
            speaker = "SOPHIA"
            text = line.removeprefix("SOPHIA:").strip()
        else:
            continue
        chunks.append({
            "speaker": speaker,
            "text": text,
            "chunk_type": "final",
            "sequence_order": sequence_order,
            "confidence": None,
        })
    return chunks
