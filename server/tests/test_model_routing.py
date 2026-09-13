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
        self.assertEqual(validate_tts_model("gemini-3.1-flash-tts-preview"), "gemini-3.1-flash-tts-preview")
        self.assertEqual(validate_tts_model("gemini-2.5-flash-lite-preview-tts"), "gemini-2.5-flash-lite-preview-tts")
        self.assertEqual(validate_tts_model("gemini-2.5-flash-preview-tts"), "gemini-2.5-flash-preview-tts")
        self.assertEqual(validate_tts_model("google-tts"), "google-tts")
        self.assertEqual(validate_tts_model("unknown_tts"), "gemini-3.1-flash-tts-preview")


class TestVoiceCloningRouting(unittest.TestCase):
    def test_voice_cloning_key_loading(self):
        import voice_profiles

        male_file = voice_profiles.get_voice_cloning_key_file("male")
        female_file = voice_profiles.get_voice_cloning_key_file("female")
        self.assertIsNotNone(male_file, "Male clone key file should be resolved")
        self.assertIsNotNone(female_file, "Female clone key file should be resolved")
        self.assertTrue(os.path.isfile(male_file))
        self.assertTrue(os.path.isfile(female_file))

        male_key = voice_profiles.load_voice_cloning_key("male")
        female_key = voice_profiles.load_voice_cloning_key("female")
        self.assertIsNotNone(male_key)
        self.assertIsNotNone(female_key)
        self.assertGreater(len(male_key), 100)
        self.assertGreater(len(female_key), 100)

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

