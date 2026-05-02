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
