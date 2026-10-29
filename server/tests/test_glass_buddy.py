"""Unit tests for Kavya / Buddy (Cymbal Kart Glass Buddy) architecture, 15 tools, and Header/Footer System Cards."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from persona_prompt_cards.kavya_cards import (
    KAVYA_GLASS_BUDDY_CARDS,
    format_kavya_prompt_card,
)
from persona_tools.glass_buddy import (
    ALL_GLASS_BUDDY_TOOL_SCHEMAS,
    GlassBuddyExecutionEngine,
    switch_phase_schema,
)
from persona_registry import (
    ArchitecturePattern,
    KavyaGlassBuddyArchitecture,
    get_persona_architecture,
    resolve_persona_architecture,
)


class TestKavyaGlassBuddy(unittest.IsolatedAsyncioTestCase):

    async def test_all_15_mock_tools_execution(self):
        broadcast_mock = MagicMock()
        engine = GlassBuddyExecutionEngine(broadcast=broadcast_mock)

        # 1. make_call
        res = await engine.make_call({"contact_name": "Sameer", "user_query": "Call Sameer"})
        self.assertEqual(res["status"], "calling")
        self.assertIn("Sameer", res["message"])

        # 2. start_live_ai
        res = await engine.start_live_ai({"user_query": "Start live AI"})
        self.assertEqual(res["status"], "active")

        # 3. take_photo
        res = await engine.take_photo({"user_query": "Take a photo"})
        self.assertEqual(res["status"], "captured")

        # 4. start_video
        res = await engine.start_video({"user_query": "Record a video"})
        self.assertEqual(res["status"], "recording")

        # 5. meeting_mode
        res = await engine.meeting_mode({"action": "start", "user_query": "Start meeting mode"})
        self.assertEqual(res["status"], "recording")

        # 6. route_hardware_directive
        res = await engine.route_hardware_directive({"user_query": "What is in front of me?"})
        self.assertEqual(res["status"], "success")

        # 7. log_my_meal (verifies phonetic guidance avoiding 'logged' -> 'globbed')
        res = await engine.log_my_meal({"dish_name": "Poha", "calories": 250, "user_query": "Log my meal"})
        self.assertEqual(res["status"], "logged")
        self.assertIn("Poha", res["message"])
        self.assertIn("Meal saved", res["note"])

        # 8. stop_b
        res = await engine.stop_b({"user_query": "Stop Buddy"})
        self.assertEqual(res["status"], "stopped")

        # 9. set_reminder
        res = await engine.set_reminder({"title": "Drink water", "remind_at": "in 1 hour", "user_query": "Remind me"})
        self.assertEqual(res["status"], "success")

        # 10. get_health_data
        res = await engine.get_health_data({"metric": "all", "fields": ["steps", "heart_rate_bpm"], "window": "today", "bucket": "none"})
        self.assertEqual(res["status"], "success")
        self.assertIn("steps", res)

        # 11. get_calendar_events
        res = await engine.get_calendar_events({"window": "today", "user_query": "Check calendar"})
        self.assertEqual(res["status"], "success")
        self.assertIn("events", res)

        # 12. get_nutrition
        res = await engine.get_nutrition({"query": "masala dosa", "user_query": "Calories in masala dosa"})
        self.assertEqual(res["status"], "success")
        self.assertIn("calories", res)

        # 13. recall_memory
        res = await engine.recall_memory({"query": "allergies", "user_query": "Do I have any allergies?"})
        self.assertEqual(res["status"], "success")
        self.assertIn("data", res)

        # 14. plan_my_meal (15th tool from Google Doc)
        res = await engine.plan_my_meal({"query": "high-protein veg dinner", "user_query": "Dinner mein kya khaun?"})
        self.assertEqual(res["status"], "success")
        self.assertIn("remaining_budget_today", res["data"])
        self.assertIn("suggested_meals", res["data"])

        # 15. input_required (supports both flat and multi-answer array formats)
        res = await engine.input_required({
            "for_tool": "make_call",
            "answers": [{"key": "consent_given", "outcome": "confirmed", "value": "yes"}],
            "user_query": "Yes, go ahead",
        })
        self.assertEqual(res["status"], "confirmed")

        # All 15 mock calls emit events to broadcast
        self.assertEqual(broadcast_mock.call_count, 15)

    def test_architecture_resolution(self):
        arch_type = resolve_persona_architecture("kavya-glass-buddy")
        self.assertEqual(arch_type, ArchitecturePattern.GLASS_BUDDY)

        alias_type = resolve_persona_architecture("reservation-agent")
        self.assertEqual(alias_type, ArchitecturePattern.GLASS_BUDDY)

        arch = get_persona_architecture("kavya-glass-buddy")
        self.assertIsInstance(arch, KavyaGlassBuddyArchitecture)
        self.assertTrue(arch.has_exclusive_tools())

    def test_tool_schemas_live_vs_cascade(self):
        arch = KavyaGlassBuddyArchitecture()

        live_tools = arch.get_tool_schemas(engine="live")
        self.assertEqual(len(live_tools), 16)  # 15 action tools + switch_phase
        names = [t.name for t in live_tools]
        self.assertIn("switch_phase", names)
        self.assertIn("make_call", names)
        self.assertIn("route_hardware_directive", names)
        self.assertIn("plan_my_meal", names)

        cascade_tools = arch.get_tool_schemas(engine="cascade")
        self.assertEqual(len(cascade_tools), 15)  # 15 action tools only
        c_names = [t.name for t in cascade_tools]
        self.assertNotIn("switch_phase", c_names)
        self.assertIn("make_call", c_names)
        self.assertIn("plan_my_meal", c_names)

    def test_system_prompt_pure_cymbal_kart_and_header_footer(self):
        arch = KavyaGlassBuddyArchitecture()

        for engine_mode in ("live", "cascade"):
            prompt = arch.compose_system_prompt(None, engine=engine_mode)
            self.assertIn("Cymbal Kart", prompt)
            self.assertIn("Cymbal Smartglasses", prompt)
            self.assertIn("<language_and_accent_control>", prompt)
            self.assertIn("<system_profile_metadata>", prompt)
            self.assertIn("<system_footer>", prompt)
            self.assertNotIn("Lenskart", prompt)
            self.assertNotIn("lenskart", prompt.lower())
            self.assertNotIn("AjnaLens", prompt)
            self.assertNotIn("ajnalens", prompt.lower())

        for phase_id, card in KAVYA_GLASS_BUDDY_CARDS.items():
            self.assertTrue(card.header, f"{phase_id} missing header")
            self.assertTrue(card.footer, f"{phase_id} missing footer")
            rendered = format_kavya_prompt_card(card)
            self.assertIn("<system_header>", rendered)
            self.assertIn("<system_footer>", rendered)
            self.assertIn("Cymbal Kart", rendered)
            self.assertNotIn("lenskart", rendered.lower())

    async def test_switch_phase_live(self):
        arch = KavyaGlassBuddyArchitecture()
        mock_llm = MagicMock()
        mock_llm.inject_directive = AsyncMock(return_value=True)
        broadcast_mock = AsyncMock()

        registered = arch.register_handlers(mock_llm, broadcast=broadcast_mock, engine="live")
        self.assertEqual(len(registered), 16)  # 15 tools + switch_phase

        result = await arch._switch_phase({"phase_id": "SOP_02_VISION_CAPTURE"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["delivery_status"], "sent")
        mock_llm.inject_directive.assert_awaited_once()
        broadcast_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

