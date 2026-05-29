import asyncio
import os
import random

import httpx
from loguru import logger

from pipecat.frames.frames import Frame, OutputAudioRawFrame, UserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


FILLER_PHRASES = ["Yeah...", "Mhm...", "Okay so...", "Right...", "Let me think...", "Hmm..."]

# Energy-aware phrase preference maps (G17)
# Values are subsets of FILLER_PHRASES ordered by preference for each energy state
_ENERGY_PHRASE_PREFERENCE: dict[str, list[str]] = {
    "calm":       ["Mhm...", "Okay so...", "Right..."],
    "emotional":  ["Mhm...", "Okay so..."],
    "skeptical":  ["Yeah...", "Right...", "Okay so..."],
    "rushed":     ["Right...", "Yeah...", "Mhm..."],
    "talkative":  ["Mhm...", "Right...", "Yeah..."],
    "hesitant":   ["Okay so...", "Let me think...", "Hmm..."],
    "motivated":  ["Right...", "Yeah...", "Mhm..."],
}


async def pregenerate_filler_clips(
    api_key: str = None,
    voice_id: str = None,
    sample_rate: int = 16000,
) -> dict[str, bytes]:
    api_key = api_key or os.environ.get("CARTESIA_API_KEY", "")
    voice_id = voice_id or os.environ.get("CARTESIA_VOICE_ID", "")
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
    def __init__(
        self,
        transport_output: FrameProcessor,
        sample_rate: int = 16000,
        clips: dict = None,
        energy_getter=None,
    ):
        super().__init__()
        self._transport_output = transport_output
        self._clips = clips if clips is not None else {}
        self._sample_rate = sample_rate
        self._phrase_list = list(self._clips.keys())
        # energy_getter: callable returning current SellerEnergy string (G17)
        self._energy_getter = energy_getter
        # Anti-repetition: track last 3 phrases (G18)
        self._recent_phrases: list[str] = []

    def _pick_phrase(self) -> str | None:
        if not self._phrase_list:
            return None

        energy = self._energy_getter() if self._energy_getter else "calm"
        preferred = _ENERGY_PHRASE_PREFERENCE.get(energy, [])

        # Build candidate list: prefer energy-matched phrases not recently used
        available = [p for p in self._phrase_list if p in self._clips]
        recent_set = set(self._recent_phrases[-3:])

        # Try preferred phrases not recently used
        candidates = [p for p in preferred if p in available and p not in recent_set]
        if not candidates:
            # Fall back to any available not recently used
            candidates = [p for p in available if p not in recent_set]
        if not candidates:
            candidates = available

        phrase = random.choice(candidates)
        self._recent_phrases.append(phrase)
        if len(self._recent_phrases) > 6:
            self._recent_phrases = self._recent_phrases[-6:]
        return phrase

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStoppedSpeakingFrame) and self._clips:
            asyncio.create_task(self._inject_filler())

        await self.push_frame(frame, direction)

    async def _inject_filler(self):
        phrase = self._pick_phrase()
        if not phrase:
            return
        pcm = self._clips.get(phrase)
        if not pcm:
            return
        frame = OutputAudioRawFrame(audio=pcm, sample_rate=self._sample_rate, num_channels=1)
        try:
            await self._transport_output.push_frame(frame)
            logger.debug("filler injected phrase={} energy={}", phrase,
                         self._energy_getter() if self._energy_getter else "?")
        except Exception as e:
            logger.warning("filler inject failed error={}", str(e))
