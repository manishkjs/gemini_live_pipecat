"""Shared session handoff and single-use credential storage across Cloud Run instances.

Supports two cross-instance backends without external Python dependencies:
1. ``SQLiteSharedStore(db_path)`` — stdlib SQLite WAL store for multi-worker local
   deployments and deterministic multi-store integration tests.
2. ``FirestoreSharedStore(project_id, db_id)`` — Cloud Run shared store backed by the
   dedicated ``v2v-demo-visits`` Firestore database, with 32 KB inline threshold,
   500 KB sub-document chunking in <=8-write batches, RFC3339 ``expires_at`` Timestamps
   for native Firestore TTL cleanup, and ``updateTime`` optimistic concurrency.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_DB_ID = "v2v-demo-visits"
FIRESTORE_INLINE_MAX_CHARS = 32_768
FIRESTORE_CHUNK_CHARS = 500_000
FIRESTORE_MAX_BATCH_WRITES = 8
HANDOFF_FIELDS = ("instructions", "tools", "avatar_custom_image", "custom_voice_audio")
MEDIA_FIELDS = ("avatar_custom_image", "custom_voice_audio")


class SharedStoreError(RuntimeError):
    """Raised when the cross-instance session store cannot be reached or rejects an operation."""


def _doc_key(raw_id: str) -> str:
    return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()


def _iso_utc(epoch_seconds: float) -> str:
    return (
        datetime.fromtimestamp(float(epoch_seconds), tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


class _TimestampValue:
    """Marker wrapper so ``FirestoreSharedStore._encode_fields`` emits a ``timestampValue``."""

    __slots__ = ("iso",)

    def __init__(self, epoch_seconds: float):
        self.iso = _iso_utc(epoch_seconds)


class SQLiteSharedStore:
    """Process-safe and store-independent SQLite WAL backing store."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    token TEXT NOT NULL,
                    join_token TEXT,
                    join_expires_wall REAL NOT NULL,
                    expires_wall REAL NOT NULL,
                    instructions TEXT,
                    tools TEXT,
                    avatar_custom_image TEXT,
                    custom_voice_audio TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_profiles (
                    profile_id TEXT PRIMARY KEY,
                    secret_key TEXT NOT NULL,
                    expires_wall REAL NOT NULL
                )
                """
            )

    def create_session(
        self,
        session_id: str,
        *,
        token: str,
        join: str,
        join_ttl: float,
        session_ttl: float,
        instructions: Optional[str] = None,
        tools: Optional[str] = None,
        avatar_custom_image: Optional[str] = None,
        custom_voice_audio: Optional[str] = None,
        now_wall: Optional[float] = None,
    ) -> bool:
        now = time.time() if now_wall is None else now_wall
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM sessions WHERE expires_wall <= ?", (now,))
                row = conn.execute(
                    "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                if row is not None:
                    conn.execute("ROLLBACK")
                    return False
                conn.execute(
                    """
                    INSERT INTO sessions (
                        session_id, token, join_token, join_expires_wall, expires_wall,
                        instructions, tools, avatar_custom_image, custom_voice_audio
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        token,
                        join,
                        now + join_ttl,
                        now + session_ttl,
                        instructions,
                        tools,
                        avatar_custom_image,
                        custom_voice_audio,
                    ),
                )
                conn.execute("COMMIT")
                return True
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def get_session(self, session_id: str, now_wall: Optional[float] = None) -> Optional[Dict[str, Any]]:
        now = time.time() if now_wall is None else now_wall
        with self._lock, contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            if row["expires_wall"] <= now:
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                return None
            data = dict(row)
            if data["join_expires_wall"] <= now and (
                data.get("avatar_custom_image") is not None or data.get("custom_voice_audio") is not None
            ):
                conn.execute(
                    "UPDATE sessions SET avatar_custom_image = NULL, custom_voice_audio = NULL WHERE session_id = ?",
                    (session_id,),
                )
                data["avatar_custom_image"] = None
                data["custom_voice_audio"] = None
            return data

    def consume_join(self, session_id: str, join: str, now_wall: Optional[float] = None) -> bool:
        now = time.time() if now_wall is None else now_wall
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    """
                    UPDATE sessions
                    SET join_token = NULL
                    WHERE session_id = ?
                      AND join_token = ?
                      AND join_expires_wall > ?
                      AND expires_wall > ?
                    """,
                    (session_id, join, now, now),
                )
                conn.execute("COMMIT")
                return cur.rowcount == 1
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def set_instructions(self, session_id: str, prompt: str, now_wall: Optional[float] = None) -> bool:
        now = time.time() if now_wall is None else now_wall
        with self._lock, contextlib.closing(self._connect()) as conn:
            cur = conn.execute(
                "UPDATE sessions SET instructions = ? WHERE session_id = ? AND expires_wall > ?",
                (prompt, session_id, now),
            )
            return cur.rowcount == 1

    def take_field(self, session_id: str, field: str, now_wall: Optional[float] = None) -> Optional[str]:
        if field not in HANDOFF_FIELDS:
            raise ValueError(f"Unsupported handoff field: {field}")
        now = time.time() if now_wall is None else now_wall
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    f"SELECT {field}, join_expires_wall, expires_wall FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if row is None or row["expires_wall"] <= now:
                    if row is not None:
                        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                    conn.execute("COMMIT")
                    return None
                if field in MEDIA_FIELDS and row["join_expires_wall"] <= now:
                    conn.execute(
                        f"UPDATE sessions SET {field} = NULL WHERE session_id = ?",
                        (session_id,),
                    )
                    conn.execute("COMMIT")
                    return None
                val = row[field]
                if val is not None:
                    conn.execute(
                        f"UPDATE sessions SET {field} = NULL WHERE session_id = ?",
                        (session_id,),
                    )
                conn.execute("COMMIT")
                return val
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def take_handoff(self, session_id: str, now_wall: Optional[float] = None) -> Dict[str, Optional[str]]:
        now = time.time() if now_wall is None else now_wall
        empty: Dict[str, Optional[str]] = {f: None for f in HANDOFF_FIELDS}
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    """
                    SELECT instructions, tools, avatar_custom_image, custom_voice_audio,
                           join_expires_wall, expires_wall
                    FROM sessions WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                if row is None or row["expires_wall"] <= now:
                    if row is not None:
                        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                    conn.execute("COMMIT")
                    return empty
                join_alive = row["join_expires_wall"] > now
                result: Dict[str, Optional[str]] = {
                    "instructions": row["instructions"],
                    "tools": row["tools"],
                    "avatar_custom_image": row["avatar_custom_image"] if join_alive else None,
                    "custom_voice_audio": row["custom_voice_audio"] if join_alive else None,
                }
                if any(row[f] is not None for f in HANDOFF_FIELDS):
                    conn.execute(
                        """
                        UPDATE sessions
                        SET instructions = NULL, tools = NULL, avatar_custom_image = NULL, custom_voice_audio = NULL
                        WHERE session_id = ?
                        """,
                        (session_id,),
                    )
                conn.execute("COMMIT")
                return result
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def clear_handoff_payloads(self, session_id: str) -> None:
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE sessions
                SET instructions = NULL, tools = NULL, avatar_custom_image = NULL, custom_voice_audio = NULL
                WHERE session_id = ?
                """,
                (session_id,),
            )

    def delete_session(self, session_id: str) -> None:
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def clear_all_sessions(self) -> None:
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute("DELETE FROM sessions")

    def register_voice_profile(self, profile_id: str, key: str, ttl_seconds: float, now_wall: Optional[float] = None) -> None:
        now = time.time() if now_wall is None else now_wall
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute("DELETE FROM voice_profiles WHERE expires_wall <= ?", (now,))
            conn.execute(
                "INSERT OR REPLACE INTO voice_profiles (profile_id, secret_key, expires_wall) VALUES (?, ?, ?)",
                (profile_id, key, now + ttl_seconds),
            )

    def consume_voice_profile(self, profile_id: str, now_wall: Optional[float] = None) -> Optional[str]:
        now = time.time() if now_wall is None else now_wall
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT secret_key, expires_wall FROM voice_profiles WHERE profile_id = ?",
                    (profile_id,),
                ).fetchone()
                conn.execute("DELETE FROM voice_profiles WHERE profile_id = ?", (profile_id,))
                conn.execute("COMMIT")
                if row is None or row["expires_wall"] <= now:
                    return None
                return row["secret_key"]
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def clear_voice_profiles(self) -> None:
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute("DELETE FROM voice_profiles")


class FirestoreSharedStore:
    """Cloud Run shared store backed by Firestore REST API with batched 500 KB blob chunking."""

    def __init__(self, project_id: str, db_id: str = DEFAULT_DB_ID):
        self.project_id = project_id
        self.db_id = db_id or DEFAULT_DB_ID
        self._creds = None
        self._creds_lock = threading.Lock()

    def _token(self) -> str:
        with self._creds_lock:
            try:
                import google.auth
                from google.auth.transport.requests import Request as GoogleAuthRequest

                if self._creds is None:
                    self._creds, _ = google.auth.default(
                        scopes=["https://www.googleapis.com/auth/datastore"]
                    )
                if not self._creds.valid:
                    self._creds.refresh(GoogleAuthRequest())
                tok = self._creds.token
            except Exception as exc:
                raise SharedStoreError(f"Firestore credentials unavailable: {exc}") from exc
            if not tok:
                raise SharedStoreError("Firestore credentials returned an empty access token")
            return tok

    @property
    def _db_path(self) -> str:
        return f"projects/{self.project_id}/databases/{self.db_id}"

    def _session_doc(self, session_id: str) -> str:
        return f"{self._db_path}/documents/studio_sessions/{_doc_key(session_id)}"

    @staticmethod
    def _field_gen_key(field: str) -> str:
        return "instructions_gen" if field == "instructions" else "blob_gen"

    def _blob_doc(self, session_id: str, field: str, idx: int, gen: str = "") -> str:
        prefix = f"{gen}_" if gen else ""
        return f"{self._session_doc(session_id)}/blobs/{prefix}{field}_{idx}"

    def _profile_doc(self, profile_id: str) -> str:
        return f"{self._db_path}/documents/studio_voice_profiles/{_doc_key(profile_id)}"

    def _request(self, method: str, url: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        token = self._token()
        if not token:
            raise SharedStoreError("Shared session store access token unavailable")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Authorization": f"Bearer {token}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError:
            raise
        except Exception as exc:
            raise SharedStoreError(f"Firestore request failed ({method}): {exc}") from exc

    @staticmethod
    def _is_precondition_conflict(exc: urllib.error.HTTPError) -> bool:
        body_text = ""
        try:
            raw = exc.read()
            if raw:
                body_text = raw.decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        upper = body_text.upper()
        if exc.code == 409:
            return True
        if exc.code == 400 and ("FAILED_PRECONDITION" in upper or "PRECONDITION" in upper):
            return True
        if exc.code == 404 and ("NOT_FOUND" in upper or not upper):
            return True
        return False

    def _get_doc(self, doc_path: str) -> Optional[Dict[str, Any]]:
        url = f"https://firestore.googleapis.com/v1/{doc_path}"
        try:
            res = self._request("GET", url)
            if res is None:
                raise SharedStoreError("Firestore GET returned None")
            return res
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise SharedStoreError(f"Firestore GET failed with HTTP {exc.code}") from exc

    def _commit(self, writes: List[Dict[str, Any]]) -> bool:
        if not writes:
            return True
        has_precondition = any("currentDocument" in w for w in writes)
        url = f"https://firestore.googleapis.com/v1/{self._db_path}/documents:commit"
        try:
            res = self._request("POST", url, {"writes": writes})
            if res is None:
                raise SharedStoreError("Firestore commit returned None")
            return True
        except urllib.error.HTTPError as exc:
            if has_precondition and self._is_precondition_conflict(exc):
                return False
            raise SharedStoreError(f"Firestore commit failed with HTTP {exc.code}") from exc

    def _commit_batched(
        self,
        writes: List[Dict[str, Any]],
        *,
        best_effort: bool = False,
    ) -> None:
        if not writes:
            return
        for i in range(0, len(writes), FIRESTORE_MAX_BATCH_WRITES):
            batch = writes[i : i + FIRESTORE_MAX_BATCH_WRITES]
            try:
                self._commit(batch)
            except SharedStoreError:
                if not best_effort:
                    raise

    def _fetch_chunks(self, session_id: str, field: str, chunk_count: int, gen: str) -> Optional[str]:
        paths = [self._blob_doc(session_id, field, idx, gen=gen) for idx in range(chunk_count)]
        if chunk_count == 1:
            docs = [self._get_doc(paths[0])]
        else:
            with ThreadPoolExecutor(max_workers=min(8, chunk_count)) as pool:
                docs = list(pool.map(self._get_doc, paths))
        parts: List[str] = []
        for idx, bdoc in enumerate(docs):
            if bdoc is None:
                raise SharedStoreError(
                    f"Missing Firestore blob chunk {idx + 1}/{chunk_count} for {session_id}.{field}"
                )
            parts.append(self._decode_fields(bdoc).get("data") or "")
        return "".join(parts)

    def _delete_blobs_for_record(self, session_id: str, data: Dict[str, Any], fields=HANDOFF_FIELDS) -> List[Dict[str, Any]]:
        deletes: List[Dict[str, Any]] = []
        for field in fields:
            count = int(data.get(f"{field}_chunks") or 0)
            gen = str(data.get(self._field_gen_key(field)) or "")
            for idx in range(count):
                deletes.append({"delete": self._blob_doc(session_id, field, idx, gen=gen)})
        return deletes

    @staticmethod
    def _encode_fields(mapping: Dict[str, Any]) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}
        for k, v in mapping.items():
            if v is None:
                fields[k] = {"nullValue": None}
            elif isinstance(v, _TimestampValue):
                fields[k] = {"timestampValue": v.iso}
            elif isinstance(v, bool):
                fields[k] = {"booleanValue": v}
            elif isinstance(v, int):
                fields[k] = {"integerValue": str(v)}
            elif isinstance(v, float):
                fields[k] = {"doubleValue": v}
            else:
                fields[k] = {"stringValue": str(v)}
        return fields

    @staticmethod
    def _decode_fields(doc: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, val in (doc.get("fields") or {}).items():
            if "stringValue" in val:
                out[k] = val["stringValue"]
            elif "timestampValue" in val:
                out[k] = val["timestampValue"]
            elif "doubleValue" in val:
                out[k] = float(val["doubleValue"])
            elif "integerValue" in val:
                out[k] = int(val["integerValue"])
            elif "booleanValue" in val:
                out[k] = bool(val["booleanValue"])
            else:
                out[k] = None
        return out

    def create_session(
        self,
        session_id: str,
        *,
        token: str,
        join: str,
        join_ttl: float,
        session_ttl: float,
        instructions: Optional[str] = None,
        tools: Optional[str] = None,
        avatar_custom_image: Optional[str] = None,
        custom_voice_audio: Optional[str] = None,
        now_wall: Optional[float] = None,
    ) -> bool:
        now = time.time() if now_wall is None else now_wall
        doc_path = self._session_doc(session_id)
        existing = self._get_doc(doc_path)
        precondition: Dict[str, Any] = {"exists": False}
        stale_blob_deletes: List[Dict[str, Any]] = []
        if existing is not None:
            decoded = self._decode_fields(existing)
            if (decoded.get("expires_wall") or 0) > now:
                return False
            precondition = {"updateTime": existing["updateTime"]}
            stale_blob_deletes = self._delete_blobs_for_record(session_id, decoded)

        blob_gen = secrets.token_hex(6)
        instructions_gen = secrets.token_hex(6)
        join_exp = float(now + join_ttl)
        sess_exp = float(now + session_ttl)

        doc_values: Dict[str, Any] = {
            "session_id": session_id,
            "token": token,
            "join_token": join,
            "join_expires_wall": join_exp,
            "expires_wall": sess_exp,
            "expires_at": _TimestampValue(sess_exp),
            "blob_gen": blob_gen,
            "instructions_gen": instructions_gen,
        }
        blob_writes: List[Dict[str, Any]] = []
        new_blob_deletes: List[Dict[str, Any]] = []
        raw_payloads = {
            "instructions": instructions,
            "tools": tools,
            "avatar_custom_image": avatar_custom_image,
            "custom_voice_audio": custom_voice_audio,
        }
        for field, text in raw_payloads.items():
            gen = instructions_gen if field == "instructions" else blob_gen
            blob_exp = join_exp if field in MEDIA_FIELDS else sess_exp
            if text is None:
                doc_values[field] = None
                doc_values[f"{field}_chunks"] = 0
            elif len(text) <= FIRESTORE_INLINE_MAX_CHARS:
                doc_values[field] = text
                doc_values[f"{field}_chunks"] = 0
            else:
                chunks = [
                    text[i : i + FIRESTORE_CHUNK_CHARS]
                    for i in range(0, len(text), FIRESTORE_CHUNK_CHARS)
                ]
                doc_values[field] = None
                doc_values[f"{field}_chunks"] = len(chunks)
                for idx, chunk in enumerate(chunks):
                    bpath = self._blob_doc(session_id, field, idx, gen=gen)
                    blob_writes.append(
                        {
                            "update": {
                                "name": bpath,
                                "fields": self._encode_fields(
                                    {"data": chunk, "expires_at": _TimestampValue(blob_exp)}
                                ),
                            }
                        }
                    )
                    new_blob_deletes.append({"delete": bpath})

        # Write blob chunks in <=4 MB batches first so max 7M avatar + 4M voice never hits Firestore's 10 MiB commit cap.
        if blob_writes:
            try:
                self._commit_batched(blob_writes)
            except BaseException:
                self._commit_batched(new_blob_deletes, best_effort=True)
                raise

        committed = self._commit(
            [
                {
                    "update": {
                        "name": doc_path,
                        "fields": self._encode_fields(doc_values),
                    },
                    "currentDocument": precondition,
                }
            ]
        )
        if not committed:
            self._commit_batched(new_blob_deletes, best_effort=True)
            return False

        if stale_blob_deletes:
            self._commit_batched(stale_blob_deletes, best_effort=True)
        return True

    def get_session(self, session_id: str, now_wall: Optional[float] = None) -> Optional[Dict[str, Any]]:
        now = time.time() if now_wall is None else now_wall
        doc_path = self._session_doc(session_id)
        doc = self._get_doc(doc_path)
        if doc is None:
            return None
        data = self._decode_fields(doc)
        if (data.get("expires_wall") or 0) <= now:
            self.delete_session(session_id)
            return None
        return data

    def consume_join(self, session_id: str, join: str, now_wall: Optional[float] = None) -> bool:
        now = time.time() if now_wall is None else now_wall
        doc_path = self._session_doc(session_id)
        doc = self._get_doc(doc_path)
        if doc is None:
            return False
        data = self._decode_fields(doc)
        if (
            not isinstance(data.get("join_token"), str)
            or not secrets.compare_digest(data["join_token"], join)
            or (data.get("join_expires_wall") or 0) <= now
            or (data.get("expires_wall") or 0) <= now
        ):
            return False
        return self._commit(
            [
                {
                    "update": {
                        "name": doc_path,
                        "fields": self._encode_fields({"join_token": None}),
                    },
                    "updateMask": {"fieldPaths": ["join_token"]},
                    "currentDocument": {"updateTime": doc["updateTime"]},
                }
            ]
        )

    def set_instructions(self, session_id: str, prompt: str, now_wall: Optional[float] = None) -> bool:
        now = time.time() if now_wall is None else now_wall
        doc_path = self._session_doc(session_id)
        doc = self._get_doc(doc_path)
        if doc is None:
            return False
        data = self._decode_fields(doc)
        sess_exp = float(data.get("expires_wall") or 0)
        if sess_exp <= now:
            return False

        old_chunks = int(data.get("instructions_chunks") or 0)
        old_gen = str(data.get("instructions_gen") or "")
        new_gen = secrets.token_hex(6)
        blob_writes: List[Dict[str, Any]] = []
        new_blob_deletes: List[Dict[str, Any]] = []

        if len(prompt) <= FIRESTORE_INLINE_MAX_CHARS:
            fields: Dict[str, Any] = {
                "instructions": prompt,
                "instructions_chunks": 0,
                "instructions_gen": new_gen,
            }
        else:
            chunks = [
                prompt[i : i + FIRESTORE_CHUNK_CHARS]
                for i in range(0, len(prompt), FIRESTORE_CHUNK_CHARS)
            ]
            fields = {
                "instructions": None,
                "instructions_chunks": len(chunks),
                "instructions_gen": new_gen,
            }
            for idx, chunk in enumerate(chunks):
                bpath = self._blob_doc(session_id, "instructions", idx, gen=new_gen)
                blob_writes.append(
                    {
                        "update": {
                            "name": bpath,
                            "fields": self._encode_fields(
                                {"data": chunk, "expires_at": _TimestampValue(sess_exp)}
                            ),
                        }
                    }
                )
                new_blob_deletes.append({"delete": bpath})

        if blob_writes:
            try:
                self._commit_batched(blob_writes)
            except BaseException:
                self._commit_batched(new_blob_deletes, best_effort=True)
                raise

        committed = self._commit(
            [
                {
                    "update": {
                        "name": doc_path,
                        "fields": self._encode_fields(fields),
                    },
                    "updateMask": {
                        "fieldPaths": ["instructions", "instructions_chunks", "instructions_gen"]
                    },
                    "currentDocument": {"updateTime": doc["updateTime"]},
                }
            ]
        )
        if not committed:
            self._commit_batched(new_blob_deletes, best_effort=True)
            return False

        if old_chunks > 0:
            old_deletes = [
                {"delete": self._blob_doc(session_id, "instructions", idx, gen=old_gen)}
                for idx in range(old_chunks)
            ]
            self._commit_batched(old_deletes, best_effort=True)
        return True

    def take_field(self, session_id: str, field: str, now_wall: Optional[float] = None) -> Optional[str]:
        if field not in HANDOFF_FIELDS:
            raise ValueError(f"Unsupported handoff field: {field}")
        now = time.time() if now_wall is None else now_wall
        doc_path = self._session_doc(session_id)
        doc = self._get_doc(doc_path)
        if doc is None:
            return None
        data = self._decode_fields(doc)
        if (data.get("expires_wall") or 0) <= now:
            self.delete_session(session_id)
            return None
        chunk_count = int(data.get(f"{field}_chunks") or 0)
        inline_val = data.get(field)
        if inline_val is None and chunk_count <= 0:
            return None

        gen = str(data.get(self._field_gen_key(field)) or "")
        blob_deletes = [
            {"delete": self._blob_doc(session_id, field, idx, gen=gen)}
            for idx in range(chunk_count)
        ]

        if field in MEDIA_FIELDS and (data.get("join_expires_wall") or 0) <= now:
            if self._commit(
                [
                    {
                        "update": {
                            "name": doc_path,
                            "fields": self._encode_fields({field: None, f"{field}_chunks": 0}),
                        },
                        "updateMask": {"fieldPaths": [field, f"{field}_chunks"]},
                        "currentDocument": {"updateTime": doc["updateTime"]},
                    }
                ]
            ):
                self._commit_batched(blob_deletes, best_effort=True)
            return None

        assembled = inline_val
        if chunk_count > 0:
            assembled = self._fetch_chunks(session_id, field, chunk_count, gen)
            if assembled is None:
                return None

        if not self._commit(
            [
                {
                    "update": {
                        "name": doc_path,
                        "fields": self._encode_fields({field: None, f"{field}_chunks": 0}),
                    },
                    "updateMask": {"fieldPaths": [field, f"{field}_chunks"]},
                    "currentDocument": {"updateTime": doc["updateTime"]},
                }
            ]
        ):
            return None

        if blob_deletes:
            self._commit_batched(blob_deletes, best_effort=True)
        return assembled

    def take_handoff(self, session_id: str, now_wall: Optional[float] = None) -> Dict[str, Optional[str]]:
        now = time.time() if now_wall is None else now_wall
        empty: Dict[str, Optional[str]] = {f: None for f in HANDOFF_FIELDS}
        doc_path = self._session_doc(session_id)
        doc = self._get_doc(doc_path)
        if doc is None:
            return empty
        data = self._decode_fields(doc)
        if (data.get("expires_wall") or 0) <= now:
            self.delete_session(session_id)
            return empty
        join_alive = (data.get("join_expires_wall") or 0) > now
        result: Dict[str, Optional[str]] = {f: None for f in HANDOFF_FIELDS}
        mask: List[str] = []
        clear_fields: Dict[str, Any] = {}
        blob_deletes: List[Dict[str, Any]] = []
        has_any_stored = False

        for field in HANDOFF_FIELDS:
            chunk_count = int(data.get(f"{field}_chunks") or 0)
            inline_val = data.get(field)
            if inline_val is None and chunk_count <= 0:
                continue
            has_any_stored = True
            clear_fields[field] = None
            clear_fields[f"{field}_chunks"] = 0
            mask.extend([field, f"{field}_chunks"])
            is_media = field in MEDIA_FIELDS
            gen = str(data.get(self._field_gen_key(field)) or "")
            for idx in range(chunk_count):
                blob_deletes.append({"delete": self._blob_doc(session_id, field, idx, gen=gen)})
            if chunk_count > 0:
                if not is_media or join_alive:
                    assembled = self._fetch_chunks(session_id, field, chunk_count, gen)
                    if assembled is not None:
                        result[field] = assembled
            elif not is_media or join_alive:
                result[field] = inline_val

        if not has_any_stored:
            return empty

        if not self._commit(
            [
                {
                    "update": {"name": doc_path, "fields": self._encode_fields(clear_fields)},
                    "updateMask": {"fieldPaths": mask},
                    "currentDocument": {"updateTime": doc["updateTime"]},
                }
            ]
        ):
            return empty

        if blob_deletes:
            self._commit_batched(blob_deletes, best_effort=True)
        return result

    def clear_handoff_payloads(self, session_id: str) -> None:
        doc_path = self._session_doc(session_id)
        doc = self._get_doc(doc_path)
        if doc is None:
            return
        data = self._decode_fields(doc)
        if not any(
            data.get(f) is not None or int(data.get(f"{f}_chunks") or 0) > 0
            for f in HANDOFF_FIELDS
        ):
            return
        mask: List[str] = []
        fields: Dict[str, Any] = {}
        for field in HANDOFF_FIELDS:
            fields[field] = None
            fields[f"{field}_chunks"] = 0
            mask.extend([field, f"{field}_chunks"])
        blob_deletes = self._delete_blobs_for_record(session_id, data)
        if self._commit(
            [
                {
                    "update": {"name": doc_path, "fields": self._encode_fields(fields)},
                    "updateMask": {"fieldPaths": mask},
                }
            ]
        ):
            self._commit_batched(blob_deletes, best_effort=True)

    def delete_session(self, session_id: str) -> None:
        doc_path = self._session_doc(session_id)
        doc = self._get_doc(doc_path)
        blob_deletes: List[Dict[str, Any]] = []
        if doc is not None:
            data = self._decode_fields(doc)
            blob_deletes = self._delete_blobs_for_record(session_id, data)
        self._commit([{"delete": doc_path}])
        if blob_deletes:
            self._commit_batched(blob_deletes, best_effort=True)

    def clear_all_sessions(self) -> None:
        pass

    def register_voice_profile(self, profile_id: str, key: str, ttl_seconds: float, now_wall: Optional[float] = None) -> None:
        now = time.time() if now_wall is None else now_wall
        exp = float(now + ttl_seconds)
        if not self._commit(
            [
                {
                    "update": {
                        "name": self._profile_doc(profile_id),
                        "fields": self._encode_fields(
                            {
                                "secret_key": key,
                                "expires_wall": exp,
                                "expires_at": _TimestampValue(exp),
                            }
                        ),
                    }
                }
            ]
        ):
            raise SharedStoreError("Failed to persist voice profile handle")

    def consume_voice_profile(self, profile_id: str, now_wall: Optional[float] = None) -> Optional[str]:
        now = time.time() if now_wall is None else now_wall
        doc_path = self._profile_doc(profile_id)
        doc = self._get_doc(doc_path)
        if doc is None:
            return None
        data = self._decode_fields(doc)
        if not self._commit(
            [
                {
                    "delete": doc_path,
                    "currentDocument": {"updateTime": doc["updateTime"]},
                }
            ]
        ):
            return None
        if (data.get("expires_wall") or 0) <= now:
            return None
        return data.get("secret_key")

    def clear_voice_profiles(self) -> None:
        pass


def build_default_shared_store():
    """Return configured cross-instance store (SQLite path or Cloud Run Firestore), or None."""
    sqlite_path = (os.environ.get("SESSION_STORE_PATH") or "").strip()
    if sqlite_path:
        return SQLiteSharedStore(sqlite_path)
    if os.environ.get("K_SERVICE") and os.environ.get("GCP_PROJECT_ID"):
        project_id = os.environ["GCP_PROJECT_ID"].strip()
        db_id = (os.environ.get("VISIT_COUNTER_DB_ID") or DEFAULT_DB_ID).strip() or DEFAULT_DB_ID
        return FirestoreSharedStore(project_id=project_id, db_id=db_id)
    return None
