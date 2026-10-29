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

    def test_connect_rejects_oversized_media_payloads_with_413(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)

        over_body = client.post(
            "/connect?session_id=huge_body",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": str(12 * 1024 * 1024 + 1)},
        )
        self.assertEqual(over_body.status_code, 413)
        self.assertIn("MB", over_body.json()["detail"])

        over_image = client.post(
            "/connect?session_id=huge_img",
            json={"avatar_custom_image": "A" * 7_000_001},
        )
        self.assertEqual(over_image.status_code, 413)
        self.assertIn("5 MB", over_image.json()["detail"])

        over_audio = client.post(
            "/connect?session_id=huge_wav",
            json={"custom_voice_audio": "A" * 4_000_001},
        )
        self.assertEqual(over_audio.status_code, 413)
        self.assertIn("3 MB", over_audio.json()["detail"])
        self.assertFalse(session_access._sessions)

    def test_unclaimed_media_blobs_are_released_once_join_expires(self):
        with patch("session_access.time.monotonic", return_value=0):
            sid, token, _ = session_access.issue(
                "media_sess",
                avatar_custom_image="data:image/png;base64,AAAA",
                custom_voice_audio="data:audio/wav;base64,BBBB",
            )
        with patch("session_access.time.monotonic", return_value=session_access.JOIN_TTL_SECONDS + 1):
            self.assertTrue(session_access.authorized(sid, token))
            self.assertIsNone(session_access._sessions[sid].get("avatar_custom_image"))
            self.assertIsNone(session_access._sessions[sid].get("custom_voice_audio"))
            self.assertIsNone(session_access.take_avatar_custom_image(sid))
            self.assertIsNone(session_access.take_custom_voice_audio(sid))

    def test_connect_accepts_null_system_instruction(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)

        null_resp = client.post(
            "/connect?session_id=null_instr&system_instruction=QueryFallback",
            json={"system_instruction": None},
        )
        self.assertEqual(null_resp.status_code, 200)
        self.assertEqual(
            session_access.take_instructions(null_resp.json()["session_id"]),
            "QueryFallback",
        )

        control_resp = client.post(
            "/connect?session_id=str_instr",
            json={"system_instruction": "hi"},
        )
        self.assertEqual(control_resp.status_code, 200)
        self.assertEqual(
            session_access.take_instructions(control_resp.json()["session_id"]),
            "hi",
        )

    def test_connect_streams_body_and_enforces_byte_limit_without_trusting_content_length(self):
        from fastapi.testclient import TestClient
        from starlette.requests import Request
        import server
        client = TestClient(server.app)

        chunks_yielded = 0

        async def oversized_stream(self_req):
            nonlocal chunks_yielded
            # Yield 20 chunks of 1 MB each; intake must stop as soon as total > 12 MB (13th chunk)
            for _ in range(20):
                chunks_yielded += 1
                yield b"x" * (1024 * 1024)

        with patch.object(Request, "body", side_effect=AssertionError("request.body() must not be called")), \
             patch.object(Request, "stream", oversized_stream):
            no_cl = client.post(
                "/connect?session_id=stream_no_cl",
                content=b"{}",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(no_cl.status_code, 413)
            self.assertEqual(chunks_yielded, 13)

            chunks_yielded = 0
            understated_cl = client.post(
                "/connect?session_id=stream_understated_cl",
                content=b"{}",
                headers={"Content-Type": "application/json", "Content-Length": "2"},
            )
            self.assertEqual(understated_cl.status_code, 413)
            self.assertEqual(chunks_yielded, 13)

        # Exact-limit boundary (MAX_CONNECT_BODY_BYTES = 12 * 1024 * 1024) across multiple chunks:
        # 1) Exactly MAX_CONNECT_BODY_BYTES of valid JSON (padded with spaces) across 4 chunks -> 200
        prefix = b'{"system_instruction":"boundary_ok"}'
        pad_len = server.MAX_CONNECT_BODY_BYTES - len(prefix)
        exact_payload = prefix + (b" " * pad_len)
        chunk_size = 4 * 1024 * 1024
        exact_chunks = [exact_payload[i : i + chunk_size] for i in range(0, len(exact_payload), chunk_size)]

        async def exact_boundary_stream(self_req):
            for c in exact_chunks:
                yield c

        with patch.object(Request, "body", side_effect=AssertionError("request.body() must not be called")), \
             patch.object(Request, "stream", exact_boundary_stream):
            exact_resp = client.post(
                "/connect?session_id=stream_exact_limit",
                content=b"{}",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(exact_resp.status_code, 200)
            self.assertEqual(
                session_access.take_instructions(exact_resp.json()["session_id"]),
                "boundary_ok",
            )

        # 2) MAX_CONNECT_BODY_BYTES + 1 across multiple chunks -> 413 on the 1-byte overflow chunk
        plus_one_yielded = 0

        async def boundary_plus_one_stream(self_req):
            nonlocal plus_one_yielded
            for c in exact_chunks + [b" ", b"ignored_trailing_chunk"]:
                plus_one_yielded += 1
                yield c

        with patch.object(Request, "body", side_effect=AssertionError("request.body() must not be called")), \
             patch.object(Request, "stream", boundary_plus_one_stream):
            plus_one_resp = client.post(
                "/connect?session_id=stream_limit_plus_one",
                content=b"{}",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(plus_one_resp.status_code, 413)
            self.assertEqual(plus_one_yielded, len(exact_chunks) + 1)

        normal_resp = client.post(
            "/connect?session_id=stream_ok",
            json={"system_instruction": "streamed ok"},
        )
        self.assertEqual(normal_resp.status_code, 200)
        self.assertFalse(session_access.authorized("stream_no_cl", "x" * 32))
        self.assertFalse(session_access.authorized("stream_understated_cl", "x" * 32))
        self.assertFalse(session_access.authorized("stream_limit_plus_one", "x" * 32))
        self.assertNotIn("stream_no_cl", session_access._sessions)
        self.assertNotIn("stream_understated_cl", session_access._sessions)
        self.assertNotIn("stream_limit_plus_one", session_access._sessions)

        for idx, bad_val in enumerate([123, ["a"], {"x": 1}, True]):
            bad_sid = f"stream_bad_type_{idx}"
            bad_resp = client.post(
                f"/connect?session_id={bad_sid}",
                json={"system_instruction": bad_val},
            )
            self.assertEqual(bad_resp.status_code, 400)
            self.assertNotIn(bad_sid, session_access._sessions)

    def test_cross_instance_sqlite_handoff_and_single_use_replay_protection(self):
        import os
        import tempfile
        from shared_session_store import SQLiteSharedStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "shared_sessions.sqlite3")
            shared_a = SQLiteSharedStore(db_path)
            shared_b = SQLiteSharedStore(db_path)
            store_a = session_access.SessionStore(shared_store=shared_a)
            store_b = session_access.SessionStore(shared_store=shared_b)
            vp_a = voice_profiles.VoiceProfileStore(shared_store=shared_a)
            vp_b = voice_profiles.VoiceProfileStore(shared_store=shared_b)

            sid, diag_token, join_token = store_a.issue(
                "multi_sqlite_1",
                instructions="Cross-instance prompt",
                tools='[{"name":"lookup_order"}]',
                avatar_custom_image="data:image/png;base64,AVATAR_PNG",
                custom_voice_audio="data:audio/wav;base64,VOICE_WAV",
            )
            pid = vp_a.register("secret-chirp-clone-key")

            # Instance B (which never saw /connect) validates join, pops handoff & voice profile, and authorizes /api/logs
            self.assertTrue(store_b.consume_join(sid, join_token))
            self.assertFalse(store_b.consume_join(sid, join_token))
            self.assertFalse(store_a.consume_join(sid, join_token))

            handoff = store_b.take_handoff(sid)
            self.assertEqual(handoff["instructions"], "Cross-instance prompt")
            self.assertEqual(handoff["tools"], '[{"name":"lookup_order"}]')
            self.assertEqual(handoff["avatar_custom_image"], "data:image/png;base64,AVATAR_PNG")
            self.assertEqual(handoff["custom_voice_audio"], "data:audio/wav;base64,VOICE_WAV")
            self.assertEqual(store_a.take_handoff(sid)["instructions"], None)

            self.assertEqual(vp_b.consume(pid), "secret-chirp-clone-key")
            self.assertIsNone(vp_b.consume(pid))
            self.assertIsNone(vp_a.consume(pid))

            self.assertTrue(store_b.authorized(sid, diag_token))
            self.assertTrue(store_a.authorized(sid, diag_token))

    def test_cross_instance_firestore_chunked_media_and_optimistic_concurrency(self):
        import copy
        import io
        import json
        import urllib.error
        from fastapi.testclient import TestClient
        import server
        from shared_session_store import (
            FIRESTORE_CHUNK_CHARS,
            FirestoreSharedStore,
            SharedStoreError,
        )

        json_clone = copy.deepcopy
        fake_docs = {}
        rev_counter = [0]
        commit_byte_sizes = []

        def http_err(code: int, status: str) -> urllib.error.HTTPError:
            body = json.dumps({"error": {"code": code, "status": status}}).encode("utf-8")
            return urllib.error.HTTPError("https://firestore.googleapis.com", code, status, {}, io.BytesIO(body))

        def fake_request(store_self, method, url, payload=None):
            prefix = "https://firestore.googleapis.com/v1/"
            assert url.startswith(prefix)
            rel = url[len(prefix) :]
            if method == "GET":
                doc = fake_docs.get(rel)
                if doc is None:
                    raise http_err(404, "NOT_FOUND")
                return json_clone(doc)
            if method == "POST" and rel.endswith(":commit"):
                raw_bytes = len(json.dumps(payload).encode("utf-8"))
                commit_byte_sizes.append(raw_bytes)
                # Enforce Firestore's real 10 MiB commit RPC limit
                if raw_bytes > 10 * 1024 * 1024:
                    raise http_err(400, "INVALID_ARGUMENT")
                for w in payload.get("writes", []):
                    cur = w.get("currentDocument")
                    target = w["update"]["name"] if "update" in w else w["delete"]
                    existing = fake_docs.get(target)
                    if cur:
                        if "exists" in cur and bool(existing is not None) != cur["exists"]:
                            raise http_err(409, "ALREADY_EXISTS")
                        if "updateTime" in cur and (not existing or existing["updateTime"] != cur["updateTime"]):
                            raise http_err(400, "FAILED_PRECONDITION")
                for w in payload.get("writes", []):
                    rev_counter[0] += 1
                    ts = f"2026-10-29T16:00:{rev_counter[0]:06d}Z"
                    if "delete" in w:
                        fake_docs.pop(w["delete"], None)
                    elif "update" in w:
                        name = w["update"]["name"]
                        new_fields = w["update"].get("fields", {})
                        mask = (w.get("updateMask") or {}).get("fieldPaths")
                        if mask and name in fake_docs:
                            merged = dict(fake_docs[name]["fields"])
                            for fp in mask:
                                if fp in new_fields:
                                    merged[fp] = new_fields[fp]
                                else:
                                    merged.pop(fp, None)
                            doc_obj = {"name": name, "fields": merged, "updateTime": ts}
                        else:
                            doc_obj = {"name": name, "fields": dict(new_fields), "updateTime": ts}
                        # Enforce Firestore's real 1 MiB per-document limit
                        if len(json.dumps(doc_obj).encode("utf-8")) > 1024 * 1024:
                            raise http_err(400, "INVALID_ARGUMENT")
                        fake_docs[name] = doc_obj
                return {"writeResults": []}
            raise AssertionError(f"Unexpected {method} {url}")

        with patch.object(FirestoreSharedStore, "_request", fake_request):
            fs_a = FirestoreSharedStore("demo-proj", "v2v-demo-visits")
            fs_b = FirestoreSharedStore("demo-proj", "v2v-demo-visits")
            store_a = session_access.SessionStore(shared_store=fs_a)
            store_b = session_access.SessionStore(shared_store=fs_b)
            vp_a = voice_profiles.VoiceProfileStore(shared_store=fs_a)
            vp_b = voice_profiles.VoiceProfileStore(shared_store=fs_b)

            # S3 + S4: max 7 MB avatar + 4 MB voice + 400 KB instructions + 400 KB tools (~11.8 MB total)
            # stays < 1 MiB per document and < 10 MiB per :commit batch, with native expires_at Timestamps.
            max_avatar = "IMG_" + ("A" * (7_000_000 - 4))
            max_voice = "WAV_" + ("V" * (4_000_000 - 4))
            big_prompt = "P" * 400_000
            big_tools = "T" * 400_000

            sid, diag_token, join_token = store_a.issue(
                "fs_sess_1",
                instructions=big_prompt,
                tools=big_tools,
                avatar_custom_image=max_avatar,
                custom_voice_audio=max_voice,
            )
            pid = vp_a.register("fs-voice-secret")
            self.assertTrue(all(sz < 5 * 1024 * 1024 for sz in commit_byte_sizes))

            # S5: Every document (session, blob, voice_profile) carries a native timestampValue expires_at
            for doc_key, doc_val in fake_docs.items():
                self.assertIn("timestampValue", doc_val["fields"].get("expires_at", {}), doc_key)

            # S6: Shrinking chunked instructions -> short inline instructions deletes all old instruction blobs
            store_a.set_instructions(sid, "Short updated prompt", token=diag_token)
            inst_blobs_after_shrink = [k for k in fake_docs if "instructions_" in k and "/blobs/" in k]
            self.assertEqual(inst_blobs_after_shrink, [])

            # Instance B consumes join, reassembles & deletes all remaining chunks in take_handoff, and consumes voice profile
            self.assertTrue(store_b.consume_join(sid, join_token))
            self.assertFalse(store_a.consume_join(sid, join_token))
            handoff = store_b.take_handoff(sid)
            self.assertEqual(handoff["avatar_custom_image"], max_avatar)
            self.assertEqual(handoff["custom_voice_audio"], max_voice)
            self.assertEqual(handoff["instructions"], "Short updated prompt")
            self.assertEqual(handoff["tools"], big_tools)
            self.assertEqual([k for k in fake_docs if "/blobs/" in k], [])
            self.assertEqual(vp_b.consume(pid), "fs-voice-secret")
            self.assertIsNone(vp_a.consume(pid))
            self.assertTrue(store_b.authorized(sid, diag_token))

            # S6b: Overwriting an expired session doc and take_field on expired media clean up blobs too
            fs_a.create_session(
                "exp_media_sess",
                token="t" * 32,
                join="j" * 32,
                join_ttl=10.0,
                session_ttl=100.0,
                avatar_custom_image="M" * 100_000,
                now_wall=1000.0,
            )
            self.assertEqual(len([k for k in fake_docs if "/blobs/" in k]), 1)
            # Media join expired at 1015, session still alive -> take_field returns None AND deletes expired media blob
            self.assertIsNone(fs_b.take_field("exp_media_sess", "avatar_custom_image", now_wall=1015.0))
            self.assertEqual([k for k in fake_docs if "/blobs/" in k], [])

        # S1: SessionStore.issue does NOT hold _lock while shared_store.create_session runs
        lock_held_during_io = []

        class SlowSharedStore:
            def create_session(self_s, *args, **kwargs):
                # Attempt non-blocking acquire from another thread to prove _lock is NOT held during I/O
                import threading
                acquired = []
                def probe():
                    got = probe_store._lock.acquire(blocking=False)
                    acquired.append(got)
                    if got:
                        probe_store._lock.release()
                t = threading.Thread(target=probe)
                t.start()
                t.join(timeout=1.0)
                lock_held_during_io.append(not acquired[0])
                return True

        probe_store = session_access.SessionStore(shared_store=SlowSharedStore())
        probe_store.issue("lock_free_io")
        self.assertEqual(lock_held_during_io, [False])

        # S2: Missing credentials / Firestore 503 raises SharedStoreError -> HTTP 503 (never silent success or false 409)
        broken_fs = FirestoreSharedStore("demo-proj", "v2v-demo-visits")
        with patch.object(FirestoreSharedStore, "_token", side_effect=SharedStoreError("ADC missing")):
            with self.assertRaises(SharedStoreError):
                broken_fs.create_session("no_creds", token="t" * 32, join="j" * 32, join_ttl=60, session_ttl=300)
            client = TestClient(server.app)
            session_access.configure_shared_store(broken_fs)
            try:
                r503 = client.post("/connect?session_id=should_503", json={})
                self.assertEqual(r503.status_code, 503)
                self.assertNotIn("should_503", session_access._sessions)
            finally:
                session_access.configure_shared_store(None)

    def test_finished_calls_release_active_capacity_while_retaining_diagnostic_access(self):
        from unittest.mock import AsyncMock, MagicMock
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect
        import server

        store = session_access.SessionStore()
        tokens = []
        # Run 5 sequential calls through max_active=2, max_diagnostic=5
        for idx in range(5):
            sid, tok, join = store.issue(f"seq_{idx}", max_active=2, max_diagnostic=5)
            tokens.append((sid, tok))
            self.assertTrue(store.consume_join(sid, join))
            store.open_connection(sid)
            self.assertEqual(store.active_connection_count(), 1)
            store.close_connection(sid)
            self.assertEqual(store.active_connection_count(), 0)

        # All 5 finished calls still retain diagnostic token access
        for sid, tok in tokens:
            self.assertTrue(store.authorized(sid, tok))

        # Meanwhile 2 simultaneously open/pending sessions block a 3rd until one closes
        s1, _, j1 = store.issue("conc_1", max_active=2, max_diagnostic=10)
        store.consume_join(s1, j1)
        store.open_connection(s1)
        s2, _, _ = store.issue("conc_2", max_active=2, max_diagnostic=10)
        with self.assertRaisesRegex(RuntimeError, "Session capacity reached"):
            store.issue("conc_3", max_active=2, max_diagnostic=10)
        store.close_connection(s1)
        s3, _, _ = store.issue("conc_3", max_active=2, max_diagnostic=10)
        self.assertEqual(s3, "conc_3")

        # End-to-end /connect -> /ws disconnect releases active capacity immediately,
        # AND S8: anonymous raw /ws (no connection_id) enforces MAX_SESSIONS with zero shared-store calls.
        client = TestClient(server.app)
        mock_shared = MagicMock()
        mock_shared.create_session.return_value = True
        mock_shared.consume_join.return_value = True
        mock_shared.take_handoff.return_value = {
            "instructions": None,
            "tools": None,
            "avatar_custom_image": None,
            "custom_voice_audio": None,
        }
        with patch("session_access.MAX_SESSIONS", 1), \
             patch.object(server, "load_pipeline", return_value=AsyncMock(return_value=None)):
            r1 = client.post("/connect?bot_type=tts-llm-stt", json={})
            self.assertEqual(r1.status_code, 200)
            # While r1 is pending join (active_count == 1 == MAX_SESSIONS), an anonymous /ws is rejected with 1013
            session_access.configure_shared_store(mock_shared)
            try:
                with self.assertRaises(WebSocketDisconnect) as ws_exc:
                    with client.websocket_connect("/ws?bot_type=tts-llm-stt") as ws:
                        ws.receive_text()
                self.assertEqual(ws_exc.exception.code, 1013)
                mock_shared.take_handoff.assert_not_called()
            finally:
                session_access.configure_shared_store(None)

            d1 = r1.json()
            ws_rel_1 = urlparse(d1["ws_url"]).path + "?" + urlparse(d1["ws_url"]).query
            with client.websocket_connect(ws_rel_1):
                pass
            # Slot is now released, so both an anonymous /ws AND a 2nd /connect succeed!
            session_access.configure_shared_store(mock_shared)
            try:
                with client.websocket_connect("/ws?bot_type=tts-llm-stt"):
                    pass
                mock_shared.take_handoff.assert_not_called()
                mock_shared.clear_handoff_payloads.assert_not_called()
            finally:
                session_access.configure_shared_store(None)

            r2 = client.post("/connect?bot_type=tts-llm-stt", json={})
            self.assertEqual(r2.status_code, 200)
            logs_1 = client.get(
                f"/api/logs?session_id={d1['session_id']}",
                headers={"x-session-token": d1["diagnostic_token"]},
            )
            self.assertEqual(logs_1.status_code, 200)




