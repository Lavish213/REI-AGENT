from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_FRUSTRATED_KEYWORDS = [
    "i don't know", "i'm not sure", "this is hard", "i can't",
    "i'm worried", "not sure", "don't know", "so frustrated",
    "i give up", "this is crazy",
]

_INTERESTED_KEYWORDS = [
    "tell me more", "how much", "when can", "what would",
    "i'm thinking", "what if", "sounds good", "interested",
    "like that idea", "how soon",
]

_SAD_KEYWORDS = [
    "passed away", "divorce", "losing", "behind", "struggling",
    "can't afford", "foreclosure", "death", "sick", "cancer",
    "hospital", "broke", "bankrupt",
]


def _detect_emotion(text: str) -> str | None:
    lower = text.lower()
    for kw in _SAD_KEYWORDS:
        if kw in lower:
            return "sad"
    for kw in _FRUSTRATED_KEYWORDS:
        if kw in lower:
            return "frustrated"
    for kw in _INTERESTED_KEYWORDS:
        if kw in lower:
            return "interested"
    return None


class EmotionDetectorProcessor(FrameProcessor):
    def __init__(self, on_emotion_detected):
        super().__init__()
        self._on_emotion_detected = on_emotion_detected

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            emotion = _detect_emotion(frame.text)
            if emotion:
                self._on_emotion_detected(emotion)

        await self.push_frame(frame, direction)
