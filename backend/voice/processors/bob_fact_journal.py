from __future__ import annotations
import asyncio
import copy
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor
from backend.lib import db


class BobFactJournalProcessor(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._saved = {}
        self._writer = None

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)
        if self._ctx.lead_id and self._ctx.bob_verified_facts != self._saved and (self._writer is None or self._writer.done()):
            self._writer = asyncio.create_task(self._journal())

    async def _journal(self):
        retries = 0
        while self._ctx.bob_verified_facts != self._saved:
            snapshot = copy.deepcopy(self._ctx.bob_verified_facts)
            try:
                await asyncio.to_thread(db.stage_bob_call_facts, self._ctx.lead_id, self._ctx._call_sid, snapshot)
                self._saved = snapshot
            except Exception as error:
                retries += 1
                logger.error("bob_fact_journal_failed call_sid={} type={}", self._ctx._call_sid, type(error).__name__)
                if retries >= 5:
                    return
                await asyncio.sleep(min(5, 2**(retries-1)))
        try:
            await asyncio.to_thread(db.flush_bob_call_fact_outbox, 1)
        except Exception as error:
            logger.warning("bob_fact_flush_failed type={}", type(error).__name__)

    async def cleanup(self):
        if self._writer is not None and not self._writer.done():
            self._writer.cancel()
            await asyncio.gather(self._writer, return_exceptions=True)
        await super().cleanup()
