"""Lamborghini Experience Lounge lookup, appointment booking, and Phase Card tool schemas.

Provides deterministic tool execution for Pragya's Lamborghini VIP outbound sales concierge:
1. `get_phase_card`: Fetches modular JIT SOP phase cards (SOP 01-06).
2. `get_exp_center`: Looks up authorized Lamborghini lounges by city or pincode.
3. `create_appointment_booking`: Books 15-minute VIP Lounge private viewings / test drives.
"""

from __future__ import annotations

import re
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

create_appointment_booking_schema = FunctionSchema(
    name="create_appointment_booking",
    description="Book an exclusive VIP Lounge private viewing or test drive appointment based on the client's 6-digit PIN code or city.",
    properties={
        "pincode": {
            "type": "string",
            "description": "The customer's 6-digit postal PIN code (e.g. '110037', '400051', '560001') or city ('Delhi', 'Mumbai', 'Bengaluru').",
        },
        "date": {
            "type": "string",
            "description": "The scheduled date (e.g. 'Tomorrow', 'Saturday, 14th September').",
        },
        "time": {
            "type": "string",
            "description": "The scheduled time slot (e.g. '11:00 AM', '3:30 PM').",
        },
        "vehicle_variant": {
            "type": "string",
            "description": "The Lamborghini model chosen (e.g. 'Revuelto', 'Urus SE', 'Temerario').",
        },
        "customer_name_or_phone": {
            "type": "string",
            "description": "Customer contact number or name if provided.",
        },
    },
    required=["pincode", "date", "time"],
)

get_phase_card_schema = FunctionSchema(
    name="get_phase_card",
    description="Retrieve active SOP conversational instructions and boundaries for a specific phase.",
    properties={
        "phase": {
            "type": "string",
            "description": "Target phase name.",
        },
    },
    required=["phase"],
)

get_exp_center_schema = FunctionSchema(
    name="get_exp_center",
    description="Look up nearest Lamborghini Experience Lounges by city name or 6-digit Indian pincode.",
    properties={
        "city_or_pincode": {
            "type": "string",
            "description": "City or 6-digit pincode.",
        },
    },
    required=["city_or_pincode"],
)

SUPERCAR_TOOL_SCHEMAS: List[FunctionSchema] = [
    create_appointment_booking_schema,
]
