from __future__ import annotations

from loguru import logger

_LEARNING_RATE = 0.1
_LENGTH_THRESHOLD = 5
_SMOOTHING_FACTOR = 3
_BASE_WPM = 150.0


class SpeedTracker:
    def __init__(self, call_ctx):
        self._ctx = call_ctx
        self._wpm = _BASE_WPM
        self._speed_coefficient = 1.0

    def update(self, text: str) -> None:
        words = text.strip().split()
        length = len(words)
        if length < 2:
            return

        p_t = min(
            1.0,
            _LEARNING_RATE * ((length + _SMOOTHING_FACTOR) / (_LENGTH_THRESHOLD + _SMOOTHING_FACTOR)),
        )
        self._wpm = self._wpm * (1 - p_t) + self._wpm * p_t
        self._speed_coefficient = self._wpm / _BASE_WPM

        self._ctx.tts_speed = max(0.7, min(1.2, self._speed_coefficient * 0.85))

        logger.debug(
            "speed_tracker wpm={:.1f} coefficient={:.2f} tts_speed={:.2f}",
            self._wpm,
            self._speed_coefficient,
            self._ctx.tts_speed,
        )

    @property
    def speed_coefficient(self) -> float:
        return self._speed_coefficient

    @property
    def wpm(self) -> float:
        return self._wpm
