"""Unit and functional tests for `processors.background_speech_gate`."""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from typing import Any
import unittest

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from pipecat.classifiers.base_classifier import (
    BaseClassifier,
    ClassifierAudio,
    ClassifierError,
    ClassifierInput,
    ClassifierQuestion,
    ClassifierResult,
    YesNoResult,
)
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    LLMContextFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
    UserMuteStartedFrame,
    UserMuteStoppedFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMTokenUsage
from pipecat.processors.frame_processor import FrameDirection

import agent_live
from processors.background_speech_gate import (
    BackgroundSpeechEvaluator,
    CascadeBackgroundSpeechGate,
    LiveBackgroundSpeechGate,
    _coalesce_audio_frames,
)


class _StubDecisionsClassifier(BaseClassifier):
    """Deterministic in-memory classifier stub recording every request."""

    def __init__(
        self,
        *,
        probability: float = 0.92,
        delay_secs: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.probability = probability
        self.delay_secs = delay_secs
        self.error = error
        self.calls: list[dict[str, Any]] = []

    @property
    def supports_audio(self) -> bool:
        return True

    async def _ask(
        self,
        state: str | dict[str, Any] | list[Any],
        questions: dict[str, ClassifierQuestion],
        inputs: list[ClassifierInput] = (),
    ) -> tuple[dict[str, ClassifierResult], LLMTokenUsage]:
        self.calls.append({"state": state, "questions": dict(questions), "inputs": list(inputs)})
        if self.delay_secs > 0:
            await asyncio.sleep(self.delay_secs)
        if self.error is not None:
            raise self.error
        return (
            {name: YesNoResult(probability=self.probability) for name in questions},
            LLMTokenUsage(prompt_tokens=20, completion_tokens=2, total_tokens=22),
        )


def _pcm_chunk(duration_secs: float, sample_rate: int = 16000) -> bytes:
    num_samples = int(round(duration_secs * sample_rate))
    return b"\x12\x00" * num_samples


class TestBackgroundSpeechEvaluator(unittest.IsolatedAsyncioTestCase):
    """Tests for `BackgroundSpeechEvaluator` thresholds, fail-open, and circuit breaker."""

    async def test_addressed_turn_responds(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.91)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub, ignore_threshold=0.85)
        dec = await ev.evaluate(
            transcript="Yes, my OTP is 4829.",
            last_bot_utterance="Please tell me the 4-digit OTP.",
        )
        self.assertTrue(dec.should_respond)
        self.assertEqual(dec.reason, "addressed")
        self.assertAlmostEqual(dec.addressed_probability, 0.91, places=3)
        self.assertAlmostEqual(dec.background_probability, 0.09, places=3)
        self.assertIn("Please tell me the 4-digit OTP.", stub.calls[0]["state"])

    async def test_high_confidence_background_is_ignored(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.06)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub, ignore_threshold=0.85)
        dec = await ev.evaluate(
            transcript="Mummy ek minute ruko, chai le aao.",
            last_bot_utterance="Would you like to confirm your SIP date?",
        )
        self.assertFalse(dec.should_respond)
        self.assertEqual(dec.reason, "background_speech")
        self.assertAlmostEqual(dec.background_probability, 0.94, places=3)

    async def test_ambiguous_probability_biases_toward_responding(self) -> None:
        # 25% addressed -> 75% background, which is below the 85% ignore threshold.
        stub = _StubDecisionsClassifier(probability=0.25)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub, ignore_threshold=0.85)
        dec = await ev.evaluate(transcript="Haan")
        self.assertTrue(dec.should_respond)
        self.assertEqual(dec.reason, "addressed")

    async def test_short_audio_without_transcript_fails_open(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.01)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub)
        dec = await ev.evaluate(audio_pcm=_pcm_chunk(0.08), sample_rate=16000)
        self.assertTrue(dec.should_respond)
        self.assertEqual(dec.reason, "short_audio_bypass")
        self.assertEqual(len(stub.calls), 0)

    async def test_timeout_fails_open_and_circuit_breaker_opens(self) -> None:
        stub = _StubDecisionsClassifier(delay_secs=0.5)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub, timeout_secs=0.2)
        for _ in range(3):
            dec = await ev.evaluate(transcript="Hello?")
            self.assertTrue(dec.should_respond)
            self.assertEqual(dec.reason, "fail_open_timeout")
        # 4th call should hit circuit breaker immediately without invoking stub.
        dec4 = await ev.evaluate(transcript="Are you there?")
        self.assertTrue(dec4.should_respond)
        self.assertEqual(dec4.reason, "fail_open_circuit_open")
        self.assertEqual(len(stub.calls), 3)

    async def test_classifier_error_fails_open(self) -> None:
        stub = _StubDecisionsClassifier(error=ClassifierError("upstream 503"))
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub)
        dec = await ev.evaluate(transcript="Check my balance")
        self.assertTrue(dec.should_respond)
        self.assertEqual(dec.reason, "fail_open_error")

    async def test_missing_api_key_fails_open(self) -> None:
        ev = BackgroundSpeechEvaluator(enabled=True, api_key="")
        dec = await ev.evaluate(transcript="Hello")
        self.assertTrue(dec.should_respond)
        self.assertEqual(dec.reason, "fail_open_missing_api_key")

    def test_real_google_decisions_client_uses_v1beta(self) -> None:
        ev = BackgroundSpeechEvaluator(enabled=True, api_key="fake-decision-key")
        self.assertIsNotNone(ev.classifier)
        self.assertEqual(ev.classifier.client._genai._api_client._http_options.api_version, "v1beta")


class TestLiveBackgroundSpeechGate(unittest.IsolatedAsyncioTestCase):
    """Tests for `LiveBackgroundSpeechGate` Silero-mode buffering and gating."""

    async def _run_gate_capture(self, gate: LiveBackgroundSpeechGate, frames: list[Frame]) -> list[Frame]:
        emitted: list[Frame] = []

        async def _capture(frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
            emitted.append(frame)

        gate.push_frame = _capture
        for frame in frames:
            await gate.process_frame(frame, FrameDirection.DOWNSTREAM)
        return emitted

    async def test_addressed_turn_flushes_start_coalesced_audio_and_stop(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.95)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub)
        gate = LiveBackgroundSpeechGate(
            ev,
            get_last_bot_utterance=lambda: "How can I help you today?",
        )

        # Idle pre-roll audio should NOT be forwarded before speech starts.
        idle_frame = InputAudioRawFrame(audio=_pcm_chunk(0.20), sample_rate=16000, num_channels=1)
        speech_frames = [
            InputAudioRawFrame(audio=_pcm_chunk(0.15), sample_rate=16000, num_channels=1)
            for _ in range(4)
        ]
        emitted = await self._run_gate_capture(
            gate,
            [
                idle_frame,
                VADUserStartedSpeakingFrame(),
                *speech_frames,
                VADUserStoppedSpeakingFrame(stop_secs=0.2),
            ],
        )

        # Verify Decisions received audio + bot context.
        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(len(stub.calls[0]["inputs"]), 1)
        self.assertIsInstance(stub.calls[0]["inputs"][0], ClassifierAudio)
        self.assertIn("How can I help you today?", stub.calls[0]["state"])

        # Verify emitted order: RTVI telemetry, VADStart, InputAudioRawFrame(s), VADStop.
        frame_types = [type(f) for f in emitted]
        self.assertEqual(frame_types[0], OutputTransportMessageUrgentFrame)
        self.assertEqual(emitted[0].message["data"]["decision"], "respond")
        self.assertEqual(frame_types[1], VADUserStartedSpeakingFrame)
        self.assertEqual(frame_types[-1], VADUserStoppedSpeakingFrame)
        audio_out = [f for f in emitted if isinstance(f, InputAudioRawFrame)]
        self.assertGreaterEqual(len(audio_out), 1)
        total_bytes = sum(len(f.audio) for f in audio_out)
        # 0.20s pre-roll + 4 * 0.15s = 0.80s at 16kHz 16-bit mono = 25600 bytes.
        self.assertEqual(total_bytes, len(_pcm_chunk(0.80)))

    async def test_background_speech_turn_is_completely_suppressed(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.05)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub)
        gate = LiveBackgroundSpeechGate(ev)

        emitted = await self._run_gate_capture(
            gate,
            [
                InputAudioRawFrame(audio=_pcm_chunk(0.20), sample_rate=16000, num_channels=1),
                VADUserStartedSpeakingFrame(),
                InputAudioRawFrame(audio=_pcm_chunk(0.60), sample_rate=16000, num_channels=1),
                VADUserStoppedSpeakingFrame(stop_secs=0.2),
            ],
        )

        # Only the RTVI telemetry message should be emitted; zero speech/audio frames.
        self.assertEqual([type(f) for f in emitted], [OutputTransportMessageUrgentFrame])
        self.assertEqual(emitted[0].message["data"]["decision"], "ignore")
        self.assertEqual(emitted[0].message["data"]["mode"], "live")

    async def test_max_buffer_cap_classifies_mid_turn_and_streams_remainder(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.93)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub)
        gate = LiveBackgroundSpeechGate(ev, max_buffer_secs=1.0, pre_roll_secs=0.0)

        emitted = await self._run_gate_capture(
            gate,
            [
                VADUserStartedSpeakingFrame(),
                InputAudioRawFrame(audio=_pcm_chunk(0.60), sample_rate=16000, num_channels=1),
                InputAudioRawFrame(audio=_pcm_chunk(0.60), sample_rate=16000, num_channels=1),
                InputAudioRawFrame(audio=_pcm_chunk(0.20), sample_rate=16000, num_channels=1),
                VADUserStoppedSpeakingFrame(stop_secs=0.2),
            ],
        )

        # Classified once at the 1.0s cap, not again at stop.
        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(type(emitted[-1]), VADUserStoppedSpeakingFrame)
        total_audio_bytes = sum(len(f.audio) for f in emitted if isinstance(f, InputAudioRawFrame))
        self.assertEqual(total_audio_bytes, len(_pcm_chunk(1.40)))

    async def test_mute_and_cancel_clear_buffered_turn_and_forward(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.90)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub)
        gate = LiveBackgroundSpeechGate(ev)

        emitted = await self._run_gate_capture(
            gate,
            [
                VADUserStartedSpeakingFrame(),
                InputAudioRawFrame(audio=_pcm_chunk(0.40), sample_rate=16000, num_channels=1),
                UserMuteStartedFrame(),
                VADUserStoppedSpeakingFrame(),
                UserMuteStoppedFrame(),
                EndFrame(),
                CancelFrame(),
            ],
        )

        self.assertEqual(len(stub.calls), 0)
        self.assertEqual(
            [type(f) for f in emitted],
            [UserMuteStartedFrame, UserMuteStoppedFrame, EndFrame, CancelFrame],
        )

    async def test_live_gate_interrupts_bot_immediately_on_speech_start(self) -> None:
        from unittest.mock import AsyncMock

        from pipecat.frames.frames import BotStartedSpeakingFrame

        stub = _StubDecisionsClassifier(probability=0.04)
        gate = LiveBackgroundSpeechGate(BackgroundSpeechEvaluator(enabled=True, classifier=stub))
        gate.broadcast_interruption = AsyncMock()

        emitted: list[Frame] = []
        gate.push_frame = lambda f, d=FrameDirection.DOWNSTREAM: asyncio.sleep(0, result=emitted.append(f))

        # Bot starts speaking -> upstream BotStartedSpeakingFrame reaches gate and passes upstream.
        await gate.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        emitted.clear()
        # User starts speaking -> immediate interruption BEFORE speech stops, without
        # emitting a duplicate raw RTVI metric (llm._record_bot_interruption owns that).
        await gate.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        gate.broadcast_interruption.assert_awaited_once()
        self.assertEqual(emitted, [])

        # Background speech still gets dropped at VAD stop without reaching Gemini,
        # and on_ignored_barge_in is notified once.
        ignored_barge_ins: list[int] = []
        gate._on_ignored_barge_in = lambda: ignored_barge_ins.append(1)
        await gate.process_frame(
            InputAudioRawFrame(audio=_pcm_chunk(0.50), sample_rate=16000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await gate.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.2), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(ignored_barge_ins), 1)
        self.assertEqual(emitted[-1].message["data"]["decision"], "ignore")
        self.assertEqual([f for f in emitted if isinstance(f, InputAudioRawFrame)], [])

    async def test_speaking_frames_absorbed_while_buffering_and_stereo_downmixed(self) -> None:
        from pipecat.frames.frames import UserSpeakingFrame
        import numpy as np

        stub = _StubDecisionsClassifier(probability=0.03)
        gate = LiveBackgroundSpeechGate(
            BackgroundSpeechEvaluator(enabled=True, classifier=stub),
            pre_roll_secs=0.0,
        )
        # Build 0.50s of 2-channel stereo PCM (left=1000, right=3000 -> mono=2000).
        num_frames = int(0.50 * 16000)
        stereo = np.column_stack(
            [
                np.full(num_frames, 1000, dtype=np.int16),
                np.full(num_frames, 3000, dtype=np.int16),
            ]
        ).tobytes()

        emitted = await self._run_gate_capture(
            gate,
            [
                VADUserStartedSpeakingFrame(),
                UserSpeakingFrame(),
                InputAudioRawFrame(audio=stereo, sample_rate=16000, num_channels=2),
                VADUserStoppedSpeakingFrame(stop_secs=0.0),
            ],
        )
        # Zero speaking frames leaked downstream; classifier received 1-channel mono 0.50s audio.
        self.assertEqual([type(f) for f in emitted], [OutputTransportMessageUrgentFrame])
        self.assertEqual(emitted[0].message["data"]["audio_duration_secs"], 0.5)
        sent_audio = stub.calls[0]["inputs"][0].audio
        self.assertEqual(len(sent_audio), num_frames * 2)
        mono_vals = np.frombuffer(sent_audio, dtype=np.int16)
        self.assertTrue(np.all(mono_vals == 2000))

    def test_live_vad_mode_forces_silero_when_ignore_background_enabled(self) -> None:
        self.assertEqual(
            agent_live.resolve_live_vad_mode(vad=False, vad_mode="gemini", ignore_background=True),
            ("silero", True, True),
        )
        self.assertEqual(
            agent_live.resolve_live_vad_mode(vad=True, vad_mode="both", ignore_background=True),
            ("silero", True, True),
        )
        vad_params = agent_live.build_gemini_live_vad_params(
            vad=True, vad_mode="both", ignore_background=True
        )
        self.assertIsNotNone(vad_params)
        self.assertTrue(vad_params.disabled)
        analyzer = agent_live.build_live_vad_analyzer(
            vad=False, vad_mode="gemini", ignore_background=True
        )
        self.assertIsNotNone(analyzer)


class TestCascadeBackgroundSpeechGate(unittest.IsolatedAsyncioTestCase):
    """Tests for `CascadeBackgroundSpeechGate` LLM turn gating and context hygiene."""

    async def _run_cascade_capture(
        self,
        gate: CascadeBackgroundSpeechGate,
        frames: list[Frame],
    ) -> list[Frame]:
        emitted: list[Frame] = []

        async def _capture(frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
            emitted.append(frame)

        gate.push_frame = _capture
        for frame in frames:
            await gate.process_frame(frame, FrameDirection.DOWNSTREAM)
        return emitted

    async def test_opening_greeting_and_tool_results_bypass_gate(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.01)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub)
        gate = CascadeBackgroundSpeechGate(ev)

        greeting_ctx = SimpleNamespace(messages=[{"role": "user", "content": "Hello!"}])
        tool_ctx = SimpleNamespace(
            messages=[
                {"role": "user", "content": "Check my SIP"},
                {"role": "assistant", "content": "Checking now."},
                {"role": "tool", "content": '{"sip": 5000}'},
            ]
        )
        emitted = await self._run_cascade_capture(
            gate,
            [LLMContextFrame(context=greeting_ctx), LLMContextFrame(context=tool_ctx)],
        )

        self.assertEqual(len(stub.calls), 0)
        self.assertEqual(len(emitted), 2)

    async def test_addressed_cascade_turn_passes_through_with_audio_and_bot_context(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.94)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub)
        audio_clip = _pcm_chunk(0.50)
        gate = CascadeBackgroundSpeechGate(ev, get_recent_audio=lambda: (audio_clip, 16000))

        ctx = SimpleNamespace(
            messages=[
                {"role": "assistant", "content": "Would you like to invest 5000 rupees monthly?"},
                {"role": "user", "content": "Yes, go ahead."},
            ]
        )
        emitted = await self._run_cascade_capture(
            gate,
            [UserStoppedSpeakingFrame(), LLMContextFrame(context=ctx)],
        )

        self.assertEqual(len(stub.calls), 1)
        self.assertIn("Would you like to invest 5000 rupees monthly?", stub.calls[0]["state"])
        self.assertIn("Yes, go ahead.", stub.calls[0]["state"])
        self.assertEqual(len(stub.calls[0]["inputs"]), 1)
        self.assertEqual(
            [type(f) for f in emitted],
            [UserStoppedSpeakingFrame, OutputTransportMessageUrgentFrame, LLMContextFrame],
        )
        self.assertEqual(len(ctx.messages), 2)

    async def test_ignored_cascade_turn_drops_frame_and_pops_user_message(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.04)
        ev = BackgroundSpeechEvaluator(enabled=True, classifier=stub)
        gate = CascadeBackgroundSpeechGate(ev)

        ctx = SimpleNamespace(
            messages=[
                {"role": "assistant", "content": "How can I assist with your portfolio?"},
                {"role": "user", "content": "Breaking news on Channel 9 tonight!"},
            ]
        )
        emitted = await self._run_cascade_capture(
            gate,
            [VADUserStoppedSpeakingFrame(), LLMContextFrame(context=ctx)],
        )

        self.assertEqual(
            [type(f) for f in emitted],
            [VADUserStoppedSpeakingFrame, OutputTransportMessageUrgentFrame],
        )
        self.assertEqual(emitted[1].message["data"]["decision"], "ignore")
        self.assertEqual(emitted[1].message["data"]["mode"], "cascade")
        # Background message popped so next real user turn sees clean history.
        self.assertEqual(len(ctx.messages), 1)
        self.assertEqual(ctx.messages[0]["role"], "assistant")

    async def test_pipeline_task_interruption_mid_evaluate_never_poisons_llm_context(self) -> None:
        """Real Pipecat 1.16 PipelineTask test for InterruptionFrame task cancellation."""
        from pipecat.frames.frames import EndTaskFrame, InterruptionFrame
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.runner import PipelineRunner
        from pipecat.pipeline.task import PipelineParams, PipelineTask
        from pipecat.processors.aggregators.llm_context import LLMContext
        from pipecat.processors.frame_processor import FrameProcessor
        from turn_telemetry import TurnTracker

        class _Sink(FrameProcessor):
            def __init__(self) -> None:
                super().__init__()
                self.context_frames: list[LLMContextFrame] = []

            async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
                await super().process_frame(frame, direction)
                if isinstance(frame, LLMContextFrame):
                    self.context_frames.append(frame)
                await self.push_frame(frame, direction)

        class _ScriptedClassifier(_StubDecisionsClassifier):
            def __init__(self) -> None:
                super().__init__()
                self.entered_interrupted = asyncio.Event()
                # 1st = normal ignored TV turn, 2nd = interrupted TV turn, 3rd = real caller
                self.probs = [0.04, 0.03, 0.96]

            async def _ask(self, state, questions, inputs=()):
                idx = len(self.calls)
                self.calls.append({"state": state})
                if idx == 1:
                    self.entered_interrupted.set()
                    await asyncio.sleep(0.12)
                prob = self.probs[min(idx, len(self.probs) - 1)]
                return (
                    {name: YesNoResult(probability=prob) for name in questions},
                    LLMTokenUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
                )

        from diagnostic_buffer import DIAGNOSTIC_LOG_BUFFER, TURN_LATENCY_RECORDS
        from processors.turn_telemetry import TurnBoundaryProcessor

        DIAGNOSTIC_LOG_BUFFER.clear()
        TURN_LATENCY_RECORDS.clear()
        tracker = TurnTracker("s-cancel", "tts-llm-stt", vad_stop_padding_ms=400)
        boundary = TurnBoundaryProcessor(tracker)
        stub = _ScriptedClassifier()
        utt_counter = [0]
        gate = CascadeBackgroundSpeechGate(
            BackgroundSpeechEvaluator(enabled=True, classifier=stub),
            get_current_utterance_id=lambda: utt_counter[0],
            on_ignored_turn=tracker.mark_ignored,
        )
        sink = _Sink()
        pipeline = Pipeline([boundary, gate, sink])
        task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))

        ctx = LLMContext(
            messages=[
                {"role": "assistant", "content": "How can I help you today?"},
            ]
        )

        async def _drive() -> None:
            try:
                await asyncio.sleep(0.05)
                # Turn 1 (normal un-interrupted ignored TV speech) -> status="ignored" with 0 ERROR logs.
                utt_counter[0] = 1
                await task.queue_frame(VADUserStartedSpeakingFrame())
                await task.queue_frame(VADUserStoppedSpeakingFrame())
                await asyncio.sleep(0.02)
                turn1 = tracker.current
                ctx.messages.append({"role": "user", "content": "Weather report on radio."})
                await task.queue_frame(LLMContextFrame(context=ctx))
                await asyncio.sleep(0.06)
                self.assertEqual(turn1.status, "ignored")

                # Turn 2 (TV speech interrupted mid-evaluate by Turn 3) -> must NOT clobber Turn 3!
                utt_counter[0] = 2
                await task.queue_frame(VADUserStartedSpeakingFrame())
                await task.queue_frame(VADUserStoppedSpeakingFrame())
                await asyncio.sleep(0.02)
                turn2 = tracker.current
                ctx.messages.append({"role": "user", "content": "Buy crispy chips on Channel 5!"})
                await task.queue_frame(LLMContextFrame(context=ctx))
                await asyncio.wait_for(stub.entered_interrupted.wait(), timeout=2.0)

                await task.queue_frame(InterruptionFrame())
                await asyncio.sleep(0.03)
                utt_counter[0] = 3
                await task.queue_frame(VADUserStartedSpeakingFrame())
                await task.queue_frame(VADUserStoppedSpeakingFrame())
                await asyncio.sleep(0.03)
                turn3 = tracker.current

                await asyncio.sleep(0.18)
                self.assertEqual(
                    [(m["role"], m["content"]) for m in ctx.messages],
                    [("assistant", "How can I help you today?")],
                )
                self.assertEqual(turn2.status, "interrupted")
                self.assertIsNone(turn3.status, "Async Turn 2 ignore must NOT clobber Turn 3!")
                error_logs = [r for r in DIAGNOSTIC_LOG_BUFFER if r.get("level") == "ERROR"]
                self.assertEqual(error_logs, [])
                ignored_records = [
                    r for r in TURN_LATENCY_RECORDS if r["session_id"] == "s-cancel" and r["status"] == "ignored"
                ]
                self.assertEqual(len(ignored_records), 1)
                self.assertEqual(ignored_records[0]["turn_id"], 1)

                # Turn 3: Real caller utterance passes cleanly through the same gate.
                ctx.messages.append({"role": "user", "content": "Book a car service for Friday."})
                await task.queue_frame(LLMContextFrame(context=ctx))
                await asyncio.sleep(0.08)
                await task.queue_frame(EndFrame())
            except Exception:
                await task.cancel()
                raise

        runner = PipelineRunner(handle_sigint=False)
        await asyncio.gather(runner.run(task), _drive())

        self.assertEqual(len(sink.context_frames), 1)
        self.assertEqual(
            [(m["role"], m["content"]) for m in ctx.messages],
            [
                ("assistant", "How can I help you today?"),
                ("user", "Book a car service for Friday."),
            ],
        )

    async def test_cascade_overlapping_cancelled_turns_preserve_order_and_never_hang(self) -> None:
        """Verifies both overlapping addressed orderings (T1 slow/fast) and addressed-T1 + ignored-T2."""
        from pipecat.frames.frames import InterruptionFrame
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.runner import PipelineRunner
        from pipecat.pipeline.task import PipelineParams, PipelineTask
        from pipecat.processors.aggregators.llm_context import LLMContext
        from pipecat.processors.frame_processor import FrameProcessor

        class _SnapshotSink(FrameProcessor):
            def __init__(self) -> None:
                super().__init__()
                self.snapshots: list[list[tuple[str, str]]] = []

            async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
                await super().process_frame(frame, direction)
                if isinstance(frame, LLMContextFrame):
                    self.snapshots.append([(m["role"], m["content"]) for m in frame.context.messages])
                await self.push_frame(frame, direction)

        class _StepClassifier(_StubDecisionsClassifier):
            def __init__(self, steps: list[tuple[float, float]]) -> None:
                super().__init__()
                self.steps = steps  # [(prob, delay_secs), ...]
                self.first_started = asyncio.Event()

            async def _ask(self, state, questions, inputs=()):
                idx = len(self.calls)
                self.calls.append({"state": state})
                if idx == 0:
                    self.first_started.set()
                prob, delay = self.steps[min(idx, len(self.steps) - 1)]
                if delay > 0:
                    await asyncio.sleep(delay)
                return (
                    {name: YesNoResult(probability=prob) for name in questions},
                    LLMTokenUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
                )

        async def _run_overlap_case(
            steps: list[tuple[float, float]],
            t1_text: str,
            t2_text: str,
        ) -> tuple[list[list[tuple[str, str]]], list[tuple[str, str]]]:
            clf = _StepClassifier(steps)
            gate = CascadeBackgroundSpeechGate(BackgroundSpeechEvaluator(enabled=True, classifier=clf))
            sink = _SnapshotSink()
            task = PipelineTask(Pipeline([gate, sink]), params=PipelineParams(allow_interruptions=True))
            ctx = LLMContext(messages=[{"role": "assistant", "content": "Where would you like to fly?"}])

            async def _drive() -> None:
                await asyncio.sleep(0.03)
                await task.queue_frame(VADUserStoppedSpeakingFrame())
                ctx.messages.append({"role": "user", "content": t1_text})
                await task.queue_frame(LLMContextFrame(context=ctx))
                await asyncio.wait_for(clf.first_started.wait(), timeout=2.0)
                await task.queue_frame(InterruptionFrame())
                await asyncio.sleep(0.01)
                ctx.messages.append({"role": "user", "content": t2_text})
                await task.queue_frame(LLMContextFrame(context=ctx))
                await asyncio.sleep(0.30)
                await task.queue_frame(EndFrame())

            await asyncio.gather(PipelineRunner(handle_sigint=False).run(task), _drive())
            return sink.snapshots, [(m["role"], m["content"]) for m in ctx.messages]

        # 1. Slow T1 (0.15s) + Fast T2 (0.02s), both addressed -> [assistant, T1, T2]
        snaps_slow_t1, final_slow_t1 = await _run_overlap_case(
            [(0.95, 0.15), (0.95, 0.02)],
            "Book me a flight to Mumbai",
            "for tomorrow morning",
        )
        expected_both = [
            ("assistant", "Where would you like to fly?"),
            ("user", "Book me a flight to Mumbai"),
            ("user", "for tomorrow morning"),
        ]
        self.assertEqual(final_slow_t1, expected_both)
        self.assertEqual(snaps_slow_t1[-1], expected_both)

        # 2. Fast T1 (0.04s) + Slow T2 (0.15s), both addressed -> [assistant, T1, T2]
        snaps_fast_t1, final_fast_t1 = await _run_overlap_case(
            [(0.95, 0.04), (0.95, 0.15)],
            "Book me a flight to Mumbai",
            "for tomorrow morning",
        )
        self.assertEqual(final_fast_t1, expected_both)
        self.assertEqual(snaps_fast_t1[-1], expected_both)

        # 3. Addressed T1 interrupted mid-eval by Ignored T2 -> LLM still receives [assistant, T1]!
        snaps_t1_ok_t2_bg, final_t1_ok_t2_bg = await _run_overlap_case(
            [(0.96, 0.12), (0.02, 0.02)],
            "What is my account balance?",
            "Breaking news on Channel 9!",
        )
        expected_t1_only = [
            ("assistant", "Where would you like to fly?"),
            ("user", "What is my account balance?"),
        ]
        self.assertGreaterEqual(len(snaps_t1_ok_t2_bg), 1, "Addressed Turn 1 must reach LLM!")
        self.assertEqual(snaps_t1_ok_t2_bg[-1], expected_t1_only)
        self.assertEqual(final_t1_ok_t2_bg, expected_t1_only)

    async def test_live_barge_in_delayed_server_interrupted_and_filler_races(self) -> None:
        """Verifies all 3 Gemini Live Silero-VAD barge-in invariants on CustomGeminiLiveLLMService."""
        from unittest.mock import AsyncMock, patch
        from pipecat.frames.frames import InterruptionFrame, LLMFullResponseEndFrame
        from pipecat.processors.frame_processor import FrameProcessor
        from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
        from processors.turn_telemetry import TurnBoundaryProcessor
        from turn_telemetry import TurnTracker

        pushed: list[tuple[Frame, FrameDirection]] = []

        async def _capture(proc, frame, direction=FrameDirection.DOWNSTREAM):
            pushed.append((frame, direction))

        def _live_msg(*, audio=None, transcript=None, user_transcript=None, turn_complete=False, interrupted=False):
            parts = []
            if audio is not None:
                parts.append(
                    SimpleNamespace(
                        text=None,
                        thought=None,
                        inline_data=SimpleNamespace(mime_type="audio/pcm;rate=24000", data=audio),
                    )
                )
            sc = SimpleNamespace(
                model_turn=SimpleNamespace(parts=parts) if parts else None,
                output_transcription=SimpleNamespace(text=transcript) if transcript else None,
                input_transcription=SimpleNamespace(text=user_transcript) if user_transcript else None,
                grounding_metadata=None,
                turn_complete=turn_complete,
                interrupted=interrupted,
            )
            return SimpleNamespace(server_content=sc, usage_metadata=None)

        with (
            patch.object(FrameProcessor, "push_frame", new=_capture),
            patch.object(FrameProcessor, "broadcast_interruption", new=AsyncMock()),
            patch.object(FrameProcessor, "stop_all_metrics", new=AsyncMock()),
        ):
            llm = agent_live.CustomGeminiLiveLLMService(api_key="dummy")
            llm._vad_disabled = True
            tracker = TurnTracker("s-live-race", "gemini-live", vad_stop_padding_ms=400)
            boundary = TurnBoundaryProcessor(tracker)
            llm._turn_tracker = tracker

            # --- Race A: Post-turn_complete WebAudio tail barge-in flushes browser & keeps flag False ---
            from pipecat.frames.frames import BotStartedSpeakingFrame, OutputTransportMessageFrame

            with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
                await llm.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
            await llm._handle_msg_output_transcription(_live_msg(transcript="Hello!"))
            await llm._handle_msg_model_turn(_live_msg(audio=b"\x01\x00" * 240))
            await llm._handle_msg_turn_complete(_live_msg(turn_complete=True))
            self.assertFalse(llm._mixin_bot_responding)
            self.assertTrue(llm._bot_playback_active)
            pushed.clear()
            with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
                await llm.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
            self.assertFalse(llm._awaiting_interrupted_turn_complete)
            tail_interrupts = [
                f
                for f, _ in pushed
                if isinstance(f, OutputTransportMessageUrgentFrame)
                and f.message.get("data", {}).get("payload", {}).get("type") == "interruption"
            ]
            self.assertEqual(len(tail_interrupts), 1, "Playback tail barge-in must flush browser WebAudio via UrgentFrame!")

            # --- Race B: Ignored mid-turn side-talk must disarm RepeatOnFiller ---
            await llm._handle_msg_output_transcription(_live_msg(transcript="Your balance is"))
            await llm._handle_msg_model_turn(_live_msg(audio=b"\x01\x00" * 240))
            with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
                await llm.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
            self.assertTrue(llm._repeat_on_filler_pending)
            llm.clear_pending_filler_after_ignored_turn()
            self.assertFalse(llm._repeat_on_filler_pending)
            await llm._handle_msg_turn_complete(_live_msg(turn_complete=True))

            llm._send_repeat_instruction = AsyncMock()
            await llm._handle_msg_input_transcription(_live_msg(user_transcript="Haan."))
            llm._send_repeat_instruction.assert_not_awaited()

            # --- Race C: Real caller barge-in with in-flight Turn-1 chunk + delayed server_content.interrupted ---
            pushed.clear()
            with patch.object(FrameProcessor, "process_frame", new=AsyncMock()):
                s1, e1 = VADUserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame()
                await boundary.process_frame(s1, FrameDirection.DOWNSTREAM)
                await boundary.process_frame(e1, FrameDirection.DOWNSTREAM)
            with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
                await llm.process_frame(e1, FrameDirection.DOWNSTREAM)
            turn1 = tracker.current

            await llm._handle_msg_output_transcription(_live_msg(transcript="Long Turn 1 reply"))
            await llm._handle_msg_model_turn(_live_msg(audio=b"\x01\x00" * 240))
            # 1. Local gate interrupts immediately at VAD start before ActivityStart is sent.
            with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
                await llm.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
            self.assertEqual(turn1.status, "interrupted")
            self.assertTrue(llm._awaiting_interrupted_turn_complete)

            # 2. Gate approves Turn 2 and flushes VADStart + VADStop while Turn 1 has not sent turn_complete yet.
            with patch.object(FrameProcessor, "process_frame", new=AsyncMock()):
                s2, e2 = VADUserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame()
                await boundary.process_frame(s2, FrameDirection.DOWNSTREAM)
                await boundary.process_frame(e2, FrameDirection.DOWNSTREAM)
            with (
                patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()),
                patch.object(GeminiLiveLLMService, "_handle_user_started_speaking", new=AsyncMock()),
                patch.object(GeminiLiveLLMService, "_handle_user_stopped_speaking", new=AsyncMock()),
            ):
                await llm.process_frame(s2, FrameDirection.DOWNSTREAM)
                await llm.process_frame(e2, FrameDirection.DOWNSTREAM)
            turn2 = tracker.current
            self.assertEqual(turn2.turn_id, 2)
            # Must STILL mute stale Turn-1 chunks until Turn 1's turn_complete arrives!
            self.assertTrue(llm._awaiting_interrupted_turn_complete)

            pushed_before_stale = len(pushed)
            await llm._handle_msg_output_transcription(_live_msg(transcript=" leaked stale tail"))
            await llm._handle_msg_model_turn(_live_msg(audio=b"\x02\x00" * 240))
            self.assertEqual(len(pushed), pushed_before_stale, "Stale Turn-1 chunks must not leak!")

            # 3. Gemini processes ActivityStart and sends delayed server_content.interrupted
            # WITHOUT turn_complete (or with deferred IN_PROGRESS turn_complete on 3.8 extended thinking).
            await llm.broadcast_interruption()
            llm._defer_turn_complete_until_idle(_live_msg(turn_complete=True, interrupted=True))
            self.assertIsNone(llm._turn_complete_pending_idle)
            self.assertFalse(llm._awaiting_interrupted_turn_complete)
            self.assertIsNone(turn2.status, "Delayed Turn-1 interrupted echo must NOT abort Turn 2!")

            # 4. Turn 2 output arrives immediately (even without Turn-1 turn_complete) and completes cleanly.
            await llm._handle_msg_input_transcription(_live_msg(user_transcript="Switch to Friday."))
            await llm._handle_msg_output_transcription(_live_msg(transcript="Switched to Friday."))
            await llm._handle_msg_model_turn(_live_msg(audio=b"\x03\x00" * 240))
            await llm._handle_msg_turn_complete(_live_msg(turn_complete=True))
            end_frames = [f for f, _ in pushed if isinstance(f, LLMFullResponseEndFrame)]
            self.assertEqual(len(end_frames), 1)

    async def test_live_urgent_interruption_survives_trailing_interruption_frame_past_queued_tts(self) -> None:
        """Real PipelineTask test proving UrgentFrame(interruption) is NOT wiped by InterruptionFrame."""
        from pipecat.frames.frames import InterruptionFrame, TTSAudioRawFrame
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.runner import PipelineRunner
        from pipecat.pipeline.task import PipelineParams, PipelineTask
        from pipecat.processors.frame_processor import FrameProcessor

        class _SlowOutputSink(FrameProcessor):
            def __init__(self) -> None:
                super().__init__()
                self.urgent_interruptions: list[dict[str, Any]] = []

            async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
                await super().process_frame(frame, direction)
                if isinstance(frame, TTSAudioRawFrame):
                    await asyncio.sleep(0.15)
                elif isinstance(frame, OutputTransportMessageUrgentFrame):
                    if frame.message.get("data", {}).get("payload", {}).get("type") == "interruption":
                        self.urgent_interruptions.append(frame.message["data"]["payload"])
                await self.push_frame(frame, direction)

        class _PassThroughBase(FrameProcessor):
            async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
                await super().process_frame(frame, direction)
                await self.push_frame(frame, direction)

        class _FakeLiveService(agent_live.GeminiSessionLoggerMixin, _PassThroughBase):
            def __init__(self) -> None:
                super().__init__()
                self._mixin_bot_responding = True
                self._response_started_at = 1.0

        svc = _FakeLiveService()
        sink = _SlowOutputSink()
        task = PipelineTask(Pipeline([svc, sink]), params=PipelineParams(allow_interruptions=True))

        async def _drive() -> None:
            try:
                await asyncio.sleep(0.03)
                # Queue slow TTS audio frames so DataFrame queue is busy, then send InterruptionFrame.
                for _ in range(4):
                    await task.queue_frame(TTSAudioRawFrame(audio=b"\x01\x00" * 240, sample_rate=24000, num_channels=1))
                await asyncio.sleep(0.02)
                await task.queue_frame(InterruptionFrame())
                await asyncio.sleep(0.08)
                await task.queue_frame(EndFrame())
            except Exception:
                await task.cancel()
                raise

        await asyncio.gather(PipelineRunner(handle_sigint=False).run(task), _drive())
        self.assertEqual(len(sink.urgent_interruptions), 1)

    async def test_r3_cascade_delayed_stt_and_aggregator_append_race_and_utterance_fifo(self) -> None:
        """Covers Round 3 probes: delayed T2 >1s after VADStop, append-before-dequeue race, & utt_id FIFO."""
        from pipecat.frames.frames import InterruptionFrame
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.runner import PipelineRunner
        from pipecat.pipeline.task import PipelineParams, PipelineTask
        from pipecat.processors.aggregators.llm_context import LLMContext
        from pipecat.processors.frame_processor import FrameProcessor

        class _Sink(FrameProcessor):
            def __init__(self) -> None:
                super().__init__()
                self.llm_calls: list[list[str]] = []
                self.gate_events: list[dict[str, Any]] = []

            async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
                await super().process_frame(frame, direction)
                if isinstance(frame, LLMContextFrame):
                    self.llm_calls.append([m["content"] for m in frame.context.messages])
                elif isinstance(frame, OutputTransportMessageUrgentFrame):
                    data = frame.message.get("data", {})
                    if data.get("type") == "background_gate":
                        self.gate_events.append(data)
                await self.push_frame(frame, direction)

        class _EnteredClassifier(_StubDecisionsClassifier):
            def __init__(self, delay_secs: float) -> None:
                super().__init__(probability=0.95, delay_secs=delay_secs)
                self.first_entered = asyncio.Event()

            async def _ask(self, state, questions, inputs=()):
                if not self.calls:
                    self.first_entered.set()
                return await super()._ask(state, questions, inputs=inputs)

        # 1. T1 cancelled -> T2 VADStart/VADStop -> T2 STT/Aggregator lands 1.0s later -> ONLY 1 LLM call!
        clf_a = _EnteredClassifier(delay_secs=0.20)
        gate_a = CascadeBackgroundSpeechGate(BackgroundSpeechEvaluator(enabled=True, classifier=clf_a))
        sink_a = _Sink()
        task_a = PipelineTask(Pipeline([gate_a, sink_a]), params=PipelineParams(allow_interruptions=True))
        ctx_a = LLMContext(messages=[{"role": "assistant", "content": "A0"}])

        async def _drive_a() -> None:
            try:
                await asyncio.sleep(0.03)
                await task_a.queue_frame(VADUserStartedSpeakingFrame())
                await task_a.queue_frame(VADUserStoppedSpeakingFrame())
                await task_a.queue_frame(UserStoppedSpeakingFrame())
                ctx_a.messages.append({"role": "user", "content": "T1"})
                await task_a.queue_frame(LLMContextFrame(context=ctx_a))
                await asyncio.wait_for(clf_a.first_entered.wait(), timeout=2.0)
                # T2 starts and VAD-stops quickly, but aggregator/STT takes 1.0s!
                await task_a.queue_frame(InterruptionFrame())
                await task_a.queue_frame(VADUserStartedSpeakingFrame())
                await task_a.queue_frame(VADUserStoppedSpeakingFrame())
                await asyncio.sleep(1.0)
                await task_a.queue_frame(UserStoppedSpeakingFrame())
                ctx_a.messages.append({"role": "user", "content": "T2"})
                await task_a.queue_frame(LLMContextFrame(context=ctx_a))
                await asyncio.sleep(0.30)
                await task_a.queue_frame(EndFrame())
            except Exception:
                await task_a.cancel()
                raise

        await asyncio.gather(PipelineRunner(handle_sigint=False).run(task_a), _drive_a())
        self.assertEqual(sink_a.llm_calls, [["A0", "T1", "T2"]])

        # 2. Aggregator appends T2 BEFORE T1's background settle commits, AND before T2 frame is dequeued!
        clf_b = _EnteredClassifier(delay_secs=0.12)
        utt_ref = [1]
        gate_b = CascadeBackgroundSpeechGate(
            BackgroundSpeechEvaluator(enabled=True, classifier=clf_b),
            get_current_utterance_id=lambda: utt_ref[0],
        )
        sink_b = _Sink()
        task_b = PipelineTask(Pipeline([gate_b, sink_b]), params=PipelineParams(allow_interruptions=True))
        ctx_b = LLMContext(messages=[{"role": "assistant", "content": "A0"}])

        async def _drive_b() -> None:
            try:
                await asyncio.sleep(0.03)
                utt_ref[0] = 1
                await task_b.queue_frame(VADUserStartedSpeakingFrame())
                await task_b.queue_frame(VADUserStoppedSpeakingFrame())
                await task_b.queue_frame(UserStoppedSpeakingFrame())
                ctx_b.messages.append({"role": "user", "content": "T1"})
                await task_b.queue_frame(LLMContextFrame(context=ctx_b))
                await asyncio.wait_for(clf_b.first_entered.wait(), timeout=2.0)
                await task_b.queue_frame(InterruptionFrame())
                # T2 VAD completes (utt_id=2) and T2 is appended to ctx_b BEFORE T1 settles!
                utt_ref[0] = 2
                await task_b.queue_frame(VADUserStartedSpeakingFrame())
                await task_b.queue_frame(VADUserStoppedSpeakingFrame())
                ctx_b.messages.append({"role": "user", "content": "T2"})
                await asyncio.sleep(0.18)  # Let T1 settle while T2 is already in ctx_b.messages!
                await task_b.queue_frame(UserStoppedSpeakingFrame())
                await task_b.queue_frame(LLMContextFrame(context=ctx_b))
                await asyncio.sleep(0.20)
                await task_b.queue_frame(EndFrame())
            except Exception:
                await task_b.cancel()
                raise

        await asyncio.gather(PipelineRunner(handle_sigint=False).run(task_b), _drive_b())
        self.assertEqual(sink_b.llm_calls, [["A0", "T1", "T2"]])
        self.assertEqual([e.get("utterance_id") for e in sink_b.gate_events], [1, 2])

    async def test_emotion_observer_disabled_still_records_utterance_audio_when_requested(self) -> None:
        from processors.emotion_perception import AudioEmotionObserver

        obs = AudioEmotionObserver(enabled=False, record_utterance_audio=True)
        obs.push_frame = lambda f, d=FrameDirection.DOWNSTREAM: asyncio.sleep(0)
        await obs.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await obs.process_frame(
            InputAudioRawFrame(audio=_pcm_chunk(0.50), sample_rate=16000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await obs.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.0), FrameDirection.DOWNSTREAM)
        pcm, sr = obs.get_last_utterance_audio()
        self.assertIsNotNone(pcm)
        self.assertEqual(len(pcm), len(_pcm_chunk(0.50)))
        self.assertEqual(sr, 16000)

    async def test_r2_skip_stt_audio_message_does_not_leak_synthetic_prompt_as_transcript(self) -> None:
        stub = _StubDecisionsClassifier(probability=0.05)
        gate = CascadeBackgroundSpeechGate(
            BackgroundSpeechEvaluator(enabled=True, classifier=stub),
            get_recent_audio=lambda: (_pcm_chunk(0.50), 16000),
        )
        skip_stt_ctx = SimpleNamespace(
            messages=[
                {"role": "assistant", "content": "How can I assist?"},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Listen carefully to the user's spoken audio and directly answer or respond to what they just said before continuing:",
                        },
                        {"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}},
                    ],
                },
            ]
        )
        await self._run_cascade_capture(
            gate,
            [VADUserStoppedSpeakingFrame(), LLMContextFrame(context=skip_stt_ctx)],
        )
        self.assertEqual(len(stub.calls), 1)
        self.assertNotIn("Listen carefully", stub.calls[0]["state"])
        self.assertEqual(len(stub.calls[0]["inputs"]), 1)

    async def test_r3_emotion_observer_never_pairs_short_reply_with_previous_turn_audio(self) -> None:
        from processors.emotion_perception import AudioEmotionObserver

        obs = AudioEmotionObserver(enabled=True, api_key="fake-key", classifier=_StubDecisionsClassifier())
        obs.push_frame = lambda f, d=FrameDirection.DOWNSTREAM: asyncio.sleep(0)

        # Turn 1: 0.6s utterance completes and populates _last_raw_utterance_audio.
        await obs.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await obs.process_frame(
            InputAudioRawFrame(audio=_pcm_chunk(0.60), sample_rate=16000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await obs.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.0), FrameDirection.DOWNSTREAM)
        audio_t1, _ = obs.get_last_utterance_audio()
        self.assertIsNotNone(audio_t1)
        self.assertEqual(len(audio_t1), len(_pcm_chunk(0.60)))

        # Turn 2: very short 0.10s "haan" (< MIN_FINAL_SECS=0.25s) must return None, NOT Turn 1's audio.
        await obs.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await obs.process_frame(
            InputAudioRawFrame(audio=_pcm_chunk(0.10), sample_rate=16000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await obs.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.0), FrameDirection.DOWNSTREAM)
        audio_t2, _ = obs.get_last_utterance_audio()
        self.assertIsNone(audio_t2)

    async def test_r4_live_gate_before_turn_boundary_prevents_phantom_turns_and_preserves_vad_stop_ts(self) -> None:
        from processors.turn_telemetry import TurnBoundaryProcessor
        from turn_telemetry import TurnTracker

        tracker = TurnTracker("s-r4", "gemini-live", vad_stop_padding_ms=400)
        boundary = TurnBoundaryProcessor(tracker)
        boundary.push_frame = lambda f, d=FrameDirection.DOWNSTREAM: asyncio.sleep(0)

        # 1. Ignored background turn never reaches TurnBoundaryProcessor.
        stub_bg = _StubDecisionsClassifier(probability=0.04)
        gate_bg = LiveBackgroundSpeechGate(BackgroundSpeechEvaluator(enabled=True, classifier=stub_bg))
        gate_bg.push_frame = lambda f, d=FrameDirection.DOWNSTREAM: boundary.process_frame(f, d)

        await gate_bg.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate_bg.process_frame(
            InputAudioRawFrame(audio=_pcm_chunk(0.50), sample_rate=16000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await gate_bg.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.2), FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.current.turn_id, 0)
        self.assertIsNone(tracker.current.status)

        # 2. Approved turn with 0.15s classifier delay stamps vad_stop BEFORE the delay.
        stub_ok = _StubDecisionsClassifier(probability=0.95, delay_secs=0.15)
        gate_ok = LiveBackgroundSpeechGate(BackgroundSpeechEvaluator(enabled=True, classifier=stub_ok))
        gate_ok.push_frame = lambda f, d=FrameDirection.DOWNSTREAM: boundary.process_frame(f, d)

        await gate_ok.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate_ok.process_frame(
            InputAudioRawFrame(audio=_pcm_chunk(0.50), sample_rate=16000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        import time as _time

        t_before_stop = _time.monotonic()
        await gate_ok.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.2), FrameDirection.DOWNSTREAM)
        t_after_stop = _time.monotonic()
        self.assertEqual(tracker.current.turn_id, 1)
        self.assertIsNotNone(tracker.current.vad_stop)
        # vad_stop must be captured before the 150ms classifier sleep.
        self.assertLess(tracker.current.vad_stop, t_after_stop - 0.10)
        self.assertGreaterEqual(tracker.current.vad_stop, t_before_stop - 0.05)

    def test_coalesce_audio_frames_merges_small_chunks(self) -> None:
        frames = [
            InputAudioRawFrame(audio=_pcm_chunk(0.02), sample_rate=16000, num_channels=1)
            for _ in range(10)
        ]
        frames[0].metadata["turn_id"] = 7
        merged = _coalesce_audio_frames(frames, chunk_ms=100)
        self.assertEqual(len(merged), 2)
        self.assertEqual(sum(len(f.audio) for f in merged), len(_pcm_chunk(0.20)))
        self.assertEqual(merged[0].metadata.get("turn_id"), 7)


if __name__ == "__main__":
    unittest.main()
