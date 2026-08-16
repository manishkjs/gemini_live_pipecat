"""Unit tests for Continuous Watcher Brain (Gemini 3.5 Flash-Lite Sidecar)."""

import os
import json
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from watcher_brain import WatcherBrain
from system_prompt import WATCHER_SYSTEM_PROMPT


class TestWatcherBrain(unittest.TestCase):
    """Test suite for WatcherBrain sidecar functionality."""

    def setUp(self):
        self.patcher = patch("watcher_brain.Client")
        self.mock_client_cls = self.patcher.start()
        self.mock_client = MagicMock()
        self.mock_client_cls.return_value = self.mock_client

    def tearDown(self):
        self.patcher.stop()

    def test_initialization_defaults(self):
        """Verify WatcherBrain defaults to gemini-3.5-flash-lite at location=global."""
        brain = WatcherBrain(project_id="test-proj")
        self.assertEqual(brain.model, "gemini-3.5-flash-lite")
        self.assertEqual(brain.location, "global")
        self.assertEqual(brain.project_id, "test-proj")
        self.mock_client_cls.assert_called_once_with(
            project="test-proj",
            location="global",
            vertexai=True,
        )

    def test_watcher_system_prompt_structure(self):
        """Verify WATCHER_SYSTEM_PROMPT contains XML tags and response format."""
        self.assertIn("<watcher_system_prompt>", WATCHER_SYSTEM_PROMPT)
        self.assertIn("</watcher_system_prompt>", WATCHER_SYSTEM_PROMPT)
        self.assertIn("should_inject_hint", WATCHER_SYSTEM_PROMPT)
        self.assertIn("hint_type", WATCHER_SYSTEM_PROMPT)
        self.assertIn("hint_text", WATCHER_SYSTEM_PROMPT)

    def test_analyze_dialogue_injects_hint(self):
        """Verify analyze_dialogue parses valid JSON hint response."""
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "should_inject_hint": True,
            "hint_type": "objection",
            "hint_text": "Customer is worried about lock-in. Mention 6M STL with 18% XIRR and monthly interest payout.",
            "reasoning": "High liquidity hesitation detected."
        })
        self.mock_client.models.generate_content.return_value = mock_response

        brain = WatcherBrain(project_id="test-proj")
        history = [
            {"role": "assistant", "text": "नमस्ते! मैं प्रज्ञा बात कर रही हूँ Cymbal Lending से।"},
            {"role": "user", "text": "मुझे डर है कि मेरा पैसा फँस जाएगा और ज़रूरत पड़ने पर नहीं मिलेगा।"}
        ]

        result = asyncio.run(brain.analyze_dialogue(history))
        self.assertIsNotNone(result)
        self.assertTrue(result["should_inject_hint"])
        self.assertEqual(result["hint_type"], "objection")
        self.assertIn("6M STL", result["hint_text"])

    def test_analyze_dialogue_no_hint(self):
        """Verify analyze_dialogue returns should_inject_hint=False for filler utterances."""
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "should_inject_hint": False,
            "hint_type": None,
            "hint_text": None,
            "reasoning": "Standard filler greeting, no intervention needed."
        })
        self.mock_client.models.generate_content.return_value = mock_response

        brain = WatcherBrain(project_id="test-proj")
        history = [
            {"role": "assistant", "text": "नमस्ते! क्या आपके पास 2 मिनट का समय है?"},
            {"role": "user", "text": "हाँ जी बताइए।"}
        ]

        result = asyncio.run(brain.analyze_dialogue(history))
        self.assertIsNotNone(result)
        self.assertFalse(result["should_inject_hint"])

    def test_maybe_whisper_to_live_sends_websocket_frame(self):
        """Verify maybe_whisper_to_live dispatches system role frame to Gemini Live session."""
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "should_inject_hint": True,
            "hint_type": "strategy",
            "hint_text": "Customer mentioned ₹1,00,000. Highlight ₹24,000 annual return at 24% MTL.",
            "reasoning": "Capital sizing opportunity."
        })
        self.mock_client.models.generate_content.return_value = mock_response

        brain = WatcherBrain(project_id="test-proj")
        mock_session = MagicMock()
        mock_session.send_client_content = AsyncMock()

        history = [
            {"role": "assistant", "text": "आप कितना invest करने का सोच रहे हैं?"},
            {"role": "user", "text": "मैं 1 लाख रुपये invest करना चाहता हूँ।"}
        ]

        success = asyncio.run(brain.maybe_whisper_to_live(mock_session, history, user_id="user_test"))
        self.assertTrue(success)
        mock_session.send_client_content.assert_called_once()
        call_args = mock_session.send_client_content.call_args
        turns = call_args.kwargs.get("turns", [])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].role, "system")
        self.assertIn('<copilot_hint type="strategy">', turns[0].parts[0].text)
        self.assertIn("₹1,00,000", turns[0].parts[0].text)

    def test_maybe_whisper_to_live_skips_short_fillers(self):
        """Verify maybe_whisper_to_live skips 1-word filler user utterances without calling API."""
        brain = WatcherBrain(project_id="test-proj")
        mock_session = MagicMock()
        mock_session.send_client_content = AsyncMock()

        history = [
            {"role": "assistant", "text": "क्या आपको समझ आया?"},
            {"role": "user", "text": "हाँ"}
        ]

        success = asyncio.run(brain.maybe_whisper_to_live(mock_session, history, user_id="user_test"))
        self.assertFalse(success)
        self.mock_client.models.generate_content.assert_not_called()
        mock_session.send_client_content.assert_not_called()


if __name__ == "__main__":
    unittest.main()
