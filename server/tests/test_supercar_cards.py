"""Pragya's three stage cards and the one ALWAYS block they all carry."""

import unittest

from supercar_cards import (
    ALWAYS_BLOCK,
    PRAGYA_SUPERCAR_CARDS,
    format_supercar_prompt_card,
    get_pragya_phase_card,
    get_pragya_root_system_instruction,
    render_state_line,
)


class TestSupercarCards(unittest.TestCase):
    def test_one_card_per_injectable_call_state(self):
        """Three cards, in call order. Stage one is the system instruction."""
        expected = ["SOP_02_DISCOVERY", "SOP_03_PINCODE", "SOP_04_BOOKED"]
        self.assertEqual(list(PRAGYA_SUPERCAR_CARDS), expected)
        for key in expected:
            card = PRAGYA_SUPERCAR_CARDS[key]
            self.assertEqual(card.persona_name, "Pragya")
            self.assertIn("Lamborghini", card.persona_role)

    def test_the_opening_has_no_card(self):
        """She is already speaking by the time a card could arrive.

        A card that can never be delivered is a second version of the truth,
        free to drift away from the system instruction that is actually used.
        """
        self.assertNotIn("SOP_01_OPENING", PRAGYA_SUPERCAR_CARDS)
        self.assertIsNone(get_pragya_phase_card("SOP_01_OPENING"))

    def test_card_retrieval_by_aliases(self):
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
        """A breakdown can be mentioned in any stage, so it cannot live in one."""
        for phase_id, card in PRAGYA_SUPERCAR_CARDS.items():
            formatted = format_supercar_prompt_card(card)
            self.assertIn("the selling stops", formatted, phase_id)
            self.assertIn("Roadside Assistance", formatted, phase_id)

    def test_nothing_in_the_deck_is_phrased_as_a_prohibition(self):
        """A "never say X" spends tokens naming X and primes the model with it.

        Checked on whole words so that "whenever" and "Lounge revert" style
        substrings cannot produce a false positive.
        """
        import re

        banned = re.compile(r"\b(never|do not|don't|avoid)\b", re.IGNORECASE)
        blobs = {p: format_supercar_prompt_card(c) for p, c in PRAGYA_SUPERCAR_CARDS.items()}
        blobs["ROOT"] = get_pragya_root_system_instruction()
        for name, blob in blobs.items():
            found = banned.findall(blob)
            self.assertEqual(found, [], f"{name} still prohibits: {found}")

    def test_the_caller_chooses_the_destination(self):
        """The deck must not tell her to finish a stage before starting another.

        The rigid version marched a caller who had already said "just book me
        in" back through the pitch.
        """
        self.assertIn("The caller decides where this goes", ALWAYS_BLOCK)
        self.assertIn("ask only for what is still missing", ALWAYS_BLOCK)

    def test_organising_the_visit_treats_the_car_as_optional(self):
        """A showroom visit is exactly how an undecided buyer decides."""
        directive = PRAGYA_SUPERCAR_CARDS["SOP_03_PINCODE"].directive
        self.assertIn("The car is optional", directive)
        self.assertIn("PIN code", directive)

    def test_the_booked_card_lets_the_caller_circle_back(self):
        """Observed live: she held a wrap-up card while he asked about engines."""
        directive = PRAGYA_SUPERCAR_CARDS["SOP_04_BOOKED"].directive
        self.assertIn("circle back", directive)

    def test_card_formatting_is_directive_then_constant(self):
        card = get_pragya_phase_card("SOP_02_DISCOVERY")
        formatted = format_supercar_prompt_card(card, context="Inbound inquiry")
        self.assertTrue(formatted.startswith("[STAGE 2 OF 4"))
        self.assertIn("Inbound inquiry", formatted)
        self.assertTrue(formatted.endswith(ALWAYS_BLOCK))

    def test_a_card_carries_what_the_caller_already_said(self):
        """Re-asking for a PIN code she was just given is the robot tell."""
        card = get_pragya_phase_card("SOP_03_PINCODE")
        formatted = format_supercar_prompt_card(
            card, state={"pincode": "560048", "car_choice": "Temerario"}
        )
        self.assertIn("PIN code 560048", formatted)
        self.assertIn("car Temerario", formatted)
        self.assertIn("Still needed to book: day, time.", formatted)

    def test_state_rendering_is_silent_when_nothing_is_known(self):
        """An empty state must not add noise to the card."""
        self.assertEqual(render_state_line(None), "")
        self.assertEqual(render_state_line({}), "")

    def test_lean_root_system_instruction_length(self):
        root_prompt = get_pragya_root_system_instruction()
        self.assertLess(len(root_prompt), 1600)
        self.assertIn("Pragya", root_prompt)
        self.assertIn("Lamborghini India", root_prompt)
        self.assertIn("create_appointment_booking", root_prompt)

    def test_root_prompt_presses_once_before_taking_a_callback(self):
        """A soft "no" is an objection. The instruction says so in the positive."""
        root = get_pragya_root_system_instruction()
        self.assertIn("press once warmly", root)
        self.assertIn("callback", root)


if __name__ == "__main__":
    unittest.main()
