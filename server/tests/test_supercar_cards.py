"""Pragya's four phase cards and the one ALWAYS block they all carry."""

import unittest

from supercar_cards import (
    ALWAYS_BLOCK,
    PRAGYA_SUPERCAR_CARDS,
    format_supercar_prompt_card,
    get_pragya_phase_card,
    get_pragya_root_system_instruction,
)


class TestSupercarCards(unittest.TestCase):
    def test_one_card_per_call_state(self):
        """The deck is keyed by the tracker's phases, in call order."""
        expected = [
            "SOP_01_OPENING",
            "SOP_02_DISCOVERY",
            "SOP_03_PINCODE",
            "SOP_04_BOOKED",
        ]
        self.assertEqual(list(PRAGYA_SUPERCAR_CARDS), expected)
        for key in expected:
            card = PRAGYA_SUPERCAR_CARDS[key]
            self.assertEqual(card.persona_name, "Pragya")
            self.assertIn("Lamborghini", card.persona_role)

    def test_card_retrieval_by_aliases(self):
        self.assertEqual(
            get_pragya_phase_card("SOP_01_OPENING").phase_id, "SOP_01_OPENING"
        )
        self.assertEqual(get_pragya_phase_card("discovery").phase_id, "SOP_02_DISCOVERY")
        # Pricing is an answer, not a destination — it lives inside discovery.
        self.assertEqual(get_pragya_phase_card("pricing").phase_id, "SOP_02_DISCOVERY")
        self.assertEqual(get_pragya_phase_card("pincode").phase_id, "SOP_03_PINCODE")
        self.assertEqual(get_pragya_phase_card("booking").phase_id, "SOP_03_PINCODE")
        self.assertEqual(get_pragya_phase_card("booked").phase_id, "SOP_04_BOOKED")

    def test_every_blob_stays_lean(self):
        """~500 tokens is the budget; a card is re-billed on every later turn.

        Bound is in characters because this module has no tokenizer, but the
        ratio is stable: the largest card measures ~410 tokens.
        """
        for phase_id, card in PRAGYA_SUPERCAR_CARDS.items():
            blob = format_supercar_prompt_card(card)
            self.assertLess(len(blob), 2600, f"{phase_id} blob is getting fat")

    def test_discovery_names_only_the_current_lineup(self):
        card = get_pragya_phase_card("SOP_02_DISCOVERY")
        for model in ("Revuelto", "Urus SE", "Temerario"):
            self.assertIn(model, card.directive)

    def test_no_card_sells_a_discontinued_model(self):
        """She cannot show a car India no longer sells."""
        for phase_id, card in PRAGYA_SUPERCAR_CARDS.items():
            for retired in ("Gallardo", "Huracán", "Huracan", "Aventador"):
                self.assertNotIn(
                    retired, card.directive, f"{phase_id} still sells the {retired}"
                )

    def test_no_card_instructs_an_undeclared_tool_call(self):
        """`create_appointment_booking` is the only tool that exists."""
        for phase_id, card in PRAGYA_SUPERCAR_CARDS.items():
            formatted = format_supercar_prompt_card(card)
            for ghost in ("get_phase_card", "get_exp_center", "service_override("):
                self.assertNotIn(
                    ghost, formatted, f"{phase_id} calls the non-existent {ghost}"
                )

    def test_the_owner_in_trouble_override_rides_on_every_card(self):
        """A breakdown can be mentioned in any phase, so it cannot live in one."""
        for phase_id, card in PRAGYA_SUPERCAR_CARDS.items():
            formatted = format_supercar_prompt_card(card)
            self.assertIn("stop selling", formatted, phase_id)
            self.assertIn("Roadside Assistance", formatted, phase_id)

    def test_each_stage_ends_by_asking_permission_to_move_on(self):
        """The funnel advances on the caller's yes, not on a regex's whim."""
        for phase_id in ("SOP_01_OPENING", "SOP_02_DISCOVERY", "SOP_03_PINCODE"):
            self.assertIn("EXIT", PRAGYA_SUPERCAR_CARDS[phase_id].directive, phase_id)

    def test_opening_stage_only_checks_availability(self):
        """Pitching before they have agreed to listen is how a call gets cut."""
        directive = PRAGYA_SUPERCAR_CARDS["SOP_01_OPENING"].directive
        self.assertIn("callback", directive.lower())
        self.assertNotIn("crore", directive)

    def test_card_formatting_is_directive_then_constant(self):
        card = get_pragya_phase_card("SOP_01_OPENING")
        formatted = format_supercar_prompt_card(card, context="Inbound inquiry")
        self.assertTrue(formatted.startswith("[STAGE 1 OF 4"))
        self.assertIn("Inbound inquiry", formatted)
        self.assertTrue(formatted.endswith(ALWAYS_BLOCK))

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
