import asyncio
import random

import httpx
from loguru import logger

from pipecat.frames.frames import Frame, OutputAudioRawFrame, UserStartedSpeakingFrame, UserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


BACKCHANNEL_PHRASES = ["Mhm", "Yeah", "Right", "Uh-huh", "Mm", "Okay", "I see", "Got it"]


async def _generate_clip_cartesia(text: str, api_key: str, voice_id: str, sample_rate: int) -> bytes:
    url = "https://api.cartesia.ai/tts/bytes"
    headers = {
        "X-API-Key": api_key,
        "Cartesia-Version": "2024-06-10",
        "Content-Type": "application/json",
    }
    payload = {
        "model_id": "sonic-2024-10-19",
        "transcript": text,
        "voice": {"mode": "id", "id": voice_id},
        "output_format": {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": sample_rate,
        },
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.content


async def pregenerate_backchannel_clips(
    api_key: str,
    voice_id: str,
    sample_rate: int,
) -> dict[str, bytes]:
    clips = {}
    for phrase in BACKCHANNEL_PHRASES:
        try:
            pcm = await _generate_clip_cartesia(phrase, api_key, voice_id, sample_rate)
            clips[phrase] = pcm
            logger.info("backchannel clip ready phrase={}", phrase)
        except Exception as e:
            logger.warning("backchannel clip failed phrase={} error={}", phrase, str(e))
        await asyncio.sleep(0.3)
    return clips


class BackchannelProcessor(FrameProcessor):
    def __init__(self, transport_output: FrameProcessor, clips: dict[str, bytes], sample_rate: int):
        super().__init__()
        self._transport_output = transport_output
        self._clips = clips
        self._sample_rate = sample_rate
        self._speaking = False
        self._speaking_task: asyncio.Task | None = None
        self._phrase_list = list(clips.keys())
        self._last_phrase: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            self._speaking = True
            if self._speaking_task:
                self._speaking_task.cancel()
            self._speaking_task = asyncio.create_task(self._monitor())

        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._speaking = False
            if self._speaking_task:
                self._speaking_task.cancel()
                self._speaking_task = None

        await self.push_frame(frame, direction)

    async def _monitor(self):
        try:
            await asyncio.sleep(4.0)
            while self._speaking:
                if self._clips:
                    await self._inject()
                interval = random.uniform(4.0, 8.0)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _inject(self):
        if not self._phrase_list:
            return
        candidates = [p for p in self._phrase_list if p != self._last_phrase]
        if not candidates:
            candidates = self._phrase_list
        phrase = random.choice(candidates)
        self._last_phrase = phrase
        pcm = self._clips.get(phrase)
        if not pcm:
            return
        frame = OutputAudioRawFrame(audio=pcm, sample_rate=self._sample_rate, num_channels=1)
        try:
            await self._transport_output.push_frame(frame)
            logger.debug("backchannel injected phrase={}", phrase)
        except Exception as e:
            logger.warning("backchannel inject failed error={}", str(e))
