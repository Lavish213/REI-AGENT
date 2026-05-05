import os
import asyncio
from collections.abc import AsyncGenerator

import httpx
from loguru import logger

from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame
from pipecat.services.tts_service import TTSService


ORPHEUS_VOICES = ["leah", "juno", "leo", "zac", "zoe", "mia", "aria"]
ORPHEUS_DEFAULT_VOICE = "leah"
ORPHEUS_SAMPLE_RATE = 24000
ORPHEUS_ENDPOINT = "https://api.together.xyz/v1/audio/speech"


class OrpheusTTSService(TTSService):
    def __init__(
        self,
        *,
        api_key: str,
        voice: str = ORPHEUS_DEFAULT_VOICE,
        sample_rate: int = ORPHEUS_SAMPLE_RATE,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._api_key = api_key
        self._voice = voice

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        logger.debug("orpheus tts voice={} len={}", self._voice, len(text))

        yield TTSStartedFrame(context_id=context_id)

        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "cartesia/orpheus-3b-0.1-ft",
                "input": text,
                "voice": self._voice,
                "response_format": "pcm",
                "stream": True,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", ORPHEUS_ENDPOINT, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.error("orpheus error status={} body={}", resp.status_code, body[:200])
                        yield TTSStoppedFrame(context_id=context_id)
                        return

                    async def _byte_iter():
                        async for chunk in resp.aiter_bytes(chunk_size=4096):
                            if chunk:
                                yield chunk

                    async for frame in self._stream_audio_frames_from_iterator(
                        _byte_iter(),
                        in_sample_rate=ORPHEUS_SAMPLE_RATE,
                        context_id=context_id,
                    ):
                        yield frame

        except Exception as e:
            logger.error("orpheus tts failed error={}", str(e))

        yield TTSStoppedFrame(context_id=context_id)
