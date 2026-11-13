"""Unit tests for the Pipecat 1.16 Google Decisions AudioEmotionObserver."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from pipecat.classifiers.base_classifier import (
    BaseClassifier,
    ChoiceResult,
    ClassifierAudio,
    ClassifierInput,
    ClassifierQuestion,
    ClassifierResult,
)
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    InputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
    UserMuteStartedFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.clocks.system_clock import SystemClock
from pipecat.metrics.metrics import LLMTokenUsage
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.utils.asyncio.task_manager import TaskManager

from processors.emotion_perception import AudioEmotionObserver, compute_pcm16_rms


def _make_pcm_chunk(duration_secs: float, amplitude: int, sample_rate: int = 16000) -> bytes:
    count = int(round(duration_secs * sample_rate))
    samples = np.full(count, amplitude, dtype=np.int16)
    return samples.tobytes()


class _FakeDecisionsClassifier(BaseClassifier):
    """Deterministic in-memory BaseClassifier double for emotion unit tests."""

    def __init__(self, scripted: list[tuple[str, float, float, int]] | None = None) -> None:
        super().__init__()
        self._scripted = list(scripted or [("frustrated", 0.91, 0.0, 48)])
        self.calls: list[dict] = []
        self._usage = SimpleNamespace(input_tokens=0, output_tokens=0)
        self.client = SimpleNamespace(usage=self._usage)

    @property
    def model(self) -> str:
        return "gemini-decision-1"

    @property
    def supports_audio(self) -> bool:
        return True

    async def _ask(
        self,
        state: str | dict | list,
        questions: dict[str, ClassifierQuestion],
        inputs: tuple[ClassifierInput, ...] = (),
    ) -> tuple[dict[str, ClassifierResult], LLMTokenUsage]:
        idx = min(len(self.calls), len(self._scripted) - 1)
        choice, confidence, delay_secs, tok = self._scripted[idx]
        audio_items = [item for item in inputs if isinstance(item, ClassifierAudio)]
        self.calls.append(
            {
                "state": state,
                "questions": list(questions.keys()),
                "audio_secs": audio_items[0].duration_secs if audio_items else 0.0,
            }
        )
        if delay_secs > 0:
            await asyncio.sleep(delay_secs)
        self._usage.input_tokens += tok
        result = ChoiceResult(
            choice=choice,
            probabilities={choice: confidence},
            confidence=confidence,
        )
        return {"emotion": result}, LLMTokenUsage(
            prompt_tokens=tok,
            completion_tokens=0,
            total_tokens=tok,
        )


class TestAudioEmotionObserver(unittest.IsolatedAsyncioTestCase):
    async def _attach_capture(self, observer: AudioEmotionObserver) -> list:
        tm = TaskManager()
        await observer.setup(
            FrameProcessorSetup(
                clock=SystemClock(),
                task_manager=tm,
                pipeline_worker=mock.MagicMock(),
            )
        )
        self.addAsyncCleanup(observer.cleanup)
        captured: list = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            captured.append((frame, direction))

        observer.push_frame = capture  # type: ignore[method-assign]
        return captured

    async def test_disabled_or_missing_api_key_is_pure_passthrough(self) -> None:
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
            observer = AudioEmotionObserver(enabled=True, api_key="")
        self.assertFalse(observer.is_usable)
        captured = await self._attach_capture(observer)

        chunk = InputAudioRawFrame(
            audio=_make_pcm_chunk(0.8, 12000),
            sample_rate=16000,
            num_channels=1,
        )
        await observer.process_frame(chunk, FrameDirection.DOWNSTREAM)
        self.assertEqual(len(captured), 1)
        self.assertIs(captured[0][0], chunk)

    async def test_vad_utterance_emits_interim_and_final_emotion_frames(self) -> None:
        fake = _FakeDecisionsClassifier(
            [
                ("hesitant", 0.78, 0.0, 40),
                ("frustrated", 0.92, 0.0, 64),
            ]
        )
        observer = AudioEmotionObserver(
            enabled=True,
            session_id="sess-emo-1",
            classifier=fake,
        )
        captured = await self._attach_capture(observer)

        await observer.process_frame(
            StartFrame(),
            FrameDirection.DOWNSTREAM,
        )
        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        # Rewind _last_interim_at slightly so >=1.2s buffered speech triggers interim immediately.
        observer._last_interim_at -= 2.0
        for _ in range(7):
            await observer.process_frame(
                InputAudioRawFrame(
                    audio=_make_pcm_chunk(0.2, 9000),
                    sample_rate=16000,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )
        await asyncio.sleep(0.05)
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)

        emotion_msgs = [
            f.message["data"]
            for f, _ in captured
            if isinstance(f, OutputTransportMessageUrgentFrame)
            and f.message.get("data", {}).get("type") == "user_emotion"
        ]
        self.assertEqual(len(emotion_msgs), 2)
        self.assertTrue(emotion_msgs[0]["interim"])
        self.assertEqual(emotion_msgs[0]["emotion"], "hesitant")
        self.assertEqual(emotion_msgs[0]["emoji"], "\U0001f61f")
        self.assertEqual(emotion_msgs[0]["input_tokens"], 40)

        self.assertFalse(emotion_msgs[1]["interim"])
        self.assertEqual(emotion_msgs[1]["emotion"], "frustrated")
        self.assertEqual(emotion_msgs[1]["emoji"], "\U0001f624")
        self.assertEqual(emotion_msgs[1]["title"], "Frustrated")
        self.assertEqual(emotion_msgs[1]["input_tokens"], 64)

    async def test_rms_fallback_detects_speech_without_local_vad_and_ignores_bot_echo(self) -> None:
        fake = _FakeDecisionsClassifier([("happy", 0.88, 0.0, 52)])
        observer = AudioEmotionObserver(
            enabled=True,
            session_id="sess-live-vad",
            classifier=fake,
        )
        captured = await self._attach_capture(observer)

        # Low energy during bot speech (< RMS_BARGE_IN_ONSET) must NOT trigger speech onset.
        await observer.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        for _ in range(6):
            await observer.process_frame(
                InputAudioRawFrame(
                    audio=_make_pcm_chunk(0.1, 700),  # RMS ~ 0.021 < 0.036 barge-in gate
                    sample_rate=16000,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )
        await observer.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(fake.calls), 0)

        # Real caller utterance (0.7s active speech followed by 0.6s silence).
        for _ in range(7):
            await observer.process_frame(
                InputAudioRawFrame(
                    audio=_make_pcm_chunk(0.1, 8000),
                    sample_rate=16000,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )
        for _ in range(6):
            await observer.process_frame(
                InputAudioRawFrame(
                    audio=_make_pcm_chunk(0.1, 50),
                    sample_rate=16000,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )
        await asyncio.sleep(0.05)

        emotion_msgs = [
            f.message["data"]
            for f, _ in captured
            if isinstance(f, OutputTransportMessageUrgentFrame)
        ]
        self.assertEqual(len(emotion_msgs), 1)
        self.assertEqual(emotion_msgs[0]["emotion"], "happy")
        self.assertEqual(emotion_msgs[0]["emoji"], "\U0001f60a")
        self.assertFalse(emotion_msgs[0]["interim"])

    async def test_stale_interim_response_cannot_overwrite_newer_final_emotion(self) -> None:
        fake = _FakeDecisionsClassifier(
            [
                ("sarcastic", 0.85, 0.12, 30),  # Slow interim (seq 1)
                ("calm", 0.90, 0.01, 45),       # Fast final (seq 2)
            ]
        )
        observer = AudioEmotionObserver(
            enabled=True,
            session_id="sess-race",
            classifier=fake,
        )
        captured = await self._attach_capture(observer)
        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        observer._last_interim_at -= 2.0
        for _ in range(7):
            await observer.process_frame(
                InputAudioRawFrame(
                    audio=_make_pcm_chunk(0.2, 9000),
                    sample_rate=16000,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.20)

        emotion_msgs = [
            f.message["data"]
            for f, _ in captured
            if isinstance(f, OutputTransportMessageUrgentFrame)
        ]
        self.assertEqual(len(emotion_msgs), 1)
        self.assertEqual(emotion_msgs[0]["emotion"], "calm")
        self.assertFalse(emotion_msgs[0]["interim"])

    async def test_low_confidence_non_calm_falls_back_to_calm_and_mute_cancels(self) -> None:
        fake = _FakeDecisionsClassifier([("angry", 0.22, 0.0, 25)])
        observer = AudioEmotionObserver(enabled=True, classifier=fake)
        captured = await self._attach_capture(observer)

        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        for _ in range(3):
            await observer.process_frame(
                InputAudioRawFrame(
                    audio=_make_pcm_chunk(0.25, 9000),
                    sample_rate=16000,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)

        emotion_msgs = [
            f.message["data"]
            for f, _ in captured
            if isinstance(f, OutputTransportMessageUrgentFrame)
        ]
        self.assertEqual(len(emotion_msgs), 1)
        self.assertEqual(emotion_msgs[0]["emotion"], "calm")
        self.assertEqual(emotion_msgs[0]["emoji"], "\U0001f60c")

        await observer.process_frame(UserMuteStartedFrame(), FrameDirection.DOWNSTREAM)
        await observer.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)
        self.assertGreater(compute_pcm16_rms(_make_pcm_chunk(0.1, 16384)), 0.45)
        self.assertEqual(compute_pcm16_rms(b""), 0.0)


if __name__ == "__main__":
    unittest.main()
