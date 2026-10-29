"""Expiring capabilities for demo-session diagnostics and single-use WebSocket handoff.

Supports both in-process storage and cross-instance shared storage (SQLite WAL or
Cloud Run Firestore via ``shared_session_store``), while separating active/pending
connection capacity (``MAX_SESSIONS``) from 4-hour retained diagnostic access
(``MAX_DIAGNOSTIC_SESSIONS``). Never holds ``self._lock`` across shared-store I/O.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from shared_session_store import build_default_shared_store

SESSION_TTL_SECONDS = 4 * 60 * 60
JOIN_TTL_SECONDS = 300
MAX_SESSIONS = 1000
MAX_DIAGNOSTIC_SESSIONS = 10_000


class SessionStore:
    """Independent session capability and handoff store (one per server instance)."""

    def __init__(
        self,
        shared_store: Any = None,
        *,
        now_fn: Optional[Callable[[], float]] = None,
    ):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._shared = shared_store
        self._now_fn = now_fn
        self._lock = threading.RLock()

    def _now(self) -> float:
        return self._now_fn() if self._now_fn is not None else time.monotonic()

    @staticmethod
    def _is_active_or_pending(record: Dict[str, Any], now: float) -> bool:
        if record.get("active"):
            return True
        return bool(record.get("join") and record["join_expires"] > now)

    def _prune_locked(self, now: float, max_diagnostic: int) -> None:
        for key, value in list(self._sessions.items()):
            if value["expires"] <= now:
                del self._sessions[key]
            elif value["join_expires"] <= now:
                value["join"] = None
                value.pop("avatar_custom_image", None)
                value.pop("custom_voice_audio", None)

        closed_keys = [
            k for k, v in self._sessions.items() if not self._is_active_or_pending(v, now)
        ]
        overflow = len(closed_keys) - max_diagnostic
        for k in closed_keys[: max(0, overflow)]:
            self._sessions.pop(k, None)

    def active_connection_count(self) -> int:
        with self._lock:
            now = self._now()
            self._prune_locked(now, MAX_DIAGNOSTIC_SESSIONS)
            return sum(1 for v in self._sessions.values() if self._is_active_or_pending(v, now))

    def issue(
        self,
        session_id: Optional[str] = None,
        token: Optional[str] = None,
        *,
        instructions: Optional[str] = None,
        tools: Optional[str] = None,
        avatar_custom_image: Optional[str] = None,
        custom_voice_audio: Optional[str] = None,
        max_active: Optional[int] = None,
        max_diagnostic: Optional[int] = None,
        join_ttl: Optional[float] = None,
        session_ttl: Optional[float] = None,
    ):
        eff_max_active = MAX_SESSIONS if max_active is None else max_active
        eff_max_diag = MAX_DIAGNOSTIC_SESSIONS if max_diagnostic is None else max_diagnostic
        eff_join_ttl = JOIN_TTL_SECONDS if join_ttl is None else join_ttl
        eff_sess_ttl = SESSION_TTL_SECONDS if session_ttl is None else session_ttl

        session_id = session_id or str(uuid4())
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128:
            raise ValueError("Invalid session_id")
        if token is not None and (
            not isinstance(token, str) or len(token) < 32 or len(token) > 256 or not token.isascii()
        ):
            raise ValueError("Invalid session capability")
        if instructions is not None and not isinstance(instructions, str):
            raise ValueError("Invalid session instructions")
        if tools is not None and not isinstance(tools, str):
            raise ValueError("Invalid session tools")
        if avatar_custom_image is not None and not isinstance(avatar_custom_image, str):
            raise ValueError("Invalid avatar_custom_image")
        if custom_voice_audio is not None and not isinstance(custom_voice_audio, str):
            raise ValueError("Invalid custom_voice_audio")

        token = token or secrets.token_urlsafe(32)
        join = secrets.token_urlsafe(32)

        with self._lock:
            now = self._now()
            self._prune_locked(now, eff_max_diag)
            if session_id in self._sessions:
                raise ValueError("Session already exists; create a fresh session_id")
            active_count = sum(
                1 for v in self._sessions.values() if self._is_active_or_pending(v, now)
            )
            if active_count >= eff_max_active:
                raise RuntimeError("Session capacity reached")

            # Reserve local slot before performing any shared-store I/O outside self._lock.
            self._sessions[session_id] = {
                "token": token,
                "join": join,
                "join_expires": now + eff_join_ttl,
                "expires": now + eff_sess_ttl,
                "active": False,
                "instructions": instructions,
                "tools": tools,
                "avatar_custom_image": avatar_custom_image,
                "custom_voice_audio": custom_voice_audio,
            }
            self._prune_locked(now, eff_max_diag)

        shared = self._shared
        if shared is not None:
            try:
                created = shared.create_session(
                    session_id,
                    token=token,
                    join=join,
                    join_ttl=eff_join_ttl,
                    session_ttl=eff_sess_ttl,
                    instructions=instructions,
                    tools=tools,
                    avatar_custom_image=avatar_custom_image,
                    custom_voice_audio=custom_voice_audio,
                )
            except BaseException:
                with self._lock:
                    self._sessions.pop(session_id, None)
                raise
            if not created:
                with self._lock:
                    self._sessions.pop(session_id, None)
                raise ValueError("Session already exists; create a fresh session_id")

        return session_id, token, join

    def discard(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        with self._lock:
            self._sessions.pop(session_id, None)
        shared = self._shared
        if shared is not None:
            shared.delete_session(session_id)

    def _cache_remote_locked(self, session_id: str, remote: Dict[str, Any], now: float) -> Optional[Dict[str, Any]]:
        wall_now = time.time()
        rem_session = max(0.0, float(remote.get("expires_wall") or 0.0) - wall_now)
        rem_join = max(0.0, float(remote.get("join_expires_wall") or 0.0) - wall_now)
        if rem_session <= 0.0:
            return None
        existing = self._sessions.get(session_id)
        if existing is not None:
            return existing
        record = {
            "token": remote["token"],
            "join": remote.get("join_token"),
            "join_expires": now + rem_join,
            "expires": now + rem_session,
            "active": False,
        }
        self._sessions[session_id] = record
        return record

    def authorized(self, session_id: Optional[str], token: Optional[str]) -> bool:
        if not session_id or not isinstance(token, str) or not token.isascii():
            return False
        with self._lock:
            now = self._now()
            self._prune_locked(now, MAX_DIAGNOSTIC_SESSIONS)
            record = self._sessions.get(session_id)
            if record is not None:
                stored_tok = record.get("token")
                return bool(isinstance(stored_tok, str) and secrets.compare_digest(stored_tok, token))
            shared = self._shared

        if shared is None:
            return False
        remote = shared.get_session(session_id)
        if remote is None:
            return False
        with self._lock:
            now = self._now()
            record = self._cache_remote_locked(session_id, remote, now)
            stored_tok = record.get("token") if record else None
            return bool(isinstance(stored_tok, str) and secrets.compare_digest(stored_tok, token))

    def consume_join(self, session_id: Optional[str], join: Optional[str]) -> bool:
        if not session_id or not isinstance(join, str) or not join.isascii():
            return False
        shared = self._shared
        if shared is not None:
            if not shared.consume_join(session_id, join):
                with self._lock:
                    rec = self._sessions.get(session_id)
                    if rec is not None:
                        rec["join"] = None
                return False
            with self._lock:
                rec = self._sessions.get(session_id)
                if rec is not None:
                    rec["join"] = None
                    return True
            remote = shared.get_session(session_id)
            if remote is not None:
                with self._lock:
                    now = self._now()
                    self._prune_locked(now, MAX_DIAGNOSTIC_SESSIONS)
                    record = self._cache_remote_locked(session_id, remote, now)
                    if record is not None:
                        record["join"] = None
            return True

        with self._lock:
            now = self._now()
            self._prune_locked(now, MAX_DIAGNOSTIC_SESSIONS)
            record = self._sessions.get(session_id)
            if not record or not record.get("join") or record["join_expires"] <= now:
                return False
            if not secrets.compare_digest(record["join"], join):
                return False
            record["join"] = None
            return True

    def open_anonymous_connection(
        self,
        session_id: str,
        *,
        max_active: Optional[int] = None,
        max_diagnostic: Optional[int] = None,
        session_ttl: Optional[float] = None,
    ) -> None:
        """Reserve local active capacity for a raw `/ws` client without touching the shared store."""
        eff_max_active = MAX_SESSIONS if max_active is None else max_active
        eff_max_diag = MAX_DIAGNOSTIC_SESSIONS if max_diagnostic is None else max_diagnostic
        eff_sess_ttl = SESSION_TTL_SECONDS if session_ttl is None else session_ttl
        with self._lock:
            now = self._now()
            self._prune_locked(now, eff_max_diag)
            active_count = sum(
                1 for v in self._sessions.values() if self._is_active_or_pending(v, now)
            )
            if active_count >= eff_max_active:
                raise RuntimeError("Session capacity reached")
            self._sessions[session_id] = {
                "token": None,
                "join": None,
                "join_expires": 0.0,
                "expires": now + eff_sess_ttl,
                "active": True,
                "anonymous": True,
            }

    def open_connection(self, session_id: Optional[str]) -> None:
        """Mark a session's WebSocket connection active while the call is running."""
        if not session_id:
            return
        with self._lock:
            record = self._sessions.get(session_id)
            if record is not None:
                record["active"] = True
                return
            shared = self._shared

        if shared is None:
            return
        remote = shared.get_session(session_id)
        if remote is None:
            return
        with self._lock:
            now = self._now()
            record = self._cache_remote_locked(session_id, remote, now)
            if record is not None:
                record["active"] = True

    def release_local_connection(self, session_id: Optional[str]) -> bool:
        """Synchronously release the in-memory active slot; returns True if shared store cleanup is needed."""
        if not session_id:
            return False
        is_anonymous = False
        with self._lock:
            record = self._sessions.get(session_id)
            if record is not None:
                if record.get("anonymous"):
                    is_anonymous = True
                    self._sessions.pop(session_id, None)
                else:
                    record["active"] = False
                    record["join"] = None
                    record.pop("instructions", None)
                    record.pop("tools", None)
                    record.pop("avatar_custom_image", None)
                    record.pop("custom_voice_audio", None)
        return bool(self._shared is not None and not is_anonymous)

    def clear_shared_handoff(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        shared = self._shared
        if shared is not None:
            shared.clear_handoff_payloads(session_id)

    def close_connection(self, session_id: Optional[str]) -> None:
        """Release active connection slot when WebSocket closes while retaining diagnostic access."""
        if self.release_local_connection(session_id):
            self.clear_shared_handoff(session_id)

    def set_instructions(self, session_id: str, prompt: str, token: Optional[str] = None) -> None:
        if not isinstance(prompt, str):
            raise ValueError("Invalid session instructions")
        shared = self._shared
        with self._lock:
            now = self._now()
            self._prune_locked(now, MAX_DIAGNOSTIC_SESSIONS)
            record = self._sessions.get(session_id)

        if record is None and shared is not None:
            remote = shared.get_session(session_id)
            if remote is not None:
                with self._lock:
                    now = self._now()
                    record = self._cache_remote_locked(session_id, remote, now)

        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                raise ValueError("Unknown or expired session")
            stored_tok = record.get("token")
            if token is not None and (
                not isinstance(token, str)
                or not token.isascii()
                or not isinstance(stored_tok, str)
                or not secrets.compare_digest(stored_tok, token)
            ):
                raise ValueError("Unauthorized session token")
            record["instructions"] = prompt

        if shared is not None:
            if not shared.set_instructions(session_id, prompt):
                raise ValueError("Unknown or expired session")

    def _take_field(self, session_id: Optional[str], field: str) -> Optional[str]:
        if not session_id:
            return None
        shared = self._shared
        if shared is not None:
            with self._lock:
                rec = self._sessions.get(session_id)
                if rec is not None:
                    if rec.get("anonymous"):
                        return None
                    rec.pop(field, None)
            return shared.take_field(session_id, field)
        with self._lock:
            now = self._now()
            self._prune_locked(now, MAX_DIAGNOSTIC_SESSIONS)
            record = self._sessions.get(session_id)
            return record.pop(field, None) if record else None

    def take_instructions(self, session_id: Optional[str]) -> Optional[str]:
        return self._take_field(session_id, "instructions")

    def take_tools(self, session_id: Optional[str]) -> Optional[str]:
        return self._take_field(session_id, "tools")

    def take_avatar_custom_image(self, session_id: Optional[str]) -> Optional[str]:
        return self._take_field(session_id, "avatar_custom_image")

    def take_custom_voice_audio(self, session_id: Optional[str]) -> Optional[str]:
        return self._take_field(session_id, "custom_voice_audio")

    def take_handoff(self, session_id: Optional[str]) -> Dict[str, Optional[str]]:
        empty: Dict[str, Optional[str]] = {
            "instructions": None,
            "tools": None,
            "avatar_custom_image": None,
            "custom_voice_audio": None,
        }
        if not session_id:
            return empty
        shared = self._shared
        if shared is not None:
            with self._lock:
                rec = self._sessions.get(session_id)
                if rec is not None:
                    if rec.get("anonymous"):
                        return empty
                    for f in empty:
                        rec.pop(f, None)
                    rec["_handoff_cleared"] = True
            return shared.take_handoff(session_id)
        with self._lock:
            now = self._now()
            self._prune_locked(now, MAX_DIAGNOSTIC_SESSIONS)
            record = self._sessions.get(session_id)
            if not record:
                return empty
            return {f: record.pop(f, None) for f in empty}

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
        shared = self._shared
        if shared is not None:
            shared.clear_all_sessions()


_default_store = SessionStore(
    shared_store=build_default_shared_store(),
    now_fn=lambda: time.monotonic(),
)
_sessions = _default_store._sessions


def configure_shared_store(shared_store: Any = None) -> None:
    """Attach or clear the cross-instance shared store on the default module store."""
    _default_store._shared = shared_store


def issue(
    session_id=None,
    token=None,
    *,
    instructions=None,
    tools=None,
    avatar_custom_image=None,
    custom_voice_audio=None,
):
    return _default_store.issue(
        session_id,
        token,
        instructions=instructions,
        tools=tools,
        avatar_custom_image=avatar_custom_image,
        custom_voice_audio=custom_voice_audio,
        max_active=MAX_SESSIONS,
        max_diagnostic=MAX_DIAGNOSTIC_SESSIONS,
        join_ttl=JOIN_TTL_SECONDS,
        session_ttl=SESSION_TTL_SECONDS,
    )


def discard(session_id):
    """Release a session whose connection setup failed before returning its handles."""
    _default_store.discard(session_id)


def authorized(session_id, token):
    return _default_store.authorized(session_id, token)


def consume_join(session_id, join):
    return _default_store.consume_join(session_id, join)


def open_anonymous_connection(session_id):
    _default_store.open_anonymous_connection(
        session_id,
        max_active=MAX_SESSIONS,
        max_diagnostic=MAX_DIAGNOSTIC_SESSIONS,
        session_ttl=SESSION_TTL_SECONDS,
    )


def open_connection(session_id):
    _default_store.open_connection(session_id)


def release_local_connection(session_id) -> bool:
    return _default_store.release_local_connection(session_id)


def clear_shared_handoff(session_id):
    _default_store.clear_shared_handoff(session_id)


def close_connection(session_id):
    _default_store.close_connection(session_id)


def active_connection_count() -> int:
    return _default_store.active_connection_count()


def set_instructions(session_id, prompt, token=None):
    _default_store.set_instructions(session_id, prompt, token=token)


def take_instructions(session_id):
    return _default_store.take_instructions(session_id)


def take_tools(session_id):
    return _default_store.take_tools(session_id)


def take_avatar_custom_image(session_id):
    return _default_store.take_avatar_custom_image(session_id)


def take_custom_voice_audio(session_id):
    return _default_store.take_custom_voice_audio(session_id)


def take_handoff(session_id):
    return _default_store.take_handoff(session_id)
