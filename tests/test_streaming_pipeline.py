import asyncio
import base64
import json

import pytest
from pipecat.frames.frames import EndFrame, InterruptionFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, OutputAudioRawFrame, TTSTextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.workers.runner import WorkerRunner
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.twilio import TwilioFrameSerializer

from backend.voice.processors.sentence_streamer import SentenceStreamProcessor
from backend.voice.processors.speech_output import SpeechOutputProcessor


class SyntheticSpeech(FrameProcessor):
    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail
        self.spoken = []

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TTSTextFrame):
            if self.fail:
                await self.push_error("Injected speech-provider failure", force_treat_as_permanent=True)
                return
            self.spoken.append(frame.text)
            await self.push_frame(OutputAudioRawFrame(audio=b"\x00\x00" * 160, sample_rate=8000, num_channels=1))
        await self.push_frame(frame, direction)


class TelephoneSink(FrameProcessor):
    def __init__(self):
        super().__init__()
        self.messages = []
        self.serializer = TwilioFrameSerializer(stream_sid="MZ-validated", params=TwilioFrameSerializer.InputParams(auto_hang_up=False))

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, (OutputAudioRawFrame, InterruptionFrame)):
            encoded = await self.serializer.serialize(frame)
            if encoded:
                self.messages.append(json.loads(encoded))
        await self.push_frame(frame, direction)


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", [1, 7, 40, 1000])
async def test_real_runner_streams_synthetic_audio_to_telephone_serializer(chunk_size):
    speech, sink = SyntheticSpeech(), TelephoneSink()
    task = PipelineWorker(Pipeline([SentenceStreamProcessor(), SpeechOutputProcessor(), speech, sink]), params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=8000))
    runner = WorkerRunner(handle_sigint=False)
    text = "[warm] Hey, this is Sophia. The amount is $150.50. Would Tuesday work?"
    await task.queue_frames([LLMFullResponseStartFrame(), *[LLMTextFrame(text[index:index + chunk_size]) for index in range(0, len(text), chunk_size)], LLMFullResponseEndFrame(), EndFrame()])
    await runner.add_workers(task)
    await asyncio.wait_for(runner.run(), timeout=5)
    assert len(speech.spoken) == 3
    assert "[warm]" not in "".join(speech.spoken)
    assert "$150.50" in "".join(speech.spoken)
    media = [message for message in sink.messages if message["event"] == "media"]
    assert len(media) == 3
    assert all(message["streamSid"] == "MZ-validated" for message in media)
    assert all(len(base64.b64decode(message["media"]["payload"])) == 160 for message in media)


@pytest.mark.asyncio
async def test_fatal_speech_failure_terminates_real_runner():
    speech, sink = SyntheticSpeech(fail=True), TelephoneSink()
    task = PipelineWorker(Pipeline([SentenceStreamProcessor(), speech, sink]), processor_unusable_policy=ProcessorUnusablePolicy.CANCEL)
    observed = []
    @task.event_handler("on_pipeline_error")
    async def on_error(task, frame):
        observed.append(frame.error)
    await task.queue_frames([LLMFullResponseStartFrame(), LLMTextFrame("Hello."), LLMFullResponseEndFrame()])
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(task)
    await asyncio.wait_for(runner.run(), timeout=5)
    assert observed == ["Injected speech-provider failure"]
    assert not speech.spoken
    assert not sink.messages
