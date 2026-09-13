"""Unit tests for Kavya (Cymbal Glass Buddy) architecture, tools, and cards."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

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

    async def test_all_14_mock_tools_execution(self):
        broadcast_mock = MagicMock()
        engine = GlassBuddyExecutionEngine(broadcast=broadcast_mock)

        # 1. make_call
        res = await engine.make_call({"contact_name": "Sameer"})
        self.assertEqual(res["status"], "calling")
        self.assertIn("Sameer", res["message"])

        # 2. start_live_ai
        res = await engine.start_live_ai({})
        self.assertEqual(res["status"], "active")

        # 3. take_photo
        res = await engine.take_photo({"mode": "high_res"})
        self.assertEqual(res["status"], "captured")

        # 4. start_video
        res = await engine.start_video({"duration_seconds": 30})
        self.assertEqual(res["status"], "recording")

        # 5. meeting_mode
        res = await engine.meeting_mode({"action": "start"})
        self.assertEqual(res["status"], "recording")

        # 6. route_hardware_directive
        res = await engine.route_hardware_directive({"query": "What is in front of me?"})
        self.assertEqual(res["status"], "success")

        # 7. log_my_meal
        res = await engine.log_my_meal({"dish_name": "Poha", "calories": 250})
        self.assertEqual(res["status"], "logged")
        self.assertIn("Poha", res["message"])

        # 8. stop_b
        res = await engine.stop_b({})
        self.assertEqual(res["status"], "stopped")

        # 9. set_reminder
        res = await engine.set_reminder({"reminder_text": "Drink water", "target_time": "in 1 hour"})
        self.assertEqual(res["status"], "success")

        # 10. get_health_data
        res = await engine.get_health_data({"metric_type": "all"})
        self.assertEqual(res["status"], "success")
        self.assertIn("steps", res)

        # 11. get_calendar_events
        res = await engine.get_calendar_events({"window": "today"})
        self.assertEqual(res["status"], "success")
        self.assertIn("events", res)

        # 12. get_nutrition
        res = await engine.get_nutrition({"query": "masala dosa"})
        self.assertEqual(res["status"], "success")
        self.assertIn("calories", res)

        # 13. recall_memory
        res = await engine.recall_memory({"query": "allergies"})
        self.assertEqual(res["status"], "success")
        self.assertIn("data", res)

        # 14. input_required
        res = await engine.input_required({"for_tool": "make_call", "outcome": "confirmed"})
        self.assertEqual(res["status"], "confirmed")

        # All 14 mock calls emit events to broadcast
        self.assertEqual(broadcast_mock.call_count, 14)

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
        self.assertEqual(len(live_tools), 15)  # 14 action tools + switch_phase
        names = [t.name for t in live_tools]
        self.assertIn("switch_phase", names)
        self.assertIn("make_call", names)
        self.assertIn("route_hardware_directive", names)

        cascade_tools = arch.get_tool_schemas(engine="cascade")
        self.assertEqual(len(cascade_tools), 14)  # 14 action tools only
        c_names = [t.name for t in cascade_tools]
        self.assertNotIn("switch_phase", c_names)
        self.assertIn("make_call", c_names)

    def test_system_prompt_pure_cymbal(self):
        arch = KavyaGlassBuddyArchitecture()

        live_prompt = arch.compose_system_prompt(None, engine="live")
        self.assertIn("Cymbal Smartglasses", live_prompt)
        self.assertNotIn("Lenskart", live_prompt)
        self.assertNotIn("AjnaLens", live_prompt)

        cascade_prompt = arch.compose_system_prompt(None, engine="cascade")
        self.assertIn("Cymbal Smartglasses", cascade_prompt)
        self.assertNotIn("Lenskart", cascade_prompt)
        self.assertNotIn("AjnaLens", cascade_prompt)

    async def test_switch_phase_live(self):
        arch = KavyaGlassBuddyArchitecture()
        mock_llm = MagicMock()
        mock_llm.inject_directive = AsyncMock(return_value=True)
        broadcast_mock = AsyncMock()

        registered = arch.register_handlers(mock_llm, broadcast=broadcast_mock, engine="live")
        self.assertEqual(len(registered), 15)  # 14 tools + switch_phase

        result = await arch._switch_phase({"phase_id": "SOP_02_VISION_CAPTURE"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["delivery_status"], "sent")
        mock_llm.inject_directive.assert_awaited_once()
        broadcast_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
