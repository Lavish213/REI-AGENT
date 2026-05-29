from __future__ import annotations

import os
from loguru import logger

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_COMPRESS_AFTER = 30


async def compress_context(messages: list[dict], objective: str) -> list[dict]:
    if len(messages) <= _COMPRESS_AFTER:
        return messages

    system_msgs = [m for m in messages if m.get("role") == "system"]
    convo_msgs = [m for m in messages if m.get("role") != "system"]

    if len(convo_msgs) <= 10:
        return messages

    to_summarize = convo_msgs[:-6]
    keep_recent = convo_msgs[-6:]

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        transcript_lines = []
        for m in to_summarize:
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, str) and role in ("user", "assistant"):
                speaker = "SELLER" if role == "user" else "SOPHIA"
                transcript_lines.append(f"{speaker}: {content}")

        transcript = "\n".join(transcript_lines)

        response = await client.messages.create(
            model=_DEFAULT_MODEL,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"Summarize this real estate call transcript in 3-4 sentences. "
                    f"Keep: seller motivation, timeline, condition, price mentioned, objections raised, emotional state. "
                    f"Current objective: {objective}.\n\nTRANSCRIPT:\n{transcript}"
                ),
            }],
        )

        summary = response.content[0].text.strip()
        summary_msg = {"role": "user", "content": f"[PRIOR CALL SUMMARY: {summary}]"}
        compressed = system_msgs + [summary_msg] + keep_recent

        logger.info("context_compressed original={} compressed={}", len(messages), len(compressed))
        return compressed

    except Exception as e:
        logger.warning("context_compress failed error={} returning original", str(e))
        return messages
