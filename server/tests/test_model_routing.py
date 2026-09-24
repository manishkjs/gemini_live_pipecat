import unittest
import os
import sys

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from agent import validate_stt_model, validate_llm_model, validate_tts_model


class TestModelRouting(unittest.TestCase):
    def test_stt_model_validation(self):
        # Gemini 3.5 Transcribe Live
        self.assertEqual(validate_stt_model("gemini-3.5-transcribe-live"), "gemini-3.5-transcribe-live")
        self.assertEqual(validate_stt_model("gemini-3.5-transcribe-live-aistudio"), "gemini-3.5-transcribe-live-aistudio")
        # Legacy Cloud Speech v2 models
        self.assertEqual(validate_stt_model("chirp_3"), "chirp_3")
        self.assertEqual(validate_stt_model("chirp_2"), "chirp_2")
        self.assertEqual(validate_stt_model("latest_long"), "latest_long")
        # Fallback for unknown defaults to gemini-3.5-transcribe-live-aistudio
        self.assertEqual(validate_stt_model("unknown_stt"), "gemini-3.5-transcribe-live-aistudio")

    def test_llm_model_validation(self):
        # Gemini tiers
        self.assertEqual(validate_llm_model("gemini-3.5-flash-lite"), "gemini-3.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-3.7-flash"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(validate_llm_model("gemini-2.5-flash-lite"), "gemini-2.5-flash-lite")
        # Removed models should fallback to gemini-3.5-flash-lite
        self.assertEqual(validate_llm_model("gemini-2.5-pro"), "gemini-3.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-3.5-pro"), "gemini-3.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-2.0-flash"), "gemini-3.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-2.0-flash-lite"), "gemini-3.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-3.5-flash"), "gemini-3.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-3.6-flash"), "gemini-3.5-flash-lite")

    def test_tts_model_validation(self):
        self.assertEqual(validate_tts_model("gemini-3.8-flash-tts"), "gemini-3.8-flash-tts")
        self.assertEqual(validate_tts_model("gemini-3.8-flash-lite-tts"), "gemini-3.8-flash-lite-tts")
        self.assertEqual(validate_tts_model("gemini-3.1-flash-tts-preview"), "gemini-3.1-flash-tts-preview")
        self.assertEqual(validate_tts_model("gemini-2.5-flash-lite-preview-tts"), "gemini-2.5-flash-lite-preview-tts")
        self.assertEqual(validate_tts_model("gemini-2.5-flash-preview-tts"), "gemini-2.5-flash-preview-tts")
        self.assertEqual(validate_tts_model("google-tts"), "google-tts")
        self.assertEqual(validate_tts_model("unknown_tts"), "gemini-3.8-flash-lite-tts")

    def test_live_model_gateway_routing(self):
        from agent_live import resolve_live_model_gateway, build_thinking_config

        # Vertex AI GA 3.8 Live (default) and legacy preview alias
        self.assertEqual(resolve_live_model_gateway("gemini-3.8-live"), (False, "gemini-3.8-live"))
        self.assertEqual(resolve_live_model_gateway("gemini-3.8-live-preview"), (False, "gemini-3.8-live"))
        self.assertEqual(resolve_live_model_gateway("gemini-3.8-flash-live-preview"), (False, "gemini-3.8-live"))

        # Vertex AI Extended Thinking remains -preview
        self.assertEqual(
            resolve_live_model_gateway("gemini-3.8-live-extended-thinking-preview"),
            (False, "gemini-3.8-live-extended-thinking-preview"),
        )

        # AI Studio 3.8 Live via -aistudio suffix and Extended Thinking
        self.assertEqual(resolve_live_model_gateway("gemini-3.8-live-aistudio"), (True, "gemini-3.8-live"))
        self.assertEqual(
            resolve_live_model_gateway("gemini-3.8-live-extended-thinking"),
            (True, "gemini-3.8-live-extended-thinking"),
        )

        # Vertex AI 2.5 Native Audio vs AI Studio 2.5 Native Audio
        self.assertEqual(
            resolve_live_model_gateway("gemini-live-2.5-flash-native-audio"),
            (False, "gemini-live-2.5-flash-native-audio"),
        )
        self.assertEqual(
            resolve_live_model_gateway("gemini-2.5-flash-native-audio-latest"),
            (True, "gemini-2.5-flash-native-audio-latest"),
        )

        # Base gemini-3.8-live never emits thinking_level; extended-thinking does
        self.assertEqual(build_thinking_config("gemini-3.8-live", True, "medium"), {})
        self.assertEqual(
            build_thinking_config("gemini-3.8-live-extended-thinking-preview", False, None),
            {"thinking_level": "medium"},
        )


class TestVoiceCloningRouting(unittest.TestCase):
    def test_voice_cloning_key_loading(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import voice_profiles
        with tempfile.TemporaryDirectory() as folder:
            for gender, env in (("male", "CLONE_TTS_VOICE_KEY_MALE"), ("female", "CLONE_TTS_VOICE_KEY_FEMALE")):
                path = Path(folder) / f"{gender}.txt"
                path.write_text(f"dummy-{gender}-credential\n")
                with patch.dict(os.environ, {env: str(path)}):
                    self.assertEqual(voice_profiles.get_voice_cloning_key_file(gender), str(path))
                    self.assertEqual(voice_profiles.load_voice_cloning_key(gender), f"dummy-{gender}-credential")

    def test_clone_voice_matchers(self):
        import voice_profiles

        # Male matchers
        self.assertTrue(voice_profiles.is_male_clone_voice("Custom-Male"))
        self.assertTrue(voice_profiles.is_male_clone_voice("Chirp3-HD-Clone-Male"))
        self.assertTrue(voice_profiles.is_male_clone_voice("hi-IN-Chirp3-HD-Custom-Male"))
        self.assertFalse(voice_profiles.is_male_clone_voice("Custom-Female"))
        self.assertFalse(voice_profiles.is_male_clone_voice("Aoede"))
        self.assertFalse(voice_profiles.is_male_clone_voice(None))

        # Female matchers
        self.assertTrue(voice_profiles.is_female_clone_voice("Custom-Female"))
        self.assertTrue(voice_profiles.is_female_clone_voice("Chirp3-HD-Clone-Female"))
        self.assertTrue(voice_profiles.is_female_clone_voice("hi-IN-Chirp3-HD-Custom-Female"))
        self.assertFalse(voice_profiles.is_female_clone_voice("Custom-Male"))
        self.assertFalse(voice_profiles.is_female_clone_voice("Puck"))
        self.assertFalse(voice_profiles.is_female_clone_voice(None))

        # Custom clone matchers
        self.assertTrue(voice_profiles.is_custom_clone_voice("Custom-Male"))
        self.assertTrue(voice_profiles.is_custom_clone_voice("Custom-Female"))
        self.assertTrue(voice_profiles.is_custom_clone_voice("Custom-Key"))
        self.assertFalse(voice_profiles.is_custom_clone_voice("Aoede"))
        self.assertFalse(voice_profiles.is_custom_clone_voice(None))


if __name__ == "__main__":
    unittest.main()

