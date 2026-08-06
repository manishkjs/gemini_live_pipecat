"""
Unit and integration tests for Gemini Live Pipecat LangSmith Observability.
"""

import os
import unittest

from server.gemini_live_pipecat_langsmith import (
    GeminiLiveLangSmithPipeline,
    configure_pipecat,
    AudioRawFrame,
    InterruptionFrame,
    StartFrame,
    EndFrame,
)


class TestObservabilityPipeline(unittest.TestCase):
    """Test suite for LangSmith Pipecat tracing integration."""

    def setUp(self):
        self.api_key = "test_gemini_api_key"
        self.conv_id = "test_conversation_12345"
        self.project = "test-gemini-live-project"

    def test_configure_pipecat_initialization(self):
        """Verify environment variables and configure_pipecat are called correctly."""
        pipeline = GeminiLiveLangSmithPipeline(
            gemini_api_key=self.api_key,
            langsmith_api_key="test_langsmith_key",
            langsmith_project=self.project,
            conversation_id=self.conv_id,
        )
        self.assertEqual(os.environ.get("LANGSMITH_TRACING"), "true")
        self.assertEqual(os.environ.get("LANGSMITH_PROJECT"), self.project)
        self.assertEqual(os.environ.get("LANGSMITH_API_KEY"), "test_langsmith_key")

    def test_build_pipeline_task_params(self):
        """Verify PipelineTask is built with turn tracking and conversation ID."""
        pipeline = GeminiLiveLangSmithPipeline(
            gemini_api_key=self.api_key,
            conversation_id=self.conv_id,
        )
        task = pipeline.build_pipeline(room_url="https://demo.daily.co/test-room")
        
        # Verify task parameters
        self.assertTrue(task.params.allow_interruptions)
        self.assertTrue(task.params.enable_tracing)
        self.assertTrue(task.params.enable_turn_tracking)
        self.assertEqual(task.params.conversation_id, self.conv_id)
        self.assertEqual(task.params.extra_metadata["model"], "gemini-2.0-flash-exp")
        self.assertEqual(task.params.extra_metadata["provider"], "google-gemini-live")


if __name__ == "__main__":
    unittest.main()
