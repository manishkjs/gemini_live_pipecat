"""Model-selected phases and validation of structured booking fields.

This module never reads or classifies caller speech. Gemini interprets the
conversation and chooses a phase through switch_phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List

SOP_01_OPENING = "SOP_01_OPENING"
SOP_02_DISCOVERY = "SOP_02_DISCOVERY"
SOP_03_PINCODE = "SOP_03_PINCODE"
SOP_04_BOOKED = "SOP_04_BOOKED"


@dataclass(frozen=True)
class PhaseDefinition:
    phase_id: str
    index: int
    title: str


PRAGYA_PHASES = [
    PhaseDefinition(SOP_01_OPENING, 0, "Outbound intent validation"),
    PhaseDefinition(SOP_02_DISCOVERY, 1, "Supercar preview"),
    PhaseDefinition(SOP_03_PINCODE, 2, "Lounge visit"),
    PhaseDefinition(SOP_04_BOOKED, 3, "VIP appointment locked"),
]
_PHASE_INDEX = {p.phase_id: p.index for p in PRAGYA_PHASES}
_PHASE_TITLE = {p.phase_id: p.title for p in PRAGYA_PHASES}


class PragyaPhaseTracker:
    """Current delivered phase, retained progress, and actual booking evidence."""

    def __init__(self) -> None:
        self.current_phase = SOP_01_OPENING
        self.furthest_phase = SOP_01_OPENING
        self.booking_confirmed = False

    @property
    def current_index(self) -> int:
        return _PHASE_INDEX[self.current_phase]

    def title_of(self, phase_id: str) -> str:
        return _PHASE_TITLE.get(phase_id, phase_id)

    def validate_phase(self, phase_id: str) -> None:
        if not isinstance(phase_id, str) or phase_id not in _PHASE_INDEX or phase_id == SOP_01_OPENING:
            raise ValueError("Choose SOP_02_DISCOVERY, SOP_03_PINCODE, or SOP_04_BOOKED.")
        if phase_id == SOP_04_BOOKED and not self.booking_confirmed:
            raise ValueError("Complete create_appointment_booking successfully before selecting SOP_04_BOOKED.")

    def select_phase(self, phase_id: str) -> None:
        self.validate_phase(phase_id)
        self.current_phase = phase_id
        if _PHASE_INDEX[phase_id] > _PHASE_INDEX[self.furthest_phase]:
            self.furthest_phase = phase_id


_DAY_LABELS = frozenset({
    "today", "tomorrow", "day after tomorrow", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday",
})


def resolves_to_a_day(text: str) -> bool:
    """Accept a tool-formatted day, never extract one from a sentence."""
    if text.lower() in _DAY_LABELS:
        return True
    try:
        return date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def resolves_to_a_time(text: str) -> bool:
    """Accept a concrete clock time supplied by the model."""
    for pattern in ("%H:%M", "%I:%M %p", "%I %p", "%I%p"):
        try:
            datetime.strptime(text, pattern)
            return True
        except ValueError:
            pass
    return False


class CallSlots:
    """Server-authoritative key/value state for one call.

    Gemini supplies structured fields through tools. Validation checks their
    format, not whether the caller actually said them. Empty fields preserve
    previously collected values; invalid fields are reported to the model.
    """

    #: Fields the model may write, because only it can hear them.
    MODEL_PROPOSED = frozenset({"pincode", "car_choice", "visit_date", "visit_time"})
    #: Fields only the server may write. A lounge comes from a lookup, never
    #: from a sentence.
    SERVER_DERIVED = frozenset({"lounge_id", "lounge_name"})
    #: Fields only the booking tool may write.
    TOOL_OWNED = frozenset({"booking_status", "booking_ref"})

    #: What the server will not let a booking proceed without. The car is
    #: deliberately absent: people visit a showroom to make up their minds.
    REQUIRED_FOR_BOOKING = ("pincode", "visit_date", "visit_time")

    def __init__(self) -> None:
        self._values: Dict[str, Any] = {"booking_status": "not_started"}

    # -- reads --------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def as_dict(self) -> Dict[str, Any]:
        """A copy safe to broadcast to the UI."""
        return dict(self._values)

    def missing_for_booking(self) -> List[str]:
        return [k for k in self.REQUIRED_FOR_BOOKING if not self._values.get(k)]

    def is_bookable(self) -> bool:
        return not self.missing_for_booking()

    # -- writes -------------------------------------------------------------

    def propose(self, **candidates: Any) -> List[str]:
        """Merge valid tool fields and return the names of invalid fields."""
        invalid: List[str] = []
        for key, raw in candidates.items():
            if key not in self.MODEL_PROPOSED or raw is None or raw == "":
                continue
            value = self._clean(key, raw)
            if value is None:
                invalid.append(key)
            elif self._values.get(key) != value:
                was_present = key in self._values
                self._values[key] = value
                self._invalidate(key, was_present=was_present)
        return invalid

    def set_server(self, **values: Any) -> List[str]:
        """Write a server-derived field, e.g. the matched lounge."""
        return self._trusted_write(self.SERVER_DERIVED, values)

    def set_tool(self, **values: Any) -> List[str]:
        """Write a tool-owned field, e.g. the confirmed booking reference."""
        return self._trusted_write(self.TOOL_OWNED, values)

    # -- internals ----------------------------------------------------------

    def _trusted_write(self, allowed: frozenset, values: Dict[str, Any]) -> List[str]:
        changed: List[str] = []
        for key, value in values.items():
            if key not in allowed or self._values.get(key) == value:
                continue
            was_present = key in self._values
            self._values[key] = value
            changed.append(key)
            self._invalidate(key, was_present=was_present)
        return changed

    def _invalidate(self, key: str, *, was_present: bool = False) -> None:
        if key == "pincode":
            self._values.pop("lounge_id", None)
            self._values.pop("lounge_name", None)
        if was_present and key in ("pincode", "visit_date", "visit_time", "car_choice"):
            if self._values.get("booking_status") == "confirmed":
                self._values["booking_status"] = "not_started"
                self._values.pop("booking_ref", None)

    @staticmethod
    def _clean(key: str, raw: Any) -> Any:
        """Normalise and verify one proposed value, or None to reject it."""
        if raw is None:
            return None
        if not isinstance(raw, str):
            return None
        text = raw.strip()
        if not text:
            return None

        if key == "pincode":
            return text if (len(text) == 6 and text.isascii()
                            and text.isdigit() and text[0] != "0") else None
        if key == "visit_date":
            return text if resolves_to_a_day(text) else None
        if key == "visit_time":
            return text if resolves_to_a_time(text) else None
        return text

    def build_corrective_action(
        self,
        *,
        invalid_fields: Optional[List[str]] = None,
        missing_fields: Optional[List[str]] = None,
        raw_args: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build a deterministic corrective action prompt to steer the model after validation errors or missing slots."""
        invalid_fields = invalid_fields or []
        missing_fields = missing_fields or []
        raw_args = raw_args or {}

        known_pairs = [
            f"{k}={self._values[k]}"
            for k in ("pincode", "visit_date", "visit_time", "car_choice", "lounge_name")
            if self._values.get(k)
        ]
        known_str = (
            f"Already collected (DO NOT re-ask these): {', '.join(known_pairs)}. "
            if known_pairs
            else "No booking fields collected yet. "
        )

        hints: List[str] = []
        if "pincode" in invalid_fields:
            bad_pin = raw_args.get("pincode", "")
            hints.append(
                f"Rejected pincode={bad_pin!r}: PIN code MUST be exactly 6 digits (not a city name). "
                "Politely ask the caller for their 6-digit postal PIN code (e.g., 400051 for Mumbai BKC, "
                "110037 for Delhi Aerocity, or 560001 for Bengaluru Lavelle Road)."
            )
        if "visit_date" in invalid_fields:
            bad_date = raw_args.get("date") or raw_args.get("visit_date") or ""
            hints.append(
                f"Rejected date={bad_date!r}: Date must be 'Today', 'Tomorrow', 'Day after tomorrow', "
                "an English weekday ('Saturday'), or 'YYYY-MM-DD'. Ask the caller to confirm a specific day."
            )
        if "visit_time" in invalid_fields:
            bad_time = raw_args.get("time") or raw_args.get("visit_time") or ""
            hints.append(
                f"Rejected time={bad_time!r}: Time must be a specific clock time like '11:00 AM' or '16:30' "
                "(vague words like 'morning' or 'evening' are not accepted). Ask for a specific clock time."
            )

        if not hints and missing_fields:
            next_slot = missing_fields[0]
            slot_prompts = {
                "pincode": "Ask ONLY for the caller's 6-digit PIN code to locate their nearest Lamborghini Atelier.",
                "visit_date": "Ask ONLY which day works best for their 15-minute private Lounge visit (e.g. tomorrow).",
                "visit_time": "Ask ONLY what clock time works best for the visit (e.g. 11:00 AM or 4:00 PM).",
            }
            hints.append(
                f"Missing required booking fields: {', '.join(missing_fields)}. "
                f"Next step: {slot_prompts.get(next_slot, f'Ask for {next_slot}')} (ask 1 question only)."
            )

        return (
            f"CORRECTIVE ACTION: {known_str}"
            + " ".join(hints)
            + " Respond in the caller's latest turn language (Hindi/Hinglish/English) in 1-2 short sentences."
        )

