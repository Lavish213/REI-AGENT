from __future__ import annotations

import re
from loguru import logger

DEFAULT_CHAR_BUDGET = 6000

_SECTION_ORDER = [
    "EXAMPLES",
    "WORKFLOW",
    "CALLER PROPERTY CONTEXT",
    "SELLER MEMORY",
    "ACQUISITION_INTEL",
    "TOOLS",
    "OBJECTIONS",
    "GUARDRAILS",
    "VOICE",
]

_NEVER_REMOVE = frozenset(["TOOLS", "VOICE", "ACQUISITION_INTEL"])

_SECTION_PATTERN = re.compile(
    r"^(" + "|".join(re.escape(s) for s in _SECTION_ORDER) + r")\s*$",
    re.MULTILINE,
)


def _split_into_sections(prompt: str):
    parts = _SECTION_PATTERN.split(prompt)
    sections = []
    preamble = parts[0] if parts else ""
    i = 1
    while i < len(parts):
        header = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections.append((header, body))
        i += 2
    return sections, preamble


def apply_budget(prompt: str, budget: int = DEFAULT_CHAR_BUDGET) -> str:
    if len(prompt) <= budget:
        return prompt

    sections, preamble = _split_into_sections(prompt)
    original_len = len(prompt)
    trimmed_headers = set()
    result_sections = list(sections)

    for target_header in _SECTION_ORDER:
        if len(preamble) + sum(len(h) + len(b) for h, b in result_sections) <= budget:
            break
        for i, (h, b) in enumerate(result_sections):
            if h == target_header:
                half_body = b[: len(b) // 2]
                result_sections[i] = (h, half_body)
                trimmed_headers.add(h)
                if len(preamble) + sum(len(h2) + len(b2) for h2, b2 in result_sections) <= budget:
                    break
                if h not in _NEVER_REMOVE:
                    result_sections.pop(i)
                break

    reassembled = preamble
    for h, b in result_sections:
        reassembled += h + "\n" + b

    final_len = len(reassembled)
    if final_len < original_len:
        logger.info("prompt_budget trimmed original={} final={} removed_headers={}", original_len, final_len, trimmed_headers)

    return reassembled


def estimate_tokens(text: str) -> int:
    return len(text) // 4
