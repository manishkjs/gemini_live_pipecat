"""Unit tests for Jarvis key storage/precedence, validation, permissions, and setup bridge."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot  # noqa: E402
import jarvis_app  # noqa: E402
import jarvis_config  # noqa: E402
import mac_permissions  # noqa: E402


class _FakeHttpResponse:

    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class JarvisConfigStorageAndPrecedenceTest(unittest.TestCase):

    def test_save_api_key_creates_0600_file_and_preserves_other_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            cfg.write_text(json.dumps({"other_setting": True}), encoding="utf-8")
            os.chmod(cfg, 0o644)

            written = jarvis_config.save_api_key("  test_fake_key_12345  ", config_path=cfg)
            self.assertEqual(written, cfg)
            mode = stat.S_IMODE(cfg.stat().st_mode)
            self.assertEqual(mode, 0o600)

            loaded_json = json.loads(cfg.read_text(encoding="utf-8"))
            self.assertEqual(
                loaded_json,
                {"other_setting": True, "gemini_api_key": "test_fake_key_12345"},
            )
            self.assertEqual(
                jarvis_config.load_saved_api_key(config_path=cfg), "test_fake_key_12345"
            )

    def test_save_api_key_rejects_empty_or_whitespace_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            for bad in ("", "   ", "has space inside", "line1\nline2"):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        jarvis_config.save_api_key(bad, config_path=cfg)
            self.assertFalse(cfg.exists())

    def test_lookup_precedence_env_then_dotenv_then_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            dotenv_file = Path(tmp) / ".env"
            cfg_file = Path(tmp) / "config.json"
            dotenv_file.write_text(
                'GEMINI_API_KEY="from_dotenv_value"\nJARVIS_VOICE=Puck\n', encoding="utf-8"
            )
            jarvis_config.save_api_key("from_config_value", config_path=cfg_file)

            # 1. Environment variable wins over .env and config.json
            hit_env = jarvis_config.lookup_api_key(
                environ={"GEMINI_API_KEY": "from_env_value"},
                dotenv_path=dotenv_file,
                config_path=cfg_file,
            )
            self.assertEqual(hit_env, jarvis_config.KeyLookup("from_env_value", "env"))

            # GOOGLE_API_KEY in env also beats .env
            hit_google_env = jarvis_config.lookup_api_key(
                environ={"GOOGLE_API_KEY": "from_google_env"},
                dotenv_path=dotenv_file,
                config_path=cfg_file,
            )
            self.assertEqual(hit_google_env, jarvis_config.KeyLookup("from_google_env", "env"))

            # 2. .env wins over config.json when env is unset/blank
            hit_dotenv = jarvis_config.lookup_api_key(
                environ={"GEMINI_API_KEY": "   "},
                dotenv_path=dotenv_file,
                config_path=cfg_file,
            )
            self.assertEqual(hit_dotenv, jarvis_config.KeyLookup("from_dotenv_value", "dotenv"))

            # 3. config.json is used when .env is bypassed or has no key
            hit_cfg = jarvis_config.lookup_api_key(
                environ={"JARVIS_NO_DOTENV": "1"},
                dotenv_path=dotenv_file,
                config_path=cfg_file,
            )
            self.assertEqual(hit_cfg, jarvis_config.KeyLookup("from_config_value", "config"))

            dotenv_file.write_text("# comment only\n", encoding="utf-8")
            hit_cfg2 = jarvis_config.lookup_api_key(
                environ={},
                dotenv_path=dotenv_file,
                config_path=cfg_file,
            )
            self.assertEqual(hit_cfg2, jarvis_config.KeyLookup("from_config_value", "config"))

    def test_missing_key_and_vertex_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_dotenv = Path(tmp) / ".env"
            missing_cfg = Path(tmp) / "config.json"
            with self.assertRaises(jarvis_config.NoApiKeyError):
                jarvis_config.resolve_api_key(
                    environ={}, dotenv_path=missing_dotenv, config_path=missing_cfg
                )
            with self.assertRaises(RuntimeError):
                jarvis_config.resolve_api_key(
                    environ={"GOOGLE_GENAI_USE_VERTEXAI": "true", "GEMINI_API_KEY": "x"},
                    dotenv_path=missing_dotenv,
                    config_path=missing_cfg,
                )

    def test_load_non_secret_dotenv_skips_api_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            dotenv_file = Path(tmp) / ".env"
            dotenv_file.write_text(
                "GEMINI_API_KEY=secret1\nGOOGLE_API_KEY=secret2\nJARVIS_VOICE=Aoede\n",
                encoding="utf-8",
            )
            env: dict[str, str] = {}
            jarvis_config.load_non_secret_dotenv_into_environ(dotenv_file, env)
            self.assertEqual(env, {"JARVIS_VOICE": "Aoede"})


class KeyValidationAndRedactionTest(unittest.TestCase):

    def test_validate_uses_header_not_url_and_accepts_200(self):
        captured = {}

        def fake_opener(req, timeout):
            captured["url"] = req.full_url
            captured["header"] = req.get_header("X-goog-api-key")
            captured["timeout"] = timeout
            return _FakeHttpResponse({"models": [{"name": "models/gemini-2.5-flash"}]})

        fake_key = "AIzaSyFakeUnitTestKeyValue00000001"
        res = jarvis_config.validate_gemini_api_key(fake_key, opener=fake_opener)
        self.assertTrue(res.ok)
        self.assertNotIn(fake_key, captured["url"])
        self.assertEqual(captured["header"], fake_key)
        self.assertNotIn(fake_key, res.message)

    def test_validate_handles_rejected_expired_forbidden_and_network_errors_without_leaking_key(self):
        fake_key = "AIzaSyFakeUnitTestKeyValue99999999"

        def raise_http(code: int, body_obj: dict[str, object]):
            def _opener(req, _timeout):
                raw = io.BytesIO(json.dumps(body_obj).encode("utf-8"))
                raise urllib.error.HTTPError(req.full_url, code, "err", hdrs=None, fp=raw)  # type: ignore[arg-type]

            return _opener

        # Google's DebugInfo echoes the invalid key back; verify we never include it.
        res_bad = jarvis_config.validate_gemini_api_key(
            fake_key,
            opener=raise_http(
                400,
                {
                    "error": {
                        "code": 400,
                        "message": "API key not valid. Please pass a valid API key.",
                        "details": [{"detail": f"Invalid API key: {fake_key}"}],
                    }
                },
            ),
        )
        self.assertFalse(res_bad.ok)
        self.assertEqual(res_bad.error_kind, "rejected")
        self.assertIn("rejected", res_bad.message.lower())
        self.assertNotIn(fake_key, res_bad.message)

        res_exp = jarvis_config.validate_gemini_api_key(
            fake_key,
            opener=raise_http(400, {"error": {"message": "API key expired."}}),
        )
        self.assertFalse(res_exp.ok)
        self.assertIn("expired", res_exp.message.lower())

        res_403 = jarvis_config.validate_gemini_api_key(
            fake_key,
            opener=raise_http(403, {"error": {"status": "PERMISSION_DENIED"}}),
        )
        self.assertFalse(res_403.ok)
        self.assertEqual(res_403.error_kind, "rejected")

        def raise_offline(_req, _timeout):
            raise urllib.error.URLError("nodename nor servname provided")

        res_net = jarvis_config.validate_gemini_api_key(fake_key, opener=raise_offline)
        self.assertFalse(res_net.ok)
        self.assertEqual(res_net.error_kind, "network")
        self.assertIn("internet connection", res_net.message.lower())

    def test_redact_and_classify_auth_errors(self):
        fake = "AIzaSySecretTokenForRedactionTest1234"
        raw = f"ClientError: Invalid API key: {fake} (also custom_tok_9876)"
        redacted = jarvis_config.redact_secrets(raw, "custom_tok_9876")
        self.assertNotIn(fake, redacted)
        self.assertNotIn("custom_tok_9876", redacted)

        ws_err = RuntimeError("1007 None. API key not valid. Please pass a valid API key.")
        reason = jarvis_config.classify_gemini_auth_error(ws_err, "", fake)
        self.assertIsNotNone(reason)
        self.assertIn("rejected", (reason or "").lower())

        audio_err = RuntimeError("Invalid output device index 99")
        self.assertIsNone(jarvis_config.classify_gemini_auth_error(audio_err, ""))


class MacPermissionsTest(unittest.TestCase):

    def test_microphone_screen_and_accessibility_statuses(self):
        self.assertEqual(mac_permissions.check_microphone(lambda: 3).status, "granted")
        self.assertEqual(mac_permissions.check_microphone(lambda: 0).status, "prompt")
        self.assertEqual(mac_permissions.check_microphone(lambda: 2).status, "denied")
        mic_unknown = mac_permissions.check_microphone(lambda: None)
        self.assertEqual(mic_unknown.status, "unknown")
        self.assertFalse(mic_unknown.detectable)
        self.assertIn("cannot be detected", mic_unknown.detail.lower())

        self.assertEqual(mac_permissions.check_screen_recording(lambda: True).status, "granted")
        self.assertEqual(mac_permissions.check_screen_recording(lambda: False).status, "denied")
        self.assertEqual(mac_permissions.check_screen_recording(lambda: None).status, "unknown")

        self.assertEqual(mac_permissions.check_accessibility(lambda: True).status, "granted")
        self.assertEqual(mac_permissions.check_accessibility(lambda: False).status, "denied")
        self.assertEqual(mac_permissions.check_accessibility(lambda: None).status, "unknown")

    def test_automation_statuses_including_undetectable_targets(self):
        both_ok = mac_permissions.check_automation(
            lambda: {"com.google.Chrome": 0, "com.apple.systemevents": 0}
        )
        self.assertEqual(both_ok.status, "granted")

        chrome_denied = mac_permissions.check_automation(
            lambda: {"com.google.Chrome": -1743, "com.apple.systemevents": 0}
        )
        self.assertEqual(chrome_denied.status, "denied")
        self.assertIn("Chrome", chrome_denied.detail)

        partial = mac_permissions.check_automation(
            lambda: {"com.google.Chrome": 0, "com.apple.systemevents": -600}
        )
        self.assertEqual(partial.status, "unknown")
        self.assertFalse(partial.detectable)
        self.assertIn("cannot be detected", partial.detail.lower())

        neither = mac_permissions.check_automation(lambda: None)
        self.assertEqual(neither.status, "unknown")
        self.assertFalse(neither.detectable)
        self.assertIn("cannot be detected", neither.detail.lower())

    def test_open_privacy_pane_invokes_open_with_matching_anchor(self):
        calls: list[list[str]] = []
        for perm_id in ("microphone", "screen_recording", "accessibility", "automation"):
            ok = mac_permissions.open_privacy_pane(perm_id, runner=calls.append)
            self.assertTrue(ok)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(cmd[0] == "open" and "Privacy_" in cmd[1] for cmd in calls))
        self.assertFalse(mac_permissions.open_privacy_pane("bogus", runner=calls.append))


class WebviewBridgeSetupFlowTest(unittest.TestCase):

    def test_bridge_saves_valid_key_never_exposes_key_and_reopens_on_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_secret = "AIzaSyBridgeFlowFakeSecret00012345"
            env = {"JARVIS_CONFIG_DIR": tmp, "JARVIS_NO_DOTENV": "1"}
            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(
                    mac_permissions,
                    "check_all_permissions",
                    return_value=[{"id": "microphone", "name": "Microphone", "status": "granted"}],
                ),
            ):
                bridge = jarvis_app.WebviewBridge(initial_setup=True)
                bridge.mark_ready()

                state0 = bridge.get_setup_state()
                self.assertFalse(state0["has_key"])
                self.assertTrue(state0["setup_open"])

                with mock.patch.object(
                    jarvis_config,
                    "validate_gemini_api_key",
                    return_value=jarvis_config.ValidationResult(ok=True, message="Verified."),
                ):
                    saved_res = bridge.validate_and_save_key(fake_key := fake_secret)
                self.assertTrue(saved_res["ok"])
                self.assertNotIn(fake_key, json.dumps(saved_res))

                state1 = bridge.get_setup_state()
                self.assertTrue(state1["has_key"])
                self.assertEqual(state1["source"], "config")
                self.assertNotIn(fake_key, json.dumps(state1))

                # Simulate starting Jarvis and then Gemini rejecting the saved key on connect.
                bridge.setup_open = False

                async def fake_rejected_run(_ui, _ctl):
                    raise jarvis_config.ApiKeyRejectedError(
                        "Gemini rejected the saved API key. Paste a valid key from Google AI Studio."
                    )

                with mock.patch.object(bot, "run_jarvis", side_effect=fake_rejected_run):
                    bridge._pipeline_gen = 1
                    bridge._pipeline_entry(bridge.control, 1)

                self.assertTrue(bridge.setup_open)
                self.assertIn("rejected", bridge.setup_reason.lower())

    def test_open_external_only_allows_https(self):
        bridge = jarvis_app.WebviewBridge(initial_setup=True)
        with mock.patch.object(jarvis_app.subprocess, "Popen") as popen_mock, mock.patch.object(
            jarvis_app.webbrowser, "open"
        ) as wb_mock:
            self.assertFalse(bridge.open_external("file:///etc/passwd"))
            self.assertFalse(bridge.open_external("javascript:alert(1)"))
            self.assertTrue(bridge.open_external("https://aistudio.google.com/apikey"))
            self.assertTrue(popen_mock.called or wb_mock.called)


class RunJarvisRejectedKeyPipelineTest(unittest.IsolatedAsyncioTestCase):

    async def test_run_jarvis_raises_api_key_rejected_on_pipeline_auth_error_frame(self):
        from pipecat.frames.frames import LLMContextFrame
        from pipecat.processors.frame_processor import FrameProcessor
        import pipecat.transports.local.audio as local_audio_mod

        class _DummyEndpoint(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                await self.push_frame(frame, direction)

        class _FakeTransport:
            def __init__(self, _params):
                self._in = _DummyEndpoint()
                self._out = _DummyEndpoint()

            def input(self):
                return self._in

            def output(self):
                return self._out

        class _RejectingLLM(FrameProcessor):
            Settings = bot.GeminiLiveLLMService.Settings

            def __init__(self, **kwargs):
                super().__init__()
                self.api_key = kwargs.get("api_key")

            def register_function(self, *args, **kwargs):
                pass

            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, LLMContextFrame):
                    await self.push_error(
                        error_msg="Max consecutive failures (3) reached, treating as fatal error",
                        exception=RuntimeError(
                            "1007 None. API key not valid. Please pass a valid API key."
                        ),
                        force_treat_as_permanent=True,
                    )
                    return
                await self.push_frame(frame, direction)

        class _DummyUi:
            def __init__(self):
                self.events = []

            def emit(self, ev):
                self.events.append(ev)

            async def request_approval(self, action, reason):
                return False

        ui = _DummyUi()
        env = {"GEMINI_API_KEY": "AIzaSyBogusTestKeyForPipeline0001", "JARVIS_ECHO_GUARD": "off"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(local_audio_mod, "LocalAudioTransport", _FakeTransport),
            mock.patch.object(bot, "GeminiLiveLLMService", _RejectingLLM),
        ):
            with self.assertRaises(jarvis_config.ApiKeyRejectedError) as ctx:
                await bot.run_jarvis(ui)
            self.assertIn("rejected", str(ctx.exception).lower())
            self.assertNotIn("AIzaSyBogusTestKeyForPipeline0001", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
