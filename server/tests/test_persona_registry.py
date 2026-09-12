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

if __name__ == "__main__":
    unittest.main()
