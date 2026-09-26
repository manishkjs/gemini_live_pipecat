"""Gemini 3.8 TTS cloned voice (voicekey_...) routing.

The Gemini clone is a different product from the Chirp 3 HD clones: its
credential goes in `VoiceConfig(voice=...)` on gemini-3.8-flash(-lite)-tts, is
bound to the AI Studio GEMINI_API_KEY project, and must never be sent to Chirp
or to PrebuiltVoiceConfig (400 "No matching speaker voice found").
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from google.genai import types

import voice_profiles


class TestGeminiCloneSelection(unittest.TestCase):
    def test_gemini_clone_is_not_mistaken_for_a_chirp_clone(self):
        self.assertTrue(voice_profiles.is_gemini_clone_voice("Gemini-Clone-Male"))
        self.assertFalse(voice_profiles.is_custom_clone_voice("Gemini-Clone-Male"))
        self.assertFalse(voice_profiles.is_male_clone_voice("Gemini-Clone-Male"))
        self.assertIsNone(voice_profiles.resolve_clone_key("Gemini-Clone-Male"))

    def test_named_and_chirp_voices_never_load_the_gemini_key(self):
        with patch.object(voice_profiles, "load_gemini_voice_key") as load:
            for voice in ("Puck", "Custom-Male", "Custom-Female", "Custom-Key", ""):
                self.assertIsNone(voice_profiles.resolve_gemini_voice_key(voice))
            load.assert_not_called()

    def test_key_resolves_from_env_path(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("  voicekey_CAESfake  \n")
        try:
            with patch.dict(os.environ, {"GEMINI_TTS_VOICE_KEY_MALE": f.name}):
                self.assertEqual(voice_profiles.resolve_gemini_voice_key("Gemini-Clone-Male"), "voicekey_CAESfake")
        finally:
            os.unlink(f.name)

    def test_missing_key_fails_loudly(self):
        with patch.object(voice_profiles, "load_gemini_voice_key", return_value=None):
            with self.assertRaisesRegex(ValueError, "Gemini 3.8 cloned voice"):
                voice_profiles.resolve_gemini_voice_key("Gemini-Clone-Male")

    def test_non_voicekey_content_is_rejected(self):
        with patch.object(voice_profiles, "load_gemini_voice_key", return_value="not-a-voicekey"):
            with self.assertRaisesRegex(ValueError, "voicekey_"):
                voice_profiles.resolve_gemini_voice_key("Gemini-Clone-Male")

    def test_only_gemini_38_tts_models_accept_the_clone(self):
        for model in ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-3.8-flash-lite-tts-aistudio"):
            self.assertTrue(voice_profiles.supports_gemini_clone(model), model)
        for model in ("google-tts", "gemini-2.5-flash-preview-tts", "gemini-3.1-flash-tts-preview"):
            self.assertFalse(voice_profiles.supports_gemini_clone(model), model)


class TestGeminiCloneSpeechConfig(unittest.TestCase):
    def _service(self, **kw):
        # The pipecat base builds a Cloud TTS client in __init__; these tests are
        # about request shape, so they must not depend on local credentials.
        from agent import CustomVertexGeminiTTSService
        from pipecat.services.google.tts import GeminiTTSService
        with patch.object(GeminiTTSService, "_create_client", return_value=None), \
             patch("agent.genai.Client", return_value=None):
            return CustomVertexGeminiTTSService(project_id="p", location="us-central1", **kw)

    def test_voice_key_goes_in_voice_config_voice_never_prebuilt(self):
        svc = self._service(voice_id="Gemini-Clone-Male", model="gemini-3.8-flash-lite-tts", voice_key="voicekey_CAESfake")
        cfg = svc._voice_config()
        self.assertIsInstance(cfg, types.VoiceConfig)
        self.assertEqual(cfg.voice, "voicekey_CAESfake")
        self.assertIsNone(cfg.prebuilt_voice_config)
        self.assertTrue(svc._is_aistudio, "voicekeys are bound to the AI Studio GEMINI_API_KEY project")
        self.assertNotIn("voicekey_", svc._settings.voice, "the credential must not live in loggable settings")

    def test_named_voice_still_uses_prebuilt(self):
        svc = self._service(voice_id="Puck", model="gemini-3.8-flash-tts")
        cfg = svc._voice_config()
        self.assertIsNone(cfg.voice)
        self.assertEqual(cfg.prebuilt_voice_config.voice_name, "Puck")


class TestGeminiLiveReplicatedVoice(unittest.TestCase):
    def test_live_replicated_voice_detection_and_manish_sample(self):
        self.assertTrue(voice_profiles.is_live_replicated_voice("Gemini-Clone-Male"))
        self.assertTrue(voice_profiles.is_live_replicated_voice("Custom-Live-Voice"))
        self.assertFalse(voice_profiles.is_live_replicated_voice("Puck"))
        self.assertFalse(voice_profiles.is_live_replicated_voice("Custom-Male"))

        with tempfile.NamedTemporaryFile("wb", suffix=".wav", delete=False) as f:
            f.write(b"RIFF\x24\x00\x00\x00WAVEfmt ")
        try:
            with patch.dict(os.environ, {"GEMINI_LIVE_VOICE_SAMPLE_MALE": f.name}):
                sample = voice_profiles.load_gemini_live_voice_sample("Gemini-Clone-Male")
                self.assertIsNotNone(sample)
                self.assertTrue(sample.startswith(b"RIFF"))
                self.assertIsNone(voice_profiles.load_gemini_live_voice_sample("Puck"))
        finally:
            os.unlink(f.name)

    def test_normalize_custom_voice_audio_resamples_to_24k_mono_s16le_wav(self):
        import io
        import wave
        import numpy as np
        from agent_live import normalize_custom_voice_audio

        # Create a 5-second stereo 48kHz 16-bit WAV
        sr = 48000
        dur = 5.0
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        tone = (np.sin(2 * np.pi * 220 * t) * 12000).astype(np.int16)
        stereo = np.column_stack([tone, tone]).ravel()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(stereo.tobytes())

        norm_bytes, meta = normalize_custom_voice_audio(buf.getvalue())
        self.assertTrue(norm_bytes.startswith(b"RIFF"))
        self.assertEqual(meta["orig_rate"], 48000)
        self.assertEqual(meta["orig_channels"], 2)
        self.assertAlmostEqual(meta["duration_s"], 5.0, places=1)

        with wave.open(io.BytesIO(norm_bytes), "rb") as out_wf:
            self.assertEqual(out_wf.getnchannels(), 1)
            self.assertEqual(out_wf.getsampwidth(), 2)
            self.assertEqual(out_wf.getframerate(), 24000)
            self.assertEqual(out_wf.getnframes(), 24000 * 5)

    def test_connect_stores_custom_voice_audio_outside_ws_url(self):
        from fastapi.testclient import TestClient
        import server
        import session_access

        session_access._sessions.clear()
        client = TestClient(server.app)
        fake_wav_b64 = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA="
        res = client.post(
            "/connect?bot_type=gemini-live&voice=Custom-Live-Voice",
            json={"custom_voice_audio": fake_wav_b64},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertNotIn("UklGRiQ", data["ws_url"])
        self.assertNotIn("custom_voice_audio", data["ws_url"])
        self.assertEqual(session_access.take_custom_voice_audio(data["session_id"]), fake_wav_b64)
        self.assertIsNone(session_access.take_custom_voice_audio(data["session_id"]))


if __name__ == "__main__":
    unittest.main()

