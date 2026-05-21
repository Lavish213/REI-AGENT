from __future__ import annotations

import os

from anthropic import Anthropic
from loguru import logger


_client: Anthropic | None = None


MAX_CONTEXT_MESSAGES = 12
RECENT_MESSAGE_COUNT = 4
SUMMARY_MAX_TOKENS = 300


def _get_client() -> Anthropic:
    global _client

    if _client is None:
        _client = Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )

    return _client


def compress_context(
    messages: list[dict],
    current_state: str,
) -> list[dict]:

    if len(messages) <= MAX_CONTEXT_MESSAGES:
        return messages

    system_messages = [
        message
        for message in messages
        if message.get("role") == "system"
    ]

    conversation_messages = [
        message
        for message in messages
        if message.get("role") != "system"
    ]

    if len(conversation_messages) <= RECENT_MESSAGE_COUNT:
        return messages

    historical_messages = conversation_messages[
        :-RECENT_MESSAGE_COUNT
    ]

    recent_messages = conversation_messages[
        -RECENT_MESSAGE_COUNT:
    ]

    transcript_parts: list[str] = []

    for message in historical_messages:
        content = message.get("content")

        if not isinstance(content, str):
            continue

        role = (
            "SELLER"
            if message.get("role") == "user"
            else "SOPHIA"
        )

        transcript_parts.append(
            f"{role}: {content.strip()}"
        )

    transcript = "\n".join(transcript_parts).strip()

    if not transcript:
        return messages

    try:
        client = _get_client()

        response = client.messages.create(
            model=os.environ.get(
                "LLM_MODEL",
                "claude-sonnet-4-6",
            ),
            max_tokens=SUMMARY_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize this real estate acquisitions "
                        "conversation.\n\n"
                        "Focus on:\n"
                        "- seller motivation\n"
                        "- emotional state\n"
                        "- timeline\n"
                        "- objections\n"
                        "- property condition\n"
                        "- price discussion\n"
                        "- appointment progress\n"
                        "- important relationship context\n\n"
                        f"Current runtime state: "
                        f"{current_state}\n\n"
                        f"Conversation:\n{transcript}"
                    ),
                }
            ],
        )

        summary_text = (
            response.content[0].text.strip()
        )

        compressed_summary_message = {
            "role": "system",
            "content": (
                "[COMPRESSED CONVERSATION CONTEXT]\n"
                f"{summary_text}"
            ),
        }

        compressed_context = (
            system_messages
            + [compressed_summary_message]
            + recent_messages
        )

        logger.info(
            "context compressed original_messages={} compressed_messages={}",
            len(messages),
            len(compressed_context),
        )

        return compressed_context

    except Exception as error:
        logger.exception(
            "context compression failed error={}",
            str(error),
        )

        return messages