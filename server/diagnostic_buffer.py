import logging
import sys
from collections import deque
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger

DIAGNOSTIC_LOG_BUFFER: deque = deque(maxlen=1500)

def classify_tab_and_badge(message_str: str) -> Dict[str, Any]:
    msg_low = message_str.lower()
    if "ttfb" in msg_low or "ttft" in msg_low or "turn token usage" in msg_low or "latency" in msg_low:
        return {"tab": "latency", "badge": "⚡ Latency Profile"}
    elif any(k in msg_low for k in ["mem0", "recall_user_memories", "search_user_memory", "save_user_memory", "embedder", "qdrant", "pgvector", "alloydb", "tool result", "tool output"]):
        return {"tab": "mem0", "badge": "🧠 Mem0 Engine"}
    elif "multitenant" in msg_low or "identify_user" in msg_low or "active_user_id" in msg_low or "normalize_user_id" in msg_low or "identity" in msg_low:
        return {"tab": "identity", "badge": "👤 Multi-Tenant"}
    elif "transcription" in msg_low or "interruption" in msg_low or "stopped speaking" in msg_low or "started speaking" in msg_low:
        return {"tab": "audio", "badge": "🎙️ Audio Turn"}
    else:
        return {"tab": "all", "badge": "📄 Raw Backend"}

def append_raw_log_entry(message: str, level: str = "INFO"):
    clean_msg = message.strip()
    if not clean_msg:
        return
    classification = classify_tab_and_badge(clean_msg)
    
    # Extract numeric TTFB if present for floating badge update
    ttfb_ms = None
    if "ttft calculation:" in clean_msg.lower() or "ttfb:" in clean_msg.lower():
        try:
            for word in clean_msg.replace("s", " ").replace("ms", " ").split():
                try:
                    val = float(word)
                    if val < 20.0:  # seconds
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
        "tab": classification["tab"],
        "badge": classification["badge"],
        "ttfb_ms": ttfb_ms
    }
    DIAGNOSTIC_LOG_BUFFER.append(entry)

def append_diagnostic_log(event_type: str, details: str, ttfb_ms: Optional[float] = None, user_id: str = "default_user"):
    msg = f"[{event_type}] ({user_id}) {details}"
    append_raw_log_entry(msg, level="INFO")

class BackendDiagnosticHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            append_raw_log_entry(msg, level=record.levelname)
        except Exception:
            pass

def setup_global_backend_log_interceptor():
    """Intercept all Loguru and Python standard logging to capture 100% of backend trace right for UI."""
    try:
        logger.add(
            lambda msg: append_raw_log_entry(msg, level="INFO" if "INFO" in msg else ("DEBUG" if "DEBUG" in msg else "ERROR")),
            format="{message}",
            level="DEBUG"
        )
    except Exception:
        pass

    root_logger = logging.getLogger()
    if not any(isinstance(h, BackendDiagnosticHandler) for h in root_logger.handlers):
        root_logger.addHandler(BackendDiagnosticHandler())

def get_recent_diagnostic_logs(limit: int = 500) -> List[Dict[str, Any]]:
    return list(DIAGNOSTIC_LOG_BUFFER)[-limit:]

def clear_diagnostic_logs() -> None:
    DIAGNOSTIC_LOG_BUFFER.clear()

# Initialize global interceptor immediately
setup_global_backend_log_interceptor()
