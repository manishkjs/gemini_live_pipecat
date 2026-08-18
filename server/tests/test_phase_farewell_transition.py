import asyncio
import unittest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from phase_engine import ConsultativePhaseTracker, PHASE_PROMPT_CARDS
from system_prompt import INTENT_CLASSIFIER_SYSTEM_PROMPT

class TestPhaseFarewellAndFemaleGrammar(unittest.TestCase):

    def setUp(self):
        self.tracker = ConsultativePhaseTracker(gemini_service=None, enable_client_content=False)

    def test_farewell_transitions_to_phase_9(self):
        """Verify that saying 'bye', 'boy', 'alvida', 'thank you bye' in Phase 4/6/7/8 routes directly to Phase 9."""
        farewell_phrases = [
            "अच्छा ठीक है चलो थैंक यू बाय",
            "ok bye",
            "boy",
            "chalo bye",
            "alvida",
            "thank you bye",
            "theek hai bye",
            "baad mein baat karte hain",
        ]
        for phrase in farewell_phrases:
            self.tracker.current_phase = 4
            asyncio.run(self.tracker.handle_user_transcript(phrase))
            self.assertEqual(
                self.tracker.current_phase,
                9,
                f"Phrase '{phrase}' failed to transition to Phase 9 from Phase 4",
            )

    def test_opening_busy_stays_phase_1(self):
        """Verify that 'busy' on Turn 1 stays in Phase 1."""
        self.tracker.current_phase = 1
        asyncio.run(self.tracker.handle_user_transcript("I am busy right now, call back"))
        self.assertEqual(self.tracker.current_phase, 1)

    def test_prompt_cards_contain_female_grammar(self):
        """Verify that PHASE_PROMPT_CARDS[9] has context-aware validation."""
        card = PHASE_PROMPT_CARDS[9]
        self.assertIn("Commitment & Activation Close", card["title"])
        self.assertIn("Dynamically remind the customer", card["directive"])

    def test_classifier_prompt_disambiguation(self):
        """Verify that INTENT_CLASSIFIER_SYSTEM_PROMPT explicitly specifies Phase 1 vs Phase 9 routing."""
        self.assertIn("INITIAL OPENING GREETING ONLY", INTENT_CLASSIFIER_SYSTEM_PROMPT)
        self.assertIn("NEVER route to Phase 1 mid-call or during farewells", INTENT_CLASSIFIER_SYSTEM_PROMPT)
        self.assertIn("Farewell & Wrap-Up Invariant", INTENT_CLASSIFIER_SYSTEM_PROMPT)

if __name__ == "__main__":
    unittest.main()
