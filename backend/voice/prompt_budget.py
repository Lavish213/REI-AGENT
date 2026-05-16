"""
Prompt budget manager (G24).

Prevents oversized system prompts from inflating token cost and hurting inference speed.
Prioritizes: core Sophia identity > current context > pricing > geo phrases > memory

Budget is measured in characters (rough proxy: 4 chars ≈ 1 token).
Default budget: 6000 chars ≈ 1500 tokens — well within Haiku's 200k context,
but tight enough to keep inference fast and cost down.
"""
from __future__ import annotations

import re
from loguru import logger

# Approx character budget for system prompt (excl. [CONTEXT:] prefix injected live)
DEFAULT_CHAR_BUDGET = 6000

# Section headers in priority order — later sections are trimmed LAST (highest priority)
_SECTION_ORDER = [
    "OFFER GUIDANCE",
    "PRICING",
    "LOCATION INTELLIGENCE",
    "SOPHIA LOCAL GEOGRAPHIC FAMILIARITY",
    "PREVIOUS CALL CONTEXT",
    "SELLER MEMORY",
    "CALLER PROPERTY CONTEXT",
]

_SECTION_PATTERN = re.compile(
    r"^(" + "|".join(re.escape(s) for s in _SECTION_ORDER) + r")\s*$",
    re.MULTILINE,
)


def _split_into_sections(prompt: str) -> list[tuple[str, str]]:
    """Split prompt into (header, body) pairs preserving order."""
    parts = _SECTION_PATTERN.split(prompt)
    sections: list[tuple[str, str]] = []
    i = 0
    # Everything before first header
    preamble = parts[0] if parts else ""
    i = 1
    while i < len(parts):
        header = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections.append((header, body))
        i += 2
    return sections, preamble


def apply_budget(prompt: str, budget: int = DEFAULT_CHAR_BUDGET) -> str:
    """
    Trim the system prompt to stay within character budget.
    Removes or truncates lower-priority sections first.
    """
    if len(prompt) <= budget:
        return prompt

    sections, preamble = _split_into_sections(prompt)
    original_len = len(prompt)

    # Trim from the end of _SECTION_ORDER (lowest priority first)
    trimmed_headers = set()
    result_sections = list(sections)

    for target_header in reversed(_SECTION_ORDER):
        if len(preamble) + sum(len(h) + len(b) for h, b in result_sections) <= budget:
            break
        for i, (h, b) in enumerate(result_sections):
            if h == target_header:
                # Try halving the body first
                half_body = b[: len(b) // 2]
                result_sections[i] = (h, half_body)
                trimmed_headers.add(h)
                if len(preamble) + sum(len(h2) + len(b2) for h2, b2 in result_sections) <= budget:
                    break
                # Remove entirely if still over
                result_sections.pop(i)
                break

    reassembled = preamble
    for h, b in result_sections:
        reassembled += h + "\n" + b

    final_len = len(reassembled)
    if final_len < original_len:
        logger.info(
            "prompt_budget trimmed original={} final={} removed_headers={}",
            original_len, final_len, trimmed_headers,
        )

    return reassembled


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 4 chars per token."""
    return len(text) // 4
