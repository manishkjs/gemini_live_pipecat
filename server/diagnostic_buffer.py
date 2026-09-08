import logging
from collections import deque
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger

# Ring buffer for retaining recent Cloud Run / backend logs for UI diagnostics
DIAGNOSTIC_LOG_BUFFER: deque = deque(maxlen=1500)

# Structured storage for individual turn latencies across session
TURN_LATENCY_RECORDS: List[Dict[str, Any]] = []

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

def record_turn_latency(stage: str, value_ms: float, details: str = ""):
    """Record an individual latency event for a specific stage (stt, llm, tts, live_ttfb)."""
    if value_ms <= 0 or value_ms > 30000:
        return
    now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = {
        "timestamp": now_str,
        "stage": stage,
        "value_ms": round(float(value_ms), 1),
        "details": details
    }
    TURN_LATENCY_RECORDS.append(entry)

def parse_and_record_latency_from_log(msg: str):
    """Auto-extract and record latency measurements from log strings."""
    lower = msg.lower()
    
    # 1. Native Gemini Live TTFB
    if "ttft calculation:" in lower or "live ttfb" in lower or ("live" in lower and "ttfb" in lower) or ("geminilive" in lower and "ttfb:" in lower):
        try:
            import re
            m = re.search(r"(\d+(?:\.\d+)?)\s*ms", lower)
            if m:
                record_turn_latency("live_ttfb", float(m.group(1)), "Gemini Live Native Audio")
            else:
                m_sec = re.search(r"(\d+(?:\.\d+)?)\s*s", lower)
                if m_sec:
                    record_turn_latency("live_ttfb", float(m_sec.group(1)) * 1000.0, "Gemini Live Native Audio")
        except Exception:
            pass

    # 2. Cloud Speech v2 STT Latency
    elif "stt latency" in lower:
        try:
            import re
            m = re.search(r"(\d+(?:\.\d+)?)\s*ms", msg)
            if m:
                record_turn_latency("stt", float(m.group(1)), "STT v2 Chirp")
            else:
                m_sec = re.search(r"(\d+(?:\.\d+)?)\s*s", msg)
                if m_sec:
                    record_turn_latency("stt", float(m_sec.group(1)) * 1000.0, "STT v2 Chirp")
        except Exception:
            pass

    # 3. LLM Latency / TTFB
    elif "llm latency" in lower or ("llmservice" in lower and "ttfb:" in lower):
        try:
            import re
            m = re.search(r"ttfb:\s*(\d+(?:\.\d+)?)\s*s", lower) or re.search(r"latency:\s*(\d+(?:\.\d+)?)\s*s", lower)
            if m:
                record_turn_latency("llm", float(m.group(1)) * 1000.0, "LLM TTFB")
            else:
                m_ms = re.search(r"(\d+(?:\.\d+)?)\s*ms", lower)
                if m_ms:
                    record_turn_latency("llm", float(m_ms.group(1)), "LLM TTFB")
        except Exception:
            pass

    # 4. TTS Latency
    elif "tts latency" in lower or ("ttsservice" in lower and "ttfb:" in lower):
        try:
            import re
            m = re.search(r"ttfb:\s*(\d+(?:\.\d+)?)\s*s", lower) or re.search(r"latency:\s*(\d+(?:\.\d+)?)\s*s", lower)
            if m:
                record_turn_latency("tts", float(m.group(1)) * 1000.0, "TTS TTFB")
            else:
                m_ms = re.search(r"(\d+(?:\.\d+)?)\s*ms", lower)
                if m_ms:
                    record_turn_latency("tts", float(m_ms.group(1)), "TTS TTFB")
        except Exception:
            pass

def append_raw_log_entry(message: str, level: str = "INFO"):
    clean_msg = message.strip()
    if not clean_msg:
        return
    
    # Auto-extract and record latency measurements
    parse_and_record_latency_from_log(clean_msg)

    # Extract numeric TTFB if present for floating badge live latency counter
    ttfb_ms = None
    if "ttft calculation:" in clean_msg.lower() or "ttfb:" in clean_msg.lower():
        try:
            for word in clean_msg.replace("s", " ").replace("ms", " ").split():
                try:
                    val = float(word)
                    if val < 20.0:  # seconds to ms conversion
                        ttfb_ms = round(val * 1000.0, 1)
                    else:
                        ttfb_ms = round(val, 1)
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    entry = {
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "level": level,
        "message": clean_msg,
        "ttfb_ms": ttfb_ms
    }
    DIAGNOSTIC_LOG_BUFFER.append(entry)

def append_diagnostic_log(event_type: str, details: str, ttfb_ms: Optional[float] = None, user_id: Optional[str] = None, **kwargs):
    if user_id:
        msg = f"[{event_type}] ({user_id}) {details}"
    else:
        msg = f"[{event_type}] {details}"
    clean_msg = msg.strip()

    if ttfb_ms is not None:
        if "LIVE" in event_type.upper() or "LIVE" in details.upper():
            record_turn_latency("live_ttfb", ttfb_ms, f"{event_type}: {details}")
        elif "LLM" in event_type.upper():
            record_turn_latency("llm", ttfb_ms, f"{event_type}: {details}")
        elif "STT" in event_type.upper():
            record_turn_latency("stt", ttfb_ms, f"{event_type}: {details}")
        elif "TTS" in event_type.upper():
            record_turn_latency("tts", ttfb_ms, f"{event_type}: {details}")

    entry = {
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "level": "INFO",
        "message": clean_msg,
        "ttfb_ms": ttfb_ms
    }
    DIAGNOSTIC_LOG_BUFFER.append(entry)

def get_latency_summary() -> Dict[str, Any]:
    """Aggregate all turn latencies and compute official statistical percentiles."""
    live_vals = [r["value_ms"] for r in TURN_LATENCY_RECORDS if r["stage"] == "live_ttfb"]
    stt_vals = [r["value_ms"] for r in TURN_LATENCY_RECORDS if r["stage"] == "stt"]
    llm_vals = [r["value_ms"] for r in TURN_LATENCY_RECORDS if r["stage"] == "llm"]
    tts_vals = [r["value_ms"] for r in TURN_LATENCY_RECORDS if r["stage"] == "tts"]

    # Compute overall turnarounds (for cascaded or live)
    total_vals = []
    if live_vals:
        total_vals = live_vals
    elif llm_vals:
        # Approximate end-to-end total
        for i in range(len(llm_vals)):
            s = stt_vals[i] if i < len(stt_vals) else 0.0
            l = llm_vals[i]
            t = tts_vals[i] if i < len(tts_vals) else 0.0
            total_vals.append(round(s + l + t, 1))

    return {
        "live_ttfb": compute_percentiles(live_vals),
        "stt": compute_percentiles(stt_vals),
        "llm": compute_percentiles(llm_vals),
        "tts": compute_percentiles(tts_vals),
        "total_turnaround": compute_percentiles(total_vals),
        "turns": list(TURN_LATENCY_RECORDS)[-100:]  # Recent 100 turns
    }

class BackendDiagnosticHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            append_raw_log_entry(msg, level=record.levelname)
        except Exception:
            pass

def setup_global_backend_log_interceptor():
    """Intercept Loguru and Python standard logging to capture backend/Cloud Run stdout in real-time."""
    try:
        def _loguru_sink(message):
            text = str(message)
            lvl = "ERROR" if any(k in text.upper() for k in ["ERROR", "EXCEPTION", "TRACEBACK", "CRITICAL"]) else ("WARNING" if "WARN" in text.upper() else ("DEBUG" if "DEBUG" in text.upper() else "INFO"))
            append_raw_log_entry(text, level=lvl)

        logger.add(_loguru_sink, format="{message}", level="DEBUG")
    except Exception:
        pass

    root_logger = logging.getLogger()
    if not any(isinstance(h, BackendDiagnosticHandler) for h in root_logger.handlers):
        root_logger.addHandler(BackendDiagnosticHandler())

def get_recent_diagnostic_logs(limit: int = 500) -> List[Dict[str, Any]]:
    return list(DIAGNOSTIC_LOG_BUFFER)[-limit:]

def clear_diagnostic_logs() -> None:
    DIAGNOSTIC_LOG_BUFFER.clear()
    TURN_LATENCY_RECORDS.clear()

# Initialize global interceptor immediately on import
setup_global_backend_log_interceptor()
