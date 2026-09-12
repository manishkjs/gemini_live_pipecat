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
* **Monotonic.** A sales funnel only moves forward. A caller circling back to
  models after giving a PIN code has not un-given the PIN code, and a tracker
  that rewinds reads as a bug to anyone watching the demo.
* **Evidence-based.** Phase 4 is reached only by an executed booking, never by
  the caller merely agreeing. The tracker must not be able to claim a booking
  the backend never made.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


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
    """The furthest phase the caller's own words justify, or None.

    Returns ``None`` rather than ``SOP_01_OPENING`` for unremarkable speech:
    "no evidence of a move" and "evidence of being in phase 1" are different
    claims, and conflating them would re-announce phase 1 on every turn.
    """
    if not text or not text.strip():
        return None

    normalized = normalize_for_pincode(text)
    lowered = (text or "").lower().translate(_DEVANAGARI_DIGITS)

    if _PINCODE_RE.search(normalized) or _CITY_RE.search(lowered) or _PIN_WORD_RE.search(lowered):
        return SOP_03_PINCODE

    if _DISCOVERY_RE.search(lowered):
        return SOP_02_DISCOVERY

    return None


class PragyaPhaseTracker:
    """Monotonic funnel position for one call.

    Deliberately holds no reference to the LLM, the transport or the event bus:
    it answers "did this utterance move the call forward, and to where", and
    the caller decides what to do with the answer. That keeps it trivially
    testable without a live session.
    """

    def __init__(self) -> None:
        self.current_phase: str = SOP_01_OPENING

    @property
    def current_index(self) -> int:
        return _PHASE_INDEX[self.current_phase]

    def title_of(self, phase_id: str) -> str:
        return _PHASE_TITLE.get(phase_id, phase_id)

    def _advance_to(self, phase_id: str) -> Optional[str]:
        """Move forward to ``phase_id``; return it only if this was a change."""
        target = _PHASE_INDEX.get(phase_id)
        if target is None or target <= self.current_index:
            return None
        self.current_phase = phase_id
        return phase_id

    def observe_user_text(self, text: str) -> Optional[str]:
        """Advance on caller speech. Returns the new phase, or None if unmoved."""
        detected = detect_phase(text)
        if detected is None:
            return None
        return self._advance_to(detected)

    def observe_booking_confirmed(self) -> Optional[str]:
        """A booking actually executed: the only route into the final phase."""
        return self._advance_to(SOP_04_BOOKED)
