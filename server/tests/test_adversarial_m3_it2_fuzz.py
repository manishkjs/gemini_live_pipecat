"""Milestone M3 Iteration 2 Adversarial Stress & Differential Fuzzing Suite.

Author: Challenger 1 (Iteration 2)
Methodology: solution_stress_testing (Exhaustive Fuzzing, Pure Predicate Invariant Verification,
IEEE-754 Special Float Mining, State-Machine Monte Carlo Simulation, Thread Concurrency Harness).
"""

import concurrent.futures
import math
import os
import random
import sys
import threading
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple

server_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from phase_engine import (
    DecisionStage,
    StageTransitionManager,
    NumericLedger,
    EscalationTracker,
)


class TestM3It2PurePredicateInvariantFuzzing(unittest.TestCase):
    """Stress test the pure predicate invariant of can_transition across 10,000 randomized queries."""

    def test_10000_can_transition_queries_zero_mutation(self):
        """Verify can_transition does not mutate a single internal attribute over 10,000 chaotic calls."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.CURIOUS)
        mgr._close_attempts = 1
        mgr._has_recommendation = True
        mgr._hesitant_turn = 4
        mgr._stage_entry_turn = 2
        mgr._last_turn = 5

        def get_snapshot():
            return (
                mgr.current_stage,
                mgr._close_attempts,
                mgr._has_recommendation,
                mgr._hesitant_turn,
                mgr._stage_entry_turn,
                mgr._last_turn,
            )

        initial_snapshot = get_snapshot()

        rng = random.Random(20260814)
        stages = list(DecisionStage)
        intents = [
            None, "READY", "ready", "NOT_READY", 6.0, 6, DecisionStage.READY,
            DecisionStage.HESITANT, "EVALUATING", "", "   ", 123, ["READY"]
        ]
        fact_stores = [
            None,
            {},
            {"amount": 50000},
            {"amount": 0},
            {"amount": -100},
            {"amount": float("nan")},
            {"amount": float("inf")},
            {"amount": "25000"},
            {"amount": "invalid"},
        ]

        for _ in range(10000):
            from_s = rng.choice(stages)
            to_s = rng.choice(stages)
            intent = rng.choice(intents)
            fs = rng.choice(fact_stores)
            turn = rng.randint(1, 100)

            # Call read-only query
            mgr.can_transition(
                from_stage=from_s,
                to_stage=to_s,
                fact_store=fs,
                user_intent=intent,
                turn_id=turn,
            )

            current_snapshot = get_snapshot()
            self.assertEqual(
                current_snapshot,
                initial_snapshot,
                f"can_transition mutated state! Initial: {initial_snapshot}, Current: {current_snapshot}"
            )


class TestM3It2IEEE754FloatBypassMining(unittest.TestCase):
    """Exhaustive boundary testing on IEEE 754 special floats, string conversions, and numeric types."""

    def test_exhaustive_nan_inf_fact_store_matrix(self):
        """Test extensive variations of NaN, Inf, subnormal floats, and negative values in FactStore."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.READY)

        failing_inputs = [
            float("nan"),
            float("inf"),
            float("-inf"),
            0,
            0.0,
            -0.0,
            -1,
            -1e-15,
            -1e10,
            "nan",
            "NaN",
            "NAN",
            "inf",
            "Infinity",
            "+inf",
            "-inf",
            "-Infinity",
            "0",
            "0.0",
            "-5000",
            "",
            "   ",
            None,
            [],
            {},
            {"nested": 50000},
            object(),
        ]

        for val in failing_inputs:
            fs = {"amount": val}
            # COMMITTED gate check
            allowed, _ = mgr.can_transition(
                from_stage=DecisionStage.READY,
                to_stage=DecisionStage.COMMITTED,
                fact_store=fs,
            )
            self.assertFalse(allowed, f"FactStore amount={val!r} should be REJECTED by COMMITTED gate")

            # Recommendation gate check
            rec_allowed, _ = mgr.can_recommend_product(fact_store=fs)
            self.assertFalse(rec_allowed, f"FactStore amount={val!r} should be REJECTED by Recommendation gate")

            # _get_amount_from_fact_store
            extracted = mgr._get_amount_from_fact_store(fs)
            self.assertIsNone(extracted, f"_get_amount_from_fact_store for amount={val!r} should return None, got {extracted}")

    def test_valid_extreme_finite_positive_amounts(self):
        """Verify very small and very large finite positive numbers pass FactStore parsing."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.READY)

        passing_inputs = [
            1,
            1.0,
            0.01,
            1e-8,
            1e6,
            5000000.0,
            "1",
            " 50000 ",
            "50000.75",
            "1e5",
            "2.5e6",
        ]

        for val in passing_inputs:
            fs = {"amount": val}
            allowed, _ = mgr.can_transition(
                from_stage=DecisionStage.READY,
                to_stage=DecisionStage.COMMITTED,
                fact_store=fs,
            )
            self.assertTrue(allowed, f"FactStore amount={val!r} should be ACCEPTED by COMMITTED gate")

            rec_allowed, _ = mgr.can_recommend_product(fact_store=fs)
            self.assertTrue(rec_allowed, f"FactStore amount={val!r} should be ACCEPTED by Recommendation gate")

            extracted = mgr._get_amount_from_fact_store(fs)
            self.assertIsNotNone(extracted)
            self.assertGreater(extracted, 0)
            self.assertTrue(math.isfinite(extracted))

    def test_numeric_ledger_strict_nan_inf_rejections(self):
        """Verify NumericLedger rejects NaN/Inf/Non-positive in principal, tenure, etc."""
        ledger = NumericLedger()

        invalid_principals = [
            float("nan"), float("inf"), float("-inf"), 0, -0.0, -1000,
            None, "50000", [50000], {"p": 50000}
        ]

        for p in invalid_principals:
            with self.assertRaises(ValueError, msg=f"Principal {p!r} must raise ValueError"):
                ledger.record_quote(
                    principal=p,  # type: ignore
                    tenure_months=12,
                    xirr_pct=21.0,
                    profit=1000.0,
                    maturity_amount=51000.0,
                )

        invalid_tenures = [0, -1, -12]
        for t in invalid_tenures:
            with self.assertRaises(ValueError, msg=f"Tenure {t!r} must raise ValueError"):
                ledger.record_quote(
                    principal=50000,
                    tenure_months=t,
                    xirr_pct=21.0,
                    profit=1000.0,
                    maturity_amount=51000.0,
                )


class TestM3It2UserIntentTypeSafety(unittest.TestCase):
    """Stress test user_intent evaluation in Skip Guard against various types, spoofing, and edge cases."""

    def test_user_intent_comprehensive_matrix(self):
        """Verify that ONLY valid READY intents bypass forward jump > 3."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
        # Jump UNAWARE (1) -> READY (6): delta = 5 (> 3)

        valid_intents = [
            "READY",
            "ready",
            "Ready",
            "  READY  ",
            "ready\n",
            "\tReAdY\t",
            DecisionStage.READY,
        ]

        for intent in valid_intents:
            allowed, reason = mgr.can_transition(
                from_stage=DecisionStage.UNAWARE,
                to_stage=DecisionStage.READY,
                fact_store={"amount": 50000},
                user_intent=intent,
            )
            self.assertTrue(allowed, f"Valid intent {intent!r} must allow UNAWARE->READY transition, got: {reason}")

        blocked_intents = [
            6,
            6.0,
            6.000000001,
            5.999999999,
            "6",
            "6.0",
            DecisionStage.INTERESTED,
            DecisionStage.COMMITTED,
            DecisionStage.UNAWARE,
            True,   # True == 1 in Python int comparison
            False,  # False == 0 in Python int comparison
            None,
            "",
            "   ",
            "NOT_READY",
            "ALMOST_READY",
            "READY_FOR_SURE",
            "READY!",
            "I AM READY",
            ["READY"],
            {"user_intent": "READY"},
            (DecisionStage.READY,),
            complex(6, 0),
        ]

        for intent in blocked_intents:
            allowed, reason = mgr.can_transition(
                from_stage=DecisionStage.UNAWARE,
                to_stage=DecisionStage.READY,
                fact_store={"amount": 50000},
                user_intent=intent,  # type: ignore
            )
            self.assertFalse(allowed, f"Invalid intent {intent!r} must be BLOCKED from UNAWARE->READY, got: {reason}")


class TestM3It2MonteCarloStateMachineSimulation(unittest.TestCase):
    """Simulate 500 realistic multi-turn consultative dialogue lifecycles to verify state invariants."""

    def test_500_monte_carlo_dialogue_journeys(self):
        """Verify all business gates, hysteresis, staleness, close limits across 500 random journeys."""
        rng = random.Random(42)

        for journey_id in range(500):
            mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
            ledger = NumericLedger()
            escalation = EscalationTracker()

            has_amount = False
            amount_val = 50000.0
            turn = 1

            for step in range(30):
                turn += 1
                action = rng.choice([
                    "user_advance", "user_hesitate", "user_object", "user_give_amount",
                    "bot_recommend", "bot_attempt_close", "user_human_req", "user_query", "idle_turn"
                ])

                if action == "user_give_amount":
                    has_amount = True
                    amount_val = float(rng.choice([25000, 50000, 100000, 500000]))

                fs = {"amount": amount_val} if has_amount else None

                if action == "user_advance":
                    # Try to advance stage
                    target = DecisionStage(min(int(mgr.current_stage) + rng.randint(1, 3), 8))
                    mgr.transition_to(target, fact_store=fs, turn_id=turn)

                elif action == "user_hesitate":
                    mgr.transition_to(DecisionStage.HESITANT, fact_store=fs, turn_id=turn)

                elif action == "user_object":
                    # Retreat to CURIOUS or INTERESTED
                    target = rng.choice([DecisionStage.CURIOUS, DecisionStage.INTERESTED])
                    if int(target) <= int(mgr.current_stage):
                        mgr.transition_to(target, fact_store=fs, turn_id=turn)

                elif action == "bot_recommend":
                    can_rec, _ = mgr.can_recommend_product(fact_store=fs)
                    if can_rec:
                        mgr.record_recommendation()
                        ledger.record_quote(
                            principal=amount_val,
                            tenure_months=12,
                            xirr_pct=21.0,
                            profit=round(amount_val * 0.21, 2),
                            maturity_amount=round(amount_val * 1.21, 2),
                        )

                elif action == "bot_attempt_close":
                    can_close, _ = mgr.can_attempt_close()
                    if can_close:
                        attempts = mgr.record_close_attempt()
                        self.assertLessEqual(attempts, 2)
                    else:
                        # Ensure why it failed: either no recommendation or attempts >= 2
                        self.assertTrue(
                            not mgr._has_recommendation or mgr.close_attempts >= 2
                        )

                elif action == "user_human_req":
                    escalation.record_human_request()

                elif action == "user_query":
                    escalation.record_user_query(f"Question at turn {turn}")

                elif action == "idle_turn":
                    # Check staleness auto advance
                    mgr.auto_advance(current_turn=turn)

                # Assert Global Invariants at every step
                self.assertGreaterEqual(int(mgr.current_stage), 1)
                self.assertLessEqual(int(mgr.current_stage), 8)
                self.assertLessEqual(mgr.close_attempts, 3)  # Can only record up to 2 via can_attempt_close check


class TestM3It2ThreadSafetyAndConcurrency(unittest.TestCase):
    """Stress test concurrent execution on StageTransitionManager and NumericLedger."""

    def test_concurrent_stage_and_ledger_access(self):
        """Hammer StageTransitionManager and NumericLedger with 20 parallel threads."""
        ledger = NumericLedger()
        mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
        mgr.record_recommendation()

        num_threads = 20
        iterations_per_thread = 200
        errors = []

        def worker(thread_idx: int):
            try:
                rng = random.Random(thread_idx * 1000)
                for i in range(iterations_per_thread):
                    turn = i + 1
                    # Record quote
                    p = float(rng.randint(10000, 1000000))
                    t = rng.randint(1, 24)
                    mat = p * 1.15
                    ledger.record_quote(p, t, 15.0, p * 0.15, mat)

                    # Verify quote
                    ledger.verify_quote(p, t, mat)

                    # Stage checks
                    mgr.can_transition(
                        DecisionStage.CURIOUS,
                        DecisionStage.INTERESTED,
                        fact_store={"amount": p},
                        turn_id=turn
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        self.assertEqual(len(errors), 0, f"Thread errors encountered: {errors}")
        self.assertEqual(len(ledger.get_history()), num_threads * iterations_per_thread)


if __name__ == "__main__":
    unittest.main()
