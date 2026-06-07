from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Phase = Literal["VERIFY", "LIGHT_DISCOVERY", "QUALIFY", "NEXT_STEP", "WRAP"]
MoodHint = Literal["guarded", "open", "skeptical", "distressed", "motivated", "unknown"]
MissingBox = Literal["condition", "timeline", "motivation", "next_step", "identity", "occupancy", "none"]

@dataclass
class CallBrief:
    phase: Phase = "VERIFY"
    objective: str = "Confirm ownership and introduce the reason for the call."
    missing_box: MissingBox = "motivation"
    mood: MoodHint = "unknown"
    avoid: list[str] = field(default_factory=list)
    escalation: list[str] = field(default_factory=list)
    opener_hint: str | None = None

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "objective": self.objective,
            "missing_box": self.missing_box,
            "mood": self.mood,
            "avoid": self.avoid,
            "escalation": self.escalation,
            "opener_hint": self.opener_hint,
        }

    @staticmethod
    def from_dict(d: dict) -> "CallBrief":
        return CallBrief(
            phase=d.get("phase", "VERIFY"),
            objective=d.get("objective", "Confirm ownership and introduce the reason for the call."),
            missing_box=d.get("missing_box", "motivation"),
            mood=d.get("mood", "unknown"),
            avoid=d.get("avoid", []),
            escalation=d.get("escalation", []),
            opener_hint=d.get("opener_hint"),
        )

    @staticmethod
    def default() -> "CallBrief":
        return CallBrief()
