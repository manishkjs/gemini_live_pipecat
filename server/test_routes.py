import sys
import os
import unittest

server_dir = os.path.dirname(os.path.abspath(__file__))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from fastapi.testclient import TestClient
from server import app
from tracing import GLOBAL_LANGSMITH_TRACER

class TestDiagnosticsAndTracing(unittest.TestCase):
    """Diagnostics routes are scoped to one session and gated by its capability token."""

    SESSION = "s_diag"

    def setUp(self):
        import diagnostic_buffer
        import session_access
        self.db = diagnostic_buffer
        self.access = session_access
        self.access._sessions.clear()
        self.db.DIAGNOSTIC_LOG_BUFFER.clear()
        self.db.TURN_LATENCY_RECORDS.clear()
        _, token, _ = self.access.issue(self.SESSION)
        self.headers = {"X-Session-Token": token}
        self.client = TestClient(app)

    def tearDown(self):
        self.db.bind_session(None)
        self.db.DIAGNOSTIC_LOG_BUFFER.clear()
        self.db.TURN_LATENCY_RECORDS.clear()
        self.access._sessions.clear()

    def test_diagnostics_route(self):
        # The standalone telemetry page was retired with the Voice Studio
        # redesign; /diagnostics now serves the studio (whose observability
        # drawer reads /api/logs) and must never be cached.
        r = self.client.get("/diagnostics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("no-store", r.headers["cache-control"])

    def test_logs_endpoint(self):
        self.db.bind_session(self.SESSION)
        self.db.record_metric(self.SESSION, 1, "gemini-live", "live_ttfb", 380.0)
        self.db.append_raw_log_entry("LLM Latency: 0.450s")
        self.db.bind_session(None)
        r = self.client.get(f"/api/logs?session_id={self.SESSION}", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["session_id"], self.SESSION)
        self.assertIn("LLM Latency: 0.450s", [entry["message"] for entry in data["logs"]])
        self.assertEqual(data["latency_summary"]["live_ttfb"]["p50"], 380.0)

    def test_latency_metrics_endpoint(self):
        r = self.client.get(f"/api/metrics/latency?session_id={self.SESSION}", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for key in ("live_ttfb", "llm", "stt", "tts", "total_turnaround", "vad_stop_to_first_server_audio"):
            self.assertIn(key, data)

    def test_trace_endpoint(self):
        r = self.client.get(f"/api/trace/current?session_id={self.SESSION}", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("trace_url", r.json())

    def test_tracer_session(self):
        url = GLOBAL_LANGSMITH_TRACER.start_session("test_sess", "gemini-live-2.5-flash-native-audio", "Puck", "en-US")
        self.assertIsNotNone(url)
        GLOBAL_LANGSMITH_TRACER.record_user_turn("Hello Gemini")
        GLOBAL_LANGSMITH_TRACER.record_bot_turn("Hello!", ttfb_ms=350.0)
        GLOBAL_LANGSMITH_TRACER.record_tool_call("get_current_time", {}, "14:15 UTC", 10.0)
        GLOBAL_LANGSMITH_TRACER.record_interruption(200.0)
        GLOBAL_LANGSMITH_TRACER.end_session("Session finished")


class TestThinkingConfig(unittest.TestCase):
    """Gemini 3 rejects requests that carry both thinking_budget and
    thinking_level, so the Live path must only ever emit thinking_level."""

    def test_disabled_by_default(self):
        from agent_live import build_thinking_config
        self.assertEqual(build_thinking_config("gemini-3.5-flash-live-preview", False, None), {})

    def test_never_emits_deprecated_budget(self):
        from agent_live import build_thinking_config
        models = [
            "gemini-3.5-flash-live-preview",
            "gemini-3.1-flash-live-preview",
            "gemini-3.5-flash-lite-live-preview",
            "gemini-live-2.5-flash-native-audio",
        ]
        for model in models:
            for level in [None, "minimal", "low", "medium", "high"]:
                config = build_thinking_config(model, True, level)
                self.assertNotIn("thinking_budget", config, f"{model}/{level} leaked thinking_budget")

    def test_explicit_level_is_forwarded(self):
        from agent_live import build_thinking_config
        for level in ["minimal", "low", "medium", "high"]:
            config = build_thinking_config("gemini-3.5-flash-live-preview", True, level)
            self.assertEqual(config, {"thinking_level": level})

    def test_unknown_level_falls_back_instead_of_forwarding_garbage(self):
        from agent_live import build_thinking_config
        config = build_thinking_config("gemini-3.5-flash-live-preview", True, "turbo")
        self.assertEqual(config, {"thinking_level": "medium"})

    def test_latency_sensitive_models_default_to_minimal(self):
        from agent_live import build_thinking_config
        self.assertEqual(
            build_thinking_config("gemini-3.1-flash-live-preview", True, None),
            {"thinking_level": "minimal"},
        )
        self.assertEqual(
            build_thinking_config("gemini-3.5-flash-lite-live-preview", True, None),
            {"thinking_level": "minimal"},
        )

    def test_thinking_named_model_reasons_without_opt_in(self):
        from agent_live import build_thinking_config
        config = build_thinking_config("gemini-3.5-live-extended-thinking-preview", False, None)
        self.assertEqual(config, {"thinking_level": "medium"})


class TestSystemPromptComposition(unittest.TestCase):
    """A caller-supplied system instruction is authoritative.

    An earlier revision appended a global "never ask for the user's name" rule
    to every Live session, which silently contradicted custom instructions and
    changed the behaviour of the original client. These tests keep that from
    coming back.
    """

    def test_custom_instruction_is_not_rewritten(self):
        from agent_live import compose_live_system_prompt
        instruction = "You are a receptionist. Ask the caller for their name and greet them by it."
        prompt = compose_live_system_prompt(instruction, "female", "en-US")
        self.assertTrue(prompt.startswith(instruction), "The caller's instruction must survive verbatim")
        self.assertNotIn("Never ask for the user's name", prompt)

    def test_custom_instruction_only_gains_the_language_directive(self):
        from agent_live import compose_live_system_prompt
        instruction = "Be terse."
        prompt = compose_live_system_prompt(instruction, "female", "hi-IN")
        self.assertEqual(prompt, "Be terse.\n\nIMPORTANT: You must converse in hi-IN language.")

    def test_default_prompt_still_carries_the_shared_house_rules(self):
        from agent_live import compose_live_system_prompt
        prompt = compose_live_system_prompt(None, "female", "en-US")
        self.assertIn("Never ask for the user's name", prompt)
        self.assertIn("gender-neutral", prompt)

    def test_default_prompt_still_honours_voice_gender(self):
        from agent_live import compose_live_system_prompt
        male = compose_live_system_prompt(None, "male", "en-US")
        self.assertIn("male AI assistant", male)
        self.assertNotIn("female AI assistant", male)


class TestVadPlumbing(unittest.TestCase):
    """The VAD toggle must reach the transport, not stop at the UI."""

    def test_enabled_builds_an_analyzer(self):
        from agent_live import build_live_vad_analyzer
        self.assertIsNotNone(build_live_vad_analyzer(True))

    def test_disabled_defers_to_server_side_turn_detection(self):
        from agent_live import build_live_vad_analyzer
        self.assertIsNone(build_live_vad_analyzer(False))

    def test_both_engines_accept_a_vad_argument(self):
        import inspect
        from agent_live import run_agent_live
        from agent import run_agent
        for fn in (run_agent_live, run_agent):
            self.assertIn("vad", inspect.signature(fn).parameters, f"{fn.__name__} ignores the VAD toggle")

    def test_websocket_endpoint_accepts_vad_and_rejects_raw_keys(self):
        import inspect
        from server import websocket_endpoint
        params = inspect.signature(websocket_endpoint).parameters
        self.assertIn("vad", params)
        self.assertIn("voice_profile_id", params)
        self.assertNotIn(
            "custom_voice_key",
            params,
            "The WebSocket URL is logged; it must only ever carry an opaque profile id",
        )


class TestVoiceProfileRegistry(unittest.TestCase):
    def setUp(self):
        import voice_profiles
        voice_profiles.clear()

    def test_key_is_exchanged_for_an_opaque_handle(self):
        import voice_profiles
        secret = "super-secret-cloning-key"
        profile_id = voice_profiles.register(secret)
        self.assertTrue(voice_profiles.is_profile_id(profile_id))
        self.assertNotIn(secret, profile_id)
        self.assertEqual(voice_profiles.consume(profile_id), secret)

    def test_handles_are_single_use(self):
        import voice_profiles
        profile_id = voice_profiles.register("k")
        self.assertEqual(voice_profiles.consume(profile_id), "k")
        self.assertIsNone(voice_profiles.consume(profile_id))

    def test_handles_expire(self):
        import voice_profiles
        profile_id = voice_profiles.register("k", ttl_seconds=-1)
        self.assertIsNone(voice_profiles.consume(profile_id))

    def test_empty_and_unknown_inputs_are_inert(self):
        import voice_profiles
        self.assertIsNone(voice_profiles.register(""))
        self.assertIsNone(voice_profiles.register("   "))
        self.assertIsNone(voice_profiles.register(None))
        self.assertIsNone(voice_profiles.consume("vp_does-not-exist"))
        self.assertIsNone(voice_profiles.consume(None))

    def test_connect_never_puts_the_key_in_the_websocket_url(self):
        import voice_profiles
        secret = "cloning-key-that-must-not-leak"
        client = TestClient(app)
        response = client.post("/connect?bot_type=gemini-live", json={"custom_voice_key": secret})
        self.assertEqual(response.status_code, 200)
        ws_url = response.json()["ws_url"]
        self.assertNotIn(secret, ws_url)
        self.assertIn("voice_profile_id=vp_", ws_url)
        self.assertEqual(voice_profiles.active_count(), 1)


class TestSessionScopedDiagnostics(unittest.TestCase):
    """One process serves many demoers; their metrics must not blend together."""

    def setUp(self):
        import diagnostic_buffer
        import session_access
        self.db = diagnostic_buffer
        self.access = session_access
        self.access._sessions.clear()
        self.db.DIAGNOSTIC_LOG_BUFFER.clear()
        self.db.TURN_LATENCY_RECORDS.clear()
        self.db.bind_session(None)
        self.client = TestClient(app)

    def tearDown(self):
        self.db.bind_session(None)
        self.db.DIAGNOSTIC_LOG_BUFFER.clear()
        self.db.TURN_LATENCY_RECORDS.clear()
        self.access._sessions.clear()

    def _log_as(self, session_id, message):
        self.db.bind_session(session_id)
        self.db.append_raw_log_entry(message)

    def test_records_carry_the_session_that_produced_them(self):
        self._log_as("s_alice", "alice speaking")
        self.db.record_metric("s_alice", 1, "tts-llm-stt", "llm", 120.0)
        entry = self.db.DIAGNOSTIC_LOG_BUFFER[-1]
        self.assertEqual(entry["session_id"], "s_alice")
        self.assertEqual(self.db.TURN_LATENCY_RECORDS[-1]["session_id"], "s_alice")

    def test_one_session_never_sees_anothers_logs(self):
        self._log_as("s_alice", "alice speaking")
        self._log_as("s_bob", "bob speaking")
        alice = self.db.get_recent_diagnostic_logs(session_id="s_alice")
        messages = [r["message"] for r in alice]
        self.assertIn("alice speaking", messages)
        self.assertNotIn("bob speaking", messages)

    def test_latency_percentiles_are_computed_per_session(self):
        self.db.record_metric("s_alice", 1, "tts-llm-stt", "llm", 100.0)
        self.db.record_metric("s_bob", 1, "tts-llm-stt", "llm", 900.0)
        alice = self.db.get_latency_summary(session_id="s_alice")
        self.assertEqual(alice["llm"]["count"], 1)
        self.assertEqual(alice["llm"]["max"], 100.0)

    def test_unscoped_process_logs_never_leak_into_a_session(self):
        # Since cd553ad, logs emitted outside any session are retained as
        # __unscoped__ and excluded from every session's view.
        self.db.append_raw_log_entry("uvicorn started")
        self._log_as("s_alice", "alice speaking")
        self.assertEqual(self.db.DIAGNOSTIC_LOG_BUFFER[0]["session_id"], self.db.UNSCOPED)
        bob = [r["message"] for r in self.db.get_recent_diagnostic_logs(session_id="s_bob")]
        self.assertNotIn("uvicorn started", bob)
        self.assertNotIn("alice speaking", bob)

    def test_clearing_one_session_leaves_the_others_intact(self):
        self._log_as("s_alice", "alice speaking")
        self._log_as("s_bob", "bob speaking")
        self.db.clear_diagnostic_logs(session_id="s_alice")
        remaining = [r["message"] for r in self.db.DIAGNOSTIC_LOG_BUFFER]
        self.assertNotIn("alice speaking", remaining)
        self.assertIn("bob speaking", remaining)

    def test_clearing_requires_an_explicit_session(self):
        # An unscoped clear would let one demoer wipe everyone's telemetry.
        self._log_as("s_alice", "alice speaking")
        with self.assertRaises(ValueError):
            self.db.clear_diagnostic_logs()
        self.assertEqual(len(self.db.DIAGNOSTIC_LOG_BUFFER), 1)

    def test_logs_endpoint_filters_and_echoes_the_scope(self):
        _, token, _ = self.access.issue("s_bob")
        self._log_as("s_alice", "alice speaking")
        self._log_as("s_bob", "bob speaking")
        response = self.client.get("/api/logs?session_id=s_bob", headers={"X-Session-Token": token})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], "s_bob")
        messages = [r["message"] for r in payload["logs"]]
        self.assertIn("bob speaking", messages)
        self.assertNotIn("alice speaking", messages)

    def test_websocket_endpoint_accepts_a_session_id(self):
        import inspect
        from server import websocket_endpoint
        self.assertIn("session_id", inspect.signature(websocket_endpoint).parameters)


if __name__ == "__main__":
    unittest.main()
