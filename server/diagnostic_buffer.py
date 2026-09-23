"""Bounded, session-scoped diagnostics. Metrics are explicit, never log-parsed."""
import contextvars
import math
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DIAGNOSTIC_LOG_BUFFER = deque(maxlen=1500)
TURN_LATENCY_RECORDS = deque(maxlen=2000)
SESSION_ID = contextvars.ContextVar("diagnostic_session_id", default=None)
BOT_TYPE = contextvars.ContextVar("diagnostic_bot_type", default=None)
UNSCOPED = "__unscoped__"
BOT_TYPES = {"gemini-live", "tts-llm-stt"}


def current_session_id():
    return SESSION_ID.get() or UNSCOPED


def bind_session(session_id, bot_type=None):
    if bot_type is not None and bot_type not in BOT_TYPES:
        raise ValueError("Unknown bot_type")
    SESSION_ID.set(session_id or None)
    BOT_TYPE.set(bot_type)


def require_session(session_id):
    if not isinstance(session_id, str) or not session_id.strip() or session_id == UNSCOPED:
        raise ValueError("A non-empty session_id is required")
    return session_id


def _belongs_to(record, session_id):
    return record.get("session_id") == require_session(session_id)


def _numpy_percentile(sorted_values: List[float], p: float) -> float:
    """Calculate percentile using linear interpolation (standard numpy method)."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (p / 100.0) * (len(sorted_values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight

def compute_percentiles(values: List[float]) -> Dict[str, Any]:
    """Compute P50, P90, P95, Mean, Min, Max, and Count for a list of latency values (in ms)."""
    if not values:
        return {
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0,
            "count": 0
        }
    sorted_v = sorted(values)
    return {
        "p50": round(_numpy_percentile(sorted_v, 50), 1),
        "p90": round(_numpy_percentile(sorted_v, 90), 1),
        "p95": round(_numpy_percentile(sorted_v, 95), 1),
        "mean": round(sum(sorted_v) / len(sorted_v), 1),
        "min": round(sorted_v[0], 1),
        "max": round(sorted_v[-1], 1),
        "count": len(sorted_v)
    }

def record_metric(session_id, turn_id, bot_type, stage, value_ms=None, status="ok", **details):
    """One call per measured event; repeated sentences are distinct observations."""
    require_session(session_id)
    uncorrelated = turn_id is None and stage in {"stt", "llm", "tts", "live_ttfb"} and details.get("attribution") == "unavailable"
    valid_turn = isinstance(turn_id, int) and not isinstance(turn_id, bool) and turn_id >= 0
    if bot_type not in BOT_TYPES or not (uncorrelated or valid_turn):
        raise ValueError("Explicit bot_type and pipeline turn_id are required")
    if status not in {"ok", "interrupted", "abandoned"}:
        raise ValueError("Unknown turn status")
    if value_ms is not None and (isinstance(value_ms, bool) or not isinstance(value_ms, (int, float)) or not math.isfinite(value_ms) or value_ms < 0):
        raise ValueError("value_ms must be finite and nonnegative")
    entry = {**details, "session_id": session_id, "turn_id": turn_id, "bot_type": bot_type,
             "stage": stage, "status": status, "timestamp": datetime.now(timezone.utc).isoformat()}
    if value_ms is not None:
        entry["value_ms"] = value_ms
    if status != "ok":
        for key in ("turnaround_ms", "vad_stop_to_first_server_audio_ms", "estimated_speech_end_to_first_server_audio_ms"):
            entry.pop(key, None)
    TURN_LATENCY_RECORDS.append(entry)
    return entry


def append_raw_log_entry(message, level="INFO"):
    """Explicit logs only. No global log interceptor and no metric extraction."""
    if message.strip():
        DIAGNOSTIC_LOG_BUFFER.append({"timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level, "message": message.strip(), "session_id": current_session_id()})


def append_diagnostic_log(event_type, details, ttfb_ms=None, user_id=None, **kwargs):
    # Keep the existing event-log UI; latency comes exclusively from record_metric.
    append_raw_log_entry(f"[{event_type}] " + (f"({user_id}) " if user_id else "") + details)
    DIAGNOSTIC_LOG_BUFFER[-1]["event_type"] = event_type


def record_provider_usage(payload):
    """Retain numeric provider snapshots, keyed by response; never parse logs.

    This is a bounded diagnostic view, not the complete call billing ledger.
    Missing identity or invalid counters leave usage unavailable.
    """
    session_id, response_id = payload.get("session_id"), payload.get("response_id")
    usage = payload.get("usage") or {}
    if not session_id or session_id == UNSCOPED or not response_id:
        return
    keys = ("prompt_token_count", "response_token_count", "total_token_count")
    counters = {key: usage.get(key) for key in keys}
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in counters.values()):
        return
    for detail_key in (
        "prompt_tokens_details",
        "cache_tokens_details",
        "response_tokens_details",
        "thoughts_token_count",
        "cached_content_token_count",
    ):
        if detail_key in usage:
            counters[detail_key] = usage[detail_key]
    DIAGNOSTIC_LOG_BUFFER.append({"timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id, "response_id": response_id, "event_type": "Provider usage",
        "level": "INFO", "message": "Provider usage snapshot", "usage": counters})


def _usage_summary(session_id):
    responses = {r["response_id"]: r["usage"] for r in DIAGNOSTIC_LOG_BUFFER
                 if r.get("session_id") == session_id and "usage" in r}
    return {"count": len(responses), "scope": "retained_response_snapshots",
            **{key: sum(u[key] for u in responses.values()) for key in
               ("prompt_token_count", "response_token_count", "total_token_count")}}


def get_latency_summary(session_id=None):
    require_session(session_id)
    scoped = [r for r in TURN_LATENCY_RECORDS if _belongs_to(r, session_id)]
    values = lambda stage: [r["value_ms"] for r in scoped if r["stage"] == stage and r["status"] == "ok" and "value_ms" in r]
    result = {stage: compute_percentiles(values(stage)) for stage in ("stt", "llm", "tts", "live_ttfb")}
    completed = [r["vad_stop_to_first_server_audio_ms"] for r in scoped
                 if r["stage"] == "turn" and r["status"] == "ok" and "vad_stop_to_first_server_audio_ms" in r]
    result.update(vad_stop_to_first_server_audio=compute_percentiles(completed),
                  # Compatibility key is intentionally empty: this is not E2E/playback.
                  total_turnaround=compute_percentiles([]), caller_perceived_latency_available=False,
                  retention_limit=TURN_LATENCY_RECORDS.maxlen, retention_scope="process-wide",
                  provider_usage=_usage_summary(session_id),
                  attribution_unavailable_count=sum(r.get("attribution") == "unavailable" for r in scoped),
                  turns=scoped[-100:])
    return result


def get_recent_diagnostic_logs(limit=500, session_id=None):
    require_session(session_id)
    limit = max(1, min(int(limit), DIAGNOSTIC_LOG_BUFFER.maxlen))
    return [r for r in DIAGNOSTIC_LOG_BUFFER if _belongs_to(r, session_id)][-limit:]


def clear_diagnostic_logs(session_id=None):
    require_session(session_id)
    for buffer in (DIAGNOSTIC_LOG_BUFFER, TURN_LATENCY_RECORDS):
        kept = [r for r in buffer if r.get("session_id") != session_id]
        buffer.clear()
        buffer.extend(kept)


def install_log_capture():
    """Preserve raw diagnostic logs; this sink never derives metrics from text."""
    from loguru import logger
    def capture(message):
        record = message.record
        append_raw_log_entry(record["message"], record["level"].name)
    return logger.add(capture, level="DEBUG")


_LOG_SINK = install_log_capture()
