import asyncio
import os
import random

import httpx
from loguru import logger

from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, Frame, OutputAudioRawFrame, UserStartedSpeakingFrame, UserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


BACKCHANNEL_PHRASES = ["Mhm", "Yeah", "Right", "Uh-huh", "Mm", "Okay", "I see", "Got it"]


async def _generate_clip_elevenlabs(text: str, api_key: str, voice_id: str, sample_rate: int) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5"),
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=headers, json=payload, params={"output_format": f"pcm_{sample_rate}"})
        resp.raise_for_status()
        return resp.content


async def pregenerate_backchannel_clips(
    api_key: str = None,
    voice_id: str = None,
    sample_rate: int = 16000,
) -> dict[str, bytes]:
    api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "")
    clips = {}
    for phrase in BACKCHANNEL_PHRASES:
        try:
            pcm = await _generate_clip_elevenlabs(phrase, api_key, voice_id, sample_rate)
            clips[phrase] = pcm
            logger.info("backchannel clip ready phrase={}", phrase)
        except Exception as e:
            logger.warning("backchannel clip failed phrase={} error={}", phrase, str(e))
        await asyncio.sleep(0.3)
    return clips


class BackchannelProcessor(FrameProcessor):
    def __init__(self, transport_output: FrameProcessor, sample_rate: int = 16000, clips: dict = None):
        super().__init__()
        self._transport_output = transport_output
        self._clips = clips if clips is not None else {}
        self._sample_rate = sample_rate
        self._speaking = False
        self._bot_speaking = False
        self._speaking_task: asyncio.Task | None = None
        self._phrase_list = list(self._clips.keys())
        self._last_phrase: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False

        elif isinstance(frame, UserStartedSpeakingFrame):
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
            while self._speaking and not self._bot_speaking:
                if self._clips:
                    await self._inject()
                interval = random.uniform(4.0, 8.0)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _inject(self):
        if not self._phrase_list or self._bot_speaking:
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
