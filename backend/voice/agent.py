import os
import re
import json
import asyncio
from datetime import datetime, timezone
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.frames.frames import TranscriptionFrame
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
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
from pipecat.processors.frame_processor import FrameDirection

from backend.voice.tools import SOPHIA_TOOLS, execute_tool
from backend.qa.grader import grade_call
from backend.lib.db import insert_call, update_lead_stage, update_lead_for_disposition
from backend.voice.orpheus_tts import OrpheusTTSService
from backend.voice.processors.backchannel import BackchannelProcessor, pregenerate_backchannel_clips
from backend.voice.processors.filler import FillerGapProcessor, pregenerate_filler_clips
from backend.voice.processors.interruption import InterruptionAckProcessor
from backend.voice.processors.emotion import EmotionDetectorProcessor
from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor
from backend.voice.processors.room_tone import RoomToneProcessor
from backend.voice.processors.phone_eq import PhoneEQProcessor
from backend.voice.processors.breath_injector import BreathInjectorProcessor
from backend.voice.processors.response_cache import ResponseCacheProcessor, pregenerate_response_cache
from backend.voice.processors.latency_tracker import LatencyTracker, LatencyTrackerProcessor
from backend.voice.processors.sentence_streamer import SentenceStreamProcessor
from backend.voice.processors.fair_housing import FairHousingFilter
from backend.voice.processors.ai_identity import AIIdentityProcessor


SPANISH_MARKERS = [
    "hola", "oye", "buenos", "buenas", "sí", "si ", "no entiendo",
    "habla español", "español", "hablas", "habla", "mira", "órale",
    "sale", "qué onda", "andale", "ándale", "neta", "ahorita",
]

_MD_STRIP_PATTERN = re.compile(r"^#{1,3}\s+|[*`]|^---+$", re.MULTILINE)


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


def _make_tool_handler(tool_name: str, call_ctx=None):
    async def handler(params: FunctionCallParams) -> None:
        result = execute_tool(tool_name, dict(params.arguments), call_ctx=call_ctx)
        await params.result_callback(result)
    return handler


def _rate_for_emotion(emotion: str | None) -> float:
    if emotion in ("frustrated", "sad"):
        return 0.92
    if emotion in ("interested",):
        return 1.0
    return 0.97


async def _build_tts(call_ctx_ref) -> tuple:
    use_orpheus = bool(os.environ.get("TOGETHER_AI_API_KEY"))

    if use_orpheus:
        tts = OrpheusTTSService(
            api_key=os.environ["TOGETHER_AI_API_KEY"],
            voice="leah",
        )
        logger.info("using orpheus tts via together ai")
    else:
        tts = CartesiaTTSService(
            api_key=os.environ["CARTESIA_API_KEY"],
            settings=CartesiaTTSService.Settings(
                voice=os.environ["CARTESIA_VOICE_ID"],
                generation_config=GenerationConfig(
                    speed=_rate_for_emotion(getattr(call_ctx_ref, "current_emotion", None)),
                    emotion="positivity:high",
                ),
            ),
        )
        logger.info("using cartesia tts fallback")

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


async def run_sophia_agent(
    websocket,
    call_sid: str,
    call_context: dict,
    startup_clips: dict = None,
) -> None:
    logger.info("sophia agent starting call_sid={}", call_sid)

    stream_sid = call_sid
    try:
        for _ in range(5):
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            msg = json.loads(raw)
            if msg.get("event") == "start":
                stream_sid = msg.get("streamSid", call_sid)
                logger.info("stream started stream_sid={}", stream_sid)
                break
            logger.debug("pre-start event={}", msg.get("event"))
    except asyncio.TimeoutError:
        logger.warning("timed out waiting for start event using call_sid as fallback")
    except Exception as e:
        logger.warning("could not read start event error={}", str(e))

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

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=TwilioFrameSerializer(
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

    for tool in SOPHIA_TOOLS:
        llm.register_function(tool["name"], _make_tool_handler(tool["name"], call_ctx))

    tts = await _build_tts(call_ctx)

    clip_sample_rate = 16000
    _sc = startup_clips or {}
    backchannel_clips = _sc.get("backchannel") or {}
    filler_clips = _sc.get("filler") or {}
    response_cache_clips = _sc.get("response_cache") or {}

    if not backchannel_clips and not filler_clips and not response_cache_clips:
        cartesia_api_key = os.environ.get("CARTESIA_API_KEY", "")
        cartesia_voice_id = os.environ.get("CARTESIA_VOICE_ID", "")
        backchannel_clips, filler_clips, response_cache_clips = await asyncio.gather(
            pregenerate_backchannel_clips(cartesia_api_key, cartesia_voice_id, clip_sample_rate),
            pregenerate_filler_clips(cartesia_api_key, cartesia_voice_id, clip_sample_rate),
            pregenerate_response_cache(cartesia_api_key, cartesia_voice_id, clip_sample_rate),
        )
        logger.info("clips generated per-call fallback call_sid={}", call_sid)
    else:
        logger.info(
            "using startup clips call_sid={} backchannel={} filler={} cache={}",
            call_sid,
            len(backchannel_clips),
            len(filler_clips),
            len(response_cache_clips),
        )

    transport_output = transport.output()

    backchannel_proc = BackchannelProcessor(transport_output, clip_sample_rate, clips=backchannel_clips)
    filler_proc = FillerGapProcessor(transport_output, clip_sample_rate, clips=filler_clips)
    interruption_proc = InterruptionAckProcessor()

    def on_emotion(emotion: str):
        call_ctx.current_emotion = emotion
        logger.debug("emotion detected emotion={}", emotion)

    emotion_proc = EmotionDetectorProcessor(on_emotion)
    ai_identity_proc = AIIdentityProcessor()
    extended_path = _get_extended_prompt_path() if not spanish_detected else None
    context_tracker = ContextTrackerProcessor(
        call_ctx,
        extended_prompt_path=extended_path,
    )

    response_cache_proc = ResponseCacheProcessor(transport_output, clip_sample_rate, clips=response_cache_clips)
    sentence_streamer = SentenceStreamProcessor()
    fair_housing_filter = FairHousingFilter()

    latency_tracker = LatencyTracker()
    latency_proc_stt = LatencyTrackerProcessor(latency_tracker)
    latency_proc_tts = LatencyTrackerProcessor(latency_tracker)

    room_tone_proc = RoomToneProcessor()
    phone_eq_proc = PhoneEQProcessor()
    breath_injector_proc = BreathInjectorProcessor()

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
    if not spanish_detected:
        context_tracker._llm_context = context

    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    confidence=0.7,
                    start_secs=0.2,
                    stop_secs=0.2,
                    min_volume=0.6,
                ),
            ),
        ),
    )

    pipeline = Pipeline([
        transport.input(),
        stt,
        latency_proc_stt,
        emotion_proc,
        ai_identity_proc,
        context_tracker,
        backchannel_proc,
        filler_proc,
        interruption_proc,
        context_aggregator.user(),
        llm,
        fair_housing_filter,
        sentence_streamer,
        response_cache_proc,
        breath_injector_proc,
        tts,
        latency_proc_tts,
        phone_eq_proc,
        room_tone_proc,
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
        await task.queue_frames([context_aggregator.user().get_context_frame()])

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
        await _handle_call_end(call_sid, call_context, context, call_ctx, seller_memory)


async def _handle_call_end(
    call_sid: str,
    call_context: dict,
    context: LLMContext,
    call_ctx=None,
    seller_memory=None,
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
                "signalwire_call_id": call_sid,
                "direction": "inbound",
                "transcript": transcript,
                "call_disposition": disposition,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            insert_call(call_data)

            if disposition:
                update_lead_for_disposition(lead["id"], disposition)

            asyncio.create_task(
                _run_qa_async(transcript, lead["id"], call_sid)
            )
            asyncio.create_task(
                _run_transcript_intel_async(transcript, lead["id"], call_sid)
            )

    except Exception as e:
        logger.error("handle_call_end error call_sid={} error={}", call_sid, str(e))


async def _run_qa_async(transcript: str, lead_id: str, call_sid: str) -> None:
    try:
        await asyncio.to_thread(grade_call, transcript, lead_id, call_sid)
        logger.info("QA grading complete call_sid={}", call_sid)
    except Exception as e:
        logger.error("QA grading failed call_sid={} error={}", call_sid, str(e))


async def _run_transcript_intel_async(transcript: str, lead_id: str, call_sid: str) -> None:
    try:
        from backend.qa.transcript_intel import analyze_transcript
        await asyncio.to_thread(analyze_transcript, transcript, lead_id, call_sid)
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
