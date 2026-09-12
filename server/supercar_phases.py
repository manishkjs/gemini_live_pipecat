"""Deterministic, zero-token phase tracking for Pragya's outbound call.

Why this module exists
----------------------
The UI's SOP tracker used to advance only when the model chose to call
``get_phase_card``. That coupled a *display* concern to a *tool* the model paid
for on every turn, and it failed in the obvious way: the caller said their PIN
code, the model booked correctly, and the tracker still showed Phase 1 because
no tool had been invoked to announce the move.

Phase tracking is therefore derived here, on the server, from what the caller
actually said. It costs zero tokens, zero tools and zero model latency: a
regex pass over a transcript that already exists.

Invariants
----------
* **Current topic.** The highlight follows the caller back to cars or onward
  to a visit. Collected slots and the furthest milestone are retained separately.
* **Evidence-based.** Phase 4 is reached only by an executed booking, never by
  the caller merely agreeing. The tracker must not be able to claim a booking
  the backend never made.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


SOP_01_OPENING = "SOP_01_OPENING"
SOP_02_DISCOVERY = "SOP_02_DISCOVERY"
SOP_03_PINCODE = "SOP_03_PINCODE"
SOP_04_BOOKED = "SOP_04_BOOKED"


@dataclass(frozen=True)
class PhaseDefinition:
    phase_id: str
    index: int
    title: str


PRAGYA_PHASES: List[PhaseDefinition] = [
    PhaseDefinition(SOP_01_OPENING, 0, "Outbound intent validation"),
    PhaseDefinition(SOP_02_DISCOVERY, 1, "Supercar preview"),
    PhaseDefinition(SOP_03_PINCODE, 2, "PIN code & lounge matching"),
    PhaseDefinition(SOP_04_BOOKED, 3, "VIP appointment locked"),
]

_PHASE_INDEX = {p.phase_id: p.index for p in PRAGYA_PHASES}
_PHASE_TITLE = {p.phase_id: p.title for p in PRAGYA_PHASES}


# A bare six-digit run is the strongest possible signal, but speech-to-text
# frequently spaces the digits out ("1 1 0 0 3 7") or hyphenates them, so the
# text is normalised before matching rather than the pattern being loosened.
_PINCODE_RE = re.compile(r"\b\d{6}\b")

# Callers speak Hindi and Chirp returns Devanagari, so every keyword list must
# carry both scripts. Devanagari has no \b word boundary that Python's `re`
# recognises against Latin \w, so the Devanagari alternatives are matched
# without boundaries -- safe here because these are long, distinctive strings.
_CITY_RE = re.compile(
    r"\b(delhi|new delhi|dilli|aerocity|gurgaon|gurugram|noida|"
    r"mumbai|bombay|bkc|bandra|thane|"
    r"bengaluru|bangalore|lavelle|koramangala|indiranagar)\b"
    r"|(दिल्ली|दिल्लि|एरोसिटी|गुड़गांव|गुरुग्राम|नोएडा|"
    r"मुंबई|मुम्बई|बंबई|बांद्रा|ठाणे|"
    r"बेंगलुरु|बेंगलूरु|बैंगलोर|बंगलौर|कोरमंगला|इंदिरानगर)"
)

# "pin code", "pincode", "पिन कोड", "area code", "postal code".
_PIN_WORD_RE = re.compile(
    r"(pin\s*-?\s*code|pincode|pin\s+kod|postal\s+code|area\s+code"
    r"|पिन\s*कोड|पिनकोड|पिन|डाक\s*कोड|क्षेत्र\s*कोड)"
)

# Asking to book *is* stage 3. Stage 3 means "organise the visit", so it is
# where missing prerequisites get collected -- there is no reason to march a
# caller who already said "book me in" back through the product pitch. This is
# checked before the discovery pattern below, which also contains "booking" and
# "test drive": furthest signal wins.
_BOOKING_INTENT_RE = re.compile(
    r"\b(book|books|booked|booking|appointment|appointments|schedule|slot|"
    r"reserve|test\s*drives?|showroom\s*visits?|visits?|come\s*over|"
    r"aa\s*jaunga|aa\s*jaaunga|aunga)\b"
    r"|(बुक|बुकिंग|अपॉइंटमेंट|अपाइंटमेंट|अपॉइंट|टेस्ट\s*ड्राइव|"
    r"विजिट|विज़िट|आ\s*जाऊंगा|आ\s*जाऊँगा|आना\s*चाह|मिलने\s*आ|"
    r"समय\s*तय|स्लॉट)"
)

# `s?` suffixes matter: the original list had "car" but not "cars", so the most
# obvious discovery question in English -- "which cars do you have" -- did not
# match. Anchor plurals rather than enumerating them.
_DISCOVERY_RE = re.compile(
    r"\b(revuelto|urus|temerario|huracan|huracán|aventador|gallardo|lamborghini|lambo|"
    r"supercars?|super\s*cars?|models?|variants?|engines?|v12|v10|v8|hybrids?|specs?|"
    r"specifications?|prices?|pricing|costs?|kitne|kitna|kitni|crore|showrooms?|lounges?|"
    r"test\s*drives?|visits?|dekhna|dekhni|dekhiye|dekh|dikhao|gaadi|gaadiyan|gadi|cars?|"
    r"electric|petrol|colour|color|booking|interested)\b"
    r"|(गाड़ी|गाडी|गाड़ियां|कार|कारें|कारों|मॉडल|मोडल|वेरिएंट|वैरिएंट|"
    r"सुपरकार|लेम्बोर्गिनी|लंबोर्गिनी|इंजन|हाइब्रिड|इलेक्ट्रिक|पेट्रोल|"
    r"कीमत|दाम|प्राइस|कितने|कितना|कितनी|करोड़|शोरूम|लाउंज|"
    r"टेस्ट\s*ड्राइव|दिखाओ|दिखाइए|देखना|देखनी|देखने|रंग|बुकिंग)"
)

# Refusal beats the booking keyword it contains. Evaluate bounded clauses so
# a later positive request can still change the topic. Ambiguous speech keeps
# the current topic; these rules do not claim to understand every paraphrase.
_REFUSAL_RE = re.compile(
    r"\b(don['’]?t|do\s+not|not\s+(?:now|ready|interested)|no\s+(?:thanks|booking|visit)|"
    r"stop|cancel|nahi|nahin|mat)\b|नहीं|नही|मत\s|रद्द"
)
_OPENING_ACCEPT_RE = re.compile(
    r"^(yes|yeah|yep|sure|okay|ok|go\s+ahead|haan|han|ha)\b"
    r"|^(जी|हाँ|हां|बोलिए|बताइए|बताओ)|\b(two minutes|do minute|bataiye|boliye)\b"
)
_AFTERCARE_RE = re.compile(
    r"\b(confirmation|reference|booking\s*(id|number)|address|parking|"
    r"thank\s*you|thanks|goodbye|bye)\b|पुष्टि|रेफरेंस|पता|पार्किंग|धन्यवाद"
)
_VISIT_CHANGE_RE = re.compile(
    r"\b(reschedule|cancel|change\s+(?:my\s+|the\s+)?(?:booking|appointment|day|time|date))\b"
    r"|रद्द|समय\s*बदल|दिन\s*बदल"
)
_CLAUSE_BREAK_RE = re.compile(
    r"[.!?;,]+|\b(?:but|however|actually|instead|lekin)\b|लेकिन|मगर"
)

# Spoken digits, English and Hindi, so "one one zero zero three seven" and
# "एक एक शून्य शून्य तीन सात" both normalise to a matchable pincode.
_SPOKEN_DIGITS = {
    "zero": "0", "oh": "0", "o": "0", "shunya": "0", "शून्य": "0",
    "one": "1", "ek": "1", "एक": "1",
    "two": "2", "do": "2", "दो": "2",
    "three": "3", "teen": "3", "तीन": "3",
    "four": "4", "char": "4", "चार": "4",
    "five": "5", "paanch": "5", "panch": "5", "पांच": "5", "पाँच": "5",
    "six": "6", "chhe": "6", "che": "6", "छह": "6",
    "seven": "7", "saat": "7", "सात": "7",
    "eight": "8", "aath": "8", "आठ": "8",
    "nine": "9", "nau": "9", "नौ": "9",
}


# Chirp returns Devanagari numerals for spoken digits in Hindi sessions.
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize_for_pincode(text: str) -> str:
    """Collapse spoken or spaced-out digits into contiguous numerals.

    ``"1 1 0 0 3 7"``, ``"one one zero zero three seven"`` and ``"110-037"``
    all become ``"110037"`` so a single strict six-digit pattern can match all
    three. Loosening the pattern instead would match phone numbers and prices.
    """
    lowered = (text or "").lower().translate(_DEVANAGARI_DIGITS)
    tokens = re.split(r"[\s,\-\.]+", lowered)
    out: List[str] = []
    for token in tokens:
        out.append(_SPOKEN_DIGITS.get(token, token))
    joined = " ".join(out)
    # Glue runs of single digits: "1 1 0 0 3 7" -> "110037".
    return re.sub(r"(?<=\d)\s+(?=\d)", "", joined)


def detect_phase(text: str) -> Optional[str]:
    """Identify the latest explicit topic; leave ambiguous speech unchanged."""
    if not text or not text.strip():
        return None

    lowered = (text or "").lower().translate(_DEVANAGARI_DIGITS)
    topic = None
    for clause in _CLAUSE_BREAK_RE.split(lowered):
        booking = _BOOKING_INTENT_RE.search(clause)
        pin = _PIN_WORD_RE.search(clause) or _PINCODE_RE.search(normalize_for_pincode(clause))
        if _REFUSAL_RE.search(clause) and (booking or pin):
            topic = SOP_02_DISCOVERY
        elif pin or booking:
            topic = SOP_03_PINCODE
        elif _DISCOVERY_RE.search(clause):
            topic = SOP_02_DISCOVERY
        # A city alone is context, not consent to organise a visit.
    return topic


class PragyaPhaseTracker:
    """Current topic, retained milestones, and booking evidence for one call.

    Deliberately holds no reference to the LLM, the transport or the event bus:
    it answers "did this utterance move the call forward, and to where", and
    the caller decides what to do with the answer. That keeps it trivially
    testable without a live session.
    """

    def __init__(self) -> None:
        self.current_phase: str = SOP_01_OPENING
        self.furthest_phase: str = SOP_01_OPENING
        self.booking_confirmed = False

    @property
    def current_index(self) -> int:
        return _PHASE_INDEX[self.current_phase]

    def title_of(self, phase_id: str) -> str:
        return _PHASE_TITLE.get(phase_id, phase_id)

    def _advance_to(self, phase_id: str) -> Optional[str]:
        """Select a topic without erasing a previously reached milestone."""
        target = _PHASE_INDEX.get(phase_id)
        if target is None or phase_id == self.current_phase:
            return None
        self.current_phase = phase_id
        if target > _PHASE_INDEX[self.furthest_phase]:
            self.furthest_phase = phase_id
        return phase_id

    def observe_user_text(self, text: str) -> Optional[str]:
        """Select on caller speech. Ambiguous acknowledgements retain the topic."""
        detected = detect_phase(text)
        lowered = (text or "").strip().lower()
        if self.booking_confirmed:
            if _VISIT_CHANGE_RE.search(lowered):
                detected = SOP_03_PINCODE
            elif _AFTERCARE_RE.search(lowered) and detected != SOP_02_DISCOVERY:
                detected = SOP_04_BOOKED
        if (
            detected is None and self.current_phase == SOP_01_OPENING
            and _OPENING_ACCEPT_RE.search(lowered) and not _REFUSAL_RE.search(lowered)
        ):
            detected = SOP_02_DISCOVERY
        if detected is None:
            return None
        return self._advance_to(detected)

    def observe_booking_confirmed(self) -> Optional[str]:
        """A booking actually executed: the only route into the final phase."""
        self.booking_confirmed = True
        return self._advance_to(SOP_04_BOOKED)

    def observe_booking_request(self) -> Optional[str]:
        """The caller (or a premature tool call) asked to organise the visit.

        Stage 3 is *where prerequisites get collected*, not a reward for having
        sat through the pitch. A booking attempt that is missing a pincode is
        the clearest possible evidence that the call is in stage 3, so it moves
        there rather than being discarded.
        """
        return self._advance_to(SOP_03_PINCODE)


# ---------------------------------------------------------------------------
# Structured call state
# ---------------------------------------------------------------------------
# Conversation history is too fragile to carry booking prerequisites. A live
# call proved it: the model read "pincode 560048" and immediately booked with
# ``date='Next week'`` (never said by the caller) and ``time=''``, and the tool
# wrote both down as fact and returned "Schedule: Next week at ."
#
# Two rules prevent the whole class of failure:
#
# 1. **Ownership.** Each field has exactly one legitimate writer. The model may
#    *propose* what it heard; only the server may name a lounge, and only the
#    booking tool may declare a booking confirmed.
# 2. **Validation on write.** A proposed value that does not resolve to a real
#    day or a real clock time is rejected at the door rather than stored and
#    believed. Blanks never overwrite a captured value, so a partial tool call
#    accumulates state instead of erasing it.


#: Accepts a concrete day. "Next week" and "soon" are deliberately excluded:
#: they are the vague values that produced a phantom booking.
_DAY_RE = re.compile(
    r"\b(today|tomorrow|tmrw|day\s*after\s*tomorrow|"
    r"mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thursday|"
    r"fri|friday|sat|saturday|sun|sunday|aaj|kal|parso|parson)\b"
    r"|(आज|कल|परसों|परसो|सोमवार|मंगलवार|बुधवार|गुरुवार|बृहस्पतिवार|"
    r"शुक्रवार|शनिवार|रविवार|इतवार)"
    r"|\b(0?[1-9]|[12]\d|3[01])\s*(?:st|nd|rd|th)?\s*"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"|\b(0?[1-9]|[12]\d|3[01])\s*[/-]\s*(0?[1-9]|1[0-2])\b"
)

#: Accepts a clock time. A bare "morning" is not a slot you can hold a car for.
_CLOCK_RE = re.compile(
    r"\b([01]?\d|2[0-3])\s*[:.]\s*([0-5]\d)\b"
    r"|\b([01]?\d|2[0-3])\s*(?:am|pm|a\.m\.?|p\.m\.?)\b"
    r"|\b([01]?\d|2[0-3])\s*(?:o'?\s*clock)\b"
    r"|\b([01]?\d|2[0-3])\s*(?:baje|बजे)"
)


def _spoken_to_digits(text: str) -> str:
    """Spoken numbers to numerals, without gluing neighbours together.

    ``normalize_for_pincode`` deliberately glues digit runs so "5 6 0 0 4 8"
    becomes a pincode. That is exactly wrong for a time: it would turn
    "5 30" into "530". Times need the substitution but not the glue.
    """
    lowered = (text or "").lower().translate(_DEVANAGARI_DIGITS)
    return " ".join(_SPOKEN_DIGITS.get(t, t) for t in re.split(r"[\s,]+", lowered))


def resolves_to_a_day(text: str) -> bool:
    """Whether this names a day a showroom could actually hold open."""
    return bool(text and _DAY_RE.search(_spoken_to_digits(text)))


def resolves_to_a_time(text: str) -> bool:
    """Whether this names a time a showroom could actually hold open."""
    return bool(text and _CLOCK_RE.search(_spoken_to_digits(text)))


#: The caller never chose a car. Different from having chosen not to choose.
CAR_NOT_DISCUSSED = None
#: The caller explicitly wants to decide at the lounge, or to see the range.
CAR_UNDECIDED = "undecided"


class CallSlots:
    """Server-authoritative key/value state for one call.

    The model proposes, the server disposes. ``propose`` silently drops values
    it cannot verify, so a hallucinated date leaves the slot empty and the
    booking gate keeps asking for it — which is the behaviour we want.
    """

    #: Fields the model may write, because only it can hear them.
    MODEL_PROPOSED = frozenset(
        {"intent", "pincode", "city", "car_choice", "visit_date", "visit_time",
         "plan_read_back"}
    )
    #: Fields only the server may write. A lounge comes from a lookup, never
    #: from a sentence.
    SERVER_DERIVED = frozenset({"lounge_id", "lounge_name"})
    #: Fields only the booking tool may write.
    TOOL_OWNED = frozenset({"booking_status", "booking_ref"})

    #: Changing the key on the left invalidates the fields on the right.
    #: A new pincode means the lounge we matched is no longer theirs, and any
    #: plan they agreed to was a plan about somewhere else.
    INVALIDATES: Dict[str, tuple] = {
        "pincode": ("lounge_id", "lounge_name", "plan_read_back"),
        "lounge_id": ("plan_read_back",),
        "visit_date": ("plan_read_back",),
        "visit_time": ("plan_read_back",),
    }

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
        """Merge model-heard values. Returns the keys that actually changed.

        Unverifiable and blank values are dropped rather than stored: the cost
        of ignoring a real answer is one extra question, the cost of believing
        an invented one is a phantom appointment.
        """
        changed: List[str] = []
        for key, raw in candidates.items():
            if key not in self.MODEL_PROPOSED:
                continue
            value = self._clean(key, raw)
            if value is None:
                continue
            if self._values.get(key) == value:
                continue
            self._values[key] = value
            changed.append(key)
            self._invalidate(key)
        return changed

    def set_server(self, **values: Any) -> List[str]:
        """Write a server-derived field, e.g. the matched lounge."""
        return self._trusted_write(self.SERVER_DERIVED, values)

    def set_tool(self, **values: Any) -> List[str]:
        """Write a tool-owned field, e.g. the confirmed booking reference."""
        return self._trusted_write(self.TOOL_OWNED, values)

    def observe_user_text(self, text: str) -> List[str]:
        """Capture what the transcript alone can prove. Costs nothing.

        Only the pincode is taken this way: it is the one field with a shape
        strict enough that a regex cannot be wrong about it.
        """
        if not text:
            return []
        match = _PINCODE_RE.search(normalize_for_pincode(text))
        if not match:
            return []
        return self.propose(pincode=match.group(0))

    # -- internals ----------------------------------------------------------

    def _trusted_write(self, allowed: frozenset, values: Dict[str, Any]) -> List[str]:
        changed: List[str] = []
        for key, value in values.items():
            if key not in allowed or self._values.get(key) == value:
                continue
            self._values[key] = value
            changed.append(key)
            self._invalidate(key)
        return changed

    def _invalidate(self, key: str) -> None:
        for dependent in self.INVALIDATES.get(key, ()):
            self._values.pop(dependent, None)

    @staticmethod
    def _clean(key: str, raw: Any) -> Any:
        """Normalise and verify one proposed value, or None to reject it."""
        if raw is None:
            return None
        if key == "plan_read_back":
            return bool(raw) or None

        text = str(raw).strip()
        if not text:
            return None

        if key == "pincode":
            match = _PINCODE_RE.search(normalize_for_pincode(text))
            # A city is not a pincode. It is a useful hint, and it is stored
            # under `city`, but it will not satisfy the booking gate.
            return match.group(0) if match else None
        if key == "visit_date":
            return text if resolves_to_a_day(text) else None
        if key == "visit_time":
            return text if resolves_to_a_time(text) else None
        return text
