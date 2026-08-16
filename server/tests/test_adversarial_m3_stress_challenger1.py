"""Adversarial Empirical Stress Test Suite for Milestone M3.

Author: Challenger 1 (Specialist / Critic)
Methodology: solution_stress_testing (Differential Fuzzing, Edge Case Matrix, Property Invariant Checking)

Tests:
1. DecisionStage & StageTransitionManager (All 64 stage permutations, intent variations, skip deltas)
2. Empirical Proof of Bugs / Vulnerabilities:
   - Bug A: Mutating side-effect in can_transition(to_stage=HESITANT)
   - Bug B: IntEnum numeric/float equality bypass for user_intent
   - Bug C: NaN floating point handling in FactStore & NumericLedger
3. Hysteresis Guard & Turn Arithmetic (Cooldown window, rapid oscillations, backward/forward turns)
4. Staleness Guard & Auto-Advance Invariants (Stagnation thresholds, multi-step auto advance, Disengaged cap)
5. FactStore Extraction & Boundary Amounts (Dict, getter, attribute, types, negative, zero, extreme)
6. Close Limiter & Recommendation Gates (Pre-requisites, attempt caps, state reset)
7. NumericLedger High-Volume Fuzzing & Tolerance Boundaries (5000 quotes, precision, quote overrides, RBI ceiling)
8. EscalationTracker Differential Oracle Fuzzing (All (H, Q) permutations, sequence orderings, callback thresholds)
"""

import math
import os
import random
import sys
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


class MockFactStoreDict:
    def __init__(self, amount: Any):
        self._data = {"amount": amount}
    def get(self, key: str, default=None):
        return self._data.get(key, default)


class MockFactStoreGetter:
    def __init__(self, amount: Any):
        self._amount = amount
    def get_fact(self, key: str) -> Any:
        return self._amount if key == "amount" else None


class MockFactStoreAttr:
    def __init__(self, amount: Any):
        self.amount = amount


class MockFactStoreNestedFacts:
    def __init__(self, amount: Any):
        self.facts = {"amount": amount}


class TestM3StageTransitionPermutationsAdversarial(unittest.TestCase):
    """Stress test all 64 stage transition permutations against skip and business gates."""

    def test_all_64_stage_transition_permutations_isolated(self):
        """Exhaustively verify all 8x8 stage transitions on isolated managers without READY intent."""
        fact_store = {"amount": 50000}

        for from_s in DecisionStage:
            for to_s in DecisionStage:
                # Use fresh instance for pure predicate isolation
                mgr = StageTransitionManager(initial_stage=from_s)
                delta = int(to_s) - int(from_s)
                allowed, reason = mgr.can_transition(
                    from_stage=from_s,
                    to_stage=to_s,
                    fact_store=fact_store,
                    user_intent=None,
                    turn_id=10,
                )
                if from_s == to_s:
                    self.assertTrue(allowed, f"Self-transition {from_s}->{to_s} must be allowed")
                elif delta > 3:
                    self.assertFalse(
                        allowed,
                        f"Forward jump of delta={delta} ({from_s.name}->{to_s.name}) without READY intent must be blocked"
                    )
                elif delta <= 3:
                    self.assertTrue(
                        allowed,
                        f"Jump of delta={delta} ({from_s.name}->{to_s.name}) should be allowed with valid amount"
                    )

    def test_all_64_stage_transition_permutations_with_ready_intent_isolated(self):
        """Exhaustively verify all 8x8 stage transitions on isolated managers WITH READY intent."""
        fact_store = {"amount": 50000}
        ready_intents = ["READY", "ready", "Ready", "ReAdY", DecisionStage.READY]

        for intent in ready_intents:
            for from_s in DecisionStage:
                for to_s in DecisionStage:
                    mgr = StageTransitionManager(initial_stage=from_s)
                    allowed, reason = mgr.can_transition(
                        from_stage=from_s,
                        to_stage=to_s,
                        fact_store=fact_store,
                        user_intent=intent,
                        turn_id=10,
                    )
                    self.assertTrue(
                        allowed,
                        f"Transition {from_s.name}->{to_s.name} with intent '{intent}' should be allowed"
                    )

    def test_invalid_string_intents_do_not_bypass_skip_guard(self):
        """Adversarially probe invalid intent strings that attempt to spoof READY."""
        fact_store = {"amount": 50000}

        spoofed_intents = [
            "NOT_READY", "ALMOST_READY", "READY_TO_INVEST", "READY123",
            "COMMITTED", "EVALUATING", "DISENGAGED", "1", "6", None, "", "   ",
            123, ["READY"], {"intent": "READY"}
        ]

        for intent in spoofed_intents:
            mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
            allowed, reason = mgr.can_transition(
                from_stage=DecisionStage.UNAWARE,
                to_stage=DecisionStage.READY,
                fact_store=fact_store,
                user_intent=intent,
                turn_id=10,
            )
            self.assertFalse(
                allowed,
                f"Spoofed intent '{intent}' should NOT bypass skip guard for UNAWARE->READY"
            )

    def test_negative_stage_jumps_are_always_permitted_isolated(self):
        """Verify backward stage transitions (delta < 0) are never blocked by skip guard."""
        fact_store = {"amount": 50000}

        for from_s in DecisionStage:
            for to_s in DecisionStage:
                if int(to_s) < int(from_s):
                    mgr = StageTransitionManager(initial_stage=from_s)
                    allowed, reason = mgr.can_transition(
                        from_stage=from_s,
                        to_stage=to_s,
                        fact_store=fact_store,
                        user_intent=None,
                        turn_id=10,
                    )
                    self.assertTrue(
                        allowed,
                        f"Backward transition {from_s.name} -> {to_s.name} (delta={int(to_s)-int(from_s)}) must be allowed"
                    )


class TestM3EmpiricalBugFindings(unittest.TestCase):
    """Empirically verify fixes for bugs found during adversarial stress testing."""

    def test_bug_can_transition_mutates_hesitant_turn_side_effect(self):
        """Verify that can_transition does NOT mutate _hesitant_turn as a read-only query function.
        
        A read-only query function (can_transition) must NOT mutate internal state.
        When can_transition(..., HESITANT) is evaluated, _hesitant_turn must remain None until transition_to is called.
        """
        mgr = StageTransitionManager(initial_stage=DecisionStage.INTERESTED)
        self.assertIsNone(mgr._hesitant_turn)

        # Call can_transition for HESITANT without calling transition_to
        # INTERESTED (3) -> HESITANT (5): delta = 2 (allowed by Skip Guard)
        allowed, reason = mgr.can_transition(
            from_stage=DecisionStage.INTERESTED,
            to_stage=DecisionStage.HESITANT,
            fact_store={"amount": 50000},
            turn_id=5,
        )
        self.assertTrue(allowed, f"INTERESTED->HESITANT should be allowed, got: {reason}")

        # FIX VERIFICATION: _hesitant_turn is NOT mutated on read-only check
        self.assertIsNone(mgr._hesitant_turn, "can_transition must not mutate _hesitant_turn on query")

        # Downstream query to EVALUATING at turn 5 is allowed because no hysteresis cooldown was activated
        allowed_eval, reason_eval = mgr.can_transition(
            from_stage=DecisionStage.UNAWARE,
            to_stage=DecisionStage.EVALUATING,
            fact_store={"amount": 50000},
            turn_id=5,
        )
        self.assertTrue(
            allowed_eval,
            f"Downstream query to EVALUATING should be allowed, got: {reason_eval}"
        )

    def test_bug_intenum_float_equality_intent_bypass(self):
        """Verify that passing float 6.0 does NOT bypass the skip guard."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
        # UNAWARE (1) -> READY (6): delta = 5.
        # Passing 6.0 as user_intent must NOT bypass skip guard
        allowed, reason = mgr.can_transition(
            from_stage=DecisionStage.UNAWARE,
            to_stage=DecisionStage.READY,
            fact_store={"amount": 50000},
            user_intent=6.0,
            turn_id=10,
        )
        self.assertFalse(allowed, "Float 6.0 must NOT bypass skip guard")

    def test_boundary_nan_amount_in_fact_store(self):
        """Verify float('nan') is rejected in FactStore amount checks."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.READY)
        nan_store = {"amount": float("nan")}

        # float('nan') must be rejected by COMMITTED gate
        allowed_comm, reason_comm = mgr.can_transition(
            DecisionStage.READY, DecisionStage.COMMITTED, fact_store=nan_store
        )
        self.assertFalse(allowed_comm, "NaN amount must be rejected by COMMITTED gate")


class TestM3HysteresisAndStalenessStress(unittest.TestCase):
    """Stress test Hysteresis cooldown and Staleness auto-advance under chaotic turn sequences."""

    def test_hysteresis_cooldown_with_fuzzed_turn_sequences(self):
        """Fuzz turn sequences around HESITANT to verify exact 2-turn cooldown boundary."""
        fact_store = {"amount": 50000}
        base_turns = [1, 5, 10, 50, 100, 999, 10000]

        for base_t in base_turns:
            mgr = StageTransitionManager(initial_stage=DecisionStage.EVALUATING)
            mgr.transition_to(DecisionStage.HESITANT, fact_store, turn_id=base_t)
            self.assertEqual(mgr.hesitant_entered_turn, base_t)

            for target in [DecisionStage.EVALUATING, DecisionStage.READY, DecisionStage.COMMITTED]:
                # Turn elapsed = 0 (same turn): blocked
                self.assertFalse(mgr.can_transition(DecisionStage.HESITANT, target, fact_store, turn_id=base_t)[0])
                # Turn elapsed = 1: blocked
                self.assertFalse(mgr.can_transition(DecisionStage.HESITANT, target, fact_store, turn_id=base_t + 1)[0])
                # Turn elapsed = 2: blocked
                self.assertFalse(mgr.can_transition(DecisionStage.HESITANT, target, fact_store, turn_id=base_t + 2)[0])
                # Turn elapsed = 3: allowed!
                self.assertTrue(mgr.can_transition(DecisionStage.HESITANT, target, fact_store, turn_id=base_t + 3)[0])
                # Turn elapsed = 100: allowed!
                self.assertTrue(mgr.can_transition(DecisionStage.HESITANT, target, fact_store, turn_id=base_t + 100)[0])

    def test_hysteresis_allows_non_closing_transitions(self):
        """Verify HESITANT allows retreating to CURIOUS / INTERESTED / DISENGAGED during cooldown."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.EVALUATING)
        fact_store = {"amount": 50000}

        mgr.transition_to(DecisionStage.HESITANT, fact_store, turn_id=10)

        # Elapsed = 1 (Turn 11): CURIOUS, INTERESTED, DISENGAGED must be allowed
        self.assertTrue(mgr.can_transition(DecisionStage.HESITANT, DecisionStage.CURIOUS, fact_store, turn_id=11)[0])
        self.assertTrue(mgr.can_transition(DecisionStage.HESITANT, DecisionStage.INTERESTED, fact_store, turn_id=11)[0])
        self.assertTrue(mgr.can_transition(DecisionStage.HESITANT, DecisionStage.DISENGAGED, fact_store, turn_id=11)[0])

    def test_rapid_hesitant_reentry_resets_cooldown(self):
        """Verify re-entering HESITANT resets cooldown timer to the newer turn."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.EVALUATING)
        fact_store = {"amount": 50000}

        # Turn 10: Enter HESITANT
        mgr.transition_to(DecisionStage.HESITANT, fact_store, turn_id=10)
        self.assertEqual(mgr.hesitant_entered_turn, 10)

        # Turn 13: Cooldown expired, transition to CURIOUS
        self.assertTrue(mgr.transition_to(DecisionStage.CURIOUS, fact_store, turn_id=13))

        # Turn 20: Re-enter HESITANT
        self.assertTrue(mgr.transition_to(DecisionStage.HESITANT, fact_store, turn_id=20))
        self.assertEqual(mgr.hesitant_entered_turn, 20)

        # Turn 21 (elapsed 1 from turn 20): EVALUATING must be blocked
        self.assertFalse(mgr.can_transition(DecisionStage.HESITANT, DecisionStage.EVALUATING, fact_store, turn_id=21)[0])
        # Turn 22 (elapsed 2 from turn 20): EVALUATING must be blocked
        self.assertFalse(mgr.can_transition(DecisionStage.HESITANT, DecisionStage.EVALUATING, fact_store, turn_id=22)[0])
        # Turn 23 (elapsed 3 from turn 20): EVALUATING allowed
        self.assertTrue(mgr.can_transition(DecisionStage.HESITANT, DecisionStage.EVALUATING, fact_store, turn_id=23)[0])

    def test_staleness_sweep_and_disengaged_cap(self):
        """Verify staleness threshold across all stages and verify auto_advance caps at DISENGAGED."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
        # Entry at turn 1

        # Turns 1..5: elapsed 0..4 -> check_staleness False
        for t in range(1, 6):
            self.assertFalse(mgr.check_staleness(current_turn=t))
            self.assertIsNone(mgr.auto_advance(current_turn=t))

        # Turn 6: elapsed 5 -> check_staleness True -> auto_advance to CURIOUS (2)
        self.assertTrue(mgr.check_staleness(current_turn=6))
        adv1 = mgr.auto_advance(current_turn=6)
        self.assertEqual(adv1, DecisionStage.CURIOUS)
        self.assertEqual(mgr.current_stage, DecisionStage.CURIOUS)
        self.assertEqual(mgr._stage_entry_turn, 6)

        # Stagnate in CURIOUS until turn 11 (elapsed 5 from turn 6) -> auto_advance to INTERESTED (3)
        self.assertTrue(mgr.check_staleness(current_turn=11))
        adv2 = mgr.auto_advance(current_turn=11)
        self.assertEqual(adv2, DecisionStage.INTERESTED)

        # Fast forward through all stages to DISENGAGED (8)
        # INTERESTED (3) -> EVALUATING (4) at turn 16
        mgr.auto_advance(current_turn=16)
        # EVALUATING (4) -> HESITANT (5) at turn 21
        mgr.auto_advance(current_turn=21)
        # HESITANT (5) -> READY (6) at turn 26
        mgr.auto_advance(current_turn=26)
        # READY (6) -> COMMITTED (7) at turn 31
        mgr.auto_advance(current_turn=31)
        # COMMITTED (7) -> DISENGAGED (8) at turn 36
        mgr.auto_advance(current_turn=36)
        self.assertEqual(mgr.current_stage, DecisionStage.DISENGAGED)

        # Stagnate in DISENGAGED until turn 45 -> must stay DISENGAGED, never exceed 8
        self.assertTrue(mgr.check_staleness(current_turn=45))
        adv_cap = mgr.auto_advance(current_turn=45)
        self.assertEqual(adv_cap, DecisionStage.DISENGAGED)
        self.assertEqual(mgr.current_stage, DecisionStage.DISENGAGED)


class TestM3FactStoreExtractionAndAmountBoundaries(unittest.TestCase):
    """Stress test FactStore polymorphism, type coercions, and boundary amount values."""

    def test_fact_store_polymorphic_adapters(self):
        """Verify _get_amount_from_fact_store supports dict, getter, attr, and nested facts."""
        mgr = StageTransitionManager()

        amount_val = 75000.0
        self.assertEqual(mgr._get_amount_from_fact_store({"amount": amount_val}), amount_val)
        self.assertEqual(mgr._get_amount_from_fact_store(MockFactStoreGetter(amount_val)), amount_val)
        self.assertEqual(mgr._get_amount_from_fact_store(MockFactStoreAttr(amount_val)), amount_val)
        self.assertEqual(mgr._get_amount_from_fact_store(MockFactStoreNestedFacts(amount_val)), amount_val)

    def test_amount_type_coercion_and_string_values(self):
        """Verify numeric strings are safely parsed and invalid strings rejected."""
        mgr = StageTransitionManager()

        self.assertEqual(mgr._get_amount_from_fact_store({"amount": "50000"}), 50000.0)
        self.assertEqual(mgr._get_amount_from_fact_store({"amount": " 25000.50 "}), 25000.50)
        self.assertEqual(mgr._get_amount_from_fact_store({"amount": 100000}), 100000.0)

        # Invalid formats return None
        self.assertIsNone(mgr._get_amount_from_fact_store({"amount": "fifty thousand"}))
        self.assertIsNone(mgr._get_amount_from_fact_store({"amount": ""}))
        self.assertIsNone(mgr._get_amount_from_fact_store({"amount": None}))
        self.assertIsNone(mgr._get_amount_from_fact_store({}))
        self.assertIsNone(mgr._get_amount_from_fact_store(None))

    def test_committed_and_recommendation_gates_with_adversarial_amounts(self):
        """Stress test COMMITTED and Recommendation gates with zero, negative, extreme amounts."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.READY)

        # Rejected amounts
        failing_cases = [
            None,
            {},
            {"amount": None},
            {"amount": 0},
            {"amount": 0.0},
            {"amount": "0"},
            {"amount": -1},
            {"amount": -500.0},
            {"amount": "-10000"},
            {"amount": "invalid"},
            {"other_key": 50000},
        ]

        for case in failing_cases:
            allowed_c, reason_c = mgr.can_transition(
                DecisionStage.READY, DecisionStage.COMMITTED, fact_store=case
            )
            self.assertFalse(allowed_c, f"COMMITTED gate should block for case: {case}")

            allowed_r, reason_r = mgr.can_recommend_product(fact_store=case)
            self.assertFalse(allowed_r, f"Recommendation gate should block for case: {case}")

        # Allowed amounts
        passing_cases = [
            {"amount": 1},
            {"amount": 25000},
            {"amount": "50000"},
            {"amount": 5000000.0},
            MockFactStoreGetter(100000),
            MockFactStoreAttr(500000),
        ]

        for case in passing_cases:
            allowed_c, reason_c = mgr.can_transition(
                DecisionStage.READY, DecisionStage.COMMITTED, fact_store=case
            )
            self.assertTrue(allowed_c, f"COMMITTED gate should allow for case: {case}")

            allowed_r, reason_r = mgr.can_recommend_product(fact_store=case)
            self.assertTrue(allowed_r, f"Recommendation gate should allow for case: {case}")


class TestM3CloseLimiterGateAdversarial(unittest.TestCase):
    """Stress test Close Limiter Gate attempt counting, prerequisites, and invariants."""

    def test_close_limiter_strict_two_attempt_enforcement(self):
        """Verify close attempt gate rejects without recommendation and caps strictly at 2."""
        mgr = StageTransitionManager()

        # Step 0: Initial state -> No recommendation -> Blocked
        self.assertFalse(mgr.can_attempt_close()[0])

        # Step 1: Record recommendation
        mgr.record_recommendation()

        # Step 2: 1st close attempt -> Allowed
        self.assertTrue(mgr.can_attempt_close()[0])
        att1 = mgr.record_close_attempt()
        self.assertEqual(att1, 1)
        self.assertEqual(mgr.close_attempts, 1)

        # Step 3: 2nd close attempt -> Allowed
        self.assertTrue(mgr.can_attempt_close()[0])
        att2 = mgr.record_close_attempt()
        self.assertEqual(att2, 2)
        self.assertEqual(mgr.close_attempts, 2)

        # Step 4: 3rd close attempt -> Blocked!
        allowed_3, reason_3 = mgr.can_attempt_close()
        self.assertFalse(allowed_3)
        self.assertIn("Maximum close attempts (2) reached", reason_3)

        # Step 5: High volume spam attempts -> Continues to be blocked
        for _ in range(50):
            self.assertFalse(mgr.can_attempt_close()[0])


class TestM3NumericLedgerHighVolumeFuzzing(unittest.TestCase):
    """Differential & property fuzzing for NumericLedger with 5000 quotes."""

    def setUp(self):
        self.ledger = NumericLedger()

    def test_5000_fuzzed_quotes_recording_and_verification(self):
        """Differential fuzzing: generate 5000 randomized financial quotes, record and verify."""
        rng = random.Random(42)

        recorded_records = []
        for i in range(5000):
            p = float(rng.randint(1000, 5000000))
            t = rng.randint(1, 36)
            xirr = round(rng.uniform(10.0, 30.0), 2)
            profit = round(p * (xirr / 100.0) * (t / 12.0), 2)
            maturity = round(p + profit, 2)
            emi = round(maturity / t, 2)

            self.ledger.record_quote(
                principal=p,
                tenure_months=t,
                xirr_pct=xirr,
                profit=profit,
                maturity_amount=maturity,
                monthly_emi=emi,
            )
            recorded_records.append((p, t, maturity))

        self.assertEqual(len(self.ledger.get_history()), 5000)

        # Sample 500 random records and verify exact and fuzzy tolerance
        sample = rng.sample(recorded_records, 500)
        for p, t, mat in sample:
            # Exact check
            self.assertTrue(self.ledger.verify_quote(p, t, mat, tolerance=1.0))
            # Within tolerance (±0.50)
            self.assertTrue(self.ledger.verify_quote(p, t, mat + 0.50, tolerance=1.0))
            self.assertTrue(self.ledger.verify_quote(p, t, mat - 0.50, tolerance=1.0))
            # Out of tolerance (±1.50)
            self.assertFalse(self.ledger.verify_quote(p, t, mat + 1.50, tolerance=1.0))
            self.assertFalse(self.ledger.verify_quote(p, t, mat - 1.50, tolerance=1.0))

    def test_quote_revision_picks_latest(self):
        """Verify that multiple quotes for identical (P, T) correctly resolve to the latest quote."""
        # Turn 1 quote: ₹50,000 for 6M at 15% -> Maturity ₹53,750
        self.ledger.record_quote(50000, 6, 15.0, 3750, 53750)
        self.assertTrue(self.ledger.verify_quote(50000, 6, 53750))

        # Turn 3 revised quote: ₹50,000 for 6M at 18% -> Maturity ₹54,500
        self.ledger.record_quote(50000, 6, 18.0, 4500, 54500)

        # Latest quote is now ₹54,500; old quote ₹53,750 should now FAIL verification
        self.assertTrue(self.ledger.verify_quote(50000, 6, 54500))
        self.assertFalse(self.ledger.verify_quote(50000, 6, 53750))

        latest_q = self.ledger.get_quote(50000, 6)
        self.assertIsNotNone(latest_q)
        self.assertEqual(latest_q["maturity_amount"], 54500)

    def test_rbi_platform_ceiling_exact_bounds(self):
        """Verify exact ₹50,00,000 boundary conditions."""
        # 50,00,000 is allowed
        self.ledger.record_quote(5000000.0, 12, 24.0, 1200000.0, 6200000.0)
        self.assertTrue(self.ledger.verify_quote(5000000.0, 12, 6200000.0))

        # 50,00,000.01 is rejected
        with self.assertRaises(ValueError):
            self.ledger.record_quote(5000000.01, 12, 24.0, 1200000.0, 6200000.0)

        # 0 and negative rejected
        with self.assertRaises(ValueError):
            self.ledger.record_quote(0, 12, 24.0, 0, 0)
        with self.assertRaises(ValueError):
            self.ledger.record_quote(-100, 12, 24.0, 0, 0)

        # Tenure 0 and negative rejected
        with self.assertRaises(ValueError):
            self.ledger.record_quote(50000, 0, 24.0, 0, 50000)
        with self.assertRaises(ValueError):
            self.ledger.record_quote(50000, -6, 24.0, 0, 50000)


class TestM3EscalationTrackerDifferentialOracle(unittest.TestCase):
    """Differential testing of EscalationTracker against an independent ground truth oracle."""

    @staticmethod
    def oracle_escalation_tier(human_requests: int, queries_count: int) -> int:
        """Independent ground-truth oracle for the 5-Tier Escalation Matrix."""
        if human_requests >= 2 or queries_count >= 3:
            return 5
        if human_requests == 1:
            return 4
        if queries_count >= 2:
            return 3
        if queries_count == 1:
            return 2
        return 1

    def test_differential_oracle_all_grid_points(self):
        """Exhaustively verify all (H, Q) grid points for H in 0..10 and Q in 0..10."""
        for h in range(11):
            for q in range(11):
                tracker = EscalationTracker()
                for _ in range(h):
                    tracker.record_human_request()
                for i in range(q):
                    tracker.record_user_query(f"Query {i+1}")

                expected_tier = self.oracle_escalation_tier(h, q)
                actual_tier = tracker.get_escalation_tier()

                self.assertEqual(
                    actual_tier,
                    expected_tier,
                    f"Mismatch at (H={h}, Q={q}): expected Tier {expected_tier}, got Tier {actual_tier}"
                )

                expected_callback = (expected_tier >= 5)
                actual_callback = tracker.is_callback_booking_required()
                self.assertEqual(
                    actual_callback,
                    expected_callback,
                    f"Callback requirement mismatch at (H={h}, Q={q})"
                )

    def test_interleaved_human_requests_and_queries(self):
        """Verify interleaved sequences of human requests and queries."""
        rng = random.Random(1337)

        for trial in range(100):
            tracker = EscalationTracker()
            h_count = 0
            q_count = 0

            # Generate random sequence of 15 actions
            actions = [rng.choice(["H", "Q"]) for _ in range(15)]
            for act in actions:
                if act == "H":
                    tracker.record_human_request()
                    h_count += 1
                else:
                    tracker.record_user_query(f"Query {q_count}")
                    q_count += 1

                expected_tier = self.oracle_escalation_tier(h_count, q_count)
                self.assertEqual(tracker.get_escalation_tier(), expected_tier)


if __name__ == "__main__":
    unittest.main()
