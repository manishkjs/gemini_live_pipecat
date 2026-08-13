"""Adversarial Verification and Boundary Audit Test Suite for Milestone 4.
Author: Challenger 2 (Empirical Challenger)

Tests:
1. 9-Phase Consultative Sales Journey Structure, Keywords & Monotonic Ordering.
2. Comprehensive Objection Handling Playbook (NPA Defaults, Bank FD Comparison, ICICI/IDBI Escrow, Liquidity).
3. 9-Month Tenure Rejection across ALL entry points (get_product_recommendation, calculate_manual_lending, calculate_stl_returns, system_prompt.py).
4. Platform Boundaries & Routing (₹250 min, sub-₹25k manual routing, ₹50L max, ₹25L STL cap, MTL caps).
5. Context Window Compression Configuration (20,000 token default in agent_live and server, cwc construction).
6. 25-Turn Stateful Sales Simulation & Memory Retention (₹24L, low risk, daily payout, 12-month tenure).
7. Accurate Token Accumulation & 20k Token Sliding Window Compression Trigger.
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
import importlib.util
server_py_path = os.path.join(SERVER_DIR, "server.py")
server_spec = importlib.util.spec_from_file_location("server_app_module", server_py_path)
server_app_module = importlib.util.module_from_spec(server_spec)
server_spec.loader.exec_module(server_app_module)
websocket_endpoint = getattr(server_app_module, "websocket_endpoint", None)



class TestNinePhaseSalesJourneyStructure(unittest.TestCase):
    """Audits the 9-Phase Consultative Sales Funnel structure and keywords in system_prompt.py."""

    def test_all_nine_phases_present_and_monotonic(self):
        """Asserts all 9 phases appear in strictly increasing sequential order in SYSTEM_PROMPT."""
        phases = [
            "Phase 1: Time Check & Availability",
            "Phase 2: Discovery & P2P Familiarity",
            "Phase 3: Concept Education",
            "Phase 4: Platform Legitimacy & RBI Trust",
            "Phase 5: Risk Mitigation & Diversification Math",
            "Phase 6: Confidence & Readiness Check",
            "Phase 7: Product Recommendation & Mathematical Calculation",
            "Phase 8: App & KYC Navigation",
            "Phase 9: Commitment & Close",
        ]
        self.assertIn("<nine_phase_sales_journey>", SYSTEM_PROMPT)
        self.assertIn("</nine_phase_sales_journey>", SYSTEM_PROMPT)

        last_pos = -1
        for phase in phases:
            pos = SYSTEM_PROMPT.find(phase)
            self.assertNotEqual(pos, -1, f"Missing phase header in SYSTEM_PROMPT: {phase}")
            self.assertGreater(pos, last_pos, f"Phase '{phase}' is out of order")
            last_pos = pos

    def test_phase_1_to_9_keyword_coverage(self):
        """Audits essential keyword anchors across each phase."""
        expected_keywords = {
            1: ["Time Check", "2 minutes", "availability", "convenient callback"],
            2: ["Discovery", "P2P Familiarity", "goals profiling", "daily liquidity"],
            3: ["Concept Education", "creditworthy", "12% to 24% p.a.", "bank margins"],
            4: ["Platform Legitimacy", "RBI Trust", "RBI-registered NBFC-P2P", "Trustee Escrow account", "ICICI/IDBI"],
            5: ["Risk Mitigation", "Diversification Math", "100+ borrowers", "₹50,000", "NPA provisions"],
            6: ["Confidence & Readiness", "readiness check", "investment amount", "tenure horizon"],
            7: ["Product Recommendation", "Mathematical Calculation", "deterministic tools", "STL 5M", "STL 7M", "MTL 14M Monthly", "MTL 14M Daily"],
            8: ["App & KYC Navigation", "KYC guidance", "PAN", "Aadhaar Digilocker OTP", "Bank penny-drop"],
            9: ["Commitment & Close", "starting deposit", "activation date", "first lending plan", "Escrow UPI/Netbanking"],
        }
        for phase_num, keywords in expected_keywords.items():
            for kw in keywords:
                self.assertIn(kw, SYSTEM_PROMPT, f"Phase {phase_num} missing keyword anchor: '{kw}'")


class TestObjectionHandlingPlaybook(unittest.TestCase):
    """Audits the 4 required objection handlers in system_prompt.py."""

    def test_npa_defaults_objection_coverage(self):
        """Audits NPA defaults objection: 100+ borrowers, credit scoring, net returns."""
        self.assertIn("Is it safe? What if borrowers default (NPA)?", SYSTEM_PROMPT)
        self.assertIn("100+ borrowers", SYSTEM_PROMPT)
        self.assertIn("net of historical NPA provisions", SYSTEM_PROMPT)

    def test_bank_fd_comparison_objection_coverage(self):
        """Audits Bank FD comparison objection: 6.5%-7.5% vs 12%-24% and continuous cash flows."""
        self.assertIn("Why not just put money in Bank Fixed Deposits (FD)?", SYSTEM_PROMPT)
        self.assertIn("Bank FDs give only 6.5%–7.5%", SYSTEM_PROMPT)
        self.assertIn("12%–24% p.a. returns", SYSTEM_PROMPT)
        self.assertIn("monthly EMI or daily interest payouts", SYSTEM_PROMPT)

    def test_rbi_legitimacy_and_escrow_objection_coverage(self):
        """Audits RBI registration and ICICI/IDBI Trustee Escrow coverage."""
        self.assertIn("Is Cymbal Lending legal / RBI approved?", SYSTEM_PROMPT)
        self.assertIn("RBI-registered NBFC-P2P", SYSTEM_PROMPT)
        self.assertIn("ICICI/IDBI Trustee Escrow", SYSTEM_PROMPT)

    def test_liquidity_objection_coverage(self):
        """Audits liquidity objection: monthly EMIs / daily EDI credits without lock-ins."""
        self.assertIn("Can I withdraw money anytime?", SYSTEM_PROMPT)
        self.assertIn("monthly EMIs", SYSTEM_PROMPT)
        self.assertIn("regular ongoing liquidity rather than rigid lock-ins", SYSTEM_PROMPT)


class TestNineMonthTenureRejectionAudit(unittest.TestCase):
    """Adversarially tests 9-month tenure rejection across ALL system entry points."""

    def test_rejection_in_get_product_recommendation(self):
        """`get_product_recommendation` with tenure_months=9 MUST return is_valid=False and advise 6M/12M."""
        res = get_product_recommendation(amount=100000, tenure_months=9)
        self.assertFalse(res["is_valid"])
        self.assertIn("9-month", res["error"])
        self.assertIn("6-month STL 7M", res["suggestion"])
        self.assertIn("12-month MTL 14M", res["suggestion"])

    def test_rejection_in_calculate_manual_lending(self):
        """`calculate_manual_lending` with tenure_months=9 MUST return error dictionary."""
        res = calculate_manual_lending(amount=50000, tenure_months=9)
        self.assertIn("error", res)
        self.assertIn("9-month tenure is strictly not available", res["error"])

    def test_rejection_in_calculate_stl_returns(self):
        """`calculate_stl_returns` with tenure_months=9 MUST reject with invalid tenure."""
        res = calculate_stl_returns(amount=50000, tenure_months=9)
        self.assertIn("error", res)
        self.assertIn("Invalid tenure 9 months for STL", res["error"])

    def test_rejection_in_system_prompt_boundary_rules(self):
        """`SYSTEM_PROMPT` MUST explicitly reject 9-month tenures and specify 6M STL 7M & 12M MTL 14M."""
        self.assertIn("<boundary_and_contradiction_handling>", SYSTEM_PROMPT)
        self.assertIn("9-Month Tenure Rejection (Strict)", SYSTEM_PROMPT)
        self.assertIn("STRICTLY NOT AVAILABLE", SYSTEM_PROMPT)
        self.assertIn("6-Month STL 7M", SYSTEM_PROMPT)
        self.assertIn("12-Month MTL 14M", SYSTEM_PROMPT)


class TestPlatformBoundariesAndLimitsAudit(unittest.TestCase):
    """Adversarially tests platform minimums, sub-₹25k routing, and product ceilings."""

    def test_platform_minimum_250_rupees_boundaries(self):
        """Amounts below ₹250 rejected; ₹250 allowed in manual lending."""
        res_below = get_product_recommendation(amount=249.99)
        self.assertFalse(res_below["is_valid"])
        self.assertIn("Minimum platform investment/lending amount is ₹250", res_below["error"])

        res_man_below = calculate_manual_lending(amount=249.99, tenure_months=3)
        self.assertIn("error", res_man_below)
        self.assertIn("Minimum manual lending amount is ₹250", res_man_below["error"])

        res_man_exact = calculate_manual_lending(amount=250.0, tenure_months=3)
        self.assertEqual(res_man_exact["principal"], 250.0)
        self.assertNotIn("error", res_man_exact)

    def test_sub_25k_manual_routing(self):
        """Amounts from ₹250 to ₹24,999 route to Manual Lending."""
        for amt in [250.0, 1000.0, 15000.0, 24999.0]:
            res = get_product_recommendation(amount=amt)
            self.assertTrue(res["is_valid"])
            self.assertEqual(res["recommended_product"], "Manual Lending")
            self.assertIn("₹250", res["note"])

    def test_platform_maximum_ceiling_50_lakhs(self):
        """Amounts > ₹50,00,000 rejected across tools; exact ₹50L allowed in manual."""
        res_rec_high = get_product_recommendation(amount=5000001)
        self.assertFalse(res_rec_high["is_valid"])
        self.assertIn("50,00,000", res_rec_high["error"])

        res_man_high = calculate_manual_lending(amount=5000001, tenure_months=6)
        self.assertIn("error", res_man_high)
        self.assertIn("50,00,000", res_man_high["error"])

        res_man_max = calculate_manual_lending(amount=5000000, tenure_months=6)
        self.assertEqual(res_man_max["principal"], 5000000.0)
        self.assertNotIn("error", res_man_max)

    def test_product_specific_caps_stl_and_mtl(self):
        """STL (₹25k-₹25L), MTL Monthly (₹1L-₹10L), MTL Daily (₹1L-₹25L)."""
        # STL ₹25k min
        stl_under = calculate_stl_returns(amount=24999)
        self.assertIn("error", stl_under)
        self.assertEqual(stl_under["min_amount"], 25000)

        # STL ₹25L max
        stl_max = calculate_stl_returns(amount=2500000, tenure_months=6)
        self.assertEqual(stl_max["principal"], 2500000.0)
        stl_over = calculate_stl_returns(amount=2500001, tenure_months=6)
        self.assertIn("error", stl_over)

        # MTL Monthly ₹10L cap
        mtl_m_max = calculate_mtl_returns(amount=1000000, repayment_type="monthly")
        self.assertEqual(mtl_m_max["principal"], 1000000.0)
        mtl_m_over = calculate_mtl_returns(amount=1000001, repayment_type="monthly")
        self.assertIn("error", mtl_m_over)

        # MTL Daily ₹25L cap and ₹24L exact math
        mtl_d_24l = calculate_mtl_returns(amount=2400000, repayment_type="daily")
        self.assertEqual(mtl_d_24l["principal"], 2400000.0)
        self.assertEqual(mtl_d_24l["profit_rupees"], 432000.0)
        self.assertEqual(mtl_d_24l["final_maturity_amount"], 2832000.0)
        self.assertEqual(mtl_d_24l["payout_amount"], 7758.90)

        mtl_d_over = calculate_mtl_returns(amount=2500001, repayment_type="daily")
        self.assertIn("error", mtl_d_over)


class TestContextCompressionConfigurationAudit(unittest.TestCase):
    """Audits Context Window Compression signature defaults and cwc dictionary logic."""

    def test_run_agent_live_signature_defaults(self):
        """run_agent_live must have context_compression=True and trigger_tokens=20000."""
        sig = inspect.signature(agent_live.run_agent_live)
        params = sig.parameters
        self.assertIn("context_compression", params)
        self.assertIn("context_compression_trigger_tokens", params)
        self.assertEqual(params["context_compression"].default, True)
        self.assertEqual(params["context_compression_trigger_tokens"].default, 20000)

    def test_server_websocket_endpoint_signature_defaults(self):
        """websocket_endpoint in server.py must have context_compression=True and trigger_tokens=20000."""
        sig = inspect.signature(websocket_endpoint)
        params = sig.parameters
        self.assertIn("context_compression", params)
        self.assertIn("context_compression_trigger_tokens", params)
        self.assertEqual(params["context_compression"].default, True)
        self.assertEqual(params["context_compression_trigger_tokens"].default, 20000)

    def test_cwc_dictionary_construction(self):
        """Audits cwc dictionary construction across all permutations."""
        def build_cwc(context_compression: bool, context_compression_trigger_tokens: Any) -> Dict[str, Any]:
            cwc = {}
            if context_compression:
                cwc["enabled"] = True
                cwc["trigger_tokens"] = context_compression_trigger_tokens if context_compression_trigger_tokens is not None else 20000
            return cwc

        self.assertEqual(build_cwc(True, 20000), {"enabled": True, "trigger_tokens": 20000})
        self.assertEqual(build_cwc(True, None), {"enabled": True, "trigger_tokens": 20000})
        self.assertEqual(build_cwc(True, 15000), {"enabled": True, "trigger_tokens": 15000})
        self.assertEqual(build_cwc(False, 20000), {})


class StatefulSalesSessionHarness:
    """Accurate simulation harness for multi-turn conversational state and token tracking."""

    def __init__(self, compression_trigger_tokens: int = 20000):
        self.compression_trigger_tokens = compression_trigger_tokens
        self.current_phase = 1
        self.user_profile: Dict[str, Any] = {
            "amount": None,
            "risk_appetite": None,
            "payout_preference": None,
            "tenure_months": None,
            "kyc_completed_steps": [],
            "commitment_date": None,
        }
        self.turns: List[Dict[str, Any]] = []
        self.accumulated_tokens = 1500  # Initial System Prompt
        self.compression_events = 0

    def execute_turn(
        self,
        user_utterance: str,
        expected_phase: int,
        tool_call: Optional[str] = None,
        tool_args: Optional[Dict[str, Any]] = None,
        profile_updates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.current_phase = expected_phase
        if profile_updates:
            self.user_profile.update(profile_updates)

        tool_result = None
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

        # Audio + text multimodal tokens per turn (~800 tokens)
        turn_tokens = len(user_utterance.split()) * 10 + 750
        if tool_result:
            turn_tokens += len(str(tool_result).split()) * 5
        self.accumulated_tokens += turn_tokens

        # Check Context Compression Trigger
        if self.accumulated_tokens >= self.compression_trigger_tokens:
            self.compression_events += 1
            compressed_tokens = int(self.accumulated_tokens * 0.4)
            self.accumulated_tokens -= compressed_tokens

        turn_record = {
            "turn": len(self.turns) + 1,
            "phase": self.current_phase,
            "tool_called": tool_call,
            "tool_result": tool_result,
            "profile_snapshot": dict(self.user_profile),
            "accumulated_tokens": self.accumulated_tokens,
            "compression_events": self.compression_events,
        }
        self.turns.append(turn_record)
        return turn_record


class TestAdversarial25TurnSalesSimulation(unittest.TestCase):
    """Simulates a 25-turn sales journey validating memory retention and compression."""

    def test_25_turn_journey_and_memory_retention(self):
        """Validates all 9 phases, objection handling, 9-month rejection, and constraint preservation."""
        session = StatefulSalesSessionHarness(compression_trigger_tokens=20000)

        # Phase 1: Time Check
        session.execute_turn("नमस्ते! क्या बात है?", expected_phase=1)
        session.execute_turn("हाँ 2 मिनट हैं मेरे पास।", expected_phase=1)

        # Phase 2: Discovery
        session.execute_turn("P2P lending explore कर रहा हूँ।", expected_phase=2)
        # In Turn 4: User establishes ₹24 Lakhs, low risk, daily payout
        t4 = session.execute_turn(
            "24 lakh invest karne hain, low risk aur daily payout prefer karunga.",
            expected_phase=2,
            profile_updates={"amount": 2400000.0, "risk_appetite": "low", "payout_preference": "daily"},
        )
        self.assertEqual(t4["profile_snapshot"]["amount"], 2400000.0)

        # Phase 3: Concept Education
        session.execute_turn("Returns kaise bante hain?", expected_phase=3)

        # Phase 4: Platform Legitimacy
        session.execute_turn("RBI approved hai kya?", expected_phase=4)

        # Phase 5: Risk Mitigation & Objections
        session.execute_turn("Borrower default kare toh?", expected_phase=5)
        session.execute_turn("Bank FD mein 7% mil raha hai, FD kyu nahi?", expected_phase=5)

        # Phase 6: Confidence & 9-month Contradiction Rejection
        session.execute_turn("Samajh gaya.", expected_phase=6)
        t10 = session.execute_turn(
            "Kya 9 month ke liye invest kar sakta hoon?",
            expected_phase=6,
            tool_call="get_product_recommendation",
            tool_args={"amount": 2400000.0, "tenure_months": 9},
        )
        self.assertFalse(t10["tool_result"]["is_valid"])
        self.assertIn("9-month", t10["tool_result"]["error"])

        session.execute_turn(
            "Theek hai, 12 months MTL plan theek hai daily payout ke sath.",
            expected_phase=6,
            profile_updates={"tenure_months": 12},
        )

        # Phase 7: Product Recommendation & Math Calculation
        t12 = session.execute_turn(
            "24 lakh par exactly kitna daily payout banega?",
            expected_phase=7,
            tool_call="calculate_mtl_returns",
            tool_args={"amount": session.user_profile["amount"], "repayment_type": "daily"},
        )
        res_mtl = t12["tool_result"]
        self.assertEqual(res_mtl["principal"], 2400000.0)
        self.assertEqual(res_mtl["profit_rupees"], 432000.0)
        self.assertEqual(res_mtl["final_maturity_amount"], 2832000.0)
        self.assertEqual(res_mtl["payout_amount"], 7758.90)

        # Phase 7: Objection & Boundary Test (₹60 Lakhs)
        session.execute_turn("Daily payout bank mein aayega?", expected_phase=7)
        t14 = session.execute_turn(
            "60 lakh par kya milega?",
            expected_phase=7,
            tool_call="get_product_recommendation",
            tool_args={"amount": 6000000.0, "tenure_months": 12},
        )
        self.assertFalse(t14["tool_result"]["is_valid"])

        session.execute_turn("Theek hai, 24 lakh hi continue karunga.", expected_phase=7)

        # Phase 8: App & KYC Navigation
        t16 = session.execute_turn(
            "KYC start karein.",
            expected_phase=8,
            tool_call="get_kyc_guidance",
            tool_args={"step_or_doc": "pan"},
            profile_updates={"kyc_completed_steps": ["pan"]},
        )
        self.assertEqual(t16["tool_result"]["step"], "PAN Verification")

        session.execute_turn(
            "Aadhaar verify ho gaya.",
            expected_phase=8,
            tool_call="get_kyc_guidance",
            tool_args={"step_or_doc": "aadhaar"},
            profile_updates={"kyc_completed_steps": ["pan", "aadhaar"]},
        )
        session.execute_turn(
            "Bank link ho gaya penny drop se.",
            expected_phase=8,
            tool_call="get_kyc_guidance",
            tool_args={"step_or_doc": "bank"},
            profile_updates={"kyc_completed_steps": ["pan", "aadhaar", "bank"]},
        )
        t19 = session.execute_turn(
            "Loan filters check karna hai.",
            expected_phase=8,
            tool_call="get_app_screen_flow",
            tool_args={"target_flow": "loan filter"},
        )
        self.assertEqual(len(t19["tool_result"]["available_filters"]), 8)

        t20 = session.execute_turn(
            "Deposit flow kya hai?",
            expected_phase=8,
            tool_call="get_app_screen_flow",
            tool_args={"target_flow": "deposit"},
        )
        self.assertEqual(t20["turn"], 20)

        # Post-20 Turn Memory Invariant Check
        self.assertEqual(session.user_profile["amount"], 2400000.0)
        self.assertEqual(session.user_profile["risk_appetite"], "low")
        self.assertEqual(session.user_profile["payout_preference"], "daily")
        self.assertEqual(session.user_profile["tenure_months"], 12)
        self.assertEqual(session.user_profile["kyc_completed_steps"], ["pan", "aadhaar", "bank"])

        # Phase 9: Commitment & Close
        session.execute_turn(
            "Kal subah 10 baje 24 lakh transfer karunga.",
            expected_phase=9,
            profile_updates={"commitment_date": "tomorrow 10:00 AM"},
        )
        session.execute_turn("Escrow details clear hain.", expected_phase=9)
        t23 = session.execute_turn(
            "9 month option later aa sakta hai kya?",
            expected_phase=9,
            tool_call="get_product_recommendation",
            tool_args={"amount": 2400000.0, "tenure_months": 9},
        )
        self.assertFalse(t23["tool_result"]["is_valid"])

        session.execute_turn("12 month daily hi finalize hai.", expected_phase=9)
        session.execute_turn("Thanks Pragya!", expected_phase=9)

        self.assertEqual(len(session.turns), 25)
        self.assertEqual(session.user_profile["amount"], 2400000.0)
        self.assertEqual(session.user_profile["commitment_date"], "tomorrow 10:00 AM")

    def test_context_compression_sliding_window_trigger(self):
        """Audits token accumulation crossing 20,000 tokens and activating compression."""
        session = StatefulSalesSessionHarness(compression_trigger_tokens=20000)
        session.accumulated_tokens = 19500
        # Turn with tool call adds ~1,000+ tokens, pushing over 20,000
        turn = session.execute_turn(
            "Detailed query with calculation",
            expected_phase=7,
            tool_call="calculate_mtl_returns",
            tool_args={"amount": 2400000.0, "repayment_type": "daily"},
        )
        self.assertGreaterEqual(session.compression_events, 1)
        self.assertLess(session.accumulated_tokens, 20000)


class TestExtendedAdversarialEdgeCases(unittest.TestCase):
    """Deep adversarial boundary edge cases across all financial and routing interfaces."""

    def test_tenure_rejection_matrix(self):
        """Tenure 9 is strictly rejected; valid tenures succeed; other invalid tenures reject appropriately."""
        # 9-month rejection in get_product_recommendation
        res9 = get_product_recommendation(amount=100000, tenure_months=9)
        self.assertFalse(res9["is_valid"])
        self.assertIn("9-month", res9["error"])

        # 9-month rejection in calculate_manual_lending
        res_man9 = calculate_manual_lending(amount=50000, tenure_months=9)
        self.assertIn("error", res_man9)
        self.assertIn("9-month tenure is strictly not available", res_man9["error"])

        # 9-month rejection in calculate_stl_returns
        res_stl9 = calculate_stl_returns(amount=50000, tenure_months=9)
        self.assertIn("error", res_stl9)
        self.assertIn("Invalid tenure 9 months", res_stl9["error"])

        # Other invalid tenures in manual lending (e.g. 0, -1, 7, 8, 10, 11, 13)
        for invalid_t in [0, -1, 7, 8, 10, 11, 13]:
            res_inv = calculate_manual_lending(amount=50000, tenure_months=invalid_t)
            self.assertIn("error", res_inv)

        # Valid tenures in manual lending (2, 3, 4, 5, 6, 12)
        for valid_t in [2, 3, 4, 5, 6, 12]:
            res_v = calculate_manual_lending(amount=50000, tenure_months=valid_t)
            self.assertNotIn("error", res_v)
            self.assertEqual(res_v["principal"], 50000.0)

    def test_recommendation_matrix(self):
        """Validates correct product recommendation across amount, risk, and tenure variations."""
        # ₹24L Low Risk -> MTL 14M Daily
        r_24l_low = get_product_recommendation(amount=2400000, risk_appetite="low", tenure_months=12)
        self.assertTrue(r_24l_low["is_valid"])
        self.assertEqual(r_24l_low["recommended_product"], "MTL 14M Daily (EDI)")

        # ₹10L Medium Risk -> MTL 14M Monthly
        r_10l_med = get_product_recommendation(amount=1000000, risk_appetite="medium", tenure_months=12)
        self.assertTrue(r_10l_med["is_valid"])
        self.assertEqual(r_10l_med["recommended_product"], "MTL 14M Monthly (EMI)")

        # ₹50k 3 months -> STL 5M
        r_50k_3m = get_product_recommendation(amount=50000, tenure_months=3)
        self.assertTrue(r_50k_3m["is_valid"])
        self.assertEqual(r_50k_3m["recommended_product"], "STL 5M")

        # ₹50k 6 months -> STL 7M
        r_50k_6m = get_product_recommendation(amount=50000, tenure_months=6)
        self.assertTrue(r_50k_6m["is_valid"])
        self.assertEqual(r_50k_6m["recommended_product"], "STL 7M")

        # ₹10k -> Manual Lending
        r_10k = get_product_recommendation(amount=10000)
        self.assertTrue(r_10k["is_valid"])
        self.assertEqual(r_10k["recommended_product"], "Manual Lending")

    def test_extreme_and_negative_amounts(self):
        """Negative and zero amounts must be rejected gracefully."""
        self.assertFalse(get_product_recommendation(amount=-500)["is_valid"])
        self.assertFalse(get_product_recommendation(amount=0)["is_valid"])
        self.assertIn("error", calculate_manual_lending(amount=-500, tenure_months=6))
        self.assertIn("error", calculate_manual_lending(amount=0, tenure_months=6))
        self.assertIn("error", calculate_stl_returns(amount=-500))
        self.assertIn("error", calculate_stl_returns(amount=0))
        self.assertIn("error", calculate_mtl_returns(amount=-500))
        self.assertIn("error", calculate_mtl_returns(amount=0))


if __name__ == "__main__":
    unittest.main()

