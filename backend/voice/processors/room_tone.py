import random
import struct

from pipecat.frames.frames import Frame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_NOISE_AMPLITUDE = 80


def _add_noise(pcm_bytes: bytes) -> bytes:
    samples = len(pcm_bytes) // 2
    result = bytearray(len(pcm_bytes))
    for i in range(samples):
        sample = struct.unpack_from("<h", pcm_bytes, i * 2)[0]
        noise = random.randint(-_NOISE_AMPLITUDE, _NOISE_AMPLITUDE)
        clamped = max(-32768, min(32767, sample + noise))
        struct.pack_into("<h", result, i * 2, clamped)
    return bytes(result)


class RoomToneProcessor(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSAudioRawFrame) and frame.audio:
            noisy = _add_noise(frame.audio)
            new_frame = TTSAudioRawFrame(
                audio=noisy,
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
                context_id=getattr(frame, "context_id", None),
            )
            new_frame.transport_destination = getattr(frame, "transport_destination", None)
            frame = new_frame

        await self.push_frame(frame, direction)
