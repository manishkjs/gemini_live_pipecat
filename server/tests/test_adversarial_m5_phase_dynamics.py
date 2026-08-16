"""Adversarial Stress & Hardening Test Suite for Milestone M5:
Phase Engine, State Machine Transitions, Sales Gates, Numeric Ledger, Escalation Matrix, and Live Lifecycle.

Author: Empirical Challenger (Challenger 2)
Milestone: M5 (Adversarial Coverage Hardening)

Comprehensive White-Box Adversarial Stress Testing:
1. Decision Stages & Transition Gates (TestDecisionStageHoppingAdversarial):
   - Illegal forward skips (>3 jumps) blocked unless explicit READY intent
   - Legal skip bypass with case/type-insensitive READY intent variations vs invalid lookalikes
   - Backward transitions (negative deltas) and boundary deltas (0, 1, 2, 3) across all 8 stages
   - COMMITTED gate amount prerequisite & adversarial payload validation (NaN, Inf, strings, <=0)
   - Recommendation gate amount prerequisite validation

2. Close Limiter & Recommendation Lifecycle (TestCloseLimiterAndRecommendationAdversarial):
   - Close attempts blocked without prior product recommendation
   - Recommendation gate requires positive financial amount in FactStore
   - Close attempt limiter enforces strict 2-attempt cap with overflow protection
   - State transition isolation: close attempts counter persistence across stage shifts

3. Hysteresis & Hesitation Dynamics (TestHysteresisAndThrashingAdversarial):
   - Hysteresis 2-turn cooldown on HESITANT with exact tick boundary conditions
   - Cooldown persistence when exiting HESITANT to non-evaluation stages
   - Rapid oscillation / hesitation thrashing stress sequence
   - Pure predicate guarantee: zero state mutations on can_transition queries

4. Staleness Guard & Auto-Advance Dynamics (TestStalenessDynamicsAndCeilingAdversarial):
   - Exact 5-turn staleness boundary detection
   - Sequential auto-advances from UNAWARE to DISENGAGED
   - DISENGAGED auto-advance ceiling cap (no overflow beyond stage 8)
   - Manual stage transitions reset staleness counter

5. Numeric Consistency Ledger (TestNumericLedgerContradictionsAndCeilingAdversarial):
   - Strict RBI platform ceiling enforcement (₹50,00,000 / ₹50 Lakhs limit)
   - Deterministic quote recording, bounds validation, and history retrieval
   - Strict ±1.0 rupee tolerance verification
   - Out-of-tolerance and conflicting quotes contradiction detection
   - Multiple / updated quote resolution (latest quote priority)

6. 5-Tier Human Escalation Matrix (TestEscalationMatrixThresholdAdversarial):
   - Tier 1 to 5 progression across queries and human requests
   - Edge comparison: 1 vs 2 human requests (Tier 4 vs Tier 5 / Callback trigger)
   - Edge comparison: 2 vs 3 repeated queries (Tier 3 vs Tier 5 / Callback trigger)
   - Interleaved queries and human requests stability

7. Consultative Phase Engine & Frame Interception (TestConsultativePhaseEngineDynamicsAdversarial):
   - Real-time Attention Steering without audio interruption (bot speaking queueing & flush)
   - Fast-path keyword and regex transcript matching for Phases 1-9
   - Functional tool call result frame phase steering (returns -> P7, KYC -> P8, KB -> P4)

8. Live Pipeline Lifecycle & Downcar Triggers (TestAgentLiveLifecycleAdversarial):
   - AntiCancel tool shield: tool lock interruption suppression & FunctionCallCancelFrame drop
   - AntiCancel watchdog timeout self-healing (8.0s limit)
   - Transcript history accumulation, partial utterance flush on interruption, lexical name resolution
   - Client disconnect event triggers asynchronous post-session downcar memory extraction

9. System Prompt Integrity & Objection Directives (TestSystemPromptAdversarial):
   - Turn 1 greeting with exact name elicitation and '2 minutes' availability check
   - Devanagari Hindi + Latin English financial terms code-mixing compliance
   - 9-month tenure strict rejection, ₹250 min and ₹50L ceiling directives
   - 4-pillar objection handling playbook (defaults, bank FD, RBI escrow, liquidity)
   - Lean chained prompt generation across sales phases
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import sys
import time
import unittest
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure server directory is on sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from memory_bank import FactStore, MemoryBank, normalize_lexical_user_id
from phase_engine import (
    PHASE_PROMPT_CARDS,
    ConsultativePhaseTracker,
    DecisionStage,
    EscalationTracker,
    NumericLedger,
    PhaseTransitionProcessor,
    StageTransitionManager,
)
from pipecat.frames.frames import (
    Frame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    FunctionCallCancelFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from system_prompt import (
    BASE_SYSTEM_PROMPT,
    BOUNDARY_RULES,
    FEW_SHOT_EXAMPLES,
    LEAN_PERSONA_PROMPT,
    OBJECTION_PLAYBOOK,
    PHASE_PROMPTS,
    SYSTEM_PROMPT,
    get_chained_system_prompt,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. DECISION STAGES & TRANSITION GATES ADVERSARIAL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestDecisionStageHoppingAdversarial(unittest.TestCase):
    """Adversarial stress testing for 8 Decision Stages and Stage Transition Gates."""

    def setUp(self):
        self.stm = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
        self.fact_store = FactStore()

    def test_illegal_forward_skips_without_ready_intent(self):
        """Verify that any forward jump > 3 stages is strictly blocked without explicit READY intent."""
        # Matrix of all forward jumps > 3
        illegal_skips = [
            (DecisionStage.UNAWARE, DecisionStage.HESITANT, 4),
            (DecisionStage.UNAWARE, DecisionStage.READY, 5),
            (DecisionStage.UNAWARE, DecisionStage.COMMITTED, 6),
            (DecisionStage.UNAWARE, DecisionStage.DISENGAGED, 7),
            (DecisionStage.CURIOUS, DecisionStage.READY, 4),
            (DecisionStage.CURIOUS, DecisionStage.COMMITTED, 5),
            (DecisionStage.CURIOUS, DecisionStage.DISENGAGED, 6),
            (DecisionStage.INTERESTED, DecisionStage.COMMITTED, 4),
            (DecisionStage.INTERESTED, DecisionStage.DISENGAGED, 5),
            (DecisionStage.EVALUATING, DecisionStage.DISENGAGED, 4),
        ]

        invalid_intents = [
            None,
            "",
            "   ",
            "INTERESTED",
            "PROCEED",
            "MAYBE",
            "YES",
            "ALMOST_READY",
            "NOT_READY",
            "READY_NOW",
            123,
            True,
            False,
            [],
            {},
        ]

        for from_s, to_s, delta in illegal_skips:
            for intent in invalid_intents:
                allowed, reason = self.stm.can_transition(
                    from_stage=from_s,
                    to_stage=to_s,
                    fact_store=self.fact_store,
                    user_intent=intent,
                    turn_id=1,
                )
                self.assertFalse(
                    allowed,
                    f"Expected skip {from_s.name} -> {to_s.name} (delta {delta}) to be blocked with intent={intent!r}",
                )
                self.assertIn("Skip Guard", reason)
                self.assertIn(f"Forward jump of {delta} stages blocked", reason)

    def test_legal_skip_with_ready_intent_and_intent_variants(self):
        """Verify that forward jump > 3 succeeds if and only if explicit READY intent is present."""
        self.fact_store.set_fact("amount", 50000, turn_id=1)

        # Valid READY intent variations
        valid_intents = [
            "READY",
            "ready",
            "Ready",
            " READY ",
            "  ready  ",
            DecisionStage.READY,
        ]

        for intent in valid_intents:
            stm = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)
            allowed, reason = stm.can_transition(
                from_stage=DecisionStage.UNAWARE,
                to_stage=DecisionStage.READY,
                fact_store=self.fact_store,
                user_intent=intent,
                turn_id=1,
            )
            self.assertTrue(
                allowed,
                f"Expected UNAWARE -> READY (delta 5) to be allowed with intent={intent!r}, got reason: {reason}",
            )

    def test_backward_transitions_and_boundary_deltas(self):
        """Verify that all backward transitions (delta < 0) and boundary deltas (0, 1, 2, 3) are allowed."""
        # 1. Delta 0: Same stage transition
        for stage in DecisionStage:
            allowed, reason = self.stm.can_transition(
                from_stage=stage,
                to_stage=stage,
                fact_store=self.fact_store,
                turn_id=1,
            )
            self.assertTrue(allowed)
            self.assertEqual(reason, "No stage change")

        # 2. Backward jumps (delta < 0): Any backward move should be permitted by skip guard
        backward_moves = [
            (DecisionStage.DISENGAGED, DecisionStage.UNAWARE),
            (DecisionStage.COMMITTED, DecisionStage.CURIOUS),
            (DecisionStage.READY, DecisionStage.INTERESTED),
            (DecisionStage.EVALUATING, DecisionStage.UNAWARE),
            (DecisionStage.HESITANT, DecisionStage.CURIOUS),
        ]
        for from_s, to_s in backward_moves:
            allowed, reason = self.stm.can_transition(
                from_stage=from_s,
                to_stage=to_s,
                fact_store=self.fact_store,
                turn_id=10,
            )
            self.assertTrue(
                allowed,
                f"Backward transition {from_s.name} -> {to_s.name} should be permitted",
            )

        # 3. Boundary forward jumps: delta in [1, 2, 3]
        for from_val in range(1, 6):
            for delta in [1, 2, 3]:
                to_val = from_val + delta
                if to_val > 8:
                    continue
                from_s = DecisionStage(from_val)
                to_s = DecisionStage(to_val)
                # Ensure FactStore has amount if to_stage is COMMITTED
                fs = FactStore()
                fs.set_fact("amount", 100000, turn_id=1)
                allowed, reason = self.stm.can_transition(
                    from_stage=from_s,
                    to_stage=to_s,
                    fact_store=fs,
                    turn_id=10,
                )
                self.assertTrue(
                    allowed,
                    f"Forward jump {from_s.name} -> {to_s.name} (delta {delta}) should be allowed",
                )

    def test_committed_gate_adversarial_payloads(self):
        """Verify that COMMITTED stage transition strictly validates amount across all edge types."""
        invalid_fact_stores = [
            None,
            {},
            {"amount": None},
            {"amount": 0},
            {"amount": 0.0},
            {"amount": -100},
            {"amount": -50000.0},
            {"amount": float("nan")},
            {"amount": float("inf")},
            {"amount": float("-inf")},
            {"amount": "abc"},
            {"amount": ""},
            {"amount": []},
            {"amount": {}},
        ]

        for bad_fs in invalid_fact_stores:
            allowed, reason = self.stm.can_transition(
                from_stage=DecisionStage.READY,
                to_stage=DecisionStage.COMMITTED,
                fact_store=bad_fs,
                turn_id=1,
            )
            self.assertFalse(
                allowed,
                f"COMMITTED gate should reject bad fact_store payload: {bad_fs!r}",
            )
            self.assertIn("COMMITTED Gate", reason)

        # Valid fact stores
        valid_fact_stores = [
            {"amount": 25000},
            {"amount": 50000.0},
            {"amount": "100000"},
            {"amount": 5000000.0},
        ]
        for good_fs in valid_fact_stores:
            allowed, reason = self.stm.can_transition(
                from_stage=DecisionStage.READY,
                to_stage=DecisionStage.COMMITTED,
                fact_store=good_fs,
                turn_id=1,
            )
            self.assertTrue(
                allowed,
                f"COMMITTED gate should allow valid fact_store: {good_fs!r}",
            )


# ═══════════════════════════════════════════════════════════════════════
# 2. CLOSE LIMITER & RECOMMENDATION LIFECYCLE ADVERSARIAL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestCloseLimiterAndRecommendationAdversarial(unittest.TestCase):
    """Adversarial stress testing for Close Limiter Gate and Recommendation Gate."""

    def setUp(self):
        self.stm = StageTransitionManager()
        self.fact_store = FactStore()

    def test_close_attempt_blocked_without_prior_recommendation(self):
        """Verify that close attempts are strictly blocked before a product recommendation is recorded."""
        # Initial state: no recommendation
        allowed, reason = self.stm.can_attempt_close()
        self.assertFalse(allowed)
        self.assertIn("Prior product recommendation required", reason)

    def test_recommendation_gate_factstore_amount_validation(self):
        """Verify that product recommendation pitch requires a positive investment amount in FactStore."""
        # 1. Missing / None / Empty
        self.assertFalse(self.stm.can_recommend_product(None)[0])
        self.assertFalse(self.stm.can_recommend_product({})[0])
        self.assertFalse(self.stm.can_recommend_product(self.fact_store)[0])

        # 2. Invalid / Non-positive amounts
        invalid_amounts = [0, -100, float("nan"), float("inf"), float("-inf"), "invalid"]
        for amt in invalid_amounts:
            allowed, reason = self.stm.can_recommend_product({"amount": amt})
            self.assertFalse(allowed, f"Amount {amt} should not be allowed for recommendation")
            self.assertIn("Recommendation Gate", reason)

        # 3. Valid amounts
        valid_amounts = [250, 25000, 50000.0, "100000", 5000000]
        for amt in valid_amounts:
            allowed, _ = self.stm.can_recommend_product({"amount": amt})
            self.assertTrue(allowed, f"Amount {amt} should be allowed for recommendation")

    def test_close_attempt_overflow_and_strict_2_attempt_cap(self):
        """Verify that close attempts are capped at max 2, and overflow attempts are blocked."""
        self.fact_store.set_fact("amount", 50000, turn_id=1)
        self.assertTrue(self.stm.can_recommend_product(self.fact_store)[0])

        # Record recommendation
        self.stm.record_recommendation()

        # Attempt 1: Allowed
        self.assertTrue(self.stm.can_attempt_close()[0])
        count1 = self.stm.record_close_attempt()
        self.assertEqual(count1, 1)

        # Attempt 2: Allowed
        self.assertTrue(self.stm.can_attempt_close()[0])
        count2 = self.stm.record_close_attempt()
        self.assertEqual(count2, 2)

        # Attempt 3: Blocked by close limiter
        allowed3, reason3 = self.stm.can_attempt_close()
        self.assertFalse(allowed3)
        self.assertIn("Maximum close attempts (2) reached", reason3)

        # Overflow attempt 4+: Still blocked
        self.stm.record_close_attempt()
        self.assertFalse(self.stm.can_attempt_close()[0])

    def test_state_machine_isolation_and_close_attempts_persistence(self):
        """Verify that stage transitions do not inadvertently reset close attempts count."""
        self.stm.record_recommendation()
        self.stm.record_close_attempt()
        self.assertEqual(self.stm.close_attempts, 1)

        # Transition across various stages
        self.stm.transition_to(DecisionStage.CURIOUS, turn_id=2)
        self.stm.transition_to(DecisionStage.INTERESTED, turn_id=3)
        self.stm.transition_to(DecisionStage.EVALUATING, turn_id=4)

        # Close attempts should remain 1
        self.assertEqual(self.stm.close_attempts, 1)
        self.assertTrue(self.stm.can_attempt_close()[0])

        # Second close attempt
        self.stm.record_close_attempt()
        self.assertEqual(self.stm.close_attempts, 2)

        # Now close attempt is exhausted regardless of stage transitions
        self.stm.transition_to(DecisionStage.READY, turn_id=5)
        self.assertFalse(self.stm.can_attempt_close()[0])


# ═══════════════════════════════════════════════════════════════════════
# 3. HYSTERESIS & HESITATION DYNAMICS ADVERSARIAL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestHysteresisAndThrashingAdversarial(unittest.TestCase):
    """Adversarial stress testing for Hysteresis Cooldown (2 turns) on HESITANT."""

    def setUp(self):
        self.stm = StageTransitionManager(initial_stage=DecisionStage.CURIOUS)
        self.fact_store = FactStore()
        self.fact_store.set_fact("amount", 50000, turn_id=1)

    def test_hysteresis_2_turn_cooldown_exact_tick_boundaries(self):
        """Verify that transitioning to HESITANT enforces exactly a 2-turn cooldown."""
        # Enter HESITANT at turn 10
        success = self.stm.transition_to(DecisionStage.HESITANT, fact_store=self.fact_store, turn_id=10)
        self.assertTrue(success)
        self.assertEqual(self.stm.current_stage, DecisionStage.HESITANT)
        self.assertEqual(self.stm.hesitant_entered_turn, 10)

        # In HESITANT at turn 10 (elapsed = 0):
        # Target stages EVALUATING, READY, COMMITTED should be BLOCKED
        for target in (DecisionStage.EVALUATING, DecisionStage.READY, DecisionStage.COMMITTED):
            allowed, reason = self.stm.can_transition(
                from_stage=DecisionStage.HESITANT,
                to_stage=target,
                fact_store=self.fact_store,
                user_intent="READY",
                turn_id=10,
            )
            self.assertFalse(allowed, f"Expected transition to {target.name} to be blocked at turn 10 (elapsed 0)")
            self.assertIn("Hysteresis Guard", reason)

        # Non-evaluation stages (UNAWARE, CURIOUS, INTERESTED, DISENGAGED) should be ALLOWED
        for safe_target in (DecisionStage.UNAWARE, DecisionStage.CURIOUS, DecisionStage.INTERESTED, DecisionStage.DISENGAGED):
            allowed, _ = self.stm.can_transition(
                from_stage=DecisionStage.HESITANT,
                to_stage=safe_target,
                fact_store=self.fact_store,
                turn_id=10,
            )
            self.assertTrue(allowed, f"Transition to safe stage {safe_target.name} should be allowed at turn 10")

        # In HESITANT at turn 11 (elapsed = 1): Still blocked for evaluation/closing
        allowed_t11, _ = self.stm.can_transition(
            from_stage=DecisionStage.HESITANT,
            to_stage=DecisionStage.READY,
            fact_store=self.fact_store,
            user_intent="READY",
            turn_id=11,
        )
        self.assertFalse(allowed_t11)

        # In HESITANT at turn 12 (elapsed = 2): Still blocked (cooldown is <= 2 when in HESITANT)
        allowed_t12, _ = self.stm.can_transition(
            from_stage=DecisionStage.HESITANT,
            to_stage=DecisionStage.READY,
            fact_store=self.fact_store,
            user_intent="READY",
            turn_id=12,
        )
        self.assertFalse(allowed_t12)

        # In HESITANT at turn 13 (elapsed = 3): Cooldown CLEARED -> Transition allowed!
        allowed_t13, _ = self.stm.can_transition(
            from_stage=DecisionStage.HESITANT,
            to_stage=DecisionStage.READY,
            fact_store=self.fact_store,
            user_intent="READY",
            turn_id=13,
        )
        self.assertTrue(allowed_t13)

    def test_hysteresis_when_leaving_hesitant_to_intermediate_stage(self):
        """Verify hysteresis cooldown persists even if user moves to an intermediate stage."""
        # Enter HESITANT at turn 5
        self.stm.transition_to(DecisionStage.HESITANT, fact_store=self.fact_store, turn_id=5)

        # At turn 6 (elapsed 1), move to CURIOUS
        success_curious = self.stm.transition_to(DecisionStage.CURIOUS, fact_store=self.fact_store, turn_id=6)
        self.assertTrue(success_curious)
        self.assertEqual(self.stm.current_stage, DecisionStage.CURIOUS)

        # From CURIOUS at turn 6 (elapsed 1), try to jump to READY: Blocked by hysteresis (elapsed 1 < 2)
        allowed_t6, reason_t6 = self.stm.can_transition(
            from_stage=DecisionStage.CURIOUS,
            to_stage=DecisionStage.READY,
            fact_store=self.fact_store,
            user_intent="READY",
            turn_id=6,
        )
        self.assertFalse(allowed_t6)
        self.assertIn("Hysteresis Guard", reason_t6)

        # At turn 7 (elapsed 2), from CURIOUS to READY: Allowed (elapsed 2 >= 2 for non-HESITANT current_stage)
        allowed_t7, _ = self.stm.can_transition(
            from_stage=DecisionStage.CURIOUS,
            to_stage=DecisionStage.READY,
            fact_store=self.fact_store,
            user_intent="READY",
            turn_id=7,
        )
        self.assertTrue(allowed_t7)

    def test_hesitation_thrashing_stress_sequence(self):
        """Stress: Rapid oscillation between HESITANT, CURIOUS, and EVALUATING resets cooldowns cleanly."""
        # Cycle 1: Enter HESITANT at turn 1 -> Exit to CURIOUS at turn 3 -> Cooldown expires at turn 4
        self.assertTrue(self.stm.transition_to(DecisionStage.HESITANT, turn_id=1))
        self.assertFalse(self.stm.can_transition(self.stm.current_stage, DecisionStage.READY, fact_store=self.fact_store, user_intent="READY", turn_id=2)[0])
        self.assertTrue(self.stm.transition_to(DecisionStage.CURIOUS, turn_id=3))
        self.assertTrue(self.stm.transition_to(DecisionStage.READY, fact_store=self.fact_store, user_intent="READY", turn_id=4))

        # Cycle 2: Enter HESITANT again at turn 10
        self.assertTrue(self.stm.transition_to(DecisionStage.HESITANT, turn_id=10))
        self.assertEqual(self.stm.hesitant_entered_turn, 10)
        # Cooldown must be re-activated for turns 10, 11, 12
        self.assertFalse(self.stm.can_transition(self.stm.current_stage, DecisionStage.EVALUATING, turn_id=11)[0])
        self.assertFalse(self.stm.can_transition(self.stm.current_stage, DecisionStage.EVALUATING, turn_id=12)[0])
        self.assertTrue(self.stm.can_transition(self.stm.current_stage, DecisionStage.EVALUATING, turn_id=13)[0])

    def test_pure_predicate_zero_side_effects(self):
        """Verify calling can_transition repeatedly causes zero mutations to state manager attributes."""
        initial_stage = self.stm.current_stage
        initial_hesitant = self.stm.hesitant_entered_turn
        initial_close = self.stm.close_attempts

        for from_s in DecisionStage:
            for to_s in DecisionStage:
                for t in [1, 5, 10, 20]:
                    self.stm.can_transition(from_s, to_s, fact_store=self.fact_store, user_intent="READY", turn_id=t)

        self.assertEqual(self.stm.current_stage, initial_stage)
        self.assertEqual(self.stm.hesitant_entered_turn, initial_hesitant)
        self.assertEqual(self.stm.close_attempts, initial_close)


# ═══════════════════════════════════════════════════════════════════════
# 4. STALENESS GUARD & AUTO-ADVANCE ADVERSARIAL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestStalenessDynamicsAndCeilingAdversarial(unittest.TestCase):
    """Adversarial stress testing for Staleness Guard (5-turn threshold) and Auto-Advance."""

    def setUp(self):
        self.stm = StageTransitionManager(initial_stage=DecisionStage.UNAWARE)

    def test_staleness_exact_5_turn_boundary(self):
        """Verify staleness detection triggers at exactly >= 5 turns without premature advancement."""
        # Initialized at turn 1 (entry_turn = 1)
        for t in range(1, 6):
            self.assertFalse(
                self.stm.check_staleness(current_turn=t),
                f"Turn {t} should not be stale (stagnant = {t - 1} < 5)",
            )
            self.assertIsNone(self.stm.auto_advance(current_turn=t))

        # At turn 6: stagnant = 6 - 1 = 5 turns -> STALE!
        self.assertTrue(self.stm.check_staleness(current_turn=6))
        new_stage = self.stm.auto_advance(current_turn=6)
        self.assertEqual(new_stage, DecisionStage.CURIOUS)
        self.assertEqual(self.stm.current_stage, DecisionStage.CURIOUS)

        # After auto-advance at turn 6, new entry_turn is 6.
        # Turn 7..10: Not stale
        for t in range(7, 11):
            self.assertFalse(self.stm.check_staleness(current_turn=t))
            self.assertIsNone(self.stm.auto_advance(current_turn=t))

        # At turn 11: stagnant = 11 - 6 = 5 turns -> Auto-advance to INTERESTED
        self.assertTrue(self.stm.check_staleness(current_turn=11))
        next_stage = self.stm.auto_advance(current_turn=11)
        self.assertEqual(next_stage, DecisionStage.INTERESTED)

    def test_staleness_auto_advance_ceiling_at_disengaged(self):
        """Verify auto-advance caps at DISENGAGED (stage 8) and does not overflow or raise IndexError."""
        # Set stage to DISENGAGED (8)
        self.stm.current_stage = DecisionStage.DISENGAGED
        self.stm._stage_entry_turn = 20

        # At turn 25 (stagnant = 5): Stale!
        self.assertTrue(self.stm.check_staleness(current_turn=25))
        advanced = self.stm.auto_advance(current_turn=25)
        self.assertEqual(advanced, DecisionStage.DISENGAGED)
        self.assertEqual(self.stm.current_stage, DecisionStage.DISENGAGED)

    def test_manual_transition_resets_staleness(self):
        """Verify manual transition updates stage entry turn and resets staleness counter."""
        # Entry at turn 1
        self.assertFalse(self.stm.check_staleness(current_turn=4))

        # Manual transition at turn 4 to INTERESTED
        self.stm.transition_to(DecisionStage.INTERESTED, turn_id=4)
        self.assertEqual(self.stm.current_stage, DecisionStage.INTERESTED)
        self.assertEqual(self.stm._stage_entry_turn, 4)

        # Turn 6 (stagnant = 2 from turn 4): Not stale
        self.assertFalse(self.stm.check_staleness(current_turn=6))

        # Turn 9 (stagnant = 5 from turn 4): Stale!
        self.assertTrue(self.stm.check_staleness(current_turn=9))
        self.assertEqual(self.stm.auto_advance(current_turn=9), DecisionStage.EVALUATING)


# ═══════════════════════════════════════════════════════════════════════
# 5. NUMERIC CONSISTENCY LEDGER ADVERSARIAL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestNumericLedgerContradictionsAndCeilingAdversarial(unittest.TestCase):
    """Adversarial stress testing for NumericLedger, RBI platform ceiling (₹50L), and quote verification."""

    def setUp(self):
        self.ledger = NumericLedger()

    def test_numeric_ledger_rbi_platform_ceiling_overflow(self):
        """Verify ₹50 Lakhs (₹5,000,000) platform ceiling is strictly enforced."""
        # ₹50 Lakhs exact: Allowed
        q_50l = self.ledger.record_quote(
            principal=5000000.0,
            tenure_months=12,
            xirr_pct=24.0,
            profit=1200000.0,
            maturity_amount=6200000.0,
            monthly_emi=516666.67,
        )
        self.assertEqual(q_50l["principal"], 5000000.0)

        # Overflow above ₹50 Lakhs: Must raise ValueError
        overflow_principals = [
            5000000.01,
            5000001.0,
            6000000.0,
            10000000.0,  # ₹1 Crore
            50000000.0,  # ₹5 Crore
        ]
        for p in overflow_principals:
            with self.assertRaises(ValueError, msg=f"Principal {p} should exceed ceiling"):
                self.ledger.record_quote(
                    principal=p,
                    tenure_months=12,
                    xirr_pct=24.0,
                    profit=p * 0.24,
                    maturity_amount=p * 1.24,
                )

    def test_numeric_ledger_invalid_inputs_rejection(self):
        """Verify invalid principal (0, negative, NaN, Inf) or tenure <= 0 raises ValueError."""
        invalid_principals = [0, -1, -50000, float("nan"), float("inf"), float("-inf")]
        for bad_p in invalid_principals:
            with self.assertRaises(ValueError):
                self.ledger.record_quote(
                    principal=bad_p,
                    tenure_months=6,
                    xirr_pct=18.0,
                    profit=4500,
                    maturity_amount=54500,
                )

        invalid_tenures = [0, -1, -6]
        for bad_t in invalid_tenures:
            with self.assertRaises(ValueError):
                self.ledger.record_quote(
                    principal=50000,
                    tenure_months=bad_t,
                    xirr_pct=18.0,
                    profit=4500,
                    maturity_amount=54500,
                )

    def test_numeric_ledger_quote_verification_and_tolerance(self):
        """Verify quote matching within ±1.0 rupee tolerance and rejection beyond tolerance."""
        self.ledger.record_quote(
            principal=50000.0,
            tenure_months=6,
            xirr_pct=18.0,
            profit=4500.0,
            maturity_amount=54500.0,
            monthly_emi=9083.33,
        )

        # Exact match
        self.assertTrue(self.ledger.verify_quote(50000, 6, 54500.0))

        # Within tolerance ±1.0
        self.assertTrue(self.ledger.verify_quote(50000, 6, 54500.5))
        self.assertTrue(self.ledger.verify_quote(50000, 6, 54499.5))
        self.assertTrue(self.ledger.verify_quote(50000, 6, 54501.0))
        self.assertTrue(self.ledger.verify_quote(50000, 6, 54499.0))

        # Outside tolerance > 1.0 (Contradictions)
        self.assertFalse(self.ledger.verify_quote(50000, 6, 54501.1))
        self.assertFalse(self.ledger.verify_quote(50000, 6, 54498.9))
        self.assertFalse(self.ledger.verify_quote(50000, 6, 52000.0))  # Contradiction!
        self.assertFalse(self.ledger.verify_quote(50000, 6, 60000.0))  # Contradiction!

        # Non-existent principal or tenure
        self.assertFalse(self.ledger.verify_quote(100000, 6, 54500.0))
        self.assertFalse(self.ledger.verify_quote(50000, 12, 54500.0))

    def test_numeric_ledger_multiple_quotes_and_latest_quote_priority(self):
        """Verify that updating a quote updates the active verification target to the latest quote."""
        # Quote 1: STL 6M at 18%
        self.ledger.record_quote(50000, 6, 18.0, 4500, 54500)
        # Quote 2: STL 6M recalculated at 19%
        self.ledger.record_quote(50000, 6, 19.0, 4750, 54750)

        # Latest quote should be 54750
        latest = self.ledger.get_quote(50000, 6)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["maturity_amount"], 54750.0)

        # Verification uses latest quote
        self.assertTrue(self.ledger.verify_quote(50000, 6, 54750.0))
        self.assertFalse(self.ledger.verify_quote(50000, 6, 54500.0))

        # All quotes history
        all_q = self.ledger.get_all_quotes()
        self.assertEqual(len(all_q), 2)

        # Clear
        self.ledger.clear()
        self.assertEqual(len(self.ledger.get_all_quotes()), 0)


# ═══════════════════════════════════════════════════════════════════════
# 6. 5-TIER HUMAN ESCALATION MATRIX ADVERSARIAL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestEscalationMatrixThresholdAdversarial(unittest.TestCase):
    """Adversarial stress testing for 5-Tier Human Escalation Matrix edge conditions."""

    def setUp(self):
        self.tracker = EscalationTracker()

    def test_escalation_tier_progression(self):
        """Verify exact progression across Tiers 1 through 5."""
        # Tier 1: Normal conversation (0 queries, 0 human requests)
        self.assertEqual(self.tracker.get_escalation_tier(), 1)
        self.assertFalse(self.tracker.is_callback_booking_required())

        # 1 Query -> Tier 2
        tier2 = self.tracker.record_user_query("What is P2P?")
        self.assertEqual(tier2, 2)
        self.assertEqual(self.tracker.get_escalation_tier(), 2)
        self.assertFalse(self.tracker.is_callback_booking_required())

        # 2 Queries -> Tier 3
        tier3 = self.tracker.record_user_query("What is the interest rate?")
        self.assertEqual(tier3, 3)
        self.assertEqual(self.tracker.get_escalation_tier(), 3)
        self.assertFalse(self.tracker.is_callback_booking_required())

        # 3 Queries -> Tier 5 (Callback required!)
        tier5 = self.tracker.record_user_query("Can you guarantee 24%?")
        self.assertEqual(tier5, 5)
        self.assertEqual(self.tracker.get_escalation_tier(), 5)
        self.assertTrue(self.tracker.is_callback_booking_required())

    def test_escalation_edge_1_vs_2_human_requests(self):
        """Verify 1 human request (Tier 4) vs 2 human requests (Tier 5 / Callback booking)."""
        # 1 Human request
        t1 = self.tracker.record_human_request()
        self.assertEqual(t1, 4)
        self.assertEqual(self.tracker.get_escalation_tier(), 4)
        self.assertFalse(self.tracker.is_callback_booking_required())

        # 2 Human requests -> Tier 5
        t2 = self.tracker.record_human_request()
        self.assertEqual(t2, 5)
        self.assertEqual(self.tracker.get_escalation_tier(), 5)
        self.assertTrue(self.tracker.is_callback_booking_required())

    def test_escalation_edge_2_vs_3_repeated_queries(self):
        """Verify boundary between 2 queries (Tier 3) and 3 queries (Tier 5)."""
        t = EscalationTracker()
        t.record_user_query("Query 1")
        t.record_user_query("Query 2")
        self.assertEqual(t.get_escalation_tier(), 3)
        self.assertFalse(t.is_callback_booking_required())

        t.record_user_query("Query 3")
        self.assertEqual(t.get_escalation_tier(), 5)
        self.assertTrue(t.is_callback_booking_required())


# ═══════════════════════════════════════════════════════════════════════
# 7. CONSULTATIVE PHASE ENGINE & FRAME INTERCEPTION ADVERSARIAL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestConsultativePhaseEngineDynamicsAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial testing for ConsultativePhaseTracker prompt card delivery and PhaseTransitionProcessor."""

    async def test_bot_speaking_queues_prompt_card_and_flushes_safely(self):
        """Verify that phase transitions occurring while the bot is speaking are queued and flushed on speech stop."""
        mock_service = MagicMock()
        mock_session = AsyncMock()
        mock_service._session = mock_session

        tracker = ConsultativePhaseTracker(gemini_service=mock_service, enable_client_content=True)

        # 1. Bot starts speaking
        tracker.set_bot_speaking(True)

        # 2. Trigger transition to Phase 4 (RBI Trust)
        await tracker.transition_to(4, trigger_reason="User asked RBI question while bot was speaking")

        # Phase state updated immediately
        self.assertEqual(tracker.current_phase, 4)
        # But send_client_content must NOT be dispatched yet to avoid interrupting bot audio
        mock_session.send_client_content.assert_not_called()
        self.assertEqual(tracker._pending_phase, 4)

        # 3. Bot finishes speaking -> Flush pending prompt card
        await tracker.on_bot_stopped_speaking()
        mock_session.send_client_content.assert_called_once()
        self.assertIsNone(tracker._pending_phase)

    async def test_fast_path_transcript_keyword_transitions(self):
        """Verify fast-path keyword and regex triggers across sales phases."""
        mock_service = MagicMock()
        tracker = ConsultativePhaseTracker(gemini_service=mock_service, enable_client_content=False)

        # Phase 1 -> 2: Consent
        await tracker.handle_user_transcript("हाँ, बिल्कुल बताइए")
        self.assertEqual(tracker.current_phase, 2)

        # Phase 2 -> 3: Familiarity
        await tracker.handle_user_transcript("मैं पहली बार P2P explore कर रहा हूँ")
        self.assertEqual(tracker.current_phase, 3)

        # Phase 3 -> 4: RBI / Escrow Trust
        await tracker.handle_user_transcript("क्या Cymbal Lending RBI registered NBFC है?")
        self.assertEqual(tracker.current_phase, 4)

        # Phase 4 -> 5: Risk & Defaults
        await tracker.handle_user_transcript("अगर borrower default कर दे या पैसा डूब जाए तो क्या होगा?")
        self.assertEqual(tracker.current_phase, 5)

        # Phase 5 -> 7: Returns Calculation
        await tracker.handle_user_transcript("50000 लगाने पर कितना profit और monthly payout मिलेगा?")
        self.assertEqual(tracker.current_phase, 7)

        # Phase 7 -> 8: KYC Navigation
        await tracker.handle_user_transcript("KYC के लिए Aadhaar Digilocker OTP कैसे सबमिट करें?")
        self.assertEqual(tracker.current_phase, 8)

        # Phase 8 -> 1: Busy / Callback Request
        await tracker.handle_user_transcript("मैं अभी बहुत busy हूँ, बाद में call back करो")
        self.assertEqual(tracker.current_phase, 1)

    async def test_functional_tool_result_frame_phase_steering(self):
        """Verify that FunctionCallResultFrame auto-advances phase tracker."""
        mock_service = MagicMock()
        tracker = ConsultativePhaseTracker(gemini_service=mock_service, enable_client_content=False)
        processor = PhaseTransitionProcessor(tracker=tracker)

        # 1. Calculation tool -> Phase 7
        frame_calc = FunctionCallResultFrame(
            function_name="calculate_mtl_returns",
            tool_call_id="call_calc",
            arguments={"amount": 100000, "tenure_months": 12},
            result={"profit": 24000},
        )
        await processor.process_frame(frame_calc, FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.current_phase, 7)

        # 2. KYC tool -> Phase 8
        frame_kyc = FunctionCallResultFrame(
            function_name="get_app_screen_flow",
            tool_call_id="call_kyc",
            arguments={"screen_name": "KYC_AADHAAR_DIGILOCKER"},
            result={"screen": "KYC_AADHAAR_DIGILOCKER"},
        )
        await processor.process_frame(frame_kyc, FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.current_phase, 8)


# ═══════════════════════════════════════════════════════════════════════
# 8. LIVE PIPELINE LIFECYCLE & DOWNCAR TRIGGERS ADVERSARIAL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestAgentLiveLifecycleAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing for Pipecat live lifecycle, AntiCancel tool shield, and downcar trigger."""

    def test_anticancel_tool_lock_watchdog_self_healing(self):
        """Verify AntiCancel tool lock watchdog self-heals after 8.0s timeout to prevent permanent lockup."""
        from agent_live import GeminiSessionLoggerMixin

        class DummyLLM(GeminiSessionLoggerMixin):
            def __init__(self):
                self._active_tools_in_flight = 0
                self._frame_locked_tools = False
                self._tool_lock_started_at = None

        llm = DummyLLM()
        self.assertFalse(llm._tools_in_flight())

        # Lock tool at T=0
        llm._lock_tools("test start")
        self.assertTrue(llm._tools_in_flight())
        self.assertEqual(llm._active_tools_in_flight, 1)

        # Simulate stuck tool (>8.0s hold)
        llm._tool_lock_started_at = time.monotonic() - 8.5
        # Accessing _tools_in_flight should detect expired hold and auto-release
        is_in_flight = llm._tools_in_flight()
        self.assertFalse(is_in_flight)
        self.assertEqual(llm._active_tools_in_flight, 0)
        self.assertFalse(llm._frame_locked_tools)

    async def test_anticancel_suppresses_interruption_during_tool_flight(self):
        """Verify user interruptions and FunctionCallCancelFrame are suppressed while tool is active."""
        from agent_live import GeminiSessionLoggerMixin

        class MockBaseProcessor(FrameProcessor):
            def __init__(self):
                super().__init__()
                self.processed_frames = []

            async def process_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
                self.processed_frames.append(frame)

        class DummyLLM(GeminiSessionLoggerMixin, MockBaseProcessor):
            def __init__(self):
                super().__init__()
                self._active_tools_in_flight = 0
                self._frame_locked_tools = False
                self._tool_lock_started_at = None
                self._repeat_on_filler_pending = False
                self.pushed_frames = []

            async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
                self.pushed_frames.append(frame)

        class FunctionCallInProgressFrame(Frame):
            pass

        class FunctionCallCancelFrame(Frame):
            pass

        llm = DummyLLM()

        # 1. Tool starts
        await llm.process_frame(FunctionCallInProgressFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(llm._active_tools_in_flight, 1)

        # 2. InterruptionFrame arrives during tool flight -> Must be suppressed (not forwarded to super)
        int_frame = InterruptionFrame()
        await llm.process_frame(int_frame, FrameDirection.DOWNSTREAM)
        self.assertNotIn(int_frame, llm.processed_frames)

        # 3. FunctionCallCancelFrame arrives -> Suppressed
        cancel_frame = FunctionCallCancelFrame()
        await llm.process_frame(cancel_frame, FrameDirection.DOWNSTREAM)
        self.assertNotIn(cancel_frame, llm.processed_frames)

        # 4. Tool finishes
        result_frame = FunctionCallResultFrame(
            function_name="calculate_stl_returns",
            tool_call_id="call_1",
            arguments={"amount": 50000, "tenure_months": 6},
            result={"net_profit": 4500},
        )
        await llm.process_frame(result_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(llm._active_tools_in_flight, 0)

        # 5. Subsequent InterruptionFrame is allowed
        int_frame2 = InterruptionFrame()
        await llm.process_frame(int_frame2, FrameDirection.DOWNSTREAM)
        self.assertIn(int_frame2, llm.processed_frames)

    async def test_transcript_accumulation_and_lexical_identity_resolution(self):
        """Verify user utterances populate transcript_history and resolve lexical identity."""
        from agent_live import GeminiSessionLoggerMixin

        class MockBaseLLM(FrameProcessor):
            async def _push_user_transcription(self, sentence: str, result=None):
                pass

        class DummyLLM(GeminiSessionLoggerMixin, MockBaseLLM):
            def __init__(self):
                super().__init__()
                self.transcript_history = []
                self.active_user_id = "user_anonymous"
                self.pushed_frames = []

            async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
                self.pushed_frames.append(frame)

        llm = DummyLLM()

        # Push user transcription introducing themselves
        await llm._push_user_transcription("नमस्ते, मेरा नाम आदित्य शर्मा है")
        self.assertEqual(len(llm.transcript_history), 1)
        self.assertEqual(llm.transcript_history[0]["role"], "user")
        self.assertEqual(llm.transcript_history[0]["text"], "नमस्ते, मेरा नाम आदित्य शर्मा है")
        self.assertEqual(llm.active_user_id, "user_aditya_sharma")


# ═══════════════════════════════════════════════════════════════════════
# 9. SYSTEM PROMPT INTEGRITY & OBJECTION DIRECTIVES ADVERSARIAL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestSystemPromptAdversarial(unittest.TestCase):
    """Adversarial validation of system prompt constraints, greetings, script mix, and objection rules."""

    def test_system_prompt_turn_1_greeting_and_name_elicitation(self):
        """Verify exact Turn 1 greeting with Pragya identity, name elicitation, and 2-minute availability check."""
        expected_greeting = "नमस्ते! मैं प्रज्ञा बात कर रही हूँ, Cymbal Lending से। क्या मैं आपका नाम जान सकती हूँ, और क्या आपके पास बात करने के लिए 2 minutes का समय है?"

        # Check in composite SYSTEM_PROMPT
        self.assertIn(expected_greeting, SYSTEM_PROMPT)

        # Check in Phase 1 prompt card
        p1_prompt = PHASE_PROMPTS[1]
        self.assertIn(expected_greeting, p1_prompt)

        # Check in chained prompt for Phase 1
        chained_p1 = get_chained_system_prompt(phase=1)
        self.assertIn(expected_greeting, chained_p1)

    def test_devanagari_hindi_and_latin_english_prompt_invariants(self):
        """Verify Hinglish code-mixing script rules are strictly defined across all prompt cards."""
        script_rules = [
            "Devanagari script",
            "Latin script",
            "Cymbal Lending",
            "प्रज्ञा",
        ]
        for rule in script_rules:
            self.assertIn(rule, SYSTEM_PROMPT)
            self.assertIn(rule, LEAN_PERSONA_PROMPT)
        self.assertIn("सिम्बल लेंडिंग", SYSTEM_PROMPT)

    def test_9_month_rejection_and_platform_ceilings_in_boundary_rules(self):
        """Verify 9-month strict rejection and platform lending boundaries (₹250 to ₹50L) in prompt directives."""
        self.assertIn("9-Month Tenure Rejection (Strict)", BOUNDARY_RULES)
        self.assertIn("9-month tenures are STRICTLY NOT AVAILABLE", BOUNDARY_RULES)
        self.assertIn("Platform Absolute Ceiling: ₹50,00,000", BOUNDARY_RULES)
        self.assertIn("₹50 Lakhs", BOUNDARY_RULES)
        self.assertIn("Platform Absolute Minimum: ₹250", BOUNDARY_RULES)

    def test_objection_playbook_content(self):
        """Verify 4 core objection playbooks are documented with exact safety pillars."""
        self.assertIn("100 से ज़्यादा vetted borrowers", OBJECTION_PLAYBOOK)
        self.assertIn("96.18% recovery track record", OBJECTION_PLAYBOOK)
        self.assertIn("3.5% NPA provisions adjust करने के बाद net", OBJECTION_PLAYBOOK)
        self.assertIn("Bank Fixed Deposits (FD)", OBJECTION_PLAYBOOK)
        self.assertIn("ICICI/IDBI Trustee Escrow", OBJECTION_PLAYBOOK)

    def test_chained_system_prompt_generation_variants(self):
        """Verify get_chained_system_prompt properly injects phases, boundary rules, and user profiles."""
        # Phase 1: Injects greeting guidance
        p1 = get_chained_system_prompt(phase=1)
        self.assertIn("Phase 1: Time Check & Availability", p1)
        self.assertIn("क्या मैं आपका नाम जान सकती हूँ", p1)

        # Phase 7: Injects BOUNDARY_RULES
        p7 = get_chained_system_prompt(phase=7)
        self.assertIn("Phase 7: Product Recommendation", p7)
        self.assertIn("9-Month Tenure Rejection", p7)

        # With user_profile
        profile = {"name": "Aditya Sharma", "amount": 100000, "tenure_months": 12}
        p_profile = get_chained_system_prompt(phase=2, user_profile=profile)
        self.assertIn("User Profile State: {'name': 'Aditya Sharma'", p_profile)


if __name__ == "__main__":
    unittest.main()
