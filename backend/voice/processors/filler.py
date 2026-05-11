import asyncio
import os
import random

import httpx
from loguru import logger

from pipecat.frames.frames import Frame, OutputAudioRawFrame, UserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


FILLER_PHRASES = ["Yeah...", "Mhm...", "Okay so...", "Right...", "Let me think...", "Hmm..."]


async def pregenerate_filler_clips(
    api_key: str = None,
    voice_id: str = None,
    sample_rate: int = 16000,
) -> dict[str, bytes]:
    api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "")
    clips = {}
    for phrase in FILLER_PHRASES:
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "text": phrase,
                "model_id": os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5"),
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload, params={"output_format": f"pcm_{sample_rate}"})
                resp.raise_for_status()
                clips[phrase] = resp.content
            logger.info("filler clip ready phrase={}", phrase)
        except Exception as e:
            logger.warning("filler clip failed phrase={} error={}", phrase, str(e))
        await asyncio.sleep(0.3)
    return clips


class FillerGapProcessor(FrameProcessor):
    def __init__(self, transport_output: FrameProcessor, sample_rate: int = 16000, clips: dict = None):
        super().__init__()
        self._transport_output = transport_output
        self._clips = clips if clips is not None else {}
        self._sample_rate = sample_rate
        self._phrase_list = list(self._clips.keys())
        self._last_phrase: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStoppedSpeakingFrame) and self._clips:
            asyncio.create_task(self._inject_filler())

        await self.push_frame(frame, direction)

    async def _inject_filler(self):
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
            logger.debug("filler injected phrase={}", phrase)
        except Exception as e:
            logger.warning("filler inject failed error={}", str(e))
