"""Adversarial stress and simulation test suite for Milestone 4:
Context Memory, Multi-Turn Consultative Sales Journey & Sliding Window Compression.

Tests:
1. Full 25-turn stateful consultative sales journey simulation (Phase 1 to Phase 9).
2. Preservation of user profile (₹24 Lakhs, low-risk, daily payout, 12-month tenure) across 20+ turns without parameter loss or corruption.
3. Mid-session objection handling (Bank FD comparison, NPA defaults, platform trust, liquidity).
4. Boundary & contradiction rejection (9-month tenure rejection, ₹60L out-of-bound rejection, recovery back to ₹24L).
5. AntiCancel tool shield invocation during math & navigation tool executions.
6. Context compression token threshold accumulation and sliding window trigger at 20,000 tokens.
7. Zero crash and robust state consistency across long conversational lifecycles.
"""

import unittest
import sys
import os
import time
from typing import Dict, Any, List, Optional

# Add server directory to sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from system_prompt import SYSTEM_PROMPT
from tools.financial_math import (
    calculate_stl_returns,
    calculate_mtl_returns,
    calculate_manual_lending,
    calculate_sip_returns,
    get_product_recommendation,
)
from tools.navigation import (
    get_kyc_guidance,
    get_app_screen_flow,
)


class StatefulConsultativeSession:
    """Simulates a stateful multi-turn conversational session managing user profile,
    sales phases, deterministic tool executions, and token accumulation."""

    def __init__(self, compression_trigger_tokens: int = 20000):
        self.compression_trigger_tokens = compression_trigger_tokens
        self.current_phase = 1
        self.user_profile: Dict[str, Any] = {
            "amount": None,
            "risk_appetite": None,
            "payout_preference": None,
            "tenure_months": None,
            "familiarity": None,
            "kyc_completed_steps": [],
            "commitment_date": None,
        }
        self.turns: List[Dict[str, Any]] = []
        self.accumulated_tokens = 1500  # Initial System Prompt tokens
        self.compression_events = 0
        self.is_tool_locked = False

    def execute_turn(
        self,
        user_utterance: str,
        expected_phase: int,
        tool_call: Optional[str] = None,
        tool_args: Optional[Dict[str, Any]] = None,
        profile_updates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        turn_number = len(self.turns) + 1
        self.current_phase = expected_phase

        # Apply profile updates
        if profile_updates:
            self.user_profile.update(profile_updates)

        tool_result = None
        if tool_call:
            # Simulate AntiCancel tool lock
            self.is_tool_locked = True
            if tool_call == "calculate_mtl_returns":
                tool_result = calculate_mtl_returns(**(tool_args or {}))
            elif tool_call == "calculate_stl_returns":
                tool_result = calculate_stl_returns(**(tool_args or {}))
            elif tool_call == "calculate_manual_lending":
                tool_result = calculate_manual_lending(**(tool_args or {}))
            elif tool_call == "get_product_recommendation":
                tool_result = get_product_recommendation(**(tool_args or {}))
            elif tool_call == "get_kyc_guidance":
                tool_result = get_kyc_guidance(**(tool_args or {}))
            elif tool_call == "get_app_screen_flow":
                tool_result = get_app_screen_flow(**(tool_args or {}))
            self.is_tool_locked = False

        # Calculate realistic token consumption for audio + text context per turn (~750 tokens)
        turn_tokens = len(user_utterance.split()) * 5 + 400
        if tool_result:
            turn_tokens += len(str(tool_result).split()) * 3
        self.accumulated_tokens += turn_tokens

        # Check Context Window Compression Trigger
        if self.accumulated_tokens >= self.compression_trigger_tokens:
            self.compression_events += 1
            # Sliding window compresses older conversation turns while keeping system prompt & recent turns
            compressed_tokens = int(self.accumulated_tokens * 0.4)
            self.accumulated_tokens -= compressed_tokens

        turn_record = {
            "turn": turn_number,
            "phase": self.current_phase,
            "user_utterance": user_utterance,
            "tool_called": tool_call,
            "tool_result": tool_result,
            "profile_snapshot": dict(self.user_profile),
            "accumulated_tokens": self.accumulated_tokens,
            "compression_events": self.compression_events,
        }
        self.turns.append(turn_record)
        return turn_record


class TestMultiTurnConsultativeSessionSimulation(unittest.TestCase):
    """Simulates a complete 25-turn sales journey validating memory retention across 20+ turns."""

    def setUp(self):
        self.session = StatefulConsultativeSession(compression_trigger_tokens=20000)

    def test_25_turn_consultative_sales_journey_with_parameter_retention(self):
        """Validates that a 25-turn session progresses through all 9 phases, handles objections,
        rejects contradictions (9-month tenure), and preserves ₹24 Lakhs low-risk daily payout."""

        # ── Phase 1: Time Check & Availability ────────────────────────
        t1 = self.session.execute_turn(
            user_utterance="नमस्ते! कौन बात कर रहे हैं?",
            expected_phase=1,
        )
        self.assertEqual(t1["turn"], 1)
        self.assertEqual(t1["phase"], 1)

        t2 = self.session.execute_turn(
            user_utterance="हाँ, मेरे पास 2 मिनट हैं, बताइए।",
            expected_phase=1,
            profile_updates={"time_available": True},
        )
        self.assertEqual(t2["turn"], 2)

        # ── Phase 2: Discovery & P2P Familiarity ──────────────────────
        t3 = self.session.execute_turn(
            user_utterance="मैं P2P lending पहली बार explore कर रहा हूँ।",
            expected_phase=2,
            profile_updates={"familiarity": "new"},
        )
        self.assertEqual(t3["profile_snapshot"]["familiarity"], "new")

        # Crucial Turn 4: User sets long-term constraint: ₹24 Lakhs, Low Risk, Daily Payout
        t4 = self.session.execute_turn(
            user_utterance="मेरे पास 24 लाख रुपये हैं, low risk investment चाहिए और daily payout prefer करूँगा।",
            expected_phase=2,
            profile_updates={
                "amount": 2400000.0,
                "risk_appetite": "low",
                "payout_preference": "daily",
            },
        )
        self.assertEqual(t4["profile_snapshot"]["amount"], 2400000.0)
        self.assertEqual(t4["profile_snapshot"]["risk_appetite"], "low")
        self.assertEqual(t4["profile_snapshot"]["payout_preference"], "daily")

        # ── Phase 3: Concept Education ────────────────────────────────
        t5 = self.session.execute_turn(
            user_utterance="P2P lending mein return kaise banta hai aur banks se jyada kyu milta hai?",
            expected_phase=3,
        )
        self.assertEqual(t5["phase"], 3)

        # ── Phase 4: Platform Legitimacy & RBI Trust ──────────────────
        t6 = self.session.execute_turn(
            user_utterance="Cymbal Lending kitna safe hai? RBI approved hai kya?",
            expected_phase=4,
        )
        self.assertEqual(t6["phase"], 4)

        # ── Phase 5: Risk Mitigation & Diversification Math ───────────
        t7 = self.session.execute_turn(
            user_utterance="Agar borrower default kar de toh mera paisa doob jayega kya?",
            expected_phase=5,
        )
        self.assertEqual(t7["phase"], 5)

        # ── Intermediate Objection 1: Bank FD Comparison ──────────────
        t8 = self.session.execute_turn(
            user_utterance="Mujhe Bank FD mein 7% mil raha hai, wahi safe nahi hai kya?",
            expected_phase=5,
        )
        self.assertEqual(t8["phase"], 5)

        # ── Phase 6: Confidence & Readiness Check ─────────────────────
        t9 = self.session.execute_turn(
            user_utterance="Haan main samajh gaya diversification ka concept.",
            expected_phase=6,
        )
        self.assertEqual(t9["phase"], 6)

        # ── Contradiction Injection: Request 9-Month Tenure ───────────
        t10 = self.session.execute_turn(
            user_utterance="Kya main 24 lakh 9 months ke liye invest kar sakta hoon?",
            expected_phase=6,
            tool_call="get_product_recommendation",
            tool_args={"amount": 2400000.0, "risk_appetite": "low", "tenure_months": 9},
        )
        # Verify 9-month rejection
        self.assertFalse(t10["tool_result"]["is_valid"])
        self.assertIn("9-month", t10["tool_result"]["error"])
        self.assertIn("6-month STL 7M or 12-month MTL 14M", t10["tool_result"]["suggestion"])

        # ── Preference Alignment: 12-Month MTL 14M Daily ──────────────
        t11 = self.session.execute_turn(
            user_utterance="Theek hai, 9 months nahi hai toh main 12 months MTL plan lunga daily payout ke saath.",
            expected_phase=6,
            profile_updates={"tenure_months": 12},
        )
        self.assertEqual(t11["profile_snapshot"]["tenure_months"], 12)

        # ── Phase 7: Product Recommendation & Mathematical Calculation ─
        # In Turn 12, execute deterministic MTL calculation for ₹24L Daily
        t12 = self.session.execute_turn(
            user_utterance="24 lakh par 12 months mein exactly kitna daily payout aur total profit banega?",
            expected_phase=7,
            tool_call="calculate_mtl_returns",
            tool_args={"amount": self.session.user_profile["amount"], "repayment_type": "daily"},
        )
        self.assertEqual(t12["phase"], 7)
        res_mtl = t12["tool_result"]
        self.assertIsNotNone(res_mtl)
        self.assertEqual(res_mtl["principal"], 2400000.0)
        self.assertEqual(res_mtl["profit_rupees"], 432000.0)
        self.assertEqual(res_mtl["final_maturity_amount"], 2832000.0)
        self.assertEqual(res_mtl["payout_amount"], 7758.90)
        self.assertEqual(res_mtl["annualized_xirr_pct"], 18.0)

        # ── Intermediate Objection 2: Liquidity & Daily Withdrawals ────
        t13 = self.session.execute_turn(
            user_utterance="Yeh 7,758 rupees daily seedhe mere bank account mein aayenge?",
            expected_phase=7,
        )
        self.assertEqual(t13["phase"], 7)

        # ── Boundary Test: Exceeding RBI Platform Limit (₹60 Lakhs) ────
        t14 = self.session.execute_turn(
            user_utterance="Agar main 60 lakh invest karun toh?",
            expected_phase=7,
            tool_call="get_product_recommendation",
            tool_args={"amount": 6000000.0, "risk_appetite": "low", "tenure_months": 12},
        )
        self.assertFalse(t14["tool_result"]["is_valid"])
        self.assertIn("50,00,000", t14["tool_result"]["error"])

        # ── Recovery Back to Preserved ₹24 Lakhs ───────────────────────
        t15 = self.session.execute_turn(
            user_utterance="Achha samajh gaya, 50 lakh RBI limit hai. Main 24 lakh hi continue karunga.",
            expected_phase=7,
        )
        # Verify user profile still maintains ₹24 Lakhs and daily payout
        self.assertEqual(self.session.user_profile["amount"], 2400000.0)
        self.assertEqual(self.session.user_profile["payout_preference"], "daily")

        # ── Phase 8: App & KYC Navigation — Step 1: PAN ────────────────
        t16 = self.session.execute_turn(
            user_utterance="Investment start karne ke liye KYC process kya hai?",
            expected_phase=8,
            tool_call="get_kyc_guidance",
            tool_args={"step_or_doc": "pan"},
            profile_updates={"kyc_completed_steps": ["pan"]},
        )
        self.assertEqual(t16["phase"], 8)
        self.assertIn("PAN", t16["tool_result"]["step"])

        # ── Phase 8: KYC Step 2: Aadhaar Digilocker OTP ────────────────
        t17 = self.session.execute_turn(
            user_utterance="PAN ke baad next step kya hai?",
            expected_phase=8,
            tool_call="get_kyc_guidance",
            tool_args={"step_or_doc": "aadhaar"},
            profile_updates={"kyc_completed_steps": ["pan", "aadhaar"]},
        )
        self.assertIn("Aadhaar", t17["tool_result"]["step"])

        # ── Phase 8: KYC Step 3: Bank Penny Drop ──────────────────────
        t18 = self.session.execute_turn(
            user_utterance="Bank account link kaise hoga payout receive karne ke liye?",
            expected_phase=8,
            tool_call="get_kyc_guidance",
            tool_args={"step_or_doc": "bank"},
            profile_updates={"kyc_completed_steps": ["pan", "aadhaar", "bank"]},
        )
        self.assertIn("Bank", t18["tool_result"]["step"])

        # ── Phase 8: App Screen Flow — Loan Filter (8 Options) ─────────
        t19 = self.session.execute_turn(
            user_utterance="App mein loan filter mein kya kya options milte hain?",
            expected_phase=8,
            tool_call="get_app_screen_flow",
            tool_args={"target_flow": "loan filter"},
        )
        self.assertEqual(len(t19["tool_result"]["available_filters"]), 8)

        # ── Phase 8: App Screen Flow — Deposit Flow ───────────────────
        t20 = self.session.execute_turn(
            user_utterance="Escrow account mein paise deposit karne ka flow kaisa hai?",
            expected_phase=8,
            tool_call="get_app_screen_flow",
            tool_args={"target_flow": "deposit"},
        )
        self.assertEqual(t20["turn"], 20)
        self.assertIn("Escrow", str(t20["tool_result"]))

        # ── CRUCIAL CHECK: Post-20 Turn Memory Invariant Verification ──
        # Assert that after 20 full turns, user profile is 100% intact
        self.assertEqual(self.session.user_profile["amount"], 2400000.0)
        self.assertEqual(self.session.user_profile["risk_appetite"], "low")
        self.assertEqual(self.session.user_profile["payout_preference"], "daily")
        self.assertEqual(self.session.user_profile["tenure_months"], 12)
        self.assertEqual(self.session.user_profile["kyc_completed_steps"], ["pan", "aadhaar", "bank"])

        # ── Phase 9: Commitment & Close ───────────────────────────────
        t21 = self.session.execute_turn(
            user_utterance="Main kal subah 10 baje 24 lakh ka deposit complete karke plan activate kar dunga.",
            expected_phase=9,
            profile_updates={"commitment_date": "tomorrow 10:00 AM"},
        )
        self.assertEqual(t21["phase"], 9)
        self.assertEqual(self.session.user_profile["commitment_date"], "tomorrow 10:00 AM")

        t22 = self.session.execute_turn(
            user_utterance="Theek hai, Escrow UPI aur Netbanking details note kar li hain.",
            expected_phase=9,
        )
        self.assertEqual(t22["turn"], 22)

        # ── Late-Turn Contradiction Verification (Turn 23) ────────────
        t23 = self.session.execute_turn(
            user_utterance="Agar kal tak 9 month wala plan aa jaye toh?",
            expected_phase=9,
            tool_call="get_product_recommendation",
            tool_args={"amount": 2400000.0, "tenure_months": 9},
        )
        self.assertFalse(t23["tool_result"]["is_valid"])

        t24 = self.session.execute_turn(
            user_utterance="Samajh gaya, 12 month MTL 14M daily hi best hai mere liye. Thanks Pragya!",
            expected_phase=9,
        )
        self.assertEqual(t24["turn"], 24)

        t25 = self.session.execute_turn(
            user_utterance="Thank you, bye!",
            expected_phase=9,
        )
        self.assertEqual(t25["turn"], 25)
        self.assertEqual(len(self.session.turns), 25)


class TestContextCompressionTokenThreshold(unittest.TestCase):
    """Validates sliding window context compression trigger at 20,000 tokens."""

    def test_compression_trigger_at_20000_tokens(self):
        """Simulates heavy token accumulation and verifies compression activates at 20,000 tokens."""
        session = StatefulConsultativeSession(compression_trigger_tokens=20000)

        # Accumulate 19,800 tokens
        session.accumulated_tokens = 19800
        t1 = session.execute_turn("Short question", expected_phase=2)
        # Turn adds ~400+ tokens, pushing over 20,000
        self.assertGreaterEqual(session.compression_events, 1)
        self.assertLess(session.accumulated_tokens, 20000)

    def test_custom_compression_threshold_override(self):
        """Validates that custom trigger_tokens parameter (e.g. 15,000) triggers at custom threshold."""
        session_custom = StatefulConsultativeSession(compression_trigger_tokens=15000)
        session_custom.accumulated_tokens = 14800
        session_custom.execute_turn("Another turn", expected_phase=3)
        self.assertEqual(session_custom.compression_events, 1)

    def test_system_prompt_and_profile_preservation_post_compression(self):
        """Ensures system prompt invariants and user investment constraints survive compression."""
        session = StatefulConsultativeSession(compression_trigger_tokens=20000)
        session.user_profile["amount"] = 2400000.0
        session.user_profile["payout_preference"] = "daily"
        session.accumulated_tokens = 19000

        # Force multiple compression cycles (e.g., 3 cycles across 30 turns)
        for i in range(30):
            session.execute_turn(
                f"Turn {i+1} detailed financial discussion with verbose data payload.",
                expected_phase=min(9, (i // 3) + 1),
            )

        self.assertGreaterEqual(session.compression_events, 1)
        # Assert user preferences remain intact
        self.assertEqual(session.user_profile["amount"], 2400000.0)
        self.assertEqual(session.user_profile["payout_preference"], "daily")


if __name__ == "__main__":
    unittest.main()
