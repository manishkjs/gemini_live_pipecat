"""Prompt contract: one opening, three overriding context cards, declared tools."""
import unittest
from supercar_cards import (
    PRAGYA_SUPERCAR_CARDS, format_supercar_prompt_card, get_pragya_phase_card,
    get_pragya_root_system_instruction, render_state_line,
)
from supercar_tools import SUPERCAR_TOOL_SCHEMAS


class TestSupercarCards(unittest.TestCase):
    def test_one_card_per_injectable_phase(self):
        self.assertEqual(list(PRAGYA_SUPERCAR_CARDS), ["SOP_02_DISCOVERY", "SOP_03_PINCODE", "SOP_04_BOOKED"])
        self.assertIsNone(get_pragya_phase_card("SOP_01_OPENING"))
        for name, phase in (("discovery", "SOP_02_DISCOVERY"), ("booking", "SOP_03_PINCODE"), ("booked", "SOP_04_BOOKED")):
            self.assertEqual(get_pragya_phase_card(name).phase_id, phase)

    def test_every_card_explicitly_supersedes_earlier_phase_instructions(self):
        for card in PRAGYA_SUPERCAR_CARDS.values():
            text = format_supercar_prompt_card(card)
            self.assertTrue(text.startswith("[CURRENT PHASE:"))
            self.assertIn("Disregard instructions in all earlier phase cards.", text)
            self.assertIn("root persona", text)
            self.assertLess(len(text), 3200)

    def test_root_gives_model_phase_selection_and_keeps_opening_small(self):
        root = get_pragya_root_system_instruction()
        self.assertLess(len(root), 2400)
        for phrase in ("You decide the phase", "switch_phase", "हाँ, दो मिनट बात करते हैं", "बुक कर दो"):
            self.assertIn(phrase, root)
        self.assertNotIn("scissor", root)
        self.assertEqual({s.name for s in SUPERCAR_TOOL_SCHEMAS}, {"switch_phase", "create_appointment_booking"})

    def test_visit_card_is_focused_and_carries_known_fields(self):
        text = format_supercar_prompt_card(get_pragya_phase_card("booking"), state={"pincode": "560048"})
        self.assertIn("Your only task now is\ncollecting PIN code, day and time.", text)
        self.assertIn("The car is optional", text)
        self.assertIn("PIN code 560048", text)
        self.assertIn("Still needed to book: day, time.", text)
        self.assertIn("create_appointment_booking", text)

    def test_confirmation_uses_actual_tool_result_and_allows_product_detour(self):
        text = format_supercar_prompt_card(get_pragya_phase_card("booked"))
        self.assertIn("successful booking tool result", text)
        self.assertIn("switch_phase(SOP_02_DISCOVERY)", text)
        self.assertIn("cannot cancel or reschedule", text)

    def test_empty_state_adds_no_extra_context(self):
        self.assertEqual(render_state_line(None), "")
        self.assertEqual(render_state_line({}), "")
