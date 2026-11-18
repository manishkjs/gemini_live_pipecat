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
                self.entered = asyncio.Event()
                self.probs = [0.03, 0.96]  # 1st = TV noise (ignore), 2nd = real caller (respond)

            async def _ask(self, state, questions, inputs=()):
                idx = len(self.calls)
                self.calls.append({"state": state})
                if idx == 0:
                    self.entered.set()
                    await asyncio.sleep(0.12)
                prob = self.probs[min(idx, len(self.probs) - 1)]
                return (
                    {name: YesNoResult(probability=prob) for name in questions},
                    LLMTokenUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
                )

        tracker = TurnTracker("s-cancel", "tts-llm-stt", vad_stop_padding_ms=400)
        tracker.current.vad_start = 1.0
        tracker.current.vad_stop = 1.5
        stub = _ScriptedClassifier()
        gate = CascadeBackgroundSpeechGate(
            BackgroundSpeechEvaluator(enabled=True, classifier=stub),
            on_ignored_turn=tracker.mark_ignored,
        )
        sink = _Sink()
        pipeline = Pipeline([gate, sink])
        task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))

        ctx = LLMContext(
            messages=[
                {"role": "assistant", "content": "How can I help you today?"},
            ]
        )

        async def _drive() -> None:
            await asyncio.sleep(0.05)
            await task.queue_frame(VADUserStoppedSpeakingFrame())
            # Turn 1: TV speech enters gate.process_frame(LLMContextFrame) and blocks in evaluate().
            ctx.messages.append({"role": "user", "content": "Buy crispy chips on Channel 5!"})
            await task.queue_frame(LLMContextFrame(context=ctx))
            await asyncio.wait_for(stub.entered.wait(), timeout=2.0)
            # Mid-evaluation InterruptionFrame cancels Pipecat's __process_frame_task!
            await task.queue_frame(InterruptionFrame())
            await asyncio.sleep(0.18)
            # Ignored TV message MUST NOT remain in ctx.messages, and Turn 1 is marked ignored.
            self.assertEqual(
                [(m["role"], m["content"]) for m in ctx.messages],
                [("assistant", "How can I help you today?")],
            )
            self.assertEqual(tracker.current.status, "ignored")

            # Turn 2: Real caller utterance passes cleanly through the same gate.
            ctx.messages.append({"role": "user", "content": "Book a car service for Friday."})
            await task.queue_frame(LLMContextFrame(context=ctx))
            await asyncio.sleep(0.08)
            await task.queue_frame(EndFrame())

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

            # --- Race A: Post-turn_complete tail barge-in must NOT stick _awaiting_interrupted_turn_complete ---
            await llm._handle_msg_output_transcription(_live_msg(transcript="Hello!"))
            await llm._handle_msg_model_turn(_live_msg(audio=b"\x01\x00" * 240))
            await llm._handle_msg_turn_complete(_live_msg(turn_complete=True))
            self.assertFalse(llm._mixin_bot_responding)
            with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
                await llm.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
            self.assertFalse(llm._awaiting_interrupted_turn_complete)

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

            # 3. Gemini processes ActivityStart and sends delayed server_content.interrupted + Turn-1 turn_complete.
            await llm.broadcast_interruption()
            await llm._handle_msg_turn_complete(_live_msg(turn_complete=True))
            self.assertFalse(llm._awaiting_interrupted_turn_complete)
            self.assertIsNone(turn2.status, "Delayed Turn-1 interrupted echo must NOT abort Turn 2!")

            # 4. Turn 2 output arrives and completes cleanly.
            await llm._handle_msg_input_transcription(_live_msg(user_transcript="Switch to Friday."))
            await llm._handle_msg_output_transcription(_live_msg(transcript="Switched to Friday."))
            await llm._handle_msg_model_turn(_live_msg(audio=b"\x03\x00" * 240))
            await llm._handle_msg_turn_complete(_live_msg(turn_complete=True))
            end_frames = [f for f, _ in pushed if isinstance(f, LLMFullResponseEndFrame)]
            self.assertEqual(len(end_frames), 1)

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
