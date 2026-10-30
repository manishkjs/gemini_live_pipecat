"""Per-day record of which signed-in Googlers used the studio.

The public demo URL sits behind Cloud IAP, which stamps every request with
``X-Goog-Authenticated-User-Email: accounts.google.com:<ldap>@google.com``.
We keep one Firestore document per (UTC day, email) in collection
``studio_daily_users`` of the ``v2v-demo-visits`` database (the same database
the visit counter uses). Writes are best effort and never fail a request.

Outside Cloud Run (no ``K_SERVICE``) the records go to a local JSONL file so
the hooks can be exercised by tests and local runs.
"""
import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Optional

import visit_counter

COLLECTION = "studio_daily_users"
IAP_EMAIL_HEADER = "x-goog-authenticated-user-email"
RETENTION_DAYS = 30
_DEFAULT_LOCAL_PATH = os.environ.get(
    "DEMO_USERS_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "studio_daily_users.jsonl"),
)
_local_path: Optional[str] = _DEFAULT_LOCAL_PATH
_lock = threading.Lock()


def configure_store(path: Optional[str]) -> None:
    """Point local (non Cloud Run) records at ``path``; tests use a temp file."""
    global _local_path
    with _lock:
        _local_path = path if path is not None else _DEFAULT_LOCAL_PATH


def googler_email(headers: Mapping[str, str]) -> Optional[str]:
    """The IAP-authenticated email, or None when the request did not come through IAP."""
    raw = ""
    for key, value in headers.items():
        if str(key).lower() == IAP_EMAIL_HEADER:
            raw = str(value or "")
            break
    raw = raw.strip()
    if not raw:
        return None
    if ":" in raw:
        raw = raw.rsplit(":", 1)[1].strip()
    raw = raw.lower()
    if "@" not in raw or len(raw) > 254:
        return None
    return raw


def _doc_id(day: str, email: str) -> str:
    safe = email.replace("/", "_")
    return f"{day}_{safe}"


def _uses_firestore() -> bool:
    return bool(os.environ.get("K_SERVICE") and os.environ.get("GCP_PROJECT_ID"))


def _string_values(values) -> Dict[str, Any]:
    return {"values": [{"stringValue": str(v)} for v in values if v]}


def _firestore_record(email: str, kind: str, now: datetime, extras: Dict[str, str]) -> bool:
    db_path = visit_counter._firestore_db_path()
    token = visit_counter._get_firestore_token()
    if not db_path or not token:
        return False
    day = now.strftime("%Y-%m-%d")
    doc = f"{db_path}/documents/{COLLECTION}/{_doc_id(day, email)}"
    epoch = int(now.timestamp())
    expires = (now + timedelta(days=RETENTION_DAYS)).isoformat().replace("+00:00", "Z")
    counter = "sessions_started" if kind == "session" else "page_visits"
    transforms = [
        {"fieldPath": counter, "increment": {"integerValue": "1"}},
        {"fieldPath": "first_seen_epoch", "minimum": {"integerValue": str(epoch)}},
        {"fieldPath": "last_seen_epoch", "maximum": {"integerValue": str(epoch)}},
    ]
    for field in ("personas", "engines", "models"):
        value = extras.get(field)
        if value:
            transforms.append({"fieldPath": field, "appendMissingElements": _string_values([value])})
    payload = {
        "writes": [
            {
                "update": {
                    "name": doc,
                    "fields": {
                        "email": {"stringValue": email},
                        "date": {"stringValue": day},
                        "expires_at": {"timestampValue": expires},
                    },
                },
                "updateMask": {"fieldPaths": ["email", "date", "expires_at"]},
                "updateTransforms": transforms,
            }
        ]
    }
    req = urllib.request.Request(
        f"https://firestore.googleapis.com/v1/{db_path}/documents:commit",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3.0):
            return True
    except Exception:
        return False


def _local_record(email: str, kind: str, now: datetime, extras: Dict[str, str]) -> bool:
    path = _local_path
    if not path:
        return False
    row = {"email": email, "kind": kind, "at": now.isoformat(), **{k: v for k, v in extras.items() if v}}
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        return True
    except Exception:
        return False


def record_activity(
    email: Optional[str],
    kind: str = "visit",
    persona: Optional[str] = None,
    engine: Optional[str] = None,
    model: Optional[str] = None,
) -> bool:
    """Count one page visit or session start for ``email`` on today's UTC record.

    Returns True when a record was written. Anonymous (non IAP) traffic is ignored.
    """
    if not email or kind not in ("visit", "session"):
        return False
    now = datetime.now(timezone.utc)
    extras = {"personas": persona or "", "engines": engine or "", "models": model or ""}
    if _uses_firestore():
        return _firestore_record(email, kind, now, extras)
    return _local_record(email, kind, now, extras)
