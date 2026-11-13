"""Unit tests for the Pipecat 1.16 Google Decisions AudioEmotionObserver."""

from __future__ import annotations

import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from pipecat.classifiers.base_classifier import (
    BaseClassifier,
    ChoiceResult,
    ClassifierAudio,
    ClassifierError,
    ClassifierInput,
    ClassifierQuestion,
    ClassifierResult,
)
from pipecat.clocks.system_clock import SystemClock
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    InputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
    UserMuteStartedFrame,
    UserMuteStoppedFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMTokenUsage
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.utils.asyncio.task_manager import TaskManager

import processors.emotion_perception as emo_mod
from processors.emotion_perception import (
    AudioEmotionObserver,
    compute_pcm16_rms,
    resolve_decision_api_key_async,
)


def _make_pcm_chunk(
    duration_secs: float,
    amplitude: int,
    sample_rate: int = 16000,
    channels: int = 1,
) -> bytes:
    count = int(round(duration_secs * sample_rate)) * channels
    samples = np.full(count, amplitude, dtype=np.int16)
    return samples.tobytes()


class _FakeDecisionsClassifier(BaseClassifier):
    """Deterministic in-memory BaseClassifier double for emotion unit tests."""

    def __init__(
        self,
        scripted: list[tuple[str, float, float, int, int] | tuple[str, float, float, int]] | None = None,
        *,
        setup_delay_secs: float = 0.0,
        raise_error: str | None = None,
    ) -> None:
        super().__init__()
        self._scripted = list(scripted or [("frustrated", 0.91, 0.0, 48, 4)])
        self._setup_delay_secs = setup_delay_secs
        self._raise_error = raise_error
        self.calls: list[dict] = []
        self._call_counter = 0
        self.setup_calls = 0
        self._usage = SimpleNamespace(input_tokens=0, output_tokens=0)
        self.client = SimpleNamespace(usage=self._usage)

    @property
    def model(self) -> str:
        return "gemini-decision-1"

    @property
    def supports_audio(self) -> bool:
        return True

    async def setup(self, task_manager) -> None:
        self.setup_calls += 1
        await super().setup(task_manager)
        if self._setup_delay_secs > 0:
            await asyncio.sleep(self._setup_delay_secs)

    async def _ask(
        self,
        state: str | dict | list,
        questions: dict[str, ClassifierQuestion],
        inputs: tuple[ClassifierInput, ...] = (),
    ) -> tuple[dict[str, ClassifierResult], LLMTokenUsage]:
        idx = min(self._call_counter, len(self._scripted) - 1)
        self._call_counter += 1
        entry = self._scripted[idx]
        if len(entry) == 5:
            choice, confidence, delay_secs, in_tok, out_tok = entry
        else:
            choice, confidence, delay_secs, in_tok = entry
            out_tok = 0
        audio_items = [item for item in inputs if isinstance(item, ClassifierAudio)]
        self.calls.append(
            {
                "state": state,
                "questions": list(questions.keys()),
                "audio_secs": audio_items[0].duration_secs if audio_items else 0.0,
                "sample_rate": audio_items[0].sample_rate if audio_items else 0,
            }
        )
        if delay_secs > 0:
            await asyncio.sleep(delay_secs)
        if self._raise_error:
            raise ClassifierError(self._raise_error)
        self._usage.input_tokens += in_tok
        self._usage.output_tokens += out_tok
        result = ChoiceResult(
            choice=choice,
            probabilities={choice: confidence},
            confidence=confidence,
        )
        return {"emotion": result}, LLMTokenUsage(
            prompt_tokens=in_tok,
            completion_tokens=out_tok,
            total_tokens=in_tok + out_tok,
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

    async def test_disabled_with_injected_classifier_makes_zero_calls(self) -> None:
        fake = _FakeDecisionsClassifier([("angry", 0.95, 0.0, 40, 3)])
        observer = AudioEmotionObserver(enabled=False, classifier=fake)
        self.assertFalse(observer.is_usable)
        captured = await self._attach_capture(observer)

        await observer.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        for _ in range(5):
            await observer.process_frame(
                InputAudioRawFrame(
                    audio=_make_pcm_chunk(0.2, 10000),
                    sample_rate=16000,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.03)
        self.assertEqual(len(fake.calls), 0)
        self.assertEqual(len(captured), 8)

    async def test_missing_api_key_logs_warning_and_secret_manager_caches(self) -> None:
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
            with mock.patch.object(emo_mod.logger, "warning") as warn_mock:
                observer = AudioEmotionObserver(enabled=True, api_key="", session_id="s-nokey")
                self.assertFalse(observer.is_usable)
                self.assertTrue(warn_mock.called)

        emo_mod._SECRET_MANAGER_CACHE.clear()
        emo_mod._IN_FLIGHT_KEY_LOOKUPS.clear()

        def slow_access(request, *, timeout=None, retry="UNSET"):
            time.sleep(0.25)
            return SimpleNamespace(payload=SimpleNamespace(data=b"sm-test-key-123\n"))

        fake_sm = mock.MagicMock()
        fake_sm.access_secret_version.side_effect = slow_access
        fake_sm_module = SimpleNamespace(
            SecretManagerServiceClient=mock.MagicMock(return_value=fake_sm)
        )
        clean_env = {
            k: v
            for k, v in emo_mod.os.environ.items()
            if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")
        }
        with mock.patch.dict("os.environ", clean_env, clear=True), mock.patch.dict(
            "sys.modules",
            {
                "google.cloud.secretmanager": fake_sm_module,
                "google.cloud": SimpleNamespace(secretmanager=fake_sm_module),
            },
        ):
            max_gap = 0.0
            ticks = 0
            running_hb = True

            async def heartbeat() -> None:
                nonlocal max_gap, ticks
                last = time.perf_counter()
                while running_hb:
                    await asyncio.sleep(0.01)
                    now_hb = time.perf_counter()
                    ticks += 1
                    max_gap = max(max_gap, now_hb - last)
                    last = now_hb

            hb_task = asyncio.create_task(heartbeat())
            # Yield once so heartbeat starts ticking BEFORE resolve_decision_api_key_async runs.
            await asyncio.sleep(0)
            try:
                # 10 concurrent cold lookups must deduplicate into 1 RPC with bounded timeout=2.0, retry=None.
                results_10 = await asyncio.gather(
                    *(resolve_decision_api_key_async("proj-emo-test") for _ in range(10))
                )
            finally:
                running_hb = False
                await hb_task

            self.assertEqual(results_10, ["sm-test-key-123"] * 10)
            self.assertGreater(ticks, 5, "Heartbeat task never ticked during lookup")
            self.assertLess(
                max_gap,
                0.05,
                f"Secret Manager lookup stalled event loop ({max_gap:.3f}s)",
            )
            self.assertNotIn("GEMINI_API_KEY", emo_mod.os.environ)
            self.assertEqual(fake_sm.access_secret_version.call_count, 1)
            call_kwargs = fake_sm.access_secret_version.call_args.kwargs
            self.assertEqual(call_kwargs.get("timeout"), 2.0)
            self.assertIsNone(call_kwargs.get("retry"))

            # Cached 2nd lookup returns immediately without another RPC.
            key2 = await resolve_decision_api_key_async("proj-emo-test")
            self.assertEqual(key2, "sm-test-key-123")
            self.assertEqual(fake_sm.access_secret_version.call_count, 1)

            # Observer setup with deferred project_id returns in <50ms even when Secret Manager sleeps 1.0s.
            def very_slow_access(request, *, timeout=None, retry=None):
                time.sleep(0.40)
                return SimpleNamespace(payload=SimpleNamespace(data=b"lazy-key\n"))

            fake_sm.access_secret_version.side_effect = very_slow_access
            t_lazy = time.perf_counter()
            lazy_obs = AudioEmotionObserver(enabled=True, project_id="proj-lazy-setup")
            await self._attach_capture(lazy_obs)
            self.assertLess(time.perf_counter() - t_lazy, 0.05)
            await lazy_obs.cleanup()

            # Empty lookup is cached for SECRET_MANAGER_EMPTY_TTL_SECS on the async path and retries once monotonic clock advances.
            emo_mod._SECRET_MANAGER_CACHE.clear()
            attempts = 0

            def transient_fail(request, *, timeout=None, retry=None):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("transient IAM propagation delay")
                return SimpleNamespace(payload=SimpleNamespace(data=b"recovered-key\n"))

            fake_sm.access_secret_version.side_effect = transient_fail
            t_base = time.monotonic()
            fake_now = [t_base]
            with mock.patch.object(emo_mod.time, "monotonic", side_effect=lambda: fake_now[0]):
                first_empty = await resolve_decision_api_key_async("proj-transient")
                self.assertEqual(first_empty, "")
                fake_now[0] = t_base + 30.0  # Within 60s TTL -> still cached
                cached_empty = await resolve_decision_api_key_async("proj-transient")
                self.assertEqual(cached_empty, "")
                self.assertEqual(attempts, 1)

                fake_now[0] = t_base + 61.0  # Past 60s TTL -> async path expires entry and retries
                recovered = await resolve_decision_api_key_async("proj-transient")
                self.assertEqual(recovered, "recovered-key")
                self.assertEqual(attempts, 2)
            self.assertNotIn("GEMINI_API_KEY", emo_mod.os.environ)
        emo_mod._SECRET_MANAGER_CACHE.clear()
        emo_mod._IN_FLIGHT_KEY_LOOKUPS.clear()

    async def test_setup_warms_in_background_without_holding_start_frame(self) -> None:
        fake = _FakeDecisionsClassifier(setup_delay_secs=1.0)
        observer = AudioEmotionObserver(enabled=True, classifier=fake)
        t0 = time.perf_counter()
        captured = await self._attach_capture(observer)
        await observer.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.05, f"StartFrame blocked by setup warmup ({elapsed:.3f}s)")
        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0][0], StartFrame)

    async def test_vad_utterance_emits_interim_and_final_with_output_tokens(self) -> None:
        fake = _FakeDecisionsClassifier(
            [
                ("hesitant", 0.78, 0.0, 40, 3),
                ("frustrated", 0.92, 0.0, 64, 5),
            ]
        )
        observer = AudioEmotionObserver(
            enabled=True,
            session_id="sess-emo-1",
            classifier=fake,
        )
        captured = await self._attach_capture(observer)

        await observer.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(observer.current_utterance_id, 1)
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
        self.assertEqual(emotion_msgs[0]["input_tokens"], 40)
        self.assertEqual(emotion_msgs[0]["output_tokens"], 3)

        self.assertFalse(emotion_msgs[1]["interim"])
        self.assertEqual(emotion_msgs[1]["emotion"], "frustrated")
        self.assertEqual(emotion_msgs[1]["input_tokens"], 64)
        self.assertEqual(emotion_msgs[1]["output_tokens"], 5)
        self.assertEqual(emotion_msgs[1]["total_input_tokens"], 104)
        self.assertEqual(emotion_msgs[1]["total_output_tokens"], 8)

    async def test_slow_u1_final_is_not_dropped_by_fast_u2_interim(self) -> None:
        fake = _FakeDecisionsClassifier(
            [
                ("frustrated", 0.90, 0.16, 60, 4),  # U1 final (slow)
                ("happy", 0.86, 0.01, 35, 3),       # U2 interim (fast)
                ("calm", 0.89, 0.02, 50, 4),        # U2 final
            ]
        )
        observer = AudioEmotionObserver(enabled=True, session_id="sess-u1-u2", classifier=fake)
        captured = await self._attach_capture(observer)

        # Utterance 1 (short enough to skip interim, triggers final)
        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        for _ in range(4):
            await observer.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.2, 9000), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

        # Utterance 2 starts immediately and emits a fast interim before U1 final returns
        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        observer._last_interim_at -= 2.0
        for _ in range(7):
            await observer.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.2, 9000), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        await asyncio.sleep(0.22)
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.06)

        emotion_msgs = [
            f.message["data"]
            for f, _ in captured
            if isinstance(f, OutputTransportMessageUrgentFrame)
        ]
        u1_finals = [m for m in emotion_msgs if m["utterance_id"] == 1 and not m["interim"]]
        u2_interims = [m for m in emotion_msgs if m["utterance_id"] == 2 and m["interim"]]
        self.assertEqual(len(u1_finals), 1)
        self.assertEqual(u1_finals[0]["emotion"], "frustrated")
        self.assertEqual(len(u2_interims), 1)
        self.assertEqual(u2_interims[0]["emotion"], "happy")

    async def test_stale_interim_dropped_without_skewing_turn2_tokens(self) -> None:
        fake = _FakeDecisionsClassifier(
            [
                ("sarcastic", 0.85, 0.12, 30, 4),  # Turn 1 slow interim (seq 1, dropped)
                ("calm", 0.90, 0.01, 45, 5),       # Turn 1 fast final (seq 2)
                ("happy", 0.88, 0.01, 50, 6),      # Turn 2 final (seq 3)
            ]
        )
        observer = AudioEmotionObserver(enabled=True, session_id="sess-tok", classifier=fake)
        captured = await self._attach_capture(observer)

        # Turn 1
        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        observer._last_interim_at -= 2.0
        for _ in range(7):
            await observer.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.2, 9000), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.18)

        # Turn 2
        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        for _ in range(4):
            await observer.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.2, 9000), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)

        emotion_msgs = [
            f.message["data"]
            for f, _ in captured
            if isinstance(f, OutputTransportMessageUrgentFrame)
        ]
        self.assertEqual([m["emotion"] for m in emotion_msgs], ["calm", "happy"])
        self.assertEqual(emotion_msgs[0]["input_tokens"], 45)
        self.assertEqual(emotion_msgs[0]["output_tokens"], 5)
        # Turn 2's per-call input_tokens must be 50 (NOT 50 + 30 = 80 from dropped interim!)
        self.assertEqual(emotion_msgs[1]["input_tokens"], 50)
        self.assertEqual(emotion_msgs[1]["output_tokens"], 6)
        # Session cumulative totals include all 3 completed classifier calls (30 + 45 + 50 = 125).
        self.assertEqual(emotion_msgs[1]["total_input_tokens"], 125)
        self.assertEqual(emotion_msgs[1]["total_output_tokens"], 15)

    async def test_mute_cancels_interim_preserves_prior_final_and_blocks_muted_audio(self) -> None:
        fake = _FakeDecisionsClassifier(
            [
                ("hesitant", 0.80, 0.30, 30, 2),    # U1 slow interim -> cancelled on mute
                ("frustrated", 0.91, 0.08, 48, 4),  # U1 final -> finishes even if muted right after speech
                ("angry", 0.95, 0.01, 40, 3),       # Must NEVER be called while muted
            ]
        )
        observer = AudioEmotionObserver(enabled=True, classifier=fake)
        captured = await self._attach_capture(observer)

        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        observer._last_interim_at -= 2.0
        for _ in range(7):
            await observer.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.2, 9000), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        # Yield once so U1 interim starts and sleeps in _ask
        await asyncio.sleep(0.01)
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        # Caller immediately clicks Mute right after finishing U1
        await observer.process_frame(UserMuteStartedFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(observer._interim_tasks), 0)

        # Feed loud speech + VAD while muted: zero new calls or tasks allowed (privacy invariant)
        calls_at_mute = len(fake.calls)
        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        for _ in range(8):
            await observer.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.2, 12000), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.14)
        self.assertEqual(len(fake.calls), calls_at_mute)
        self.assertEqual(len(observer._tasks), 0)

        emotion_msgs = [
            f.message["data"]
            for f, _ in captured
            if isinstance(f, OutputTransportMessageUrgentFrame)
        ]
        self.assertEqual(len(emotion_msgs), 1)
        self.assertFalse(emotion_msgs[0]["interim"])
        self.assertEqual(emotion_msgs[0]["emotion"], "frustrated")

        # Unmuting restores normal operation
        await observer.process_frame(UserMuteStoppedFrame(), FrameDirection.DOWNSTREAM)
        self.assertFalse(observer._muted)

        # Also verify RMS fallback mode (no external VAD frames) never classifies audio while muted.
        rms_fake = _FakeDecisionsClassifier([("angry", 0.95, 0.0, 40, 3)])
        rms_obs = AudioEmotionObserver(enabled=True, classifier=rms_fake)
        await self._attach_capture(rms_obs)
        await rms_obs.process_frame(UserMuteStartedFrame(), FrameDirection.DOWNSTREAM)
        for _ in range(7):
            await rms_obs.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.2, 12000), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        for _ in range(6):
            await rms_obs.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.1, 20), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        await asyncio.sleep(0.04)
        self.assertEqual(len(rms_fake.calls), 0)

    async def test_end_frame_cancels_slow_in_flight_tasks(self) -> None:
        fake = _FakeDecisionsClassifier([("calm", 0.90, 2.0, 40, 3)])
        observer = AudioEmotionObserver(enabled=True, classifier=fake)
        await self._attach_capture(observer)

        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        for _ in range(4):
            await observer.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.2, 9000), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        self.assertGreaterEqual(len(observer._tasks), 1)

        await observer.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(observer._tasks), 0)

    async def test_trim_tail_secs_and_rms_onset_no_double_append(self) -> None:
        fake = _FakeDecisionsClassifier([("happy", 0.88, 0.0, 52, 4)])
        observer = AudioEmotionObserver(enabled=True, classifier=fake)
        await self._attach_capture(observer)

        # Feed 2 x 0.08s = 0.16s (= ONSET_HOLD_SECS) at 16 kHz (2560 bytes each = 5120 bytes total).
        for _ in range(2):
            await observer.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.08, 8000), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        self.assertTrue(observer._speaking)
        self.assertEqual(len(observer._speech_buffer), 5120)

        # Feed another 0.84s -> total 1.00s buffered speech, then VAD stop with stop_secs=0.40s -> ~0.60s clip.
        await observer.process_frame(
            InputAudioRawFrame(audio=_make_pcm_chunk(0.84, 8000), sample_rate=16000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await observer.process_frame(
            VADUserStoppedSpeakingFrame(stop_secs=0.40),
            FrameDirection.DOWNSTREAM,
        )
        await asyncio.sleep(0.04)
        self.assertEqual(len(fake.calls), 1)
        self.assertAlmostEqual(fake.calls[0]["audio_secs"], 0.60, delta=0.03)

    async def test_rms_barge_in_echo_gate_stereo_48khz_and_auth_circuit_breaker(self) -> None:
        fake = _FakeDecisionsClassifier([("angry", 0.22, 0.0, 25, 2)])
        observer = AudioEmotionObserver(enabled=True, classifier=fake)
        captured = await self._attach_capture(observer)

        # Low energy during bot speech (< RMS_BARGE_IN_ONSET) must NOT trigger speech onset.
        await observer.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        for _ in range(5):
            await observer.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.1, 700), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
        await observer.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(fake.calls), 0)

        # Stereo 48 kHz utterance (1.0s) downmixes cleanly to mono 1.0s clip and low-confidence falls back to calm.
        await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await observer.process_frame(
            InputAudioRawFrame(
                audio=_make_pcm_chunk(1.0, 9000, sample_rate=48000, channels=2),
                sample_rate=48000,
                num_channels=2,
            ),
            FrameDirection.DOWNSTREAM,
        )
        await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.04)
        self.assertEqual(len(fake.calls), 1)
        self.assertAlmostEqual(fake.calls[0]["audio_secs"], 1.0, delta=0.02)
        emotion_msgs = [
            f.message["data"]
            for f, _ in captured
            if isinstance(f, OutputTransportMessageUrgentFrame)
        ]
        self.assertEqual(emotion_msgs[0]["emotion"], "calm")
        self.assertGreater(compute_pcm16_rms(_make_pcm_chunk(0.1, 16384)), 0.45)
        self.assertEqual(compute_pcm16_rms(b""), 0.0)

        # Permanent auth error trips circuit breaker immediately so subsequent clips are skipped.
        bad_auth_fake = _FakeDecisionsClassifier(raise_error="403 API_KEY_INVALID")
        bad_obs = AudioEmotionObserver(enabled=True, classifier=bad_auth_fake)
        await self._attach_capture(bad_obs)
        await bad_obs.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await bad_obs.process_frame(
            InputAudioRawFrame(audio=_make_pcm_chunk(0.6, 9000), sample_rate=16000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await bad_obs.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.04)
        self.assertFalse(bad_obs.is_usable)

    async def test_concurrency_semaphore_caps_in_flight_requests_and_transcript_grace_window(self) -> None:
        gate = asyncio.Event()
        in_flight = 0
        max_in_flight = 0

        class _GatedClassifier(BaseClassifier):
            def __init__(self) -> None:
                super().__init__()
                self._usage = SimpleNamespace(input_tokens=0, output_tokens=0)
                self.client = SimpleNamespace(usage=self._usage)

            @property
            def model(self) -> str:
                return "gemini-decision-1"

            @property
            def supports_audio(self) -> bool:
                return True

            async def _ask(self, state, questions, inputs=()):
                nonlocal in_flight, max_in_flight
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
                try:
                    await gate.wait()
                    self._usage.input_tokens += 20
                    self._usage.output_tokens += 2
                    res = ChoiceResult(choice="calm", probabilities={"calm": 0.9}, confidence=0.9)
                    return {"emotion": res}, LLMTokenUsage(
                        prompt_tokens=20, completion_tokens=2, total_tokens=22
                    )
                finally:
                    in_flight -= 1

        gated = _GatedClassifier()
        observer = AudioEmotionObserver(enabled=True, classifier=gated)
        captured = await self._attach_capture(observer)

        for turn_idx in range(4):
            await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            if turn_idx == 1:
                # Immediately after Utterance 1 completed (<700ms grace window, no interim yet),
                # transcript_utterance_id still attributes Turn 1's arriving STT transcript to 1.
                self.assertEqual(observer.current_utterance_id, 2)
                self.assertEqual(observer.transcript_utterance_id, 1)
                # Past 700ms grace window, transcript_utterance_id advances to 2.
                observer._utterance_started_at -= 0.80
                self.assertEqual(observer.transcript_utterance_id, 2)
                # When not actively speaking (e.g. speech aborted before completion while last_completed=1),
                # transcript_utterance_id must NOT fall back to last_completed_utterance_id.
                observer._utterance_started_at = time.monotonic()
                observer._speaking = False
                self.assertEqual(observer.transcript_utterance_id, 2)
                observer._speaking = True
            await observer.process_frame(
                InputAudioRawFrame(audio=_make_pcm_chunk(0.6, 9000), sample_rate=16000, num_channels=1),
                FrameDirection.DOWNSTREAM,
            )
            await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            if turn_idx == 1:
                # Once speech stops (not _speaking), transcript_utterance_id equals current_utterance_id (2), never 1.
                observer._utterance_started_at = time.monotonic()
                self.assertEqual(observer.transcript_utterance_id, 2)

        await asyncio.sleep(0.03)
        self.assertEqual(in_flight, 2)
        self.assertEqual(max_in_flight, 2)

        gate.set()
        await asyncio.sleep(0.06)
        self.assertEqual(max_in_flight, 2)
        emotion_msgs = [
            f.message["data"]
            for f, _ in captured
            if isinstance(f, OutputTransportMessageUrgentFrame)
        ]
        self.assertEqual(len(emotion_msgs), 4)
        self.assertEqual(emotion_msgs[-1]["total_input_tokens"], 80)
        self.assertEqual(emotion_msgs[-1]["total_output_tokens"], 8)


if __name__ == "__main__":
    unittest.main()
