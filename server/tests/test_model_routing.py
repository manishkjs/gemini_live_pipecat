import unittest
import os
import sys

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from agent import validate_stt_model, validate_llm_model


class TestModelRouting(unittest.TestCase):
    def test_stt_model_validation(self):
        # Gemini 3.5 Transcribe Live
        self.assertEqual(validate_stt_model("gemini-3.5-transcribe-live"), "gemini-3.5-transcribe-live")
        self.assertEqual(validate_stt_model("gemini-3.5-transcribe-live-aistudio"), "gemini-3.5-transcribe-live-aistudio")
        # Legacy Cloud Speech v2 models
        self.assertEqual(validate_stt_model("chirp_3"), "chirp_3")
        self.assertEqual(validate_stt_model("chirp_2"), "chirp_2")
        self.assertEqual(validate_stt_model("latest_long"), "latest_long")
        # Fallback for unknown
        self.assertEqual(validate_stt_model("unknown_stt"), "gemini-3.5-transcribe-live")

    def test_llm_model_validation(self):
        # Gemini 3.7 Flash and approved tiers
        self.assertEqual(validate_llm_model("gemini-3.7-flash"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-3.5-flash-lite"), "gemini-3.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(validate_llm_model("gemini-2.5-flash-lite"), "gemini-2.5-flash-lite")
        # Removed models should fallback to gemini-3.7-flash
        self.assertEqual(validate_llm_model("gemini-2.5-pro"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-3.5-pro"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-2.0-flash"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-2.0-flash-lite"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-3.5-flash"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-3.6-flash"), "gemini-3.7-flash")


if __name__ == "__main__":
    unittest.main()
