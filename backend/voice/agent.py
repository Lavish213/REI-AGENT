import os
import asyncio
from datetime import datetime, timezone
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.anthropic import AnthropicLLMService
from pipecat.services.deepgram import DeepgramSTTService
from pipecat.services.cartesia import CartesiaTTSService
from pipecat.transports.network.websocket_server import (
    WebsocketServerParams,
    WebsocketServerTransport,
)
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.processors.logger import FrameLogger

from backend.voice.tools import SOPHIA_TOOLS
from backend.voice.context import compress_context
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


async def run_sophia_agent(
    websocket,
    call_sid: str,
    call_context: dict,
) -> None:
    logger.info("sophia agent starting call_sid={}", call_sid)

    system_prompt = _load_system_prompt(
        call_context.get("property_context_str", "No property context available.")
    )

    transport = WebsocketServerTransport(
        websocket=websocket,
        params=WebsocketServerParams(
            audio_out_enabled=True,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True,
        ),
    )

    stt = DeepgramSTTService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        live_options={
            "model": "nova-2",
            "language": "en-US",
            "punctuate": True,
            "interim_results": False,
            "endpointing": 300,
        },
    )

    llm = AnthropicLLMService(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model=os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514"),
        tools=SOPHIA_TOOLS,
    )

    tts = CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        voice_id=os.environ["CARTESIA_VOICE_ID"],
        params=CartesiaTTSService.InputParams(
            speed="normal",
            emotion=["positivity:high", "curiosity:medium"],
        ),
    )

    owner_first = call_context.get("owner_first_name") or "there"
    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "assistant",
            "content": f"San Joaquin House Buyers, this is Sophia!",
        },
    ]

    context = OpenAILLMContext(messages=messages)
    context_aggregator = llm.create_context_aggregator(context)

    transcript_turns = []

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
        await _handle_call_end(call_sid, call_context, context)


async def _handle_call_end(
    call_sid: str,
    call_context: dict,
    context: OpenAILLMContext,
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
            speaker = "SELLER" if role == "user" else "SOPHIA"
            lines.append(f"{speaker}: {content}")
    return "\n".join(lines)
