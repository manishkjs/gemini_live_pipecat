"""Tools and mock execution engine for Kavya (Glass Buddy - Cymbal Smartglasses).

Implements the full 14-tool surface from ajna_v25 with deterministic mock
execution, realistic responses, and RTVI event broadcasting.
100% Cymbal Smartglasses; zero third-party branding.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional
from google.genai import types


# ---------------------------------------------------------------------------
# Tool Schemas
# ---------------------------------------------------------------------------

make_call_schema = types.FunctionDeclaration(
    name="make_call",
    description="Place a phone call to a named contact or phone number through Cymbal Smartglasses.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "contact_name": types.Schema(
                type=types.Type.STRING,
                description="The name of the contact to call from the phone book (e.g., 'Rohan', 'Priya').",
            ),
            "phone_number": types.Schema(
                type=types.Type.STRING,
                description="Spoken phone number with country code, if given directly.",
            ),
        },
    ),
)

start_live_ai_schema = types.FunctionDeclaration(
    name="start_live_ai",
    description="Activate the real-time Live AI multimodal vision stream on Cymbal Smartglasses on explicit command.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={},
    ),
)

take_photo_schema = types.FunctionDeclaration(
    name="take_photo",
    description="Capture a high-resolution photograph using the built-in Cymbal Smartglasses camera.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={},
    ),
)

start_video_schema = types.FunctionDeclaration(
    name="start_video",
    description="Begin recording a video clip through the Cymbal Smartglasses camera.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={},
    ),
)

meeting_mode_schema = types.FunctionDeclaration(
    name="meeting_mode",
    description="Start or stop meeting recording mode to transcribe an in-person conversation or meeting.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "action": types.Schema(
                type=types.Type.STRING,
                description="Action: 'start' to begin recording, 'stop' to finish.",
            ),
        },
    ),
)

route_hardware_directive_schema = types.FunctionDeclaration(
    name="route_hardware_directive",
    description="Inspect user surroundings by commanding the smartglasses camera when the user asks a visual question.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "directive": types.Schema(
                type=types.Type.STRING,
                description="The visual inspection query, e.g. 'inspect_view', 'what_am_i_looking_at'.",
            ),
        },
        required=["directive"],
    ),
)

log_my_meal_schema = types.FunctionDeclaration(
    name="log_my_meal",
    description="Log a meal into Cymbal Health for daily nutrition and calorie tracking.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "meal_description": types.Schema(
                type=types.Type.STRING,
                description="Description of the food or meal being logged, e.g. 'two rotis with dal and paneer'.",
            ),
        },
    ),
)

stop_b_schema = types.FunctionDeclaration(
    name="stop_b",
    description="Stop active smartglasses background processes, recording sessions, or video capture immediately.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={},
    ),
)

set_reminder_schema = types.FunctionDeclaration(
    name="set_reminder",
    description="Schedule a voice reminder with a title and specific time.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(
                type=types.Type.STRING,
                description="The task or event to be reminded of.",
            ),
            "remind_at": types.Schema(
                type=types.Type.STRING,
                description="The target date or time for the reminder, e.g. '5:30 PM today', 'tomorrow at 9 AM'.",
            ),
        },
        required=["title"],
    ),
)

get_health_data_schema = types.FunctionDeclaration(
    name="get_health_data",
    description="Fetch current fitness and health statistics (steps, heart rate, sleep duration) from Cymbal Health.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "metric": types.Schema(
                type=types.Type.STRING,
                description="Metric to query: 'steps', 'heart_rate', 'sleep', 'all'. Default is 'all'.",
            ),
        },
    ),
)

get_calendar_events_schema = types.FunctionDeclaration(
    name="get_calendar_events",
    description="Read scheduled calendar appointments and events for today or an upcoming window (read-only).",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "window": types.Schema(
                type=types.Type.STRING,
                description="Window: 'today', 'tomorrow', 'this_week', or 'on_date'.",
            ),
            "date": types.Schema(
                type=types.Type.STRING,
                description="Specific date formatted as YYYY-MM-DD if asking about a particular day.",
            ),
        },
    ),
)

get_nutrition_schema = types.FunctionDeclaration(
    name="get_nutrition",
    description="Look up estimated nutritional value, macronutrients, and calories for a given food or drink.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query": types.Schema(
                type=types.Type.STRING,
                description="The food item to analyze, e.g. 'masala dosa', 'apple', 'black coffee'.",
            ),
        },
        required=["query"],
    ),
)

recall_memory_schema = types.FunctionDeclaration(
    name="recall_memory",
    description="Search personal facts, dietary restrictions, and preferences remembered from prior conversations.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query": types.Schema(
                type=types.Type.STRING,
                description="Search query in English for remembered facts, e.g. 'peanut allergy, food restrictions'.",
            ),
        },
        required=["query"],
    ),
)

input_required_schema = types.FunctionDeclaration(
    name="input_required",
    description="Confirm or submit user authorization/input for a pending smartglasses action.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "for_tool": types.Schema(type=types.Type.STRING, description="The tool awaiting confirmation."),
            "key": types.Schema(type=types.Type.STRING, description="The confirmation key, e.g. 'consent_given'."),
            "outcome": types.Schema(type=types.Type.STRING, description="User decision: 'confirmed' or 'declined'."),
            "value": types.Schema(type=types.Type.STRING, description="Optional text or choice provided by the user."),
        },
        required=["for_tool", "outcome"],
    ),
)

switch_phase_schema = types.FunctionDeclaration(
    name="switch_phase",
    description=(
        "Transition the active smartglasses companion phase. Allowed phases: "
        "'SOP_01_COMPANION_READY', 'SOP_02_VISION_CAPTURE', 'SOP_03_DAILY_ASSISTANT', 'SOP_04_HEALTH_WELLNESS'."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "phase_id": types.Schema(type=types.Type.STRING, description="Target phase identifier."),
        },
        required=["phase_id"],
    ),
)


ALL_GLASS_BUDDY_TOOL_SCHEMAS: List[types.FunctionDeclaration] = [
    make_call_schema,
    start_live_ai_schema,
    take_photo_schema,
    start_video_schema,
    meeting_mode_schema,
    route_hardware_directive_schema,
    log_my_meal_schema,
    stop_b_schema,
    set_reminder_schema,
    get_health_data_schema,
    get_calendar_events_schema,
    get_nutrition_schema,
    recall_memory_schema,
    input_required_schema,
]


# ---------------------------------------------------------------------------
# Mock Execution Engine
# ---------------------------------------------------------------------------

class GlassBuddyExecutionEngine:
    """Deterministic mock execution engine for all 14 Cymbal Glass Buddy tools."""

    def __init__(self, broadcast: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self._broadcast = broadcast
        self.active_phase = "SOP_01_COMPANION_READY"
        self._lock = asyncio.Lock()

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        if self._broadcast:
            try:
                self._broadcast({
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        "persona": "kavya_glass_buddy",
                        "event": event_type,
                        **data,
                    },
                })
            except Exception:
                pass

    async def make_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        contact = params.get("contact_name") or "Contact"
        number = params.get("phone_number") or "+91-9876543210"
        result = {
            "status": "calling",
            "contact_name": contact,
            "phone_number": number,
            "message": f"Calling {contact} now via Cymbal Smartglasses...",
        }
        self._emit("call_placed", result)
        return result

    async def start_live_ai(self, params: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "status": "active",
            "message": "Live AI multimodal vision stream activated on Cymbal Smartglasses.",
        }
        self._emit("live_ai_started", result)
        return result

    async def take_photo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "status": "captured",
            "photo_id": "cymbal_img_8492.jpg",
            "resolution": "4K Ultra-Wide",
            "message": "Photo captured and saved to your Cymbal gallery.",
        }
        self._emit("photo_captured", result)
        return result

    async def start_video(self, params: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "status": "recording",
            "video_id": "cymbal_vid_1024.mp4",
            "message": "Video recording started on Cymbal Smartglasses.",
        }
        self._emit("video_started", result)
        return result

    async def meeting_mode(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = params.get("action", "start")
        result = {
            "status": "recording" if action == "start" else "stopped",
            "action": action,
            "message": f"Meeting mode {action}ed on Cymbal Smartglasses. Audio transcription active.",
        }
        self._emit("meeting_mode_updated", result)
        return result

    async def route_hardware_directive(self, params: Dict[str, Any]) -> Dict[str, Any]:
        directive = params.get("directive", "inspect_surroundings")
        result = {
            "status": "success",
            "directive": directive,
            "visual_description": "You are looking at a modern workspace desk with dual monitors, a laptop, and a notebook.",
            "message": "View inspected through smartglasses camera.",
        }
        self._emit("hardware_directive_executed", result)
        return result

    async def log_my_meal(self, params: Dict[str, Any]) -> Dict[str, Any]:
        meal = params.get("dish_name") or params.get("meal_description") or "Balanced Indian meal"
        result = {
            "status": "logged",
            "meal": meal,
            "estimated_calories": params.get("calories", 450),
            "protein": "24g",
            "carbs": "52g",
            "message": f"Meal '{meal}' successfully logged in Cymbal Health.",
        }
        self._emit("meal_logged", result)
        return result

    async def stop_b(self, params: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "status": "stopped",
            "message": "All active background tasks and recordings stopped.",
        }
        self._emit("tasks_stopped", result)
        return result

    async def set_reminder(self, params: Dict[str, Any]) -> Dict[str, Any]:
        title = params.get("title", "Important Task")
        remind_at = params.get("remind_at", "in 1 hour")
        result = {
            "status": "success",
            "reminder_id": "cymbal_rem_4821",
            "title": title,
            "remind_at": remind_at,
            "message": f"Reminder set for '{title}' at {remind_at}.",
        }
        self._emit("reminder_set", result)
        return result

    async def get_health_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        metric = params.get("metric", "all")
        result = {
            "status": "success",
            "metric": metric,
            "steps": 7450,
            "step_goal": 10000,
            "heart_rate_bpm": 72,
            "sleep_duration": "7 hours 20 mins",
            "glasses_battery": "84%",
        }
        self._emit("health_data_fetched", result)
        return result

    async def get_calendar_events(self, params: Dict[str, Any]) -> Dict[str, Any]:
        window = params.get("window", "today")
        result = {
            "status": "success",
            "window": window,
            "events": [
                {"title": "Product Architecture Sync", "time": "3:00 PM - 3:30 PM", "location": "Google Meet"},
                {"title": "Evening Walk & Workout", "time": "6:30 PM - 7:15 PM", "location": "Neighbourhood Park"},
            ],
            "message": "Calendar is read-only. Displaying today's scheduled meetings.",
        }
        self._emit("calendar_events_fetched", result)
        return result

    async def get_nutrition(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query", "food item")
        result = {
            "status": "success",
            "query": query,
            "calories": 280,
            "protein": "8g",
            "carbs": "36g",
            "fat": "6g",
            "summary": f"{query} is a healthy choice with moderate calories and balanced nutrients.",
        }
        self._emit("nutrition_analyzed", result)
        return result

    async def recall_memory(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query", "")
        result = {
            "status": "success",
            "query": query,
            "data": [
                "User is allergic to peanuts and strictly avoids peanut butter.",
                "User prefers morning reminders at 8:30 AM on weekdays.",
                "User works as a software engineer in Bengaluru.",
            ],
        }
        self._emit("memory_recalled", result)
        return result

    async def input_required(self, params: Dict[str, Any]) -> Dict[str, Any]:
        for_tool = params.get("for_tool", "make_call")
        outcome = params.get("outcome", "confirmed")
        result = {
            "status": "confirmed",
            "for_tool": for_tool,
            "outcome": outcome,
            "message": f"Action for {for_tool} confirmed.",
        }
        self._emit("input_confirmed", result)
        return result
