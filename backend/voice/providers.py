from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger

ProviderName = Literal["anthropic", "groq", "cartesia", "elevenlabs", "orpheus", "deepgram"]


@dataclass
class ProviderHealth:
    name: ProviderName
    available: bool = True
    failure_count: int = 0
    last_failure_ts: float = 0.0
    total_calls: int = 0
    total_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls

    def record_success(self, latency_ms: float) -> None:
        self.total_calls += 1
        self.total_latency_ms += latency_ms
        self.available = True
        self.failure_count = max(0, self.failure_count - 1)

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_ts = time.monotonic()
        if self.failure_count >= 3:
            self.available = False
            logger.warning("provider={} marked unavailable after {} failures", self.name, self.failure_count)

    def is_circuit_open(self, recovery_secs: float = 60.0) -> bool:
        if self.available:
            return False
        elapsed = time.monotonic() - self.last_failure_ts
        if elapsed >= recovery_secs:
            logger.info("provider={} circuit closing after {}s recovery", self.name, elapsed)
            self.available = True
            self.failure_count = 0
            return False
        return True


@dataclass
class ProviderRegistry:
    _health: dict[ProviderName, ProviderHealth] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("anthropic", "groq", "cartesia", "elevenlabs", "orpheus", "deepgram"):
            self._health[name] = ProviderHealth(name=name)

    def health(self, name: ProviderName) -> ProviderHealth:
        return self._health[name]

    def select_llm(self) -> tuple[str, bool]:
        groq_key = os.environ.get("GROQ_API_KEY", "")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key and not self._health["anthropic"].is_circuit_open():
            return ("anthropic", True)
        if groq_key and not self._health["groq"].is_circuit_open():
            logger.warning("provider_registry selecting groq fallback — tools will not work")
            return ("groq", False)
        logger.error("provider_registry no LLM provider available")
        return ("anthropic", True)

    def select_tts(self) -> str:
        cartesia_key = os.environ.get("CARTESIA_API_KEY", "")
        together_key = os.environ.get("TOGETHER_AI_API_KEY", "")
        elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if cartesia_key and not self._health["cartesia"].is_circuit_open():
            return "cartesia"
        if together_key and not self._health["orpheus"].is_circuit_open():
            return "orpheus"
        if elevenlabs_key and not self._health["elevenlabs"].is_circuit_open():
            return "elevenlabs"
        logger.error("provider_registry no TTS provider available")
        return "cartesia"

    def get_llm_model(self) -> str:
        return os.environ.get("VOICE_LLM_MODEL", "claude-haiku-4-5-20251001")

    def summary(self) -> dict:
        return {
            name: {
                "available": h.available,
                "failure_count": h.failure_count,
                "avg_latency_ms": round(h.avg_latency_ms, 1),
                "total_calls": h.total_calls,
            }
            for name, h in self._health.items()
        }


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
        logger.info("provider_registry initialized")
    return _registry
