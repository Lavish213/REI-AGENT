import os
import json
import asyncio
from datetime import datetime, timezone
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.frames.frames import LLMContextFrame
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
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

from backend.voice.tools import SOPHIA_TOOLS, execute_tool
from backend.qa.grader import grade_call
from backend.lib.db import insert_call, update_lead_stage


def _load_system_prompt(property_context_str: str) -> str:
    prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")

    parts = []
    for filename in [
        "sophia_system.md",
        "sophia_scenarios.md",
        "sophia_market.md",
        "sophia_scripts.md",
    ]:
        filepath = os.path.join(prompts_dir, filename)
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                parts.append(f.read().strip())

    base_prompt = "\n\n---\n\n".join(parts)

    return f"{base_prompt}\n\n---\n\nCALLER PROPERTY CONTEXT\n\n{property_context_str}"


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


def _make_tool_handler(tool_name: str):
    async def handler(params: FunctionCallParams) -> None:
        result = execute_tool(tool_name, dict(params.arguments))
        await params.result_callback(result)
    return handler


async def run_sophia_agent(
    websocket,
    call_sid: str,
    call_context: dict,
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

    system_prompt = _load_system_prompt(
        call_context.get("property_context_str", "No property context available.")
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_in_sample_rate=16000,
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

    stt = DeepgramSTTService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        settings=DeepgramSTTService.Settings(
            model="nova-2",
            language="en-US",
            punctuate=True,
            interim_results=False,
            endpointing=300,
        ),
    )

    llm = AnthropicLLMService(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        settings=AnthropicLLMService.Settings(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
        ),
    )

    for tool in SOPHIA_TOOLS:
        llm.register_function(tool["name"], _make_tool_handler(tool["name"]))

    tts = CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        settings=CartesiaTTSService.Settings(
            voice=os.environ["CARTESIA_VOICE_ID"],
            generation_config=GenerationConfig(
                speed=1.0,
                emotion="positivity:high",
            ),
        ),
    )

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
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_connected(transport, client):
        logger.info("client connected call_sid={}", call_sid)
        await task.queue_frames([LLMContextFrame(context=context)])

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
        await _handle_call_end(call_sid, call_context, context)


async def _handle_call_end(
    call_sid: str,
    call_context: dict,
    context: LLMContext,
) -> None:
    logger.info("handling call end call_sid={}", call_sid)

    try:
        transcript = _build_transcript(context.messages)

        lead = call_context.get("lead")
        if lead:
            call_data = {
                "lead_id": lead["id"],
                "signalwire_call_id": call_sid,
                "direction": "inbound",
                "transcript": transcript,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            insert_call(call_data)

            asyncio.create_task(
                _run_qa_async(transcript, lead["id"], call_sid)
            )

    except Exception as e:
        logger.error("handle_call_end error call_sid={} error={}", call_sid, str(e))


async def _run_qa_async(transcript: str, lead_id: str, call_sid: str) -> None:
    try:
        await asyncio.to_thread(grade_call, transcript, lead_id, call_sid)
        logger.info("QA grading complete call_sid={}", call_sid)
    except Exception as e:
        logger.error("QA grading failed call_sid={} error={}", call_sid, str(e))


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
