"""Adversarial stress test harness for get_kyc_guidance (Milestone 2 Challenger 2)."""

import unittest
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.navigation import get_kyc_guidance


class TestKycGuidanceStress(unittest.TestCase):
    """Adversarial stress testing for get_kyc_guidance."""

    def test_required_queries_execution_and_fields(self):
        """Test all 22 required queries from prompt specification."""
        queries_with_expected_behavior = [
            ("pan", "PAN Verification", True),
            ("PAN", "PAN Verification", True),
            ("pan_card", "PAN Verification", True),
            ("aadhaar", "Aadhaar / Address Verification", True),
            ("AADHAAR", "Aadhaar / Address Verification", True),
            ("aadhar", "Aadhaar / Address Verification", True),
            ("AADHAR", "Aadhaar / Address Verification", True),
            ("digilocker", "Complete KYC 3-Step Overview", True),  # Falls through to overview
            ("otp", "Complete KYC 3-Step Overview", True),         # Falls through to overview
            ("address", "Aadhaar / Address Verification", True),
            ("bank", "Bank Account Linking", True),
            ("BANK", "Bank Account Linking", True),
            ("penny", "Bank Account Linking", True),
            ("penny_drop", "Bank Account Linking", True),
            ("account", "Bank Account Linking", True),
            ("ifsc", "Complete KYC 3-Step Overview", True),        # Falls through to overview
            ("all", "Complete KYC 3-Step Overview", True),
            ("", "Complete KYC 3-Step Overview", True),
            (None, "Complete KYC 3-Step Overview", True),
            ([], "Complete KYC 3-Step Overview", True),
            ("random_query", "Complete KYC 3-Step Overview", True),
        ]

        for query, expected_step, should_succeed in queries_with_expected_behavior:
            with self.subTest(query=query):
                res = get_kyc_guidance(query)
                self.assertIsInstance(res, dict)
                # Field presence checks
                self.assertIn("step", res)
                self.assertIn("instructions_hinglish", res)
                self.assertIn("requirements", res)
                self.assertIsInstance(res["step"], str)
                self.assertIsInstance(res["instructions_hinglish"], str)
                self.assertIsInstance(res["requirements"], str)
                self.assertTrue(len(res["step"]) > 0)
                self.assertTrue(len(res["instructions_hinglish"]) > 0)
                self.assertTrue(len(res["requirements"]) > 0)
                self.assertEqual(res["step"], expected_step)

    def test_non_string_numeric_input_behavior(self):
        """Expose vulnerability with numeric and non-string truthy inputs."""
        non_string_truthy = [123, 45.67, True, [1, 2], {"key": "val"}]
        for val in non_string_truthy:
            with self.subTest(val=val):
                with self.assertRaises(AttributeError):
                    get_kyc_guidance(val)

        # Falsy non-string inputs that default to 'all' via 'or'
        falsy_inputs = [0, False, [], {}, set()]
        for val in falsy_inputs:
            with self.subTest(val=val):
                res = get_kyc_guidance(val)
                self.assertEqual(res["step"], "Complete KYC 3-Step Overview")

    def test_accurate_guidance_pan(self):
        """Verify accurate guidance for PAN: 10-digit PAN + photo."""
        res = get_kyc_guidance("pan")
        self.assertEqual(res["step"], "PAN Verification")
        self.assertIn("10-digit PAN", res["instructions_hinglish"])
        self.assertIn("photo", res["instructions_hinglish"].lower())
        self.assertIn("photo", res["requirements"].lower())
        self.assertIn("Original PAN Card", res["requirements"])

    def test_accurate_guidance_aadhaar(self):
        """Verify accurate guidance for Aadhaar: Digilocker 12-digit + OTP."""
        for query in ["aadhaar", "aadhar", "address"]:
            res = get_kyc_guidance(query)
            self.assertEqual(res["step"], "Aadhaar / Address Verification")
            self.assertIn("Digilocker", res["instructions_hinglish"])
            self.assertIn("12-digit Aadhaar", res["instructions_hinglish"])
            self.assertIn("OTP", res["instructions_hinglish"])
            self.assertIn("OTP", res["requirements"])
            self.assertIn("linked with Aadhaar", res["requirements"])

    def test_accurate_guidance_bank(self):
        """Verify accurate guidance for Bank: penny drop ₹1 deposit + IFSC."""
        for query in ["bank", "account", "penny", "penny_drop"]:
            res = get_kyc_guidance(query)
            self.assertEqual(res["step"], "Bank Account Linking")
            self.assertIn("₹1", res["instructions_hinglish"])
            self.assertIn("Penny drop", res["instructions_hinglish"])
            self.assertIn("IFSC Code", res["instructions_hinglish"])
            self.assertIn("Bank Account Number", res["instructions_hinglish"])
            self.assertIn("PAN card name", res["requirements"])

    def test_complete_kyc_overview_accuracy(self):
        """Verify accurate 3-step overview for general KYC query."""
        for query in ["all", "", None, "kyc"]:
            res = get_kyc_guidance(query)
            self.assertEqual(res["step"], "Complete KYC 3-Step Overview")
            self.assertIn("3 simple steps", res["instructions_hinglish"])
            self.assertIn("1. PAN card", res["instructions_hinglish"])
            self.assertIn("2. Digilocker", res["instructions_hinglish"])
            self.assertIn("3. Apna bank account number", res["instructions_hinglish"])
            self.assertIn("penny-drop", res["instructions_hinglish"])
            self.assertIn("PAN Card", res["requirements"])
            self.assertIn("Active Bank Account", res["requirements"])

    def test_whitespace_and_case_insensitivity(self):
        """Verify robustness against case and whitespace variations."""
        cases = [
            ("   PAN   ", "PAN Verification"),
            ("\tpan_card\n", "PAN Verification"),
            ("   AADHAAR\t", "Aadhaar / Address Verification"),
            ("   aadhar   ", "Aadhaar / Address Verification"),
            ("  BANK ACCOUNT  ", "Bank Account Linking"),
            ("  PENNY_DROP  ", "Bank Account Linking"),
            ("   \t\n   ", "Complete KYC 3-Step Overview"),
        ]
        for query, expected_step in cases:
            with self.subTest(query=query):
                res = get_kyc_guidance(query)
                self.assertEqual(res["step"], expected_step)

    def test_subword_and_sentence_context(self):
        """Verify that natural sentence queries route to correct steps."""
        cases = [
            ("Please guide me on how to upload my PAN card", "PAN Verification"),
            ("How do I complete my aadhaar verification via digilocker?", "Aadhaar / Address Verification"),
            ("How does the penny drop bank account linking work?", "Bank Account Linking"),
            ("What are the full KYC requirements?", "Complete KYC 3-Step Overview"),
        ]
        for query, expected_step in cases:
            with self.subTest(query=query):
                res = get_kyc_guidance(query)
                self.assertEqual(res["step"], expected_step)

    def test_keyword_precedence(self):
        """Verify deterministic branch precedence when multiple keywords appear."""
        # 'pan' is checked first in if "pan" in query
        res_pan_aadhaar = get_kyc_guidance("pan and aadhaar")
        self.assertEqual(res_pan_aadhaar["step"], "PAN Verification")

        # 'aadhaar' is checked before 'bank'
        res_aadhaar_bank = get_kyc_guidance("aadhaar and bank")
        self.assertEqual(res_aadhaar_bank["step"], "Aadhaar / Address Verification")

    def test_large_input_and_performance(self):
        """Verify performance and memory stability on 10,000 iterations and large payload."""
        large_query = "pan " * 5000
        start = time.perf_counter()
        res_large = get_kyc_guidance(large_query)
        self.assertEqual(res_large["step"], "PAN Verification")

        # 10,000 queries throughput test
        t0 = time.perf_counter()
        for i in range(10000):
            q = "pan" if i % 3 == 0 else ("aadhaar" if i % 3 == 1 else "bank")
            get_kyc_guidance(q)
        t1 = time.perf_counter()
        total_time = t1 - t0
        self.assertLess(total_time, 0.5)  # 10k calls in < 500ms


if __name__ == "__main__":
    unittest.main()
