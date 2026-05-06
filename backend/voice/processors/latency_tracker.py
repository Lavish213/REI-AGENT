import time

from loguru import logger

from pipecat.frames.frames import (
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class LatencyTracker:
    __slots__ = ("_stop_ts", "_stt_ts", "_tts_start_ts", "_tts_audio_ts", "_logged")

    def __init__(self):
        self._stop_ts: float | None = None
        self._stt_ts: float | None = None
        self._tts_start_ts: float | None = None
        self._tts_audio_ts: float | None = None
        self._logged = False

    def _reset(self):
        self._stop_ts = None
        self._stt_ts = None
        self._tts_start_ts = None
        self._tts_audio_ts = None
        self._logged = False

    def on_user_stopped(self):
        self._reset()
        self._stop_ts = time.perf_counter()

    def on_transcription(self):
        if self._stop_ts and not self._stt_ts:
            self._stt_ts = time.perf_counter()

    def on_tts_started(self):
        if self._stt_ts and not self._tts_start_ts:
            self._tts_start_ts = time.perf_counter()

    def on_tts_audio(self):
        if self._tts_start_ts and not self._tts_audio_ts:
            self._tts_audio_ts = time.perf_counter()
            self._maybe_log()

    def _maybe_log(self):
        if self._logged:
            return
        if not all([self._stop_ts, self._stt_ts, self._tts_start_ts, self._tts_audio_ts]):
            return
        self._logged = True
        stt_ms = int((self._stt_ts - self._stop_ts) * 1000)
        llm_ms = int((self._tts_start_ts - self._stt_ts) * 1000)
        tts_ms = int((self._tts_audio_ts - self._tts_start_ts) * 1000)
        total_ms = int((self._tts_audio_ts - self._stop_ts) * 1000)
        if total_ms > 600:
            label = "[LATENCY ⚠ SLOW]"
        elif total_ms >= 400:
            label = "[LATENCY OK]"
        else:
            label = "[LATENCY ✅ FAST]"
        logger.info(
            "{} STT: {}ms | LLM: {}ms | TTS: {}ms | Total: {}ms",
            label, stt_ms, llm_ms, tts_ms, total_ms,
        )


class LatencyTrackerProcessor(FrameProcessor):
    def __init__(self, tracker: LatencyTracker):
        super().__init__()
        self._t = tracker

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStoppedSpeakingFrame):
            self._t.on_user_stopped()
        elif isinstance(frame, TranscriptionFrame):
            self._t.on_transcription()
        elif isinstance(frame, TTSStartedFrame):
            self._t.on_tts_started()
        elif isinstance(frame, TTSAudioRawFrame):
            self._t.on_tts_audio()

        await self.push_frame(frame, direction)
