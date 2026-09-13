"""Expiring capabilities for demo-session diagnostics and one websocket join.

This protects one session from another caller. Deployment authentication and
multi-instance routing remain the hosting layer's responsibility.
"""
import secrets
import time
from uuid import uuid4

SESSION_TTL_SECONDS = 4 * 60 * 60
JOIN_TTL_SECONDS = 300
MAX_SESSIONS = 1000
_sessions = {}


def _prune():
    now = time.monotonic()
    for key in [key for key, value in _sessions.items() if value["expires"] <= now]:
        del _sessions[key]


def issue(session_id=None, token=None):
    _prune()
    session_id = session_id or str(uuid4())
    if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128:
        raise ValueError("Invalid session_id")
    if session_id in _sessions:
        raise ValueError("Session already exists; create a fresh session_id")
    if len(_sessions) >= MAX_SESSIONS:
        raise RuntimeError("Session capacity reached")
    if token is not None and (len(token) < 32 or len(token) > 256 or not token.isascii()):
        raise ValueError("Invalid session capability")
    token = token or secrets.token_urlsafe(32)
    join = secrets.token_urlsafe(32)
    now = time.monotonic()
    _sessions[session_id] = {"token": token, "join": join, "join_expires": now + JOIN_TTL_SECONDS,
                             "expires": now + SESSION_TTL_SECONDS}
    return session_id, token, join


def authorized(session_id, token):
    _prune()
    record = _sessions.get(session_id)
    return bool(record and isinstance(token, str) and token.isascii()
                and secrets.compare_digest(record["token"], token))


def consume_join(session_id, join):
    _prune()
    record = _sessions.get(session_id)
    if not record or not record["join"] or record["join_expires"] <= time.monotonic():
        return False
    if not isinstance(join, str) or not join.isascii() or not secrets.compare_digest(record["join"], join):
        return False
    record["join"] = None
    return True


def set_instructions(session_id, prompt):
    _sessions[session_id]["instructions"] = prompt


def take_instructions(session_id):
    _prune()
    record = _sessions.get(session_id)
    return record.pop("instructions", None) if record else None
