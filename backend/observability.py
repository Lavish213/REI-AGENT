import os
from loguru import logger


def setup_logging() -> None:
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    logger.remove()
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{name}</cyan> | {message}",
        colorize=True,
    )
    logger.info("logging configured level={}", log_level)


def _get_langfuse():
    try:
        from langfuse import Langfuse
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
        if not public_key or not secret_key:
            return None
        return Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    except Exception as e:
        logger.warning("langfuse init failed error={}", str(e))
        return None


_langfuse = None


def get_langfuse():
    global _langfuse
    if _langfuse is None:
        _langfuse = _get_langfuse()
    return _langfuse


def trace_call_start(call_sid: str, call_context: dict) -> object | None:
    lf = get_langfuse()
    if not lf:
        return None
    try:
        lead = call_context.get("lead") or {}
        prop = lead.get("properties") or {}
        trace = lf.trace(
            id=call_sid,
            name="sophia_call",
            metadata={
                "call_sid": call_sid,
                "lead_id": lead.get("id"),
                "address": prop.get("address"),
                "distress_score": prop.get("distress_score"),
                "boss_mode": call_context.get("boss_mode", False),
                "is_outbound": call_context.get("is_outbound", False),
            },
        )
        logger.debug("langfuse trace_start call_sid={}", call_sid)
        return trace
    except Exception as e:
        logger.warning("langfuse trace_start failed call_sid={} error={}", call_sid, str(e))
        return None


def trace_call_end(
    trace,
    call_sid: str,
    disposition: str | None,
    transcript_length: int,
    turn_count: int,
) -> None:
    if not trace:
        return
    try:
        trace.update(
            output={
                "disposition": disposition,
                "transcript_length": transcript_length,
                "turn_count": turn_count,
            },
        )
        lf = get_langfuse()
        if lf:
            lf.flush()
        logger.debug("langfuse trace_end call_sid={} disposition={}", call_sid, disposition)
    except Exception as e:
        logger.warning("langfuse trace_end failed call_sid={} error={}", call_sid, str(e))


def trace_tool_call(
    trace,
    tool_name: str,
    tool_input: dict,
    tool_result: str,
) -> None:
    if not trace:
        return
    try:
        trace.event(
            name=f"tool_{tool_name}",
            metadata={"tool_name": tool_name, "input": tool_input, "result": tool_result[:200]},
        )
    except Exception as e:
        logger.warning("langfuse trace_tool failed tool={} error={}", tool_name, str(e))


def trace_llm_turn(
    trace,
    turn: int,
    user_text: str,
    assistant_text: str,
    latency_ms: int,
) -> None:
    if not trace:
        return
    try:
        trace.generation(
            name=f"turn_{turn}",
            input=user_text[:500],
            output=assistant_text[:500],
            metadata={"turn": turn, "latency_ms": latency_ms},
        )
    except Exception as e:
        logger.warning("langfuse trace_llm_turn failed turn={} error={}", turn, str(e))


def log_call_trace(
    call_sid: str,
    turn: int,
    component: str,
    input_text: str,
    output_text: str,
    latency_ms: int,
    tokens_used: int = 0,
    error: str = "",
) -> None:
    logger.info(
        "trace call={} turn={} component={} latency={}ms tokens={}",
        call_sid,
        turn,
        component,
        latency_ms,
        tokens_used,
    )

    try:
        from backend.lib.db import _get_client
        client = _get_client()
        client.table("traces").insert({
            "signalwire_call_id": call_sid,
            "turn_number": turn,
            "component": component,
            "input_text": input_text[:500] if input_text else "",
            "output_text": output_text[:500] if output_text else "",
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "error": error[:200] if error else "",
        }).execute()
    except Exception as e:
        logger.error("trace save failed call={} error={}", call_sid, str(e))


def log_latency_benchmark(
    call_sid: str,
    turn: int,
    stt_ms: int,
    llm_ms: int,
    tts_ms: int,
) -> None:
    total = stt_ms + llm_ms + tts_ms
    target = int(os.environ.get("LATENCY_TARGET_MS", 800))

    if total > target:
        logger.warning(
            "latency over target call={} turn={} total={}ms target={}ms stt={}ms llm={}ms tts={}ms",
            call_sid, turn, total, target, stt_ms, llm_ms, tts_ms,
        )
    else:
        logger.info(
            "latency ok call={} turn={} total={}ms stt={}ms llm={}ms tts={}ms",
            call_sid, turn, total, stt_ms, llm_ms, tts_ms,
        )

    try:
        from backend.lib.db import _get_client
        client = _get_client()
        client.table("latency_benchmarks").insert({
            "signalwire_call_id": call_sid,
            "turn_number": turn,
            "stt_latency_ms": stt_ms,
            "llm_latency_ms": llm_ms,
            "tts_latency_ms": tts_ms,
            "total_latency_ms": total,
        }).execute()
    except Exception as e:
        logger.error("latency benchmark save failed error={}", str(e))
