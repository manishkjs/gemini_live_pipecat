"""Pipeline-owned turn intervals on one monotonic server clock.

Provider callbacks retain a Turn object. They never look up the latest turn.
No acoustic speech-end or client playback timestamp is invented.
"""
import time
import math
from dataclasses import dataclass
from diagnostic_buffer import record_metric


@dataclass
class Turn:
    session_id: str
    turn_id: int
    bot_type: str
    vad_stop: float | None = None
    vad_stop_padding_ms: float | None = None
    first_audio: float | None = None
    status: str | None = None

    def metric(self, stage, seconds):
        if (self.status is None and isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
                and math.isfinite(seconds) and seconds >= 0):
            record_metric(self.session_id, self.turn_id, self.bot_type, stage, seconds * 1000)

    def audio(self, now=None):
        if self.status is None and self.first_audio is None:
            self.first_audio = time.monotonic() if now is None else now

    def finish(self, status, now=None):
        if self.status is not None:
            return
        self.status = status
        details = {"vad_stop_padding_ms": self.vad_stop_padding_ms,
                   "endpoint": "first_server_audio_emission"}
        if status == "ok" and self.vad_stop is not None and self.first_audio is not None:
            elapsed = (self.first_audio - self.vad_stop) * 1000
            if elapsed >= 0:
                details["vad_stop_to_first_server_audio_ms"] = elapsed
                if self.vad_stop_padding_ms is not None:
                    details["estimated_speech_end_to_first_server_audio_ms"] = elapsed + self.vad_stop_padding_ms
                    details["estimation_method"] = "vad_event_interval_plus_configured_stop_padding"
        record_metric(self.session_id, self.turn_id, self.bot_type, "turn", status=status, **details)


class TurnTracker:
    def __init__(self, session_id, bot_type, *, vad_stop_padding_ms=None):
        self.session_id, self.bot_type = session_id, bot_type
        self.padding = vad_stop_padding_ms
        self.counter = 0
        self.current = Turn(session_id, 0, bot_type)  # Synthetic greeting: no VAD interval.
        self.speaking = False
        self.stopped = False

    def start(self):
        if not self.speaking:
            self.current.finish("interrupted")
        self.speaking, self.stopped = True, False

    def stop(self, *, vad=False, now=None):
        if not self.stopped:
            self.current.finish("abandoned")
            self.counter += 1
            self.current = Turn(self.session_id, self.counter, self.bot_type)
            self.stopped = True
        self.speaking = False
        if vad and self.current.vad_stop is None:
            self.current.vad_stop = time.monotonic() if now is None else now
            self.current.vad_stop_padding_ms = self.padding
        return self.current

    def interrupt(self):
        self.current.finish("interrupted")

    def close(self):
        self.current.finish("abandoned")
