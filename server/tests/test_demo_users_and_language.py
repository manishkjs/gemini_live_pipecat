"""Tests for the daily Googler usage record and the mid-call language switching rules."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import demo_users  # noqa: E402


class TestGooglerEmailHeader(unittest.TestCase):
    def test_strips_iap_prefix_and_lowercases(self):
        headers = {"X-Goog-Authenticated-User-Email": "accounts.google.com:Manishkjs@google.com"}
        self.assertEqual(demo_users.googler_email(headers), "manishkjs@google.com")

    def test_header_lookup_is_case_insensitive(self):
        self.assertEqual(demo_users.googler_email({"x-goog-authenticated-user-email": "a@google.com"}), "a@google.com")

    def test_anonymous_requests_return_none(self):
        self.assertIsNone(demo_users.googler_email({}))
        self.assertIsNone(demo_users.googler_email({"x-goog-authenticated-user-email": ""}))
        self.assertIsNone(demo_users.googler_email({"x-goog-authenticated-user-email": "accounts.google.com:"}))
        self.assertIsNone(demo_users.googler_email({"x-goog-authenticated-user-email": "not-an-email"}))


class TestRecordActivityLocal(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._path = os.path.join(self._dir.name, "users.jsonl")
        demo_users.configure_store(self._path)
        for key in ("K_SERVICE", "GCP_PROJECT_ID"):
            os.environ.pop(key, None)

    def tearDown(self):
        demo_users.configure_store(None)
        self._dir.cleanup()

    def _rows(self):
        with open(self._path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_visit_and_session_rows_are_appended(self):
        self.assertTrue(demo_users.record_activity("a@google.com", "visit"))
        self.assertTrue(demo_users.record_activity(
            "a@google.com", "session", persona="travel-concierge", engine="live", model="gemini-3.8-live"))
        rows = self._rows()
        self.assertEqual([r["kind"] for r in rows], ["visit", "session"])
        self.assertEqual(rows[1]["personas"], "travel-concierge")
        self.assertEqual(rows[1]["engines"], "live")
        self.assertEqual(rows[1]["models"], "gemini-3.8-live")
        self.assertNotIn("personas", rows[0])

    def test_anonymous_and_unknown_kinds_are_ignored(self):
        self.assertFalse(demo_users.record_activity(None, "visit"))
        self.assertFalse(demo_users.record_activity("a@google.com", "download"))
        self.assertFalse(os.path.exists(self._path))


class TestFirestorePayload(unittest.TestCase):
    def test_commit_payload_uses_counters_and_array_unions(self):
        captured = {}

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _Resp()

        import urllib.request
        from datetime import datetime, timezone

        orig_open = urllib.request.urlopen
        orig_db = demo_users.visit_counter._firestore_db_path
        orig_tok = demo_users.visit_counter._get_firestore_token
        urllib.request.urlopen = fake_urlopen
        demo_users.visit_counter._firestore_db_path = lambda: "projects/p/databases/v2v-demo-visits"
        demo_users.visit_counter._get_firestore_token = lambda: "tok"
        try:
            now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
            ok = demo_users._firestore_record(
                "a@google.com", "session", now, {"personas": "debt-collector", "engines": "cascade", "models": ""})
        finally:
            urllib.request.urlopen = orig_open
            demo_users.visit_counter._firestore_db_path = orig_db
            demo_users.visit_counter._get_firestore_token = orig_tok
        self.assertTrue(ok)
        self.assertTrue(captured["url"].endswith("/databases/v2v-demo-visits/documents:commit"))
        write = captured["body"]["writes"][0]
        self.assertTrue(write["update"]["name"].endswith("/studio_daily_users/2026-10-30_a@google.com"))
        self.assertEqual(write["update"]["fields"]["email"]["stringValue"], "a@google.com")
        self.assertEqual(write["update"]["fields"]["date"]["stringValue"], "2026-10-30")
        paths = {t["fieldPath"]: t for t in write["updateTransforms"]}
        self.assertEqual(paths["sessions_started"]["increment"]["integerValue"], "1")
        self.assertIn("minimum", paths["first_seen_epoch"])
        self.assertIn("maximum", paths["last_seen_epoch"])
        self.assertEqual(paths["personas"]["appendMissingElements"]["values"][0]["stringValue"], "debt-collector")
        self.assertEqual(paths["engines"]["appendMissingElements"]["values"][0]["stringValue"], "cascade")
        self.assertNotIn("models", paths)


class TestLanguageSwitchingRules(unittest.TestCase):
    def test_live_prompt_tells_model_to_follow_the_caller(self):
        from agent_live import compose_live_system_prompt

        prompt = compose_live_system_prompt("Be terse.", "female", "hi-IN")
        self.assertIn("Start the call in hi-IN", prompt)
        self.assertIn("speaks a whole turn in another language", prompt)
        self.assertIn("Do not announce", prompt)
        self.assertNotIn("You must converse in", prompt)

    def test_transcription_codes_default_to_multilingual_with_session_first(self):
        from agent_live import DEFAULT_LIVE_TRANSCRIPTION_LANGUAGE_CODES, live_transcription_language_codes

        codes = live_transcription_language_codes("en-US")
        self.assertEqual(codes[0], "en-US")
        self.assertEqual(codes[1:], list(DEFAULT_LIVE_TRANSCRIPTION_LANGUAGE_CODES))
        self.assertEqual(live_transcription_language_codes("hi-IN")[0], "hi-IN")
        self.assertEqual(len(live_transcription_language_codes("hi-IN")), len(DEFAULT_LIVE_TRANSCRIPTION_LANGUAGE_CODES))
        self.assertEqual(live_transcription_language_codes("ta-IN", ("ta-IN", "en-IN")), ["ta-IN", "en-IN"])

    def test_preset_personas_carry_the_switch_rule(self):
        from persona_prompt_cards import get_session_preset

        prompt = get_session_preset("debt-collector", engine="live", language="hi-IN")
        self.assertIsNotNone(prompt)
        self.assertIn("Start in Hindi.", prompt)
        self.assertIn("switch to it from your next sentence without announcing it", prompt)
        self.assertNotIn("unless the user requests another language", prompt)

    def test_tara_switches_on_a_whole_turn_in_another_language(self):
        from persona_prompt_cards.tara_cards import _CORE_SI

        self.assertIn("speaks a whole turn in a different supported language, call SelectLanguageTool", _CORE_SI)
        self.assertNotIn("One sentence that sounds different is not a request", _CORE_SI)


if __name__ == "__main__":
    unittest.main()
