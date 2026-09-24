import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import os
import sys

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from agent import CustomGeminiTranscribeLiveService
from pipecat.transcriptions.language import Language


class TestGeminiTranscribeLiveService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Test routing without real ADC, proxy configuration or provider clients.
        client_patch = patch("agent.genai.Client")
        self.client_factory = client_patch.start()
        self.addCleanup(client_patch.stop)

    def test_init_vertex_ai(self):
        service = CustomGeminiTranscribeLiveService(
            project_id="deep-clock-339817",
            location="us-central1",
            model="gemini-3.5-transcribe-live",
            languages=[Language("en-US"), Language("hi-IN")],
            is_ai_studio=False,
        )
        self.assertEqual(service.model_name, "gemini-3.5-transcribe-live-preview")
        self.assertFalse(service.is_ai_studio)
        self.client_factory.assert_called_once_with(vertexai=True, project="deep-clock-339817", location="us-central1")
        self.assertEqual(service.location, "us-central1")
        self.assertEqual(service.project_id, "deep-clock-339817")

    def test_init_ai_studio(self):
        service = CustomGeminiTranscribeLiveService(
            api_key="test_api_key",
            model="gemini-3.5-transcribe-live",
            languages=[Language("en-US")],
            is_ai_studio=True,
        )
        self.assertEqual(service.model_name, "gemini-3.5-transcribe-live")
        self.assertTrue(service.is_ai_studio)
        self.client_factory.assert_called_once_with(api_key="test_api_key")

    def test_init_ai_studio_suffix_clean(self):
        service = CustomGeminiTranscribeLiveService(
            api_key="test_api_key",
            model="gemini-3.5-transcribe-live-aistudio",
            languages=[Language("en-US")],
            is_ai_studio=True,
        )
        self.assertEqual(service.model_name, "gemini-3.5-transcribe-live")
        self.assertTrue(service.is_ai_studio)
        self.client_factory.assert_called_once_with(api_key="test_api_key")


class TestTranscribeLiveFinals(unittest.IsolatedAsyncioTestCase):
    """Live probe (2026-09-24): `input_transcription` is one FINAL per utterance, not a
    cumulative prefix, and `finished`/`turn_complete` are never set. Saying the same
    thing twice yields two identical finals, and both are real user turns."""

    def _service(self, receive_factory):
        client_patch = patch("agent.genai.Client")
        client_factory = client_patch.start()
        self.addCleanup(client_patch.stop)
        service = CustomGeminiTranscribeLiveService(
            api_key="k", model="gemini-3.5-transcribe-live", languages=[Language("en-US")], is_ai_studio=True,
        )
        session = MagicMock()
        session.receive = receive_factory(service)
        session.send_realtime_input = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        service._client.aio.live.connect = MagicMock(return_value=ctx)
        self.finals = []

        async def push_frame(frame, direction=None):
            from pipecat.frames.frames import TranscriptionFrame
            if type(frame) is TranscriptionFrame:
                self.finals.append(frame.text)

        service.push_frame = push_frame
        service._handle_transcription = AsyncMock()
        return service

    @staticmethod
    def _scripted(finals):
        from google.genai import types

        def factory(service):
            calls = {"n": 0}

            async def receive():
                calls["n"] += 1
                if calls["n"] == 1:
                    for text in finals:
                        yield types.LiveServerMessage(server_content=types.LiveServerContent(
                            input_transcription=types.Transcription(text=text)))
                else:
                    service._stopping = True
            return receive
        return factory

    async def test_repeated_identical_utterance_is_not_dropped(self):
        service = self._service(self._scripted(["Yes.", "Yes."]))
        await asyncio.wait_for(service._streaming_worker(), timeout=2)
        self.assertEqual(self.finals, ["Yes.", "Yes."])

    async def test_back_to_back_finals_are_each_delivered_immediately(self):
        service = self._service(self._scripted(["I want a test drive.", "Tomorrow at five."]))
        await asyncio.wait_for(service._streaming_worker(), timeout=2)
        # Checked right after the worker returns: no debounce delay, nothing overwritten.
        self.assertEqual(self.finals, ["I want a test drive.", "Tomorrow at five."])

    async def test_cancelling_worker_cancels_its_child_tasks(self):
        def factory(service):
            async def receive():
                await asyncio.Event().wait()
                yield None  # pragma: no cover
            return receive

        service = self._service(factory)
        before = asyncio.all_tasks()
        worker = asyncio.create_task(service._streaming_worker())
        await asyncio.sleep(0.05)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await asyncio.sleep(0.01)
        leaked = [t for t in asyncio.all_tasks() - before if not t.done()]
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
