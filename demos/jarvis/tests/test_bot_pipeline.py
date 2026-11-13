"""Unit tests for Jarvis non-blocking Gemini Live tools, echo-guard, and UI taps."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai.types import (  # noqa: E402
    EndSensitivity,
    FunctionResponseScheduling,
    StartSensitivity,
    TurnCoverage,
)
from pipecat.frames.frames import (  # noqa: E402
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InputAudioRawFrame,
    InterruptionFrame,
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

    async def test_pipecat_sends_when_idle_for_async_tools_on_3_8(self):
        llm = bot.GeminiLiveLLMService(
            api_key="test-key",
            settings=bot.GeminiLiveLLMService.Settings(model="models/gemini-3.8-live"),
        )
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
        self.assertEqual(resp.response["status"], "done")
        self.assertEqual(resp.scheduling, FunctionResponseScheduling.WHEN_IDLE)
        self.assertFalse(resp.will_continue)


class JarvisControlTest(unittest.IsolatedAsyncioTestCase):

    async def test_stop_actually_cancels_the_pipeline_task(self):
        class _Task:
            cancelled = False

            async def cancel(self, **kwargs):
                _Task.cancelled = True

        control = bot.JarvisControl()
        control.bind(asyncio.get_running_loop(), _Task())  # type: ignore[arg-type]
        control.stop()
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertTrue(_Task.cancelled)


class OutputUiTapTest(unittest.IsolatedAsyncioTestCase):

    async def test_deduplicates_llm_and_tts_text_frames(self):
        ui = _FakeUi()
        tap = bot._OutputUiTap(ui)
        tap.push_frame = lambda frame, direction: asyncio.sleep(0)  # type: ignore[method-assign]

        await tap.process_frame(LLMTextFrame("Opening "), FrameDirection.DOWNSTREAM)
        await tap.process_frame(
            TTSTextFrame("Opening ", text_type="sentence"), FrameDirection.DOWNSTREAM
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

    async def test_pause_keeps_ui_quiet(self):
        ui = _FakeUi()
        control = bot.JarvisControl()
        tap = bot._OutputUiTap(ui, None, control)
        tap.push_frame = lambda frame, direction: asyncio.sleep(0)  # type: ignore[method-assign]

        control.set_paused(True)
        await tap.process_frame(TTSTextFrame("hi", text_type="sentence"), FrameDirection.DOWNSTREAM)
        await tap.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        self.assertEqual(ui.events, [])


def _tone(amplitude: int, ms: int = 20, rate: int = 16000) -> InputAudioRawFrame:
    """A square-wave mic frame whose RMS equals `amplitude`."""
    import array

    n = rate * ms // 1000
    samples = array.array("h", [amplitude if i % 2 else -amplitude for i in range(n)])
    return InputAudioRawFrame(audio=samples.tobytes(), sample_rate=rate, num_channels=1)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class EchoModeTest(unittest.TestCase):

    def test_speakers_default_to_smart_barge_in(self):
        self.assertEqual(bot.resolve_echo_mode("auto", "MacBook Air Speakers")[0], "smart")
        self.assertEqual(bot.resolve_echo_mode("auto", "AirPods Pro")[0], "off")
        self.assertEqual(bot.resolve_echo_mode("on", "MacBook Air Speakers")[0], "mute")
        self.assertEqual(bot.resolve_echo_mode("mute", "AirPods Pro")[0], "mute")
        self.assertEqual(bot.resolve_echo_mode("smart", "AirPods Pro")[0], "smart")
        self.assertEqual(bot.resolve_echo_mode("off", "MacBook Air Speakers")[0], "off")


class BargeInDetectorTest(unittest.TestCase):

    def _detector(self, clock):
        return bot._BargeInDetector(
            ratio=2.0, min_rms=500, hold_seconds=0.1, warmup_seconds=0.2, clock=clock
        )

    def test_echo_alone_never_triggers(self):
        clock = _Clock()
        det = self._detector(clock)
        det.start_utterance()
        for i in range(150):  # 3 s of echo that swings between 600 and 1200 RMS
            clock.now += 0.02
            self.assertFalse(det.feed(_tone(1200 if i % 10 < 5 else 600)))

    def test_loud_sustained_speech_over_echo_triggers_and_keeps_preroll(self):
        clock = _Clock()
        det = self._detector(clock)
        det.start_utterance()
        for _ in range(20):  # learn ~1000 RMS of echo
            clock.now += 0.02
            det.feed(_tone(1000))
        fired = []
        for _ in range(8):  # user talks at 4x the echo
            clock.now += 0.02
            fired.append(det.feed(_tone(4000)))
        self.assertTrue(any(fired))
        self.assertFalse(fired[0])  # needs hold_seconds of speech, not one click
        preroll = det.drain()
        self.assertTrue(preroll)
        self.assertLessEqual(sum(len(f.audio) for f in preroll) / 32000, 0.52)

    def test_short_click_does_not_trigger(self):
        clock = _Clock()
        det = self._detector(clock)
        det.start_utterance()
        for _ in range(20):
            clock.now += 0.02
            det.feed(_tone(800))
        clock.now += 0.02
        self.assertFalse(det.feed(_tone(8000)))
        for _ in range(10):
            clock.now += 0.02
            self.assertFalse(det.feed(_tone(800)))

    def test_warmup_only_learns(self):
        clock = _Clock()
        det = self._detector(clock)
        det.start_utterance()
        for _ in range(5):  # 0.1 s < 0.2 s warmup, even if loud
            clock.now += 0.02
            self.assertFalse(det.feed(_tone(6000)))


class SmartBargeInPipelineTest(unittest.IsolatedAsyncioTestCase):

    async def test_barge_in_interrupts_forwards_speech_and_drops_stale_audio(self):
        clock = _Clock()
        state = bot._EchoGuardState(enabled=True, clock=clock, barge_in=True)
        det = bot._BargeInDetector(
            ratio=2.0, min_rms=500, hold_seconds=0.06, warmup_seconds=0.1, clock=clock
        )
        guard = bot._SpeakerEchoGuard(state, None, det)
        tap = bot._OutputUiTap(_FakeUi(), state)
        pushed: list[Any] = []
        out: list[Any] = []
        interrupts: list[int] = []

        async def capture(frame, direction):
            pushed.append(frame)

        async def capture_out(frame, direction):
            out.append(frame)

        async def fake_broadcast():
            interrupts.append(1)
            # The downstream copy of our own interruption reaches the output tap.
            await tap.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)

        guard.push_frame = capture  # type: ignore[method-assign]
        guard.broadcast_interruption = fake_broadcast  # type: ignore[method-assign]
        tap.push_frame = capture_out  # type: ignore[method-assign]

        await guard.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        for _ in range(10):  # echo only: mic silenced
            clock.now += 0.02
            await guard.process_frame(_tone(1000), FrameDirection.DOWNSTREAM)
        self.assertEqual(interrupts, [])
        self.assertTrue(all(not any(f.audio) for f in pushed if isinstance(f, InputAudioRawFrame)))

        pushed.clear()
        for _ in range(6):  # user talks over Jarvis
            clock.now += 0.02
            await guard.process_frame(_tone(5000), FrameDirection.DOWNSTREAM)
        self.assertEqual(interrupts, [1])
        self.assertTrue(any(any(f.audio) for f in pushed))  # real speech went through
        self.assertFalse(state.should_mute_mic())

        # Gemini keeps streaming the old reply for a moment: dropped.
        stale = OutputAudioRawFrame(audio=b"\x01\x02" * 80, sample_rate=24000, num_channels=1)
        await tap.process_frame(stale, FrameDirection.DOWNSTREAM)
        self.assertNotIn(stale, out)
        # Gemini's own "interrupted" arrives: new audio plays again.
        await tap.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        await tap.process_frame(stale, FrameDirection.DOWNSTREAM)
        self.assertIn(stale, out)

    async def test_suppression_expires_without_confirmation(self):
        clock = _Clock()
        state = bot._EchoGuardState(enabled=True, clock=clock, barge_in=True, suppress_seconds=1.0)
        state.on_local_barge_in()
        self.assertTrue(state.suppress_output())
        clock.now += 1.1
        self.assertFalse(state.suppress_output())

    async def test_mute_mode_has_no_barge_in(self):
        clock = _Clock()
        state = bot._EchoGuardState(enabled=True, clock=clock, barge_in=False)
        guard = bot._SpeakerEchoGuard(state, None, None)
        pushed: list[Any] = []

        async def capture(frame, direction):
            pushed.append(frame)

        guard.push_frame = capture  # type: ignore[method-assign]
        await guard.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        for _ in range(20):
            clock.now += 0.02
            await guard.process_frame(_tone(9000), FrameDirection.DOWNSTREAM)
        audio = [f for f in pushed if isinstance(f, InputAudioRawFrame)]
        self.assertTrue(audio and all(not any(f.audio) for f in audio))


class LiveSettingsTest(unittest.IsolatedAsyncioTestCase):

    def test_defaults_indian_english_vad_turn_coverage_and_compression(self):
        s = bot.build_live_settings("gemini-3.8-live", env={})
        self.assertEqual(s.model, "models/gemini-3.8-live")
        self.assertEqual(s.language, "en-IN")
        self.assertEqual(s.voice, "Charon")
        self.assertIn("Indian accent", s.system_instruction)
        self.assertEqual(s.vad.start_sensitivity, StartSensitivity.START_SENSITIVITY_LOW)
        self.assertEqual(s.vad.end_sensitivity, EndSensitivity.END_SENSITIVITY_LOW)
        self.assertEqual(s.vad.prefix_padding_ms, 200)
        self.assertEqual(s.vad.silence_duration_ms, 700)
        self.assertEqual(s.turn_coverage, TurnCoverage.TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO)
        self.assertTrue(s.context_window_compression.enabled)
        self.assertEqual(s.context_window_compression.trigger_tokens, 32_000)

    def test_env_overrides_language_and_voice(self):
        s = bot.build_live_settings("gemini-3.8-live", env={"JARVIS_LANGUAGE": "en-US", "JARVIS_VOICE": "Puck"})
        self.assertEqual(s.language, "en-US")
        self.assertEqual(s.voice, "Puck")
        self.assertNotIn("Indian accent", s.system_instruction)

    async def test_setup_sends_language_code_vad_and_turn_coverage(self):
        """Checks what Pipecat actually puts on the wire for these settings."""
        from unittest import mock

        llm = bot.GeminiLiveLLMService(
            api_key="test-key", settings=bot.build_live_settings("gemini-3.8-live", env={})
        )
        captured = {}

        async def record(config):
            captured["config"] = config

        with (
            mock.patch.object(llm, "_connection_task_handler", record),
            mock.patch.object(llm, "create_task", lambda coro, *a, **k: asyncio.ensure_future(coro)),
        ):
            await llm._connect()
            await asyncio.sleep(0)
        cfg = captured.get("config")
        if cfg is None:
            self.skipTest("Pipecat build path changed; config not captured")
        self.assertEqual(cfg.generation_config.speech_config.language_code, "en-IN")
        aad = cfg.realtime_input_config.automatic_activity_detection
        self.assertEqual(aad.start_of_speech_sensitivity, StartSensitivity.START_SENSITIVITY_LOW)
        self.assertEqual(aad.silence_duration_ms, 700)
        self.assertEqual(
            cfg.realtime_input_config.turn_coverage,
            TurnCoverage.TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO,
        )
        self.assertEqual(cfg.context_window_compression.trigger_tokens, 32_000)


class VocalToneTest(unittest.IsolatedAsyncioTestCase):

    async def test_dict_results_get_vocal_tone(self):
        got: list[Any] = []

        async def handler(params):
            await params.result_callback({"status": "done"})

        class _P:
            async def result_callback(self, result, **kwargs):
                got.append(result)

        p = _P()
        await bot.with_vocal_tone(handler, tone="T")(p)  # type: ignore[arg-type]
        self.assertEqual(got, [{"status": "done", "vocal_tone": "T"}])

    def test_accent_only_for_indian_locales(self):
        self.assertTrue(bot.accent_enabled("en-IN"))
        self.assertTrue(bot.accent_enabled("hi-in"))
        self.assertFalse(bot.accent_enabled("en-US"))


if __name__ == "__main__":
    unittest.main()
