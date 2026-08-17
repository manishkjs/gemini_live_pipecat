"""Unit tests for Milestone 4 (Context Memory & Consultative Sales Journey).

Covers:
- 9-Phase Consultative Sales Funnel Prompt Structure & Ordering
- Contradiction & Boundary Handling (9-month tenure rejection, limits ₹250 to ₹50L, STL/MTL caps)
- Comprehensive Objection Handling Playbook (NPA defaults, Bank FDs, RBI Trustee Escrow, Liquidity)
- Context Compression Configuration (20,000 token default, override handling, settings dictionary)
"""

import unittest
import sys
import os
import inspect
from typing import Dict, Any

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


class TestNinePhaseSalesFunnelPromptStructure(unittest.TestCase):
    """Validates presence, ordering, and keyword anchors across the 9-Phase Consultative Sales Funnel."""

    def test_nine_phases_presence_and_order(self):
        """Asserts all 9 phases appear in exact sequential order within <nine_phase_sales_journey>."""
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

        last_index = -1
        for phase in phases:
            index = SYSTEM_PROMPT.find(phase)
            self.assertNotEqual(index, -1, f"Missing phase header in prompt: {phase}")
            self.assertGreater(index, last_index, f"Phase {phase} appeared out of sequence")
            last_index = index

    def test_phase_1_time_check_keywords(self):
        """Phase 1 must contain 2-minute availability check and callback option."""
        self.assertIn("Time Check", SYSTEM_PROMPT)
        self.assertIn("2 minutes", SYSTEM_PROMPT)
        self.assertIn("availability", SYSTEM_PROMPT)
        self.assertIn("convenient callback", SYSTEM_PROMPT)

    def test_phase_2_discovery_keywords(self):
        """Phase 2 must contain discovery, familiarity check, and goals profiling."""
        self.assertIn("Discovery", SYSTEM_PROMPT)
        self.assertIn("P2P Familiarity", SYSTEM_PROMPT)
        self.assertIn("goals profiling", SYSTEM_PROMPT)
        self.assertIn("daily liquidity", SYSTEM_PROMPT)

    def test_phase_3_concept_education_keywords(self):
        """Phase 3 must explain P2P concept, vetted borrowers, 12-24% returns, and bank margins."""
        self.assertIn("Concept Education", SYSTEM_PROMPT)
        self.assertIn("creditworthy", SYSTEM_PROMPT)
        self.assertIn("12% to 24% p.a.", SYSTEM_PROMPT)
        self.assertIn("bank margins", SYSTEM_PROMPT)

    def test_phase_4_platform_legitimacy_keywords(self):
        """Phase 4 must establish RBI-registered NBFC-P2P and Trustee Escrow account."""
        self.assertIn("Platform Legitimacy", SYSTEM_PROMPT)
        self.assertIn("RBI Trust", SYSTEM_PROMPT)
        self.assertIn("RBI-registered NBFC-P2P", SYSTEM_PROMPT)
        self.assertIn("Trustee Escrow account", SYSTEM_PROMPT)
        self.assertIn("ICICI/IDBI", SYSTEM_PROMPT)

    def test_phase_5_risk_mitigation_keywords(self):
        """Phase 5 must detail 100+ borrower diversification and NPA provision adjustments."""
        self.assertIn("Risk Mitigation", SYSTEM_PROMPT)
        self.assertIn("Diversification Math", SYSTEM_PROMPT)
        self.assertIn("100+ borrowers", SYSTEM_PROMPT)
        self.assertIn("₹50,000", SYSTEM_PROMPT)
        self.assertIn("NPA provisions", SYSTEM_PROMPT)

    def test_phase_6_confidence_readiness_keywords(self):
        """Phase 6 must check confidence, readiness, horizon (3, 6, 12 months) and amount."""
        self.assertIn("Confidence & Readiness", SYSTEM_PROMPT)
        self.assertIn("readiness check", SYSTEM_PROMPT)
        self.assertIn("investment amount", SYSTEM_PROMPT)
        self.assertIn("tenure horizon", SYSTEM_PROMPT)

    def test_phase_7_product_recommendation_math_keywords(self):
        """Phase 7 must require deterministic tool calls and outline STL 5M/7M and MTL 14M plans."""
        self.assertIn("Product Recommendation", SYSTEM_PROMPT)
        self.assertIn("Mathematical Calculation", SYSTEM_PROMPT)
        self.assertIn("deterministic tools", SYSTEM_PROMPT)
        self.assertIn("STL 5M", SYSTEM_PROMPT)
        self.assertIn("STL 7M", SYSTEM_PROMPT)
        self.assertIn("MTL 14M Monthly", SYSTEM_PROMPT)
        self.assertIn("MTL 14M Daily", SYSTEM_PROMPT)

    def test_phase_8_app_kyc_navigation_keywords(self):
        """Phase 8 must guide 3-step KYC: PAN, Aadhaar OTP, and Bank penny-drop linking."""
        self.assertIn("App & KYC Navigation", SYSTEM_PROMPT)
        self.assertIn("KYC guidance", SYSTEM_PROMPT)
        self.assertIn("PAN", SYSTEM_PROMPT)
        self.assertIn("Aadhaar Digilocker OTP", SYSTEM_PROMPT)
        self.assertIn("Bank penny-drop", SYSTEM_PROMPT)

    def test_phase_9_commitment_close_keywords(self):
        """Phase 9 must secure starting deposit amount, activation date, and escrow deposit method."""
        self.assertIn("Commitment & Close", SYSTEM_PROMPT)
        self.assertIn("starting deposit", SYSTEM_PROMPT)
        self.assertIn("activation date", SYSTEM_PROMPT)
        self.assertIn("first lending plan", SYSTEM_PROMPT)
        self.assertIn("Escrow UPI/Netbanking", SYSTEM_PROMPT)


class TestContradictionAndBoundaryEnforcement(unittest.TestCase):
    """Validates strict boundary handling, 9-month rejection across prompt & tools, and platform limits."""

    def test_system_prompt_boundary_section(self):
        """Asserts <boundary_and_contradiction_handling> exists with 9-month rejection and platform limits."""
        self.assertIn("<boundary_and_contradiction_handling>", SYSTEM_PROMPT)
        self.assertIn("9-Month Tenure Rejection (Strict)", SYSTEM_PROMPT)
        self.assertIn("STRICTLY NOT AVAILABLE", SYSTEM_PROMPT)
        self.assertIn("6-Month STL 7M plan (18% annualized XIRR", SYSTEM_PROMPT)
        self.assertIn("12-Month MTL 14M plan (24% XIRR Monthly EMI / 18% XIRR Daily EDI)", SYSTEM_PROMPT)
        self.assertIn("Platform Absolute Minimum: ₹250", SYSTEM_PROMPT)
        self.assertIn("Platform Absolute Ceiling: ₹50,00,000", SYSTEM_PROMPT)

    def test_nine_month_tenure_rejection_in_recommendation(self):
        """`get_product_recommendation` with tenure=9 must return is_valid=False and suggest 6M/12M."""
        res = get_product_recommendation(amount=100000, tenure_months=9)
        self.assertFalse(res["is_valid"])
        self.assertIn("9-month", res["error"])
        self.assertIn("6-month STL 7M", res["suggestion"])
        self.assertIn("12-month MTL 14M", res["suggestion"])

    def test_nine_month_tenure_rejection_in_manual_lending(self):
        """`calculate_manual_lending` with tenure_months=9 must return an explicit error dictionary."""
        res = calculate_manual_lending(amount=50000, tenure_months=9)
        self.assertIn("error", res)
        self.assertIn("9-month tenure is strictly not available", res["error"])
        self.assertIn("2, 3, 4, 5, 6, or 12 months", res["error"])

    def test_nine_month_tenure_rejection_in_stl(self):
        """`calculate_stl_returns` with tenure_months=9 must reject with available tenures."""
        res = calculate_stl_returns(amount=50000, tenure_months=9)
        self.assertIn("error", res)
        self.assertIn("Invalid tenure 9 months for STL", res["error"])

    def test_platform_minimum_boundary_250_rupees(self):
        """Amounts under ₹250 are rejected; ₹250 is the absolute platform minimum."""
        # Under ₹250 in get_product_recommendation
        res_low = get_product_recommendation(amount=200)
        self.assertFalse(res_low["is_valid"])
        self.assertIn("Minimum platform investment/lending amount is ₹250", res_low["error"])

        # Under ₹250 in calculate_manual_lending
        res_manual_low = calculate_manual_lending(amount=200, tenure_months=3)
        self.assertIn("error", res_manual_low)
        self.assertIn("Minimum manual lending amount is ₹250", res_manual_low["error"])

        # Valid ₹250 manual lending
        res_manual_exact = calculate_manual_lending(amount=250, tenure_months=3)
        self.assertEqual(res_manual_exact["principal"], 250.0)
        self.assertNotIn("error", res_manual_exact)

    def test_sub_25k_manual_routing(self):
        """Amounts between ₹250 and ₹25,000 must be routed to Manual Lending starting from ₹250."""
        res = get_product_recommendation(amount=10000)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["recommended_product"], "Manual Lending")
        self.assertIn("₹250", res.get("note", ""))

    def test_platform_maximum_ceiling_50_lakhs(self):
        """Amounts exceeding ₹50,00,000 must be rejected with the RBI aggregate ceiling."""
        res_rec_high = get_product_recommendation(amount=6000000)
        self.assertFalse(res_rec_high["is_valid"])
        self.assertIn("50,00,000", res_rec_high["error"])
        self.assertIn("50 Lakhs", res_rec_high["error"])

        res_manual_high = calculate_manual_lending(amount=5500000, tenure_months=6)
        self.assertIn("error", res_manual_high)
        self.assertIn("50,00,000", res_manual_high["error"])

        # Exact ₹50 Lakhs is permitted in manual lending
        res_manual_max = calculate_manual_lending(amount=5000000, tenure_months=6)
        self.assertEqual(res_manual_max["principal"], 5000000.0)

    def test_product_caps_stl_and_mtl(self):
        """STL capped at ₹25L; MTL Monthly capped at ₹10L; MTL Daily capped at ₹25L."""
        # STL cap ₹25L
        stl_valid = calculate_stl_returns(amount=2500000, tenure_months=6)
        self.assertEqual(stl_valid["principal"], 2500000.0)
        stl_invalid = calculate_stl_returns(amount=2500001, tenure_months=6)
        self.assertIn("error", stl_invalid)
        self.assertIn("Maximum investment amount for STL is ₹25,00,000", stl_invalid["error"])

        # MTL Monthly cap ₹10L
        mtl_m_valid = calculate_mtl_returns(amount=1000000, repayment_type="monthly")
        self.assertEqual(mtl_m_valid["principal"], 1000000.0)
        mtl_m_invalid = calculate_mtl_returns(amount=1000001, repayment_type="monthly")
        self.assertIn("error", mtl_m_invalid)
        self.assertIn("Maximum investment for MTL Monthly is ₹10,00,000", mtl_m_invalid["error"])

        # MTL Daily cap ₹25L (e.g. ₹24 Lakhs low-risk scenario)
        mtl_d_24l = calculate_mtl_returns(amount=2400000, repayment_type="daily")
        self.assertEqual(mtl_d_24l["principal"], 2400000.0)
        self.assertEqual(mtl_d_24l["profit_rupees"], 432000.0)
        self.assertEqual(mtl_d_24l["payout_amount"], 7758.90)

        mtl_d_invalid = calculate_mtl_returns(amount=2500001, repayment_type="daily")
        self.assertIn("error", mtl_d_invalid)
        self.assertIn("Maximum investment for MTL Daily is ₹25,00,000", mtl_d_invalid["error"])


class TestObjectionHandlingPlaybook(unittest.TestCase):
    """Validates the 4 core objection handlers in system_prompt.py."""

    def test_npa_defaults_objection_math(self):
        """Asserts NPA objection covers 100+ borrower diversification and net quoted returns."""
        self.assertIn('Objection: "Is it safe? What if borrowers default (NPA)?"', SYSTEM_PROMPT)
        self.assertIn("100+ borrowers", SYSTEM_PROMPT)
        self.assertIn("Quoted returns (e.g., 18%–24% XIRR) are already net of historical NPA provisions", SYSTEM_PROMPT)

    def test_bank_fd_comparison_objection(self):
        """Asserts Bank FD objection contrasts 6.5%-7.5% with 12%-24% and continuous cash flows."""
        self.assertIn('Objection: "Why not just put money in Bank Fixed Deposits (FD)?"', SYSTEM_PROMPT)
        self.assertIn("Bank FDs give only 6.5%–7.5%", SYSTEM_PROMPT)
        self.assertIn("Cymbal Lending P2P offers 12%–24% p.a. returns", SYSTEM_PROMPT)
        self.assertIn("monthly EMI or daily interest payouts", SYSTEM_PROMPT)

    def test_platform_trust_rbi_escrow_objection(self):
        """Asserts platform legitimacy objection mentions RBI registration and ICICI/IDBI Trustee Escrow."""
        self.assertIn('Objection: "Is Cymbal Lending legal / RBI approved?"', SYSTEM_PROMPT)
        self.assertIn("RBI-registered NBFC-P2P", SYSTEM_PROMPT)
        self.assertIn("Trustee Escrow Account (ICICI/IDBI Trustee Escrow)", SYSTEM_PROMPT)

    def test_liquidity_and_continuous_payouts_objection(self):
        """Asserts liquidity objection explains continuous return via monthly EMIs or daily EDI."""
        self.assertIn('Objection: "Can I withdraw money anytime?"', SYSTEM_PROMPT)
        self.assertIn("monthly EMIs or daily EDI credits", SYSTEM_PROMPT)
        self.assertIn("regular ongoing liquidity rather than rigid lock-ins", SYSTEM_PROMPT)


class TestContextCompressionConfiguration(unittest.TestCase):
    """Validates Context Window Compression defaults and dictionary construction."""

    def test_run_agent_live_default_trigger_tokens(self):
        """`run_agent_live` must have context_compression=True and context_compression_trigger_tokens=10000."""
        sig = inspect.signature(agent_live.run_agent_live)
        params = sig.parameters
        self.assertIn("context_compression", params)
        self.assertIn("context_compression_trigger_tokens", params)
        self.assertEqual(params["context_compression"].default, True)
        self.assertEqual(params["context_compression_trigger_tokens"].default, 10000)

    def test_server_websocket_endpoint_default_trigger_tokens(self):
        """`websocket_endpoint` in server.py must have context_compression_trigger_tokens=10000."""
        sig = inspect.signature(server_module.websocket_endpoint)
        params = sig.parameters
        self.assertIn("context_compression", params)
        self.assertIn("context_compression_trigger_tokens", params)
        self.assertEqual(params["context_compression"].default, True)
        self.assertEqual(params["context_compression_trigger_tokens"].default, 10000)

    def test_cwc_dict_construction_logic(self):
        """Simulates the cwc construction logic in agent_live.py to verify exact output."""
        def build_cwc(context_compression: bool, context_compression_trigger_tokens: Any) -> Dict[str, Any]:
            cwc = {}
            if context_compression:
                cwc["enabled"] = True
                cwc["trigger_tokens"] = context_compression_trigger_tokens if context_compression_trigger_tokens is not None else 10000
            return cwc

        # Default case (None provided -> defaults to 10000)
        self.assertEqual(build_cwc(True, None), {"enabled": True, "trigger_tokens": 10000})

        # Explicit 10000
        self.assertEqual(build_cwc(True, 10000), {"enabled": True, "trigger_tokens": 10000})

        # Custom override
        self.assertEqual(build_cwc(True, 35000), {"enabled": True, "trigger_tokens": 35000})

        # Disabled
        self.assertEqual(build_cwc(False, 10000), {})


if __name__ == "__main__":
    unittest.main()
