import json
import os
import threading
import urllib.request
from collections import OrderedDict
from typing import Dict, Optional

VISIT_LABEL = "live studio visits"
VISIT_COUNTER_DB_ID = "v2v-demo-visits"
_DEFAULT_SEED = int(os.environ.get("VISIT_COUNTER_SEED", "0"))
_DEFAULT_PATH = os.environ.get(
    "VISIT_COUNTER_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "studio_visits.json"),
)

_lock = threading.Lock()
_store_path: Optional[str] = _DEFAULT_PATH
_initial_seed: int = _DEFAULT_SEED
_count: Optional[int] = None
_seen_page_loads: "OrderedDict[str, bool]" = OrderedDict()
_MAX_SEEN_PAGE_LOADS = 2048
_use_firestore: bool = bool(os.environ.get("K_SERVICE") and os.environ.get("GCP_PROJECT_ID"))
_creds = None


def _get_firestore_token() -> Optional[str]:
    global _creds
    try:
        import google.auth
        from google.auth.transport.requests import Request as GoogleAuthRequest

        if _creds is None:
            _creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/datastore"])
        if not _creds.valid:
            _creds.refresh(GoogleAuthRequest())
        return _creds.token
    except Exception:
        return None


def _firestore_db_path() -> Optional[str]:
    project_id = os.environ.get("GCP_PROJECT_ID", "").strip()
    if not project_id:
        return None
    db_id = os.environ.get("VISIT_COUNTER_DB_ID", VISIT_COUNTER_DB_ID).strip() or VISIT_COUNTER_DB_ID
    return f"projects/{project_id}/databases/{db_id}"


def _firestore_doc_path() -> Optional[str]:
    db_path = _firestore_db_path()
    if not db_path:
        return None
    doc_id = os.environ.get("VISIT_COUNTER_DOC_ID", "v2v_demo_visits").strip() or "v2v_demo_visits"
    return f"{db_path}/documents/studio_telemetry/{doc_id}"


def _firestore_get_visits() -> Optional[int]:
    doc_path = _firestore_doc_path()
    token = _get_firestore_token()
    if not doc_path or not token:
        return None
    url = f"https://firestore.googleapis.com/v1/{doc_path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_val = data.get("fields", {}).get("visits", {}).get("integerValue")
            if raw_val is not None:
                return max(0, int(raw_val))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0
    except Exception:
        pass
    return None


def _firestore_increment_visits() -> Optional[int]:
    db_path = _firestore_db_path()
    doc_path = _firestore_doc_path()
    token = _get_firestore_token()
    if not db_path or not doc_path or not token:
        return None
    url = f"https://firestore.googleapis.com/v1/{db_path}/documents:commit"
    payload = {
        "writes": [
            {
                "transform": {
                    "document": doc_path,
                    "fieldTransforms": [
                        {
                            "fieldPath": "visits",
                            "increment": {"integerValue": "1"},
                        }
                    ],
                }
            }
        ]
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("writeResults") or []
            if results:
                transform_results = results[0].get("transformResults") or []
                if transform_results and "integerValue" in transform_results[0]:
                    return max(0, int(transform_results[0]["integerValue"]))
    except Exception:
        pass
    return None


def _load_locked() -> int:
    global _count
    if _use_firestore:
        remote = _firestore_get_visits()
        if remote is not None:
            _count = remote
            return _count
    if _count is not None:
        return _count
    if _store_path and os.path.exists(_store_path):
        try:
            with open(_store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("visits"), int):
                    _count = max(0, data["visits"])
                    return _count
        except Exception:
            pass
    _count = max(0, _initial_seed)
    return _count


def _save_locked(visits: int) -> None:
    if not _store_path:
        return
    try:
        parent = os.path.dirname(_store_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp_path = f"{_store_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"visits": visits, "label": VISIT_LABEL}, f)
        os.replace(tmp_path, _store_path)
    except Exception:
        pass


def configure_store(path: Optional[str], initial_seed: int = _DEFAULT_SEED) -> None:
    """Configure or reset the persistence path (used by tests and startup)."""
    global _store_path, _initial_seed, _count, _use_firestore
    with _lock:
        _store_path = path if path is not None else _DEFAULT_PATH
        _initial_seed = initial_seed
        _count = None
        _seen_page_loads.clear()
        _use_firestore = bool(
            path is None and os.environ.get("K_SERVICE") and os.environ.get("GCP_PROJECT_ID")
        )


def get_visits() -> Dict[str, object]:
    with _lock:
        visits = _load_locked()
        return {"visits": visits, "label": VISIT_LABEL}


def record_visit(page_load_id: Optional[str] = None) -> Dict[str, object]:
    global _count
    with _lock:
        clean_id = (page_load_id or "").strip()[:128]
        if clean_id and clean_id in _seen_page_loads:
            visits = _load_locked()
            return {"visits": visits, "label": VISIT_LABEL}

        if _use_firestore:
            remote_new = _firestore_increment_visits()
            if remote_new is not None:
                if clean_id:
                    _seen_page_loads[clean_id] = True
                    while len(_seen_page_loads) > _MAX_SEEN_PAGE_LOADS:
                        _seen_page_loads.popitem(last=False)
                _count = remote_new
                _save_locked(remote_new)
                return {"visits": remote_new, "label": VISIT_LABEL}

        visits = _load_locked()
        if clean_id:
            _seen_page_loads[clean_id] = True
            while len(_seen_page_loads) > _MAX_SEEN_PAGE_LOADS:
                _seen_page_loads.popitem(last=False)
        visits += 1
        _count = visits
        _save_locked(visits)
        return {"visits": visits, "label": VISIT_LABEL}
