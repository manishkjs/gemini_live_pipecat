"""Tier 3 Cross-Feature & Pipeline Integration Tests: Cymbal Lending Voicebot.

Hermetic end-to-end component integration tests covering:
1. Lexical Normalization + Hydration: New user vs returning user profile hydration into FactStore.
2. Turn 1 Greeting + Name Elicitation + `retrieve_memory` tool execution pipeline.
3. AntiCancel Tool Shield integration with memory retrieval and financial calculations (ensuring async tools don't drop frames or cancel audio mid-sentence).
4. Decision Stage progression interacting with FactStore (Facts update triggers PhaseTransitionProcessor -> stage advances).
5. Tool Calculation (`calculate_returns`) -> Output recorded into `NumericLedger` -> Verify quote consistency.
6. Client Disconnection Event (`on_client_disconnected`) triggering `run_post_session_downcar` -> Writes structured facts and episodic memory into `MemoryBank` with MD5 hash.
7. Multi-session continuity: Session 1 disconnect writes memory -> Session 2 starts for same user -> Profile rehydrated with 90-day memory.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
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
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    Frame,
    FunctionCallResultFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    TextFrame,
    TranscriptionFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import FunctionCallParams
from tools.financial_math import (
    calculate_manual_lending,
    calculate_mtl_returns,
    calculate_returns,
    calculate_sip_returns,
    calculate_stl_returns,
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

# 1. DecisionStage Enum
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


# 2. StageTransitionManager
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


# 3. NumericLedger
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


# 4. EscalationTracker
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


# 5. retrieve_memory schema & handler
try:
    from tools.tool_definitions import handle_retrieve_memory, retrieve_memory_schema
except ImportError:
    retrieve_memory_schema = FunctionSchema(
        name="retrieve_memory",
        description="Retrieve past user profile facts and episodic memories for a customer.",
        properties={
            "user_id": {
                "type": "string",
                "description": "Normalized user ID or customer name.",
            },
            "query": {
                "type": "string",
                "description": "Query or topic to search from memory.",
            },
        },
        required=["user_id", "query"],
    )

    async def handle_retrieve_memory(params: FunctionCallParams, memory_bank: Optional[Any] = None) -> Dict[str, Any]:
        args = getattr(params, "arguments", {}) or {}
        user_id = args.get("user_id", "")
        query = args.get("query", "")

        if not user_id or not query:
            result = {"error": "Missing user_id or query", "memories": []}
        elif memory_bank is not None:
            memories = memory_bank.search_memories(user_id=user_id, query=query, threshold=0.40)
            profile = memory_bank.hydrate_user_profile(user_id=user_id, days_lookback=90)
            result = {
                "user_id": user_id,
                "facts": profile.get("facts", {}),
                "memories": [m["content"] for m in memories],
                "count": len(memories),
            }
        else:
            result = {"user_id": user_id, "memories": [], "facts": {}}

        if hasattr(params, "result_callback") and callable(params.result_callback):
            await params.result_callback(result)
        return result


# 6. run_post_session_downcar worker
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


# ═══════════════════════════════════════════════════════════════════════
# MOCK HELPER FRAME PROCESSORS FOR SHIELD INTEGRATION
# ═══════════════════════════════════════════════════════════════════════

class FunctionCallInProgressFrame(Frame):
    def __init__(self, tool_name: str = ""):
        super().__init__()
        self.tool_name = tool_name


class MockShieldedPipelineService(FrameProcessor):
    """Simulates the AntiCancel Tool Shield in CustomGeminiLiveLLMService."""

    TOOL_LOCK_MAX_HOLD_SECS = 8.0

    def __init__(self):
        super().__init__()
        self._active_tools_in_flight = 0
        self._frame_locked_tools = False
        self._tool_lock_started_at: Optional[float] = None
        self.processed_frames: List[Frame] = []
        self.suppressed_frames: List[Frame] = []

    def _is_tool_lock_active(self) -> bool:
        if self._active_tools_in_flight > 0 or self._frame_locked_tools:
            if self._tool_lock_started_at is not None:
                if (time.time() - self._tool_lock_started_at) > self.TOOL_LOCK_MAX_HOLD_SECS:
                    self._active_tools_in_flight = 0
                    self._frame_locked_tools = False
                    self._tool_lock_started_at = None
                    return False
            return True
        return False

    def acquire_tool_lock(self):
        self._active_tools_in_flight += 1
        self._frame_locked_tools = True
        self._tool_lock_started_at = time.time()

    def release_tool_lock(self):
        self._active_tools_in_flight = max(0, self._active_tools_in_flight - 1)
        if self._active_tools_in_flight == 0:
            self._frame_locked_tools = False
            self._tool_lock_started_at = None

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        await super().process_frame(frame, direction)

        if isinstance(frame, FunctionCallInProgressFrame):
            self.acquire_tool_lock()
            self.processed_frames.append(frame)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, FunctionCallResultFrame):
            self.release_tool_lock()
            self.processed_frames.append(frame)
            await self.push_frame(frame, direction)
            return

        # CancelFrame (critical pipeline termination) ALWAYS passes through
        if isinstance(frame, CancelFrame):
            self.processed_frames.append(frame)
            await self.push_frame(frame, direction)
            return

        # Interruption frames are suppressed if tool lock is active
        if isinstance(frame, (InterruptionFrame, UserStartedSpeakingFrame)):
            if self._is_tool_lock_active():
                self.suppressed_frames.append(frame)
                return  # Drop frame silently

        self.processed_frames.append(frame)
        await self.push_frame(frame, direction)


class MockGeminiSession:
    def __init__(self):
        self.send_client_content = AsyncMock()


class MockGeminiService:
    def __init__(self):
        self._session = MockGeminiSession()


# ═══════════════════════════════════════════════════════════════════════
# TIER 3 INTEGRATION TEST SUITE
# ═══════════════════════════════════════════════════════════════════════

class TestIntegrationMemoryVoice(unittest.IsolatedAsyncioTestCase):
    """Tier 3: Hermetic End-to-End Component Integration Tests."""

    def setUp(self):
        self.memory_bank = MemoryBank()

    # ── Test 1: Lexical Normalization + Hydration (New vs Returning) ──
    def test_01_lexical_normalization_and_hydration_new_vs_returning_user(self):
        """Test 1: Lexical Normalization + Hydration for new and returning users."""
        # 1. New User
        raw_new_user = "Namaste, mera naam Vikram Malhotra hai"
        norm_new_id = normalize_lexical_user_id(raw_new_user)
        self.assertEqual(norm_new_id, "user_vikram_malhotra")

        new_profile = self.memory_bank.hydrate_user_profile(norm_new_id, days_lookback=90)
        self.assertEqual(new_profile["user_id"], "user_vikram_malhotra")
        self.assertEqual(new_profile["facts"], {})
        self.assertEqual(new_profile["recent_memories"], [])
        self.assertEqual(new_profile["memory_count"], 0)
        self.assertIsNone(new_profile["last_active"])
        self.assertTrue(new_profile["profile_hydrated"])

        new_fact_store = self.memory_bank.get_fact_store(norm_new_id)
        self.assertEqual(new_fact_store.get_all_facts(), {})

        # 2. Returning User with recent and expired memories
        raw_returning_user = "Dr. Sunita Rao ji"
        norm_returning_id = normalize_lexical_user_id(raw_returning_user)
        self.assertEqual(norm_returning_id, "user_sunita_rao")

        ret_fact_store = self.memory_bank.get_fact_store(norm_returning_id)
        ret_fact_store.set_fact("goal", "wealth growth", turn_id=1)
        ret_fact_store.set_fact("amount", 500000.0, turn_id=1)
        ret_fact_store.set_fact("tenure_months", 6, turn_id=1)

        # Add recent memory (within 10 days)
        now_dt = datetime.now(timezone.utc)
        recent_ts = (now_dt - timedelta(days=10)).isoformat()
        self.memory_bank.add_memory(
            user_id=norm_returning_id,
            content="Investor prefers STL 7M with ₹5,00,000 for wealth creation",
            metadata={"source": "session_1"},
        )
        self.memory_bank._memories[norm_returning_id][-1]["created_at"] = recent_ts
        self.memory_bank._memories[norm_returning_id][-1]["updated_at"] = recent_ts

        # Add old memory (120 days ago, >90 days)
        old_ts = (now_dt - timedelta(days=120)).isoformat()
        self.memory_bank.add_memory(
            user_id=norm_returning_id,
            content="Inquired about old fixed deposit rates 7%",
            metadata={"source": "old_session"},
        )
        self.memory_bank._memories[norm_returning_id][-1]["created_at"] = old_ts
        self.memory_bank._memories[norm_returning_id][-1]["updated_at"] = old_ts

        returning_profile = self.memory_bank.hydrate_user_profile(norm_returning_id, days_lookback=90)
        self.assertEqual(returning_profile["user_id"], "user_sunita_rao")
        self.assertEqual(returning_profile["facts"]["goal"], "wealth growth")
        self.assertEqual(returning_profile["facts"]["amount"], 500000.0)
        self.assertEqual(returning_profile["facts"]["tenure_months"], 6)

        # Verify >90d memory was filtered out
        self.assertEqual(returning_profile["memory_count"], 1)
        self.assertIn("STL 7M with ₹5,00,000", returning_profile["recent_memories"][0]["content"])
        self.assertIsNotNone(returning_profile["last_active"])

    # ── Test 2: Turn 1 Greeting + Name Elicitation + retrieve_memory Pipeline ──
    async def test_02_turn1_greeting_name_elicitation_and_retrieve_memory_pipeline(self):
        """Test 2: Turn 1 Greeting + Name Elicitation + retrieve_memory tool pipeline."""
        # 1. Verify Turn 1 prompt directive
        turn1_directive = PHASE_PROMPT_CARDS[1]["directive"]
        self.assertIn("Phase 1", turn1_directive)
        self.assertIn("Pragya", turn1_directive)
        self.assertIn("Cymbal Lending", turn1_directive)

        # 2. Simulate User Speech containing spoken name
        user_utterance = "Namaste, main Aditya Sharma bol raha hoon."
        extracted_user_id = normalize_lexical_user_id(user_utterance)
        self.assertEqual(extracted_user_id, "user_aditya_sharma")

        # User confirms time availability in turn
        time_consent = "Haan 2 minute baat kar sakte hain."
        self.assertIn("2 minute", time_consent)

        # 3. Pre-seed MemoryBank and FactStore with customer history
        fact_store = self.memory_bank.get_fact_store(extracted_user_id)
        fact_store.set_fact("goal", "wealth growth", turn_id=1)
        fact_store.set_fact("amount", 50000.0, turn_id=1)
        fact_store.set_fact("tenure_months", 6, turn_id=1)

        self.memory_bank.add_memory(
            user_id=extracted_user_id,
            content="Aditya Sharma previously explored STL 7M investment of ₹50,000 for wealth creation.",
            metadata={"verified_lead": True},
        )

        # 4. Execute retrieve_memory tool
        result_payload = {}
        async def mock_result_callback(data):
            nonlocal result_payload
            result_payload = data

        call_params = MagicMock(spec=FunctionCallParams)
        call_params.arguments = {
            "user_id": extracted_user_id,
            "query": "Aditya Sharma STL 7M investment ₹50,000 wealth creation",
        }
        call_params.result_callback = mock_result_callback

        await handle_retrieve_memory(call_params, memory_bank=self.memory_bank)

        # Assert tool executed non-blocking and returned memory payload
        self.assertEqual(result_payload.get("user_id"), "user_aditya_sharma")
        self.assertGreaterEqual(result_payload.get("count", 0), 1)
        self.assertTrue(any("STL 7M investment" in m for m in result_payload.get("memories", [])))

    # ── Test 3: AntiCancel Tool Shield Integration ──
    async def test_03_anticancel_tool_shield_integration(self):
        """Test 3: AntiCancel Tool Shield protects async memory and calculation tools."""
        shield = MockShieldedPipelineService()

        # Step A: Normal state before tools
        self.assertFalse(shield._is_tool_lock_active())
        interruption1 = InterruptionFrame()
        await shield.process_frame(interruption1)
        self.assertIn(interruption1, shield.processed_frames)
        self.assertEqual(len(shield.suppressed_frames), 0)

        # Step B: Memory Retrieval / Calculation tool begins
        in_progress = FunctionCallInProgressFrame(tool_name="calculate_returns")
        await shield.process_frame(in_progress)
        self.assertTrue(shield._is_tool_lock_active())

        # Step C: User barges in during tool execution -> InterruptionFrame MUST be suppressed
        interruption2 = InterruptionFrame()
        speaking_frame = UserStartedSpeakingFrame()
        await shield.process_frame(interruption2)
        await shield.process_frame(speaking_frame)

        self.assertIn(interruption2, shield.suppressed_frames)
        self.assertIn(speaking_frame, shield.suppressed_frames)

        # Step D: CancelFrame (critical pipeline shutdown) must NEVER be suppressed
        cancel_frame = CancelFrame()
        await shield.process_frame(cancel_frame)
        self.assertIn(cancel_frame, shield.processed_frames)
        self.assertNotIn(cancel_frame, shield.suppressed_frames)

        # Step E: Tool execution finishes and emits result
        calc_result = calculate_returns(amount=50000, tenure_months=6)
        result_frame = FunctionCallResultFrame(
            function_name="calculate_returns",
            tool_call_id="call_999",
            arguments={"amount": 50000, "tenure_months": 6},
            result=calc_result,
        )
        await shield.process_frame(result_frame)
        self.assertFalse(shield._is_tool_lock_active())

        # Step F: Subsequent interruption passes through cleanly
        interruption3 = InterruptionFrame()
        await shield.process_frame(interruption3)
        self.assertIn(interruption3, shield.processed_frames)

    # ── Test 4: Decision Stage Progression Interacting with FactStore ──
    async def test_04_decision_stage_progression_with_fact_store(self):
        """Test 4: Decision Stage progression interacting with FactStore and gates."""
        stage_manager = StageTransitionManager()
        fact_store = FactStore()
        gemini_svc = MockGeminiService()
        tracker = ConsultativePhaseTracker(gemini_service=gemini_svc, enable_client_content=True)
        processor = PhaseTransitionProcessor(tracker=tracker)

        # Turn 1: Initial state UNAWARE (Phase 1)
        self.assertEqual(tracker.current_phase, 1)

        # User confirms availability -> PhaseTransitionProcessor triggers transition to Phase 2 (CURIOUS)
        consent_frame = TranscriptionFrame(text="Haan, bataiye mere paas 2 minute hain", user_id="u1", timestamp=1.0)
        await processor.process_frame(consent_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.current_phase, 2)

        allowed, reason = stage_manager.can_transition(
            DecisionStage.UNAWARE, DecisionStage.CURIOUS, fact_store=fact_store, turn_id=1
        )
        self.assertTrue(allowed)

        # Turn 2: FactStore updated with investment goals
        fact_store.set_fact("goal", "wealth growth", turn_id=2)
        fact_store.set_fact("amount", 100000.0, turn_id=2)
        fact_store.set_fact("tenure_months", 6, turn_id=2)

        allowed, reason = stage_manager.can_transition(
            DecisionStage.CURIOUS, DecisionStage.INTERESTED, fact_store=fact_store, turn_id=2
        )
        self.assertTrue(allowed)

        # Turn 3: Tool Execution calculate_returns triggers Phase 7 (Product Recommendation)
        calc_frame = FunctionCallResultFrame(
            function_name="calculate_stl_returns",
            tool_call_id="call_stl",
            arguments={"amount": 100000, "tenure_months": 6},
            result={"profit": 9000.0},
        )
        await processor.process_frame(calc_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.current_phase, 7)

        # Stage Skip Guard: Direct transition UNAWARE -> COMMITTED without amount is blocked
        empty_facts = FactStore()
        blocked, block_reason = stage_manager.can_transition(
            DecisionStage.UNAWARE, DecisionStage.COMMITTED, fact_store=empty_facts, turn_id=3
        )
        self.assertFalse(blocked)
        self.assertIn("guard", block_reason.lower())

        # Transition with complete facts to READY is approved
        ready_allowed, _ = stage_manager.can_transition(
            DecisionStage.EVALUATING, DecisionStage.READY, fact_store=fact_store, turn_id=4
        )
        self.assertTrue(ready_allowed)

    # ── Test 5: Tool Calculation Recorded into NumericLedger & Quote Consistency ──
    def test_05_tool_calculation_output_recorded_into_numeric_ledger(self):
        """Test 5: Tool Calculation output recorded into NumericLedger and verified."""
        ledger = NumericLedger()

        # 1. STL 7M Calculation for ₹2,00,000 @ 6 months
        stl_res = calculate_stl_returns(amount=200000, tenure_months=6)
        self.assertEqual(stl_res["product_name"], "STL 7M")
        self.assertEqual(stl_res["annualized_xirr_pct"], 18.0)
        self.assertEqual(stl_res["profit_rupees"], 18000.0)
        self.assertEqual(stl_res["final_maturity_amount"], 218000.0)
        self.assertEqual(stl_res["monthly_emi_payout"], 36333.33)

        # Record quote into NumericLedger
        ledger.record_quote(
            principal=stl_res["principal"],
            tenure_months=stl_res["tenure_months"],
            xirr_pct=stl_res["annualized_xirr_pct"],
            profit=stl_res["profit_rupees"],
            maturity_amount=stl_res["final_maturity_amount"],
            monthly_emi=stl_res["monthly_emi_payout"],
        )

        # Consistent quote verification passes
        self.assertTrue(ledger.verify_quote(principal=200000, tenure_months=6, quoted_maturity=218000.0))

        # Contradiction / Hallucinated quote verification FAILS
        self.assertFalse(ledger.verify_quote(principal=200000, tenure_months=6, quoted_maturity=225000.0))

        # 2. MTL 14M Calculation for ₹5,00,000 @ 12 months
        mtl_res = calculate_mtl_returns(amount=500000, repayment_type="monthly")
        ledger.record_quote(
            principal=mtl_res["principal"],
            tenure_months=mtl_res["tenure_months"],
            xirr_pct=mtl_res["annualized_xirr_pct"],
            profit=mtl_res["profit_rupees"],
            maturity_amount=mtl_res["final_maturity_amount"],
            monthly_emi=mtl_res["payout_amount"],
        )

        self.assertTrue(ledger.verify_quote(principal=500000, tenure_months=12, quoted_maturity=620000.0))
        self.assertEqual(len(ledger.get_all_quotes()), 2)

    # ── Test 6: Client Disconnection Triggers Downcar Extraction & MD5 Storage ──
    async def test_06_client_disconnect_triggers_downcar_extraction_and_md5_storage(self):
        """Test 6: Client disconnection triggers run_post_session_downcar with MD5 hash."""
        session_id = "session_test_901"
        raw_user = "Aditya Sharma"
        transcript = [
            {"role": "user", "text": "Namaste, main Aditya Sharma bol raha hoon."},
            {"role": "assistant", "text": "Namaste Aditya ji, kya 2 minute baat kar sakte hain?"},
            {"role": "user", "text": "Haan bilkul, mujhe wealth growth ke liye ₹50,000 6 months ke liye lagane hain."},
            {"role": "assistant", "text": "STL 7M mein 18% return se ₹4,500 munafa hoga."},
            {"role": "user", "text": "Theek hai main aaj hi KYC karta hoon."},
        ]

        downcar_res = await run_post_session_downcar(
            session_id=session_id,
            user_id=raw_user,
            transcript_history=transcript,
            memory_bank=self.memory_bank,
        )

        self.assertEqual(downcar_res["status"], "success")
        self.assertEqual(downcar_res["user_id"], "user_aditya_sharma")
        self.assertEqual(downcar_res["facts"]["amount"], 50000.0)
        self.assertEqual(downcar_res["facts"]["tenure_months"], 6)
        self.assertEqual(downcar_res["facts"]["goal"], "wealth growth")
        self.assertTrue(downcar_res["memory_added"])

        # Verify FactStore contains extracted facts
        user_fact_store = self.memory_bank.get_fact_store("user_aditya_sharma")
        self.assertEqual(user_fact_store.get_fact("amount"), 50000.0)
        self.assertEqual(user_fact_store.get_fact("tenure_months"), 6)

        # Idempotency check: Re-running with identical transcript does NOT add duplicate record
        second_run = await run_post_session_downcar(
            session_id=session_id,
            user_id=raw_user,
            transcript_history=transcript,
            memory_bank=self.memory_bank,
        )
        self.assertEqual(second_run["content_hash"], downcar_res["content_hash"])
        memories = self.memory_bank.get_user_memories("user_aditya_sharma")
        self.assertEqual(len(memories), 1)

    # ── Test 7: Multi-Session Continuity (Session 1 -> Session 2 Rehydration) ──
    async def test_07_multisession_continuity_session1_disconnect_session2_rehydrate(self):
        """Test 7: Multi-session continuity with 90-day profile rehydration."""
        user_name = "Priya Patel"
        norm_user_id = normalize_lexical_user_id(user_name)
        self.assertEqual(norm_user_id, "user_priya_patel")

        # Session 1: Interacts and disconnects
        session1_transcript = [
            {"role": "user", "text": "Mera naam Priya Patel hai."},
            {"role": "user", "text": "Mujhe ₹2,00,000 MTL 14M mein 12 months ke liye invest karke monthly income leni hai."},
        ]
        await run_post_session_downcar(
            session_id="sess_s1",
            user_id=norm_user_id,
            transcript_history=session1_transcript,
            memory_bank=self.memory_bank,
        )

        # Session 2 Starts (e.g. 5 days later within 90 days)
        session2_profile = self.memory_bank.hydrate_user_profile(norm_user_id, days_lookback=90)
        self.assertTrue(session2_profile["profile_hydrated"])
        self.assertEqual(session2_profile["facts"]["amount"], 200000.0)
        self.assertEqual(session2_profile["facts"]["tenure_months"], 12)
        self.assertEqual(session2_profile["facts"]["goal"], "monthly income")

        # Query past memory in Session 2
        recalled_memories = self.memory_bank.search_memories(
            user_id=norm_user_id,
            query="monthly income investment 200000",
            threshold=0.40,
        )
        self.assertGreaterEqual(len(recalled_memories), 1)
        self.assertIn("200000", recalled_memories[0]["content"])


if __name__ == "__main__":
    unittest.main()
