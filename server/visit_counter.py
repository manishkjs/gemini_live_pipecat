import json
import os
import threading
from collections import OrderedDict
from typing import Dict, Optional

VISIT_LABEL = "live studio visits"
_DEFAULT_SEED = int(os.environ.get("VISIT_COUNTER_SEED", "800"))
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


def _load_locked() -> int:
    global _count
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
        # Read-only container filesystems still keep the in-memory count.
        pass


def configure_store(path: Optional[str], initial_seed: int = _DEFAULT_SEED) -> None:
    """Configure or reset the persistence path (used by tests and startup)."""
    global _store_path, _initial_seed, _count
    with _lock:
        _store_path = path if path is not None else _DEFAULT_PATH
        _initial_seed = initial_seed
        _count = None
        _seen_page_loads.clear()


def get_visits() -> Dict[str, object]:
    with _lock:
        visits = _load_locked()
        return {"visits": visits, "label": VISIT_LABEL}


def record_visit(page_load_id: Optional[str] = None) -> Dict[str, object]:
    global _count
    with _lock:
        visits = _load_locked()
        clean_id = (page_load_id or "").strip()[:128]
        if clean_id:
            if clean_id in _seen_page_loads:
                return {"visits": visits, "label": VISIT_LABEL}
            _seen_page_loads[clean_id] = True
            while len(_seen_page_loads) > _MAX_SEEN_PAGE_LOADS:
                _seen_page_loads.popitem(last=False)
        visits += 1
        _count = visits
        _save_locked(visits)
        return {"visits": visits, "label": VISIT_LABEL}
