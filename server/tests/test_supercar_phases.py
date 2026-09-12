"""Unit tests for the deterministic, zero-token Pragya phase tracker."""

import unittest

from supercar_phases import (
    PRAGYA_PHASES,
    SOP_01_OPENING,
    SOP_02_DISCOVERY,
    SOP_03_PINCODE,
    SOP_04_BOOKED,
    PragyaPhaseTracker,
    detect_phase,
    normalize_for_pincode,
)


class TestPincodeNormalization(unittest.TestCase):
    def test_spaced_digits_collapse(self):
        self.assertIn("110037", normalize_for_pincode("mera pin 1 1 0 0 3 7 hai"))

    def test_spoken_english_digits_collapse(self):
        self.assertIn(
            "110037",
            normalize_for_pincode("one one zero zero three seven"),
        )

    def test_spoken_hindi_digits_collapse(self):
        self.assertIn("110037", normalize_for_pincode("एक एक शून्य शून्य तीन सात"))

    def test_hyphenated_pincode_collapses(self):
        self.assertIn("110037", normalize_for_pincode("110-037"))


class TestPhaseDetection(unittest.TestCase):
    def test_bare_pincode_reaches_phase_three(self):
        self.assertEqual(detect_phase("400051"), SOP_03_PINCODE)

    def test_spoken_pincode_reaches_phase_three(self):
        self.assertEqual(
            detect_phase("mera pincode hai 5 6 0 0 0 1"), SOP_03_PINCODE
        )

    def test_incidental_city_is_not_visit_intent(self):
        for city in ["Delhi", "mumbai", "Bengaluru", "Aerocity", "BKC"]:
            self.assertIsNone(detect_phase(f"main {city} mein rehta hoon"), city)
            self.assertEqual(detect_phase(f"Is the Urus comfortable in {city} traffic?"), SOP_02_DISCOVERY)

    def test_the_word_pincode_alone_reaches_phase_three(self):
        self.assertEqual(detect_phase("mera pin code bataun kya?"), SOP_03_PINCODE)

    def test_model_talk_reaches_phase_two(self):
        for cue in ["Revuelto", "Urus SE", "Temerario", "kitne ka hai"]:
            self.assertEqual(detect_phase(f"mujhe {cue} ke baare mein batao"), SOP_02_DISCOVERY, cue)

    def test_asking_to_book_reaches_phase_three_directly(self):
        """Stage 3 is where prerequisites get collected, not a reward for
        having sat through the pitch. Someone who opens with "book me a visit"
        should land there without being walked through discovery first.
        """
        for cue in [
            "can I book a visit",
            "mujhe test drive karni hai",
            "schedule an appointment please",
            "मुझे अपॉइंटमेंट चाहिए",
        ]:
            self.assertEqual(detect_phase(cue), SOP_03_PINCODE, cue)

    def test_pincode_outranks_model_talk_in_the_same_sentence(self):
        """The furthest signal wins; a PIN code is a stronger buying signal."""
        self.assertEqual(
            detect_phase("Revuelto dekhni hai, mera pincode 110037 hai"),
            SOP_03_PINCODE,
        )

    def test_small_talk_moves_nothing(self):
        for chatter in ["haan ji", "theek hai", "namaste", "", "   "]:
            self.assertIsNone(detect_phase(chatter), chatter)

    def test_a_phone_number_is_not_mistaken_for_a_pincode(self):
        """Ten digits is a phone number. Only an exact six-digit run is a PIN."""
        self.assertNotEqual(detect_phase("9876543210"), SOP_03_PINCODE)


class TestTrackerProgression(unittest.TestCase):
    def test_starts_at_opening(self):
        self.assertEqual(PragyaPhaseTracker().current_phase, SOP_01_OPENING)

    def test_walks_the_funnel_forward(self):
        tracker = PragyaPhaseTracker()
        self.assertEqual(tracker.observe_user_text("Revuelto ke specs batao"), SOP_02_DISCOVERY)
        self.assertEqual(tracker.observe_user_text("mera pincode 110037"), SOP_03_PINCODE)
        self.assertEqual(tracker.observe_booking_confirmed(), SOP_04_BOOKED)

    def test_can_skip_straight_to_pincode(self):
        """An explicit visit request can skip discovery."""
        tracker = PragyaPhaseTracker()
        self.assertEqual(tracker.observe_user_text("Book a visit in Mumbai"), SOP_03_PINCODE)

    def test_returns_to_current_topic_without_losing_milestone(self):
        tracker = PragyaPhaseTracker()
        tracker.observe_user_text("pincode 400051")
        self.assertEqual(tracker.observe_user_text("aur Urus ka engine kaisa hai?"), SOP_02_DISCOVERY)
        self.assertEqual(tracker.current_phase, SOP_02_DISCOVERY)
        self.assertEqual(tracker.furthest_phase, SOP_03_PINCODE)

    def test_refusal_beats_booking_words_in_both_languages(self):
        for speech in ["Don't book anything; just tell me about the Urus", "I am not interested in a test drive", "abhi booking nahi karni", "अभी बुकिंग नहीं करनी"]:
            tracker = PragyaPhaseTracker()
            tracker.observe_user_text("PIN 400051")
            self.assertEqual(tracker.observe_user_text(speech), SOP_02_DISCOVERY, speech)

    def test_latest_explicit_topic_wins(self):
        self.assertEqual(detect_phase("My PIN is 560048. Actually, tell me about the Revuelto engine"), SOP_02_DISCOVERY)
        self.assertEqual(detect_phase("I like the Urus, but book a visit please"), SOP_03_PINCODE)

    def test_opening_acceptance_is_contextual(self):
        for speech in ["Yes, I have two minutes", "haan bataiye", "हाँ बताइए"]:
            tracker = PragyaPhaseTracker()
            self.assertEqual(tracker.observe_user_text(speech), SOP_02_DISCOVERY)
            tracker.observe_user_text("PIN 560048")
            self.assertIsNone(tracker.observe_user_text(speech))
            self.assertEqual(tracker.current_phase, SOP_03_PINCODE)

    def test_booking_survives_product_detour_and_reference_question(self):
        tracker = PragyaPhaseTracker()
        tracker.observe_booking_confirmed()
        self.assertEqual(tracker.observe_user_text("Tell me about the Revuelto engine"), SOP_02_DISCOVERY)
        self.assertTrue(tracker.booking_confirmed)
        self.assertEqual(tracker.furthest_phase, SOP_04_BOOKED)
        self.assertEqual(tracker.observe_user_text("What is my booking reference?"), SOP_04_BOOKED)
        self.assertEqual(tracker.observe_user_text("Reschedule my appointment"), SOP_03_PINCODE)

    def test_repeating_a_phase_signal_emits_no_second_transition(self):
        """Only genuine changes are announced, so the UI does not flicker."""
        tracker = PragyaPhaseTracker()
        self.assertEqual(tracker.observe_user_text("Urus dekhni hai"), SOP_02_DISCOVERY)
        self.assertIsNone(tracker.observe_user_text("haan Urus hi"))

    def test_booking_is_the_only_route_to_the_final_phase(self):
        """Agreeing to visit is not a booking; only an executed booking is."""
        tracker = PragyaPhaseTracker()
        tracker.observe_user_text("haan main Saturday ko aa jaunga, book kar do")
        self.assertNotEqual(tracker.current_phase, SOP_04_BOOKED)
        tracker.observe_booking_confirmed()
        self.assertEqual(tracker.current_phase, SOP_04_BOOKED)

    def test_phase_definitions_are_contiguous_and_ordered(self):
        self.assertEqual([p.index for p in PRAGYA_PHASES], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
