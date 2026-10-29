import atexit
import os
import shutil
import sys
import unittest

server_dir = os.path.dirname(os.path.abspath(__file__))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

_repo_root = os.path.abspath(os.path.join(server_dir, ".."))
_existing_dist = any(
    os.path.exists(os.path.join(_repo_root, rel))
    for rel in ("demos/voice-studio/dist", "client/dist")
)
if not _existing_dist:
    _fallback_dist = os.path.join(_repo_root, "client", "dist")
    os.makedirs(os.path.join(_fallback_dist, "assets"), exist_ok=True)
    with open(os.path.join(_fallback_dist, "index.html"), "w", encoding="utf-8") as _fh:
        _fh.write("<!doctype html><html><body>Voice Studio test fixture</body></html>\n")
    atexit.register(shutil.rmtree, _fallback_dist, True)

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


class TestLiveAvatarAndInterruptionResilience(unittest.IsolatedAsyncioTestCase):
    """Regression tests for multi-turn Live Avatar stream alignment and interruption handling."""

    def test_extract_complete_mp4_segments_reassembles_16k_slices(self):
        import struct
        from agent_live import extract_complete_mp4_segments

        def make_box(btype: bytes, payload_len: int) -> bytes:
            return struct.pack(">I4s", payload_len + 8, btype) + (b"x" * payload_len)

        ftyp = make_box(b"ftyp", 20)      # 28 bytes
        moov = make_box(b"moov", 1298)    # 1306 bytes -> init = 1334 bytes
        moof1 = make_box(b"moof", 96)     # 104 bytes
        mdat1 = make_box(b"mdat", 40000)  # 40008 bytes
        moof2 = make_box(b"moof", 100)    # 108 bytes
        mdat2 = make_box(b"mdat", 1365)   # 1373 bytes

        full_stream = ftyp + moov + moof1 + mdat1 + moof2 + mdat2
        buf = bytearray()
        emitted = []

        # Feed in 16,384-byte transport slices just like Vertex AI Live Avatar
        for i in range(0, len(full_stream), 16384):
            buf.extend(full_stream[i:i + 16384])
            emitted.extend(extract_complete_mp4_segments(buf))

        self.assertEqual(len(buf), 0)
        self.assertGreaterEqual(len(emitted), 2)
        # First emitted segment must be the exact ftyp + moov init segment
        self.assertTrue(emitted[0][1])
        self.assertEqual(emitted[0][0], ftyp + moov)
        # Subsequent segments must be non-init and contain complete moof+mdat boxes
        for seg_bytes, is_init in emitted[1:]:
            self.assertFalse(is_init)
            self.assertEqual(seg_bytes[4:8], b"moof")
        reassembled = b"".join(seg for seg, _ in emitted)
        self.assertEqual(reassembled, full_stream)

    async def test_usage_metadata_handles_none_prompt_tokens_on_interrupted_turn(self):
        from types import SimpleNamespace
        from agent_live import GeminiSessionLoggerMixin

        class DummyService(GeminiSessionLoggerMixin):
            def __init__(self):
                self._context_compression_enabled = True
                self._context_compression_trigger_tokens = 5000
                self._last_prompt_tokens = 1848
                self.pushed = []

            async def push_frame(self, frame, direction=None):
                self.pushed.append(frame)

        class BaseStub:
            async def _handle_msg_usage_metadata(self, message):
                pass

        class TestService(DummyService, BaseStub):
            pass

        svc = TestService()
        msg = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=None,
                response_token_count=6,
                total_token_count=6,
                cached_content_token_count=None,
                thoughts_token_count=None,
                tool_use_prompt_token_count=None,
                prompt_tokens_details=None,
                response_tokens_details=[SimpleNamespace(modality="TEXT", token_count=6)],
            )
        )
        # Must not raise TypeError: '>' not supported between instances of 'int' and 'NoneType'
        await svc._handle_msg_usage_metadata(msg)
        self.assertEqual(svc._last_prompt_tokens, 1848)
        self.assertEqual(len(svc.pushed), 1)

    async def test_spurious_interruption_frame_ignored_when_bot_not_responding(self):
        from pipecat.frames.frames import InterruptionFrame
        from agent_live import GeminiSessionLoggerMixin

        class BaseStub:
            async def process_frame(self, frame, direction=None):
                pass

        class TestService(GeminiSessionLoggerMixin, BaseStub):
            def __init__(self):
                self._bot_is_responding = False
                self._bot_turn_text_buffer = ""
                self._my_ttfb_start = None
                self.pushed = []

            async def push_frame(self, frame, direction=None):
                self.pushed.append(frame)

        svc = TestService()
        await svc.process_frame(InterruptionFrame(), None)
        # When bot is silent between turns, LLMUserAggregator's InterruptionFrame must not emit interruption metrics
        self.assertEqual(len(svc.pushed), 0)
        self.assertFalse(getattr(svc, "_repeat_on_filler_pending", False))

        # When bot IS responding, InterruptionFrame must emit interruption metrics.
        # The mixin tracks this itself; Pipecat's private _bot_is_responding is off-limits.
        svc._mixin_bot_responding = True
        await svc.process_frame(InterruptionFrame(), None)
        self.assertEqual(len(svc.pushed), 1)
        self.assertTrue(getattr(svc, "_repeat_on_filler_pending", False))


class TestVisitCounterRoutes(unittest.TestCase):
    """Visit counter starts at 0 (never fudged), deduplicates per page load, and persists to disk."""

    def setUp(self):
        import tempfile
        import visit_counter
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store_path = os.path.join(self.tmpdir.name, "studio_visits.json")
        visit_counter.configure_store(self.store_path)
        self.client = TestClient(app)

    def tearDown(self):
        import visit_counter
        visit_counter.configure_store(None)
        self.tmpdir.cleanup()

    def test_get_and_post_visits_increment_and_persist(self):
        import visit_counter
        r0 = self.client.get("/api/visits")
        self.assertEqual(r0.status_code, 200)
        self.assertEqual(r0.json()["visits"], 0)
        self.assertEqual(r0.json()["label"], "live studio visits")

        r1 = self.client.post("/api/visits", json={"page_load_id": "pl_first"})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["visits"], 1)

        # Duplicate POST with the same page_load_id (e.g. React StrictMode double effect) must be idempotent
        r1_dup = self.client.post("/api/visits", json={"page_load_id": "pl_first"})
        self.assertEqual(r1_dup.status_code, 200)
        self.assertEqual(r1_dup.json()["visits"], 1)

        # A new page load increments the counter and persists across store reload
        r2 = self.client.post("/api/visits", json={"page_load_id": "pl_second"})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["visits"], 2)

        visit_counter.configure_store(self.store_path)
        r3 = self.client.get("/api/visits")
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["visits"], 2)

    def test_firestore_targets_dedicated_v2v_demo_visits_db(self):
        import visit_counter
        prev = os.environ.get("GCP_PROJECT_ID")
        try:
            os.environ["GCP_PROJECT_ID"] = "example-gcp-project"
            self.assertEqual(
                visit_counter._firestore_db_path(),
                "projects/example-gcp-project/databases/v2v-demo-visits",
            )
            self.assertEqual(
                visit_counter._firestore_doc_path(),
                "projects/example-gcp-project/databases/v2v-demo-visits/documents/studio_telemetry/v2v_demo_visits",
            )
        finally:
            if prev is None:
                os.environ.pop("GCP_PROJECT_ID", None)
            else:
                os.environ["GCP_PROJECT_ID"] = prev

    def test_firestore_transient_failure_does_not_poison_retry_or_double_fetch(self):
        import visit_counter
        from unittest.mock import patch

        visit_counter._use_firestore = True
        visit_counter._firestore_synced = False
        visit_counter._count = 42
        visit_counter._seen_page_loads.clear()

        lock_held_during_io = []

        def fake_fail_inc():
            lock_held_during_io.append(visit_counter._lock.locked())
            return None

        with patch.object(visit_counter, "_firestore_increment_visits", side_effect=fake_fail_inc) as mock_inc, \
             patch.object(visit_counter, "_firestore_get_visits", return_value=None) as mock_get:
            r_fail = self.client.post("/api/visits", json={"page_load_id": "pl_retry_1"})
            self.assertEqual(r_fail.status_code, 200)
            self.assertEqual(r_fail.json()["visits"], 42)
            self.assertEqual(mock_inc.call_count, 1)
            self.assertEqual(mock_get.call_count, 0)
            self.assertFalse(visit_counter._firestore_synced)
            self.assertEqual(lock_held_during_io, [False])
            self.assertNotIn("pl_retry_1", visit_counter._seen_page_loads)

        with patch.object(visit_counter, "_firestore_increment_visits", return_value=101) as mock_inc2, \
             patch.object(visit_counter, "_firestore_get_visits", return_value=101) as mock_get2:
            r_ok = self.client.post("/api/visits", json={"page_load_id": "pl_retry_1"})
            self.assertEqual(r_ok.status_code, 200)
            self.assertEqual(r_ok.json()["visits"], 101)
            self.assertTrue(visit_counter._firestore_synced)
            self.assertEqual(mock_inc2.call_count, 1)
            self.assertEqual(mock_get2.call_count, 0)

            # Duplicate page_load_id and subsequent GET /api/visits must use cached _count without hitting Firestore
            r_dup = self.client.post("/api/visits", json={"page_load_id": "pl_retry_1"})
            self.assertEqual(r_dup.status_code, 200)
            self.assertEqual(r_dup.json()["visits"], 101)
            r_get = self.client.get("/api/visits")
            self.assertEqual(r_get.status_code, 200)
            self.assertEqual(r_get.json()["visits"], 101)
            self.assertEqual(mock_inc2.call_count, 1)
            self.assertEqual(mock_get2.call_count, 0)

    def test_post_visits_rejects_oversized_payload(self):
        r_big = self.client.post("/api/visits", content=b"x" * 5000)
        self.assertEqual(r_big.status_code, 413)

    def test_concurrent_same_page_load_id_increments_firestore_only_once(self):
        import threading
        import visit_counter
        from unittest.mock import patch

        visit_counter._use_firestore = True
        visit_counter._firestore_synced = True
        visit_counter._count = 10
        visit_counter._seen_page_loads.clear()
        visit_counter._inflight_page_loads.clear()

        entered = threading.Event()
        release = threading.Event()
        lock_states = []

        def slow_firestore_inc():
            lock_states.append(visit_counter._lock.locked())
            entered.set()
            release.wait(timeout=3.0)
            return 11

        results = []
        with patch.object(visit_counter, "_firestore_increment_visits", side_effect=slow_firestore_inc) as mock_inc:
            def worker():
                results.append(visit_counter.record_visit(page_load_id="pl_concurrent_race"))

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            self.assertTrue(entered.wait(timeout=2.0))
            release.set()
            for t in threads:
                t.join(timeout=3.0)

            self.assertEqual(mock_inc.call_count, 1)
            self.assertEqual(lock_states, [False])
            self.assertEqual(len(results), 8)
            for res in results:
                self.assertEqual(res["visits"], 11)


class TestCascadePromptAndToolParity(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import server
        import session_access

        session_access._sessions.clear()
        self.client = TestClient(server.app)

    def tearDown(self):
        import session_access

        session_access._sessions.clear()

    def test_cascade_prompt_never_appends_conflicting_name_rule_to_custom_or_tara_prompts(self):
        from agent import compose_cascade_system_prompt
        from persona_registry import get_persona_architecture

        custom = "Greet the caller warmly and ask for their full name and booking reference."
        composed_custom = compose_cascade_system_prompt(
            custom,
            tts_voice="Aoede",
            clean_tts_model="google-tts",
            persona_id="custom",
        )
        self.assertIn("ask for their full name", composed_custom)
        self.assertNotIn("Never ask for the user's name", composed_custom)

        tara_arch = get_persona_architecture("travel-concierge")
        tara_prompt = tara_arch.compose_system_prompt(None, engine="cascade")
        composed_tara = compose_cascade_system_prompt(
            tara_prompt,
            tts_voice="Kore",
            clean_tts_model="gemini-3.8-flash-lite-tts",
            persona_id="travel-concierge",
        )
        self.assertNotIn("Never ask for the user's name", composed_tara)

        # Default generic prompt (system_instruction=None) retains SYSTEM_PROMPT's built-in rule and voice gender
        composed_default = compose_cascade_system_prompt(
            None,
            tts_voice="Puck",
            clean_tts_model="google-tts",
            persona_id=None,
        )
        self.assertIn("male AI assistant", composed_default)
        self.assertIn("Never ask for the user's name", composed_default)

    def test_tool_overrides_replace_defaults_without_duplicates_in_live_and_cascade(self):
        import json
        from unittest.mock import MagicMock
        from persona_registry import get_persona_architecture
        from tool_catalog import register_runtime_tool_handlers, resolve_session_tools

        arch = get_persona_architecture("banking-advisor")
        override_payload = json.dumps([
            {
                "name": "get_current_time",
                "description": "Edited time tool description",
                "properties": {},
                "required": [],
            },
            {
                "name": "search_knowledge_base",
                "description": "Edited KB description",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            {
                "name": "lookup_wire_transfer",
                "description": "Custom wire lookup tool",
                "properties": {"ref": {"type": "string"}},
                "required": ["ref"],
            },
        ])

        for eng in ("live", "cascade"):
            schemas, overridden = resolve_session_tools(arch, engine=eng, tools_raw=override_payload)
            self.assertTrue(overridden)
            names = [s.name for s in schemas]
            self.assertEqual(names, ["get_current_time", "search_knowledge_base", "lookup_wire_transfer"])
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(schemas[0].description, "Edited time tool description")

            fake_llm = MagicMock()
            register_runtime_tool_handlers(
                fake_llm,
                active_schemas=schemas,
                persona_architecture=arch,
                broadcast=MagicMock(),
                engine=eng,
            )
            registered_names = [call.args[0] for call in fake_llm.register_function.call_args_list]
            self.assertIn("get_current_time", registered_names)
            self.assertIn("search_knowledge_base", registered_names)
            self.assertIn("lookup_wire_transfer", registered_names)

    def test_persona_prompt_tools_editable_flag_and_connect_tool_validation(self):
        import session_access

        # Tara on Vertex Gemini 3.8 Live swaps tools per card -> tools_editable is False
        r_tara_live = self.client.get("/persona-prompt/travel-concierge?engine=live&model=gemini-3.8-live")
        self.assertEqual(r_tara_live.status_code, 200)
        self.assertFalse(r_tara_live.json()["tools_editable"])

        # Tara in Cascade or standard personas in Live allow static tool overrides -> tools_editable is True
        r_tara_cascade = self.client.get("/persona-prompt/travel-concierge?engine=cascade")
        self.assertEqual(r_tara_cascade.status_code, 200)
        self.assertTrue(r_tara_cascade.json()["tools_editable"])

        r_debt_live = self.client.get("/persona-prompt/debt-collector?engine=live&model=gemini-3.8-live")
        self.assertEqual(r_debt_live.status_code, 200)
        self.assertTrue(r_debt_live.json()["tools_editable"])

        # Malformed JSON, invalid Gemini tool names, or duplicate tool names in /connect fail with HTTP 400 and allocate no session
        bad_json = self.client.post("/connect?session_id=bad_tools_1", json={"tools": "{not-valid-json"})
        self.assertEqual(bad_json.status_code, 400)
        dup_tools = self.client.post(
            "/connect?session_id=bad_tools_2",
            json={"tools": [{"name": "get_current_time"}, {"name": "get_current_time"}]},
        )
        self.assertEqual(dup_tools.status_code, 400)
        bad_name_space = self.client.post(
            "/connect?session_id=bad_tools_3",
            json={"tools": [{"name": "get weather"}]},
        )
        self.assertEqual(bad_name_space.status_code, 400)
        bad_name_digit = self.client.post(
            "/connect?session_id=bad_tools_4",
            json={"tools": [{"name": "1abc"}]},
        )
        self.assertEqual(bad_name_digit.status_code, 400)
        self.assertFalse(session_access._sessions)

        # T2: Cascade default tools do not declare Live-only get_current_time / search_knowledge_base
        r_debt_cascade = self.client.get("/persona-prompt/debt-collector?engine=cascade")
        self.assertEqual(r_debt_cascade.status_code, 200)
        cascade_tool_names = [t["name"] for t in r_debt_cascade.json()["tools"]]
        self.assertNotIn("get_current_time", cascade_tool_names)
        self.assertNotIn("search_knowledge_base", cascade_tool_names)

        # T1: Tara on Vertex Gemini 3.8 Live ignores any static client tools override in /connect
        tara_override = self.client.post(
            "/connect?session_id=tara_no_override&bot_type=gemini-live&persona_id=travel-concierge&model=gemini-3.8-live",
            json={"tools": [{"name": "stale_custom_tool"}]},
        )
        self.assertEqual(tara_override.status_code, 200)
        self.assertNotIn("stale_custom_tool", tara_override.json()["ws_url"])
        self.assertIsNone(session_access.take_handoff("tara_no_override")["tools"])

        # Large (>2048 char) valid tool override strips additionalProperties and stays in session handoff
        large_tools = [
            {
                "name": f"custom_tool_{i}",
                "description": "D" * 180,
                "properties": {"q": {"type": "string", "additionalProperties": False}, "additionalProperties": False},
                "required": [],
            }
            for i in range(15)
        ]
        ok_large = self.client.post("/connect?session_id=large_tools_ok", json={"tools": large_tools})
        self.assertEqual(ok_large.status_code, 200)
        ws_url = ok_large.json()["ws_url"]
        self.assertNotIn("custom_tool_0", ws_url)
        handoff = session_access.take_handoff("large_tools_ok")
        self.assertIn("custom_tool_14", handoff["tools"])
        self.assertNotIn("additionalProperties", handoff["tools"])


if __name__ == "__main__":
    unittest.main()

