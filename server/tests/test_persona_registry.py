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
        for persona_id in ["debt-collector", "storyteller", "ai-companion"]:
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

    def test_prompt_aliases_keep_their_required_execution_architecture(self):
        from persona_registry import get_persona_architecture
        expected = {
            "wealth-manager": ArchitecturePattern.JIT_PHASE_CARDS,
            "pragya": ArchitecturePattern.JIT_PHASE_CARDS,
            "ananya": ArchitecturePattern.JIT_MF_ADVISOR,
            "groww-advisor": ArchitecturePattern.JIT_MF_ADVISOR,
            "kavya": ArchitecturePattern.GLASS_BUDDY,
            "glass-buddy": ArchitecturePattern.GLASS_BUDDY,
            "reservation-agent": ArchitecturePattern.GLASS_BUDDY,
            "ranvir": ArchitecturePattern.STATE_LADDER_NEGOTIATOR,
        }
        for alias, pattern in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(resolve_persona_architecture(alias), pattern)
                for engine in ("live", "cascade"):
                    self.assertTrue(get_persona_architecture(alias).get_tool_schemas(engine=engine))

    def test_all_aliases_agree_across_preview_prompts_cards_tools_and_editability(self):
        from fastapi.testclient import TestClient
        import server
        from persona_identity import PERSONA_ALIASES, normalize_persona_id
        from persona_registry import get_persona_architecture
        from persona_prompt_cards import get_persona_all_cards, get_persona_card, get_session_preset
        client = TestClient(server.app)
        for alias, canonical in PERSONA_ALIASES.items():
            for spelling in (alias, f" {alias.upper()} "):
                with self.subTest(alias=spelling):
                    self.assertEqual(normalize_persona_id(spelling), canonical)
                    self.assertEqual(normalize_persona_id(canonical), canonical)
                    self.assertEqual(resolve_persona_architecture(spelling), resolve_persona_architecture(canonical))
                    self.assertEqual(is_persona_ui_editable(spelling), is_persona_ui_editable(canonical))
                    self.assertEqual(PERSONA_REGISTRY[alias].architecture, PERSONA_REGISTRY[canonical].architecture)
                    alias_arch = get_persona_architecture(spelling)
                    canonical_arch = get_persona_architecture(canonical)
                    for engine in ("live", "cascade"):
                        self.assertEqual([t.name for t in alias_arch.get_tool_schemas(engine)],
                                         [t.name for t in canonical_arch.get_tool_schemas(engine)])
                        for tone in ("professional", "signature"):
                            self.assertEqual(get_session_preset(spelling, engine, tone, "hi-IN"),
                                             get_session_preset(canonical, engine, tone, "hi-IN"))
                    cards = get_persona_all_cards(canonical)
                    self.assertEqual(get_persona_all_cards(spelling), cards)
                    for card in cards.values():
                        self.assertEqual(get_persona_card(spelling, card.phase_id), card)
            for engine in ("live", "cascade"):
                alias_preview = client.get(f"/persona-prompt/{alias}?engine={engine}").json()
                canonical_preview = client.get(f"/persona-prompt/{canonical}?engine={engine}").json()
                for key in ("prompt", "architecture", "editable"):
                    self.assertEqual(alias_preview[key], canonical_preview[key], (alias, engine, key))

if __name__ == "__main__":
    unittest.main()
