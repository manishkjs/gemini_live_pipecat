import unittest
from persona_registry import (
    ArchitecturePattern,
    PERSONA_REGISTRY,
    resolve_persona_architecture,
    is_persona_ui_editable,
)

class TestPersonaRegistry(unittest.TestCase):
    def test_pragya_routing(self):
        arch = resolve_persona_architecture("lamborghini-concierge")
        self.assertEqual(arch, ArchitecturePattern.JIT_PHASE_CARDS)
        self.assertFalse(is_persona_ui_editable("lamborghini-concierge"))

    def test_ranvir_routing(self):
        arch = resolve_persona_architecture("car-negotiator")
        self.assertEqual(arch, ArchitecturePattern.STATE_LADDER_NEGOTIATOR)
        self.assertTrue(is_persona_ui_editable("car-negotiator"))

    def test_legacy_personas_fallback_to_monolithic(self):
        for persona_id in ["debt-collector", "reservation-agent", "storyteller", "ai-companion", "groww-advisor"]:
            arch = resolve_persona_architecture(persona_id)
            self.assertEqual(arch, ArchitecturePattern.MONOLITHIC_STATIC)
            self.assertTrue(is_persona_ui_editable(persona_id))

    def test_unknown_or_none_persona_fallback(self):
        self.assertEqual(resolve_persona_architecture(None), ArchitecturePattern.MONOLITHIC_STATIC)
        self.assertEqual(resolve_persona_architecture("custom"), ArchitecturePattern.MONOLITHIC_STATIC)
        self.assertEqual(resolve_persona_architecture("unknown-xyz"), ArchitecturePattern.MONOLITHIC_STATIC)
        self.assertTrue(is_persona_ui_editable(None))
        self.assertTrue(is_persona_ui_editable("custom"))

    def test_pragya_cascade_vs_live_routing(self):
        from persona_registry import get_persona_architecture
        arch = get_persona_architecture("lamborghini-concierge")

        # System instruction prompt test
        live_prompt = arch.compose_system_prompt(None, engine="live")
        cascade_prompt = arch.compose_system_prompt(None, engine="cascade")

        self.assertIn("switch_phase", live_prompt)
        self.assertNotIn("switch_phase", cascade_prompt)
        self.assertIn("CAR DISCOVERY & SPECS", cascade_prompt)
        self.assertIn("LOUNGE VISIT & APPOINTMENT", cascade_prompt)
        self.assertIn("VISIT CONFIRMED & AFTERCARE", cascade_prompt)

        # Tool schema isolation
        live_tools = arch.get_tool_schemas(engine="live")
        cascade_tools = arch.get_tool_schemas(engine="cascade")

        self.assertEqual([t.name for t in live_tools], ["switch_phase", "create_appointment_booking"])
        self.assertEqual([t.name for t in cascade_tools], ["create_appointment_booking"])

        # Handler registration test
        class DummyLLM:
            def __init__(self):
                self.functions = {}
            def register_function(self, name, handler):
                self.functions[name] = handler

        llm_live = DummyLLM()
        reg_live = arch.register_handlers(llm_live, engine="live")
        self.assertEqual(reg_live, ["switch_phase", "create_appointment_booking"])
        self.assertIn("switch_phase", llm_live.functions)
        self.assertIn("create_appointment_booking", llm_live.functions)

        llm_cascade = DummyLLM()
        reg_cascade = arch.register_handlers(llm_cascade, engine="cascade")
        self.assertEqual(reg_cascade, ["create_appointment_booking"])
        self.assertNotIn("switch_phase", llm_cascade.functions)
        self.assertIn("create_appointment_booking", llm_cascade.functions)

if __name__ == "__main__":
    unittest.main()
