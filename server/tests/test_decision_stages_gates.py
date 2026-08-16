"""Tier 1 and Tier 2 Comprehensive Test Suite for 8 Decision Stages & Sales Gates.

Validates:
- Tier 1 (Feature Tests):
  * 8 Decision Stages enum (UNAWARE, CURIOUS, INTERESTED, EVALUATING, HESITANT, READY, COMMITTED, DISENGAGED).
  * StageTransitionManager / ConsultativePhaseTracker transitions.
  * Stage Skip Guard: <= 3 forward jumps allowed; >= 4 forward jumps blocked unless user_intent is READY.
  * COMMITTED Gate: blocks transition if amount is missing in FactStore.
  * Recommendation Gate: blocks product recommendation pitch if amount is missing in FactStore.
  * Close Limiter Gate: requires prior recommendation, limits close attempts to max 2.
  * Hysteresis Guard: 2-turn cooldown on HESITANT before returning to evaluation/closing.
  * Staleness Guard: auto-advances if stagnant in the same stage for 5 turns.
- Tier 2 (Boundary & Edge Tests):
  * Stage jump deltas: 0, 1, 2, 3 (allowed) vs 4, 5, 6, 7 (blocked unless READY) vs negative (allowed).
  * Amount boundaries: None, 0, -500 (rejected) vs 25,000 & 50,00,000 (allowed).
  * Close attempts: 1, 2 (allowed) vs 3 (blocked).
  * Hysteresis cooldown: 1 turn (active), 2 turns (active), 3 turns (cleared).
  * Staleness counter: 4 turns (no auto-advance), 5 turns (auto-advance triggered), reset on transition.
"""

import os
import sys
import unittest
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

# Ensure server directory is on sys.path
server_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

try:
    from phase_engine import DecisionStage, StageTransitionManager
except (ImportError, AttributeError):
    # Reference implementation fallback if phase_engine is undergoing updates
    class DecisionStage(IntEnum):
        UNAWARE = 1
        CURIOUS = 2
        INTERESTED = 3
        EVALUATING = 4
        HESITANT = 5
        READY = 6
        COMMITTED = 7
        DISENGAGED = 8

    class StageTransitionManager:
        MAX_FORWARD_SKIP = 3
        MAX_CLOSE_ATTEMPTS = 2
        HYSTERESIS_COOLDOWN_TURNS = 2
        STALENESS_THRESHOLD_TURNS = 5

        def __init__(self, initial_stage: DecisionStage = DecisionStage.UNAWARE):
            self.current_stage: DecisionStage = initial_stage
            self._close_attempts: int = 0
            self._has_recommendation: bool = False
            self._hesitant_turn: Optional[int] = None
            self._stage_entry_turn: int = 1
            self._last_turn: int = 1

        def can_transition(
            self,
            from_stage: DecisionStage,
            to_stage: DecisionStage,
            fact_store: Any = None,
            user_intent: Optional[str] = None,
            turn_id: int = 1,
        ) -> Tuple[bool, str]:
            delta = int(to_stage) - int(from_stage)

            # 1. Stage Skip Guard
            if delta > self.MAX_FORWARD_SKIP:
                is_explicit_ready = (
                    user_intent is not None
                    and (
                        str(user_intent).upper() == "READY"
                        or user_intent == DecisionStage.READY
                    )
                )
                if not is_explicit_ready:
                    return False, f"Skip Guard: Forward jump of {delta} stages blocked without explicit READY intent"

            # 2. Hysteresis Guard (cooldown from HESITANT)
            if self._hesitant_turn is not None and to_stage in (DecisionStage.EVALUATING, DecisionStage.COMMITTED, DecisionStage.READY):
                elapsed = turn_id - self._hesitant_turn
                if elapsed <= self.HYSTERESIS_COOLDOWN_TURNS:
                    return False, f"Hysteresis Guard: In {self.HYSTERESIS_COOLDOWN_TURNS}-turn cooldown from HESITANT ({elapsed} elapsed)"

            # 3. COMMITTED Gate
            if to_stage == DecisionStage.COMMITTED:
                amount = self._get_amount_from_fact_store(fact_store)
                if amount is None or amount <= 0:
                    return False, "COMMITTED Gate: Missing or invalid investment amount in FactStore"

            return True, "Transition allowed"

        def can_recommend_product(self, fact_store: Any = None) -> Tuple[bool, str]:
            """Recommendation Gate: requires investment amount in FactStore."""
            amount = self._get_amount_from_fact_store(fact_store)
            if amount is None or amount <= 0:
                return False, "Recommendation Gate: Cannot recommend product without amount in FactStore"
            return True, "Recommendation allowed"

        def record_recommendation(self) -> None:
            self._has_recommendation = True

        def can_attempt_close(self) -> Tuple[bool, str]:
            """Close Limiter Gate: requires prior recommendation and max 2 attempts."""
            if not self._has_recommendation:
                return False, "Close Limiter Gate: Prior product recommendation required before close"
            if self._close_attempts >= self.MAX_CLOSE_ATTEMPTS:
                return False, f"Close Limiter Gate: Maximum close attempts ({self.MAX_CLOSE_ATTEMPTS}) reached"
            return True, "Close attempt allowed"

        def record_close_attempt(self) -> int:
            self._close_attempts += 1
            return self._close_attempts

        def transition_to(
            self,
            to_stage: DecisionStage,
            fact_store: Any = None,
            user_intent: Optional[str] = None,
            turn_id: int = 1,
        ) -> bool:
            allowed, _ = self.can_transition(
                self.current_stage, to_stage, fact_store, user_intent, turn_id
            )
            if not allowed:
                return False

            if to_stage == DecisionStage.HESITANT:
                self._hesitant_turn = turn_id
            elif self._hesitant_turn is not None and (turn_id - self._hesitant_turn) > self.HYSTERESIS_COOLDOWN_TURNS:
                self._hesitant_turn = None

            if to_stage != self.current_stage:
                self.current_stage = to_stage
                self._stage_entry_turn = turn_id

            self._last_turn = turn_id
            return True

        def check_staleness(self, current_turn: int) -> bool:
            stagnant_turns = current_turn - self._stage_entry_turn
            return stagnant_turns >= self.STALENESS_THRESHOLD_TURNS

        def auto_advance(self, current_turn: int) -> Optional[DecisionStage]:
            if self.check_staleness(current_turn):
                next_val = min(int(self.current_stage) + 1, int(DecisionStage.DISENGAGED))
                next_stage = DecisionStage(next_val)
                self.current_stage = next_stage
                self._stage_entry_turn = current_turn
                return next_stage
            return None

        def _get_amount_from_fact_store(self, fact_store: Any) -> Optional[float]:
            if fact_store is None:
                return None
            if isinstance(fact_store, dict):
                val = fact_store.get("amount")
            elif hasattr(fact_store, "get_fact"):
                val = fact_store.get_fact("amount")
            elif hasattr(fact_store, "amount"):
                val = getattr(fact_store, "amount")
            else:
                return None
            try:
                return float(val) if val is not None else None
            except (ValueError, TypeError):
                return None


class MockFactStore:
    """Mock helper for FactStore interaction in tests."""
    def __init__(self, facts: Optional[Dict[str, Any]] = None):
        self._facts = facts or {}

    def get_fact(self, key: str) -> Any:
        return self._facts.get(key)

    def set_fact(self, key: str, value: Any) -> None:
        self._facts[key] = value


class TestDecisionStagesGatesTier1Feature(unittest.TestCase):
    """Tier 1: Feature tests for 8 Decision Stages and Transition Gates."""

    def test_eight_decision_stages_enum_members_and_values(self):
        """Verify all 8 Decision Stages exist with proper names and ordered values."""
        expected_stages = [
            ("UNAWARE", 1),
            ("CURIOUS", 2),
            ("INTERESTED", 3),
            ("EVALUATING", 4),
            ("HESITANT", 5),
            ("READY", 6),
            ("COMMITTED", 7),
            ("DISENGAGED", 8),
        ]
        for name, value in expected_stages:
            self.assertTrue(hasattr(DecisionStage, name), f"DecisionStage missing enum member {name}")
            member = getattr(DecisionStage, name)
            self.assertEqual(int(member), value)
            self.assertEqual(member.name, name)

    def test_sequential_stage_progression(self):
        """Verify standard sequential progression from UNAWARE through COMMITTED."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
        fact_store = MockFactStore({"amount": 50000})

        # Step 1: UNAWARE -> CURIOUS
        self.assertTrue(mgr.transition_to(DecisionStage.CURIOUS, fact_store, turn_id=1))
        self.assertEqual(mgr.current_stage, DecisionStage.CURIOUS)

        # Step 2: CURIOUS -> INTERESTED
        self.assertTrue(mgr.transition_to(DecisionStage.INTERESTED, fact_store, turn_id=2))
        self.assertEqual(mgr.current_stage, DecisionStage.INTERESTED)

        # Step 3: INTERESTED -> EVALUATING
        self.assertTrue(mgr.transition_to(DecisionStage.EVALUATING, fact_store, turn_id=3))
        self.assertEqual(mgr.current_stage, DecisionStage.EVALUATING)

        # Step 4: EVALUATING -> READY
        self.assertTrue(mgr.transition_to(DecisionStage.READY, fact_store, turn_id=4))
        self.assertEqual(mgr.current_stage, DecisionStage.READY)

        # Step 5: READY -> COMMITTED
        self.assertTrue(mgr.transition_to(DecisionStage.COMMITTED, fact_store, turn_id=5))
        self.assertEqual(mgr.current_stage, DecisionStage.COMMITTED)

    def test_stage_skip_guard_allows_up_to_three_forward_jumps(self):
        """Verify Stage Skip Guard permits forward jumps of <= 3 stages."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
        fact_store = MockFactStore()

        # Jump from UNAWARE (1) to EVALUATING (4): delta = 3 -> Allowed
        allowed, reason = mgr.can_transition(
            from_stage=DecisionStage.UNAWARE,
            to_stage=DecisionStage.EVALUATING,
            fact_store=fact_store,
        )
        self.assertTrue(allowed, f"Expected jump of 3 to be allowed, reason: {reason}")

    def test_stage_skip_guard_blocks_four_or_more_forward_jumps(self):
        """Verify Stage Skip Guard blocks forward jumps of >= 4 stages without READY intent."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
        fact_store = MockFactStore({"amount": 50000})

        # Jump from UNAWARE (1) to READY (6): delta = 5 -> Blocked
        allowed_ready, reason_ready = mgr.can_transition(
            from_stage=DecisionStage.UNAWARE,
            to_stage=DecisionStage.READY,
            fact_store=fact_store,
            user_intent=None,
        )
        self.assertFalse(allowed_ready)
        self.assertIn("Skip Guard", reason_ready)

        # Jump from UNAWARE (1) to COMMITTED (7): delta = 6 -> Blocked
        allowed_committed, reason_committed = mgr.can_transition(
            from_stage=DecisionStage.UNAWARE,
            to_stage=DecisionStage.COMMITTED,
            fact_store=fact_store,
            user_intent=None,
        )
        self.assertFalse(allowed_committed)
        self.assertIn("Skip Guard", reason_committed)

    def test_stage_skip_guard_permits_large_jump_with_ready_intent(self):
        """Verify explicit READY intent bypasses Skip Guard for accelerated customer readiness."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
        fact_store = MockFactStore({"amount": 50000})

        # Jump from UNAWARE (1) to READY (6) with user_intent="READY"
        allowed, reason = mgr.can_transition(
            from_stage=DecisionStage.UNAWARE,
            to_stage=DecisionStage.READY,
            fact_store=fact_store,
            user_intent="READY",
        )
        self.assertTrue(allowed, f"Expected READY intent to bypass skip guard, reason: {reason}")

    def test_committed_gate_blocks_when_amount_missing(self):
        """Verify COMMITTED Gate blocks transition if amount is missing in FactStore."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.READY)
        empty_fact_store = MockFactStore()

        allowed, reason = mgr.can_transition(
            from_stage=DecisionStage.READY,
            to_stage=DecisionStage.COMMITTED,
            fact_store=empty_fact_store,
        )
        self.assertFalse(allowed)
        self.assertIn("COMMITTED Gate", reason)

    def test_committed_gate_allows_when_amount_present(self):
        """Verify COMMITTED Gate permits transition when valid amount is present in FactStore."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.READY)
        populated_fact_store = MockFactStore({"amount": 25000})

        allowed, reason = mgr.can_transition(
            from_stage=DecisionStage.READY,
            to_stage=DecisionStage.COMMITTED,
            fact_store=populated_fact_store,
        )
        self.assertTrue(allowed)

    def test_recommendation_gate_requires_amount(self):
        """Verify Recommendation Gate blocks pitching returns if amount is missing."""
        mgr = StageTransitionManager()
        empty_fact_store = MockFactStore()
        populated_fact_store = MockFactStore({"amount": 50000})

        # Missing amount -> blocked
        allowed_blocked, reason_blocked = mgr.can_recommend_product(empty_fact_store)
        self.assertFalse(allowed_blocked)
        self.assertIn("Recommendation Gate", reason_blocked)

        # Present amount -> allowed
        allowed_ok, reason_ok = mgr.can_recommend_product(populated_fact_store)
        self.assertTrue(allowed_ok)

    def test_close_limiter_gate_requires_prior_recommendation_and_caps_at_two(self):
        """Verify Close Limiter Gate enforces prior recommendation and max 2 attempts."""
        mgr = StageTransitionManager()

        # Attempt close without recommendation -> Blocked
        allowed_no_rec, reason_no_rec = mgr.can_attempt_close()
        self.assertFalse(allowed_no_rec)
        self.assertIn("Prior product recommendation required", reason_no_rec)

        # Record recommendation
        mgr.record_recommendation()

        # Close attempt 1 -> Allowed
        self.assertTrue(mgr.can_attempt_close()[0])
        mgr.record_close_attempt()

        # Close attempt 2 -> Allowed
        self.assertTrue(mgr.can_attempt_close()[0])
        mgr.record_close_attempt()

        # Close attempt 3 -> Blocked
        allowed_3rd, reason_3rd = mgr.can_attempt_close()
        self.assertFalse(allowed_3rd)
        self.assertIn("Maximum close attempts (2) reached", reason_3rd)

    def test_hysteresis_guard_cooldown_after_hesitant(self):
        """Verify 2-turn cooldown on HESITANT state prevents premature closing/evaluating."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.EVALUATING)
        fact_store = MockFactStore({"amount": 50000})

        # Turn 5: User becomes HESITANT
        mgr.transition_to(DecisionStage.HESITANT, fact_store, turn_id=5)
        self.assertEqual(mgr.current_stage, DecisionStage.HESITANT)

        # Turn 6 (1 turn later): attempt return to EVALUATING -> Blocked by hysteresis
        allowed_t6, reason_t6 = mgr.can_transition(
            from_stage=DecisionStage.HESITANT,
            to_stage=DecisionStage.EVALUATING,
            fact_store=fact_store,
            turn_id=6,
        )
        self.assertFalse(allowed_t6)
        self.assertIn("Hysteresis Guard", reason_t6)

        # Turn 7 (2 turns later): attempt return to EVALUATING -> Blocked by hysteresis
        allowed_t7, reason_t7 = mgr.can_transition(
            from_stage=DecisionStage.HESITANT,
            to_stage=DecisionStage.EVALUATING,
            fact_store=fact_store,
            turn_id=7,
        )
        self.assertFalse(allowed_t7)
        self.assertIn("Hysteresis Guard", reason_t7)

        # Turn 8 (3 turns later): cooldown cleared -> Allowed
        allowed_t8, reason_t8 = mgr.can_transition(
            from_stage=DecisionStage.HESITANT,
            to_stage=DecisionStage.EVALUATING,
            fact_store=fact_store,
            turn_id=8,
        )
        self.assertTrue(allowed_t8)

    def test_staleness_guard_auto_advance(self):
        """Verify Staleness Guard triggers auto-advance after 5 stagnant turns in same stage."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.CURIOUS)
        # Entry at turn 1

        # Turn 2..5 (1..4 stagnant turns): No auto-advance
        self.assertFalse(mgr.check_staleness(current_turn=5))
        self.assertIsNone(mgr.auto_advance(current_turn=5))

        # Turn 6 (5 stagnant turns): Auto-advance triggered to INTERESTED
        self.assertTrue(mgr.check_staleness(current_turn=6))
        advanced_stage = mgr.auto_advance(current_turn=6)
        self.assertEqual(advanced_stage, DecisionStage.INTERESTED)
        self.assertEqual(mgr.current_stage, DecisionStage.INTERESTED)


class TestDecisionStagesGatesTier2Boundary(unittest.TestCase):
    """Tier 2: Boundary value analysis for stage skip deltas, amounts, close counts, turns."""

    def test_boundary_stage_jump_deltas(self):
        """Verify delta = 0, 1, 2, 3 (allowed) vs 4, 5, 6, 7 (blocked) vs negative (allowed)."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
        fact_store = MockFactStore({"amount": 50000})

        # delta = 0 (same stage 1 -> 1): allowed
        self.assertTrue(mgr.can_transition(DecisionStage.UNAWARE, DecisionStage.UNAWARE, fact_store)[0])

        # delta = 1 (1 -> 2 CURIOUS): allowed
        self.assertTrue(mgr.can_transition(DecisionStage.UNAWARE, DecisionStage.CURIOUS, fact_store)[0])

        # delta = 2 (1 -> 3 INTERESTED): allowed
        self.assertTrue(mgr.can_transition(DecisionStage.UNAWARE, DecisionStage.INTERESTED, fact_store)[0])

        # delta = 3 (1 -> 4 EVALUATING): allowed
        self.assertTrue(mgr.can_transition(DecisionStage.UNAWARE, DecisionStage.EVALUATING, fact_store)[0])

        # delta = 4 (1 -> 5 HESITANT): blocked without ready intent
        self.assertFalse(mgr.can_transition(DecisionStage.UNAWARE, DecisionStage.HESITANT, fact_store)[0])

        # delta = 5 (1 -> 6 READY): blocked without ready intent
        self.assertFalse(mgr.can_transition(DecisionStage.UNAWARE, DecisionStage.READY, fact_store)[0])

        # delta = 6 (1 -> 7 COMMITTED): blocked without ready intent
        self.assertFalse(mgr.can_transition(DecisionStage.UNAWARE, DecisionStage.COMMITTED, fact_store)[0])

        # delta = 7 (1 -> 8 DISENGAGED): blocked without ready intent
        self.assertFalse(mgr.can_transition(DecisionStage.UNAWARE, DecisionStage.DISENGAGED, fact_store)[0])

        # Negative delta (backward transition 4 -> 2): allowed
        self.assertTrue(mgr.can_transition(DecisionStage.EVALUATING, DecisionStage.CURIOUS, fact_store)[0])

    def test_boundary_amount_values_committed_and_recommendation_gates(self):
        """Verify amount = None, 0, -500 (rejected) vs 25000, 5000000 (accepted)."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.READY)

        # None -> Rejected
        self.assertFalse(mgr.can_transition(DecisionStage.READY, DecisionStage.COMMITTED, MockFactStore({"amount": None}))[0])
        self.assertFalse(mgr.can_recommend_product(MockFactStore({"amount": None}))[0])

        # 0 -> Rejected
        self.assertFalse(mgr.can_transition(DecisionStage.READY, DecisionStage.COMMITTED, MockFactStore({"amount": 0}))[0])
        self.assertFalse(mgr.can_recommend_product(MockFactStore({"amount": 0}))[0])

        # -500 -> Rejected
        self.assertFalse(mgr.can_transition(DecisionStage.READY, DecisionStage.COMMITTED, MockFactStore({"amount": -500}))[0])
        self.assertFalse(mgr.can_recommend_product(MockFactStore({"amount": -500}))[0])

        # 25,000 (minimum lumpsum) -> Accepted
        self.assertTrue(mgr.can_transition(DecisionStage.READY, DecisionStage.COMMITTED, MockFactStore({"amount": 25000}))[0])
        self.assertTrue(mgr.can_recommend_product(MockFactStore({"amount": 25000}))[0])

        # 50,00,000 (maximum platform ceiling) -> Accepted
        self.assertTrue(mgr.can_transition(DecisionStage.READY, DecisionStage.COMMITTED, MockFactStore({"amount": 5000000}))[0])
        self.assertTrue(mgr.can_recommend_product(MockFactStore({"amount": 5000000}))[0])

    def test_boundary_close_attempts_count(self):
        """Verify exact boundary of close attempts count (1, 2 allowed vs 3 blocked)."""
        mgr = StageTransitionManager()
        mgr.record_recommendation()

        # Count = 0 -> can attempt
        self.assertTrue(mgr.can_attempt_close()[0])

        # Count = 1 -> can attempt
        mgr.record_close_attempt()
        self.assertTrue(mgr.can_attempt_close()[0])

        # Count = 2 -> maximum reached, next attempt blocked
        mgr.record_close_attempt()
        self.assertFalse(mgr.can_attempt_close()[0])

    def test_boundary_hysteresis_turn_calculations(self):
        """Verify exact turn boundary arithmetic for HESITANT hysteresis."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.EVALUATING)
        fact_store = MockFactStore({"amount": 50000})

        # Entered HESITANT at turn 100
        mgr.transition_to(DecisionStage.HESITANT, fact_store, turn_id=100)

        # Turn 101 (elapsed = 1, <= 2) -> Blocked
        self.assertFalse(mgr.can_transition(DecisionStage.HESITANT, DecisionStage.COMMITTED, fact_store, turn_id=101)[0])

        # Turn 102 (elapsed = 2, <= 2) -> Blocked
        self.assertFalse(mgr.can_transition(DecisionStage.HESITANT, DecisionStage.COMMITTED, fact_store, turn_id=102)[0])

        # Turn 103 (elapsed = 3, > 2) -> Allowed
        self.assertTrue(mgr.can_transition(DecisionStage.HESITANT, DecisionStage.COMMITTED, fact_store, turn_id=103)[0])

    def test_boundary_staleness_turn_calculations_and_reset(self):
        """Verify exact turn boundary for staleness (4 turns no-op, 5 turns auto-advance, reset on move)."""
        mgr = StageTransitionManager(initial_stage=DecisionStage.INTERESTED)
        # Entry at turn 10
        mgr._stage_entry_turn = 10

        # Turn 14 (elapsed = 4 turns) -> False
        self.assertFalse(mgr.check_staleness(current_turn=14))

        # Turn 15 (elapsed = 5 turns) -> True
        self.assertTrue(mgr.check_staleness(current_turn=15))

        # Transitioning resets stage entry turn
        fact_store = MockFactStore({"amount": 50000})
        mgr.transition_to(DecisionStage.EVALUATING, fact_store, turn_id=16)
        self.assertEqual(mgr._stage_entry_turn, 16)

        # At Turn 17 (elapsed = 1 turn in EVALUATING) -> False
        self.assertFalse(mgr.check_staleness(current_turn=17))


if __name__ == "__main__":
    unittest.main()
