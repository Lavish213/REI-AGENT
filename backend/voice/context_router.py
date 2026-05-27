from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ContextTier(str, Enum):
    CORE = "core"
    LIVE = "live"
    MEMORY = "memory"
    SCRIPT = "script"
    OPERATIONAL = "operational"


@dataclass(slots=True)
class RoutedContext:
    live_prefix: str
    snippets: list[str]
    memory_notes: list[str]
    operational_notes: list[str]
    max_snippets: int = 3

    def render(self) -> str:
        sections: list[str] = []

        if self.live_prefix:
            sections.append(self.live_prefix)

        if self.memory_notes:
            sections.append(
                "[MEMORY]\n"
                + "\n".join(
                    f"- {note}"
                    for note in self.memory_notes[:3]
                )
            )

        if self.snippets:
            sections.append(
                "[RELEVANT GUIDANCE]\n"
                + "\n".join(
                    f"- {snippet}"
                    for snippet in self.snippets[: self.max_snippets]
                )
            )

        if self.operational_notes:
            sections.append(
                "[OPERATIONAL]\n"
                + "\n".join(
                    f"- {note}"
                    for note in self.operational_notes[:3]
                )
            )

        return "\n\n".join(sections).strip()


class ContextRouter:
    def __init__(
        self,
        max_snippets: int = 3,
        max_memory_notes: int = 3,
        max_operational_notes: int = 3,
    ):
        self.max_snippets = max_snippets
        self.max_memory_notes = max_memory_notes
        self.max_operational_notes = max_operational_notes

    def route(
        self,
        call_ctx: Any,
        seller_text: str = "",
        memory_notes: list[str] | None = None,
        script_snippets: list[str] | None = None,
        operational_notes: list[str] | None = None,
    ) -> RoutedContext:
        seller_lower = seller_text.lower()

        live_prefix = self._build_live_prefix(call_ctx)

        selected_memory = self._select_memory(
            memory_notes or [],
        )

        selected_snippets = self._select_snippets(
            seller_lower=seller_lower,
            call_ctx=call_ctx,
            script_snippets=script_snippets or [],
        )

        selected_operational = self._select_operational_notes(
            seller_lower=seller_lower,
            operational_notes=operational_notes or [],
        )

        return RoutedContext(
            live_prefix=live_prefix,
            snippets=selected_snippets,
            memory_notes=selected_memory,
            operational_notes=selected_operational,
            max_snippets=self.max_snippets,
        )

    def _build_live_prefix(
        self,
        call_ctx: Any,
    ) -> str:
        if hasattr(call_ctx, "build_context_prefix"):
            return call_ctx.build_context_prefix()

        return ""

    def _select_memory(
        self,
        memory_notes: list[str],
    ) -> list[str]:
        cleaned = [
            note.strip()
            for note in memory_notes
            if isinstance(note, str) and note.strip()
        ]

        return cleaned[: self.max_memory_notes]

    def _select_snippets(
        self,
        seller_lower: str,
        call_ctx: Any,
        script_snippets: list[str],
    ) -> list[str]:
        cleaned = [
            snippet.strip()
            for snippet in script_snippets
            if isinstance(snippet, str) and snippet.strip()
        ]

        if not cleaned:
            return []

        objective = ""
        mode = ""

        if hasattr(call_ctx, "get_current_objective"):
            objective = call_ctx.get_current_objective()

        if hasattr(call_ctx, "get_seller_mode"):
            mode = call_ctx.get_seller_mode()

        ranked: list[tuple[int, str]] = []

        for snippet in cleaned:
            score = 0
            snippet_lower = snippet.lower()

            if objective and objective.lower() in snippet_lower:
                score += 5

            if mode and mode.lower() in snippet_lower:
                score += 4

            if "price" in seller_lower and "price" in snippet_lower:
                score += 4

            if "agent" in seller_lower and "agent" in snippet_lower:
                score += 4

            if "not interested" in seller_lower and "not interested" in snippet_lower:
                score += 4

            if "think" in seller_lower and "think" in snippet_lower:
                score += 3

            if "schedule" in seller_lower and "appointment" in snippet_lower:
                score += 3

            if score > 0:
                ranked.append((score, snippet))

        ranked.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        if ranked:
            return [
                snippet
                for _, snippet in ranked[: self.max_snippets]
            ]

        return cleaned[: self.max_snippets]

    def _select_operational_notes(
        self,
        seller_lower: str,
        operational_notes: list[str],
    ) -> list[str]:
        cleaned = [
            note.strip()
            for note in operational_notes
            if isinstance(note, str) and note.strip()
        ]

        if not cleaned:
            return []

        trigger_words = [
            "title",
            "escrow",
            "closing",
            "close",
            "contract",
            "paperwork",
            "mortgage",
            "loan",
            "subject to",
            "seller finance",
            "leaseback",
            "rent back",
        ]

        if not any(
            word in seller_lower
            for word in trigger_words
        ):
            return []

        return cleaned[: self.max_operational_notes]