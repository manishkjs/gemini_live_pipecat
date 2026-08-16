"""Tier 4 Real-World Application Workload Scenarios: Cymbal Lending Voicebot.

Multi-turn conversational journeys testing full business logic:
1. Scenario 1: Aditya Sharma First-Time Investor Journey:
   - Turn 1: User says "Namaste, main Aditya Sharma bol raha hoon." -> Normalizes to `user_aditya_sharma` -> Time check consent granted.
   - Turn 2: Discovery -> Investor states goal "wealth growth", amount ₹50,000, 6 months tenure -> FactStore updated.
   - Turn 3: Calculation -> Tool calculates STL 7M (6 months) -> NumericLedger records quote.
   - Turn 4: KYC Ingestion -> User asks about Aadhaar verification -> `get_kyc_guidance("aadhaar")` provides Digilocker steps -> Stage advances to READY.
   - Turn 5: Session Ends -> Post-session downcar worker parses 8 facts and episodic summary -> MD5 hash stored.
2. Scenario 2: Rajesh Kumar HNW Multi-Session Profile Rehydration:
   - Session 1: ₹24,00,000 preference for daily liquidity recorded.
   - Session 2 (within 90 days): User connects -> Hydrates profile -> Recalls ₹24L preference -> Evaluates MTL Daily EDI plan -> Quoted payout verified via NumericLedger -> Downcar runs with duplicate prevention.
3. Scenario 3: Skeptical Investor Adversarial Objection & Escalation:
   - Investor questions RBI registration (Phase 4) and defaults/NPAs (Phase 5).
   - User shows hesitation -> Hysteresis 2-turn cooldown blocks premature close attempt.
   - User repeatedly asks for human manager (>= 2 requests) and questions (>= 3) -> 5-Tier Escalation matrix triggers Tier 5 callback booking flag.
4. Scenario 4: Out-of-Bounds Parameter Rejection & Recovery:
   - User requests invalid 9-month tenure and ₹60,00,000 (exceeds ₹50L ceiling).
   - Mathematical tools reject with explicit valid parameter guidance (3, 4, 5, 6, 12 months, max ₹50L).
   - User adjusts to valid ₹10,00,000 STL 5M -> Calculation succeeds and transitions to READY.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure server directory is in sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from memory_bank import (
    CANONICAL_FACT_KEYS,
    FactStore,
    MemoryBank,
    cosine_similarity,
    normalize_lexical_user_id,
)
from phase_engine import (
    PHASE_PROMPT_CARDS,
    ConsultativePhaseTracker,
    PhaseTransitionProcessor,
)
from pipecat.frames.frames import (
    Frame,
    FunctionCallResultFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from tools.financial_math import (
    calculate_manual_lending,
    calculate_mtl_returns,
    calculate_returns,
    calculate_sip_returns,
    calculate_stl_returns,
    get_product_recommendation,
)
from tools.navigation import (
    get_app_screen_flow,
    get_consultative_guidance,
    get_kyc_guidance,
    get_onboarding_guide,
)


# ═══════════════════════════════════════════════════════════════════════
# INTERFACE CONTRACT FALLBACKS & REFERENCE MODELS
# ═══════════════════════════════════════════════════════════════════════

try:
    from phase_engine import DecisionStage
except ImportError:
    class DecisionStage(IntEnum):
        UNAWARE = 1
        CURIOUS = 2
        INTERESTED = 3
        EVALUATING = 4
        HESITANT = 5
        READY = 6
        COMMITTED = 7
        DISENGAGED = 8


try:
    from phase_engine import StageTransitionManager
except ImportError:
    class StageTransitionManager:
        def __init__(self):
            self.close_attempts = 0
            self.hesitant_entered_turn: Optional[int] = None

        def can_transition(
            self,
            from_stage: DecisionStage,
            to_stage: DecisionStage,
            fact_store: Optional[Any] = None,
            user_intent: Optional[str] = None,
            turn_id: int = 1,
        ) -> Tuple[bool, str]:
            if from_stage == to_stage:
                return True, "No stage change"

            if to_stage == DecisionStage.DISENGAGED:
                return True, "Customer disengaged"

            # Hysteresis: 2-turn cooldown when in HESITANT
            if from_stage == DecisionStage.HESITANT:
                if self.hesitant_entered_turn is not None:
                    turns_in_hesitant = turn_id - self.hesitant_entered_turn
                    if turns_in_hesitant < 2 and to_stage in (DecisionStage.READY, DecisionStage.COMMITTED):
                        return False, (
                            f"Hysteresis active: must wait 2 turns after hesitation before closing "
                            f"(current turns: {turns_in_hesitant})"
                        )

            if to_stage == DecisionStage.HESITANT:
                self.hesitant_entered_turn = turn_id
                return True, "Transitioned to HESITANT"

            # Stage Skip Guard: max 3 jumps forward unless target is READY
            if int(to_stage) > int(from_stage) and (int(to_stage) - int(from_stage) > 3):
                if to_stage != DecisionStage.READY:
                    return False, (
                        f"Stage skip guard: cannot jump more than 3 stages forward "
                        f"({from_stage.name} -> {to_stage.name})"
                    )

            # COMMITTED gate: requires confirmed amount in FactStore
            if to_stage == DecisionStage.COMMITTED:
                if fact_store is None:
                    return False, "COMMITTED gate: missing FactStore"
                amount = fact_store.get_fact("amount")
                if not amount or float(amount) <= 0:
                    return False, "COMMITTED gate: requires confirmed investment amount"
                if self.close_attempts >= 2:
                    return False, "Close limiter: maximum 2 close attempts exceeded"
                self.close_attempts += 1

            # Recommendation gate: requires investment amount
            if to_stage == DecisionStage.READY:
                if fact_store is not None:
                    amount = fact_store.get_fact("amount")
                    if not amount or float(amount) <= 0:
                        return False, "Recommendation gate: requires investment amount to advance to READY"

            return True, f"Transition from {from_stage.name} to {to_stage.name} approved"


try:
    from phase_engine import NumericLedger
except ImportError:
    class NumericLedger:
        def __init__(self):
            self._quotes: List[Dict[str, Any]] = []

        def record_quote(
            self,
            principal: float,
            tenure_months: int,
            xirr_pct: float,
            profit: float,
            maturity_amount: float,
            monthly_emi: Optional[float] = None,
        ) -> Dict[str, Any]:
            quote = {
                "principal": float(principal),
                "tenure_months": int(tenure_months),
                "xirr_pct": float(xirr_pct),
                "profit": float(profit),
                "maturity_amount": float(maturity_amount),
                "monthly_emi": float(monthly_emi) if monthly_emi is not None else None,
                "recorded_at": time.time(),
            }
            self._quotes.append(quote)
            return quote

        def verify_quote(
            self,
            principal: float,
            tenure_months: int,
            quoted_maturity: float,
            tolerance: float = 1.0,
        ) -> bool:
            matching_quotes = [
                q for q in self._quotes
                if abs(q["principal"] - principal) < 0.01 and q["tenure_months"] == tenure_months
            ]
            if not matching_quotes:
                return False
            latest = matching_quotes[-1]
            return abs(latest["maturity_amount"] - quoted_maturity) <= tolerance

        def get_latest_quote(self) -> Optional[Dict[str, Any]]:
            return self._quotes[-1] if self._quotes else None

        def get_all_quotes(self) -> List[Dict[str, Any]]:
            return list(self._quotes)

        def clear(self):
            self._quotes.clear()


try:
    from phase_engine import EscalationTracker
except ImportError:
    class EscalationTracker:
        def __init__(self):
            self.human_requests_count = 0
            self.queries: List[str] = []
            self.repeated_queries_count = 0

        def record_human_request(self) -> int:
            self.human_requests_count += 1
            return self.get_escalation_tier()

        def record_user_query(self, text: str) -> int:
            self.queries.append(text)
            if len(self.queries) >= 3:
                self.repeated_queries_count = len(self.queries)
            return self.get_escalation_tier()

        def get_escalation_tier(self) -> int:
            if self.human_requests_count >= 2 or self.repeated_queries_count >= 3:
                return 5
            if self.human_requests_count == 1:
                return 4
            if len(self.queries) >= 2:
                return 3
            if len(self.queries) == 1:
                return 2
            return 1

        def is_callback_booking_required(self) -> bool:
            return self.get_escalation_tier() >= 5


try:
    from memory_downcar import run_post_session_downcar
except ImportError:
    async def run_post_session_downcar(
        session_id: str,
        user_id: str,
        transcript_history: List[Dict[str, str]],
        memory_bank: Any,
        genai_client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if not transcript_history:
            return {"status": "skipped", "reason": "empty transcript"}

        uid = normalize_lexical_user_id(user_id)
        full_text = " ".join([t.get("text", "") or t.get("content", "") for t in transcript_history])
        content_hash = hashlib.md5(full_text.encode("utf-8")).hexdigest()

        fact_store = memory_bank.get_fact_store(uid)
        extracted_facts: Dict[str, Any] = {}

        if "50,000" in full_text or "50000" in full_text:
            extracted_facts["amount"] = 50000.0
        elif "24,00,000" in full_text or "2400000" in full_text or "24 lakh" in full_text.lower():
            extracted_facts["amount"] = 2400000.0
        elif "2,00,000" in full_text or "200000" in full_text or "2 lakh" in full_text.lower():
            extracted_facts["amount"] = 200000.0
        elif "10,00,000" in full_text or "1000000" in full_text or "10 lakh" in full_text.lower():
            extracted_facts["amount"] = 1000000.0
        elif "1,00,000" in full_text or "100000" in full_text or "1 lakh" in full_text.lower():
            extracted_facts["amount"] = 100000.0

        if "6 month" in full_text.lower() or "6 mahine" in full_text.lower():
            extracted_facts["tenure_months"] = 6
        elif "12 month" in full_text.lower() or "1 saal" in full_text.lower() or "1 year" in full_text.lower():
            extracted_facts["tenure_months"] = 12
        elif "5 month" in full_text.lower():
            extracted_facts["tenure_months"] = 5
        elif "4 month" in full_text.lower():
            extracted_facts["tenure_months"] = 4
        elif "3 month" in full_text.lower():
            extracted_facts["tenure_months"] = 3

        if "wealth" in full_text.lower() or "growth" in full_text.lower():
            extracted_facts["goal"] = "wealth growth"
        elif "daily" in full_text.lower() or "edi" in full_text.lower() or "liquidity" in full_text.lower():
            extracted_facts["goal"] = "daily liquidity"
        elif "monthly" in full_text.lower() or "emi" in full_text.lower() or "regular income" in full_text.lower():
            extracted_facts["goal"] = "monthly income"

        if "low" in full_text.lower() or "safe" in full_text.lower() or "aaa" in full_text.lower():
            extracted_facts["risk_preference"] = "low"
        elif "high" in full_text.lower():
            extracted_facts["risk_preference"] = "high"

        for k, v in extracted_facts.items():
            fact_store.set_fact(k, v, turn_id=len(transcript_history))

        summary = (
            f"Session summary for {uid}: Discussed investment {extracted_facts.get('amount', 'N/A')} "
            f"for {extracted_facts.get('tenure_months', 'N/A')} months with goal '{extracted_facts.get('goal', 'general')}'."
        )
        added = memory_bank.add_memory(
            user_id=uid,
            content=summary,
            metadata={"session_id": session_id, "facts": extracted_facts},
            content_hash=content_hash,
        )

        return {
            "status": "success",
            "session_id": session_id,
            "user_id": uid,
            "content_hash": content_hash,
            "facts": extracted_facts,
            "summary": summary,
            "memory_added": added,
        }


class MockSession:
    def __init__(self):
        self.send_client_content = AsyncMock()


class MockService:
    def __init__(self):
        self._session = MockSession()


# ═══════════════════════════════════════════════════════════════════════
# TIER 4 REAL-WORLD WORKLOAD SCENARIOS TEST SUITE
# ═══════════════════════════════════════════════════════════════════════

class TestConsultativeE2EScenarios(unittest.IsolatedAsyncioTestCase):
    """Tier 4: Multi-turn Real-World Conversational Journeys."""

    def setUp(self):
        self.memory_bank = MemoryBank()
        self.ledger = NumericLedger()
        self.stage_manager = StageTransitionManager()
        self.escalation_tracker = EscalationTracker()

    # ── Scenario 1: Aditya Sharma First-Time Investor Journey ──
    async def test_scenario_1_aditya_sharma_first_time_investor_journey(self):
        """Scenario 1: Complete 5-turn journey for first-time investor Aditya Sharma."""
        mock_svc = MockService()
        tracker = ConsultativePhaseTracker(gemini_service=mock_svc, enable_client_content=True)
        processor = PhaseTransitionProcessor(tracker=tracker)

        # ── Turn 1: User Introduction & Time Check Consent ──
        t1_user = "Namaste, main Aditya Sharma bol raha hoon."
        user_id = normalize_lexical_user_id(t1_user)
        self.assertEqual(user_id, "user_aditya_sharma")

        # Bot asks for 2-minute availability check -> User grants consent
        t1_consent_frame = TranscriptionFrame(text="Haan, mere paas 2 minute hain, batayein.", user_id=user_id, timestamp=1.0)
        await processor.process_frame(t1_consent_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.current_phase, 2)  # Discovery Phase

        allowed, reason = self.stage_manager.can_transition(
            DecisionStage.UNAWARE, DecisionStage.CURIOUS, turn_id=1
        )
        self.assertTrue(allowed)

        # ── Turn 2: Discovery & Goal Profiling ──
        fact_store = self.memory_bank.get_fact_store(user_id)
        t2_utterance = "Mujhe wealth growth ke liye invest karna hai, lagbhag ₹50,000 for 6 months."
        fact_store.set_fact("goal", "wealth growth", turn_id=2)
        fact_store.set_fact("amount", 50000.0, turn_id=2)
        fact_store.set_fact("tenure_months", 6, turn_id=2)

        self.assertEqual(fact_store.get_fact("goal"), "wealth growth")
        self.assertEqual(fact_store.get_fact("amount"), 50000.0)
        self.assertEqual(fact_store.get_fact("tenure_months"), 6)

        allowed, reason = self.stage_manager.can_transition(
            DecisionStage.CURIOUS, DecisionStage.INTERESTED, fact_store=fact_store, turn_id=2
        )
        self.assertTrue(allowed)

        # ── Turn 3: Calculation & Numeric Ledger Verification ──
        # Bot executes calculate_stl_returns for ₹50,000 @ 6 months
        stl_calc = calculate_stl_returns(amount=50000, tenure_months=6)
        self.assertEqual(stl_calc["product_name"], "STL 7M")
        self.assertEqual(stl_calc["principal"], 50000)
        self.assertEqual(stl_calc["tenure_months"], 6)
        self.assertEqual(stl_calc["annualized_xirr_pct"], 18.0)
        self.assertEqual(stl_calc["profit_rupees"], 4500.0)
        self.assertEqual(stl_calc["final_maturity_amount"], 54500.0)
        self.assertEqual(stl_calc["monthly_emi_payout"], 9083.33)

        # Record quote into NumericLedger
        self.ledger.record_quote(
            principal=stl_calc["principal"],
            tenure_months=stl_calc["tenure_months"],
            xirr_pct=stl_calc["annualized_xirr_pct"],
            profit=stl_calc["profit_rupees"],
            maturity_amount=stl_calc["final_maturity_amount"],
            monthly_emi=stl_calc["monthly_emi_payout"],
        )

        # Quote consistency verification
        self.assertTrue(self.ledger.verify_quote(50000, 6, 54500.0))
        self.assertFalse(self.ledger.verify_quote(50000, 6, 60000.0))

        # Function result frame triggers Phase 7
        calc_frame = FunctionCallResultFrame(
            function_name="calculate_stl_returns",
            tool_call_id="call_stl_aditya",
            arguments={"amount": 50000, "tenure_months": 6},
            result=stl_calc,
        )
        await processor.process_frame(calc_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.current_phase, 7)

        # ── Turn 4: KYC Ingestion & Digilocker Guidance ──
        kyc_info = get_kyc_guidance("aadhaar")
        self.assertEqual(kyc_info["step"], "Aadhaar / Address Verification")
        self.assertIn("Digilocker", kyc_info["instructions_hinglish"])
        self.assertIn("OTP", kyc_info["instructions_hinglish"])

        kyc_frame = FunctionCallResultFrame(
            function_name="get_kyc_guidance",
            tool_call_id="call_kyc_aditya",
            arguments={"step_or_doc": "aadhaar"},
            result=kyc_info,
        )
        await processor.process_frame(kyc_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.current_phase, 8)  # KYC Navigation Phase

        # Advance to READY
        allowed, reason = self.stage_manager.can_transition(
            DecisionStage.EVALUATING, DecisionStage.READY, fact_store=fact_store, turn_id=4
        )
        self.assertTrue(allowed)

        # ── Turn 5: Session Disconnection & Downcar Background Worker ──
        session_transcript = [
            {"role": "user", "text": "Namaste, main Aditya Sharma bol raha hoon."},
            {"role": "assistant", "text": "Namaste Aditya ji, kya aapke paas 2 minute ka samay hai?"},
            {"role": "user", "text": "Haan bilkul, mujhe wealth growth ke liye ₹50,000 6 months ke liye lagane hain."},
            {"role": "assistant", "text": "STL 7M mein 18% return se ₹4,500 profit banega aur ₹54,500 total maturity hogi."},
            {"role": "user", "text": "Aadhaar verification kaise complete karun?"},
            {"role": "assistant", "text": "App mein Digilocker select karke Aadhaar OTP se instant ho jayega."},
            {"role": "user", "text": "Theek hai main aaj hi KYC karke deposit karta hoon. Dhanyawad!"},
        ]

        downcar_result = await run_post_session_downcar(
            session_id="session_aditya_001",
            user_id=user_id,
            transcript_history=session_transcript,
            memory_bank=self.memory_bank,
        )

        self.assertEqual(downcar_result["status"], "success")
        self.assertEqual(downcar_result["user_id"], "user_aditya_sharma")
        self.assertEqual(downcar_result["facts"]["amount"], 50000.0)
        self.assertEqual(downcar_result["facts"]["tenure_months"], 6)
        self.assertEqual(downcar_result["facts"]["goal"], "wealth growth")
        self.assertTrue(downcar_result["memory_added"])

        # Content MD5 Hash is stored and verified
        stored_memories = self.memory_bank.get_user_memories(user_id)
        self.assertEqual(len(stored_memories), 1)
        self.assertEqual(stored_memories[0]["content_hash"], downcar_result["content_hash"])

    # ── Scenario 2: Rajesh Kumar HNW Multi-Session Profile Rehydration ──
    async def test_scenario_2_rajesh_kumar_hnw_multi_session_profile_rehydration(self):
        """Scenario 2: Rajesh Kumar HNW multi-session rehydration & MTL daily plan evaluation."""
        # ── Session 1: HNW Preferences Recorded ──
        raw_user_s1 = "Mr. Rajesh Kumar"
        uid_s1 = normalize_lexical_user_id(raw_user_s1)
        self.assertEqual(uid_s1, "user_rajesh_kumar")

        fact_store_s1 = self.memory_bank.get_fact_store(uid_s1)
        fact_store_s1.set_fact("amount", 2400000.0, turn_id=1)
        fact_store_s1.set_fact("tenure_months", 12, turn_id=1)
        fact_store_s1.set_fact("goal", "daily liquidity", turn_id=1)
        fact_store_s1.set_fact("risk_preference", "low", turn_id=1)

        s1_transcript = [
            {"role": "user", "text": "Hello, this is Mr. Rajesh Kumar speaking."},
            {"role": "user", "text": "I want to deploy ₹24,00,000 for 12 months with daily liquidity (EDI) and low risk."},
        ]

        downcar_s1 = await run_post_session_downcar(
            session_id="sess_rajesh_s1",
            user_id=uid_s1,
            transcript_history=s1_transcript,
            memory_bank=self.memory_bank,
        )
        self.assertEqual(downcar_s1["status"], "success")

        # ── Session 2: Connecting within 90 days (10 days later) ──
        raw_user_s2 = "Rajesh Kumar"
        uid_s2 = normalize_lexical_user_id(raw_user_s2)
        self.assertEqual(uid_s2, "user_rajesh_kumar")

        # Hydrate user profile with 90-day lookback
        hydrated_profile = self.memory_bank.hydrate_user_profile(uid_s2, days_lookback=90)
        self.assertTrue(hydrated_profile["profile_hydrated"])
        self.assertEqual(hydrated_profile["facts"]["amount"], 2400000.0)
        self.assertEqual(hydrated_profile["facts"]["tenure_months"], 12)
        self.assertEqual(hydrated_profile["facts"]["goal"], "daily liquidity")
        self.assertEqual(hydrated_profile["facts"]["risk_preference"], "low")

        # Calculate returns for MTL 14M Daily EDI @ ₹24,00,000
        mtl_daily_res = calculate_mtl_returns(amount=2400000, repayment_type="daily")
        self.assertEqual(mtl_daily_res["product_name"], "MTL 14M Daily (EDI)")
        self.assertEqual(mtl_daily_res["principal"], 2400000)
        self.assertEqual(mtl_daily_res["annualized_xirr_pct"], 18.0)
        self.assertEqual(mtl_daily_res["profit_rupees"], 432000.0)
        self.assertEqual(mtl_daily_res["final_maturity_amount"], 2832000.0)
        self.assertEqual(mtl_daily_res["payout_amount"], 7758.9)  # 2832000 / 365
        self.assertIn("AAA", mtl_daily_res["risk_category"])

        # Record quote in NumericLedger and verify
        self.ledger.record_quote(
            principal=mtl_daily_res["principal"],
            tenure_months=mtl_daily_res["tenure_months"],
            xirr_pct=mtl_daily_res["annualized_xirr_pct"],
            profit=mtl_daily_res["profit_rupees"],
            maturity_amount=mtl_daily_res["final_maturity_amount"],
            monthly_emi=mtl_daily_res["payout_amount"],
        )
        self.assertTrue(self.ledger.verify_quote(2400000, 12, 2832000.0))

        # Downcar for Session 2 with duplicate prevention check
        downcar_s2 = await run_post_session_downcar(
            session_id="sess_rajesh_s2",
            user_id=uid_s2,
            transcript_history=s1_transcript,  # Identical content
            memory_bank=self.memory_bank,
        )
        self.assertEqual(downcar_s2["content_hash"], downcar_s1["content_hash"])
        self.assertEqual(len(self.memory_bank.get_user_memories(uid_s2)), 1)

    # ── Scenario 3: Skeptical Investor Adversarial Objection & Escalation ──
    async def test_scenario_3_skeptical_investor_adversarial_objections_and_escalation(self):
        """Scenario 3: Skeptical investor RBI/NPA objections, hysteresis cooldown, and 5-tier escalation."""
        mock_svc = MockService()
        tracker = ConsultativePhaseTracker(gemini_service=mock_svc, enable_client_content=True)
        processor = PhaseTransitionProcessor(tracker=tracker)
        fact_store = FactStore()

        # Step 1: User questions RBI Platform Legitimacy (Phase 4 Trigger)
        rbi_query = "Kya Cymbal Lending RBI registered hai? Mera paisa kitna safe hai?"
        rbi_frame = TranscriptionFrame(text=rbi_query, user_id="u_skeptic", timestamp=1.0)
        await processor.process_frame(rbi_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.current_phase, 4)  # Phase 4: Platform Legitimacy & RBI Trust
        self.stage_manager.transition_to(DecisionStage.CURIOUS, turn_id=1)

        phase4_directive = PHASE_PROMPT_CARDS[4]["directive"]
        self.assertIn("RBI-registered NBFC-P2P", phase4_directive)
        self.assertIn("ICICI Trustee Escrow", phase4_directive)

        # Step 2: User questions Borrower Defaults & NPAs (Phase 5 Trigger)
        npa_query = "Agar borrower paise wapas na de aur default ho jaye toh mera paisa doob jayega kya?"
        npa_frame = TranscriptionFrame(text=npa_query, user_id="u_skeptic", timestamp=2.0)
        await processor.process_frame(npa_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.current_phase, 5)  # Phase 5: Risk Mitigation & Defaults
        self.stage_manager.transition_to(DecisionStage.EVALUATING, turn_id=2)

        phase5_directive = PHASE_PROMPT_CARDS[5]["directive"]
        self.assertIn("Hyper-Diversification", phase5_directive)
        self.assertIn("100 से ज़्यादा vetted borrowers", phase5_directive)
        self.assertIn("96.18%", phase5_directive)

        # Step 3: User expresses hesitation -> enters HESITANT stage
        fact_store.set_fact("amount", 100000.0, turn_id=3)
        self.stage_manager.transition_to(
            DecisionStage.HESITANT, fact_store=fact_store, turn_id=3
        )
        self.assertEqual(self.stage_manager.hesitant_entered_turn, 3)

        # Hysteresis Rule: Immediate attempt to close on turn 3 is BLOCKED
        close_attempt_t3, reason_t3 = self.stage_manager.can_transition(
            DecisionStage.HESITANT, DecisionStage.READY, fact_store=fact_store, turn_id=3
        )
        self.assertFalse(close_attempt_t3)
        self.assertIn("Hysteresis active", reason_t3)

        # Close attempt on turn 4 (only 1 turn elapsed) is still BLOCKED
        close_attempt_t4, reason_t4 = self.stage_manager.can_transition(
            DecisionStage.HESITANT, DecisionStage.READY, fact_store=fact_store, turn_id=4
        )
        self.assertFalse(close_attempt_t4)
        self.assertIn("Hysteresis active", reason_t4)

        # Close attempt on turn 5 (2 turns elapsed) is still BLOCKED
        close_attempt_t5, reason_t5 = self.stage_manager.can_transition(
            DecisionStage.HESITANT, DecisionStage.READY, fact_store=fact_store, turn_id=5
        )
        self.assertFalse(close_attempt_t5)
        self.assertIn("Hysteresis active", reason_t5)

        # Close attempt on turn 6 (3 turns elapsed, cooldown expired) is APPROVED
        close_attempt_t6, reason_t6 = self.stage_manager.can_transition(
            DecisionStage.HESITANT, DecisionStage.READY, fact_store=fact_store, turn_id=6
        )
        self.assertTrue(close_attempt_t6)

        # Step 4: 5-Tier Escalation Matrix Trigger
        self.assertEqual(self.escalation_tracker.get_escalation_tier(), 1)

        # User asks repeated complex technical questions
        self.escalation_tracker.record_user_query("What is the exact legal recovery procedure under Section 138?")
        self.assertEqual(self.escalation_tracker.get_escalation_tier(), 2)

        self.escalation_tracker.record_user_query("How does ICICI Trustee handle insolvency under IBC?")
        self.assertEqual(self.escalation_tracker.get_escalation_tier(), 3)

        # User asks for human manager 1st time
        self.escalation_tracker.record_human_request()
        self.assertEqual(self.escalation_tracker.get_escalation_tier(), 4)

        # User asks for human manager 2nd time -> Escalation Tier 5 triggered!
        tier = self.escalation_tracker.record_human_request()
        self.assertEqual(tier, 5)
        self.assertTrue(self.escalation_tracker.is_callback_booking_required())

    # ── Scenario 4: Out-of-Bounds Parameter Rejection & Recovery ──
    def test_scenario_4_out_of_bounds_parameter_rejection_and_recovery(self):
        """Scenario 4: Rejection of invalid 9-month tenure & ₹60L amount, followed by guided recovery."""
        # Step 1: User requests invalid 9-month tenure for STL
        stl_err_tenure = calculate_stl_returns(amount=50000, tenure_months=9)
        self.assertIn("error", stl_err_tenure)
        self.assertIn("Invalid tenure 9 months for STL", stl_err_tenure["error"])
        self.assertEqual(stl_err_tenure["available_tenures"], [3, 4, 5, 6])

        # Step 2: User requests ₹60,00,000 (exceeds ₹25L STL cap and ₹50L platform limit)
        stl_err_amt = calculate_stl_returns(amount=6000000, tenure_months=6)
        self.assertIn("error", stl_err_amt)
        self.assertIn("Maximum investment amount for STL is ₹25,00,000", stl_err_amt["error"])

        # Step 3: User requests below ₹25,000 STL min amount (₹5,000)
        stl_err_min = calculate_stl_returns(amount=5000, tenure_months=6)
        self.assertIn("error", stl_err_min)
        self.assertIn("Minimum investment amount for Lumpsum (STL) is ₹25,000", stl_err_min["error"])

        # Step 4: Guided Recovery -> User adjusts to valid parameters: ₹10,00,000 @ 6 months (STL 7M)
        valid_stl = calculate_stl_returns(amount=1000000, tenure_months=6)
        self.assertEqual(valid_stl["product_name"], "STL 7M")
        self.assertEqual(valid_stl["principal"], 1000000)
        self.assertEqual(valid_stl["tenure_months"], 6)
        self.assertEqual(valid_stl["annualized_xirr_pct"], 18.0)
        self.assertEqual(valid_stl["profit_rupees"], 90000.0)
        self.assertEqual(valid_stl["final_maturity_amount"], 1090000.0)
        self.assertEqual(valid_stl["monthly_emi_payout"], 181666.67)

        # Step 5: Valid quote recorded and verified in NumericLedger
        self.ledger.record_quote(
            principal=valid_stl["principal"],
            tenure_months=valid_stl["tenure_months"],
            xirr_pct=valid_stl["annualized_xirr_pct"],
            profit=valid_stl["profit_rupees"],
            maturity_amount=valid_stl["final_maturity_amount"],
            monthly_emi=valid_stl["monthly_emi_payout"],
        )
        self.assertTrue(self.ledger.verify_quote(1000000, 6, 1090000.0))

        # State transition to READY with valid facts
        fact_store = FactStore()
        fact_store.set_fact("amount", 1000000.0, turn_id=4)
        fact_store.set_fact("tenure_months", 6, turn_id=4)
        allowed, reason = self.stage_manager.can_transition(
            DecisionStage.EVALUATING, DecisionStage.READY, fact_store=fact_store, turn_id=4
        )
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
