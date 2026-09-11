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
        "models_available": ["Lamborghini Gallardo", "Lamborghini Aventador", "Lamborghini Urus"],
    },
    "LAMBO_DEL_AERO": {
        "center_id": "LAMBO_DEL_AERO",
        "name": "Lamborghini New Delhi Lounge (Aerocity)",
        "city": "New Delhi",
        "address": "Asset 5A, Worldmark 2, Delhi Aerocity, New Delhi 110037",
        "phone": "+91 11 4567 0000",
        "models_available": ["Lamborghini Gallardo", "Lamborghini Aventador", "Lamborghini Urus"],
    },
    "LAMBO_BLR_LAV": {
        "center_id": "LAMBO_BLR_LAV",
        "name": "Lamborghini Bengaluru Experience Lounge",
        "city": "Bengaluru",
        "address": "10/1, Ground Floor, Lavelle Heights, Lavelle Road, Bengaluru 560001",
        "phone": "+91 80 4321 0000",
        "models_available": ["Lamborghini Gallardo", "Lamborghini Aventador", "Lamborghini Urus"],
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
    center_id: str,
    date: str,
    time: str,
    customer_phone: str = "",
    vehicle_variant: str = "Lamborghini Aventador",
) -> Dict[str, Any]:
    """Create a confirmed 15-minute VIP Lounge appointment and return confirmation details."""
    center = LAMBORGHINI_CENTERS.get(center_id)
    if not center:
        center = LAMBORGHINI_CENTERS["LAMBO_MUM_BKC"]

    booking_id = f"LAMBO-{uuid.uuid4().hex[:6].upper()}"
    return {
        "status": "confirmed",
        "booking_id": booking_id,
        "center_id": center["center_id"],
        "center_name": center["name"],
        "address": center["address"],
        "date": date,
        "time": time,
        "vehicle_variant": vehicle_variant or "Lamborghini Aventador",
        "customer_phone": customer_phone or "Verified Caller",
        "confirmation_message": (
            f"VIP Lounge Viewing successfully confirmed! Booking ID: {booking_id}. "
            f"Showroom: {center['name']}. Schedule: {date} at {time}. Vehicle: {vehicle_variant}."
        ),
    }


# ---------------------------------------------------------------------------
# Tool Schemas for Gemini Live / Pipecat
# ---------------------------------------------------------------------------

get_phase_card_schema = FunctionSchema(
    name="get_phase_card",
    description=(
        "Retrieve active SOP conversational instructions and boundaries for a specific phase "
        "(e.g., 'discovery', 'pricing', 'booking', 'service_override', 'objections'). "
        "Allows non-linear jumping between phases at any turn based on customer response."
    ),
    properties={
        "phase": {
            "type": "string",
            "description": (
                "The target phase name to load: 'discovery' (SOP 02: Gallardo/Aventador/Urus models), "
                "'pricing' (SOP 03: costs/Ad Personam), 'booking' (SOP 04: VIP Atelier visit/test drive), "
                "'service_override' (SOP 05: breakdown/complaints/repairs - HIGHEST PRIORITY), "
                "or 'objections' (SOP 06: speed breakers/front-lift/busy/exit)."
            ),
        },
        "reason": {
            "type": "string",
            "description": "Brief conversational reason for loading this phase card (e.g. 'caller asked about Aventador V12 price').",
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
            "description": "The customer's city name (e.g. 'Mumbai', 'Delhi', 'Bengaluru') or 6-digit pincode.",
        },
    },
    required=["city_or_pincode"],
)

create_appointment_booking_schema = FunctionSchema(
    name="create_appointment_booking",
    description="Silently book an exclusive 15-minute VIP Lounge private viewing or test drive appointment.",
    properties={
        "center_id": {
            "type": "string",
            "description": "The unique center ID (e.g. 'LAMBO_MUM_BKC', 'LAMBO_DEL_AERO', 'LAMBO_BLR_LAV').",
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
            "description": "The Lamborghini model chosen (e.g. 'Lamborghini Aventador', 'Lamborghini Gallardo', 'Lamborghini Urus').",
        },
        "customer_phone": {
            "type": "string",
            "description": "Customer contact number if provided.",
        },
    },
    required=["center_id", "date", "time"],
)

SUPERCAR_TOOL_SCHEMAS: List[FunctionSchema] = [
    get_phase_card_schema,
    get_exp_center_schema,
    create_appointment_booking_schema,
]
