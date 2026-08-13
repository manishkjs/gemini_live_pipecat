"""Unit tests for Cymbal Lending financial calculation tools (standard unittest)."""

import unittest
import sys
import os

# Add server directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.financial_math import (
    calculate_stl_returns,
    calculate_mtl_returns,
    calculate_manual_lending,
    calculate_sip_returns,
    get_product_recommendation,
)
from tools.navigation import get_kyc_guidance, get_app_screen_flow


class TestFinancialMath(unittest.TestCase):

    def test_stl_returns_5m(self):
        # 50,000 for 4 months (STL 5M @ 15% XIRR)
        res = calculate_stl_returns(50000, 4)
        self.assertEqual(res["product_name"], "STL 5M")
        self.assertEqual(res["annualized_xirr_pct"], 15.0)
        self.assertEqual(res["principal"], 50000)
        self.assertEqual(res["tenure_months"], 4)
        # Profit = 50000 * 0.15 * (4/12) = 2500
        self.assertEqual(res["profit_rupees"], 2500.0)
        self.assertEqual(res["final_maturity_amount"], 52500.0)

    def test_stl_returns_7m(self):
        # 50,000 for 6 months (STL 7M @ 18% XIRR)
        res = calculate_stl_returns(50000, 6)
        self.assertEqual(res["product_name"], "STL 7M")
        self.assertEqual(res["annualized_xirr_pct"], 18.0)
        self.assertEqual(res["principal"], 50000)
        self.assertEqual(res["tenure_months"], 6)
        # Profit = 50000 * 0.18 * (6/12) = 4500
        self.assertEqual(res["profit_rupees"], 4500.0)
        self.assertEqual(res["final_maturity_amount"], 54500.0)

    def test_stl_limits(self):
        # Below ₹25,000 minimum
        res_low = calculate_stl_returns(10000, 4)
        self.assertIn("error", res_low)

        # Above ₹25,00,000 maximum
        res_high = calculate_stl_returns(3000000, 4)
        self.assertIn("error", res_high)

    def test_mtl_monthly_returns(self):
        # 1,00,000 for 12 months Monthly EMI @ 24% XIRR
        res = calculate_mtl_returns(100000, "monthly")
        self.assertEqual(res["product_name"], "MTL 14M Monthly (EMI)")
        self.assertEqual(res["annualized_xirr_pct"], 24.0)
        self.assertEqual(res["profit_rupees"], 24000.0)
        self.assertEqual(res["final_maturity_amount"], 124000.0)

    def test_mtl_daily_returns(self):
        # 1,00,000 for 12 months Daily EDI @ 18% XIRR
        res = calculate_mtl_returns(100000, "daily")
        self.assertEqual(res["product_name"], "MTL 14M Daily (EDI)")
        self.assertEqual(res["annualized_xirr_pct"], 18.0)
        self.assertEqual(res["profit_rupees"], 18000.0)
        self.assertEqual(res["final_maturity_amount"], 118000.0)

    def test_manual_lending_standard(self):
        # 50,000 for 6 months standard @ 18% XIRR
        res = calculate_manual_lending(50000, 6)
        self.assertEqual(res["annualized_xirr_pct"], 18.0)
        self.assertEqual(res["profit_rupees"], 4500.0)

        # 1,00,000 for 12 months standard @ 24% XIRR
        res_12 = calculate_manual_lending(100000, 12)
        self.assertEqual(res_12["annualized_xirr_pct"], 24.0)
        self.assertEqual(res_12["profit_rupees"], 24000.0)

    def test_manual_lending_custom_portfolio_rule_4(self):
        # 1,00,000 for 12 months with 40% borrower interest and 5% NPA
        # Step A: Principal = 100,000
        # Step B: NPA Loss = 100,000 * 5% = 5,000
        # Step C: Performing Principal = 95,000
        # Step D: Gross Interest = 95,000 * 40% * (12/12) = 38,000
        # Step E: Platform Fee = 100,000 * 6% = 6,000
        # Step F: Net Profit = 38,000 - 6,000 - 5,000 = 27,000
        # Step G: Net ROI = (27,000 / 100,000) * 100 = 27.0%
        res = calculate_manual_lending(
            amount=100000,
            tenure_months=12,
            custom_borrower_rate_pct=40.0,
            custom_npa_rate_pct=5.0,
        )
        self.assertEqual(res["step_a_principal"], 100000.0)
        self.assertEqual(res["step_b_npa_loss_rupees"], 5000.0)
        self.assertEqual(res["step_c_performing_principal"], 95000.0)
        self.assertEqual(res["step_d_gross_interest"], 38000.0)
        self.assertEqual(res["step_e_platform_fee_rupees"], 6000.0)
        self.assertEqual(res["step_f_net_profit_rupees"], 27000.0)
        self.assertEqual(res["step_g_net_annualized_roi_pct"], 27.0)
        self.assertEqual(res["final_total_amount"], 127000.0)

    def test_product_recommendation(self):
        # 9-month tenure should be rejected as unavailable
        res_9m = get_product_recommendation(50000, "medium", 9)
        self.assertFalse(res_9m["is_valid"])

        # Low risk 12-month should recommend MTL Daily
        res_low = get_product_recommendation(100000, "low", 12)
        self.assertEqual(res_low["recommended_product"], "MTL 14M Daily (EDI)")

        # Medium risk 12-month should recommend MTL Monthly
        res_med = get_product_recommendation(100000, "medium", 12)
        self.assertEqual(res_med["recommended_product"], "MTL 14M Monthly (EMI)")

        # Short term 6-month should recommend STL 7M
        res_stl = get_product_recommendation(50000, "medium", 6)
        self.assertEqual(res_stl["recommended_product"], "STL 7M")

    def test_sip_returns(self):
        # 5,000 per month for 3 years at 12% p.a. (Annuity due / start-of-month compounding)
        # r = 12 / (12 * 100) = 0.01, n = 36
        # maturity = 5000 * (((1.01)^36 - 1) / 0.01) * 1.01 = 217,538.24
        res = calculate_sip_returns(5000, 12.0, 3)
        self.assertEqual(res["total_invested_rupees"], 180000.0)
        self.assertAlmostEqual(res["maturity_value_rupees"], 217538.24, places=1)
        self.assertAlmostEqual(res["wealth_gained_rupees"], 37538.24, places=1)

        # 0% interest rate SIP
        res_zero = calculate_sip_returns(5000, 0.0, 3)
        self.assertEqual(res_zero["total_invested_rupees"], 180000.0)
        self.assertEqual(res_zero["maturity_value_rupees"], 180000.0)
        self.assertEqual(res_zero["wealth_gained_rupees"], 0.0)

    def test_sip_invalid_inputs(self):
        self.assertIn("error", calculate_sip_returns(0, 12.0, 3))
        self.assertIn("error", calculate_sip_returns(5000, 12.0, 0))
        self.assertIn("error", calculate_sip_returns(5000, -5.0, 3))

    def test_manual_lending_validation(self):
        # Non-positive tenure
        self.assertIn("error", calculate_manual_lending(50000, 0))
        self.assertIn("error", calculate_manual_lending(50000, -2))

        # Negative borrower rate or invalid NPA rate
        self.assertIn("error", calculate_manual_lending(50000, 12, custom_borrower_rate_pct=-5))
        self.assertIn("error", calculate_manual_lending(50000, 12, custom_borrower_rate_pct=30, custom_npa_rate_pct=-1))
        self.assertIn("error", calculate_manual_lending(50000, 12, custom_borrower_rate_pct=30, custom_npa_rate_pct=150))

    def test_product_recommendation_limits(self):
        # Under ₹250 platform minimum
        res_under = get_product_recommendation(100)
        self.assertFalse(res_under["is_valid"])

        # Over ₹50L platform limit
        res_over = get_product_recommendation(6000000)
        self.assertFalse(res_over["is_valid"])

    def test_navigation_guidance(self):
        pan_guide = get_kyc_guidance("pan")
        self.assertIn("PAN", pan_guide["step"])

        deposit_guide = get_app_screen_flow("deposit")
        self.assertIn("Funds", deposit_guide["flow_name"])

    def test_none_input_resilience(self):
        # Tools must never raise AttributeError when passed None for optional string params
        mtl_res = calculate_mtl_returns(100000, None)
        self.assertEqual(mtl_res["product_name"], "MTL 14M Monthly (EMI)")

        rec_res = get_product_recommendation(50000, None)
        self.assertTrue(rec_res["is_valid"])

        kyc_res = get_kyc_guidance(None)
        self.assertIn("3-Step", kyc_res["step"])

        flow_res = get_app_screen_flow(None)
        self.assertIn("General App Navigation", flow_res["flow_name"])

    def test_manual_lending_unsupported_tenures(self):
        # 9-month tenure strictly unavailable
        res_9m = calculate_manual_lending(50000, 9)
        self.assertIn("error", res_9m)
        self.assertIn("9-month", res_9m["error"])

        # Non-standard tenures (e.g. 1 month or 8 months) rejected
        res_1m = calculate_manual_lending(50000, 1)
        self.assertIn("error", res_1m)

        res_8m = calculate_manual_lending(50000, 8)
        self.assertIn("error", res_8m)

    def test_stl_default_tenure(self):
        res_default = calculate_stl_returns(50000, None)
        self.assertEqual(res_default["product_name"], "STL 7M")
        self.assertEqual(res_default["tenure_months"], 5)
        self.assertEqual(res_default["annualized_xirr_pct"], 18.0)

    def test_mtl_limits(self):
        # Under ₹1,00,000 minimum
        self.assertIn("error", calculate_mtl_returns(50000, "monthly"))
        # Over ₹10,00,000 maximum for Monthly
        self.assertIn("error", calculate_mtl_returns(1500000, "monthly"))
        # Within ₹25,00,000 for Daily
        res_daily_ok = calculate_mtl_returns(2000000, "daily")
        self.assertEqual(res_daily_ok["product_name"], "MTL 14M Daily (EDI)")
        # Over ₹25,00,000 maximum for Daily
        self.assertIn("error", calculate_mtl_returns(3000000, "daily"))

    def test_manual_lending_all_fee_tiers(self):
        # Fee schedule: 2m -> 1%, 3m -> 1%, 4m -> 4%, 5m -> 4%, 6m -> 3%, 12m -> 6%
        expected_fees = {2: 1.0, 3: 1.0, 4: 4.0, 5: 4.0, 6: 3.0, 12: 6.0}
        for tenure, fee in expected_fees.items():
            res = calculate_manual_lending(
                amount=100000,
                tenure_months=tenure,
                custom_borrower_rate_pct=30.0,
                custom_npa_rate_pct=0.0,
            )
            self.assertEqual(res["platform_fee_pct"], fee)
            self.assertEqual(res["step_e_platform_fee_rupees"], 100000 * (fee / 100.0))

    def test_navigation_all_branches(self):
        aadhaar = get_kyc_guidance("aadhaar")
        self.assertIn("Aadhaar", aadhaar["step"])

        bank = get_kyc_guidance("bank")
        self.assertIn("Bank", bank["step"])

        manual_flow = get_app_screen_flow("manual")
        self.assertIn("Manual", manual_flow["flow_name"])

        lumpsum_flow = get_app_screen_flow("lumpsum")
        self.assertIn("Lumpsum", lumpsum_flow["flow_name"])

        filter_flow = get_app_screen_flow("loan filter")
        self.assertIn("App Loan Filter Options", filter_flow["flow_name"])
        self.assertEqual(len(filter_flow["available_filters"]), 8)

    def test_loan_filter_eight_parameters_exact(self):
        expected_filters = [
            "1. Loan Tenure (2, 3, 4, 5, 6, 12 months)",
            "2. Repayment Type (Monthly EMI vs Daily EDI)",
            "3. Risk Category (AAA Low Risk, AA Medium Risk, A High Return, B, C)",
            "4. Borrower Type (Salaried, Self-Employed, Business Owner)",
            "5. Borrower Monthly Income Bracket (e.g. ₹25,000+, ₹50,000+, ₹1,00,000+)",
            "6. Total Loan Amount Requested",
            "7. Remaining Amount to be funded",
            "8. Borrower Age Group (e.g. 21-35, 36-50, 50+)"
        ]

        for query in ["loan filter", "filter", "borrower filter", "LOAN FILTER", " App Loan Filter "]:
            res = get_app_screen_flow(query)
            self.assertEqual(res["flow_name"], "App Loan Filter Options")
            self.assertIn("available_filters", res)
            self.assertEqual(len(res["available_filters"]), 8)
            self.assertEqual(res["available_filters"], expected_filters)
            # Individually assert each parameter
            self.assertEqual(res["available_filters"][0], "1. Loan Tenure (2, 3, 4, 5, 6, 12 months)")
            self.assertEqual(res["available_filters"][1], "2. Repayment Type (Monthly EMI vs Daily EDI)")
            self.assertEqual(res["available_filters"][2], "3. Risk Category (AAA Low Risk, AA Medium Risk, A High Return, B, C)")
            self.assertEqual(res["available_filters"][3], "4. Borrower Type (Salaried, Self-Employed, Business Owner)")
            self.assertEqual(res["available_filters"][4], "5. Borrower Monthly Income Bracket (e.g. ₹25,000+, ₹50,000+, ₹1,00,000+)")
            self.assertEqual(res["available_filters"][5], "6. Total Loan Amount Requested")
            self.assertEqual(res["available_filters"][6], "7. Remaining Amount to be funded")
            self.assertEqual(res["available_filters"][7], "8. Borrower Age Group (e.g. 21-35, 36-50, 50+)")
            self.assertIn("instructions_hinglish", res)
            self.assertIn("8 exact options", res["instructions_hinglish"])

    def test_kyc_guidance_all_steps_and_variations(self):
        # Step 1: PAN Verification
        for pan_query in ["pan", "PAN", "pan card", "PAN Verification", " My PAN "]:
            pan_res = get_kyc_guidance(pan_query)
            self.assertEqual(pan_res["step"], "PAN Verification")
            self.assertIn("10-digit PAN", pan_res["instructions_hinglish"])
            self.assertIn("Original PAN Card photo", pan_res["requirements"])

        # Step 2: Aadhaar / Address Verification (including 'aadhar' spelling variant)
        for aadhaar_query in ["aadhaar", "AADHAAR", "aadhar", "Aadhar", "address", "Aadhaar OTP"]:
            aadhaar_res = get_kyc_guidance(aadhaar_query)
            self.assertEqual(aadhaar_res["step"], "Aadhaar / Address Verification")
            self.assertIn("12-digit Aadhaar", aadhaar_res["instructions_hinglish"])
            self.assertIn("Digilocker", aadhaar_res["instructions_hinglish"])
            self.assertIn("Mobile number must be linked with Aadhaar for OTP", aadhaar_res["requirements"])

        # Step 3: Bank Account Linking & Penny Drop
        for bank_query in ["bank", "BANK", "penny", "penny_drop", "penny drop", "account", "bank linking"]:
            bank_res = get_kyc_guidance(bank_query)
            self.assertEqual(bank_res["step"], "Bank Account Linking")
            self.assertIn("Penny drop", bank_res["instructions_hinglish"])
            self.assertIn("₹1", bank_res["instructions_hinglish"])
            self.assertIn("Bank account name must match PAN card name", bank_res["requirements"])

        # 3-Step Complete KYC Overview
        for overview_query in ["all", "ALL", "", None, "kyc", "overview", "complete"]:
            overview_res = get_kyc_guidance(overview_query)
            self.assertEqual(overview_res["step"], "Complete KYC 3-Step Overview")
            self.assertIn("3 simple steps", overview_res["instructions_hinglish"])
            self.assertIn("PAN card", overview_res["instructions_hinglish"])
            self.assertIn("Digilocker", overview_res["instructions_hinglish"])
            self.assertIn("penny-drop", overview_res["instructions_hinglish"])
            self.assertIn("requirements", overview_res)

    def test_app_screen_flow_all_navigation_routes(self):
        # Deposit Flow
        for dep_query in ["deposit", "DEPOSIT", "fund", "add money", "pay", " Add Money "]:
            dep_res = get_app_screen_flow(dep_query)
            self.assertEqual(dep_res["flow_name"], "Adding Funds to Cymbal Escrow Wallet")
            self.assertIn("Add Funds", dep_res["instructions_hinglish"])
            self.assertIn("₹250", dep_res["instructions_hinglish"])
            self.assertIn("₹25,000", dep_res["instructions_hinglish"])
            self.assertIn("UPI", dep_res["instructions_hinglish"])
            self.assertIn("NetBanking", dep_res["instructions_hinglish"])
            self.assertIn("Escrow", dep_res["instructions_hinglish"])

        # Lumpsum Flow (STL / MTL)
        for lump_query in ["lumpsum", "LUMPSUM", "stl", "mtl", "stl 5m", "mtl 14m"]:
            lump_res = get_app_screen_flow(lump_query)
            self.assertEqual(lump_res["flow_name"], "Lumpsum Lending (STL / MTL)")
            self.assertIn("Lumpsum Plans", lump_res["instructions_hinglish"])
            self.assertIn("STL 5M", lump_res["instructions_hinglish"])
            self.assertIn("STL 7M", lump_res["instructions_hinglish"])
            self.assertIn("MTL 14M", lump_res["instructions_hinglish"])
            self.assertIn("100+ verified borrowers", lump_res["instructions_hinglish"])

        # Manual Lending Flow
        for man_query in ["manual", "MANUAL", "manual lending", " Manual "]:
            man_res = get_app_screen_flow(man_query)
            self.assertEqual(man_res["flow_name"], "Manual Lending Selection")
            self.assertIn("Manual Lending", man_res["instructions_hinglish"])
            self.assertIn("₹250 se ₹4,000", man_res["instructions_hinglish"])
            self.assertIn("A, AA, AAA", man_res["instructions_hinglish"])

        # General / Default Navigation Flow
        for gen_query in ["general", "GENERAL", "", None, "dashboard", "home", "portfolio"]:
            gen_res = get_app_screen_flow(gen_query)
            self.assertEqual(gen_res["flow_name"], "General App Navigation")
            self.assertIn("Dashboard", gen_res["instructions_hinglish"])
            self.assertIn("Invest", gen_res["instructions_hinglish"])
            self.assertIn("Portfolio / Statement", gen_res["instructions_hinglish"])


if __name__ == "__main__":
    unittest.main()

