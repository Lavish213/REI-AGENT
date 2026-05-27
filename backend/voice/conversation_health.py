from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    WATCH = "watch"
    RECOVERY_NEEDED = "recovery_needed"
    ESCALATE = "escalate"


@dataclass(slots=True)
class ConversationHealth:
    status: HealthStatus = HealthStatus.HEALTHY
    trust_score: int = 7
    momentum_score: int = 7
    emotional_pressure: int = 0
    interruption_count: int = 0
    confusion_count: int = 0
    repetition_count: int = 0
    silence_risk_count: int = 0

    def record_trust_drop(self, amount: int = 1) -> None:
        self.trust_score = max(0, self.trust_score - amount)
        self._refresh_status()

    def record_trust_gain(self, amount: int = 1) -> None:
        self.trust_score = min(10, self.trust_score + amount)
        self._refresh_status()

    def record_momentum_drop(self, amount: int = 1) -> None:
        self.momentum_score = max(0, self.momentum_score - amount)
        self._refresh_status()

    def record_momentum_gain(self, amount: int = 1) -> None:
        self.momentum_score = min(10, self.momentum_score + amount)
        self._refresh_status()

    def record_emotional_pressure(self, amount: int = 1) -> None:
        self.emotional_pressure = min(10, self.emotional_pressure + amount)
        self._refresh_status()

    def record_interruption(self) -> None:
        self.interruption_count += 1
        self._refresh_status()

    def record_confusion(self) -> None:
        self.confusion_count += 1
        self._refresh_status()

    def record_repetition(self) -> None:
        self.repetition_count += 1
        self._refresh_status()

    def record_silence_risk(self) -> None:
        self.silence_risk_count += 1
        self._refresh_status()

    def should_recover(self) -> bool:
        return self.status in {
            HealthStatus.RECOVERY_NEEDED,
            HealthStatus.ESCALATE,
        }

    def get_runtime_instruction(self) -> str:
        if self.status == HealthStatus.ESCALATE:
            return (
                "Conversation health is unstable. Slow down, stop pushing, "
                "simplify, preserve trust, and escalate to a human if needed."
            )

        if self.status == HealthStatus.RECOVERY_NEEDED:
            return (
                "Recovery needed. Shorten the next response, acknowledge the seller, "
                "reduce pressure, and ask one simple grounding question."
            )

        if self.status == HealthStatus.WATCH:
            return (
                "Watch conversation health. Keep responses short, warm, "
                "and avoid adding pressure."
            )

        return ""

    def snapshot(self) -> dict:
        return {
            "status": self.status.value,
            "trust_score": self.trust_score,
            "momentum_score": self.momentum_score,
            "emotional_pressure": self.emotional_pressure,
            "interruption_count": self.interruption_count,
            "confusion_count": self.confusion_count,
            "repetition_count": self.repetition_count,
            "silence_risk_count": self.silence_risk_count,
            "should_recover": self.should_recover(),
        }

    def _refresh_status(self) -> None:
        if self.trust_score <= 2 or self.emotional_pressure >= 8:
            self.status = HealthStatus.ESCALATE
            return

        if (
            self.trust_score <= 4
            or self.momentum_score <= 3
            or self.confusion_count >= 2
            or self.repetition_count >= 2
            or self.silence_risk_count >= 2
        ):
            self.status = HealthStatus.RECOVERY_NEEDED
            return

        if (
            self.trust_score <= 6
            or self.momentum_score <= 5
            or self.interruption_count >= 2
            or self.emotional_pressure >= 5
        ):
            self.status = HealthStatus.WATCH
            return

        self.status = HealthStatus.HEALTHY