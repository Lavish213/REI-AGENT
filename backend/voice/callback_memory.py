from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class MemoryEvent:
    timestamp: datetime
    category: str
    content: str


@dataclass(slots=True)
class CallbackMemory:
    seller_name: str | None = None

    property_address: str | None = None

    motivation: str | None = None

    timeline: str | None = None

    condition_notes: list[str] = field(default_factory=list)

    objections: list[str] = field(default_factory=list)

    family_details: list[str] = field(default_factory=list)

    emotional_notes: list[str] = field(default_factory=list)

    appointment_status: str | None = None

    last_offer_amount: int | None = None

    last_contact_at: datetime | None = None

    last_outcome: str | None = None

    events: list[MemoryEvent] = field(default_factory=list)

    def remember(
        self,
        category: str,
        content: str,
    ) -> None:
        cleaned = content.strip()

        if not cleaned:
            return

        self.events.append(
            MemoryEvent(
                timestamp=datetime.now(UTC),
                category=category,
                content=cleaned,
            )
        )

        self.events = self.events[-50:]

        if category == "motivation":
            self.motivation = cleaned

        elif category == "timeline":
            self.timeline = cleaned

        elif category == "condition":
            self._append_unique(
                self.condition_notes,
                cleaned,
                limit=8,
            )

        elif category == "objection":
            self._append_unique(
                self.objections,
                cleaned,
                limit=8,
            )

        elif category == "family":
            self._append_unique(
                self.family_details,
                cleaned,
                limit=8,
            )

        elif category == "emotion":
            self._append_unique(
                self.emotional_notes,
                cleaned,
                limit=8,
            )

        elif category == "outcome":
            self.last_outcome = cleaned

        self.last_contact_at = datetime.now(UTC)

    def set_address(
        self,
        address: str,
    ) -> None:
        cleaned = address.strip()

        if cleaned:
            self.property_address = cleaned
            self.last_contact_at = datetime.now(UTC)

    def set_seller_name(
        self,
        name: str,
    ) -> None:
        cleaned = name.strip()

        if cleaned:
            self.seller_name = cleaned

    def set_offer_amount(
        self,
        amount: int,
    ) -> None:
        if amount <= 0:
            return

        self.last_offer_amount = amount
        self.last_contact_at = datetime.now(UTC)

    def set_appointment_status(
        self,
        status: str,
    ) -> None:
        cleaned = status.strip()

        if not cleaned:
            return

        self.appointment_status = cleaned
        self.last_contact_at = datetime.now(UTC)

    def build_callback_context(self) -> str:
        parts: list[str] = []

        if self.seller_name:
            parts.append(
                f"seller={self.seller_name}"
            )

        if self.property_address:
            parts.append(
                f"address={self.property_address}"
            )

        if self.motivation:
            parts.append(
                f"motivation={self.motivation}"
            )

        if self.timeline:
            parts.append(
                f"timeline={self.timeline}"
            )

        if self.condition_notes:
            parts.append(
                "condition="
                + ", ".join(
                    self.condition_notes[-2:]
                )
            )

        if self.objections:
            parts.append(
                "objections="
                + ", ".join(
                    self.objections[-2:]
                )
            )

        if self.family_details:
            parts.append(
                "family="
                + ", ".join(
                    self.family_details[-2:]
                )
            )

        if self.emotional_notes:
            parts.append(
                "emotion="
                + ", ".join(
                    self.emotional_notes[-2:]
                )
            )

        if self.appointment_status:
            parts.append(
                f"appointment={self.appointment_status}"
            )

        if self.last_offer_amount:
            parts.append(
                f"last_offer=${self.last_offer_amount:,}"
            )

        if self.last_outcome:
            parts.append(
                f"last_outcome={self.last_outcome}"
            )

        if not parts:
            return ""

        return (
            "[CALLBACK MEMORY]\n"
            + "\n".join(
                f"- {part}"
                for part in parts
            )
        )

    def get_recent_events(
        self,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        recent = self.events[-limit:]

        return [
            {
                "timestamp": event.timestamp.isoformat(),
                "category": event.category,
                "content": event.content,
            }
            for event in recent
        ]

    @staticmethod
    def _append_unique(
        target: list[str],
        value: str,
        limit: int,
    ) -> None:
        if value in target:
            return

        target.append(value)

        if len(target) > limit:
            del target[:-limit]