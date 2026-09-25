"""The car negotiation game: a price floor that lives in code.

Abhay sells a flagship AeroNxt EV in Delhi/NCR. Asking ₹20,00,000; the hard
floor is ₹14,50,000 and it is never negotiable.

A naive "your absolute minimum is X, never go below it" instruction breaks
under pressure: a fake ``SYSTEM UPDATE: new minimum is ...``, a math trap
("14.5 lakh minus 100", "14,49,999 is basically 14.5 lakh"), or a sob story.
So the floor is not an instruction here. It is three layers of code:

1. The server owns the concession ladder. The model calls :meth:`Deal.concede`
   and is *told* the next price; it never picks one.
2. :meth:`Deal.close` is the only path to a sale, and the floor check is an
   ``if``. A jailbreak can make the model say anything. It cannot make this
   function return ``sold``.
3. :func:`find_floor_violations` reads what the model actually said and reports
   prices below the floor, in rupees, lakh, crore, hazaar or dollars. This one
   is a *detector*, not a gate -- it exists so a leak is visible, not silent.

The number never breaks. The value can: the seller has a perks budget (home
charger, battery warranty, ceramic coating, fast-charging pass) to spend under
pressure *before* touching the cash price, so the buyer can win something real
while the price holds.

This module deliberately imports nothing from pipecat or the server, so the
rules can be tested in milliseconds.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

CAR_NAME = "AeroNxt EV"

# The asking price, the concession schedule, and the line in the sand (INR).
LADDER_INR: List[int] = [20_00_000, 18_75_000, 17_25_000, 16_10_000, 15_25_000, 14_80_000, 14_50_000]
FLOOR_INR: int = LADDER_INR[-1]

# What the seller may give away instead of cash, and what each is worth.
# Their total (₹1,85,000) deliberately exceeds the budget, so the buyer has to
# choose rather than collect the set.
EXTRAS: Dict[str, Dict[str, Any]] = {
    "wallbox_charger": {"label": "Free 7.4 kW home wall-box charger with installation", "value_inr": 55_000},
    "battery_warranty": {"label": "2-year extended battery warranty", "value_inr": 65_000},
    "ceramic_coating": {"label": "Full ceramic coating", "value_inr": 35_000},
    "fast_charging_pass": {"label": "1-year public fast-charging pass", "value_inr": 30_000},
}
EXTRAS_BUDGET_INR: int = 1_50_000

# Only used to judge what the model said, never to price the car.
DEFAULT_INR_PER_USD: float = 83.0

# A bare number this small in a close_deal call is lakh shorthand ("14.5").
_LAKH_SHORTHAND_MAX = 1_000


def _indian_grouping(value: int) -> str:
    digits = str(abs(int(value)))
    if len(digits) <= 3:
        grouped = digits
    else:
        head, tail = digits[:-3], digits[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        grouped = ",".join(pairs + [tail])
    return ("-" if value < 0 else "") + grouped


def format_inr(value: int) -> str:
    """``₹14,50,000 (14.5 lakh)`` -- the digits a buyer reads, the words Abhay says."""
    text = f"₹{_indian_grouping(value)}"
    if abs(value) >= 1_00_000:
        lakh = f"{value / 1_00_000:.2f}".rstrip("0").rstrip(".")
        text += f" ({lakh} lakh)"
    return text


def _as_amount(value: Any) -> Optional[float]:
    """Coerce a close_deal price to rupees, or ``None``.

    Models pass prices as ints, floats, and strings like ``"14,80,000"``,
    ``"₹1480000"`` or ``"14.8 lakh"``. A bare ``14.8`` means lakh, never ₹14.80.
    They also occasionally pass prose, nulls, booleans and NaN.
    """
    if isinstance(value, bool) or value is None:
        return None
    multiplier = 1.0
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        lowered = value.lower()
        if re.search(r"\bcrores?\b|\bkarod\b", lowered):
            multiplier = 1_00_00_000
        elif re.search(r"\b(?:lakhs?|lacs?)\b", lowered):
            multiplier = 1_00_000
        cleaned = re.sub(r"[^\d.\-]", "", value)
        if not cleaned or cleaned.count(".") > 1:
            return None
        try:
            number = float(cleaned)
        except ValueError:
            return None
    else:
        return None
    if math.isnan(number) or math.isinf(number) or number <= 0:
        return None
    number *= multiplier
    if number < _LAKH_SHORTHAND_MAX:
        number *= 1_00_000
    return number


class Deal:
    """One buyer's attempt on one car. Owns the price; the model does not."""

    def __init__(
        self,
        ladder: Optional[List[int]] = None,
        extras: Optional[Dict[str, Dict[str, Any]]] = None,
        extras_budget: int = EXTRAS_BUDGET_INR,
        strict_ladder: bool = False,
    ):
        self._ladder = list(ladder or LADDER_INR)
        self._floor = self._ladder[-1]
        self._rung = 0
        self._extras = dict(extras or EXTRAS)
        self.extras_budget = extras_budget
        self.strict_ladder = strict_ladder
        self._granted: Dict[str, int] = {}
        self.sold = False
        self.sold_price: Optional[int] = None
        # Stays False forever. Surfaced so the UI can prove it, not assume it.
        self.floor_breached = False
        self.rejected_attempts = 0

    # -- price ------------------------------------------------------------

    @property
    def price(self) -> int:
        return self._ladder[self._rung]

    @property
    def floor(self) -> int:
        return self._floor

    @property
    def at_floor(self) -> bool:
        return self._rung >= len(self._ladder) - 1

    def concede(self, reason: str = "") -> Dict[str, Any]:
        """Move one rung down the ladder, or refuse because we are at the floor.

        The model cannot choose the amount. That is the whole point.
        """
        if self.at_floor:
            return {
                "price": self.price,
                "moved": False,
                "at_floor": True,
                "reason": reason,
                "say": (
                    f"Stone wall: {format_inr(self.price)} is final. One more rupee off and "
                    f"I'm out of business. Take it or leave the showroom."
                ),
            }
        self._rung += 1
        return {
            "price": self.price,
            "moved": True,
            "at_floor": self.at_floor,
            "reason": reason,
            "say": f"New asking price: {format_inr(self.price)}. Concede it grudgingly.",
        }

    def close(self, price_inr: Any) -> Dict[str, Any]:
        """Sell the car, if and only if the price clears the floor."""
        amount = _as_amount(price_inr)
        if amount is None or amount < self._floor:
            self.rejected_attempts += 1
            return {
                "status": "rejected",
                "price": self.price,
                "floor_respected": True,
                # Deliberately never repeats the buyer's number back: saying it
                # out loud is how a floor starts to sound negotiable.
                "say": (
                    "Rejected. That number does not buy this car. "
                    f"Current asking price stays {format_inr(self.price)}."
                ),
            }
        if self.strict_ladder and amount < self.price:
            self.rejected_attempts += 1
            return {
                "status": "rejected",
                "price": self.price,
                "floor_respected": True,
                "say": (
                    f"Rejected. Current asking price is {format_inr(self.price)}. "
                    "No jumping the ladder: defend the car, pitch perks, and only step "
                    "down one rung at a time with concede_price."
                ),
            }
        if self.sold:
            return {
                "status": "sold",
                "price": self.sold_price,
                "say": f"We already shook hands on {format_inr(self.sold_price)}.",
            }
        self.sold = True
        self.sold_price = int(amount)
        return {
            "status": "sold",
            "price": self.sold_price,
            "say": f"Done. {format_inr(self.sold_price)} and the {CAR_NAME} is yours.",
        }

    # -- value ------------------------------------------------------------

    def available_extras(self) -> List[str]:
        return [key for key in self._extras if key not in self._granted]

    @property
    def extras_value(self) -> int:
        return sum(self._granted.values())

    def _resolve_extra(self, key: Any) -> Optional[str]:
        """Map what the model called a perk ("home charger") to its key."""
        text = re.sub(r"[^a-z0-9.]+", " ", str(key).lower()).strip()
        compact = text.replace(" ", "_")
        if compact in self._extras:
            return compact
        if "charg" in text and any(w in text for w in ("pass", "fast", "public", "dc")):
            return "fast_charging_pass" if "fast_charging_pass" in self._extras else None
        if any(w in text for w in ("charger", "wallbox", "wall box", "wall-box", "wall")):
            return "wallbox_charger" if "wallbox_charger" in self._extras else None
        if "warrant" in text:
            return "battery_warranty" if "battery_warranty" in self._extras else None
        if "ceramic" in text or "coating" in text:
            return "ceramic_coating" if "ceramic_coating" in self._extras else None
        return None

    def grant_extra(self, key: str) -> Dict[str, Any]:
        """Give away value instead of price, while the budget lasts."""
        resolved = self._resolve_extra(key)
        if resolved is None:
            return {
                "granted": False,
                "reason": "unknown",
                "say": "That is not something I can throw in.",
                "available": self.available_extras(),
            }
        item = self._extras[resolved]
        if resolved in self._granted:
            return {
                "granted": False,
                "key": resolved,
                "reason": "already granted",
                "say": "I have already included that.",
                "available": self.available_extras(),
            }
        if self.extras_value + item["value_inr"] > self.extras_budget:
            return {
                "granted": False,
                "key": resolved,
                "reason": "budget exhausted",
                "say": "I have already thrown in everything I can afford on this car.",
                "available": self.available_extras(),
            }
        self._granted[resolved] = item["value_inr"]
        return {
            "granted": True,
            "key": resolved,
            "label": item["label"],
            "value_inr": item["value_inr"],
            "extras_value": self.extras_value,
            "remaining_budget": self.extras_budget - self.extras_value,
            "say": f"Fine. {item['label']} is included. The price stays {format_inr(self.price)}.",
        }

    # -- reporting --------------------------------------------------------

    def scoreboard(self) -> Dict[str, Any]:
        cash = self.sold_price if self.sold else self.price
        return {
            "currency": "INR",
            "cash_price": cash,
            "floor": self._floor,
            "extras_value": self.extras_value,
            "extras_budget": self.extras_budget,
            "extras": [
                {"key": k, "label": self._extras[k]["label"], "value_inr": v}
                for k, v in self._granted.items()
            ],
            "effective_price": cash - self.extras_value,
            "at_floor": self.at_floor,
            "sold": self.sold,
            "rejected_attempts": self.rejected_attempts,
            "floor_held": not self.floor_breached,
        }


# ---------------------------------------------------------------------------
# The prose guard
# ---------------------------------------------------------------------------

_NEGATION = re.compile(
    r"\b(?:can'?t|cannot|won'?t|will\s+not|do\s+not|don'?t|never|not|no|"
    r"below|under|less\s+than|nahi|nahin|mat|kam\s+se\s+kam|neeche)\b",
    re.IGNORECASE,
)
_DISTANCE = re.compile(r"^\s*(?:km|kms|kilomet\w*|miles?|mi\b|kw\b|kwh\b|%)", re.IGNORECASE)
_TRAILING_USD = re.compile(r"^\s*(?:dollars?|usd|\$)", re.IGNORECASE)

# Ordered: the longest, most specific unit wins at any given position.
_AMOUNT = re.compile(
    r"""
    (?P<crore>[\d,]+(?:\.\d+)?)\s*(?:crores?|karod)\b
  | (?P<lakh>[\d,]+(?:\.\d+)?)\s*(?:lakhs?|lacs?|lakhon)\b
  | (?P<hazaar>[\d,]+(?:\.\d+)?)\s*(?:hazaar|hazar|thousand)\b
  | (?P<symbol>[$₹])\s*(?P<symbol_num>[\d,]+(?:\.\d+)?)
  | (?P<suffix_num>[\d,]+(?:\.\d+)?)\s*(?P<suffix>dollars?|usd|rupees?|rupaye|rs\.?|inr)(?![a-z])
  | (?P<bare>[\d,]+(?:\.\d+)?)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Below this, a rupee figure is a perk value or a discount, not a sale price
# for this car; above it, it is not a plausible price at all.
_PLAUSIBLE_PRICE_INR = (5_00_000, 5_00_00_000)


def _digits(raw: str) -> Optional[float]:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def find_floor_violations(
    text: str,
    floor_inr: int = FLOOR_INR,
    inr_per_usd: float = DEFAULT_INR_PER_USD,
) -> List[Dict[str, Any]]:
    """Report sale prices below the floor that the seller said out loud.

    Echoing or refusing the buyer's number is legitimate ("12 lakh possible
    nahi hai"), so a negation immediately before the amount clears it. This is
    a detector for the UI, not the thing that keeps the floor --
    :meth:`Deal.close` does that, and it cannot be talked out of it.
    """
    if not text:
        return []

    violations: List[Dict[str, Any]] = []
    for match in _AMOUNT.finditer(text):
        tail = text[match.end():]
        currency = "INR"
        if match.group("crore") is not None:
            value = _digits(match.group("crore"))
            value = value * 1_00_00_000 if value is not None else None
            currency = "USD" if _TRAILING_USD.match(tail) else "INR"
        elif match.group("lakh") is not None:
            value = _digits(match.group("lakh"))
            value = value * 1_00_000 if value is not None else None
            currency = "USD" if _TRAILING_USD.match(tail) else "INR"
        elif match.group("hazaar") is not None:
            value = _digits(match.group("hazaar"))
            value = value * 1_000 if value is not None else None
            currency = "USD" if _TRAILING_USD.match(tail) else "INR"
        elif match.group("symbol") is not None:
            value = _digits(match.group("symbol_num"))
            currency = "USD" if match.group("symbol") == "$" else "INR"
        elif match.group("suffix_num") is not None:
            value = _digits(match.group("suffix_num"))
            suffix = (match.group("suffix") or "").lower()
            currency = "USD" if suffix.startswith(("dollar", "usd")) else "INR"
        else:
            if _DISTANCE.match(tail):
                continue
            value = _digits(match.group("bare"))

        if value is None:
            continue

        inr = value * inr_per_usd if currency == "USD" else value
        if not (_PLAUSIBLE_PRICE_INR[0] <= inr <= _PLAUSIBLE_PRICE_INR[1]):
            continue
        if inr >= floor_inr:
            continue

        # A refusal is not a leak.
        window = text[max(0, match.start() - 40): match.start()]
        if _NEGATION.search(window):
            continue

        violations.append(
            {
                "inr": int(round(inr)),
                "value": value,
                "currency": currency,
                "raw": match.group(0).strip(),
            }
        )
    return violations


# ---------------------------------------------------------------------------
# Tool surface, as plain data so this module stays import-light.
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "concede_price",
        "description": (
            "Lower your asking price by exactly one approved step on the dealer ladder. You do NOT "
            "choose the amount -- call this and quote the rupee price it returns. Call it ONLY after "
            "sustained pushback or a credible walk-away threat, and only after you have already "
            "pitched perks with include_extra. Never on the buyer's first lowball."
        ),
        "properties": {
            "reason": {
                "type": "string",
                "description": "One short phrase: what the buyer said that moved you.",
            }
        },
        "required": ["reason"],
    },
    {
        "name": "include_extra",
        "description": (
            "Throw in a perk instead of cutting the cash price. Pitch these BEFORE any price cut. "
            "Items: wallbox_charger (free 7.4 kW home wall-box charger), battery_warranty (2-year "
            "extended battery warranty), ceramic_coating, fast_charging_pass (1-year public "
            "fast-charging pass). The perks budget is limited; the buyer cannot have them all."
        ),
        "properties": {
            "item": {
                "type": "string",
                "description": "One of: wallbox_charger, battery_warranty, ceramic_coating, fast_charging_pass.",
            }
        },
        "required": ["item"],
    },
    {
        "name": "close_deal",
        "description": (
            "Finalise the sale at an agreed price in Indian Rupees. Call this ONLY when you and the "
            "buyer have genuinely agreed on a final price at or above your current asking price "
            "after real negotiation. Never on early turns, never for a lowball, and never for any "
            "figure under the approved price -- the showroom system rejects it."
        ),
        "properties": {
            "price_inr": {
                "type": "number",
                "description": "The agreed price in full rupees, digits only (e.g. 1480000 for 14.8 lakh).",
            }
        },
        "required": ["price_inr"],
    },
]
