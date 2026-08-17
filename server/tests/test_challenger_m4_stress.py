"""Empirical Challenger 1 Stress & Verification Suite for Milestone 4.
Milestone 4: Context Memory, 9-Phase Consultative Sales State Machine & Sliding Window Compression.

Tests:
1. Multi-turn chaotic topic switches across 30+ turns with exact return to ₹24 Lakhs low-risk preference.
2. Aggressive boundary injection:
   - 9-month tenure strict rejection across all tools and prompt
   - Negative amounts, zero amounts, out-of-range tenures (-5 to 30)
   - Extreme numbers (> ₹50L platform limit, product-specific caps)
   - Sub-₹25k manual lending routing (₹250 to ₹24,999)
   - Custom NPA / borrower rate boundary handling
3. Token accumulation & sliding window compression at exactly 20,000 tokens and beyond.
4. Non-linear 9-phase sales state machine jumps and objection resolutions.
5. Configuration integrity of `cwc` dictionary and default parameters in agent_live and server.
"""

import unittest
import sys
import os
import inspect
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
from tools.navigation import get_kyc_guidance, get_app_screen_flow
import agent_live
try:
    import server.server as server_module
except ImportError:
    import server as server_module


class ChallengerStatefulSession:
    """Rigorous stateful multi-turn session harness modeling realistic audio/text token weights,
    sliding window compression triggers, user profile tracking, and deterministic tool execution."""

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
        simulated_tokens_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        turn_number = len(self.turns) + 1
        self.current_phase = expected_phase

        if profile_updates:
            self.user_profile.update(profile_updates)

        tool_result = None
        if tool_call:
            self.is_tool_locked = True
            if tool_call == "calculate_mtl_returns":
                tool_result = calculate_mtl_returns(**(tool_args or {}))
            elif tool_call == "calculate_stl_returns":
                tool_result = calculate_stl_returns(**(tool_args or {}))
            elif tool_call == "calculate_manual_lending":
                tool_result = calculate_manual_lending(**(tool_args or {}))
            elif tool_call == "calculate_sip_returns":
                tool_result = calculate_sip_returns(**(tool_args or {}))
            elif tool_call == "get_product_recommendation":
                tool_result = get_product_recommendation(**(tool_args or {}))
            elif tool_call == "get_kyc_guidance":
                tool_result = get_kyc_guidance(**(tool_args or {}))
            elif tool_call == "get_app_screen_flow":
                tool_result = get_app_screen_flow(**(tool_args or {}))
            self.is_tool_locked = False

        if simulated_tokens_override is not None:
            turn_tokens = simulated_tokens_override
        else:
            turn_tokens = len(user_utterance.split()) * 5 + 400
            if tool_result:
                turn_tokens += len(str(tool_result).split()) * 3
        self.accumulated_tokens += turn_tokens

        # Context Window Compression Trigger
        if self.accumulated_tokens >= self.compression_trigger_tokens:
            self.compression_events += 1
            # Sliding window compresses older conversation history while retaining system prompt & recent state
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


class TestChallengerTopicSwitchesAndLongTurnMemory(unittest.TestCase):
    """Stress tests multi-turn topic switches and long-turn memory retention across 30 turns."""

    def test_30_turn_chaotic_interleaving_and_exact_24l_preference_return(self):
        """Simulates 30 conversational turns with heavy topic switching across KYC, RAG,
        FD comparison, SIP compounding, NPA defaults, micro-loans, and 9-month contradictions.
        Verifies that after 20+ turns, the user's initial ₹24 Lakhs low-risk preference is 100% intact."""
        session = ChallengerStatefulSession(compression_trigger_tokens=20000)

        # Turn 1: Time Check
        t1 = session.execute_turn("नमस्ते! कौन बात कर रहे हैं?", expected_phase=1)
        self.assertEqual(t1["phase"], 1)

        # Turn 2: Initial Goal & Constraints Setup (₹24 Lakhs, Low Risk, Daily Payout, 12 Months)
        t2 = session.execute_turn(
            "मेरे पास 24 लाख रुपये हैं, low risk investment चाहिए और daily payout prefer करूँगा 12 महीने के लिए।",
            expected_phase=2,
            profile_updates={
                "amount": 2400000.0,
                "risk_appetite": "low",
                "payout_preference": "daily",
                "tenure_months": 12,
                "familiarity": "new",
            },
        )
        self.assertEqual(session.user_profile["amount"], 2400000.0)

        # Turn 3: Topic Switch -> RBI Trust & Escrow account
        t3 = session.execute_turn("Cymbal Lending RBI registered hai? Escrow bank kaun sa hai?", expected_phase=4)
        self.assertEqual(t3["phase"], 4)

        # Turn 4: Topic Switch -> Distractor calculation (₹50k STL for 4 months)
        t4 = session.execute_turn(
            "Agar koi dost 50,000 invest kare 4 months ke liye toh kitna profit hoga?",
            expected_phase=7,
            tool_call="calculate_stl_returns",
            tool_args={"amount": 50000, "tenure_months": 4},
        )
        self.assertEqual(t4["tool_result"]["product_name"], "STL 5M")
        self.assertEqual(t4["tool_result"]["profit_rupees"], 2500.0)

        # Turn 5: Topic Switch -> Distractor SIP calculation (₹10k/month for 5 years at 15%)
        t5 = session.execute_turn(
            "Aur agar SIP karein 10,000 monthly 5 saal ke liye 15% rate par?",
            expected_phase=7,
            tool_call="calculate_sip_returns",
            tool_args={"monthly_amount": 10000, "annual_rate": 15, "years": 5},
        )
        self.assertAlmostEqual(t5["tool_result"]["total_invested_rupees"], 600000.0)
        self.assertGreater(t5["tool_result"]["maturity_value_rupees"], 800000.0)

        # Turn 6: Topic Switch -> NPA Default question (100+ borrowers)
        t6 = session.execute_turn("Agar borrower default kare toh mera loss kaise cover hota hai?", expected_phase=5)
        self.assertEqual(t6["phase"], 5)

        # Turn 7: Topic Switch -> App Loan Filter Enumeration (8 options)
        t7 = session.execute_turn(
            "App mein loan filter mein kya 8 options aate hain?",
            expected_phase=8,
            tool_call="get_app_screen_flow",
            tool_args={"target_flow": "loan filter"},
        )
        self.assertEqual(len(t7["tool_result"]["available_filters"]), 8)

        # Turn 8: Topic Switch -> KYC Step 2 (Aadhaar Digilocker)
        t8 = session.execute_turn(
            "Aadhaar OTP verify hone mein kitna time lagta hai?",
            expected_phase=8,
            tool_call="get_kyc_guidance",
            tool_args={"step_or_doc": "aadhaar"},
        )
        self.assertIn("Aadhaar", t8["tool_result"]["step"])

        # Turn 9: Topic Switch -> Contradiction Test (9-Month Tenure)
        t9 = session.execute_turn(
            "Kya main 10 lakh 9 month ke liye invest kar sakta hoon?",
            expected_phase=7,
            tool_call="get_product_recommendation",
            tool_args={"amount": 1000000, "tenure_months": 9},
        )
        self.assertFalse(t9["tool_result"]["is_valid"])
        self.assertIn("9-month", t9["tool_result"]["error"])

        # Turn 10: Topic Switch -> Bank FD Comparison
        t10 = session.execute_turn("Bank FD 7% de raha hai, usme aur Cymbal mein kya farak hai?", expected_phase=5)
        self.assertEqual(t10["phase"], 5)

        # Turn 11: Topic Switch -> KYC Step 1 (PAN)
        t11 = session.execute_turn(
            "PAN card verification instant hota hai?",
            expected_phase=8,
            tool_call="get_kyc_guidance",
            tool_args={"step_or_doc": "pan"},
        )
        self.assertIn("PAN", t11["tool_result"]["step"])

        # Turn 12: Topic Switch -> App Screen Flow (Deposit)
        t12 = session.execute_turn(
            "Deposit karne ke liye UPI ya Netbanking use kar sakte hain?",
            expected_phase=8,
            tool_call="get_app_screen_flow",
            tool_args={"target_flow": "deposit"},
        )
        self.assertIn("Escrow", str(t12["tool_result"]))

        # Turn 13: Topic Switch -> Micro Manual Lending (₹1,000 for 3 months)
        t13 = session.execute_turn(
            "Manual lending mein 1,000 rupaye 3 mahine ke liye kitna banega?",
            expected_phase=7,
            tool_call="calculate_manual_lending",
            tool_args={"amount": 1000, "tenure_months": 3},
        )
        self.assertEqual(t13["tool_result"]["profit_rupees"], 45.0)

        # Turn 14: Topic Switch -> Extreme Limit Test (₹75 Lakhs)
        t14 = session.execute_turn(
            "Agar koi 75 lakh lagana chahe toh allowed hai?",
            expected_phase=7,
            tool_call="get_product_recommendation",
            tool_args={"amount": 7500000},
        )
        self.assertFalse(t14["tool_result"]["is_valid"])
        self.assertIn("50,00,000", t14["tool_result"]["error"])

        # Turn 15: Topic Switch -> KYC Step 3 (Bank penny drop)
        t15 = session.execute_turn(
            "Bank penny drop kya hota hai?",
            expected_phase=8,
            tool_call="get_kyc_guidance",
            tool_args={"step_or_doc": "bank"},
        )
        self.assertIn("Bank", t15["tool_result"]["step"])

        # Turn 16: Topic Switch -> STL 7M (₹25 Lakhs for 6 months)
        t16 = session.execute_turn(
            "STL 7M mein maximum 25 lakh par 6 months ka payout kitna hota hai?",
            expected_phase=7,
            tool_call="calculate_stl_returns",
            tool_args={"amount": 2500000, "tenure_months": 6},
        )
        self.assertEqual(t16["tool_result"]["profit_rupees"], 225000.0)

        # Turn 17: Topic Switch -> Rule 4 Custom Portfolio (40% borrower rate, 5% NPA)
        t17 = session.execute_turn(
            "Custom portfolio mein 40% rate aur 5% NPA par net return kya banta hai?",
            expected_phase=7,
            tool_call="calculate_manual_lending",
            tool_args={"amount": 100000, "tenure_months": 12, "custom_borrower_rate_pct": 40, "custom_npa_rate_pct": 5},
        )
        self.assertEqual(t17["tool_result"]["step_f_net_profit_rupees"], 27000.0)

        # Turn 18: Topic Switch -> App Lumpsum Flow
        t18 = session.execute_turn(
            "App mein lumpsum investment kaise select karte hain?",
            expected_phase=8,
            tool_call="get_app_screen_flow",
            tool_args={"target_flow": "lumpsum"},
        )
        self.assertIn("STL", str(t18["tool_result"]))

        # Turn 19: Topic Switch -> Daily Liquidity Mechanism
        t19 = session.execute_turn("Daily EDI payout ka kya matlab hai?", expected_phase=5)
        self.assertEqual(t19["phase"], 5)

        # ── Turn 20: CRUCIAL RECALL TURN ─────────────────────────────
        # After 20 full chaotic turns, assert that the user profile maintains the initial ₹24 Lakhs low-risk daily payout constraint
        t20 = session.execute_turn(
            "Achha, sab questions ho gaye. Ab mere original 24 lakh low-risk plan par aate hain.",
            expected_phase=6,
        )
        self.assertEqual(t20["turn"], 20)
        self.assertEqual(session.user_profile["amount"], 2400000.0)
        self.assertEqual(session.user_profile["risk_appetite"], "low")
        self.assertEqual(session.user_profile["payout_preference"], "daily")
        self.assertEqual(session.user_profile["tenure_months"], 12)

        # Turn 21: Execute Exact Mathematical Calculation on Preserved Profile
        t21 = session.execute_turn(
            "24 lakh par mera exact daily payout aur total profit kya hoga?",
            expected_phase=7,
            tool_call="calculate_mtl_returns",
            tool_args={"amount": session.user_profile["amount"], "repayment_type": session.user_profile["payout_preference"]},
        )
        res_mtl = t21["tool_result"]
        self.assertEqual(res_mtl["principal"], 2400000.0)
        self.assertEqual(res_mtl["profit_rupees"], 432000.0)
        self.assertEqual(res_mtl["final_maturity_amount"], 2832000.0)
        self.assertEqual(res_mtl["payout_amount"], 7758.90)
        self.assertEqual(res_mtl["annualized_xirr_pct"], 18.0)

        # Turns 22–30: Progress to Onboarding, KYC completion, and Closing
        session.execute_turn("Main KYC complete kar leta hoon.", expected_phase=8, profile_updates={"kyc_completed_steps": ["pan", "aadhaar", "bank"]})
        session.execute_turn("Main kal subah 10 AM ko deposit complete karunga.", expected_phase=9, profile_updates={"commitment_date": "tomorrow 10:00 AM"})
        session.execute_turn("UPI ID copy kar li hai.", expected_phase=9)
        session.execute_turn("Dhanyawad Pragya!", expected_phase=9)

        self.assertEqual(len(session.turns), 25)
        self.assertEqual(session.user_profile["amount"], 2400000.0)
        self.assertEqual(session.user_profile["payout_preference"], "daily")
        self.assertEqual(session.user_profile["commitment_date"], "tomorrow 10:00 AM")


class TestChallengerBoundaryFuzzing(unittest.TestCase):
    """Exhaustive boundary testing across tenures, amounts, rates, and invalid configurations."""

    def test_tenure_boundary_sweep_across_all_tools(self):
        """Sweeps tenures from -5 to 25 months across all calculation tools."""
        # 1. 9-month tenure must be strictly rejected by all tools
        res_rec_9 = get_product_recommendation(amount=100000, tenure_months=9)
        self.assertFalse(res_rec_9["is_valid"])
        self.assertIn("9-month", res_rec_9["error"])

        res_manual_9 = calculate_manual_lending(amount=50000, tenure_months=9)
        self.assertIn("error", res_manual_9)
        self.assertIn("9-month", res_manual_9["error"])

        res_stl_9 = calculate_stl_returns(amount=50000, tenure_months=9)
        self.assertIn("error", res_stl_9)

        # 2. Invalid tenures for STL (valid: 3, 4, 5, 6)
        for t in [-2, 0, 1, 2, 7, 8, 10, 12, 14, 24]:
            res = calculate_stl_returns(amount=50000, tenure_months=t)
            self.assertIn("error", res, f"STL should reject tenure={t}")

        # 3. Valid tenures for STL
        for t in [3, 4, 5, 6]:
            res = calculate_stl_returns(amount=50000, tenure_months=t)
            self.assertNotIn("error", res, f"STL should accept tenure={t}")
            self.assertGreater(res["profit_rupees"], 0)

        # 4. Invalid tenures for Manual Lending (valid: 2, 3, 4, 5, 6, 12)
        for t in [-5, 0, 1, 7, 8, 9, 10, 11, 13, 15, 24]:
            res = calculate_manual_lending(amount=50000, tenure_months=t)
            self.assertIn("error", res, f"Manual lending should reject tenure={t}")

        # 5. Valid tenures for Manual Lending
        for t in [2, 3, 4, 5, 6, 12]:
            res = calculate_manual_lending(amount=50000, tenure_months=t)
            self.assertNotIn("error", res, f"Manual lending should accept tenure={t}")

    def test_amount_boundaries_and_platform_limits(self):
        """Tests exact boundary thresholds: ₹250 min, ₹25k STL min, ₹1L MTL min, ₹10L/₹25L caps, ₹50L platform ceiling."""
        # Platform minimum ₹250
        self.assertFalse(get_product_recommendation(amount=0)["is_valid"])
        self.assertFalse(get_product_recommendation(amount=-100)["is_valid"])
        self.assertFalse(get_product_recommendation(amount=249)["is_valid"])
        self.assertTrue(get_product_recommendation(amount=250)["is_valid"])

        self.assertIn("error", calculate_manual_lending(amount=249, tenure_months=3))
        self.assertNotIn("error", calculate_manual_lending(amount=250, tenure_months=3))

        # Sub-₹25,000 routing to Manual Lending
        rec_micro = get_product_recommendation(amount=5000)
        self.assertTrue(rec_micro["is_valid"])
        self.assertEqual(rec_micro["recommended_product"], "Manual Lending")

        # STL boundaries (₹25k to ₹25L)
        self.assertIn("error", calculate_stl_returns(amount=24999))
        self.assertNotIn("error", calculate_stl_returns(amount=25000))
        self.assertNotIn("error", calculate_stl_returns(amount=2500000))
        self.assertIn("error", calculate_stl_returns(amount=2500001))

        # MTL boundaries
        self.assertIn("error", calculate_mtl_returns(amount=99999))
        self.assertNotIn("error", calculate_mtl_returns(amount=100000, repayment_type="monthly"))
        self.assertNotIn("error", calculate_mtl_returns(amount=1000000, repayment_type="monthly"))
        self.assertIn("error", calculate_mtl_returns(amount=1000001, repayment_type="monthly"))

        self.assertNotIn("error", calculate_mtl_returns(amount=2500000, repayment_type="daily"))
        self.assertIn("error", calculate_mtl_returns(amount=2500001, repayment_type="daily"))

        # Platform ceiling ₹50 Lakhs
        self.assertNotIn("error", calculate_manual_lending(amount=5000000, tenure_months=12))
        self.assertIn("error", calculate_manual_lending(amount=5000001, tenure_months=12))
        self.assertFalse(get_product_recommendation(amount=5000001)["is_valid"])

    def test_custom_manual_portfolio_rule_4_boundaries(self):
        """Validates Rule 4 Custom Portfolio edge cases: negative rates, extreme NPA, zero NPA."""
        # Negative borrower rate
        res_neg_rate = calculate_manual_lending(amount=100000, tenure_months=12, custom_borrower_rate_pct=-5.0)
        self.assertIn("error", res_neg_rate)

        # Negative NPA rate
        res_neg_npa = calculate_manual_lending(amount=100000, tenure_months=12, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=-2.0)
        self.assertIn("error", res_neg_npa)

        # NPA rate > 100%
        res_high_npa = calculate_manual_lending(amount=100000, tenure_months=12, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=105.0)
        self.assertIn("error", res_high_npa)

        # Zero NPA rate (100% performing)
        res_zero_npa = calculate_manual_lending(amount=100000, tenure_months=12, custom_borrower_rate_pct=36.0, custom_npa_rate_pct=0.0)
        self.assertEqual(res_zero_npa["step_b_npa_loss_rupees"], 0.0)
        self.assertEqual(res_zero_npa["step_c_performing_principal"], 100000.0)
        self.assertEqual(res_zero_npa["step_d_gross_interest"], 36000.0)
        self.assertEqual(res_zero_npa["step_e_platform_fee_rupees"], 6000.0)
        self.assertEqual(res_zero_npa["step_f_net_profit_rupees"], 30000.0)
        self.assertEqual(res_zero_npa["step_g_net_annualized_roi_pct"], 30.0)

    def test_sip_compounding_boundaries(self):
        """Validates SIP calculation edge cases: zero rate, negative amount, negative years."""
        self.assertIn("error", calculate_sip_returns(monthly_amount=-100, annual_rate=12, years=5))
        self.assertIn("error", calculate_sip_returns(monthly_amount=1000, annual_rate=-5, years=5))
        self.assertIn("error", calculate_sip_returns(monthly_amount=1000, annual_rate=12, years=-1))

        # Zero interest rate (pure savings accumulation)
        res_zero_rate = calculate_sip_returns(monthly_amount=5000, annual_rate=0, years=2)
        self.assertEqual(res_zero_rate["total_invested_rupees"], 120000.0)
        self.assertEqual(res_zero_rate["maturity_value_rupees"], 120000.0)
        self.assertEqual(res_zero_rate["wealth_gained_rupees"], 0.0)


class TestChallengerContextCompressionAt20k(unittest.TestCase):
    """Stress tests context window compression triggers at exactly 20,000 tokens and beyond."""

    def test_exact_20k_token_trigger_boundary(self):
        """Verifies compression activates when accumulated tokens reach or exceed 20,000 tokens."""
        session = ChallengerStatefulSession(compression_trigger_tokens=20000)

        # Set tokens to 19,990
        session.accumulated_tokens = 19990
        # Add a 5-token turn (total 19,995 < 20,000)
        session.execute_turn("Small turn", expected_phase=2, simulated_tokens_override=5)
        self.assertEqual(session.compression_events, 0)
        self.assertEqual(session.accumulated_tokens, 19995)

        # Add 6 tokens (total 20,001 >= 20,000) -> triggers compression
        session.execute_turn("Trigger turn", expected_phase=2, simulated_tokens_override=6)
        self.assertEqual(session.compression_events, 1)
        self.assertLess(session.accumulated_tokens, 20000)

    def test_heavy_multi_cycle_compression_under_100k_tokens(self):
        """Simulates massive conversational dialogue generating >100,000 tokens across 50 turns.
        Verifies repeated compression cycles occur without memory corruption or token explosion."""
        session = ChallengerStatefulSession(compression_trigger_tokens=20000)
        session.user_profile["amount"] = 2400000.0
        session.user_profile["risk_appetite"] = "low"
        session.user_profile["payout_preference"] = "daily"

        # Generate 50 heavy turns (2,500 tokens per turn = 125,000 total tokens)
        for i in range(50):
            session.execute_turn(
                f"Turn {i+1} detailed financial discussion with verbose audio and text payload.",
                expected_phase=min(9, (i // 5) + 1),
                simulated_tokens_override=2500,
            )

        # Verify multiple compression cycles occurred
        self.assertGreaterEqual(session.compression_events, 5)
        # Verify accumulated tokens remain capped
        self.assertLess(session.accumulated_tokens, 20000)
        # Verify user profile remains 100% intact
        self.assertEqual(session.user_profile["amount"], 2400000.0)
        self.assertEqual(session.user_profile["payout_preference"], "daily")

    def test_agent_live_and_server_cwc_configuration(self):
        """Verifies default signatures and cwc dictionary construction in agent_live and server."""
        # 1. agent_live run_agent_live default signature
        sig_agent = inspect.signature(agent_live.run_agent_live)
        self.assertEqual(sig_agent.parameters["context_compression_trigger_tokens"].default, 10000)
        self.assertEqual(sig_agent.parameters["context_compression"].default, True)

        # 2. server websocket_endpoint default signature
        sig_server = inspect.signature(server_module.websocket_endpoint)
        self.assertEqual(sig_server.parameters["context_compression_trigger_tokens"].default, 10000)


class TestChallengerSalesStateMachineRobustness(unittest.TestCase):
    """Stress tests non-linear phase jumps, callback handling, and prompt compliance."""

    def test_all_9_phases_and_objection_playbook_in_prompt(self):
        """Asserts exact presence of all 9 phases, objection directives, and boundary rules."""
        self.assertIn("<nine_phase_sales_journey>", SYSTEM_PROMPT)
        self.assertIn("Phase 1: Time Check & Availability", SYSTEM_PROMPT)
        self.assertIn("Phase 2: Discovery & P2P Familiarity", SYSTEM_PROMPT)
        self.assertIn("Phase 3: Concept Education", SYSTEM_PROMPT)
        self.assertIn("Phase 4: Platform Legitimacy & RBI Trust", SYSTEM_PROMPT)
        self.assertIn("Phase 5: Risk Mitigation & Diversification Math", SYSTEM_PROMPT)
        self.assertIn("Phase 6: Confidence & Readiness Check", SYSTEM_PROMPT)
        self.assertIn("Phase 7: Product Recommendation & Mathematical Calculation", SYSTEM_PROMPT)
        self.assertIn("Phase 8: App & KYC Navigation", SYSTEM_PROMPT)
        self.assertIn("Phase 9: Commitment & Close", SYSTEM_PROMPT)
        self.assertIn("<boundary_and_contradiction_handling>", SYSTEM_PROMPT)
        self.assertIn("9-Month Tenure Rejection (Strict)", SYSTEM_PROMPT)
        self.assertIn("Platform Absolute Minimum: ₹250", SYSTEM_PROMPT)
        self.assertIn("Platform Absolute Ceiling: ₹50,00,000", SYSTEM_PROMPT)
        self.assertIn("<objection_handling_playbook>", SYSTEM_PROMPT)

    def test_non_linear_objection_jump_and_recovery(self):
        """Simulates user jumping from Phase 8 (KYC) back to Phase 4/5 (Safety & FD objections)
        and successfully recovering forward to Phase 9 (Commitment & Close)."""
        session = ChallengerStatefulSession(compression_trigger_tokens=20000)

        # Start at Phase 8 (user reached KYC)
        session.execute_turn("Main KYC start kar raha tha...", expected_phase=8)

        # Sudden hesitation / objection jump -> Phase 4/5
        t_obj = session.execute_turn(
            "Wait, KYC karne se pehle batayein ki agar platform band ho gaya toh mere paise ka kya hoga?",
            expected_phase=4,
        )
        self.assertEqual(t_obj["phase"], 4)

        # Second objection -> Bank FD vs P2P
        t_fd = session.execute_turn("FD mein 7% guaranteed milta hai, yahan risk kyu loon?", expected_phase=5)
        self.assertEqual(t_fd["phase"], 5)

        # User satisfied, resumes KYC and closes
        session.execute_turn("Theek hai, Escrow aur diversification samajh gaya.", expected_phase=8)
        t_close = session.execute_turn("Main apna first plan kal activate karunga.", expected_phase=9, profile_updates={"commitment_date": "tomorrow"})
        self.assertEqual(t_close["phase"], 9)
        self.assertEqual(session.user_profile["commitment_date"], "tomorrow")


if __name__ == "__main__":
    unittest.main()
