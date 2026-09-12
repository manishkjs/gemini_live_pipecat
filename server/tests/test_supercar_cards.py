"""Unit tests for Pragya Lamborghini Supercar Phase Cards (SOP 01-06) and prompt formatting."""

import unittest

from supercar_cards import (
    PRAGYA_SUPERCAR_CARDS,
    get_pragya_phase_card,
    format_supercar_prompt_card,
    get_pragya_root_system_instruction,
    EXPANDED_UNIVERSAL_JUMP_FOOTER,
)


class TestSupercarCards(unittest.TestCase):
    def test_all_six_sop_cards_exist(self):
        expected_keys = [
            "SOP_01_OPENING",
            "SOP_02_PRODUCT_DISCOVERY",
            "SOP_03_PRICING",
            "SOP_04_STORE_BOOKING",
            "SOP_05_SERVICE_OVERRIDE",
            "SOP_06_OBJECTIONS",
        ]
        for key in expected_keys:
            self.assertIn(key, PRAGYA_SUPERCAR_CARDS)
            card = PRAGYA_SUPERCAR_CARDS[key]
            self.assertEqual(card.persona_name, "Pragya")
            self.assertIn("Lamborghini", card.persona_role)

    def test_card_retrieval_by_aliases(self):
        # By exact key
        card1 = get_pragya_phase_card("SOP_01_OPENING")
        self.assertIsNotNone(card1)
        self.assertEqual(card1.phase_id, "SOP_01_OPENING")

        # By alias
        self.assertEqual(get_pragya_phase_card("discovery").phase_id, "SOP_02_PRODUCT_DISCOVERY")
        self.assertEqual(get_pragya_phase_card("pricing").phase_id, "SOP_03_PRICING")
        self.assertEqual(get_pragya_phase_card("booking").phase_id, "SOP_04_STORE_BOOKING")
        self.assertEqual(get_pragya_phase_card("service_override").phase_id, "SOP_05_SERVICE_OVERRIDE")
        self.assertEqual(get_pragya_phase_card("objections").phase_id, "SOP_06_OBJECTIONS")

    def test_sop_02_contains_lamborghini_models(self):
        card = get_pragya_phase_card("SOP_02_PRODUCT_DISCOVERY")
        self.assertIn("Gallardo", card.directive)
        self.assertIn("Aventador", card.directive)
        self.assertIn("Urus", card.directive)

    def test_sop_05_strict_service_override(self):
        card = get_pragya_phase_card("SOP_05_SERVICE_OVERRIDE")
        self.assertIn("halt all sales", card.directive.lower())
        self.assertIn("Lamborghini Official Service Concierge", card.directive)

    def test_card_formatting_contains_identity_and_expanded_jump_footer(self):
        card = get_pragya_phase_card("SOP_01_OPENING")
        formatted = format_supercar_prompt_card(card, context="Inbound inquiry")
        self.assertIn("[ACTIVE_SOP_DIRECTIVE: SOP_01_OPENING", formatted)
        self.assertIn("Speaker Persona: Pragya", formatted)
        self.assertIn("Mandatory Female Grammar", formatted)
        self.assertIn("UNIVERSAL NAVIGATION COMPASS", formatted)
        self.assertIn("HIGHEST PRIORITY OVERRIDE", formatted)
        self.assertIn("Aventador", formatted)
        self.assertIn("Gallardo", formatted)
        self.assertIn("Urus", formatted)

    def test_lean_root_system_instruction_length(self):
        root_prompt = get_pragya_root_system_instruction()
        self.assertLess(len(root_prompt), 4200)
        self.assertIn("Pragya", root_prompt)
        self.assertIn("Lamborghini India", root_prompt)
        self.assertIn("create_appointment_booking", root_prompt)

    def test_root_prompt_forbids_folding_on_the_first_soft_no(self):
        """Phase 1 must push, not fold. A soft 'no' is an objection, not an exit."""
        root = get_pragya_root_system_instruction()
        self.assertIn("NEVER GIVE UP EARLY", root)
        self.assertIn("THREE", root)
        for soft_no in ["Busy", "later", "thinking about it"]:
            self.assertIn(soft_no, root, soft_no)


if __name__ == "__main__":
    unittest.main()
