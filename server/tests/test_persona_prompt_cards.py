"""Unit tests for the centralized persona_prompt_cards module."""

from __future__ import annotations

import unittest

from persona_prompt_cards import (
    PRAGYA_SUPERCAR_CARDS,
    ANANYA_MF_CARDS,
    KAVYA_GLASS_BUDDY_CARDS,
    get_pragya_phase_card,
    get_ananya_phase_card,
    get_kavya_phase_card,
    get_persona_card,
    get_persona_all_cards,
    format_persona_prompt_card,
    get_persona_system_instruction,
)


class TestPersonaPromptCards(unittest.TestCase):

    def test_pragya_cards_retrieval(self):
        card = get_pragya_phase_card("SOP_02_DISCOVERY")
        self.assertIsNotNone(card)
        self.assertEqual(card.phase_id, "SOP_02_DISCOVERY")

        # Alias lookup
        card_alias = get_pragya_phase_card("pricing")
        self.assertEqual(card_alias.phase_id, "SOP_02_DISCOVERY")

        # Unified helper lookup
        unified = get_persona_card("lamborghini-concierge", "models")
        self.assertEqual(unified.phase_id, "SOP_02_DISCOVERY")

        # All cards
        all_cards = get_persona_all_cards("pragya")
        self.assertEqual(set(all_cards.keys()), {"SOP_02_DISCOVERY", "SOP_03_PINCODE", "SOP_04_BOOKED"})

        # Instructions
        root = get_persona_system_instruction("pragya", engine="live")
        self.assertIn("Lamborghini India", root)
        self.assertIn("switch_phase", root)

        monolithic = get_persona_system_instruction("pragya", engine="cascade")
        self.assertIn("Lamborghini India", monolithic)
        self.assertIn("Revuelto", monolithic)

    def test_ananya_cards_pure_cymbal(self):
        card = get_ananya_phase_card("SOP_01_OVERVIEW")
        self.assertIsNotNone(card)
        self.assertEqual(card.phase_id, "SOP_01_OVERVIEW")

        # Check aliases
        card_alias = get_ananya_phase_card("sip")
        self.assertEqual(card_alias.phase_id, "SOP_03_SIP_PLANNING")

        # Check unified helper
        unified = get_persona_card("ananya-advisor", "schemes")
        self.assertEqual(unified.phase_id, "SOP_02_SCHEME_DETAILS")

        # Alias groww-advisor routes to ananya
        groww_alias = get_persona_card("groww-advisor", "holdings")
        self.assertEqual(groww_alias.phase_id, "SOP_01_OVERVIEW")

        # All cards
        all_cards = get_persona_all_cards("ananya-advisor")
        self.assertEqual(len(all_cards), 4)

        # STRICT BRANDING CHECK: Zero Groww references
        root = get_persona_system_instruction("ananya-advisor", engine="live")
        self.assertIn("Cymbal Investments", root)
        self.assertNotIn("Groww", root)
        self.assertNotIn("groww", root.lower())

        monolithic = get_persona_system_instruction("ananya-advisor", engine="cascade")
        self.assertIn("Cymbal Investments", monolithic)
        self.assertNotIn("Groww", monolithic)

        # Check all cards for Groww branding
        for c in all_cards.values():
            self.assertNotIn("Groww", c.directive)
            self.assertNotIn("Groww", c.persona_role)

    def test_kavya_cards_pure_cymbal_smartglasses(self):
        card = get_kavya_phase_card("SOP_01_COMPANION_READY")
        self.assertIsNotNone(card)
        self.assertEqual(card.phase_id, "SOP_01_COMPANION_READY")

        # Check aliases
        card_alias = get_kavya_phase_card("vision")
        self.assertEqual(card_alias.phase_id, "SOP_02_VISION_CAPTURE")

        # Check unified helper
        unified = get_persona_card("kavya-glass-buddy", "productivity")
        self.assertEqual(unified.phase_id, "SOP_03_DAILY_ASSISTANT")

        # Alias reservation-agent routes to kavya
        res_alias = get_persona_card("reservation-agent", "health")
        self.assertEqual(res_alias.phase_id, "SOP_04_HEALTH_WELLNESS")

        all_cards = get_persona_all_cards("kavya-glass-buddy")
        self.assertEqual(len(all_cards), 4)

        # STRICT BRANDING CHECK: Zero Lenskart / AjnaLens references
        root = get_persona_system_instruction("kavya-glass-buddy", engine="live")
        self.assertIn("Cymbal Smartglasses", root)
        self.assertNotIn("Lenskart", root)
        self.assertNotIn("AjnaLens", root)
        self.assertNotIn("Ajna", root)

        monolithic = get_persona_system_instruction("kavya-glass-buddy", engine="cascade")
        self.assertIn("Cymbal Smartglasses", monolithic)
        self.assertNotIn("Lenskart", monolithic)
        self.assertNotIn("AjnaLens", monolithic)

        # Check all cards
        for c in all_cards.values():
            self.assertNotIn("Lenskart", c.directive)
            self.assertNotIn("AjnaLens", c.directive)
            self.assertNotIn("Ajna", c.directive)

    def test_static_persona_instructions(self):
        abhay_inst = get_persona_system_instruction("car-negotiator")
        self.assertIn("Abhay", abhay_inst)
        self.assertIn("AeroNxt EV", abhay_inst)
        self.assertIn("₹20,00,000", abhay_inst)
        self.assertIn("₹14,50,000", abhay_inst)
        self.assertNotIn("Ranvir", abhay_inst)
        self.assertNotIn("dollar", abhay_inst.lower())

        meera_inst = get_persona_system_instruction("debt-collector")
        self.assertIn("Meera", meera_inst)
        self.assertIn("8,500", meera_inst)

        kabir_inst = get_persona_system_instruction("storyteller")
        self.assertIn("Kabir", kabir_inst)

        aisha_inst = get_persona_system_instruction("ai-companion")
        self.assertIn("Aisha", aisha_inst)


if __name__ == "__main__":
    unittest.main()
