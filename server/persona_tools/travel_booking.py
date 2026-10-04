"""Tara (Book My Trip) flight-booking backend: tool declarations, call state and a mock flight service.

This is the server side of the prompt-card contract in ``persona_prompt_cards/tara_cards.py``.
It plays the part ``flights-bot-service`` plays in production, with deterministic mock
inventory so the demo is repeatable:

* The server owns the state (``CallState``). The model is never the source of truth for it.
* Every tool response carries ``call_state`` (one line) and a one-line ``instruction``.
* The response that changes the flow also carries ``prompt_card`` (card + state + footer).
* Workflow rules (round-trip split, refine, ``phone_choice`` mapping, email checks, payment
  gating) live here, not in the declarations. The model follows ``next``.

The declarations below are the six lean tools from the review's Tool Declarations tab,
verbatim. ``TOOL_GROUP_BY_CARD`` lists which of them are live per card when the session can
swap tools mid-call through ``context_update`` (see ``live_tool_swapper.py``).
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import math
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from persona_prompt_cards.tara_cards import (
    AGENT_NAME,
    TARA_CARD_BY_NUMBER,
    STEP_INSTRUCTIONS,
    card_for_step,
    format_tara_prompt_card,
)

# ---------------------------------------------------------------------------
# Tool declarations (verbatim from the review, 2,198 tokens for all six)
# ---------------------------------------------------------------------------

LANGUAGES = [
    "Hindi", "Bhojpuri", "Marathi", "Tamil", "Bengali", "Kannada", "Malayalam", "Telugu",
    "Gujarati", "Punjabi", "Odia", "Assamese", "Urdu", "Konkani", "Sindhi", "Nepali",
    "Kashmiri", "Dogri", "Maithili", "Bodo", "Santhali", "Manipuri", "Sanskrit", "English",
]
_LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]

TOOL_DECLARATIONS: List[Dict[str, Any]] = [
    {
        "name": "SelectLanguageTool",
        "behavior": "BLOCKING",
        "description": "Saves the caller's language for the rest of the call. Call when the caller names a language or clearly asks to switch.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "language": {"type": "STRING", "enum": LANGUAGES, "description": "Language the caller chose."},
            },
            "required": ["language"],
        },
    },
    {
        "name": "CheckAirportTool",
        "behavior": "NON_BLOCKING",
        "description": "Checks whether a place has an airport and returns nearby options. Call before saying a place has or lacks an airport.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"place": {"type": "STRING", "description": "City, town or airport code."}},
            "required": ["place"],
        },
    },
    {
        "name": "SearchTool",
        "behavior": "NON_BLOCKING",
        "description": "Searches domestic flights, or refines the last results. Leave unknown fields empty; the tool asks for them. On a round trip, after the outbound flight is selected, call it with exactly the arguments given in that result's next entry to get the return flights from the same search.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query_sub_type": {
                    "type": "STRING", "enum": ["SPECIFIC_DATE", "DATE_RANGE", "REFINE_RESULTS"],
                    "description": "SPECIFIC_DATE for one day, DATE_RANGE for a fare calendar, REFINE_RESULTS to filter the last results.",
                },
                "origin": {"type": "STRING", "description": "From city or airport code."},
                "destination": {"type": "STRING", "description": "To city or airport code."},
                "trip_type": {"type": "STRING", "enum": ["OW", "RT"], "description": "OW one-way, RT round trip."},
                "depart_date": {"type": "STRING", "description": "Departure date, YYYY-MM-DD."},
                "depart_date_end": {"type": "STRING", "description": "Range end for DATE_RANGE, YYYY-MM-DD."},
                "return_date": {"type": "STRING", "description": "Return date for RT, YYYY-MM-DD."},
                "date_reference": {"type": "STRING", "enum": ["CALENDAR_CHEAPEST"], "description": "Use the cheapest day from the last calendar."},
                "refine_intent": {
                    "type": "STRING",
                    "enum": ["SAME_FARE", "NEXT_FARE", "CHEAPEST_ALTERNATIVES", "FASTEST_ALTERNATIVES", "MORE", "FILTER"],
                    "description": "For REFINE_RESULTS only. FILTER when setting filters; SAME_FARE or NEXT_FARE with a reference field; MORE for more options.",
                },
                "reference_flight_id": {"type": "STRING", "description": "Shown flight id the caller refers to."},
                "reference_fare": {"type": "INTEGER", "description": "Fare in rupees the caller mentioned."},
                "reference_role": {"type": "STRING", "enum": ["CHEAPEST", "FASTEST"], "description": "Reference flight by role."},
                "filters": {
                    "type": "OBJECT",
                    "description": "Filters the caller asked for. Times are HH:MM, 24-hour.",
                    "properties": {
                        "airline": {"type": "STRING", "description": "Airline name or code."},
                        "stops_count": {"type": "INTEGER", "description": "Exact stops; 0 is non-stop."},
                        "connecting": {"type": "BOOLEAN", "description": "True for any flight with a stop. Omit when stops_count is set."},
                        "time_of_day": {"type": "STRING", "enum": ["morning", "noon", "afternoon", "evening", "night"]},
                        "departure_after": {"type": "STRING"},
                        "departure_before": {"type": "STRING"},
                        "arrival_after": {"type": "STRING"},
                        "arrival_before": {"type": "STRING"},
                        "max_fare": {"type": "INTEGER", "description": "Rupees."},
                        "max_duration_minutes": {"type": "INTEGER"},
                    },
                },
                "clear_filters": {
                    "type": "ARRAY",
                    "description": "Filters the caller removed.",
                    "items": {
                        "type": "STRING",
                        "enum": ["stops", "airline", "time_of_day", "departure_time", "arrival_time", "max_fare", "max_duration_minutes"],
                    },
                },
                "passenger_count": {"type": "INTEGER", "description": "Total travellers, only if the caller said it."},
            },
            "required": ["query_sub_type"],
        },
    },
    {
        "name": "FlightActionTool",
        "behavior": "NON_BLOCKING",
        "description": "Gives details of a shown flight, or selects it for booking.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING", "enum": ["FLIGHT_DETAILS", "SELECT_FLIGHT"],
                    "description": "FLIGHT_DETAILS for questions, SELECT_FLIGHT when the caller chooses.",
                },
                "flight_id": {"type": "STRING", "description": "Id of a shown flight. Wins over reference."},
                "reference": {
                    "type": "STRING", "enum": ["CHEAPEST", "FASTEST", "FIRST", "SECOND"],
                    "description": "Use when no flight_id. FIRST and SECOND mean the most recently offered options.",
                },
                "passenger_count": {"type": "INTEGER", "description": "Total travellers, only if said in this turn."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "TravellerDetailsTool",
        "behavior": "BLOCKING",
        "description": "Saves traveller and contact details after flights are selected. Call on every caller reply until it says to call PaymentTool. Send only what the caller said in this turn.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "passenger_count": {"type": "INTEGER", "description": "New total travellers."},
                "additional_passengers": {"type": "INTEGER", "description": "Travellers to add to those saved. Do not send with passenger_count."},
                "add_more_passengers": {"type": "BOOLEAN", "description": "Caller wants to add travellers, count not said."},
                "includes_children": {"type": "BOOLEAN", "description": "Any child or infant travelling."},
                "child_count": {"type": "INTEGER", "description": "Children and infants."},
                "passenger_count_confirmed": {"type": "BOOLEAN", "description": "Caller confirmed the count and mix."},
                "passenger_index": {"type": "INTEGER", "description": "Traveller number, starting at 1."},
                "first_name_letters": {
                    "type": "ARRAY",
                    "description": "Given name letters, one capital per item, a space item between words.",
                    "items": {"type": "STRING", "enum": _LETTERS + [" "]},
                },
                "last_name_letters": {
                    "type": "ARRAY",
                    "description": "Surname letters, one capital per item.",
                    "items": {"type": "STRING", "enum": list(_LETTERS)},
                },
                "spelling_source": {
                    "type": "STRING", "enum": ["model_guess", "caller_spelled"],
                    "description": "caller_spelled only when the caller spelled the letters.",
                },
                "name_confirmed": {"type": "BOOLEAN", "description": "Caller accepted (true) or rejected (false) the name readback."},
                "age": {"type": "INTEGER", "description": "Age in years, 0 for an infant."},
                "gender": {"type": "STRING", "description": "As the caller stated it. Never guess."},
                "date_of_birth": {"type": "STRING", "description": "YYYY-MM-DD, for age 12 or below."},
                "phone_choice": {"type": "STRING", "enum": ["same", "new"], "description": "same uses the calling number, new collects another."},
                "phone_number": {"type": "STRING", "description": "New or corrected WhatsApp number."},
                "phone_confirmed": {"type": "BOOLEAN", "description": "Caller accepted the WhatsApp number readback."},
                "email": {"type": "STRING", "description": "Email as the caller said it."},
                "email_confirmed": {"type": "BOOLEAN", "description": "Caller accepted the email readback."},
                "details_confirmed": {"type": "BOOLEAN", "description": "Caller accepted the details sent on WhatsApp."},
                "retry_whatsapp": {"type": "BOOLEAN", "description": "Caller wants the failed WhatsApp send retried."},
            },
        },
    },
    {
        "name": "PaymentTool",
        "behavior": "NON_BLOCKING",
        "description": "Sends the payment link or answers a payment question. Call only when TravellerDetailsTool says so.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING", "enum": ["PROCEED", "REVIEW", "INFORMATION"],
                    "description": "PROCEED sends the link, REVIEW checks a round trip without a link, INFORMATION answers a question.",
                },
            },
            "required": ["action"],
        },
    },
]

TOOL_NAMES: List[str] = [d["name"] for d in TOOL_DECLARATIONS]
DECLARATION_BY_NAME: Dict[str, Dict[str, Any]] = {d["name"]: d for d in TOOL_DECLARATIONS}


def wire_declaration(name: str) -> Dict[str, Any]:
    """The declaration as sent on the wire. ``behavior`` is dropped.

    Gemini 3.x Live does not support ``NON_BLOCKING`` yet and Pipecat already omits the field
    for Vertex sessions, so every Tara tool runs BLOCKING here. That is the safe direction for
    this contract: the model waits for the result that carries the next card.
    """
    declaration = copy.deepcopy(DECLARATION_BY_NAME[name])
    declaration.pop("behavior", None)
    return declaration


def wire_declarations(names) -> List[Dict[str, Any]]:
    """Wire declarations for a ``context_update`` frame, in declaration order."""
    wanted = set(names)
    return [wire_declaration(name) for name in TOOL_NAMES if name in wanted]


def _json_schema_types(node: Any) -> Any:
    """Lower-case schema types (``OBJECT`` -> ``object``) for Pipecat's JSON-schema path."""
    if isinstance(node, dict):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else _json_schema_types(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [_json_schema_types(item) for item in node]
    return node


def function_schemas(names: Optional[List[str]] = None):
    """Pipecat ``FunctionSchema`` objects for setup (``names`` defaults to all six)."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    wanted = set(names or TOOL_NAMES)
    result = []
    for name in TOOL_NAMES:
        if name not in wanted:
            continue
        declaration = wire_declaration(name)
        parameters = _json_schema_types(declaration.get("parameters") or {})
        result.append(FunctionSchema(
            name=name,
            description=declaration["description"],
            properties=parameters.get("properties", {}),
            required=parameters.get("required", []),
        ))
    return result


# The tools each card registers when ``context_update`` can swap them. A context_update
# REPLACES the declared list, so each card sends only what it still needs and the tools that
# already built the session drop out: search and airport lookup once a flight is chosen,
# traveller details once the review is confirmed. SelectLanguageTool stays on every card (the
# base SI allows a language switch at any time; ~146 tokens). From card 4 a flight change picks
# one of the flights already offered (FlightActionTool, ~182 tokens); SearchTool (~763) is gone.
# A card and its tools arrive in the same tool call (``live_tool_swapper``).
_LANG = ("SelectLanguageTool",)
_TRAVELLER_STEP = _LANG + ("TravellerDetailsTool", "FlightActionTool")
TOOL_GROUP_BY_CARD: Dict[int, Tuple[str, ...]] = {
    1: _LANG,
    2: _LANG + ("SearchTool", "CheckAirportTool"),
    3: _LANG + ("FlightActionTool", "SearchTool"),
    4: _TRAVELLER_STEP,
    5: _TRAVELLER_STEP,
    6: _TRAVELLER_STEP,
    7: _TRAVELLER_STEP,
    8: _LANG + ("PaymentTool",),
}


# ---------------------------------------------------------------------------
# Mock inventory
# ---------------------------------------------------------------------------

#: city -> (IATA, airport name, lat, lon)
AIRPORTS: Dict[str, Tuple[str, str, float, float]] = {
    "Delhi": ("DEL", "Indira Gandhi International Airport", 28.56, 77.10),
    "Mumbai": ("BOM", "Chhatrapati Shivaji Maharaj International Airport", 19.09, 72.87),
    "Bengaluru": ("BLR", "Kempegowda International Airport", 13.20, 77.71),
    "Kolkata": ("CCU", "Netaji Subhas Chandra Bose International Airport", 22.65, 88.45),
    "Chennai": ("MAA", "Chennai International Airport", 12.99, 80.17),
    "Hyderabad": ("HYD", "Rajiv Gandhi International Airport", 17.24, 78.43),
    "Pune": ("PNQ", "Pune Airport", 18.58, 73.92),
    "Goa": ("GOI", "Dabolim Airport", 15.38, 73.83),
    "Ahmedabad": ("AMD", "Sardar Vallabhbhai Patel International Airport", 23.07, 72.63),
    "Jaipur": ("JAI", "Jaipur International Airport", 26.82, 75.81),
    "Kochi": ("COK", "Cochin International Airport", 10.15, 76.40),
    "Lucknow": ("LKO", "Chaudhary Charan Singh International Airport", 26.76, 80.89),
    "Patna": ("PAT", "Jay Prakash Narayan Airport", 25.59, 85.09),
    "Guwahati": ("GAU", "Lokpriya Gopinath Bordoloi International Airport", 26.11, 91.59),
    "Varanasi": ("VNS", "Lal Bahadur Shastri International Airport", 25.45, 82.86),
    "Chandigarh": ("IXC", "Chandigarh International Airport", 30.67, 76.79),
    "Srinagar": ("SXR", "Sheikh ul-Alam International Airport", 33.99, 74.77),
    "Nagpur": ("NAG", "Dr. Babasaheb Ambedkar International Airport", 21.09, 79.05),
    "Indore": ("IDR", "Devi Ahilya Bai Holkar Airport", 22.72, 75.80),
    "Bhubaneswar": ("BBI", "Biju Patnaik International Airport", 20.24, 85.82),
    "Coimbatore": ("CJB", "Coimbatore International Airport", 11.03, 77.04),
    "Thiruvananthapuram": ("TRV", "Trivandrum International Airport", 8.48, 76.92),
    "Amritsar": ("ATQ", "Sri Guru Ram Dass Jee International Airport", 31.71, 74.80),
    "Dehradun": ("DED", "Jolly Grant Airport", 30.19, 78.18),
    "Bagdogra": ("IXB", "Bagdogra Airport", 26.68, 88.33),
    "Visakhapatnam": ("VTZ", "Visakhapatnam Airport", 17.72, 83.22),
}
_CODE_TO_CITY = {v[0]: k for k, v in AIRPORTS.items()}

_CITY_ALIASES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "bombay": "Mumbai", "calcutta": "Kolkata",
    "madras": "Chennai", "new delhi": "Delhi", "dilli": "Delhi", "trivandrum": "Thiruvananthapuram",
    "cochin": "Kochi", "ernakulam": "Kochi", "vizag": "Visakhapatnam", "siliguri": "Bagdogra",
    "दिल्ली": "Delhi", "मुंबई": "Mumbai", "बेंगलुरु": "Bengaluru", "कोलकाता": "Kolkata", "चेन्नई": "Chennai",
    "हैदराबाद": "Hyderabad", "पुणे": "Pune", "गोवा": "Goa", "जयपुर": "Jaipur", "लखनऊ": "Lucknow", "पटना": "Patna",
}

#: Places without a commercial airport -> nearby airports (city, km).
NO_AIRPORT: Dict[str, List[Tuple[str, int]]] = {
    "Rishikesh": [("Dehradun", 20)], "Haridwar": [("Dehradun", 35)], "Mussoorie": [("Dehradun", 60)],
    "Darjeeling": [("Bagdogra", 70)], "Gangtok": [("Bagdogra", 125)], "Ooty": [("Coimbatore", 88)],
    "Munnar": [("Kochi", 110)], "Alleppey": [("Kochi", 85)], "Lonavala": [("Pune", 65), ("Mumbai", 90)],
    "Mahabaleshwar": [("Pune", 120)], "Noida": [("Delhi", 40)], "Gurgaon": [("Delhi", 15)],
    "Gurugram": [("Delhi", 15)], "Navi Mumbai": [("Mumbai", 30)], "Pondicherry": [("Chennai", 150)],
    "Puducherry": [("Chennai", 150)], "Shillong": [("Guwahati", 120)], "Manali": [("Chandigarh", 300)],
}


def no_airport_facts(place: str) -> Tuple[List[Dict[str, Any]], str]:
    """Nearby airports for a place without one, and the line that says so."""
    nearby = next((v for k, v in NO_AIRPORT.items() if k.lower() == place.strip().lower()), [])
    options = [{"city": c, "code": AIRPORTS[c][0], "distance_km": km} for c, km in nearby]
    facts = f"{place.strip().title()} has no airport."
    if options:
        facts += " Nearby: " + ", ".join(f"{o['city']} ({o['distance_km']} km)" for o in options) + "."
    return options, facts

INTERNATIONAL = {
    "dubai", "london", "singapore", "bangkok", "new york", "kathmandu", "colombo", "paris", "toronto",
    "abu dhabi", "doha", "kuala lumpur", "bali", "male", "sydney", "san francisco",
}

AIRLINES = [
    ("IndiGo", "6E", 1.00), ("Air India", "AI", 1.12), ("Akasa Air", "QP", 0.97),
    ("Air India Express", "IX", 0.93), ("SpiceJet", "SG", 0.95),
]
_DEPARTURES = ["05:40", "06:15", "07:05", "08:30", "10:30", "12:20", "14:45", "16:10", "18:15", "19:55", "21:30", "23:05"]
_HUBS = ["Delhi", "Mumbai", "Bengaluru", "Hyderabad"]
CALLING_NUMBER = "9876543210"  # The demo caller's line; a real deployment reads it from telephony.
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def today_ist() -> dt.date:
    return dt.datetime.now(IST).date()


def _km(a: str, b: str) -> float:
    _, _, la1, lo1 = AIRPORTS[a]
    _, _, la2, lo2 = AIRPORTS[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def rupees(amount: int) -> str:
    """Indian digit grouping: 118873 -> '₹1,18,873'."""
    digits = str(int(amount))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"₹{digits}"


def time_say(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def date_say(day: dt.date) -> str:
    return f"{day.strftime('%A')}, {day.day} {day.strftime('%B')}"


def short_date(day: dt.date) -> str:
    return f"{day.day} {day.strftime('%b')}"


def duration_say(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    parts = []
    if h:
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} minutes")
    return " ".join(parts) or "0 minutes"


def spell(word: str) -> str:
    return " ".join(ch for ch in word.upper() if ch.isalnum())


@dataclass
class Flight:
    flight_id: str
    leg: str
    airline: str
    flight_number: str
    origin: str
    destination: str
    date: dt.date
    depart: str
    arrive: str
    duration_min: int
    stops: int
    via: Optional[str]
    fare: int

    @property
    def depart_minutes(self) -> int:
        h, m = (int(x) for x in self.depart.split(":"))
        return h * 60 + m

    def label(self) -> str:
        return f"{self.airline}, {time_say(self.depart)}, {rupees(self.fare)}"

    def offer(self) -> Dict[str, Any]:
        return {
            "flight_id": self.flight_id,
            "airline": self.airline,
            "flight_number": self.flight_number,
            "depart": time_say(self.depart),
            "arrive": time_say(self.arrive),
            "duration_say": duration_say(self.duration_min),
            "stops_say": "non-stop" if not self.stops else f"1 stop via {self.via}",
            "fare": self.fare,
            "fare_say": rupees(self.fare),
            "per_adult_say": "per adult",
        }


def generate_flights(origin: str, destination: str, day: dt.date, leg: str) -> List[Flight]:
    """Six deterministic flights for a route and day, sorted by fare."""
    seed = int(hashlib.md5(f"{origin}|{destination}|{day.isoformat()}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    km = _km(origin, destination)
    direct_min = int(round((35 + km / 7.8) / 5.0) * 5)
    lead_days = max(0, (day - today_ist()).days)
    urgency = 1.35 if lead_days < 4 else 1.15 if lead_days < 10 else 1.0
    slots = sorted(rng.sample(_DEPARTURES, 6))
    prefix = "F" if leg == "outbound" else "R"
    flights: List[Flight] = []
    for i, depart in enumerate(slots):
        airline, code, factor = AIRLINES[rng.randrange(len(AIRLINES))]
        stops = 1 if (i in (2, 5) and km > 600) else 0
        via = None
        duration = direct_min
        if stops:
            hubs = [h for h in _HUBS if h not in (origin, destination)]
            via = min(hubs, key=lambda h: _km(origin, h) + _km(h, destination))
            duration += rng.choice([95, 110, 135, 150])
        h, m = (int(x) for x in depart.split(":"))
        arrive_total = h * 60 + m + duration
        arrive = f"{(arrive_total // 60) % 24:02d}:{arrive_total % 60:02d}"
        peak = 1.08 if h in (6, 7, 8, 18, 19) else 1.0
        base = (2600 + km * 3.4) * factor * peak * urgency * (0.86 if stops else 1.0)
        fare = int(base * rng.uniform(0.92, 1.12))
        fare = fare - fare % 10 + rng.choice([2, 4, 6, 8, 9])
        flights.append(Flight(
            flight_id="", leg=leg, airline=airline, flight_number=f"{code} {rng.randint(201, 2899)}",
            origin=origin, destination=destination, date=day, depart=depart, arrive=arrive,
            duration_min=duration, stops=stops, via=via, fare=fare,
        ))
    flights.sort(key=lambda f: (f.fare, f.depart_minutes))
    for i, flight in enumerate(flights, start=1):
        flight.flight_id = f"{prefix}{i}"
    return flights


# ---------------------------------------------------------------------------
# Call state
# ---------------------------------------------------------------------------

_LANGUAGE_STYLE = {
    "Hindi": "Hindi, everyday Hinglish",
    "English": "Indian English",
    "Tamil": "Tamil, everyday spoken Tamil",
}


def language_style(language: Optional[str]) -> str:
    if not language:
        return "Indian English"
    return _LANGUAGE_STYLE.get(language, f"{language}, everyday spoken {language}")


@dataclass
class Traveller:
    first_name: str = ""
    last_name: str = ""
    name_confirmed: bool = False
    age: Optional[int] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None

    @property
    def name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)

    def complete(self) -> bool:
        needs_dob = self.age is not None and self.age <= 12
        return bool(self.name and self.name_confirmed and self.age is not None and self.gender
                    and (self.date_of_birth or not needs_dob))


@dataclass
class CallState:
    """Everything the model must never have to remember. The server writes it; cards render it."""

    today: dt.date = field(default_factory=today_ist)
    language: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    trip_type: Optional[str] = None
    depart_date: Optional[dt.date] = None
    return_date: Optional[dt.date] = None
    outbound: Optional[Flight] = None
    ret: Optional[Flight] = None
    total_told: Optional[int] = None
    per_adult_told: Optional[int] = None
    passenger_count: Optional[int] = None
    child_count: int = 0
    mix_known: bool = False
    count_confirmed: bool = False
    travellers: List[Traveller] = field(default_factory=list)
    whatsapp: Optional[str] = None
    whatsapp_confirmed: bool = False
    email: Optional[str] = None
    email_confirmed: bool = False
    details_confirmed: bool = False
    booking_ref: Optional[str] = None
    step: str = "language"
    waiting_for: str = "the caller's language"
    #: Trip details heard before a search could run, so a resent card never says "not given yet".
    heard: Optional[str] = None

    def legs_selected(self) -> bool:
        if not self.outbound:
            return False
        return self.trip_type != "RT" or self.ret is not None

    def adults(self) -> int:
        return max(0, (self.passenger_count or 1) - self.child_count)

    def per_adult_total(self) -> int:
        return sum(f.fare for f in (self.outbound, self.ret) if f)

    def total_fare(self) -> int:
        return self.per_adult_total() * (self.passenger_count or 1)

    def party_say(self) -> str:
        if (self.passenger_count or 1) > 1 and not self.mix_known:
            return f"{self.passenger_count} travellers"
        adults, children = self.adults(), self.child_count
        parts = [f"{adults} adult" + ("s" if adults != 1 else "")]
        if children:
            parts.append(f"{children} child" + ("ren" if children != 1 else ""))
        return " and ".join(parts)

    def trip_text(self) -> Optional[str]:
        if not (self.origin and self.destination):
            return f"heard so far: {self.heard}" if self.heard else None
        o, d = self.origin, self.destination
        text = f"{'round trip' if self.trip_type == 'RT' else 'one way'}, {o} ({AIRPORTS[o][0]}) to {d} ({AIRPORTS[d][0]})"
        if self.depart_date:
            text += f", going {self.depart_date.day} {self.depart_date.strftime('%B')}"
        if self.trip_type == "RT":
            text += f", return {self.return_date.day} {self.return_date.strftime('%B')}" if self.return_date else ", return date not given yet"
        return text

    def _flight_text(self, flight: Optional[Flight]) -> Optional[str]:
        if not flight:
            return "not selected yet" if self.origin else None
        return f"selected, id {flight.flight_id}, {flight.airline}, {time_say(flight.depart)}, {rupees(flight.fare)}"

    def travellers_text(self) -> Optional[str]:
        if not self.passenger_count:
            return None
        text = self.party_say()
        named = []
        for i, t in enumerate(self.travellers, start=1):
            if not t.name:
                continue
            bits = [t.name]
            if t.age is not None:
                bits.append(str(t.age))
            if t.gender:
                bits.append(t.gender)
            bits.append("name confirmed" if t.name_confirmed else "name not confirmed")
            named.append(f"Passenger {i}: " + ", ".join(bits))
        return text + (". " + ". ".join(named) if named else "")

    def snapshot(self) -> Dict[str, Any]:
        whatsapp = None
        if self.whatsapp:
            source = "calling number" if self.whatsapp == CALLING_NUMBER else "number"
            whatsapp = f"{source} ending {self.whatsapp[-4:]}, {'confirmed' if self.whatsapp_confirmed else 'not confirmed'}"
        email = None
        if self.email:
            email = f"{self.email}, {'confirmed' if self.email_confirmed else 'not confirmed'}"
        total = None
        if self.total_told:
            total = f"{rupees(self.total_told)} for {self.party_say()}"
        elif self.per_adult_told:
            total = f"{rupees(self.per_adult_told)} per adult"
        return {
            "agent_name": AGENT_NAME,
            "today": date_say(self.today) + f" {self.today.year}",
            "language": self.language,
            "language_style": language_style(self.language),
            "trip_type": self.trip_type,
            "trip": self.trip_text(),
            "outbound_flight": self._flight_text(self.outbound),
            "return_flight": self._flight_text(self.ret) if self.trip_type == "RT" else None,
            "total_fare": total,
            "travellers": self.travellers_text(),
            "whatsapp": whatsapp,
            "email": email,
            "current_step": self.step.replace("_", " "),
            "waiting_for": self.waiting_for,
        }

    def one_line(self) -> str:
        """The ``call_state`` line in every tool response (kept under ~60 tokens)."""
        parts = [f"language {self.language or 'not chosen'}"]
        if self.origin and self.destination:
            trip = f"{'RT' if self.trip_type == 'RT' else 'OW'} {AIRPORTS[self.origin][0]} to {AIRPORTS[self.destination][0]}"
            if self.depart_date:
                trip += f" {short_date(self.depart_date)}"
            if self.return_date and self.trip_type == "RT":
                trip += f", return {short_date(self.return_date)}"
            parts.append(trip)
        if self.outbound:
            parts.append(f"outbound id {self.outbound.flight_id} {self.outbound.airline} {time_say(self.outbound.depart)} {rupees(self.outbound.fare)}")
        if self.trip_type == "RT" and self.origin:
            parts.append(f"return id {self.ret.flight_id} {self.ret.airline} {time_say(self.ret.depart)} {rupees(self.ret.fare)}" if self.ret else "return not selected")
        if self.passenger_count:
            parts.append(self.party_say())
        parts.append(f"step {self.step.replace('_', ' ')}")
        return "; ".join(parts)


# ---------------------------------------------------------------------------
# The booking engine
# ---------------------------------------------------------------------------

_WAITING_FOR = {
    "language": "the caller's language",
    "trip_details": "route and date",
    "flight_choice_outbound": "the caller to pick an outbound flight",
    "flight_choice_return": "the caller to pick a return flight",
    "flight_choice": "the caller to pick a flight",
    "passenger_count": "how many people are travelling",
    "passenger_mix": "whether anyone is a child",
    "child_count": "how many children are travelling",
    "child_date_of_birth": "the child's date of birth",
    "confirm_passenger_count": "a yes on the traveller count",
    "passenger_details": "the traveller's full name, age and gender",
    "confirm_name": "a yes on the name spelling",
    "phone_choice": "which WhatsApp number to use",
    "confirm_phone": "a yes on the WhatsApp number",
    "email": "the caller's email address",
    "confirm_email": "a yes on the email address",
    "review_details": "a yes on the details sent on WhatsApp",
    "retry_traveller_whatsapp": "whether to retry WhatsApp or use another number",
    "complete": "the payment link to be sent",
    "payment_sent": "the caller to pay with the link",
}

_TIME_OF_DAY = {"morning": (300, 720), "noon": (720, 840), "afternoon": (720, 1020), "evening": (1020, 1260), "night": (1260, 1740)}
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


def _clean_filters(raw: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """Validate and coerce REFINE_RESULTS filters. Nothing invalid is ever saved."""
    if raw in (None, ""):
        return {}, None
    if not isinstance(raw, dict):
        return {}, "filters must be an object, for example {\"stops_count\": 0}."
    clean: Dict[str, Any] = {}
    for key, value in raw.items():
        if value is None or value == "":
            continue
        if key == "time_of_day":
            value = str(value).strip().lower()
            if value not in _TIME_OF_DAY:
                return {}, f"time_of_day must be one of {', '.join(_TIME_OF_DAY)}."
        elif key in ("max_fare", "max_duration_minutes", "stops_count"):
            try:
                value = int(float(re.sub(r"[^0-9.]", "", str(value))))
            except ValueError:
                return {}, f"{key} must be a number."
        elif key in ("departure_after", "departure_before", "arrival_after", "arrival_before"):
            if _hhmm_minutes(value) is None:
                return {}, f"{key} must be a time in HH:MM."
        elif key == "connecting":
            value = value is True or str(value).lower() == "true"
        elif key == "airline":
            value = str(value).strip()
        else:
            continue  # not a filter this engine knows; ignore it rather than fail the search
        clean[key] = value
    return clean, None


def _age_on(born: dt.date, today: dt.date) -> int:
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _parse_date(value: Any) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None


def _hhmm_minutes(value: Any) -> Optional[int]:
    match = re.match(r"^\s*(\d{1,2}):(\d{2})", str(value or ""))
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def resolve_city(raw: Any) -> Tuple[Optional[str], Optional[str]]:
    """Return (city, problem). problem is 'international', 'no_airport' or 'unknown'."""
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return None, None
    key = text.lower().removesuffix(" airport").strip()
    upper = text.upper()
    if upper in _CODE_TO_CITY:
        return _CODE_TO_CITY[upper], None
    for city in AIRPORTS:
        if city.lower() == key:
            return city, None
    if key in _CITY_ALIASES:
        return _CITY_ALIASES[key], None
    if key in INTERNATIONAL:
        return None, "international"
    for place in NO_AIRPORT:
        if place.lower() == key:
            return None, "no_airport"
    return None, "unknown"


class TravelBookingEngine:
    """One call's booking backend. Not thread-safe; the architecture serialises calls with a lock."""

    def __init__(self, today: Optional[dt.date] = None) -> None:
        self.state = CallState(today=today or today_ist())
        self.active_card = 1
        self.results: Dict[str, List[Flight]] = {}
        self.offered: Dict[str, List[str]] = {}
        self.filters: Dict[str, Dict[str, Any]] = {"outbound": {}, "return": {}}
        self.current_leg = "outbound"
        self.calendar: List[Dict[str, Any]] = []
        self.calendar_cheapest: Optional[dt.date] = None
        self.attach_card_to_next_response = False
        self.last_card_text: Optional[str] = None
        self._current_instruction = "Ask which language the caller would like to talk in."
        self._current_next: List[Dict[str, Any]] = [{"when": "The caller names a language", "tool": "SelectLanguageTool"}]
        self._pending_name: Dict[int, Traveller] = {}
        self._child_dobs: List[str] = []
        self._payment_link_sent = False
        #: The address last read back at confirm_email; only a yes to that address confirms it.
        self._email_read_back: Optional[str] = None
        #: passenger index -> (first, last) as last read back to the caller.
        self._name_read_back: Dict[int, Tuple[str, str]] = {}
        #: Trip details heard before a search could run ("needs_info"); merged into the next search.
        self._draft: Dict[str, Any] = {}

    # -- card plumbing -------------------------------------------------------

    def build_card(self, number: Optional[int] = None, resend: Optional[str] = None) -> str:
        card = TARA_CARD_BY_NUMBER[number or self.active_card]
        text = format_tara_prompt_card(card, state=self.state.snapshot(), resend=resend)
        self.last_card_text = text
        return text

    def opening_card(self) -> str:
        """Card 1 with the initial state; sent before the greeting."""
        return self.build_card(1)

    def _set_step(self, step: str) -> None:
        s = self.state
        s.step = step
        s.waiting_for = _WAITING_FOR.get(step, step.replace("_", " "))
        if step == "confirm_passenger_count":
            s.total_told = s.total_fare()  # ask_say reads the total
        elif step == "confirm_email":
            self._email_read_back = s.email

    def _respond(self, payload: Dict[str, Any], *, card: Optional[int] = None,
                 resend_current: bool = False, informational: bool = False) -> Dict[str, Any]:
        """Attach call_state, and prompt_card when the flow changes.

        A result that moves the flow becomes the step to resume (its instruction and next).
        Side answers (airport facts, flight details, payment facts, alternatives offered for a
        change) are ``informational`` and leave that untouched.
        """
        response = dict(payload)
        if "instruction" in response and "error" not in response and not informational:
            self._current_instruction = response["instruction"]
            if "next" in response:
                self._current_next = response["next"]
        if card is not None and card != self.active_card:
            self.active_card = card
            response["prompt_card"] = self.build_card(card)
        elif resend_current or self.attach_card_to_next_response:
            response["prompt_card"] = self.build_card(self.active_card)
        if "prompt_card" in response:
            self.attach_card_to_next_response = False
        response["call_state"] = self.state.one_line()
        return response

    def _error(self, message: str, instruction: str, **extra: Any) -> Dict[str, Any]:
        return self._respond({"status": "error", "error": message, "instruction": instruction, **extra})

    def failure(self, name: str) -> Dict[str, Any]:
        """The result for a call that raised: keep the model talking and on the open step."""
        return self._error(f"{name} could not be completed.",
                           "Say sorry in a few words and ask the caller to say that again, then continue the current step.",
                           next=self._current_next)

    def current_step_payload(self) -> Dict[str, Any]:
        return {"instruction": self._current_instruction, "next": self._current_next,
                "data": {"step": self.state.step}}

    # -- dispatch ------------------------------------------------------------

    def handle(self, name: str, args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        args = dict(args or {})
        args.pop("user_language", None)  # legacy field; the server owns the language
        handler = {
            "SelectLanguageTool": self.select_language,
            "CheckAirportTool": self.check_airport,
            "SearchTool": self.search,
            "FlightActionTool": self.flight_action,
            "TravellerDetailsTool": self.traveller_details,
            "PaymentTool": self.payment,
        }.get(name)
        if handler is None:
            return self._error(f"Unknown tool {name}.", "Continue from session state.")
        return handler(args)

    # -- SelectLanguageTool --------------------------------------------------

    def select_language(self, args: Dict[str, Any]) -> Dict[str, Any]:
        raw = str(args.get("language") or "").strip()
        language = next((l for l in LANGUAGES if l.lower() == raw.lower()), None)
        if not language:
            return self._error(f"language must be one of the supported names, got '{raw}'.",
                               "Ask the caller which language they want, then call SelectLanguageTool with its name.")
        first = self.state.language is None
        self.state.language = language
        if first or self.active_card == 1:
            self._set_step("trip_details")
            return self._respond({
                "status": "saved", "language": language,
                "instruction": "Ask where they would like to fly, or for the next missing trip detail if they already gave a route, in the chosen language.",
                "data": {"step": "trip_details"},
                "next": [{"when": "The caller gives a route and a date", "tool": "SearchTool"}],
            }, card=2)
        # A mid-call switch keeps the step and re-sends the current card in the new language.
        payload = {"status": "saved", "language": language, **self.current_step_payload()}
        return self._respond(payload, resend_current=True)

    # -- CheckAirportTool ----------------------------------------------------

    def check_airport(self, args: Dict[str, Any]) -> Dict[str, Any]:
        place = str(args.get("place") or "").strip()
        if not place:
            return self._error("place is required.", "Ask which place they mean, then call CheckAirportTool.")
        city, problem = resolve_city(place)
        if city:
            code, name, _, _ = AIRPORTS[city]
            return self._respond({
                "status": "ok", "place": place, "has_airport": True,
                "airport": {"city": city, "code": code, "name": name},
                "facts": f"{city} has an airport: {name}.",
                "instruction": "Say facts in one line, then continue the trip details.",
            }, informational=True)
        if problem == "international":
            return self._respond({
                "status": "out_of_scope", "place": place, "has_airport": None,
                "facts": f"{place} is outside India.",
                "instruction": "Say you can only help with domestic flight booking within India, and offer that.",
            }, informational=True)
        options, facts = no_airport_facts(place)
        return self._respond({
            "status": "ok", "place": place, "has_airport": False, "nearby": options, "facts": facts,
            "instruction": "Say facts, then ask which nearby airport the caller wants. Never pick one for them.",
        }, informational=True)

    # -- SearchTool ----------------------------------------------------------
    # City errors carry the nearby airports themselves: CheckAirportTool is registered on
    # card 2 only, so an error on a later card must not send the model to it.

    def _city_arg(self, raw: Any, role: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        city, problem = resolve_city(raw)
        if city or not raw:
            return city, None
        if problem == "international":
            return None, self._respond({
                "status": "out_of_scope",
                "instruction": "Say you can only help with domestic flight booking within India, and offer that.",
            }, informational=True)
        if problem == "no_airport":
            options, facts = no_airport_facts(str(raw))
            return None, self._error(f"{raw} has no airport.",
                                     "Say facts, then ask which nearby airport the caller wants. Never pick one for them.",
                                     nearby=options, facts=facts)
        return None, self._error(f"{role} '{raw}' is not a known Indian airport city.",
                                 "Ask the caller to repeat the city, or to name the nearest city with an airport.")

    def _count_from_search(self, args: Dict[str, Any]) -> None:
        """A traveller count mentioned with a search or selection; a change needs the total read again."""
        s = self.state
        if isinstance(args.get("passenger_count"), int) and args["passenger_count"] > 0:
            new = min(9, args["passenger_count"])
            if new != s.passenger_count:
                s.passenger_count, s.count_confirmed, s.details_confirmed = new, False, False

    def _is_return_leg_request(self, origin: Optional[str], destination: Optional[str],
                               depart: Optional[dt.date]) -> bool:
        """The return leg of the stored round trip: the reversed route, or just the return date."""
        s = self.state
        if not (s.trip_type == "RT" and s.outbound and s.origin):
            return False
        if origin is None and destination is None:
            return depart is not None and depart == s.return_date
        return origin == s.destination and destination == s.origin and (depart is None or depart == s.return_date)

    def search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        sub = str(args.get("query_sub_type") or "").upper()
        if sub not in ("SPECIFIC_DATE", "DATE_RANGE", "REFINE_RESULTS"):
            return self._error("query_sub_type is required: SPECIFIC_DATE, DATE_RANGE or REFINE_RESULTS.",
                               "Call SearchTool again with query_sub_type set.")
        self._count_from_search(args)
        if sub == "REFINE_RESULTS":
            return self._refine(args)

        origin, problem = self._city_arg(args.get("origin"), "origin")
        if problem:
            return problem
        destination, problem = self._city_arg(args.get("destination"), "destination")
        if problem:
            return problem
        depart = _parse_date(args.get("depart_date"))
        if args.get("date_reference") == "CALENDAR_CHEAPEST":
            if not self.calendar_cheapest:
                return self._error("There is no fare calendar yet.", "Search DATE_RANGE first, or ask for a date.")
            depart = self.calendar_cheapest
        trip_type = str(args.get("trip_type") or "").upper() or None
        if trip_type not in (None, "OW", "RT"):
            trip_type = None
        return_date = _parse_date(args.get("return_date"))

        # The return leg of a stored round trip: answer from the stored split search.
        if self._is_return_leg_request(origin, destination, depart):
            return self._offer_leg("return", changing=self.state.legs_selected() and self.active_card >= 4)

        # Fill what the caller did not repeat: first from details heard before a search could
        # run, then from the stored trip. The model sends only what was said in this turn.
        s, d = self.state, self._draft
        origin = origin or d.get("origin") or s.origin
        destination = destination or d.get("destination") or s.destination
        depart = depart or d.get("depart") or s.depart_date
        if not trip_type:
            trip_type = "RT" if return_date else (d.get("trip_type") or s.trip_type or "OW")
        if trip_type == "RT":
            return_date = return_date or d.get("return_date") or s.return_date
        else:
            return_date = None
        self._draft = {k: v for k, v in (("origin", origin), ("destination", destination), ("depart", depart),
                                          ("trip_type", trip_type), ("return_date", return_date)) if v}
        s.heard = self._draft_say() or None

        missing = [label for label, value in (("origin city", origin), ("destination city", destination),
                                              ("travel date", depart)) if not value]
        if trip_type == "RT" and sub == "SPECIFIC_DATE" and not return_date:
            missing.append("return date")
        if missing:
            return self._respond({
                "status": "needs_info", "missing": missing,
                "instruction": f"Ask the caller for the {missing[0]} only.",
                "data": {"step": "trip_details", "heard": self._draft_say()},
                "next": [{"when": "The caller gives it", "tool": "SearchTool",
                          "arguments": {"query_sub_type": sub}}],
            })
        if origin == destination:
            self._draft.pop("destination", None)
            return self._error("origin and destination are the same.", "Ask the caller where they want to fly to.")
        bad = self._date_problem(depart)
        if bad:
            self._draft.pop("depart", None)
            return self._error(bad, "Ask the caller for another travel date.")

        if sub == "DATE_RANGE":
            return self._calendar(origin, destination, depart, _parse_date(args.get("depart_date_end")))

        if trip_type == "RT":
            bad = self._date_problem(return_date) or ("return date is before the departure date." if return_date < depart else None)
            if bad:
                self._draft.pop("return_date", None)
                return self._error(bad, "Ask the caller for the return date again.")

        # After a selection, a search for a leg of the same trip is a flight change, not a new trip.
        changing = s.legs_selected() and self.active_card >= 4
        if changing and origin == s.origin and destination == s.destination and depart == s.depart_date:
            self.results["outbound"] = generate_flights(origin, destination, depart, "outbound")
            self.filters["outbound"] = {}
            return self._offer_leg("outbound", changing=True)

        # A new trip: everything priced or reviewed for the old one must be heard and confirmed again.
        self._draft, s.heard = {}, None
        s.origin, s.destination, s.trip_type = origin, destination, trip_type
        s.depart_date, s.return_date = depart, return_date
        s.outbound = s.ret = None
        s.total_told = s.per_adult_told = None
        s.count_confirmed = s.details_confirmed = False
        self._void_payment_link()
        self.filters = {"outbound": {}, "return": {}}
        self.results = {"outbound": generate_flights(origin, destination, depart, "outbound")}
        if trip_type == "RT":
            self.results["return"] = generate_flights(destination, origin, return_date, "return")
        return self._offer_leg("outbound")

    def _draft_say(self) -> str:
        d = self._draft
        bits = []
        if d.get("origin") or d.get("destination"):
            bits.append(f"{d.get('origin') or '?'} to {d.get('destination') or '?'}")
        if d.get("depart"):
            bits.append(f"going {date_say(d['depart'])}")
        if d.get("return_date"):
            bits.append(f"return {date_say(d['return_date'])}")
        if d.get("trip_type") == "RT":
            bits.append("round trip")
        return ", ".join(bits)

    def _date_problem(self, day: Optional[dt.date]) -> Optional[str]:
        if not day:
            return "a date in YYYY-MM-DD is required."
        if day < self.state.today:
            return f"{day.isoformat()} is in the past; today is {self.state.today.isoformat()}."
        if (day - self.state.today).days > 330:
            return "bookings open only 330 days ahead."
        return None

    def _calendar(self, origin: str, destination: str, start: dt.date, end: Optional[dt.date]) -> Dict[str, Any]:
        end = end or (start + dt.timedelta(days=6))
        if end < start:
            return self._error("depart_date_end is before depart_date.", "Ask the caller for the date range again.")
        end = min(end, start + dt.timedelta(days=13))
        days = []
        day = start
        while day <= end:
            cheapest = generate_flights(origin, destination, day, "outbound")[0]
            days.append({"date": day.isoformat(), "date_say": date_say(day), "cheapest_fare": cheapest.fare,
                         "fare_say": rupees(cheapest.fare)})
            day += dt.timedelta(days=1)
        best = min(days, key=lambda d: d["cheapest_fare"])
        self.calendar = days
        self.calendar_cheapest = dt.date.fromisoformat(best["date"])
        self._draft.update({"origin": origin, "destination": destination})
        return self._respond({
            "status": "ok",
            "instruction": "Say the cheapest day and its fare_say, then ask if that day works.",
            "data": {"step": "trip_details", "cheapest": best, "calendar": days[:7]},
            "next": [{"when": "The caller accepts the cheapest day", "tool": "SearchTool",
                      "arguments": {"query_sub_type": "SPECIFIC_DATE", "date_reference": "CALENDAR_CHEAPEST"}}],
        })

    def _offer_leg(self, leg: str, changing: bool = False, pool: Optional[List[Flight]] = None,
                   note: Optional[str] = None) -> Dict[str, Any]:
        s = self.state
        self.current_leg = leg
        flights = pool if pool is not None else self._filtered(leg)
        if not flights:
            self.offered[leg] = []
            return self._respond({
                "status": "no_flights",
                "instruction": "Say no flight matches, and ask whether to drop a filter or try another date or time.",
                "data": {"step": s.step if changing else "flight_choice", "leg": leg,
                         "active_filters": self.filters.get(leg, {})},
            }, informational=changing)
        offered = flights[:2]
        self.offered[leg] = [f.flight_id for f in offered]
        day = s.depart_date if leg == "outbound" else s.return_date
        origin, destination = (s.origin, s.destination) if leg == "outbound" else (s.destination, s.origin)
        step = "flight_choice_return" if leg == "return" else ("flight_choice_outbound" if s.trip_type == "RT" else "flight_choice")
        if not changing:
            self._set_step(step)
        if changing:
            instruction = "Say the two flights in data.flights with fare_say and per_adult_say, then ask which one should replace the current flight."
        elif leg == "return":
            instruction = "Say the outbound selection in one short line, then the two return flights in data.flights with fare_say and per_adult_say, then ask which one."
        else:
            instruction = "Say the two flights in data.flights with fare_say and per_adult_say, then ask which one."
        data: Dict[str, Any] = {
            "step": self.state.step, "leg": leg,
            "route_say": f"{origin} to {destination}, {date_say(day)}",
            "flights": [f.offer() for f in offered],
            "results_count": len(flights),
        }
        if leg == "return" and s.outbound:
            data["outbound_selected_say"] = f"Outbound {s.outbound.airline} at {time_say(s.outbound.depart)} is selected."
        if note:
            data["note_say"] = note
        return self._respond({
            "status": "ok", "instruction": instruction, "data": data,
            "next": [{"when": "The caller picks a flight", "tool": "FlightActionTool", "arguments": {"action": "SELECT_FLIGHT"}},
                     {"when": "The caller wants cheaper, faster, an airline, a time of day or more options", "tool": "SearchTool",
                      "arguments": {"query_sub_type": "REFINE_RESULTS"}}],
        }, card=None if changing else 3, informational=changing)

    def _filtered(self, leg: str) -> List[Flight]:
        flights = list(self.results.get(leg, []))
        f = self.filters.get(leg, {})
        out = []
        for flight in flights:
            if f.get("airline") and f["airline"].lower() not in (flight.airline.lower(), flight.flight_number.split()[0].lower()) \
                    and not flight.airline.lower().startswith(f["airline"].lower()):
                continue
            if f.get("stops_count") is not None and flight.stops != f["stops_count"]:
                continue
            if f.get("connecting") is True and flight.stops == 0:
                continue
            if f.get("time_of_day"):
                lo, hi = _TIME_OF_DAY[f["time_of_day"]]
                if not lo <= flight.depart_minutes < hi:
                    continue
            arrive_m = _hhmm_minutes(flight.arrive)
            for key, value, op in (("departure_after", flight.depart_minutes, "ge"), ("departure_before", flight.depart_minutes, "le"),
                                   ("arrival_after", arrive_m, "ge"), ("arrival_before", arrive_m, "le")):
                bound = _hhmm_minutes(f.get(key))
                if bound is not None and ((op == "ge" and value < bound) or (op == "le" and value > bound)):
                    break
            else:
                if f.get("max_fare") and flight.fare > f["max_fare"]:
                    continue
                if f.get("max_duration_minutes") and flight.duration_min > f["max_duration_minutes"]:
                    continue
                out.append(flight)
        return out

    def _refine(self, args: Dict[str, Any]) -> Dict[str, Any]:
        leg = self.current_leg
        if not self.results.get(leg):
            return self._error("There are no results to refine.", "Ask for the route and date, then call SearchTool with SPECIFIC_DATE.")
        intent = str(args.get("refine_intent") or ("FILTER" if args.get("filters") or args.get("clear_filters") else "MORE")).upper()
        active = self.filters.setdefault(leg, {})
        _clear_map = {"stops": ("stops_count", "connecting"), "airline": ("airline",), "time_of_day": ("time_of_day",),
                      "departure_time": ("departure_after", "departure_before"), "arrival_time": ("arrival_after", "arrival_before"),
                      "max_fare": ("max_fare",), "max_duration_minutes": ("max_duration_minutes",)}
        filters, problem = _clean_filters(args.get("filters"))
        if problem:
            return self._error(problem, "Call SearchTool again with the filter in the declared format, or ask the caller what they meant.")
        clear = args.get("clear_filters") or []
        for name in [clear] if isinstance(clear, str) else clear:
            for key in _clear_map.get(name, ()):
                active.pop(key, None)
        active.update(filters)
        if "stops_count" in active:
            active.pop("connecting", None)
        pool = self._filtered(leg)
        note = None
        if intent == "CHEAPEST_ALTERNATIVES":
            pool.sort(key=lambda f: (f.fare, f.depart_minutes))
        elif intent == "FASTEST_ALTERNATIVES":
            pool.sort(key=lambda f: (f.duration_min, f.fare))
        elif intent == "MORE":
            shown = set(self.offered.get(leg, []))
            rest = [f for f in pool if f.flight_id not in shown]
            if not rest:
                note = "These are all the flights for this day."
            pool = rest or pool
        elif intent in ("SAME_FARE", "NEXT_FARE"):
            ref = self._reference_fare(args, leg)
            if ref is None:
                return self._error("SAME_FARE and NEXT_FARE need reference_flight_id, reference_fare or reference_role.",
                                   "Call SearchTool again with the reference the caller meant.")
            if intent == "SAME_FARE":
                pool = [f for f in pool if abs(f.fare - ref) <= 150]
            else:
                pool = sorted((f for f in pool if f.fare > ref), key=lambda f: f.fare)
        return self._offer_leg(leg, changing=self.active_card >= 4, pool=pool, note=note)

    def _reference_fare(self, args: Dict[str, Any], leg: str) -> Optional[int]:
        flights = self.results.get(leg, [])
        if args.get("reference_flight_id"):
            match = next((f for f in flights if f.flight_id.upper() == str(args["reference_flight_id"]).upper()), None)
            return match.fare if match else None
        if isinstance(args.get("reference_fare"), int):
            return args["reference_fare"]
        role = args.get("reference_role")
        if role == "CHEAPEST" and flights:
            return min(f.fare for f in flights)
        if role == "FASTEST" and flights:
            return min(flights, key=lambda f: f.duration_min).fare
        return None

    # -- FlightActionTool ----------------------------------------------------

    def _resolve_flight(self, args: Dict[str, Any]) -> Tuple[Optional[Flight], Optional[str]]:
        flight_id = str(args.get("flight_id") or "").strip().upper()
        if flight_id:
            leg = "return" if flight_id.startswith("R") else "outbound"
            match = next((f for f in self.results.get(leg, []) if f.flight_id == flight_id), None)
            if not match:
                return None, f"flight_id {flight_id} is not in the current results."
            return match, None
        reference = str(args.get("reference") or "").upper()
        leg = self.current_leg
        flights = self.results.get(leg, [])
        if not flights:
            return None, "There is no flight list yet."
        if reference in ("FIRST", "SECOND"):
            offered = self.offered.get(leg, [])
            index = 0 if reference == "FIRST" else 1
            if index >= len(offered):
                return None, f"There is no {reference.lower()} offered flight."
            return next(f for f in flights if f.flight_id == offered[index]), None
        if reference == "CHEAPEST":
            return min(flights, key=lambda f: (f.fare, f.depart_minutes)), None
        if reference == "FASTEST":
            return min(flights, key=lambda f: (f.duration_min, f.fare)), None
        return None, "flight_id or reference is required."

    def flight_action(self, args: Dict[str, Any]) -> Dict[str, Any]:
        action = str(args.get("action") or "").upper()
        if action not in ("FLIGHT_DETAILS", "SELECT_FLIGHT"):
            return self._error("action must be FLIGHT_DETAILS or SELECT_FLIGHT.", "Call FlightActionTool again with action set.")
        self._count_from_search(args)
        flight, problem = self._resolve_flight(args)
        if not flight:
            if not self.results:
                return self._error(problem, "Ask for the route and date, then call SearchTool.")
            return self._error(problem, "Ask the caller which flight they mean from the list they heard, or call SearchTool for what they asked.")
        if action == "FLIGHT_DETAILS":
            return self._respond({
                "status": "ok",
                "instruction": "Answer the caller's question from data in one or two lines. Say baggage or penalty only if asked, word for word.",
                "data": {"step": self.state.step, "flight": flight.offer(), "facts": f"{flight.airline} {flight.flight_number}, departs {time_say(flight.depart)}, arrives {time_say(flight.arrive)}, {duration_say(flight.duration_min)}."},
                "baggage": "15 kg check-in and 7 kg cabin baggage per adult.",
                "penalty": f"Cancellation fee {rupees(3500 if flight.fare > 6000 else 2999)} up to 4 hours before departure. Date change fee {rupees(2250)} plus any fare difference.",
                "next": self._current_next,
            }, informational=True)
        return self._select(flight)

    def _select(self, flight: Flight) -> Dict[str, Any]:
        s = self.state
        changing = s.legs_selected() and self.active_card >= 4
        if flight.leg == "return":
            if s.trip_type != "RT" or not s.outbound:
                return self._error("Select the outbound flight first.", "Help the caller pick the outbound flight.")
            previous, s.ret = s.ret, flight
        else:
            previous, s.outbound = s.outbound, flight

        if changing:
            # The itinerary changed: the caller reviews it again, and any link sent is void.
            total = s.total_fare()
            s.total_told = total
            s.details_confirmed = False
            self._void_payment_link()
            leg_word = "return" if flight.leg == "return" else ("outbound" if s.trip_type == "RT" else "")
            change = (f"Your {leg_word + ' ' if leg_word else ''}flight is now {flight.airline} at {time_say(flight.depart)}. "
                      f"The new total is {rupees(total)} for {s.party_say()}.")
            if previous and previous.flight_id == flight.flight_id:
                change = f"{flight.airline} at {time_say(flight.depart)} is already selected. The total stays {rupees(total)}."
            step, fields = self._next_open_step()
            response = self._step_response(step, {**fields, "change": change}, status="changed")
            response["instruction"] = "Say change exactly as given, then " + response["instruction"][0].lower() + response["instruction"][1:]
            return response

        if s.trip_type == "RT" and flight.leg == "outbound" and not s.ret:
            # Outbound of a round trip: hand the model the exact return-leg arguments.
            return_args = {"query_sub_type": "SPECIFIC_DATE", "trip_type": "OW", "origin": s.destination,
                           "destination": s.origin, "depart_date": s.return_date.isoformat()}
            self._set_step("flight_choice_return")
            return self._respond({
                "status": "selected",
                "instruction": "Say data.facts, then call SearchTool with exactly the arguments in next to get the return flights.",
                "data": {"step": "flight_choice_return",
                         "facts": f"{flight.airline}, {rupees(flight.fare)}, {time_say(flight.depart)} is selected for the outbound flight.",
                         "per_adult_say": "per adult"},
                "next": [{"when": "Now", "tool": "SearchTool", "arguments": return_args}],
            })

        # Last leg selected for the first time: the fare, then the first open traveller step
        # (the count, unless the caller already gave it with the search).
        s.per_adult_told = s.per_adult_total()
        combined = s.trip_type == "RT"
        facts = (f"{flight.airline} at {time_say(flight.depart)} is selected. "
                 + (f"The combined fare for both flights is {rupees(s.per_adult_total())}" if combined else f"The fare is {rupees(flight.fare)}"))
        step, fields = self._next_open_step() if s.passenger_count else ("passenger_count", {"ask_say": "How many people are travelling?"})
        self._set_step(step)
        return self._respond({
            "status": "selected",
            "instruction": STEP_INSTRUCTIONS["flight_selected"],
            "data": {"step": step, "facts": facts, "per_adult_say": "per adult"},
            **fields,
            "next": [{"when": "The caller answers, confirms, or corrects this step", "tool": "TravellerDetailsTool"}],
        }, card=card_for_step(step))

    def _void_payment_link(self) -> None:
        """After a change the old link and reference are void; PROCEED issues new ones."""
        self._payment_link_sent = False
        self.state.booking_ref = None

    # -- TravellerDetailsTool ------------------------------------------------

    def _step_response(self, step: str, extra: Optional[Dict[str, Any]] = None, *, status: str = "ok") -> Dict[str, Any]:
        self._set_step(step)
        if step == "confirm_name" and "name_spell" in (extra or {}) and extra.get("passenger_index") in self._pending_name:
            heard = self._pending_name[extra["passenger_index"]]
            self._name_read_back[extra["passenger_index"]] = (heard.first_name, heard.last_name)
        payload: Dict[str, Any] = {"status": status, "instruction": STEP_INSTRUCTIONS[step], "data": {"step": step}}
        if step == "complete":
            # Card 8 declares PaymentTool only: the details were confirmed at review.
            payload["next"] = [{"when": "Now", "tool": "PaymentTool", "arguments": {"action": "PROCEED"}}]
        else:
            payload["next"] = [{"when": "The caller answers, confirms, or corrects this step", "tool": "TravellerDetailsTool"}]
        payload.update(extra or {})
        return self._respond(payload, card=card_for_step(step))

    def _next_open_step(self) -> Tuple[str, Dict[str, Any]]:
        """The first unfinished step, in booking order, with its spoken fields."""
        s = self.state
        if not s.passenger_count:
            return "passenger_count", {"ask_say": "How many people are travelling?"}
        if s.passenger_count > 1 and not s.count_confirmed:
            if s.child_count == 0 and not s.mix_known:
                return "passenger_mix", {"ask_say": "Are all travellers adults, or are some of them children?"}
            if s.mix_known and s.child_count and len(self._child_dobs) < s.child_count:
                return "child_date_of_birth", {"ask_say": f"What is child {len(self._child_dobs) + 1}'s date of birth?"}
            return "confirm_passenger_count", {"ask_say": f"So that is {s.party_say()}, and the total fare is {rupees(s.total_fare())}. Shall I continue?"}
        while len(s.travellers) < s.passenger_count:
            s.travellers.append(Traveller())
        del s.travellers[s.passenger_count:]
        for index, traveller in enumerate(s.travellers, start=1):
            if not traveller.complete():
                pending = self._pending_name.get(index)
                if pending and not traveller.name_confirmed:
                    return "confirm_name", self._name_readback(index, pending, changed=None)
                missing = []
                if not traveller.name_confirmed:
                    missing.append("full name as on Aadhaar")
                if traveller.age is None:
                    missing.append("age")
                if not traveller.gender:
                    missing.append("gender")
                if traveller.age is not None and traveller.age <= 12 and not traveller.date_of_birth:
                    missing.append("date of birth")
                return "passenger_details", {
                    "passenger_index": index,
                    "ask_say": f"Please tell me passenger {index}'s " + ", ".join(missing) + ".",
                    "gender_say": "male or female",
                }
        if not (s.whatsapp and s.whatsapp_confirmed):
            if s.whatsapp and s.whatsapp != CALLING_NUMBER:
                return "confirm_phone", {"phone_digits": " ".join(s.whatsapp), "ask_say": "Is this WhatsApp number correct?"}
            return "phone_choice", {
                "calling_number": CALLING_NUMBER, "phone_digits": " ".join(CALLING_NUMBER),
                "ask_say": "Shall I send the booking details on WhatsApp to this number?",
            }
        if not s.email:
            return "email", {"ask_say": "What is your email address for the ticket?"}
        if not s.email_confirmed:
            return "confirm_email", {"email_readback": self._email_readback(s.email), "ask_say": "Is this email address correct?"}
        if not s.details_confirmed:
            if s.whatsapp.endswith("0000"):
                return "retry_traveller_whatsapp", {"note_say": "The WhatsApp message could not be delivered to this number.",
                                                    "ask_say": "Shall I try again, or use another number?"}
            return "review_details", {"heads_up": "I have sent all the booking details on WhatsApp.",
                                      "ask_say": "Please check them and tell me if everything is correct."}
        return "complete", {"heads_up": "All details are saved."}

    def _heard_name(self, index: int) -> bool:
        """True when the pending name for ``index`` is exactly the one last read back."""
        pending = self._pending_name.get(index)
        return pending is not None and self._name_read_back.get(index) == (pending.first_name, pending.last_name)

    def _name_readback(self, index: int, name: Traveller, changed: Optional[bool],
                       only: Optional[str] = None) -> Dict[str, Any]:
        first = name.first_name if only in (None, "first") else ""
        last = name.last_name if only in (None, "last") else ""
        readback = {
            "passenger_index": index,
            "note_say": f"I have noted passenger {index}'s name as {name.name}.",
            "name_spell": {
                "first_say": first, "first_spell": ", ".join(spell(w) for w in first.split()) if first else "",
                "last_say": last, "last_spell": spell(last) if last else "",
            },
            "ask_say": "Is this spelling correct?",
        }
        if changed is not None:
            readback["spelling_changed"] = changed
        return readback

    @staticmethod
    def _letters_to_name(letters: Any) -> str:
        if not isinstance(letters, list):
            return ""
        text = "".join(str(l)[:1] if str(l) != " " else " " for l in letters if isinstance(l, str))
        return " ".join(w.capitalize() for w in text.split())

    @staticmethod
    def _email_readback(email: str) -> Dict[str, str]:
        local, _, domain = email.partition("@")
        words = {".": "dot", "_": "underscore", "-": "dash", "+": "plus"}
        local_spell = " ".join(words.get(ch, ch.upper()) for ch in local)
        domain_say = " dot ".join(domain.split("."))
        return {"local_spell": local_spell, "domain_say": domain_say}

    @staticmethod
    def _normalise_email(raw: str) -> str:
        text = raw.strip().lower()
        text = re.sub(r"\s*\(?at the rate\)?\s*", "@", text)
        text = re.sub(r"\s+at\s+", "@", text)
        text = re.sub(r"\s+dot\s+", ".", text)
        return re.sub(r"\s+", "", text)

    @staticmethod
    def _normalise_phone(raw: Any) -> Optional[str]:
        digits = re.sub(r"\D", "", str(raw or ""))
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        if digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]
        return digits if re.fullmatch(r"[6-9]\d{9}", digits) else None

    def traveller_details(self, args: Dict[str, Any]) -> Dict[str, Any]:
        s = self.state
        if not s.legs_selected():
            return self._error("Flights are not selected yet.",
                               "Help the caller choose the flight first; traveller details come after selection.")

        # Email can arrive at any step: validate and save it at once, never drop it. A yes counts
        # only for the address last read back, and never in the call that changes the address.
        email_error, email_changed = None, False
        if args.get("email"):
            email = self._normalise_email(str(args["email"]))
            if _EMAIL_RE.match(email):
                if email != s.email:
                    s.email, s.email_confirmed, s.details_confirmed = email, False, False
                    email_changed = True
            elif email.startswith("@"):
                email_error = "The email address needs a name before the @, for example rahul.sharma@gmail.com."
            elif "@" not in email:
                email_error = "The email address is incomplete: it needs a name, an @ and a domain such as gmail.com."
            else:
                email_error = "The email domain is incomplete, for example gmail.com."
        if not email_changed:
            if args.get("email_confirmed") is True and s.email and self._email_read_back == s.email:
                s.email_confirmed = True
            elif args.get("email_confirmed") is False and s.step == "confirm_email":
                s.email, s.email_confirmed = None, False

        # Traveller count and mix. A changed count or mix means the total must be read again.
        mix_before = (s.child_count, s.mix_known)
        count_before = s.passenger_count or 0
        count_changed = False
        if isinstance(args.get("passenger_count"), int) and args["passenger_count"] > 0:
            new = min(9, args["passenger_count"])
            count_changed = new != s.passenger_count
            s.passenger_count = new
        elif isinstance(args.get("additional_passengers"), int) and args["additional_passengers"] > 0:
            s.passenger_count = min(9, (s.passenger_count or 1) + args["additional_passengers"])
            count_changed = True
        elif args.get("add_more_passengers") is True and not args.get("passenger_count"):
            s.count_confirmed = False
            return self._step_response("passenger_count", {"ask_say": "How many more people are travelling?"})
        if count_changed:
            s.count_confirmed = False
            s.details_confirmed = False
            if s.passenger_count == 1:
                s.child_count, s.mix_known, self._child_dobs = 0, True, []
            elif s.passenger_count > count_before and s.child_count == 0:
                s.mix_known = False  # the new travellers may be children
            for gone in [i for i in self._pending_name if i > s.passenger_count]:
                self._pending_name.pop(gone)
                self._name_read_back.pop(gone, None)
        # "dono adults hain" often arrives as a count confirmation while the mix question is open.
        if (args.get("passenger_count_confirmed") is True and s.step == "passenger_mix"
                and args.get("includes_children") is None and not args.get("child_count")):
            args["includes_children"] = False
            args.pop("passenger_count_confirmed")
        if args.get("includes_children") is False:
            s.child_count, s.mix_known, self._child_dobs = 0, True, []
        elif args.get("includes_children") is True:
            s.mix_known = True
            if not s.child_count:
                if isinstance(args.get("child_count"), int) and args["child_count"] > 0:
                    s.child_count = args["child_count"]
                else:
                    return self._step_response("child_count", {"ask_say": "How many children are travelling?"})
        if isinstance(args.get("child_count"), int) and args["child_count"] >= 0:
            s.child_count = min(args["child_count"], max(0, (s.passenger_count or 1) - 1))
            s.mix_known = True
            self._child_dobs = self._child_dobs[: s.child_count]
        mix_changed = (s.child_count, s.mix_known) != mix_before
        if mix_changed and s.passenger_count != 1:
            s.count_confirmed = False
        if args.get("date_of_birth") and s.step == "child_date_of_birth":
            dob = _parse_date(args["date_of_birth"])
            if not dob or dob > s.today:
                return self._step_response("child_date_of_birth", {"error": "date_of_birth must be a past date in YYYY-MM-DD.",
                                                                     "ask_say": "What is the child's date of birth?"})
            self._child_dobs.append(dob.isoformat())
        # At the total readback the model only moves on after the caller's yes: to names, or with
        # the yes sent as another confirmation flag. Never when this same call changed the count or mix.
        at_readback = s.step == "confirm_passenger_count" and not (count_changed or mix_changed)
        if at_readback and args.get("passenger_count_confirmed") is None:
            stray_yes = [k for k in ("details_confirmed", "phone_confirmed", "email_confirmed", "name_confirmed") if args.get(k) is True]
            if stray_yes or self._has_person_fields(args):
                args["passenger_count_confirmed"] = True
                for key in stray_yes:
                    args.pop(key)
        if args.get("passenger_count_confirmed") is True and at_readback:
            s.count_confirmed = True
        elif args.get("passenger_count_confirmed") is False and at_readback:
            return self._step_response("passenger_count", {"ask_say": "How many people are travelling, and how many of them are children?"})
        if s.passenger_count == 1:
            s.count_confirmed = True

        # Names, age, gender.
        saved = None
        if not s.count_confirmed and s.passenger_count and self._has_person_fields(args):
            saved = f"Saved passenger {self._person_index(args)}'s details; they are read back after this step."
        result = self._apply_traveller_fields(args)
        if result is not None:
            return result

        # WhatsApp number. At phone_choice a bare phone_confirmed true means "same" (the old bot looped
        # there). An explicit "same" counts at any step, including going back to the calling number.
        if args.get("phone_choice") == "same" or (
                s.step == "phone_choice" and args.get("phone_confirmed") is True and not args.get("phone_number")):
            if s.whatsapp != CALLING_NUMBER or not s.whatsapp_confirmed:
                s.whatsapp, s.whatsapp_confirmed, s.details_confirmed = CALLING_NUMBER, True, False
        elif args.get("phone_number"):
            phone = self._normalise_phone(args["phone_number"])
            if not phone:
                return self._step_response(s.step if s.step in ("phone_choice", "confirm_phone", "retry_traveller_whatsapp", "review_details") else "phone_choice", {
                    "error": "phone_number must be a 10-digit Indian mobile number.",
                    "ask_say": "Please tell me the 10-digit WhatsApp number again.",
                })
            s.whatsapp, s.whatsapp_confirmed = phone, False
            s.details_confirmed = False
        elif args.get("phone_choice") == "new" and s.step == "phone_choice":
            return self._step_response("phone_choice", {"ask_say": "Please tell me the WhatsApp number you want to use."})
        if args.get("phone_confirmed") is True and s.step == "confirm_phone" and s.whatsapp:
            s.whatsapp_confirmed = True
        elif args.get("phone_confirmed") is False and s.step == "confirm_phone":
            s.whatsapp, s.whatsapp_confirmed = None, False
            return self._step_response("phone_choice", {"ask_say": "Please tell me the correct WhatsApp number."})

        # Review on WhatsApp. The mock never delivers to a number ending 0000, so a retry fails
        # again; only the caller can change the number.
        retried = s.step == "retry_traveller_whatsapp" and args.get("retry_whatsapp") is True
        if args.get("details_confirmed") is True and s.step == "review_details":
            s.details_confirmed = True
        elif args.get("details_confirmed") is False and s.step == "review_details":
            touched = any(args.get(k) for k in ("first_name_letters", "last_name_letters", "age", "gender", "email", "phone_number"))
            if not touched:
                return self._step_response("review_details", {"ask_say": "Which detail should I correct?"})

        step, fields = self._next_open_step()
        if email_error and step in ("email", "confirm_email", "review_details", "complete"):
            return self._step_response("email", {"error": email_error, "ask_say": "Please tell me the email address again."})
        if step == "review_details" and s.step == "review_details" and not args.get("details_confirmed"):
            fields["heads_up"] = "I have sent the corrected details on WhatsApp."
        if step == "retry_traveller_whatsapp" and retried:
            fields.update(note_say="The WhatsApp message could not be delivered again.",
                          ask_say="Shall I use another number?")
        response = self._step_response(step, fields)
        if email_error:
            response["email_error"] = email_error
        if saved:
            # Live 3.8 treated a plain "ok" as licence to keep collecting names; say the step is still open.
            response.update(status="step_open", saved=saved,
                            instruction="First finish this step, then continue with the saved details. " + response["instruction"])
        return response

    def _has_person_fields(self, args: Dict[str, Any]) -> bool:
        return bool(args.get("first_name_letters") or args.get("last_name_letters") or args.get("age") is not None
                    or args.get("gender") or (args.get("date_of_birth") and self.state.step != "child_date_of_birth")
                    or args.get("name_confirmed") is not None)

    def _person_index(self, args: Dict[str, Any]) -> int:
        """The traveller these fields belong to: the one named, else the first incomplete one."""
        s = self.state
        while len(s.travellers) < s.passenger_count:
            s.travellers.append(Traveller())
        index = args.get("passenger_index") if isinstance(args.get("passenger_index"), int) else None
        if not index or not 1 <= index <= s.passenger_count:
            index = next((i for i, t in enumerate(s.travellers, start=1) if not t.complete()), 1)
        return index

    def _apply_traveller_fields(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        s = self.state
        if not s.passenger_count or not self._has_person_fields(args):
            return None
        # Before the count is confirmed, keep what the caller said but let the count step finish first;
        # _next_open_step reads the name back once it is.
        deferred = not s.count_confirmed
        has_name = bool(args.get("first_name_letters") or args.get("last_name_letters"))
        index = self._person_index(args)
        traveller = s.travellers[index - 1]
        if args.get("name_confirmed") is not None and not has_name and traveller.name_confirmed:
            # A bare yes/no with a stale index (the model repeats an earlier passenger_index):
            # it answers the one readback the caller just heard.
            awaiting = [i for i in self._name_read_back if i in self._pending_name and self._heard_name(i)]
            if len(awaiting) == 1:
                index = awaiting[0]
                traveller = s.travellers[index - 1]

        if args.get("age") is not None:
            try:
                age = int(args["age"])
                if 0 <= age <= 110:
                    if age != traveller.age and traveller.date_of_birth in self._child_dobs:
                        traveller.date_of_birth = None  # a count-step date matched the old age; match again
                    traveller.age = age
            except (TypeError, ValueError):
                pass
        if args.get("gender"):
            g = str(args["gender"]).strip().lower()
            traveller.gender = {"m": "male", "man": "male", "f": "female", "woman": "female", "purush": "male", "mahila": "female"}.get(g, g)
        if args.get("date_of_birth") and s.step != "child_date_of_birth":
            dob = _parse_date(args["date_of_birth"])
            if dob and dob <= s.today:
                traveller.date_of_birth = dob.isoformat()

        if traveller.age is not None and traveller.age <= 12 and not traveller.date_of_birth:
            remaining = list(self._child_dobs)  # dates given at the count step, not yet used
            for other in s.travellers:
                if other.date_of_birth in remaining:
                    remaining.remove(other.date_of_birth)
            # Only a date that fits the stated age; otherwise passenger_details asks for it.
            gaps = {d: abs(_age_on(dt.date.fromisoformat(d), s.today) - traveller.age) for d in remaining}
            fits = [d for d, gap in gaps.items() if gap <= 1]
            traveller.date_of_birth = min(fits, key=gaps.get) if fits else None

        if has_name:
            first = self._letters_to_name(args.get("first_name_letters"))
            last = self._letters_to_name(args.get("last_name_letters"))
            had_readback = self._heard_name(index)
            previous = self._pending_name.get(index) or Traveller(first_name=traveller.first_name, last_name=traveller.last_name)
            only = None
            if first and not last and previous.last_name and args.get("spelling_source") == "caller_spelled":
                only = "first"
            if last and not first and previous.first_name:
                only = "last"
            candidate = Traveller(first_name=first or previous.first_name, last_name=last or previous.last_name)
            changed = candidate.name != previous.name
            self._pending_name[index] = candidate
            traveller.name_confirmed = False
            s.details_confirmed = False
            # A yes counts only for the readback the caller just heard, resent unchanged.
            if args.get("name_confirmed") is True and args.get("spelling_source") != "caller_spelled" \
                    and had_readback and not changed:
                traveller.first_name, traveller.last_name = candidate.first_name, candidate.last_name
                traveller.name_confirmed = True
                self._pending_name.pop(index, None)
                return None
            if deferred:
                return None
            readback = self._name_readback(index, candidate, changed, only=only)
            if args.get("spelling_source") == "caller_spelled" and not changed:
                readback["spelling_changed"] = False
            return self._step_response("confirm_name", readback)

        if args.get("name_confirmed") is True and self._heard_name(index):
            pending = self._pending_name.pop(index)
            traveller.first_name, traveller.last_name = pending.first_name, pending.last_name
            traveller.name_confirmed = True
        elif args.get("name_confirmed") is False and not deferred:
            self._name_read_back.pop(index, None)  # rejected: a later yes needs a fresh readback
            pending = self._pending_name.get(index)
            return self._step_response("confirm_name", {
                "passenger_index": index,
                "ask_say": "Please say and spell the first name, then the surname, letter by letter.",
                "spelling_changed": False,
                "note_say": f"Let me correct the name for passenger {index}." if pending else "",
            })
        return None

    # -- PaymentTool ---------------------------------------------------------

    def payment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        s = self.state
        action = str(args.get("action") or "").upper()
        if action == "INFORMATION":
            return self._respond({
                "status": "ok",
                "facts": "You can pay by UPI, debit or credit card, or net banking. The link stays valid for 30 minutes, and the ticket is issued on WhatsApp and email right after payment.",
                "instruction": "Answer the payment question from facts in one or two lines.",
                "data": {"step": s.step},
                "next": self._current_next,
            }, informational=True)
        if action not in ("PROCEED", "REVIEW"):
            return self._error("action must be PROCEED, REVIEW or INFORMATION.", "Call PaymentTool again with an action.")
        if s.step not in ("complete", "payment_sent"):
            return self._error("Traveller and contact details are not complete yet.",
                               "Continue the current step with TravellerDetailsTool.", next=self._current_next)
        if action == "REVIEW":
            return self._respond({
                "status": "ok",
                "facts": f"Total {rupees(s.total_fare())} for {s.party_say()}.",
                "instruction": "Say facts, then ask whether to send the payment link.",
                "data": {"step": s.step},
                "next": [{"when": "The caller agrees", "tool": "PaymentTool", "arguments": {"action": "PROCEED"}}],
            }, informational=True)
        already = self._payment_link_sent
        if not already:
            digest = hashlib.md5(f"{s.outbound.flight_number}{s.whatsapp}{s.total_fare()}".encode()).hexdigest()
            s.booking_ref = "BMT" + str(int(digest[:8], 16) % 10_000_000).zfill(7)
            self._payment_link_sent = True
        self._set_step("payment_sent")
        s.total_told = s.total_fare()
        return self._respond({
            "status": "link_sent" if not already else "already_sent",
            "heads_up": f"I have sent the payment link for {rupees(s.total_fare())} on WhatsApp to the number ending {s.whatsapp[-4:]}, and to your email.",
            "instruction": STEP_INSTRUCTIONS["payment_sent"],
            "data": {"step": "payment_sent", "booking_ref": s.booking_ref, "amount_say": rupees(s.total_fare()),
                     "booking_status": "pending payment"},
            "next": [{"when": "The caller asks about payment", "tool": "PaymentTool", "arguments": {"action": "INFORMATION"}}],
        }, card=8)

    # -- telemetry -----------------------------------------------------------

    def slots(self) -> Dict[str, Any]:
        """Compact state for the Voice Studio UI (``call_state`` events)."""
        snap = self.state.snapshot()
        return {k: v for k, v in snap.items() if v and k not in ("agent_name", "language_style", "trip_type")} | (
            {"booking_ref": self.state.booking_ref} if self.state.booking_ref else {})
