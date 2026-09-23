import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import session_access
import voice_profiles


class TestSessionAccess(unittest.TestCase):
    def setUp(self):
        session_access._sessions.clear()
        voice_profiles.clear()

    def tearDown(self):
        session_access._sessions.clear()
        voice_profiles.clear()

    def test_capability_and_join_are_separate_and_join_is_single_use(self):
        sid, token, join = session_access.issue("A")
        self.assertTrue(session_access.authorized(sid, token))
        self.assertFalse(session_access.authorized(sid, join))
        self.assertFalse(session_access.authorized("B", token))
        self.assertFalse(session_access.consume_join(sid, token))
        self.assertTrue(session_access.consume_join(sid, join))
        self.assertFalse(session_access.consume_join(sid, join))
        self.assertTrue(session_access.authorized(sid, token))

    def test_existing_session_cannot_be_overwritten(self):
        _, token, _ = session_access.issue("A")
        with self.assertRaises(ValueError):
            session_access.issue("A", "x" * 32)
        self.assertTrue(session_access.authorized("A", token))

    def test_expiry_and_capacity(self):
        with patch("session_access.time.monotonic", return_value=0):
            _, token, join = session_access.issue("A")
        with patch("session_access.time.monotonic", return_value=301):
            self.assertFalse(session_access.consume_join("A", join))
            self.assertTrue(session_access.authorized("A", token))
        with patch("session_access.time.monotonic", return_value=15000):
            self.assertFalse(session_access.authorized("A", token))
            self.assertFalse(session_access._sessions)
        with patch("session_access.MAX_SESSIONS", 1):
            session_access.issue("A")
            with self.assertRaises(RuntimeError):
                session_access.issue("B")

    def test_real_routes_reject_missing_or_cross_session_access(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)
        created = client.post("/connect?session_id=A", headers={"X-Session-Token": "a" * 32}, json={})
        self.assertEqual(created.status_code, 200)
        self.assertNotIn("a" * 32, created.json()["ws_url"])
        for path in ("/api/logs", "/api/metrics/latency", "/api/trace/current"):
            self.assertEqual(client.get(path).status_code, 422)
            self.assertEqual(client.get(path + "?session_id=A").status_code, 403)
            self.assertEqual(client.get(path + "?session_id=A", headers={"X-Session-Token": "b" * 32}).status_code, 403)
        self.assertEqual(client.get("/api/logs?session_id=A", headers={"X-Session-Token": "a" * 32}).status_code, 200)
        self.assertEqual(client.post("/api/logs/clear").status_code, 422)
        self.assertEqual(client.post("/api/logs/clear?session_id=A").status_code, 403)

    def test_runtime_preset_matches_preview_and_custom_override_survives(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)
        query = "/connect?persona_id=storyteller&bot_type=tts-llm-stt&stt_language=hi-IN"
        response = client.post(query, json={"system_instruction": "stale browser preset", "prompt_source": "preset", "persona_tone": "signature"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn("system_instruction", data["ws_url"])
        expected = client.get("/persona-prompt/storyteller?engine=cascade&tone=signature&language=hi-IN").json()["prompt"]
        self.assertEqual(session_access.take_instructions(data["session_id"]), expected)
        self.assertIsNone(session_access.take_instructions(data["session_id"]))
        response = client.post(query, json={"system_instruction": "My own instructions"})
        self.assertEqual(session_access.take_instructions(response.json()["session_id"]), "My own instructions")

    def test_expired_unclaimed_prompts_are_removed_with_the_session(self):
        with patch("session_access.time.monotonic", return_value=0):
            session_access.issue("prompt")
            session_access.set_instructions("prompt", "Unclaimed prompt")
        with patch("session_access.time.monotonic", return_value=15000):
            self.assertIsNone(session_access.take_instructions("prompt"))
            self.assertFalse(session_access._sessions)

    def test_invalid_requests_do_not_exhaust_capacity_or_reserve_requested_id(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)
        with patch("session_access.MAX_SESSIONS", 1):
            for body in ({"system_instruction": 123}, {"custom_voice_key": []},
                         {"thinking": "false"}, {"prompt_source": []}, ["not an object"]):
                with self.subTest(body=body):
                    response = client.post("/connect?session_id=retry", json=body)
                    self.assertEqual(response.status_code, 400)
                    self.assertFalse(session_access._sessions)
                    self.assertEqual(voice_profiles.active_count(), 0)
            response = client.post("/connect", content="{broken", headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 400)
            response = client.post("/connect?bot_type=unknown", json={})
            self.assertEqual(response.status_code, 400)
            response = client.post("/connect?persona_id=storyteller&language=unknown",
                                   json={"prompt_source": "preset"})
            self.assertEqual(response.status_code, 400)
            self.assertFalse(session_access._sessions)
            self.assertEqual(client.post("/connect?session_id=retry", json={}).status_code, 200)

    def test_post_allocation_failure_releases_session_and_clone_profile(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)
        # Fail after the real profile registry accepted a dummy key.
        with patch("urllib.parse.urlencode", side_effect=RuntimeError("Unable to build URL")):
            response = client.post("/connect", json={
                "system_instruction": "Private prompt", "custom_voice_key": "dummy-clone-key"})
        self.assertEqual(response.status_code, 500)
        self.assertFalse(session_access._sessions)
        self.assertEqual(voice_profiles.active_count(), 0)
        self.assertNotIn("Private prompt", response.text)
        self.assertNotIn("dummy-clone-key", response.text)
        with patch("voice_profiles.register", side_effect=RuntimeError("Profile unavailable")):
            response = client.post("/connect", json={"custom_voice_key": "dummy-clone-key"})
        self.assertEqual(response.status_code, 500)
        self.assertFalse(session_access._sessions)

    def test_conflict_and_capacity_rejection_preserve_owner_and_allocate_no_profile(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)
        sid, token, join = session_access.issue("owner", instructions="Owner prompt")
        with patch("session_access.MAX_SESSIONS", 1):
            for requested_id, status in (("owner", 409), ("new", 503)):
                response = client.post(f"/connect?session_id={requested_id}", json={"custom_voice_key": "dummy-key"})
                self.assertEqual(response.status_code, status)
                self.assertEqual(voice_profiles.active_count(), 0)
                self.assertEqual(len(session_access._sessions), 1)
        self.assertTrue(session_access.authorized(sid, token))
        self.assertTrue(session_access.consume_join(sid, join))
        self.assertEqual(session_access.take_instructions(sid), "Owner prompt")

    def test_connection_handles_and_settings_survive_atomic_allocation(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)
        response = client.post("/connect?bot_type=gemini-live&system_instruction=LegacyPrompt", json={
            "system_instruction": "Body prompt", "custom_voice_key": "dummy-key",
            "tools": [{"name": "example"}], "context_compression": False,
            "context_compression_trigger_tokens": 100, "thinking": True,
            "thinking_level": "low", "vad": False})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        params = parse_qs(urlparse(data["ws_url"]).query)
        for private in ("system_instruction", "custom_voice_key"):
            self.assertNotIn(private, params)
        self.assertEqual(params["context_compression"], ["false"])
        self.assertEqual(params["context_compression_trigger_tokens"], ["5000"])
        self.assertEqual(params["thinking"], ["true"])
        self.assertEqual(params["thinking_level"], ["low"])
        self.assertEqual(params["vad"], ["false"])
        self.assertEqual(params["tools"], ['[{"name": "example"}]'])
        sid = data["session_id"]
        self.assertTrue(session_access.authorized(sid, data["diagnostic_token"]))
        self.assertTrue(session_access.consume_join(sid, params["connection_id"][0]))
        self.assertEqual(session_access.take_instructions(sid), "Body prompt")
        self.assertIsNone(session_access.take_instructions(sid))
        self.assertEqual(voice_profiles.consume(params["voice_profile_id"][0]), "dummy-key")
        self.assertIsNone(voice_profiles.consume(params["voice_profile_id"][0]))
        legacy = client.post("/connect?system_instruction=LegacyPrompt", json={}).json()
        self.assertNotIn("LegacyPrompt", legacy["ws_url"])
        self.assertEqual(session_access.take_instructions(legacy["session_id"]), "LegacyPrompt")

    def test_default_engine_preset_matches_websocket_cascade_default(self):
        from fastapi.testclient import TestClient
        import server
        from persona_prompt_cards import get_session_preset
        client = TestClient(server.app)
        response = client.post("/connect?persona_id=lamborghini-concierge", json={"prompt_source": "preset"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session_access.take_instructions(response.json()["session_id"]),
                         get_session_preset("lamborghini-concierge", engine="cascade"))

    def test_instruction_setter_rejects_missing_and_expired_sessions(self):
        with self.assertRaisesRegex(ValueError, "Unknown or expired session"):
            session_access.set_instructions("missing", "Prompt")
        with patch("session_access.time.monotonic", return_value=0):
            session_access.issue("expired", instructions="Original")
        with patch("session_access.time.monotonic", return_value=15000):
            with self.assertRaisesRegex(ValueError, "Unknown or expired session"):
                session_access.set_instructions("expired", "Replacement")
        self.assertFalse(session_access._sessions)
