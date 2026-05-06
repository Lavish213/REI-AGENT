import numpy as np
from loguru import logger
from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_BREATH_SAMPLE_RATE = 8000
_BREATH_DURATION_MS = 150


def _generate_breath_pcm(sample_rate: int = _BREATH_SAMPLE_RATE) -> bytes:
    num_samples = int(sample_rate * _BREATH_DURATION_MS / 1000)
    t = np.linspace(0, 1.0, num_samples, dtype=np.float32)
    envelope = np.sin(np.pi * t) ** 2
    noise = np.random.normal(0, 0.004, num_samples).astype(np.float32)
    audio = (noise * envelope * 0.15).astype(np.float32)
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    return pcm.tobytes()


_BREATH_PCM: bytes = _generate_breath_pcm()


class BreathInjectorProcessor(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSStartedFrame):
            breath_frame = TTSAudioRawFrame(
                audio=_BREATH_PCM,
                sample_rate=_BREATH_SAMPLE_RATE,
                num_channels=1,
            )
            await self.push_frame(breath_frame, direction)
            logger.debug("breath injected before tts response")
        await self.push_frame(frame, direction)
