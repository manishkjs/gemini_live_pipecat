"""Tools and mock execution engine for Kavya / Buddy (Cymbal Kart Smartglasses).

Implements the complete 15-tool surface (`make_call`, `start_live_ai`, `take_photo`,
`start_video`, `meeting_mode`, `route_hardware_directive`, `log_my_meal`, `stop_b`,
`set_reminder`, `get_health_data`, `get_calendar_events`, `get_nutrition`,
`recall_memory`, `plan_my_meal`, `input_required`) from the AI Companion specification:
- 100% Cymbal Kart Smartglasses branding.
- Includes the 15th tool `plan_my_meal` (personalized daily calorie/macro budget + Indian dish planner).
- Embeds Post-History Footer (`_AUDIO_LANGUAGE_MIRROR_DIRECTIVE`, Slide 17 pattern) in every
  ToolResult `note` and avoids the `"logged"` -> `"globbed"` phonetic trap (`b/550021593`).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional
from google.genai import types


# Post-history ToolResult recency anchor (Slide 17 Custom Footer equivalent)
_AUDIO_LANGUAGE_MIRROR_DIRECTIVE = (
    " [AUDIO & LANGUAGE FOOTER: Respond in the EXACT language of the user's latest turn "
    "(English -> English, Hindi -> Hindi, Hinglish -> Hinglish) with a natural Indian accent "
    "and crisp sentence-final pronunciation.]"
)


# ---------------------------------------------------------------------------
# Tool Schemas (All 15 Cymbal Kart Smartglasses Tools)
# ---------------------------------------------------------------------------

make_call_schema = types.FunctionDeclaration(
    name="make_call",
    description=(
        "Place a phone call to a contact or phone number via the paired smartphone on Cymbal Kart Smartglasses.\n"
        "WHEN TO USE: User explicitly asks to call / dial / ring someone ('call Mom', 'Rohan ko phone lagao', "
        "'dial 9876543210'). Pass `contact_name` if a name/relationship was spoken, or `phone_number` if digits "
        "were given; if neither was specified ('make a call'), call with neither and the tool will prompt for who "
        "to call via `needs_input`.\n"
        "RETURNS: `{status: 'calling'|'success'|'needs_input', data: {contact_name, phone_number, call_state}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
            "contact_name": types.Schema(
                type=types.Type.STRING,
                description="Name or relationship of the person to call as spoken by the user (e.g. 'Mom', 'Rohan Sharma').",
            ),
            "phone_number": types.Schema(
                type=types.Type.STRING,
                description="Explicit phone number in digits (with optional '+' country code) when the user dictates a number.",
            ),
        },
    ),
)

start_live_ai_schema = types.FunctionDeclaration(
    name="start_live_ai",
    description=(
        "Start a continuous real-time vision + voice ('Live AI') session streaming the Cymbal Kart smartglasses camera.\n"
        "WHEN TO USE: ONLY when the user explicitly asks to start Live AI or wants open-ended, multi-turn continuous "
        "visual guidance ('start Live AI', 'turn on live vision', 'watch with me while I cook').\n"
        "WHEN NOT TO USE: Do NOT use for one-off 'what am I looking at?' / 'read this' questions — use "
        "`route_hardware_directive` instead. Privacy-sensitive: requires user consent.\n"
        "RETURNS: `{status: 'active'|'success'|'needs_input', data: {session_state}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
        },
    ),
)

take_photo_schema = types.FunctionDeclaration(
    name="take_photo",
    description=(
        "Capture a still photo with the Cymbal Kart smartglasses camera and save it to the user's gallery.\n"
        "WHEN TO USE: User explicitly asks to take/click/snap/save a picture ('take a photo', 'click a picture', "
        "'photo kheencho').\n"
        "WHEN NOT TO USE: Do NOT use when the user wants to know what's in front of them ('what is this?', "
        "'read this sign') — use `route_hardware_directive`. Do NOT use before `log_my_meal`.\n"
        "RETURNS: `{status: 'captured'|'success'|'needs_input', data: {photo_id, saved_to_gallery}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
        },
    ),
)

start_video_schema = types.FunctionDeclaration(
    name="start_video",
    description=(
        "Start or stop recording a video clip on the Cymbal Kart smartglasses camera.\n"
        "WHEN TO USE: User explicitly asks to record/shoot a video clip or to stop an ongoing video recording "
        "('record a video', 'start video', 'stop recording video').\n"
        "WHEN NOT TO USE: Do NOT use for recording meetings/conversations for notes — use `meeting_mode`.\n"
        "RETURNS: `{status: 'recording'|'success'|'needs_input', data: {recording, video_id}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
        },
    ),
)

meeting_mode_schema = types.FunctionDeclaration(
    name="meeting_mode",
    description=(
        "Control Cymbal Kart smartglasses Meeting Mode to record, transcribe, and summarize a meeting or conversation.\n"
        "WHEN TO USE:\n"
        "• `action='start'` — user asks to start recording/transcribing a meeting, lecture, or discussion.\n"
        "• `action='stop'` — user asks to stop/end the meeting recording and generate the summary/action items.\n"
        "RETURNS: `{status: 'recording'|'stopped'|'needs_input', data: {meeting_active, summary}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
            "action": types.Schema(
                type=types.Type.STRING,
                description="Whether to 'start' a new meeting recording or 'stop' the currently active one.",
            ),
        },
    ),
)

route_hardware_directive_schema = types.FunctionDeclaration(
    name="route_hardware_directive",
    description=(
        "Capture a live frame from the Cymbal Kart smartglasses camera and analyze what the user is currently looking at.\n"
        "WHEN TO USE: Any question that requires SEEING the user's environment right now — 'what am I looking at?', "
        "'read this menu/sign/label', 'translate what's written here', 'how much does this cost?', 'does this outfit match?'\n"
        "WHEN NOT TO USE: Do NOT use just to save a photo to gallery (`take_photo`), for continuous streaming (`start_live_ai`), "
        "or for saving food (`log_my_meal`).\n"
        "RETURNS: `{status: 'success', data: {scene_description, detected_text}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact visual question in their own words.",
            ),
            "directive": types.Schema(
                type=types.Type.STRING,
                description="Optional visual inspection directive (e.g. 'inspect_view', 'read_text').",
            ),
        },
    ),
)

log_my_meal_schema = types.FunctionDeclaration(
    name="log_my_meal",
    description=(
        "Save a meal or food item to the user's daily Cymbal Kart nutrition diary (capturing the plate via the "
        "smartglasses camera and/or spoken description).\n"
        "WHEN TO USE: User asks to save, record, or track food they ate or are looking at ('log my meal', "
        "'save my breakfast', 'I had 2 idlis and sambar, add it', 'ye plate save karo'). Call directly — do NOT call "
        "`take_photo` first and do NOT ask the user to describe the plate before calling.\n"
        "PHONETIC NOTE: When confirming completion to the user, say 'Meal saved' or 'Added to your food diary' rather "
        "than the word 'logged' to guarantee crystal-clear audio synthesis.\n"
        "RETURNS: `{status: 'logged'|'success'|'needs_input', data: {meal, calories_kcal, protein_g, carbs_g, fat_g}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
            "meal_description": types.Schema(
                type=types.Type.STRING,
                description="Food items and quantities if the user already mentioned them in speech (e.g. '2 idlis and 1 cup sambar').",
            ),
            "dish_name": types.Schema(
                type=types.Type.STRING,
                description="Optional dish name if explicitly named by the user.",
            ),
        },
    ),
)

stop_b_schema = types.FunctionDeclaration(
    name="stop_b",
    description=(
        "End the current Cymbal Kart voice assistant session and put Buddy back to standby.\n"
        "WHEN TO USE: User says goodbye or tells the assistant to stop/dismiss/sleep ('stop', 'bye Buddy', "
        "'that's all, thanks', 'bas band karo').\n"
        "WHEN NOT TO USE: If a video recording (`start_video`) or meeting recording (`meeting_mode`) is currently "
        "running and the user says 'stop recording' / 'end meeting', stop that specific recording tool instead.\n"
        "RETURNS: `{status: 'stopped'|'success', data: {session_closed: true}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
        },
    ),
)

set_reminder_schema = types.FunctionDeclaration(
    name="set_reminder",
    description=(
        "Create a reminder or to-do task in the user's Cymbal Kart app.\n"
        "WHEN TO USE: User asks to be reminded of something or to save a to-do ('remind me to take medicine at 9 PM', "
        "'kal subah 8 baje dentist ka reminder laga do', 'add buy milk to my tasks').\n"
        "RETURNS: `{status: 'success'|'needs_input', data: {reminder_id, title, remind_at}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
            "title": types.Schema(
                type=types.Type.STRING,
                description="Short actionable title of what to remind the user about (e.g. 'Take medicine', 'Call CA').",
            ),
            "description": types.Schema(
                type=types.Type.STRING,
                description="Optional extra context mentioned by the user.",
            ),
            "remind_at": types.Schema(
                type=types.Type.STRING,
                description="Target date/time in ISO-8601 ('YYYY-MM-DDTHH:MM:SS') or natural time phrase ('5:30 PM today').",
            ),
            "no_time": types.Schema(
                type=types.Type.BOOLEAN,
                description="Set `True` ONLY when the user explicitly wants an untimed to-do item.",
            ),
        },
    ),
)

get_health_data_schema = types.FunctionDeclaration(
    name="get_health_data",
    description=(
        "Read activity, vitals, sleep, and workout metrics from the user's Cymbal Kart Smartglasses & connected health sensors.\n"
        "WHEN TO USE: User asks about steps, distance, calories burned, active minutes, heart rate, SpO2, sleep duration/score, "
        "hydration, weight, or workout sessions.\n"
        "PARAMETERS:\n"
        "• `fields`: list of metrics (`steps`, `distance_km`, `calories_burned_kcal`, `active_minutes`, `heart_rate_bpm`, "
        "`resting_heart_rate_bpm`, `spo2_pct`, `sleep_hours`, `sleep_score`, `water_ml`, `weight_kg`, `workouts`).\n"
        "• `window`: `'today'` (default), `'yesterday'`, `'last_7_days'`, or `'last_30_days'`.\n"
        "• `bucket`: `'none'` (default), `'day'`, `'hour'`, or `'week'`.\n"
        "• `op`: optional reducer (`'sum'`, `'avg'`, `'min'`, `'max'`, `'latest'`).\n"
        "RETURNS: `{status: 'success', data: {window, bucket, op, metrics}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
            "metric": types.Schema(
                type=types.Type.STRING,
                description="Optional shorthand metric selector ('steps', 'heart_rate', 'sleep', 'all').",
            ),
            "fields": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="Health metric fields to fetch (e.g. ['steps', 'heart_rate_bpm', 'sleep_hours']).",
            ),
            "window": types.Schema(
                type=types.Type.STRING,
                description="Time range: 'today' (default), 'yesterday', 'last_7_days', or 'last_30_days'.",
            ),
            "bucket": types.Schema(
                type=types.Type.STRING,
                description="Granularity: 'none' (default), 'day', 'hour', or 'week'.",
            ),
            "op": types.Schema(
                type=types.Type.STRING,
                description="Optional aggregation reducer: 'sum', 'avg', 'min', 'max', or 'latest'.",
            ),
        },
    ),
)

get_calendar_events_schema = types.FunctionDeclaration(
    name="get_calendar_events",
    description=(
        "Fetch events and meetings from the user's connected calendar (READ-ONLY).\n"
        "WHEN TO USE: User asks about their schedule, meetings, availability, or next appointment "
        "('what's on my calendar today?', 'do I have any meetings after 3 PM?', 'when is my next call?').\n"
        "LIMITATION: Strictly read-only — cannot create, edit, move, or cancel calendar events.\n"
        "RETURNS: `{status: 'success', data: {window, date, events: [{title, start, end, location, attendees}]}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
            "window": types.Schema(
                type=types.Type.STRING,
                description="Which slice of the calendar to fetch: 'today' (default), 'tomorrow', 'this_week', or 'on_date'.",
            ),
            "date": types.Schema(
                type=types.Type.STRING,
                description="Target date in 'YYYY-MM-DD' format when `window='on_date'`.",
            ),
        },
    ),
)

get_nutrition_schema = types.FunctionDeclaration(
    name="get_nutrition",
    description=(
        "Read the user's saved meals and daily calorie / macronutrient intake totals, OR look up nutritional values for a food item.\n"
        "WHEN TO USE: User asks what they have eaten so far, how many calories/protein/carbs/fat they've consumed on a day, "
        "or asks for nutritional breakdown of a specific food ('how many calories have I had today?', 'masala dosa calories').\n"
        "WHEN NOT TO USE: Do NOT use to save a new meal (`log_my_meal`), to ask what to eat next (`plan_my_meal`), "
        "or for calories burned (`get_health_data`).\n"
        "RETURNS: `{status: 'success', data: {date, totals: {calories_kcal, protein_g, carbs_g, fat_g}, meals}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
            "date": types.Schema(
                type=types.Type.STRING,
                description="Date to inspect in 'YYYY-MM-DD' format. Omit for today.",
            ),
            "query": types.Schema(
                type=types.Type.STRING,
                description="Optional specific meal, nutrient, or food item to filter or analyze (e.g. 'breakfast', 'protein', 'masala dosa').",
            ),
        },
    ),
)

recall_memory_schema = types.FunctionDeclaration(
    name="recall_memory",
    description=(
        "Search the user's long-term personal memory store on Cymbal Kart for facts, preferences, relationships, "
        "routines, and prior notes.\n"
        "WHEN TO USE: Call whenever:\n"
        "1. The user directly asks what you remember/know about them ('what's my dietary preference?', 'do I have any allergies?').\n"
        "2. Personal context (dietary restrictions, allergies, family/colleague names, medical notes, work role) would "
        "materially improve your answer.\n"
        "RETURNS: `{status: 'success', data: {query, memories: [{fact, category, updated_at}]}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
            "query": types.Schema(
                type=types.Type.STRING,
                description="Focused English search keywords describing what personal fact to look up (e.g. 'dietary restrictions allergies').",
            ),
        },
    ),
)

plan_my_meal_schema = types.FunctionDeclaration(
    name="plan_my_meal",
    description=(
        "Generate a personalized meal recommendation or full-day meal plan grounded in the user's Cymbal Kart profile, "
        "today's already-saved nutrition, and remembered dietary preferences.\n"
        "WHEN TO USE: User asks what they should eat next, wants a meal/diet plan, asks for dish ideas for a goal, "
        "or asks how to hit their remaining macros/calories ('what should I have for dinner?', 'plan my meals for today "
        "for muscle gain', 'high-protein veg lunch under 500 cal', 'dinner mein kya khaun?').\n"
        "SELF-CONTAINED: Automatically reads the user's profile (age, height, weight, activity level), today's logged "
        "meals/macros, and dietary memories (veg/non-veg, allergies, dislikes). Do NOT call `get_nutrition` or "
        "`recall_memory` separately before calling `plan_my_meal`.\n"
        "RETURNS: `{status: 'success', data: {profile, daily_target, consumed_today, remaining_budget_today, "
        "dietary_notes_from_memory, suggested_meals}, note}`."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact utterance that triggered this call, passed verbatim.",
            ),
            "query": types.Schema(
                type=types.Type.STRING,
                description="The meal slot, goal, cuisine, or constraint in English (e.g. 'high-protein vegetarian dinner under 600 kcal').",
            ),
        },
    ),
)

input_required_schema = types.FunctionDeclaration(
    name="input_required",
    description=(
        "Submit the user's answers (consent confirmation and/or missing parameter values) to resume a tool that "
        "previously returned `status='needs_input'`.\n"
        "WHEN TO USE: ONLY on the turn immediately after a tool returned `status='needs_input'`, once you have asked "
        "the user the pending question(s) and they have replied. Do NOT re-call the original tool directly — call "
        "`input_required` with `for_tool` set to that tool's name and one entry in `answers` for every pending question.\n"
        "OUTCOME VALUES:\n"
        "• `'confirmed'` — user agreed / said yes / gave permission (for `consent_given`).\n"
        "• `'declined'` — user refused / said no / cancelled (`status='cancelled'`).\n"
        "• `'provided'` — user supplied the requested slot value (put their spoken answer in `value`)."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "for_tool": types.Schema(
                type=types.Type.STRING,
                description="Exact name of the tool that returned `status='needs_input'` (e.g. 'make_call', 'log_my_meal').",
            ),
            "user_query": types.Schema(
                type=types.Type.STRING,
                description="The user's exact reply utterance in which they answered the pending question(s).",
            ),
            "answers": types.Schema(
                type=types.Type.ARRAY,
                description="List of answers resolving every question in `data.pending_questions` from the prior `needs_input` result.",
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "key": types.Schema(
                            type=types.Type.STRING,
                            description="The question `key` from `pending_questions` (e.g. 'consent_given', 'contact_name').",
                        ),
                        "outcome": types.Schema(
                            type=types.Type.STRING,
                            description="'confirmed' if user agreed, 'declined' if refused, or 'provided' when supplying a parameter.",
                        ),
                        "value": types.Schema(
                            type=types.Type.STRING,
                            description="The value spoken by the user (e.g. 'Rohan', 'tomorrow at 6 PM').",
                        ),
                    },
                ),
            ),
            "key": types.Schema(
                type=types.Type.STRING,
                description="Optional flat confirmation key for single-question resolution (e.g. 'consent_given').",
            ),
            "outcome": types.Schema(
                type=types.Type.STRING,
                description="Optional flat user decision ('confirmed', 'declined', or 'provided').",
            ),
            "value": types.Schema(
                type=types.Type.STRING,
                description="Optional flat text or choice provided by the user.",
            ),
        },
        required=["for_tool"],
    ),
)

switch_phase_schema = types.FunctionDeclaration(
    name="switch_phase",
    description=(
        "Transition the active Cymbal Kart Smartglasses companion phase. Allowed phases: "
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
    plan_my_meal_schema,
    input_required_schema,
]


# ---------------------------------------------------------------------------
# Mock Execution Engine (All 15 Tools + Chained Consent / Slot Resolution)
# ---------------------------------------------------------------------------

class GlassBuddyExecutionEngine:
    """Deterministic mock execution engine for all 15 Cymbal Kart Glass Buddy tools."""

    def __init__(self, broadcast: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self._broadcast = broadcast
        self.active_phase = "SOP_01_COMPANION_READY"
        self._lock = asyncio.Lock()
        self._pending_tool_params: Dict[str, Dict[str, Any]] = {}

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        if self._broadcast:
            try:
                self._broadcast({
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        "persona": "kavya_glass_buddy",
                        "brand": "Cymbal Kart Smartglasses",
                        "event": event_type,
                        **data,
                    },
                })
            except Exception:
                pass

    async def make_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        contact = params.get("contact_name")
        number = params.get("phone_number")
        if params.get("require_consent") and not params.get("_consent_verified"):
            self._pending_tool_params["make_call"] = dict(params)
            pending = [
                {
                    "key": "consent_given",
                    "value_format": "Yes or No confirmation from the user to place the phone call.",
                }
            ]
            if not contact and not number:
                pending.append({
                    "key": "contact_name",
                    "value_format": "Name or phone number of the person to call.",
                })
            result = {
                "status": "needs_input",
                "key": "consent_given",
                "value_format": "Yes or No confirmation from the user to place the phone call.",
                "data": {"pending_questions": pending},
                "note": (
                    f"Ask the user to confirm placing the call{f' to {contact}' if contact else ''} "
                    f"before dialing.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}"
                ),
            }
            self._emit("call_needs_input", result)
            return result

        contact = contact or "Contact"
        number = number or "+91-9876543210"
        result = {
            "status": "calling",
            "contact_name": contact,
            "phone_number": number,
            "data": {"contact_name": contact, "phone_number": number, "call_state": "dialing"},
            "message": f"Calling {contact} now via Cymbal Kart Smartglasses...",
            "note": f"Call to {contact} ({number}) is now dialing. Confirm briefly in 1 sentence.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("call_placed", result)
        return result

    async def start_live_ai(self, params: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "status": "active",
            "data": {"session_state": "streaming", "camera": "Cymbal Kart 4K Ultra-Wide"},
            "message": "Live AI multimodal vision stream activated on Cymbal Kart Smartglasses.",
            "note": f"Continuous Live AI camera stream is now active on Cymbal Kart Smartglasses.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("live_ai_started", result)
        return result

    async def take_photo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "status": "captured",
            "photo_id": "cymbal_kart_img_8492.jpg",
            "resolution": "4K Ultra-Wide",
            "data": {"photo_id": "cymbal_kart_img_8492.jpg", "saved_to_gallery": True},
            "message": "Photo captured and saved to your Cymbal Kart gallery.",
            "note": f"Photo saved to Cymbal Kart gallery. Confirm warmly in 1 short sentence.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("photo_captured", result)
        return result

    async def start_video(self, params: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "status": "recording",
            "video_id": "cymbal_kart_vid_1024.mp4",
            "data": {"recording": True, "video_id": "cymbal_kart_vid_1024.mp4"},
            "message": "Video recording started on Cymbal Kart Smartglasses.",
            "note": f"Video recording is now running on Cymbal Kart Smartglasses.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("video_started", result)
        return result

    async def meeting_mode(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = params.get("action", "start")
        is_start = action == "start"
        result = {
            "status": "recording" if is_start else "stopped",
            "action": action,
            "data": {
                "meeting_active": is_start,
                "summary": None if is_start else "Key decisions captured and saved to your Cymbal Kart notes.",
            },
            "message": f"Meeting mode {action}ed on Cymbal Kart Smartglasses. Audio transcription active.",
            "note": (
                f"Meeting recording {'started' if is_start else 'stopped and summarized in Cymbal Kart app'}. "
                f"Confirm in 1 short sentence.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}"
            ),
        }
        self._emit("meeting_mode_updated", result)
        return result

    async def route_hardware_directive(self, params: Dict[str, Any]) -> Dict[str, Any]:
        directive = params.get("directive") or params.get("user_query") or "inspect_surroundings"
        scene = "You are looking at a modern workspace desk with dual monitors, a laptop, a warm cup of masala chai, and a notebook."
        result = {
            "status": "success",
            "directive": directive,
            "visual_description": scene,
            "data": {
                "scene_description": scene,
                "detected_text": "Q3 Product Architecture Roadmap — Cymbal Kart",
            },
            "message": "View inspected through Cymbal Kart smartglasses camera.",
            "note": f"Describe what the user is seeing naturally in 1-2 sentences.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("hardware_directive_executed", result)
        return result

    async def log_my_meal(self, params: Dict[str, Any]) -> Dict[str, Any]:
        meal = (
            params.get("dish_name")
            or params.get("meal_description")
            or "Paneer Tikka Bowl with 2 Whole-Wheat Rotis & Dal"
        )
        calories = params.get("calories", 550)
        result = {
            "status": "logged",
            "meal": meal,
            "estimated_calories": calories,
            "protein": "26g",
            "carbs": "52g",
            "data": {
                "meal": meal,
                "calories_kcal": calories,
                "protein_g": 26,
                "carbs_g": 52,
                "fat_g": 18,
            },
            "message": f"Meal '{meal}' saved in Cymbal Kart Health (~{calories} kcal, 26g protein).",
            "note": (
                f"Meal saved as '{meal}' (~{calories} kcal, twenty six grams protein). "
                "Confirm this to the user in one short sentence using 'Meal saved' or 'Added to your food diary' "
                f"(AVOID saying the word 'logged' so native audio stays crisp).{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}"
            ),
        }
        self._emit("meal_logged", result)
        return result

    async def stop_b(self, params: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "status": "stopped",
            "data": {"session_closed": True},
            "message": "All active Cymbal Kart background tasks and recordings stopped.",
            "note": f"Session closed cleanly. Give a warm, brief sign-off.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("tasks_stopped", result)
        return result

    async def set_reminder(self, params: Dict[str, Any]) -> Dict[str, Any]:
        title = params.get("title") or "Important Task"
        remind_at = params.get("remind_at") or ("Untimed To-Do" if params.get("no_time") else "today at 6:00 PM")
        result = {
            "status": "success",
            "reminder_id": "cymbal_kart_rem_4821",
            "title": title,
            "remind_at": remind_at,
            "data": {
                "reminder_id": "cymbal_kart_rem_4821",
                "title": title,
                "remind_at": remind_at,
            },
            "message": f"Reminder set for '{title}' at {remind_at} in Cymbal Kart app.",
            "note": f"Reminder '{title}' scheduled for {remind_at}. Confirm in 1 short sentence.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("reminder_set", result)
        return result

    async def get_health_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        metric = params.get("metric", "all")
        fields = params.get("fields") or ["steps", "heart_rate_bpm", "sleep_hours", "calories_burned_kcal"]
        window = params.get("window", "today")
        bucket = params.get("bucket", "none")
        op = params.get("op", "latest")
        metrics_payload = {
            "steps": 7450,
            "step_goal": 10000,
            "distance_km": 5.6,
            "calories_burned_kcal": 485,
            "active_minutes": 48,
            "heart_rate_bpm": 72,
            "resting_heart_rate_bpm": 61,
            "spo2_pct": 98,
            "sleep_hours": 7.3,
            "sleep_score": 86,
            "water_ml": 1800,
            "weight_kg": 71.0,
        }
        result = {
            "status": "success",
            "metric": metric,
            "window": window,
            "bucket": bucket,
            "steps": 7450,
            "step_goal": 10000,
            "heart_rate_bpm": 72,
            "sleep_duration": "7 hours 20 mins",
            "glasses_battery": "84%",
            "data": {
                "window": window,
                "bucket": bucket,
                "op": op,
                "requested_fields": fields,
                "metrics": metrics_payload,
            },
            "note": (
                "Share only the health metrics the user asked for, speaking all numbers in English words "
                f"(e.g. 'seven thousand four hundred fifty steps').{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}"
            ),
        }
        self._emit("health_data_fetched", result)
        return result

    async def get_calendar_events(self, params: Dict[str, Any]) -> Dict[str, Any]:
        window = params.get("window", "today")
        date_str = params.get("date", "2026-09-21")
        events = [
            {
                "title": "Cymbal Kart Product Architecture Sync",
                "time": "3:00 PM - 3:30 PM",
                "start": f"{date_str}T15:00:00+05:30",
                "end": f"{date_str}T15:30:00+05:30",
                "location": "Google Meet",
            },
            {
                "title": "Evening Walk & Strength Workout",
                "time": "6:30 PM - 7:15 PM",
                "start": f"{date_str}T18:30:00+05:30",
                "end": f"{date_str}T19:15:00+05:30",
                "location": "Neighbourhood Park",
            },
        ]
        result = {
            "status": "success",
            "window": window,
            "date": date_str,
            "events": events,
            "data": {"window": window, "date": date_str, "events": events},
            "message": "Calendar is read-only. Displaying scheduled meetings.",
            "note": f"Summarize the user's schedule concisely (remember calendar is read-only).{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("calendar_events_fetched", result)
        return result

    async def get_nutrition(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query") or "today's meals"
        date_str = params.get("date", "2026-09-21")
        totals = {"calories_kcal": 1170, "protein_g": 46, "carbs_g": 138, "fat_g": 42}
        meals = [
            {"slot": "breakfast", "dish": "Poha with sprouts & masala chai", "calories_kcal": 380, "protein_g": 12},
            {"slot": "lunch", "dish": "2 Rotis, Dal Tadka, Paneer Bhurji & Salad", "calories_kcal": 620, "protein_g": 28},
            {"slot": "snack", "dish": "Roasted makhana & filter coffee", "calories_kcal": 170, "protein_g": 6},
        ]
        result = {
            "status": "success",
            "query": query,
            "date": date_str,
            "calories": 280 if query not in ("today's meals", "") else totals["calories_kcal"],
            "protein": "28g" if query not in ("today's meals", "") else "46g",
            "carbs": "36g" if query not in ("today's meals", "") else "138g",
            "fat": "8g" if query not in ("today's meals", "") else "42g",
            "summary": f"Today's intake so far is 1,170 kcal (46g protein, 138g carbs, 42g fat) across breakfast, lunch, and snack.",
            "data": {
                "date": date_str,
                "query": query,
                "totals": totals,
                "meals": meals,
            },
            "note": f"Share the nutritional summary concisely with numbers in English words.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("nutrition_analyzed", result)
        return result

    async def recall_memory(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query", "")
        memories = [
            "User is allergic to peanuts and strictly avoids peanut butter.",
            "User prefers high-protein vegetarian Indian meals (paneer, soya, moong dal, Greek yogurt).",
            "User prefers morning reminders at 8:30 AM on weekdays.",
            "User works as a software engineer in Bengaluru.",
        ]
        result = {
            "status": "success",
            "query": query,
            "data": memories,
            "structured_memories": [
                {"fact": m, "category": "personal_preference", "updated_at": "2026-09-15"}
                for m in memories
            ],
            "note": f"Use these remembered facts naturally to personalize your reply.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("memory_recalled", result)
        return result

    async def plan_my_meal(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query") or params.get("user_query") or "balanced high-protein dinner"
        plan_data = {
            "query": query,
            "profile": {
                "gender": "male",
                "age": 25,
                "height_cm": 173,
                "weight_kg": 71,
                "activity_level": "active",
                "goal": "lean muscle maintenance & steady energy",
            },
            "daily_target": {"calories_kcal": 2150, "protein_g": 115, "carbs_g": 230, "fat_g": 70},
            "consumed_today": {"calories_kcal": 1170, "protein_g": 46, "carbs_g": 138, "fat_g": 42},
            "remaining_budget_today": {"calories_kcal": 980, "protein_g": 69, "carbs_g": 92, "fat_g": 28},
            "dietary_notes_from_memory": [
                "Strictly peanut-free (peanut allergy).",
                "Prefers high-protein vegetarian Indian meals.",
            ],
            "suggested_meals": [
                {
                    "option": 1,
                    "dish": "Grilled Paneer Tikka (150g) + 1 Moong Dal Chilla with Mint Chutney & Cucumber Salad",
                    "calories_kcal": 540,
                    "protein_g": 38,
                    "carbs_g": 34,
                    "fat_g": 22,
                },
                {
                    "option": 2,
                    "dish": "Soya Chunk & Palak Bhurji Bowl + 2 Phulkas + 1 Bowl Low-Fat Dahi",
                    "calories_kcal": 510,
                    "protein_g": 42,
                    "carbs_g": 48,
                    "fat_g": 12,
                },
            ],
        }
        result = {
            "status": "success",
            "query": query,
            "data": plan_data,
            "message": "Generated personalized Cymbal Kart meal plan based on remaining 980 kcal / 69g protein budget.",
            "note": (
                "Recommend 1-2 concrete peanut-free dish ideas grounded in `remaining_budget_today` "
                "(nine hundred eighty calories and sixty nine grams protein remaining) in under 3 sentences."
                f"{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}"
            ),
        }
        self._emit("meal_planned", result)
        return result

    async def input_required(self, params: Dict[str, Any]) -> Dict[str, Any]:
        for_tool = params.get("for_tool", "make_call")
        answers = params.get("answers") or []
        outcome = params.get("outcome")
        value = params.get("value")

        # Normalize answers array if passed via the Section 6 multi-slot schema
        resolved_slots: Dict[str, Any] = {}
        declined = outcome == "declined"
        if isinstance(answers, list):
            for item in answers:
                if isinstance(item, dict):
                    k = item.get("key")
                    o = item.get("outcome")
                    v = item.get("value")
                    if o == "declined":
                        declined = True
                    if k and v:
                        resolved_slots[k] = v
                    if not outcome and o:
                        outcome = o

        outcome = outcome or "confirmed"
        if declined:
            result = {
                "status": "cancelled",
                "for_tool": for_tool,
                "outcome": "declined",
                "data": {"for_tool": for_tool, "cancelled": True},
                "message": f"Action for {for_tool} cancelled by user.",
                "note": f"The user declined {for_tool}. Acknowledge briefly and move on.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
            }
            self._emit("input_cancelled", result)
            return result

        result = {
            "status": "confirmed",
            "for_tool": for_tool,
            "outcome": outcome,
            "resolved_slots": resolved_slots,
            "value": value,
            "data": {"for_tool": for_tool, "outcome": outcome, "resolved_slots": resolved_slots},
            "message": f"Action for {for_tool} confirmed on Cymbal Kart Smartglasses.",
            "note": f"User confirmed {for_tool} ({resolved_slots or value or outcome}). Confirm completion in 1 short sentence.{_AUDIO_LANGUAGE_MIRROR_DIRECTIVE}",
        }
        self._emit("input_confirmed", result)
        return result

