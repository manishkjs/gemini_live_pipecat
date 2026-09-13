import unittest
from unittest.mock import patch
import session_access


class TestSessionAccess(unittest.TestCase):
    def setUp(self):
        session_access._sessions.clear()

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
