from __future__ import annotations

from loguru import logger

from pipecat.frames.frames import Frame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_BASE_SPEED: dict[str, float] = {
    "GRIEVING":    0.70,
    "OVERWHELMED": 0.72,
    "DISTRESSED":  0.75,
    "HOSTILE":     0.78,
    "SKEPTICAL":   0.80,
    "NEUTRAL":     0.85,
    "OPEN":        0.88,
    "URGENT":      0.90,
    "EXCITED":     0.92,
}

_BASE_VOLUME: dict[str, float] = {
    "GRIEVING":    0.75,
    "OVERWHELMED": 0.78,
    "DISTRESSED":  0.80,
    "HOSTILE":     0.82,
    "SKEPTICAL":   0.82,
    "NEUTRAL":     0.85,
    "OPEN":        0.87,
    "URGENT":      0.88,
    "EXCITED":     0.90,
}

_MOMENTUM_SPEED_DELTA = 0.03
_MOMENTUM_VOLUME_DELTA = 0.02
_SPEED_MIN = 0.70
_SPEED_MAX = 0.95
_VOLUME_MIN = 0.75
_VOLUME_MAX = 0.92
_DEFAULT_SPEED = 0.85
_DEFAULT_VOLUME = 0.85


class PacingController(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._current_speed: float = _DEFAULT_SPEED
        self._current_volume: float = _DEFAULT_VOLUME

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSTextFrame):
            speed, volume = self._compute_pacing()

            if (
                abs(speed - self._current_speed) > 0.01
                or abs(volume - self._current_volume) > 0.01
            ):
                logger.debug(
                    "pacing_controller speed={:.2f} volume={:.2f} "
                    "emotional_state={} momentum={}",
                    speed,
                    volume,
                    getattr(self._ctx, "emotional_state", "NEUTRAL"),
                    getattr(self._ctx, "momentum_direction", "STABLE"),
                )
                self._current_speed = speed
                self._current_volume = volume
                self._ctx.tts_speed = speed
                self._ctx.tts_volume = volume

                try:
                    from pipecat.services.cartesia.tts import GenerationConfig
                    from pipecat.services.tts_service import TTSUpdateSettingsFrame
                    await self.push_frame(
                        TTSUpdateSettingsFrame(
                            settings={"generation_config": GenerationConfig(
                                speed=speed,
                                volume=volume,
                            )}
                        ),
                        direction,
                    )
                except Exception:
                    pass

        await self.push_frame(frame, direction)

    def _compute_pacing(self) -> tuple[float, float]:
        emotional_state = getattr(self._ctx, "emotional_state", "NEUTRAL")
        momentum_direction = getattr(self._ctx, "momentum_direction", "STABLE")
        microstate = getattr(self._ctx, "microstate", "NEUTRAL")

        speed = _BASE_SPEED.get(emotional_state, _DEFAULT_SPEED)
        volume = _BASE_VOLUME.get(emotional_state, _DEFAULT_VOLUME)

        if momentum_direction == "RISING":
            speed += _MOMENTUM_SPEED_DELTA
            volume += _MOMENTUM_VOLUME_DELTA
        elif momentum_direction == "FALLING":
            speed -= _MOMENTUM_SPEED_DELTA
            volume -= _MOMENTUM_VOLUME_DELTA

        if microstate == "COMMITTING":
            speed = min(speed + 0.02, _SPEED_MAX)
        elif microstate == "VENTING":
            speed = max(speed - 0.03, _SPEED_MIN)
            volume = max(volume - 0.02, _VOLUME_MIN)

        speed = max(_SPEED_MIN, min(_SPEED_MAX, speed))
        volume = max(_VOLUME_MIN, min(_VOLUME_MAX, volume))

        return speed, volume