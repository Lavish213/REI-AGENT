from loguru import logger
from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, Frame, STTMuteFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class BotSpeakingSTTMuteProcessor(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            await self.push_frame(STTMuteFrame(mute=True), FrameDirection.UPSTREAM)
            logger.debug("stt_mute: muted")

        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self.push_frame(STTMuteFrame(mute=False), FrameDirection.UPSTREAM)
            logger.debug("stt_mute: unmuted")

        await self.push_frame(frame, direction)
