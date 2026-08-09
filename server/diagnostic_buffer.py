import logging
from collections import deque
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger

# Ring buffer for retaining recent Cloud Run / backend logs for UI diagnostics
DIAGNOSTIC_LOG_BUFFER: deque = deque(maxlen=1500)

def append_raw_log_entry(message: str, level: str = "INFO"):
    clean_msg = message.strip()
    if not clean_msg:
        return
    
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

def append_diagnostic_log(event_type: str, details: str, ttfb_ms: Optional[float] = None):
    msg = f"[{event_type}] {details}"
    clean_msg = msg.strip()
    entry = {
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "level": "INFO",
        "message": clean_msg,
        "ttfb_ms": ttfb_ms
    }
    DIAGNOSTIC_LOG_BUFFER.append(entry)

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

# Initialize global interceptor immediately on import
setup_global_backend_log_interceptor()
