"""STT latency as a user feels it: end of speech -> first transcript byte from the STT model.

The VAD only *decides* that speech ended after `stop_secs` of silence, so the true end of
speech is `decided_at - stop_secs`. A streaming model (Gemini 3.5 Transcribe Live) keeps
emitting while the user talks, so its first post-speech byte can land inside that silence
window, before the VAD has decided. Arrivals are therefore remembered per utterance and
matched against the true end once it is known.
"""
from typing import List, Optional

MAX_PLAUSIBLE_SECS = 10.0


class FirstByteAfterSpeechEnd:
    def __init__(self) -> None:
        self._arrivals: List[float] = []
        self._speech_end: Optional[float] = None
        self._reported = False

    def speech_started(self, now: float) -> None:
        self._arrivals.clear()
        self._speech_end = None
        self._reported = False

    def speech_stopped(self, decided_at: float, stop_secs: float) -> Optional[float]:
        """VAD decided the user stopped; returns latency if a byte already arrived."""
        self._speech_end = decided_at - max(stop_secs, 0.0)
        first = next((t for t in self._arrivals if t >= self._speech_end), None)
        return self._report(first) if first is not None else None

    def transcript_arrived(self, now: float) -> Optional[float]:
        """Any transcript message (interim or final); returns latency the first time it's known."""
        if self._speech_end is None:
            self._arrivals.append(now)
            return None
        return self._report(now) if now >= self._speech_end else None

    def final_latency(self, now: float) -> Optional[float]:
        """End of speech -> final transcript (what turn-taking actually waits for)."""
        return self._plausible(now - self._speech_end) if self._speech_end is not None else None

    def _report(self, arrived_at: float) -> Optional[float]:
        if self._reported:
            return None
        self._reported = True
        return self._plausible(arrived_at - self._speech_end)

    @staticmethod
    def _plausible(value: float) -> Optional[float]:
        return value if 0.0 <= value <= MAX_PLAUSIBLE_SECS else None
