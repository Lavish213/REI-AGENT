from __future__ import annotations

import re
from typing import Any

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_PHRASE_END_CALL = re.compile(
    r"\b(stop calling|remove me|do not call|never call again|leave me alone|take me off)\b",
    re.IGNORECASE,
)
_PHRASE_TRANSFER = re.compile(
    r"\b(transfer me|real person|talk to someone|speak to a human|talk to a person|connect me)\b",
    re.IGNORECASE,
)
_PHRASE_IDENTITY = re.compile(
    r"\b(are you a robot|are you ai|are you real|is this automated|are you human|are you a bot)\b",
    re.IGNORECASE,
)
_PHRASE_GOODBYE = re.compile(
    r"^(bye|goodbye|talk later|take care|gotta go|have a good one|thanks bye)\s*[.!]?\s*$",
    re.IGNORECASE,
)

_IDENTITY_DISCLOSURE = (
    "I'm Sophia — an automated assistant for San Joaquin House Buyers. "
    "Would you like to speak with someone directly?"
)


class AnalysisCallbackProcessor(FrameProcessor):
    def __init__(
        self,
        call_ctx: Any,
        emotional_engine: Any,
        trust_tracker: Any,
        resistance_tracker: Any,
        momentum_tracker: Any,
        fatigue_detector: Any,
        deal_heat_scorer: Any,
        seller_profile_engine: Any,
        microstate_engine: Any,
        runtime_orchestrator: Any,
    ):
        super().__init__()
        self._ctx = call_ctx
        self._emotional_engine = emotional_engine
        self._trust_tracker = trust_tracker
        self._resistance_tracker = resistance_tracker
        self._momentum_tracker = momentum_tracker
        self._fatigue_detector = fatigue_detector
        self._deal_heat_scorer = deal_heat_scorer
        self._seller_profile_engine = seller_profile_engine
        self._microstate_engine = microstate_engine
        self._runtime_orchestrator = runtime_orchestrator
        self._turn_count: int = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if text:
                await self._check_phrase_triggers(text)
                self._run_analysis(text)
                self._maybe_orchestrate()
                self._accumulate_entities(text)
                self._check_kill_switch(text)
                self._turn_count += 1
                self._ctx.turn_count = self._turn_count
                if self._turn_count % 5 == 0:
                    call_sid = getattr(self._ctx, "_call_sid", None)
                    lead_id = getattr(self._ctx, "lead_id", None)
                    if call_sid:
                        try:
                            from backend.voice.call_state_cache import save_snapshot
                            save_snapshot(call_sid, self._ctx)
                        except Exception:
                            pass
                    if lead_id:
                        import asyncio as _asyncio
                        _asyncio.create_task(self._refresh_packet_async(lead_id))
                        _asyncio.create_task(self._write_signal_feedback(lead_id, call_sid))

        await self.push_frame(frame, direction)

    async def _check_phrase_triggers(self, text: str) -> None:
        if _PHRASE_END_CALL.search(text):
            logger.info("phrase_trigger end_call_dead text={!r}", text[:60])
            self._ctx.disposition = "DEAD"
            self._ctx.call_should_end = True
            return

        if _PHRASE_TRANSFER.search(text):
            logger.info("phrase_trigger transfer text={!r}", text[:60])
            self._ctx.runtime_instruction = (
                "[Seller is asking to speak with a real person. "
                "Use the transfer_call tool immediately.]"
            )
            return

        if _PHRASE_IDENTITY.search(text):
            logger.info("phrase_trigger identity_challenge")
            self._ctx.runtime_instruction = (
                f"[Seller asked if you are AI. Respond exactly: '{_IDENTITY_DISCLOSURE}']"
            )
            return

        if _PHRASE_GOODBYE.match(text):
            logger.info("phrase_trigger goodbye text={!r}", text[:40])
            self._ctx.runtime_instruction = (
                "[Seller is saying goodbye. Wrap up warmly. "
                "Do the referral ask, then use end_call tool.]"
            )

    def _run_analysis(self, text: str) -> None:
        for name, engine, method in [
            ("emotional_engine", self._emotional_engine, "_update_emotional_state"),
            ("trust_tracker", self._trust_tracker, "_update_trust"),
            ("resistance_tracker", self._resistance_tracker, "_update_resistance"),
            ("momentum_tracker", self._momentum_tracker, "_update_momentum"),
            ("fatigue_detector", self._fatigue_detector, "_update_fatigue"),
            ("deal_heat_scorer", self._deal_heat_scorer, "_update_heat"),
            ("seller_profile_engine", self._seller_profile_engine, "_update_profile"),
            ("microstate_engine", self._microstate_engine, "_update_microstate"),
        ]:
            try:
                getattr(engine, method)(text)
            except Exception as e:
                logger.warning("{} failed error={}", name, str(e))

    def _maybe_orchestrate(self) -> None:
        try:
            ctx = self._ctx
            trust = getattr(ctx, "trust_score", 5.0)
            heat = getattr(ctx, "deal_heat", 0.0)
            fatigue = getattr(ctx, "fatigue_level", "FRESH")
            resistance = getattr(ctx, "resistance_level", "NONE")
            microstate = getattr(ctx, "microstate", "NEUTRAL")

            if trust < 2.5 and resistance == "BLOCKING":
                logger.info("orchestrator trust_collapse detected ending call")
                ctx.call_should_end = True
                return

            if fatigue == "CRITICAL":
                logger.info("orchestrator fatigue_critical detected ending call")
                ctx.runtime_instruction = (
                    "[Seller is fatigued. Wrap up warmly and end the call. "
                    "Do the referral ask first then use end_call tool.]"
                )
                ctx.call_should_end = True
                return

            if heat >= 8.0 or microstate == "COMMITTING":
                logger.info("orchestrator deal_heat ON_FIRE or COMMITTING injecting close")
                ctx.runtime_instruction = (
                    "[Seller is ready to move forward. "
                    "Go directly to booking the walkthrough appointment now.]"
                )

        except Exception as e:
            logger.warning("orchestrator check failed error={}", str(e))
