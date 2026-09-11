"""Unit tests for Pragya Ferrari Supercar Phase Cards (SOP 01-06) and prompt formatting."""

import unittest

from supercar_cards import (
    PRAGYA_SUPERCAR_CARDS,
    get_pragya_phase_card,
    format_supercar_prompt_card,
    get_pragya_root_system_instruction,
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
            self.assertIn("Ferrari", card.persona_role)

    def test_card_retrieval_by_aliases(self):
        # By exact key
        card1 = get_pragya_phase_card("SOP_01_OPENING")
        self.assertIsNotNone(card1)
        self.assertEqual(card1.phase_id, "SOP_01_OPENING")

        # By alias (e.g. discovery, pricing, booking, service_override, objections)
        self.assertEqual(get_pragya_phase_card("discovery").phase_id, "SOP_02_PRODUCT_DISCOVERY")
        self.assertEqual(get_pragya_phase_card("pricing").phase_id, "SOP_03_PRICING")
        self.assertEqual(get_pragya_phase_card("booking").phase_id, "SOP_04_STORE_BOOKING")
        self.assertEqual(get_pragya_phase_card("service_override").phase_id, "SOP_05_SERVICE_OVERRIDE")
        self.assertEqual(get_pragya_phase_card("objections").phase_id, "SOP_06_OBJECTIONS")

    def test_sop_02_contains_ferrari_models(self):
        card = get_pragya_phase_card("SOP_02_PRODUCT_DISCOVERY")
        self.assertIn("Roma", card.directive)
        self.assertIn("296 GTB", card.directive)
        self.assertIn("SF90 Stradale", card.directive)
        self.assertIn("Purosangue", card.directive)

    def test_sop_05_strict_service_override(self):
        card = get_pragya_phase_card("SOP_05_SERVICE_OVERRIDE")
        self.assertIn("Halt all sales", card.directive)
        self.assertIn("Ferrari Official Service Concierge", card.directive)

    def test_card_formatting_contains_identity_and_feminine_grammar(self):
        card = get_pragya_phase_card("SOP_01_OPENING")
        formatted = format_supercar_prompt_card(card, context="Inbound inquiry")
        self.assertIn("[ACTIVE_SOP_DIRECTIVE: SOP_01_OPENING - Opening & Consent]", formatted)
        self.assertIn("Speaker Persona: Pragya", formatted)
        self.assertIn("Mandatory Female Grammar", formatted)
        self.assertIn("Context: Inbound inquiry", formatted)

    def test_lean_root_system_instruction_length(self):
        root_prompt = get_pragya_root_system_instruction()
        self.assertLess(len(root_prompt), 900)
        self.assertIn("Pragya", root_prompt)
        self.assertIn("Ferrari India", root_prompt)
        self.assertIn("get_phase_card", root_prompt)


if __name__ == "__main__":
    unittest.main()
