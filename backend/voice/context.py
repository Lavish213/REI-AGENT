import os
from loguru import logger
from anthropic import Anthropic


_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def compress_context(messages: list[dict], current_state: str) -> list[dict]:
    if len(messages) <= 6:
        return messages

    system_messages = [m for m in messages if m.get("role") == "system"]
    conversation = [m for m in messages if m.get("role") != "system"]

    if len(conversation) <= 4:
        return messages

    to_compress = conversation[:-2]
    recent = conversation[-2:]

    transcript = "\n".join([
        f"{'SELLER' if m['role'] == 'user' else 'SOPHIA'}: {m.get('content', '')}"
        for m in to_compress
        if isinstance(m.get("content"), str)
    ])

    try:
        client = _get_client()
        response = client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"Summarize this real estate sales call conversation in 3-4 sentences. "
                    f"Focus on: seller's situation, motivation level, key objections raised, "
                    f"any numbers discussed, and current state of negotiation. "
                    f"Current conversation state: {current_state}\n\n"
                    f"CONVERSATION:\n{transcript}"
                ),
            }],
        )
        summary = response.content[0].text

        compressed_message = {
            "role": "user",
            "content": f"[CONVERSATION SUMMARY SO FAR]: {summary}",
        }

        result = system_messages + [compressed_message] + recent
        logger.info(
            "compress_context reduced {} messages to {}",
            len(messages),
            len(result),
        )
        return result

    except Exception as e:
        logger.error("compress_context failed error={}", str(e))
        return messages
