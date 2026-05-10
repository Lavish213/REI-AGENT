import asyncio
import difflib
import random

import httpx
from loguru import logger

from pipecat.frames.frames import Frame, OutputAudioRawFrame, TTSStartedFrame, TTSStoppedFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


CACHED_PHRASES = [
    "Mhm, yeah for sure.",
    "Got it.",
    "Let me pull that up real quick.",
    "And what's the address on that?",
    "Oh that makes sense.",
    "Okay so here's what I'm thinking.",
    "Yeah totally.",
    "Oh wow okay.",
    "Hey! Yeah — you got it.",
    "Oh hey — yeah for sure.",
    "Hey, totally.",
    "Okay so tell me more about that.",
    "Yeah that makes total sense.",
    "Oh interesting — how long ago was that?",
    "Right right, got it.",
    "Mm, okay yeah.",
    "Yeah I totally hear you on that.",
    "Oh I get that — totally valid.",
    "Hmm yeah — let me think about that.",
    "No I hear you, that makes sense.",
    "Oh that works perfectly.",
    "Yeah let's do it — I'll put that in.",
    "Perfect — I'll send you a confirmation.",
    "Amazing, we'll see you then!",
    "Hey I really appreciate you taking the time.",
    "Okay awesome — talk soon!",
    "Hey take care — looking forward to it!",
    "Sounds good, have a great rest of your day!",
    "And what's the condition like on it?",
    "How long have you had it?",
]

FUZZY_THRESHOLD = 0.82


def _fuzzy_match(text: str, candidates: list[str]) -> str | None:
    text_lower = text.strip().lower()
    best_score = 0.0
    best_match = None
    for phrase in candidates:
        score = difflib.SequenceMatcher(None, text_lower, phrase.lower()).ratio()
        if score > best_score:
            best_score = score
            best_match = phrase
    if best_score >= FUZZY_THRESHOLD:
        return best_match
    return None


async def _generate_clip_cartesia(text: str, api_key: str, voice_id: str, sample_rate: int) -> bytes:
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
        resp = await client.post(
            "https://api.cartesia.ai/tts/bytes",
            headers={
                "X-API-Key": api_key,
                "Cartesia-Version": "2024-06-10",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.content


async def pregenerate_response_cache(
    api_key: str,
    voice_id: str,
    sample_rate: int,
) -> dict[str, bytes]:
    clips: dict[str, bytes] = {}
    for phrase in CACHED_PHRASES:
        try:
            pcm = await _generate_clip_cartesia(phrase, api_key, voice_id, sample_rate)
            clips[phrase] = pcm
            logger.info("response_cache clip ready phrase={!r}", phrase)
        except Exception as e:
            logger.warning("response_cache clip failed phrase={!r} error={}", phrase, str(e))
        await asyncio.sleep(0.3)
    return clips


class ResponseCacheProcessor(FrameProcessor):
    def __init__(self, transport_output: FrameProcessor, clips: dict[str, bytes], sample_rate: int):
        super().__init__()
        self._transport_output = transport_output
        self._clips = clips
        self._sample_rate = sample_rate
        self._phrase_keys = list(clips.keys())

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSTextFrame) and self._clips:
            matched = _fuzzy_match(frame.text, self._phrase_keys)
            if matched:
                pcm = self._clips[matched]
                logger.debug("response_cache HIT phrase={!r}", matched)
                context_id = getattr(frame, "context_id", None) or ""
                await self.push_frame(TTSStartedFrame(context_id=context_id), direction)
                audio_frame = OutputAudioRawFrame(
                    audio=pcm,
                    sample_rate=self._sample_rate,
                    num_channels=1,
                )
                await self._transport_output.push_frame(audio_frame)
                await self.push_frame(TTSStoppedFrame(context_id=context_id), direction)
                return

        await self.push_frame(frame, direction)
