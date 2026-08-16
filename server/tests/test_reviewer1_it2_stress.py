"""Independent Adversarial Verification by Reviewer 1 (Iteration 2).
"""
import math
import unittest
from phase_engine import (
    DecisionStage,
    StageTransitionManager,
    NumericLedger,
    EscalationTracker,
)

class TestReviewerM3IndependentStress(unittest.TestCase):

    def test_pure_predicate_zero_mutation(self):
        """Verify calling can_transition on HESITANT or any stage causes 0 state mutation."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.CURIOUS)
        initial_dict = dict(mgr.__dict__)

        # Evaluate transition to HESITANT
        allowed, reason = mgr.can_transition(
            from_stage=DecisionStage.CURIOUS,
            to_stage=DecisionStage.HESITANT,
            fact_store={"amount": 50000},
            turn_id=5
        )
        self.assertTrue(allowed)
        # Verify hesitant_entered_turn is STILL None because transition_to was not called
        self.assertIsNone(mgr.hesitant_entered_turn)
        self.assertEqual(mgr.__dict__, initial_dict)

        # Call can_transition 100 times with different parameters
        for turn in range(1, 101):
            for stage in DecisionStage:
                mgr.can_transition(
                    from_stage=mgr.current_stage,
                    to_stage=stage,
                    fact_store={"amount": turn * 1000},
                    user_intent="READY",
                    turn_id=turn
                )
        self.assertEqual(mgr.__dict__, initial_dict)

    def test_nan_inf_in_fact_store_committed_gate(self):
        """Verify NaN, Inf, -Inf, 0, -1 in FactStore are rejected at COMMITTED gate."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.READY)

        bad_values = [
            float("nan"),
            float("inf"),
            float("-inf"),
            0,
            0.0,
            -0.0,
            -500,
            -1e-9,
            "nan",
            "inf",
            "-inf",
            "0",
            "-100",
            None,
            [],
            {},
        ]

        for bad in bad_values:
            allowed, reason = mgr.can_transition(
                from_stage=DecisionStage.READY,
                to_stage=DecisionStage.COMMITTED,
                fact_store={"amount": bad},
                turn_id=1
            )
            self.assertFalse(allowed, f"Amount {bad!r} should be blocked at COMMITTED gate, but got reason: {reason}")
            self.assertIn("COMMITTED Gate", reason)

    def test_nan_inf_in_numeric_ledger(self):
        """Verify NumericLedger rejects NaN, Inf, <= 0, > 50L."""
        ledger = NumericLedger()

        invalid_principals = [
            float("nan"),
            float("inf"),
            float("-inf"),
            0,
            -100,
            -0.0001,
            5000000.01,
            1e10,
            "50000",
            None,
            [50000],
        ]

        for p in invalid_principals:
            with self.assertRaises(ValueError, msg=f"Principal {p!r} must raise ValueError"):
                ledger.record_quote(
                    principal=p,
                    tenure_months=6,
                    xirr_pct=18.0,
                    profit=4500,
                    maturity_amount=54500
                )

        # Valid principal must succeed
        quote = ledger.record_quote(
            principal=5000000.0,  # exactly ₹50 Lakhs
            tenure_months=12,
            xirr_pct=24.0,
            profit=1200000.0,
            maturity_amount=6200000.0
        )
        self.assertEqual(quote["principal"], 5000000.0)
        self.assertTrue(ledger.verify_quote(5000000.0, 12, 6200000.0))

    def test_user_intent_strict_type_checking(self):
        """Verify only genuine string 'READY' or DecisionStage.READY bypass the skip guard."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)

        # Delta = 5 (UNAWARE -> READY)
        # Attempt spoofing with numeric 6, 6.0, True, other objects
        spoofed_intents = [
            6,
            6.0,
            True,
            False,
            [6],
            {"stage": 6},
            "COMMITTED",
            "HESITANT",
            "1",
            "6",
            None,
        ]

        for spoof in spoofed_intents:
            allowed, reason = mgr.can_transition(
                from_stage=DecisionStage.UNAWARE,
                to_stage=DecisionStage.READY,
                fact_store={"amount": 50000},
                user_intent=spoof,
                turn_id=1
            )
            self.assertFalse(allowed, f"Spoofed intent {spoof!r} must be blocked by Skip Guard")
            self.assertIn("Skip Guard", reason)

        # Genuine ready intents
        valid_intents = [
            "READY",
            "ready",
            "Ready",
            " ready ",
            "READY\n",
            DecisionStage.READY,
        ]
        for valid in valid_intents:
            allowed, reason = mgr.can_transition(
                from_stage=DecisionStage.UNAWARE,
                to_stage=DecisionStage.READY,
                fact_store={"amount": 50000},
                user_intent=valid,
                turn_id=1
            )
            self.assertTrue(allowed, f"Valid intent {valid!r} must allow skip")

    def test_hysteresis_and_staleness_lifecycle(self):
        """Test full hysteresis cooldown and staleness auto-advance."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.EVALUATING)

        # Transition to HESITANT at turn 10
        self.assertTrue(mgr.transition_to(DecisionStage.HESITANT, turn_id=10))
        self.assertEqual(mgr.hesitant_entered_turn, 10)

        # At turn 11 (elapsed=1 <= 2), attempt jump back to EVALUATING/READY
        allowed, reason = mgr.can_transition(DecisionStage.HESITANT, DecisionStage.EVALUATING, turn_id=11)
        self.assertFalse(allowed)
        self.assertIn("Hysteresis Guard", reason)

        # At turn 12 (elapsed=2 <= 2), still in cooldown while in HESITANT
        allowed, reason = mgr.can_transition(DecisionStage.HESITANT, DecisionStage.EVALUATING, turn_id=12)
        self.assertFalse(allowed)

        # At turn 13 (elapsed=3 > 2), cooldown clears
        allowed, reason = mgr.can_transition(DecisionStage.HESITANT, DecisionStage.EVALUATING, turn_id=13)
        self.assertTrue(allowed)
        self.assertTrue(mgr.transition_to(DecisionStage.EVALUATING, turn_id=13))

        # Staleness test: entered EVALUATING at turn 13
        self.assertFalse(mgr.check_staleness(17)) # 17 - 13 = 4 turns (< 5)
        self.assertTrue(mgr.check_staleness(18))  # 18 - 13 = 5 turns (>= 5)
        advanced = mgr.auto_advance(18)
        self.assertEqual(advanced, DecisionStage.HESITANT)
        self.assertEqual(mgr.current_stage, DecisionStage.HESITANT)

    def test_close_limiter_gate(self):
        """Test close limiter requires prior recommendation and enforces 2-attempt cap."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.READY)

        # Cannot close without recommendation
        can_close, reason = mgr.can_attempt_close()
        self.assertFalse(can_close)
        self.assertIn("Prior product recommendation required", reason)

        # Record recommendation
        mgr.record_recommendation()
        can_close, reason = mgr.can_attempt_close()
        self.assertTrue(can_close)

        # Attempt 1
        self.assertEqual(mgr.record_close_attempt(), 1)
        can_close, _ = mgr.can_attempt_close()
        self.assertTrue(can_close)

        # Attempt 2
        self.assertEqual(mgr.record_close_attempt(), 2)
        can_close, reason = mgr.can_attempt_close()
        self.assertFalse(can_close)
        self.assertIn("Maximum close attempts (2) reached", reason)

    def test_escalation_matrix(self):
        """Verify 5-tier escalation matrix and callback requirements."""
        tracker = EscalationTracker()
        self.assertEqual(tracker.get_escalation_tier(), 1)
        self.assertFalse(tracker.is_callback_booking_required())

        # 1 user query -> Tier 2
        tracker.record_user_query("What is P2P?")
        self.assertEqual(tracker.get_escalation_tier(), 2)
        self.assertFalse(tracker.is_callback_booking_required())

        # 2 user queries -> Tier 3
        tracker.record_user_query("What is the interest rate?")
        self.assertEqual(tracker.get_escalation_tier(), 3)
        self.assertFalse(tracker.is_callback_booking_required())

        # 1 human request -> Tier 4
        tracker.record_human_request()
        self.assertEqual(tracker.get_escalation_tier(), 4)
        self.assertFalse(tracker.is_callback_booking_required())

        # 2nd human request -> Tier 5 (Callback required)
        tracker.record_human_request()
        self.assertEqual(tracker.get_escalation_tier(), 5)
        self.assertTrue(tracker.is_callback_booking_required())

if __name__ == "__main__":
    unittest.main()
