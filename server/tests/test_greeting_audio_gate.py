import sys, os
server_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)
import unittest
import asyncio
import time
import numpy as np
from collections import deque

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    BotStoppedSpeakingFrame,
    TTSStoppedFrame,
    InputTransportMessageFrame,
    LLMMessagesAppendFrame,
    LLMRunFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from agent_live import StartTriggerProcessor


class TestGreetingAudioGate(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pushed_frames = []
        self.interruption_count = 0

    def _make_processor(self, gate_mic_on_greeting: bool = True):
        processor = StartTriggerProcessor(
            language="en-US",
            gate_mic_on_greeting=gate_mic_on_greeting,
        )

        async def mock_push_frame(frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
            self.pushed_frames.append((frame, direction))

        async def mock_broadcast_interruption():
            self.interruption_count += 1

        processor.push_frame = mock_push_frame
        processor.broadcast_interruption = mock_broadcast_interruption
        return processor

    def _make_audio_frame(self, rms_amplitude: float, duration_ms: int = 20):
        num_samples = int(16 * duration_ms)
        if rms_amplitude <= 0:
            samples = np.zeros(num_samples, dtype=np.int16)
        else:
            peak = min(32767.0, rms_amplitude * np.sqrt(2.0))
            t = np.linspace(0, duration_ms / 1000.0, num_samples, endpoint=False)
            samples = (np.sin(2 * np.pi * 300 * t) * peak).astype(np.int16)
        return InputAudioRawFrame(
            audio=samples.tobytes(),
            num_channels=1,
            sample_rate=16000,
        )

    async def test_silence_suppressed_when_gated(self):
        processor = self._make_processor(gate_mic_on_greeting=True)
        self.assertTrue(processor._mic_gated)

        ambient_frame = self._make_audio_frame(rms_amplitude=150.0)
        for _ in range(5):
            await processor.process_frame(ambient_frame, FrameDirection.DOWNSTREAM)

        audio_pushed = [f for f, d in self.pushed_frames if isinstance(f, InputAudioRawFrame)]
        self.assertEqual(len(audio_pushed), 0)
        self.assertTrue(processor._mic_gated)

    async def test_normal_greeting_completion_via_bot_stopped_speaking(self):
        processor = self._make_processor(gate_mic_on_greeting=True)
        self.assertTrue(processor._mic_gated)

        bot_stop = BotStoppedSpeakingFrame()
        await processor.process_frame(bot_stop, FrameDirection.UPSTREAM)

        self.assertFalse(processor._mic_gated)

        ambient_frame = self._make_audio_frame(rms_amplitude=150.0)
        await processor.process_frame(ambient_frame, FrameDirection.DOWNSTREAM)

        audio_pushed = [f for f, d in self.pushed_frames if isinstance(f, InputAudioRawFrame)]
        self.assertEqual(len(audio_pushed), 1)

    async def test_normal_greeting_completion_via_tts_stopped(self):
        processor = self._make_processor(gate_mic_on_greeting=True)
        self.assertTrue(processor._mic_gated)

        tts_stop = TTSStoppedFrame()
        await processor.process_frame(tts_stop, FrameDirection.DOWNSTREAM)

        self.assertFalse(processor._mic_gated)

    async def test_voice_barge_in_triggers_interruption_and_flushes_prebuffer(self):
        processor = self._make_processor(gate_mic_on_greeting=True)
        self.assertTrue(processor._mic_gated)

        silence_frame = self._make_audio_frame(rms_amplitude=50.0)
        for _ in range(3):
            await processor.process_frame(silence_frame, FrameDirection.DOWNSTREAM)

        self.assertEqual(len(self.pushed_frames), 0)
        self.assertEqual(self.interruption_count, 0)

        voice_frame_1 = self._make_audio_frame(rms_amplitude=2500.0)
        voice_frame_2 = self._make_audio_frame(rms_amplitude=3000.0)

        await processor.process_frame(voice_frame_1, FrameDirection.DOWNSTREAM)
        self.assertEqual(self.interruption_count, 0)

        await processor.process_frame(voice_frame_2, FrameDirection.DOWNSTREAM)

        self.assertEqual(self.interruption_count, 1)
        self.assertFalse(processor._mic_gated)

        audio_pushed = [f for f, d in self.pushed_frames if isinstance(f, InputAudioRawFrame)]
        self.assertGreaterEqual(len(audio_pushed), 2)

    async def test_passthrough_when_gate_mic_disabled(self):
        processor = self._make_processor(gate_mic_on_greeting=False)
        self.assertFalse(processor._mic_gated)

        frame = self._make_audio_frame(rms_amplitude=100.0)
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        audio_pushed = [f for f, d in self.pushed_frames if isinstance(f, InputAudioRawFrame)]
        self.assertEqual(len(audio_pushed), 1)

    async def test_watchdog_timeout_opens_gate(self):
        processor = self._make_processor(gate_mic_on_greeting=True)
        processor._gate_start_time = time.monotonic() - 15.0

        frame = self._make_audio_frame(rms_amplitude=50.0)
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        self.assertFalse(processor._mic_gated)

    async def test_hindi_start_trigger_uses_namaste_greeting(self):
        processor = StartTriggerProcessor(language="hi-IN", gate_mic_on_greeting=True)
        pushed = []

        async def capture(frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
            pushed.append(frame)

        processor.push_frame = capture
        await processor.process_frame(
            InputTransportMessageFrame(message={"type": "start_trigger", "id": "t1"}),
            FrameDirection.DOWNSTREAM,
        )
        append_frames = [f for f in pushed if isinstance(f, LLMMessagesAppendFrame)]
        self.assertEqual(len(append_frames), 1)
        self.assertEqual(append_frames[0].messages, [{"role": "user", "content": "नमस्ते!"}])

    def test_create_client_does_not_mutate_os_environ(self):
        from unittest.mock import patch
        from agent_live import CustomGeminiLiveLLMService

        svc = CustomGeminiLiveLLMService.__new__(CustomGeminiLiveLLMService)
        svc._api_key = "dummy-key"
        svc._http_options = None

        observed_env = {}

        def fake_client(**kwargs):
            observed_env["GOOGLE_CLOUD_PROJECT"] = os.environ.get("GOOGLE_CLOUD_PROJECT")
            observed_env["GOOGLE_APPLICATION_CREDENTIALS"] = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            return object()

        with patch.dict(
            os.environ,
            {"GOOGLE_CLOUD_PROJECT": "my-gcp-proj", "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/creds.json"},
            clear=False,
        ), patch("google.genai.Client", side_effect=fake_client):
            svc.create_client()

        self.assertEqual(observed_env["GOOGLE_CLOUD_PROJECT"], "my-gcp-proj")
        self.assertEqual(observed_env["GOOGLE_APPLICATION_CREDENTIALS"], "/tmp/creds.json")


if __name__ == "__main__":
    unittest.main()
