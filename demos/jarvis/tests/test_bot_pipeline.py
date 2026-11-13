"""Unit tests for Jarvis non-blocking Gemini Live tools, echo-guard, and UI taps."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai.types import FunctionResponseScheduling  # noqa: E402
from pipecat.frames.frames import (  # noqa: E402
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InputAudioRawFrame,
    LLMTextFrame,
    OutputAudioRawFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection  # noqa: E402

import bot  # noqa: E402


class _FakeUi:

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def request_approval(self, action: str, reason: str) -> bool:
        return True


class _FakeSession:

    def __init__(self) -> None:
        self.responses: list[Any] = []

    async def send_tool_response(self, *, function_responses: Any) -> None:
        self.responses.append(function_responses)


class EchoGuardTest(unittest.IsolatedAsyncioTestCase):

    def test_auto_enables_for_speakers_and_disables_for_isolated_outputs(self):
        self.assertEqual(
            bot.resolve_echo_guard_enabled("auto", "MacBook Air Speakers"),
            (True, "MacBook Air Speakers"),
        )
        self.assertEqual(
            bot.resolve_echo_guard_enabled("auto", "External Headphones"),
            (False, "External Headphones"),
        )
        self.assertEqual(
            bot.resolve_echo_guard_enabled("auto", "Manish's AirPods Pro"),
            (False, "Manish's AirPods Pro"),
        )
        self.assertEqual(
            bot.resolve_echo_guard_enabled("auto", "BlackHole 16ch"),
            (False, "BlackHole 16ch"),
        )
        self.assertEqual(
            bot.resolve_echo_guard_enabled("off", "MacBook Air Speakers"),
            (False, "MacBook Air Speakers"),
        )
        self.assertEqual(
            bot.resolve_echo_guard_enabled("on", "External Headphones"),
            (True, "External Headphones"),
        )

    async def test_speaker_echo_guard_silences_mic_during_speech_and_tail(self):
        now = 100.0
        state = bot._EchoGuardState(
            enabled=True, pre_roll_seconds=0.5, tail_seconds=0.6, clock=lambda: now
        )
        guard = bot._SpeakerEchoGuard(state)
        pushed: list[Any] = []

        async def capture(frame, direction):
            pushed.append((frame, direction))

        guard.push_frame = capture  # type: ignore[method-assign]

        loud = InputAudioRawFrame(audio=b"\x7f\x7f" * 160, sample_rate=16000, num_channels=1)
        await guard.process_frame(loud, FrameDirection.DOWNSTREAM)
        self.assertEqual(pushed[-1][0].audio, loud.audio)

        state.on_bot_started()
        await guard.process_frame(loud, FrameDirection.DOWNSTREAM)
        self.assertEqual(pushed[-1][0].audio, b"\x00" * len(loud.audio))

        now = 102.0
        state.on_bot_stopped()
        now = 102.3  # still inside 0.6s echo tail
        await guard.process_frame(loud, FrameDirection.DOWNSTREAM)
        self.assertEqual(pushed[-1][0].audio, b"\x00" * len(loud.audio))

        now = 102.7  # past echo tail
        await guard.process_frame(loud, FrameDirection.DOWNSTREAM)
        self.assertEqual(pushed[-1][0].audio, loud.audio)


class NonBlockingGeminiLiveTest(unittest.IsolatedAsyncioTestCase):

    async def test_enables_non_blocking_tools_and_when_idle_scheduling(self):
        llm = bot._NonBlockingGeminiLiveLLMService(
            api_key="test-key",
            settings=bot.GeminiLiveLLMService.Settings(model="models/gemini-3.8-live"),
        )
        self.assertTrue(llm._is_gemini_3)
        self.assertTrue(llm._supports_non_blocking_tools)

        async def dummy_tool(params):
            await params.result_callback({"status": "done"})

        llm.register_function("open_app", dummy_tool, cancel_on_interruption=False)
        fake_session = _FakeSession()
        llm._session = fake_session  # type: ignore[assignment]

        await llm._tool_result("call_1", "open_app", {"status": "done"})
        self.assertEqual(len(fake_session.responses), 1)
        resp = fake_session.responses[0]
        self.assertEqual(resp.id, "call_1")
        self.assertEqual(resp.name, "open_app")
        self.assertEqual(resp.response, {"status": "done"})
        self.assertEqual(resp.scheduling, FunctionResponseScheduling.WHEN_IDLE)


class OutputUiTapTest(unittest.IsolatedAsyncioTestCase):

    async def test_deduplicates_llm_and_tts_text_frames(self):
        ui = _FakeUi()
        tap = bot._OutputUiTap(ui)
        tap.push_frame = lambda frame, direction: asyncio.sleep(0)  # type: ignore[method-assign]

        await tap.process_frame(LLMTextFrame("Opening "), FrameDirection.DOWNSTREAM)
        await tap.process_frame(
            TTSTextFrame("Opening ", aggregated_by="sentence"), FrameDirection.DOWNSTREAM
        )
        await tap.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await tap.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)

        self.assertEqual(
            ui.events,
            [
                {"type": "bot_text", "text": "Opening "},
                {"type": "state", "state": "speaking"},
                {"type": "state", "state": "idle"},
            ],
        )

    async def test_pause_mutes_mic_and_suppresses_output_audio(self):
        control = bot.JarvisControl()
        state = bot._EchoGuardState(enabled=False)
        guard = bot._SpeakerEchoGuard(state, control)
        tap = bot._OutputUiTap(_FakeUi(), state, control)

        in_pushed: list[Any] = []
        out_pushed: list[Any] = []

        async def capture_in(frame, direction):
            in_pushed.append(frame)

        async def capture_out(frame, direction):
            out_pushed.append(frame)

        guard.push_frame = capture_in  # type: ignore[method-assign]
        tap.push_frame = capture_out  # type: ignore[method-assign]

        mic_frame = InputAudioRawFrame(audio=b"\x11\x22" * 80, sample_rate=16000, num_channels=1)
        spk_frame = OutputAudioRawFrame(audio=b"\x33\x44" * 80, sample_rate=24000, num_channels=1)

        control.set_paused(True)
        await guard.process_frame(mic_frame, FrameDirection.DOWNSTREAM)
        await tap.process_frame(spk_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(in_pushed[-1].audio, b"\x00" * len(mic_frame.audio))
        self.assertEqual(out_pushed, [])

        control.set_paused(False)
        await guard.process_frame(mic_frame, FrameDirection.DOWNSTREAM)
        await tap.process_frame(spk_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(in_pushed[-1].audio, mic_frame.audio)
        self.assertEqual(len(out_pushed), 1)


if __name__ == "__main__":
    unittest.main()
