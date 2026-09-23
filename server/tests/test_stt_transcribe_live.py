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


if __name__ == "__main__":
    unittest.main()
