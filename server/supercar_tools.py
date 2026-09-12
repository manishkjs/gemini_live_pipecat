"""Pragya phase-switch tools and the existing in-memory demo booking backend."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pipecat.adapters.schemas.function_schema import FunctionSchema


LAMBORGHINI_CENTERS: Dict[str, Dict[str, Any]] = {
    "LAMBO_MUM_BKC": {
        "center_id": "LAMBO_MUM_BKC",
        "name": "Lamborghini Mumbai Atelier (BKC)",
        "city": "Mumbai",
        "address": "Maker Maxity, 3 North Avenue, Bandra Kurla Complex (BKC), Mumbai 400051",
        "phone": "+91 22 6789 0000",
        "models_available": ["Lamborghini Revuelto", "Lamborghini Urus SE", "Lamborghini Temerario"],
    },
    "LAMBO_DEL_AERO": {
        "center_id": "LAMBO_DEL_AERO",
        "name": "Lamborghini New Delhi Lounge (Aerocity)",
        "city": "New Delhi",
        "address": "Asset 5A, Worldmark 2, Delhi Aerocity, New Delhi 110037",
        "phone": "+91 11 4567 0000",
        "models_available": ["Lamborghini Revuelto", "Lamborghini Urus SE", "Lamborghini Temerario"],
    },
    "LAMBO_BLR_LAV": {
        "center_id": "LAMBO_BLR_LAV",
        "name": "Lamborghini Bengaluru Experience Lounge",
        "city": "Bengaluru",
        "address": "10/1, Ground Floor, Lavelle Heights, Lavelle Road, Bengaluru 560001",
        "phone": "+91 80 4321 0000",
        "models_available": ["Lamborghini Revuelto", "Lamborghini Urus SE", "Lamborghini Temerario"],
    },
}


def get_exp_center(city_or_pincode: str) -> Dict[str, Any]:
    """Look up the nearest authorized Lamborghini Lounge by city name or 6-digit postal code."""
    query = (city_or_pincode or "").strip().lower()
    
    # Check Mumbai
    if any(k in query for k in ["mumbai", "bombay", "bkc", "bandra", "thane", "pune"]) or query.startswith("400"):
        return {"centers": [LAMBORGHINI_CENTERS["LAMBO_MUM_BKC"]], "is_fallback": False}

    # Check Delhi NCR
    if any(k in query for k in ["delhi", "new delhi", "noida", "gurgaon", "gurugram", "aerocity", "faridabad"]) or query.startswith("110"):
        return {"centers": [LAMBORGHINI_CENTERS["LAMBO_DEL_AERO"]], "is_fallback": False}

    # Check Bengaluru / Karnataka
    if any(k in query for k in ["bengaluru", "bangalore", "lavelle", "whitefield", "koramangala", "indiranagar"]) or query.startswith("560"):
        return {"centers": [LAMBORGHINI_CENTERS["LAMBO_BLR_LAV"]], "is_fallback": False}

    # Fallback: return all 3 flagship lounges for caller selection
    return {
        "centers": list(LAMBORGHINI_CENTERS.values()),
        "is_fallback": True,
        "message": "We currently operate flagship Lounges in Mumbai, New Delhi, and Bengaluru. Please select your preferred lounge.",
    }


def create_appointment_booking(
    pincode: str = "",
    date: str = "Tomorrow",
    time: str = "11:00 AM",
    customer_phone: str = "",
    customer_name_or_phone: str = "",
    vehicle_variant: str = "Lamborghini Revuelto",
    center_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a confirmed 15-minute VIP Lounge appointment and return confirmation details."""
    center = None
    if center_id and center_id in LAMBORGHINI_CENTERS:
        center = LAMBORGHINI_CENTERS[center_id]
    else:
        lookup_query = pincode or "Delhi"
        resolved = get_exp_center(lookup_query)
        centers = resolved.get("centers", [])
        center = centers[0] if centers else LAMBORGHINI_CENTERS["LAMBO_DEL_AERO"]

    booking_id = f"LAMBO-{uuid.uuid4().hex[:6].upper()}"
    cust = customer_name_or_phone or customer_phone or "Verified Caller"
    return {
        "status": "confirmed",
        "booking_id": booking_id,
        "center_id": center["center_id"],
        "center_name": center["name"],
        "city": center["city"],
        "address": center["address"],
        "date": date,
        "time": time,
        "vehicle_variant": vehicle_variant or "Lamborghini Revuelto",
        "customer_phone": cust,
        "confirmation_message": (
            f"VIP Lounge Viewing successfully confirmed! Booking ID: {booking_id}. "
            f"Showroom: {center['name']} ({center['city']}). "
            f"Address: {center['address']}. Schedule: {date} at {time}. Vehicle: {vehicle_variant}."
        ),
    }


# ---------------------------------------------------------------------------
# Tool Schemas for Gemini Live / Pipecat
# ---------------------------------------------------------------------------

# Gemini normalizes speech into these formats; the server never parses speech.
_BOOKING_FIELDS = {
    "pincode": {"type": "string", "description": "Six ASCII digits, e.g. 560048. Convert spoken digits; omit if unknown."},
    "date": {"type": "string", "description": "Caller-chosen day: YYYY-MM-DD, Today, Tomorrow, Day after tomorrow, or an English weekday. Clarify ambiguous dates."},
    "time": {"type": "string", "description": "Caller-chosen time in India: HH:MM (24-hour) or h:mm AM/PM. Clarify vague times."},
    "vehicle_variant": {"type": "string", "description": "Optional caller-selected car, or undecided. Omit if not discussed."},
}

switch_phase_schema = FunctionSchema(
    name="switch_phase",
    description=(
        "Select the conversation's current phase and load its context before replying. "
        "Discovery for car discussion, Lounge Visit for arranging a visit, Booked only after "
        "a successful booking. Change phase when the conversation changes, not every turn. "
        "Include any known booking details from the caller; omit unknown fields."
    ),
    properties={
        "phase_id": {
            "type": "string",
            "enum": ["SOP_02_DISCOVERY", "SOP_03_PINCODE", "SOP_04_BOOKED"],
            "description": "The phase to use now.",
        },
        **_BOOKING_FIELDS,
    },
    required=["phase_id"],
)

create_appointment_booking_schema = FunctionSchema(
    name="create_appointment_booking",
    description=(
        "Create a demo lounge booking after the caller confirms PIN, day and time. "
        "Use only details the caller supplied. On success, switch_phase to SOP_04_BOOKED."
    ),
    properties={
        **_BOOKING_FIELDS,
        "customer_name_or_phone": {
            "type": "string",
            "description": "Customer contact or name, only if supplied.",
        },
    },
    required=["pincode", "date", "time"],
)

SUPERCAR_TOOL_SCHEMAS: List[FunctionSchema] = [
    switch_phase_schema,
    create_appointment_booking_schema,
]
