from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class StreamState:
    last_seller_text: str = ""
    last_sophia_text: str = ""
    this_turn_interrupted: bool = False
    this_turn_backchannel: bool = False
    sophia_words_spoken: int = 0
    current_turn_start_ms: float = field(
        default_factory=lambda: time.monotonic() * 1000
    )

    total_turns: int = 0
    total_interruptions: int = 0
    total_silence_events: int = 0
    consecutive_silences: int = 0
    call_start_ms: float = field(
        default_factory=lambda: time.monotonic() * 1000
    )
    last_activity_ms: float = field(
        default_factory=lambda: time.monotonic() * 1000
    )
    sophia_avg_response_ms: float = 0.0
    seller_avg_response_length: float = 0.0

    in_recovery_mode: bool = False
    objection_active: bool = False
    price_discussed: bool = False
    appointment_attempted: bool = False
    warm_transfer_triggered: bool = False
    call_should_end: bool = False

    def reset_for_turn(self) -> None:
        self.this_turn_interrupted = False
        self.this_turn_backchannel = False
        self.sophia_words_spoken = 0
        self.current_turn_start_ms = time.monotonic() * 1000
        self.last_activity_ms = time.monotonic() * 1000

    def record_seller_turn(self, text: str) -> None:
        self.last_seller_text = text
        self.total_turns += 1
        word_count = len(text.split())
        if self.seller_avg_response_length == 0.0:
            self.seller_avg_response_length = float(word_count)
        else:
            self.seller_avg_response_length = (
                self.seller_avg_response_length * 0.8 + word_count * 0.2
            )
        self.last_activity_ms = time.monotonic() * 1000

    def record_sophia_turn(self, text: str) -> None:
        self.last_sophia_text = text
        self.sophia_words_spoken = len(text.split())
        self.last_activity_ms = time.monotonic() * 1000

    def record_interruption(self) -> None:
        self.this_turn_interrupted = True
        self.total_interruptions += 1

    def record_silence(self) -> None:
        self.total_silence_events += 1
        self.consecutive_silences += 1

    def reset_silence(self) -> None:
        self.consecutive_silences = 0