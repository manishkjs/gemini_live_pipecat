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
        from agent import build_cascade_thinking_config, supports_cascade_audio_input

        # Gemini & Vertex MaaS tiers
        self.assertEqual(validate_llm_model("gemini-3.5-flash-lite"), "gemini-3.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-3.8-flash"), "gemini-3.8-flash")
        self.assertEqual(validate_llm_model("gemini-3.8-flash-aistudio"), "gemini-3.8-flash-aistudio")
        self.assertEqual(validate_llm_model("gemini-3.7-flash"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(validate_llm_model("gemini-2.5-flash-lite"), "gemini-2.5-flash-lite")
        self.assertEqual(validate_llm_model("gemma-4-26b-a4b-it-maas"), "gemma-4-26b-a4b-it-maas")
        # Unlaunched / removed models should fallback to gemini-3.5-flash-lite
        self.assertEqual(validate_llm_model("gemma-4-31b-it-maas"), "gemini-3.5-flash-lite")
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

        # Gemma 4 MaaS does not support thinkingConfig or raw audio input (skip_stt).
        self.assertIsNone(build_cascade_thinking_config("gemma-4-26b-a4b-it-maas"))
        self.assertFalse(supports_cascade_audio_input("gemma-4-26b-a4b-it-maas"))
        self.assertTrue(supports_cascade_audio_input("gemini-3.5-flash-lite"))
        self.assertTrue(supports_cascade_audio_input("gemini-3.8-flash"))

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
        from agent_live import LIVE_LANGUAGE_RULE, compose_live_system_prompt

        prompt = compose_live_system_prompt("Be terse.", "male", "hi-IN", voice="Gemini-Clone-Male")
        self.assertIn("सकता हूँ", prompt)
        self.assertTrue(prompt.startswith("Be terse.\n\nVOICE GENDER:"), prompt)
        self.assertTrue(prompt.endswith(LIVE_LANGUAGE_RULE.format(language="hi-IN")), prompt)
        self.assertEqual(compose_live_system_prompt("Be terse.", "male", "hi-IN", voice="Puck"),
                         "Be terse.\n\n" + LIVE_LANGUAGE_RULE.format(language="hi-IN"),
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


class TestGemma4RateLimitFailover(unittest.TestCase):
    def test_gemma_4_maas_429_queue_full_retries_clears_stale_ttfb_and_fails_over_to_aistudio(self):
        import asyncio
        from decimal import Decimal
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        import agent
        from cascade_pricing import CascadeCostLedger

        self.assertEqual(agent.validate_llm_model("gemma-4-26b-a4b-it-aistudio"), "gemma-4-26b-a4b-it-aistudio")
        self.assertEqual(agent.validate_llm_model("gemma-4-26b-a4b-it"), "gemma-4-26b-a4b-it")
        self.assertFalse(agent.supports_cascade_audio_input("gemma-4-26b-a4b-it-aistudio"))
        self.assertFalse(agent.supports_cascade_audio_input("gemma-4-26b-a4b-it-maas"))

        class FakeBaseLLM:
            def __init__(self):
                self._settings = SimpleNamespace(model="gemma-4-26b-a4b-it-maas")
                self._project_id = "demo-proj"
                self._location = "global"
                self._my_ttfb_start = None
                self.base_calls = 0

            async def _stream_content(self, params_from_context):
                self.base_calls += 1
                self._my_ttfb_start = 100.0  # Simulate GoogleLLMService starting TTFB timer before RPC

                async def failing_gen():
                    raise RuntimeError(
                        '429 Too Many Requests. {\'message\': \'{"error":{"code":429,"message":"The request queue is full.","status":"RESOURCE_EXHAUSTED"}}\'}'
                    )
                    yield  # pragma: no cover

                return failing_gen()

        class TestVertexGemma(agent._MeteredGeminiLLMMixin, FakeBaseLLM):
            _cascade_provider = "vertex"

        async def run_scenario():
            # 1) Failover succeeds when AI Studio fallback stream yields chunks
            svc = TestVertexGemma()
            ledger = CascadeCostLedger("sess-gemma-failover", skip_stt=False)
            svc._cascade_meter = ledger
            svc._cost_input_mode = "text"

            fallback_chunk = SimpleNamespace(
                usage_metadata=SimpleNamespace(
                    prompt_token_count=798,
                    candidates_token_count=41,
                    cached_content_token_count=0,
                    thoughts_token_count=0,
                    total_token_count=839,
                    prompt_tokens_details=None,
                    cache_tokens_details=None,
                )
            )

            async def fake_aistudio_stream():
                yield fallback_chunk

            with patch("asyncio.sleep", new=AsyncMock()), \
                 patch.object(svc, "_open_gemma_aistudio_fallback", new=AsyncMock(return_value=fake_aistudio_stream())):
                stream = await svc._stream_content(SimpleNamespace())
                received = [c async for c in stream]

            self.assertEqual(len(received), 1)
            self.assertEqual(svc.base_calls, 3)  # Initial attempt + 2 retries before AI Studio failover
            self.assertEqual(svc._active_turn_model, "gemma-4-26b-a4b-it")
            snap = ledger.snapshot()
            llm_stage = snap["stages"][1]
            self.assertTrue(llm_stage["complete"])
            self.assertEqual(Decimal(llm_stage["known_usd"]), Decimal("0"))
            self.assertEqual(llm_stage["rates"][0]["provider"], "gemini")
            self.assertEqual(llm_stage["rates"][0]["model"], "gemma-4-26b-a4b-it")

            # 2) If no fallback key is available, _my_ttfb_start is cleared so Turn N+1 never inherits a 15.6s stale timer
            svc_no_fb = TestVertexGemma()
            with patch("asyncio.sleep", new=AsyncMock()), \
                 patch.object(svc_no_fb, "_open_gemma_aistudio_fallback", new=AsyncMock(return_value=None)):
                with self.assertRaisesRegex(RuntimeError, "request queue is full"):
                    stream2 = await svc_no_fb._stream_content(SimpleNamespace())
                    async for _ in stream2:
                        pass
            self.assertIsNone(svc_no_fb._my_ttfb_start)

            # 3) G1 regression: when open_base raises on stream open (before yielding a generator) AND
            #    AI Studio fallback ALSO arms _my_ttfb_start then raises, _my_ttfb_start is reset to None
            #    and the cost ledger stage is marked failed (never stuck 'Awaiting final provider usage').
            class RaiseOnOpenBase:
                def __init__(self):
                    self._settings = SimpleNamespace(model="gemma-4-26b-a4b-it-maas")
                    self._project_id = "demo-proj"
                    self._location = "global"
                    self._my_ttfb_start = None
                    self.open_calls = 0

                async def _stream_content(self, params_from_context):
                    self.open_calls += 1
                    self._my_ttfb_start = 100.0
                    err = RuntimeError("429 Too Many Requests: The request queue is full.")
                    err.code = 429
                    raise err

            class RaiseOnOpenVertexGemma(agent._MeteredGeminiLLMMixin, RaiseOnOpenBase):
                _cascade_provider = "vertex"

            svc_both_fail = RaiseOnOpenVertexGemma()
            ledger_fail = CascadeCostLedger("sess-gemma-both-fail", skip_stt=False)
            svc_both_fail._cascade_meter = ledger_fail
            svc_both_fail._cost_input_mode = "text"

            async def failing_aistudio_open(_ctx):
                svc_both_fail._my_ttfb_start = 200.0
                # Simulate real _open_gemma_aistudio_fallback try/except resetting _my_ttfb_start,
                # AND verify _open_initial's outer handler also resets even if a custom hook forgot.
                raise RuntimeError("AI Studio fallback 503 unavailable")

            with patch("asyncio.sleep", new=AsyncMock()), \
                 patch.object(svc_both_fail, "_open_gemma_aistudio_fallback", side_effect=failing_aistudio_open):
                with self.assertRaisesRegex(RuntimeError, "AI Studio fallback 503 unavailable"):
                    await svc_both_fail._stream_content(SimpleNamespace())

            self.assertEqual(svc_both_fail.open_calls, 3)
            self.assertIsNone(svc_both_fail._my_ttfb_start)
            fail_stage = ledger_fail.snapshot()["stages"][1]
            self.assertFalse(fail_stage["complete"])
            self.assertIn("LLM request failed before final usage", fail_stage["issues"])
            self.assertNotIn("Awaiting final provider usage", fail_stage["issues"])

            # 4) G2 regression: non-429 errors whose message contains '1429' are NOT treated as rate limits
            err_400_with_1429 = RuntimeError("400 Bad Request: input token count (1429) exceeds context limit")
            err_400_with_1429.code = 400
            self.assertFalse(agent.CustomGoogleVertexLLMService._is_rate_limit_error(err_400_with_1429))
            plain_1429 = RuntimeError("Invalid argument: prompt has 1429 tokens")
            self.assertFalse(agent.CustomGoogleVertexLLMService._is_rate_limit_error(plain_1429))
            real_429 = RuntimeError("429 Too Many Requests: The request queue is full.")
            self.assertTrue(agent.CustomGoogleVertexLLMService._is_rate_limit_error(real_429))

        asyncio.run(run_scenario())


if __name__ == "__main__":
    unittest.main()



