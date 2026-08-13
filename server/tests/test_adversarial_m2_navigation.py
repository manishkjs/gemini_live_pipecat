"""Adversarial stress test suite for Milestone 2: App Screen Flow & Loan Filter Navigation.

Author: Challenger 1 (M2)
Scope:
1. Target flow string edge cases for get_app_screen_flow:
   - 'loan filter', 'Loan Filter', 'LOAN_FILTER', 'filter', 'borrower filter'
   - 'deposit', 'DEPOSIT', 'fund', 'add money', 'pay'
   - 'lumpsum', 'stl', 'mtl', 'STL', 'MTL', 'stl 5m', 'mtl 14m'
   - 'manual', 'MANUAL', 'manual lending'
   - 'general', '', None, 'xyz123', 'random_invalid_string'
   - Non-string inputs: 123, [], [1, 2], {}, True, False, 3.14
2. Verification of exact 8 loan filter parameters for any filter query.
3. Schema & Key verification: 'flow_name', 'instructions_hinglish', 'available_filters'.
4. Fuzzing with 10,000 random generated inputs.
5. Large payload / string stress testing (100,000 characters).
6. Performance & Latency benchmarks (100,000 iterations).
7. Async tool handler integration verification in agent_live.
8. KYC guidance verification for 3-step process (PAN, Aadhaar, Bank penny-drop, Overview).
"""

import unittest
import sys
import os
import time
import random
import string
from typing import Dict, Any, List
from unittest.mock import MagicMock

# Mock out Vertex AI and Silero VAD so tests run standalone
for mod in [
    "vertexai",
    "vertexai.preview",
    "vertexai.preview.rag",
    "pipecat.audio.vad.silero",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Add server directory to sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from tools.navigation import get_app_screen_flow, get_kyc_guidance


class MockFunctionCallParams:
    """Mock for Pipecat FunctionCallParams to test async handler layer."""
    def __init__(self, arguments: Dict[str, Any]):
        self.arguments = arguments
        self.result = None

    async def result_callback(self, res: Any):
        self.result = res


class TestAdversarialM2Navigation(unittest.TestCase):
    """Adversarial challenger test suite for get_app_screen_flow and navigation tools."""

    EXPECTED_8_FILTERS = [
        "1. Loan Tenure (2, 3, 4, 5, 6, 12 months)",
        "2. Repayment Type (Monthly EMI vs Daily EDI)",
        "3. Risk Category (AAA Low Risk, AA Medium Risk, A High Return, B, C)",
        "4. Borrower Type (Salaried, Self-Employed, Business Owner)",
        "5. Borrower Monthly Income Bracket (e.g. ₹25,000+, ₹50,000+, ₹1,00,000+)",
        "6. Total Loan Amount Requested",
        "7. Remaining Amount to be funded",
        "8. Borrower Age Group (e.g. 21-35, 36-50, 50+)"
    ]

    # =========================================================================
    # 1. EXACT 8 LOAN FILTER PARAMETERS VERIFICATION
    # =========================================================================

    def test_filter_flow_exact_8_parameters(self):
        """Verify that all variations of filter query return the exact 8 loan filter parameters."""
        filter_queries = [
            "loan filter",
            "Loan Filter",
            "LOAN_FILTER",
            "filter",
            "borrower filter",
            "BORROWER FILTER",
            "loan filters",
            "  loan filter  ",
            "\t\nloan filter\n\t",
            "What exact options are available in the app loan filter?",
            "app loan filter options",
            "filter borrowers",
            "filter loans"
        ]

        for query in filter_queries:
            res = get_app_screen_flow(query)
            self.assertIsInstance(res, dict, f"Query '{query}' did not return dict")
            self.assertEqual(res.get("flow_name"), "App Loan Filter Options", f"Mismatch flow_name for '{query}'")
            self.assertIn("available_filters", res, f"Missing available_filters for '{query}'")
            self.assertIn("instructions_hinglish", res, f"Missing instructions_hinglish for '{query}'")
            
            filters = res["available_filters"]
            self.assertIsInstance(filters, list)
            self.assertEqual(len(filters), 8, f"Available filters count != 8 for '{query}' (got {len(filters)})")
            self.assertEqual(filters, self.EXPECTED_8_FILTERS, f"Filters do not match expected 8 list for '{query}'")
            
            # Verify each individual filter item verbatim
            self.assertEqual(filters[0], "1. Loan Tenure (2, 3, 4, 5, 6, 12 months)")
            self.assertEqual(filters[1], "2. Repayment Type (Monthly EMI vs Daily EDI)")
            self.assertEqual(filters[2], "3. Risk Category (AAA Low Risk, AA Medium Risk, A High Return, B, C)")
            self.assertEqual(filters[3], "4. Borrower Type (Salaried, Self-Employed, Business Owner)")
            self.assertEqual(filters[4], "5. Borrower Monthly Income Bracket (e.g. ₹25,000+, ₹50,000+, ₹1,00,000+)")
            self.assertEqual(filters[5], "6. Total Loan Amount Requested")
            self.assertEqual(filters[6], "7. Remaining Amount to be funded")
            self.assertEqual(filters[7], "8. Borrower Age Group (e.g. 21-35, 36-50, 50+)")

    # =========================================================================
    # 2. TARGET FLOW STRINGS & ROUTING VERIFICATION
    # =========================================================================

    def test_deposit_flow_routing(self):
        """Verify deposit flow variations."""
        deposit_queries = [
            "deposit", "DEPOSIT", "Deposit", "fund", "FUND", "funds",
            "add money", "ADD MONEY", "Add Money", "pay", "PAY",
            "how to deposit funds", "add money to escrow wallet", "fund account"
        ]
        for query in deposit_queries:
            res = get_app_screen_flow(query)
            self.assertIsInstance(res, dict)
            self.assertEqual(res.get("flow_name"), "Adding Funds to Cymbal Escrow Wallet", f"Failed for '{query}'")
            self.assertIn("Escrow", res.get("instructions_hinglish", ""))
            self.assertIn("UPI", res.get("instructions_hinglish", ""))
            self.assertIn("NetBanking", res.get("instructions_hinglish", ""))

    def test_lumpsum_flow_routing(self):
        """Verify lumpsum flow variations (STL, MTL, lumpsum)."""
        lumpsum_queries = [
            "lumpsum", "LUMPSUM", "Lumpsum", "stl", "STL", "mtl", "MTL",
            "stl 5m", "mtl 14m", "invest lumpsum", "stl plan", "mtl plan"
        ]
        for query in lumpsum_queries:
            res = get_app_screen_flow(query)
            self.assertIsInstance(res, dict)
            self.assertEqual(res.get("flow_name"), "Lumpsum Lending (STL / MTL)", f"Failed for '{query}'")
            self.assertIn("STL 5M", res.get("instructions_hinglish", ""))
            self.assertIn("STL 7M", res.get("instructions_hinglish", ""))
            self.assertIn("MTL 14M", res.get("instructions_hinglish", ""))

    def test_manual_flow_routing(self):
        """Verify manual lending flow variations."""
        manual_queries = [
            "manual", "MANUAL", "Manual", "manual lending",
            "manual selection", "how to do manual lending"
        ]
        for query in manual_queries:
            res = get_app_screen_flow(query)
            self.assertIsInstance(res, dict)
            self.assertEqual(res.get("flow_name"), "Manual Lending Selection", f"Failed for '{query}'")
            self.assertIn("Manual Lending", res.get("instructions_hinglish", ""))
            self.assertIn("₹250", res.get("instructions_hinglish", ""))

    def test_general_and_fallback_flow_routing(self):
        """Verify general / default / unknown string flow routing."""
        general_queries = [
            "general", "GENERAL", "General", "", "   ", None,
            "xyz123", "random invalid flow", "dashboard", "help",
            "profile", "settings", "unknown_screen"
        ]
        for query in general_queries:
            res = get_app_screen_flow(query)
            self.assertIsInstance(res, dict)
            self.assertEqual(res.get("flow_name"), "General App Navigation", f"Failed for '{query}'")
            self.assertIn("Dashboard", res.get("instructions_hinglish", ""))
            self.assertIn("Invest", res.get("instructions_hinglish", ""))
            self.assertIn("Portfolio / Statement", res.get("instructions_hinglish", ""))

    # =========================================================================
    # 3. SCHEMA INTEGRITY & RETURN TYPES
    # =========================================================================

    def test_schema_integrity_all_branches(self):
        """Verify return type structure and field validity across all possible branches."""
        test_inputs = [
            "loan filter", "deposit", "lumpsum", "manual", "general",
            "", None, "xyz"
        ]
        for inp in test_inputs:
            res = get_app_screen_flow(inp)
            self.assertIsInstance(res, dict)
            self.assertIn("flow_name", res)
            self.assertIsInstance(res["flow_name"], str)
            self.assertTrue(len(res["flow_name"]) > 0)
            self.assertIn("instructions_hinglish", res)
            self.assertIsInstance(res["instructions_hinglish"], str)
            self.assertTrue(len(res["instructions_hinglish"]) > 0)

            if "filter" in (inp or ""):
                self.assertIn("available_filters", res)
                self.assertIsInstance(res["available_filters"], list)
                self.assertEqual(len(res["available_filters"]), 8)
                for f in res["available_filters"]:
                    self.assertIsInstance(f, str)
                    self.assertTrue(len(f) > 0)

    # =========================================================================
    # 4. NON-STRING INPUT PROBING & ASYNC HANDLER RESILIENCE
    # =========================================================================

    def test_direct_non_string_inputs_probing(self):
        """Probe behavior of get_app_screen_flow when called directly with non-string inputs."""
        # Falsy non-string inputs resolve to 'general' via (target_flow or 'general')
        falsy_inputs = [[], {}, False, 0, 0.0]
        for inp in falsy_inputs:
            res = get_app_screen_flow(inp)
            self.assertEqual(res["flow_name"], "General App Navigation")

        # Truthy non-string inputs raise AttributeError if passed directly
        # because (target_flow or 'general') returns target_flow directly.
        truthy_non_strings = [123, [1, 2], {"flow": "filter"}, True, 3.14]
        for inp in truthy_non_strings:
            with self.assertRaises(AttributeError):
                get_app_screen_flow(inp)

    def test_async_handler_wrapper_resilience(self):
        """Verify that agent_live's handle_get_app_screen_flow protects against non-string inputs."""
        import asyncio
        from agent_live import handle_get_app_screen_flow

        async def run_async_test():
            test_args = [
                {"target_flow": "loan filter"},
                {"target_flow": 123},
                {"target_flow": [1, 2]},
                {"target_flow": True},
                {"target_flow": None},
                {},
                {"target_flow": "deposit"},
            ]
            for arg_dict in test_args:
                params = MockFunctionCallParams(arg_dict)
                await handle_get_app_screen_flow(params)
                self.assertIsNotNone(params.result)
                self.assertIsInstance(params.result, dict)
                self.assertIn("flow_name", params.result)

        asyncio.run(run_async_test())

    # =========================================================================
    # 5. KYC GUIDANCE ADVERSARIAL COVERAGE
    # =========================================================================

    def test_kyc_guidance_all_branches(self):
        """Verify KYC guidance branches for PAN, Aadhaar OTP, Bank Penny drop, and 3-step overview."""
        # PAN (keywords: 'pan')
        for q in ["pan", "PAN", "pan card", "PAN PHOTO", "pan verification"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "PAN Verification")
            self.assertIn("PAN", res["instructions_hinglish"])
            self.assertIn("requirements", res)

        # Aadhaar (keywords: 'aadhaar', 'aadhar', 'address')
        for q in ["aadhaar", "AADHAAR", "aadhar", "Aadhar", "address", "aadhaar otp", "my address proof"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "Aadhaar / Address Verification")
            self.assertIn("Digilocker", res["instructions_hinglish"])
            self.assertIn("OTP", res["requirements"])

        # Bank (keywords: 'bank', 'account', 'penny')
        for q in ["bank", "BANK", "penny", "penny drop", "account", "bank account", "penny-drop"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "Bank Account Linking")
            self.assertIn("Penny drop", res["instructions_hinglish"])
            self.assertIn("₹1", res["instructions_hinglish"])

        # Overview / fallback (keywords: 'all', '', None, or unrecognized queries)
        for q in ["all", "", None, "general", "xyz123", "kyc", "complete", "digilocker", "ifsc"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "Complete KYC 3-Step Overview")
            self.assertIn("3 simple steps", res["instructions_hinglish"])

    # =========================================================================
    # 6. ADVERSARIAL FUZZING (10,000 RANDOM INPUTS)
    # =========================================================================

    def test_random_string_fuzzing_10000_iterations(self):
        """Fuzz get_app_screen_flow with 10,000 randomized strings (unicode, control chars, punctuation)."""
        char_pool = string.ascii_letters + string.digits + string.punctuation + " \t\n\r" + "₹अआइईउऊऋएऐओऔकखगघ"
        random.seed(42)

        for i in range(10000):
            length = random.randint(0, 100)
            rand_str = "".join(random.choice(char_pool) for _ in range(length))
            res = get_app_screen_flow(rand_str)
            self.assertIsInstance(res, dict)
            self.assertIn("flow_name", res)
            self.assertIn("instructions_hinglish", res)
            if "filter" in rand_str.lower():
                self.assertEqual(res["flow_name"], "App Loan Filter Options")
                self.assertEqual(len(res["available_filters"]), 8)

    # =========================================================================
    # 7. LARGE PAYLOAD & BOUNDARY STRESS TEST
    # =========================================================================

    def test_extreme_payload_length(self):
        """Stress-test with very large strings (100,000 characters)."""
        large_string = "loan filter " * 10000  # 120,000 chars
        res = get_app_screen_flow(large_string)
        self.assertEqual(res["flow_name"], "App Loan Filter Options")
        self.assertEqual(len(res["available_filters"]), 8)

        large_random = "a" * 100000
        res_rand = get_app_screen_flow(large_random)
        self.assertEqual(res_rand["flow_name"], "General App Navigation")

    # =========================================================================
    # 8. PERFORMANCE & LATENCY BENCHMARK (100,000 INVOCATIONS)
    # =========================================================================

    def test_performance_benchmark_100k_calls(self):
        """Measure latency of 100,000 calls to guarantee zero-latency overhead."""
        queries = ["loan filter", "deposit", "lumpsum", "manual", "general", "xyz", ""]
        num_calls = 100000

        t0 = time.perf_counter()
        for i in range(num_calls):
            q = queries[i % len(queries)]
            get_app_screen_flow(q)
        elapsed_sec = time.perf_counter() - t0

        avg_latency_us = (elapsed_sec / num_calls) * 1_000_000
        print(f"\n[PERF BENCHMARK] 100,000 calls completed in {elapsed_sec:.4f}s ({avg_latency_us:.3f} µs/call)")
        # Must execute within 1.0 second total (< 10 µs per call)
        self.assertLess(elapsed_sec, 1.0, f"100,000 calls took {elapsed_sec:.2f}s, expected < 1.0s")


if __name__ == "__main__":
    unittest.main()
