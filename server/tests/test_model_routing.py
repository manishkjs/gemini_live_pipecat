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
        from agent import build_cascade_thinking_config

        # Gemini tiers
        self.assertEqual(validate_llm_model("gemini-3.5-flash-lite"), "gemini-3.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-3.8-flash"), "gemini-3.8-flash")
        self.assertEqual(validate_llm_model("gemini-3.8-flash-aistudio"), "gemini-3.8-flash-aistudio")
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

        # gemini-3.8-flash rejects THINKING_LEVEL_MINIMAL on both Vertex AI and AI Studio;
        # must use thinking_budget=0 (never thinking_level='minimal').
        cfg_38 = build_cascade_thinking_config("gemini-3.8-flash")
        self.assertIsNotNone(cfg_38)
        self.assertEqual(getattr(cfg_38, "thinking_budget", None), 0)
        self.assertIsNone(getattr(cfg_38, "thinking_level", None))

        cfg_35_lite = build_cascade_thinking_config("gemini-3.5-flash-lite")
        self.assertIsNotNone(cfg_35_lite)
        self.assertEqual(getattr(cfg_35_lite, "thinking_level", None), "minimal")

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

    def test_live_vad_modes(self):
        from agent_live import (
            resolve_live_vad_mode,
            build_live_vad_analyzer,
            build_gemini_live_vad_params,
        )

        # 1. 'both' (default): Silero VAD enabled + Gemini Internal VAD enabled (disabled=None)
        self.assertEqual(resolve_live_vad_mode(True, "both"), ("both", True, False))
        self.assertIsNotNone(build_live_vad_analyzer(True, "both"))
        self.assertIsNone(build_gemini_live_vad_params(True, "both"))

        # 2. 'gemini': Silero VAD disabled + Gemini Internal VAD enabled
        self.assertEqual(resolve_live_vad_mode(False, "gemini"), ("gemini", False, False))
        self.assertIsNone(build_live_vad_analyzer(False, "gemini"))
        self.assertIsNone(build_gemini_live_vad_params(False, "gemini"))

        # 3. 'silero': Silero VAD enabled + Gemini Internal VAD disabled (disabled=True)
        self.assertEqual(resolve_live_vad_mode(True, "silero"), ("silero", True, True))
        self.assertIsNotNone(build_live_vad_analyzer(True, "silero"))
        silero_only_params = build_gemini_live_vad_params(True, "silero")
        self.assertIsNotNone(silero_only_params)
        self.assertTrue(silero_only_params.disabled)


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


class TestLiveAvatarRouting(unittest.TestCase):
    def test_resolve_prebuilt_avatar_name(self):
        from agent_live import resolve_prebuilt_avatar_name

        # Explicit prebuilt avatar names (case-insensitive)
        self.assertEqual(resolve_prebuilt_avatar_name("Vera", "debt-collector", "Gacrux", "female"), "Vera")
        self.assertEqual(resolve_prebuilt_avatar_name("kira", "debt-collector", "Gacrux", "female"), "Kira")
        self.assertEqual(resolve_prebuilt_avatar_name("leo", None, "Puck", "male"), "Leo")

        # Auto-match by persona or voice/gender
        self.assertEqual(resolve_prebuilt_avatar_name("auto", "hindi-assistant", "Gacrux", "female"), "Vera")
        self.assertEqual(resolve_prebuilt_avatar_name("auto", "banking-advisor", "Aoede", "female"), "Kira")
        self.assertEqual(resolve_prebuilt_avatar_name("auto", "tech-architect", "Puck", "male"), "Leo")
        self.assertEqual(resolve_prebuilt_avatar_name("custom", "custom", "Puck", "male"), "Ben")
        self.assertEqual(resolve_prebuilt_avatar_name("custom", "custom", "Kore", "female"), "Kira")

    def test_auto_avatar_follows_the_voice_before_the_default_gender(self):
        from agent_live import resolve_prebuilt_avatar_name

        self.assertEqual(resolve_prebuilt_avatar_name("auto", None, "Puck", "female"), "Ben")
        self.assertEqual(resolve_prebuilt_avatar_name("auto", None, "Achernar", "male"), "Kira")
        self.assertEqual(resolve_prebuilt_avatar_name("auto", None, "Custom-Live-Voice", "female"), "Kira",
                         "a recorded voice has no known gender, so the default decides")


class TestVoiceGender(unittest.TestCase):
    def test_every_studio_voice_label_agrees(self):
        import re
        import voice_profiles

        repo = os.path.dirname(server_dir)
        with open(os.path.join(repo, "demos/voice-studio/src/lib/voice-session.ts"), encoding="utf-8") as f:
            labels = dict(re.findall(r'\["([\w-]+)", "[^"]*\((Male|Female)\)"\]', f.read()))
        self.assertGreater(len(labels), 25)
        for voice, gender in labels.items():
            self.assertEqual(voice_profiles.voice_gender(voice), gender.lower(), voice)

    def test_voices_outside_the_list(self):
        import voice_profiles

        self.assertEqual(voice_profiles.voice_gender("Gacrux"), "female")
        self.assertEqual(voice_profiles.voice_gender("hi-IN-Chirp3-HD-Charon"), "male")
        for unknown in ("Custom-Live-Voice", "Custom-Key", "", None):
            self.assertIsNone(voice_profiles.voice_gender(unknown), unknown)

    def test_live_prompt_uses_the_voice_gender(self):
        from agent_live import compose_live_system_prompt
        import voice_profiles

        self.assertIn("male AI assistant", compose_live_system_prompt(None, voice_profiles.voice_gender("Puck"), "en-US"))

    def test_live_clone_voices_get_self_reference_grammar(self):
        from agent_live import compose_live_system_prompt

        prompt = compose_live_system_prompt("Be terse.", "male", "hi-IN", voice="Gemini-Clone-Male")
        self.assertIn("सकता हूँ", prompt)
        self.assertTrue(prompt.startswith("Be terse.\n\nVOICE GENDER:"), prompt)
        self.assertTrue(prompt.endswith("IMPORTANT: You must converse in hi-IN language."), prompt)
        self.assertEqual(compose_live_system_prompt("Be terse.", "male", "hi-IN", voice="Puck"),
                         "Be terse.\n\nIMPORTANT: You must converse in hi-IN language.",
                         "named voices are left to the persona")

    def test_normalize_custom_avatar_image_produces_704x1280_rgb_png(self):
        import io
        from PIL import Image
        from agent_live import normalize_custom_avatar_image

        # 1. Square RGBA input -> 704x1280 RGB PNG
        rgba_src = Image.new("RGBA", (420, 420), color=(90, 140, 210, 180))
        src_buf = io.BytesIO()
        rgba_src.save(src_buf, format="PNG")
        norm_bytes, meta = normalize_custom_avatar_image(src_buf.getvalue())

        self.assertEqual(meta["orig_size"], "420x420")
        self.assertEqual(meta["norm_size"], "704x1280")
        self.assertLess(len(norm_bytes), 5_000_000)

        with Image.open(io.BytesIO(norm_bytes)) as out_img:
            self.assertEqual(out_img.size, (704, 1280))
            self.assertEqual(out_img.format, "PNG")
            self.assertEqual(out_img.mode, "RGB")


if __name__ == "__main__":
    unittest.main()


