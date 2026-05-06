import numpy as np
from loguru import logger
from pipecat.frames.frames import Frame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class PhoneEQProcessor(FrameProcessor):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._hp_state = 0.0
        self._comp_gain_db = 0.0

    def _highpass(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        cutoff = 300.0
        rc = 1.0 / (2.0 * np.pi * cutoff)
        dt = 1.0 / sample_rate
        alpha = rc / (rc + dt)
        out = np.empty_like(samples)
        prev_in = samples[0]
        prev_out = self._hp_state
        for i in range(len(samples)):
            current_in = samples[i]
            out[i] = alpha * (prev_out + current_in - prev_in)
            prev_in = current_in
            prev_out = out[i]
        self._hp_state = float(prev_out)
        return out

    def _presence_boost(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        f0 = 3000.0
        gain_db = 3.0
        Q = 1.0
        A = 10.0 ** (gain_db / 40.0)
        w0 = 2.0 * np.pi * f0 / sample_rate
        alpha = np.sin(w0) / (2.0 * Q)
        b0 = 1.0 + alpha * A
        b1 = -2.0 * np.cos(w0)
        b2 = 1.0 - alpha * A
        a0 = 1.0 + alpha / A
        a1 = -2.0 * np.cos(w0)
        a2 = 1.0 - alpha / A
        b = np.array([b0 / a0, b1 / a0, b2 / a0])
        a = np.array([1.0, a1 / a0, a2 / a0])
        out = np.empty_like(samples)
        x1, x2, y1, y2 = 0.0, 0.0, 0.0, 0.0
        for i in range(len(samples)):
            x0 = samples[i]
            y0 = b[0] * x0 + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2
            out[i] = y0
            x2, x1 = x1, x0
            y2, y1 = y1, y0
        return out

    def _compress(self, samples: np.ndarray) -> np.ndarray:
        threshold_db = -18.0
        ratio = 3.0
        knee_db = 6.0
        attack = 0.01
        release = 0.1
        threshold_lin = 10.0 ** (threshold_db / 20.0)
        out = np.empty_like(samples)
        gain_db = self._comp_gain_db
        for i in range(len(samples)):
            x = samples[i]
            level = abs(x)
            if level < 1e-10:
                level_db = -100.0
            else:
                level_db = 20.0 * np.log10(level)
            knee_lower = threshold_db - knee_db / 2.0
            knee_upper = threshold_db + knee_db / 2.0
            if level_db <= knee_lower:
                target_gain_db = 0.0
            elif level_db <= knee_upper:
                t = (level_db - knee_lower) / knee_db
                cs = (1.0 / ratio - 1.0) * t * t * (knee_db / 2.0)
                target_gain_db = cs
            else:
                target_gain_db = threshold_db + (level_db - threshold_db) / ratio - level_db
            if target_gain_db < gain_db:
                coeff = attack
            else:
                coeff = release
            gain_db = gain_db + coeff * (target_gain_db - gain_db)
            gain_lin = 10.0 ** (gain_db / 20.0)
            out[i] = x * gain_lin
        self._comp_gain_db = gain_db
        return out

    def _saturate(self, samples: np.ndarray) -> np.ndarray:
        drive = 1.0 + 0.005
        return np.tanh(samples * drive) * (1.0 / drive)

    def _process_audio(self, audio_bytes: bytes, sample_rate: int) -> bytes:
        pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float64) / 32768.0
        pcm = self._highpass(pcm, sample_rate)
        pcm = self._presence_boost(pcm, sample_rate)
        pcm = self._compress(pcm)
        pcm = self._saturate(pcm)
        pcm = np.clip(pcm, -1.0, 1.0)
        result = (pcm * 32768.0).astype(np.int16)
        return result.tobytes()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if not isinstance(frame, TTSAudioRawFrame):
            await self.push_frame(frame, direction)
            return
        sample_rate = getattr(frame, "sample_rate", 8000) or 8000
        try:
            processed = self._process_audio(frame.audio, sample_rate)
            frame.audio = processed
        except Exception as exc:
            logger.warning(f"PhoneEQProcessor processing error: {exc}")
        await self.push_frame(frame, direction)
