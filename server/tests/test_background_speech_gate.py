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

    async def test_r1_cascade_defers_interruption_and_turn_boundaries_until_approved(self) -> None:
        from unittest.mock import AsyncMock

        from processors.audio_accumulator import AudioAccumulator
        from processors.turn_telemetry import TurnBoundaryProcessor
        from turn_telemetry import TurnTracker

        # 1. AudioAccumulator with defer_interruption=True must NOT interrupt on VAD start.
        acc_ctx = SimpleNamespace(messages=[])
        acc = AudioAccumulator(acc_ctx, project_id="test-proj", defer_interruption=True)
        acc.broadcast_interruption = AsyncMock()
        acc.push_frame = AsyncMock()
        await acc.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        acc.broadcast_interruption.assert_not_awaited()

        # 2. Ignored background turn in CascadeBackgroundSpeechGate must NOT interrupt or mint a TurnTracker turn.
        tracker = TurnTracker("s-r1", "tts-llm-stt", vad_stop_padding_ms=400)
        boundary = TurnBoundaryProcessor(tracker)
        boundary_out: list[Frame] = []

        async def _boundary_capture(frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
            boundary_out.append(frame)

        boundary.push_frame = _boundary_capture

        stub_ignore = _StubDecisionsClassifier(probability=0.05)
        gate_ignore = CascadeBackgroundSpeechGate(
            BackgroundSpeechEvaluator(enabled=True, classifier=stub_ignore),
            interrupt_on_respond=True,
            defer_turn_boundaries=True,
        )
        gate_ignore.broadcast_interruption = AsyncMock()
        gate_ignore.push_frame = lambda f, d=FrameDirection.DOWNSTREAM: boundary.process_frame(f, d)

        bg_ctx = SimpleNamespace(
            messages=[
                {"role": "assistant", "content": "Hello, how can I help?"},
                {"role": "user", "content": "TV commercial audio"},
            ]
        )
        await gate_ignore.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate_ignore.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate_ignore.process_frame(LLMContextFrame(context=bg_ctx), FrameDirection.DOWNSTREAM)

        gate_ignore.broadcast_interruption.assert_not_awaited()
        self.assertEqual(tracker.current.turn_id, 0)
        self.assertIsNone(tracker.current.status)

        # 3. Approved turn calls broadcast_interruption() and advances TurnTracker cleanly.
        stub_ok = _StubDecisionsClassifier(probability=0.95)
        gate_ok = CascadeBackgroundSpeechGate(
            BackgroundSpeechEvaluator(enabled=True, classifier=stub_ok),
            interrupt_on_respond=True,
            defer_turn_boundaries=True,
        )
        gate_ok.broadcast_interruption = AsyncMock()
        gate_ok.push_frame = lambda f, d=FrameDirection.DOWNSTREAM: boundary.process_frame(f, d)

        ok_ctx = SimpleNamespace(
            messages=[
                {"role": "assistant", "content": "Hello, how can I help?"},
                {"role": "user", "content": "Check my balance please"},
            ]
        )
        await gate_ok.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate_ok.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate_ok.process_frame(LLMContextFrame(context=ok_ctx), FrameDirection.DOWNSTREAM)

        gate_ok.broadcast_interruption.assert_awaited_once()
        self.assertEqual(tracker.current.turn_id, 1)
        self.assertIsNotNone(tracker.current.vad_stop)

    async def test_n1_cascade_barge_in_preserves_assistant_before_user_context_order(self) -> None:
        from unittest.mock import AsyncMock

        stub = _StubDecisionsClassifier(probability=0.96)
        gate = CascadeBackgroundSpeechGate(
            BackgroundSpeechEvaluator(enabled=True, classifier=stub),
            interrupt_on_respond=True,
            defer_turn_boundaries=True,
        )
        emitted: list[Frame] = []
        gate.push_frame = lambda f, d=FrameDirection.DOWNSTREAM: asyncio.sleep(0, result=emitted.append(f))

        ctx = SimpleNamespace(
            messages=[
                {"role": "assistant", "content": "Welcome to mutual fund advisory."},
                {"role": "user", "content": "Wait, switch to my SIP details."},
            ]
        )

        # Simulate an active assistant turn whose partial reply commits asynchronously
        # when broadcast_interruption() fires (mirroring LLMAssistantAggregator._handle_interruptions).
        gate.mark_assistant_turn_started()

        async def _fake_broadcast_interruption() -> None:
            async def _commit_partial() -> None:
                await asyncio.sleep(0.02)
                ctx.messages.append({"role": "assistant", "content": "Your portfolio value is..."})
                gate.mark_assistant_turn_stopped()

            asyncio.create_task(_commit_partial())

        gate.broadcast_interruption = AsyncMock(side_effect=_fake_broadcast_interruption)

        await gate.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate.process_frame(LLMContextFrame(context=ctx), FrameDirection.DOWNSTREAM)

        gate.broadcast_interruption.assert_awaited_once()
        # Context must end with [..., assistant(partial), user(new)], NEVER reversed.
        self.assertEqual(
            [(m["role"], m["content"]) for m in ctx.messages],
            [
                ("assistant", "Welcome to mutual fund advisory."),
                ("assistant", "Your portfolio value is..."),
                ("user", "Wait, switch to my SIP details."),
            ],
        )

        # When assistant is already idle, an approved turn must NOT call broadcast_interruption().
        gate.broadcast_interruption.reset_mock()
        ctx.messages.append({"role": "assistant", "content": "Your SIP is 5000."})
        ctx.messages.append({"role": "user", "content": "Great, thanks."})
        await gate.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate.process_frame(LLMContextFrame(context=ctx), FrameDirection.DOWNSTREAM)
        gate.broadcast_interruption.assert_not_awaited()

    async def test_n5_cascade_barge_in_interrupts_when_llm_done_but_bot_still_speaking(self) -> None:
        from unittest.mock import AsyncMock

        from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame

        stub = _StubDecisionsClassifier(probability=0.95)
        gate = CascadeBackgroundSpeechGate(
            BackgroundSpeechEvaluator(enabled=True, classifier=stub),
            interrupt_on_respond=True,
            defer_turn_boundaries=True,
        )
        gate.push_frame = AsyncMock()
        gate.broadcast_interruption = AsyncMock()

        # Assistant LLM finished (on_assistant_turn_stopped fired), but TTS audio is still playing.
        gate.mark_assistant_turn_started()
        gate.mark_assistant_turn_stopped()
        await gate.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)

        ctx = SimpleNamespace(
            messages=[
                {"role": "assistant", "content": "Here is the complete breakdown of your portfolio..."},
                {"role": "user", "content": "Stop, just tell me the total."},
            ]
        )
        await gate.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate.process_frame(LLMContextFrame(context=ctx), FrameDirection.DOWNSTREAM)

        gate.broadcast_interruption.assert_awaited_once()
        # Message order remains intact without unnecessary wait.
        self.assertEqual(ctx.messages[-1]["content"], "Stop, just tell me the total.")

        # Once BotStoppedSpeakingFrame arrives and LLM is idle, no interruption is broadcast.
        gate.broadcast_interruption.reset_mock()
        await gate.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        ctx.messages.append({"role": "assistant", "content": "Total is 5 lakhs."})
        ctx.messages.append({"role": "user", "content": "Thanks."})
        await gate.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await gate.process_frame(LLMContextFrame(context=ctx), FrameDirection.DOWNSTREAM)
        gate.broadcast_interruption.assert_not_awaited()

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
