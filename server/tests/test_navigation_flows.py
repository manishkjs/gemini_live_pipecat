"""Tier 1 and Tier 2 Comprehensive Test Suite for Screen Navigation Flows.

Validates:
- Tier 1 (Feature Tests):
  * get_onboarding_guide routing to KYC vs App screen flows.
  * get_kyc_guidance for PAN, Aadhaar/Digilocker, Bank Account Penny Drop, and 3-step overview.
  * get_app_screen_flow for Escrow UPI/NetBanking wallet deposit, STL/MTL lumpsum investment,
    and the 8 loan filter parameters list.
  * get_consultative_guidance for FD comparison, NPA/Risk, RBI trust, Liquidity.
- Tier 2 (Boundary & Edge Tests):
  * Case insensitivity across inputs ("PAN", "pan", "Pan Card", "AADHAAR", "digilocker", etc.).
  * None, empty string, and missing parameters yielding safe fallback/complete overview.
  * Unknown keywords and random garbage fallback without exceptions.
  * Exact verification of the 8 filter items in available_filters.
"""

import os
import sys
import unittest

# Ensure server directory is on sys.path
server_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from tools.navigation import (
    get_onboarding_guide,
    get_kyc_guidance,
    get_app_screen_flow,
    get_consultative_guidance,
)


class TestNavigationFlowsTier1Feature(unittest.TestCase):
    """Tier 1: Feature tests for onboarding, KYC, and app navigation flows."""

    def test_onboarding_guide_routes_to_kyc_flow(self):
        """Verify get_onboarding_guide routes KYC-related topics to get_kyc_guidance."""
        kyc_topics = ["kyc", "pan", "aadhaar", "bank", "penny drop"]
        for topic in kyc_topics:
            res = get_onboarding_guide(topic)
            self.assertIsInstance(res, dict, f"Expected dict response for topic '{topic}'")
            self.assertIn("step", res, f"Expected 'step' key in KYC response for topic '{topic}'")
            self.assertIn("instructions_hinglish", res)
            self.assertIn("requirements", res)

    def test_onboarding_guide_routes_to_app_screen_flow(self):
        """Verify get_onboarding_guide routes non-KYC topics to get_app_screen_flow."""
        app_topics = ["deposit", "lumpsum", "filter", "manual", "general"]
        for topic in app_topics:
            res = get_onboarding_guide(topic)
            self.assertIsInstance(res, dict, f"Expected dict response for topic '{topic}'")
            self.assertIn("flow_name", res, f"Expected 'flow_name' key in app screen response for topic '{topic}'")
            self.assertIn("instructions_hinglish", res)

    def test_kyc_guidance_pan_step(self):
        """Verify get_kyc_guidance returns accurate PAN verification steps."""
        res = get_kyc_guidance("pan")
        self.assertEqual(res["step"], "PAN Verification")
        self.assertIn("10-digit PAN number", res["instructions_hinglish"])
        self.assertIn("PAN card", res["instructions_hinglish"])
        self.assertIn("Original PAN Card photo", res["requirements"])

    def test_kyc_guidance_aadhaar_digilocker_step(self):
        """Verify get_kyc_guidance returns accurate Aadhaar Digilocker steps."""
        res = get_kyc_guidance("aadhaar")
        self.assertEqual(res["step"], "Aadhaar / Address Verification")
        self.assertIn("Digilocker", res["instructions_hinglish"])
        self.assertIn("OTP", res["instructions_hinglish"])
        self.assertIn("Mobile number must be linked with Aadhaar", res["requirements"])

    def test_kyc_guidance_bank_penny_drop_step(self):
        """Verify get_kyc_guidance returns accurate Bank Account Penny Drop steps."""
        res = get_kyc_guidance("bank")
        self.assertEqual(res["step"], "Bank Account Linking")
        self.assertIn("Penny drop", res["instructions_hinglish"])
        self.assertIn("IFSC Code", res["instructions_hinglish"])
        self.assertIn("Bank account name must match PAN card name", res["requirements"])

    def test_kyc_guidance_complete_overview(self):
        """Verify get_kyc_guidance returns 3-step complete overview when requested."""
        res = get_kyc_guidance("all")
        self.assertEqual(res["step"], "Complete KYC 3-Step Overview")
        self.assertIn("1. PAN card", res["instructions_hinglish"])
        self.assertIn("2. Digilocker", res["instructions_hinglish"])
        self.assertIn("3. Apna bank account", res["instructions_hinglish"])
        self.assertIn("Original PAN Card", res["requirements"])

    def test_app_screen_flow_escrow_deposit(self):
        """Verify get_app_screen_flow returns Escrow UPI/NetBanking wallet deposit instructions."""
        res = get_app_screen_flow("deposit")
        self.assertEqual(res["flow_name"], "Adding Funds to Cymbal Escrow Wallet")
        self.assertIn("UPI ya NetBanking", res["instructions_hinglish"])
        self.assertIn("Escrow account", res["instructions_hinglish"])

    def test_app_screen_flow_lumpsum_investment(self):
        """Verify get_app_screen_flow returns STL/MTL lumpsum investment instructions."""
        res = get_app_screen_flow("lumpsum")
        self.assertEqual(res["flow_name"], "Lumpsum Lending (STL / MTL)")
        self.assertIn("STL 5M", res["instructions_hinglish"])
        self.assertIn("STL 7M", res["instructions_hinglish"])
        self.assertIn("MTL 14M", res["instructions_hinglish"])
        self.assertIn("100+ verified borrowers", res["instructions_hinglish"])

    def test_app_screen_flow_manual_lending(self):
        """Verify get_app_screen_flow returns Manual Lending selection guidance."""
        res = get_app_screen_flow("manual")
        self.assertEqual(res["flow_name"], "Manual Lending Selection")
        self.assertIn("Manual Lending", res["instructions_hinglish"])
        self.assertIn("₹250 se ₹4,000", res["instructions_hinglish"])

    def test_app_screen_flow_loan_filters_eight_items(self):
        """Verify get_app_screen_flow returns exactly 8 filter options for loan filtering."""
        res = get_app_screen_flow("filter")
        self.assertEqual(res["flow_name"], "App Loan Filter Options")
        self.assertIn("available_filters", res)
        filters = res["available_filters"]
        self.assertEqual(len(filters), 8, f"Expected exactly 8 filter options, got {len(filters)}")

        expected_elements = [
            "Loan Tenure",
            "Repayment Type",
            "Risk Category",
            "Borrower Type",
            "Borrower Monthly Income Bracket",
            "Total Loan Amount Requested",
            "Remaining Amount",
            "Borrower Age Group",
        ]
        for element in expected_elements:
            self.assertTrue(
                any(element in f for f in filters),
                f"Expected filter item containing '{element}' in available_filters"
            )

    def test_consultative_guidance_topics(self):
        """Verify get_consultative_guidance returns appropriate talk tracks."""
        fd_res = get_consultative_guidance("fd")
        self.assertEqual(fd_res["topic"], "Bank FD Comparison")
        self.assertIn("6.5% se 7.5%", fd_res["key_points_hinglish"])

        risk_res = get_consultative_guidance("risk")
        self.assertEqual(risk_res["topic"], "Risk & Default Mitigation")
        self.assertIn("100+ vetted borrowers", risk_res["key_points_hinglish"])

        rbi_res = get_consultative_guidance("rbi")
        self.assertEqual(rbi_res["topic"], "Platform Legitimacy & RBI Trust")
        self.assertIn("RBI-registered NBFC-P2P", rbi_res["key_points_hinglish"])

        liq_res = get_consultative_guidance("liquidity")
        self.assertEqual(liq_res["topic"], "Liquidity & Repayment Mechanics")
        self.assertIn("monthly EMIs ya daily EDI credits", liq_res["key_points_hinglish"])


class TestNavigationFlowsTier2Boundary(unittest.TestCase):
    """Tier 2: Boundary value, casing, fallback, and resilience tests."""

    def test_kyc_case_insensitivity_and_variations(self):
        """Verify case insensitivity and varied keywords for KYC lookup."""
        variations = [
            ("PAN", "PAN Verification"),
            ("pan", "PAN Verification"),
            ("Pan Card", "PAN Verification"),
            ("PAN_NUMBER", "PAN Verification"),
            ("AADHAAR", "Aadhaar / Address Verification"),
            ("aadhaar", "Aadhaar / Address Verification"),
            ("aadhar", "Aadhaar / Address Verification"),
            ("Digilocker address", "Aadhaar / Address Verification"),
            ("BANK", "Bank Account Linking"),
            ("Bank Account", "Bank Account Linking"),
            ("penny drop verification", "Bank Account Linking"),
            ("PENNY", "Bank Account Linking"),
        ]
        for query_input, expected_step in variations:
            res = get_kyc_guidance(query_input)
            self.assertEqual(
                res["step"],
                expected_step,
                f"Query '{query_input}' produced '{res['step']}', expected '{expected_step}'"
            )

    def test_app_screen_flow_case_insensitivity(self):
        """Verify case insensitivity and varied keywords for app screen lookup."""
        variations = [
            ("DEPOSIT", "Adding Funds to Cymbal Escrow Wallet"),
            ("Add Money", "Adding Funds to Cymbal Escrow Wallet"),
            ("PAY", "Adding Funds to Cymbal Escrow Wallet"),
            ("fund wallet", "Adding Funds to Cymbal Escrow Wallet"),
            ("LUMPSUM", "Lumpsum Lending (STL / MTL)"),
            ("stl plan", "Lumpsum Lending (STL / MTL)"),
            ("MTL 14M", "Lumpsum Lending (STL / MTL)"),
            ("FILTER", "App Loan Filter Options"),
            ("loan filter", "App Loan Filter Options"),
            ("BORROWER FILTER", "App Loan Filter Options"),
            ("MANUAL", "Manual Lending Selection"),
            ("manual lending", "Manual Lending Selection"),
        ]
        for query_input, expected_flow in variations:
            res = get_app_screen_flow(query_input)
            self.assertEqual(
                res["flow_name"],
                expected_flow,
                f"Query '{query_input}' produced '{res['flow_name']}', expected '{expected_flow}'"
            )

    def test_none_and_empty_topic_parameters(self):
        """Verify None, empty string, and whitespace parameters return safe defaults."""
        # get_kyc_guidance with None / empty returns Complete KYC 3-Step Overview
        self.assertEqual(get_kyc_guidance(None)["step"], "Complete KYC 3-Step Overview")
        self.assertEqual(get_kyc_guidance("")["step"], "Complete KYC 3-Step Overview")
        self.assertEqual(get_kyc_guidance("   ")["step"], "Complete KYC 3-Step Overview")

        # get_onboarding_guide with None / empty routes safely
        res_none = get_onboarding_guide(None)
        self.assertIn("flow_name", res_none)
        self.assertEqual(res_none["flow_name"], "General App Navigation")

        res_empty = get_onboarding_guide("")
        self.assertIn("flow_name", res_empty)

        res_kyc_none = get_onboarding_guide("kyc")
        self.assertEqual(res_kyc_none["step"], "Complete KYC 3-Step Overview")

        # get_app_screen_flow with None / empty
        self.assertEqual(get_app_screen_flow(None)["flow_name"], "General App Navigation")
        self.assertEqual(get_app_screen_flow("")["flow_name"], "General App Navigation")

        # get_consultative_guidance with None / empty
        self.assertEqual(get_consultative_guidance(None)["topic"], "Consultative Sales Journey")
        self.assertEqual(get_consultative_guidance("")["topic"], "Consultative Sales Journey")

    def test_unknown_keywords_fallback_gracefully(self):
        """Verify bizarre or unknown keywords fall back gracefully without raising exceptions."""
        weird_inputs = [
            "quantum_flux_12345",
            "xyz_unknown_topic",
            "!@#$%^&*()_+",
            "1234567890",
            "\t\n\r",
        ]
        for weird in weird_inputs:
            # Should not raise exception
            res_kyc = get_kyc_guidance(weird)
            self.assertEqual(res_kyc["step"], "Complete KYC 3-Step Overview")

            res_app = get_app_screen_flow(weird)
            self.assertEqual(res_app["flow_name"], "General App Navigation")

            res_onboarding = get_onboarding_guide(weird)
            self.assertEqual(res_onboarding["flow_name"], "General App Navigation")

            res_consultative = get_consultative_guidance(weird)
            self.assertEqual(res_consultative["topic"], "Consultative Sales Journey")

    def test_exact_filter_options_content_and_numbering(self):
        """Exhaustively verify each of the 8 filter items in available_filters matches specification."""
        res = get_app_screen_flow("filter")
        filters = res.get("available_filters", [])
        self.assertEqual(len(filters), 8)

        # Exact structure check
        self.assertTrue(filters[0].startswith("1. Loan Tenure"))
        self.assertTrue(filters[1].startswith("2. Repayment Type"))
        self.assertTrue(filters[2].startswith("3. Risk Category"))
        self.assertTrue(filters[3].startswith("4. Borrower Type"))
        self.assertTrue(filters[4].startswith("5. Borrower Monthly Income Bracket"))
        self.assertTrue(filters[5].startswith("6. Total Loan Amount Requested"))
        self.assertTrue(filters[6].startswith("7. Remaining Amount"))
        self.assertTrue(filters[7].startswith("8. Borrower Age Group"))

        # Verify instructions mention 8 exact options
        self.assertIn("8 exact options", res["instructions_hinglish"])


if __name__ == "__main__":
    unittest.main()
