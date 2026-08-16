"""Adversarial Financial Math & Boundary Stress-Testing Suite.
Author: Challenger 2 (Financial Math & Boundary Stress-Testing Specialist)

Empirical Stress Testing for server/tools/financial_math.py:
1. STL (Short Term Lumpsum) Bounds & Tenure Invariants:
   - ₹24,999 (rejected), ₹25,000 (valid), ₹25,00,000 (valid), ₹25,00,001 (rejected), ₹50,00,000 (rejected), ₹0, negative amounts.
   - Tenures: None (default 5m STL 7M @ 18%), 3m, 4m, 5m (STL 5M @ 15%), 6m (STL 7M @ 18%), 1m, 2m, 7m, 8m, 9m (REJECTED!), 12m, 120m.
2. MTL (Medium Term Lumpsum) Bounds & Repayment Invariants:
   - ₹99,999 (rejected), ₹1,00,000 (valid min for both).
   - Monthly EMI cap: ₹10,00,000 (valid), ₹10,00,001 (rejected).
   - Daily EDI cap: ₹25,00,000 (valid), ₹25,00,001 (rejected).
   - Negative amounts, zero amount, string case and whitespace robustness.
3. Manual Lending & Rule 4 Steps A-G High NPA Stress:
   - Amounts: ₹249 (rejected), ₹250 (valid min), ₹50,00,000 (valid max), ₹50,00,001 (rejected), ₹0, negative.
   - Strict 9-month unconditional rejection.
   - Tenures: 2, 3, 4, 5, 6, 12 (valid) vs 0, 1, 7, 8, 9, 10, 11, 13, 120 (rejected).
   - Fee map: 2m->1%, 3m->1%, 4m->4%, 5m->4%, 6m->3%, 12m->6%.
   - Extreme NPA Stress: 0% NPA, 3.5% NPA, 25% NPA, 50% NPA, 75% NPA, 100% NPA (Total default).
   - Rate validation: Negative borrower rate rejected, NPA < 0% rejected, NPA > 100% rejected.
   - Zero division prevention under 100% default rate and negative proceeds handling.
4. SIP Returns Compounding & Boundary Stress:
   - Monthly amount: <= 0 rejected.
   - Duration years: <= 0 rejected.
   - Annual rate: < 0 rejected, 0% rate annuity formula, high rates (50%, 100%).
5. Product Recommendation Funnel & Boundary Routing:
   - Sub-₹250 rejected, Super-₹50L rejected.
   - Sub-₹25k routed to Manual Lending.
   - 9-month tenure unconditionally rejected with guidance.
   - Risk appetite & tenure mappings.
6. Property-Based Fuzzing & Stress Oracle:
   - 2,000 randomized Monte Carlo test cases across amounts, tenures, NPAs, and rates.
   - Asserts 100% crash-free resilience and deterministic schema conformance.
"""

import unittest
import sys
import os
import random
import math
from typing import Dict, Any

# Ensure server is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SERVER_DIR = os.path.join(PROJECT_ROOT, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from tools.financial_math import (
    calculate_stl_returns,
    calculate_mtl_returns,
    calculate_manual_lending,
    calculate_sip_returns,
    get_product_recommendation,
)


class TestStlAdversarialBoundaries(unittest.TestCase):
    """Exhaustive boundary testing for STL (Short Term Lumpsum)."""

    def test_stl_amount_below_min_boundary(self):
        for amt in [0, -1, -25000, 1, 1000, 24999, 24999.99]:
            res = calculate_stl_returns(amt)
            self.assertIn("error", res, f"Expected error for amount {amt}")
            self.assertEqual(res.get("min_amount"), 25000)

    def test_stl_amount_exact_min_boundary(self):
        res = calculate_stl_returns(25000)
        self.assertNotIn("error", res)
        self.assertEqual(res["principal"], 25000)
        self.assertEqual(res["product_name"], "STL 7M")
        self.assertEqual(res["tenure_months"], 5)
        self.assertEqual(res["annualized_xirr_pct"], 18.0)
        expected_profit = round(25000 * 0.18 * (5 / 12.0), 2)
        self.assertEqual(res["profit_rupees"], expected_profit)
        self.assertEqual(res["final_maturity_amount"], round(25000 + expected_profit, 2))
        self.assertEqual(res["monthly_emi_payout"], round((25000 + expected_profit) / 5.0, 2))

    def test_stl_amount_exact_max_boundary(self):
        res = calculate_stl_returns(2500000, 6)
        self.assertNotIn("error", res)
        self.assertEqual(res["principal"], 2500000)
        self.assertEqual(res["product_name"], "STL 7M")
        self.assertEqual(res["tenure_months"], 6)
        expected_profit = round(2500000 * 0.18 * (6 / 12.0), 2)
        self.assertEqual(res["profit_rupees"], 225000.0)
        self.assertEqual(res["final_maturity_amount"], 2725000.0)
        self.assertEqual(res["monthly_emi_payout"], 454166.67)

    def test_stl_amount_above_max_boundary(self):
        for amt in [2500000.01, 2500001, 3000000, 5000000, 100000000]:
            res = calculate_stl_returns(amt)
            self.assertIn("error", res, f"Expected error for amount {amt}")
            self.assertEqual(res.get("max_amount"), 2500000)

    def test_stl_tenure_validation_and_unconditional_rejections(self):
        # Valid tenures
        for t in [3, 4, 5]:
            res = calculate_stl_returns(50000, t)
            self.assertNotIn("error", res)
            self.assertEqual(res["product_name"], "STL 5M")
            self.assertEqual(res["annualized_xirr_pct"], 15.0)
            self.assertEqual(res["tenure_months"], t)

        res_6 = calculate_stl_returns(50000, 6)
        self.assertNotIn("error", res_6)
        self.assertEqual(res_6["product_name"], "STL 7M")
        self.assertEqual(res_6["annualized_xirr_pct"], 18.0)
        self.assertEqual(res_6["tenure_months"], 6)

        # Default when tenure is None
        res_none = calculate_stl_returns(50000, None)
        self.assertEqual(res_none["product_name"], "STL 7M")
        self.assertEqual(res_none["tenure_months"], 5)
        self.assertEqual(res_none["annualized_xirr_pct"], 18.0)

        # Invalid tenures including 1m, 2m, 7m, 8m, 9m, 12m, 120m
        for invalid_t in [-10, -1, 0, 1, 2, 7, 8, 9, 10, 11, 12, 14, 24, 36, 120]:
            res = calculate_stl_returns(50000, invalid_t)
            self.assertIn("error", res, f"Expected rejection for tenure {invalid_t}")
            self.assertEqual(res.get("available_tenures"), [3, 4, 5, 6])


class TestMtlAdversarialBoundaries(unittest.TestCase):
    """Exhaustive boundary testing for MTL (Medium Term Lumpsum 14M)."""

    def test_mtl_amount_below_min_boundary(self):
        for amt in [-100000, 0, 1, 50000, 99999, 99999.99]:
            res = calculate_mtl_returns(amt)
            self.assertIn("error", res)
            self.assertEqual(res.get("min_amount"), 100000)

    def test_mtl_exact_min_boundary(self):
        res_m = calculate_mtl_returns(100000, "monthly")
        self.assertEqual(res_m["product_name"], "MTL 14M Monthly (EMI)")
        self.assertEqual(res_m["annualized_xirr_pct"], 24.0)
        self.assertEqual(res_m["profit_rupees"], 24000.0)
        self.assertEqual(res_m["final_maturity_amount"], 124000.0)
        self.assertEqual(res_m["payout_amount"], round(124000.0 / 12, 2))

        res_d = calculate_mtl_returns(100000, "daily")
        self.assertEqual(res_d["product_name"], "MTL 14M Daily (EDI)")
        self.assertEqual(res_d["annualized_xirr_pct"], 18.0)
        self.assertEqual(res_d["profit_rupees"], 18000.0)
        self.assertEqual(res_d["final_maturity_amount"], 118000.0)
        self.assertEqual(res_d["payout_amount"], round(118000.0 / 365, 2))

    def test_mtl_monthly_max_boundaries(self):
        # Exact max: ₹10,00,000
        res_ok = calculate_mtl_returns(1000000, "monthly")
        self.assertNotIn("error", res_ok)
        self.assertEqual(res_ok["profit_rupees"], 240000.0)
        self.assertEqual(res_ok["final_maturity_amount"], 1240000.0)

        # Above max
        for amt in [1000000.01, 1000001, 1500000, 2500000]:
            res_fail = calculate_mtl_returns(amt, "monthly")
            self.assertIn("error", res_fail)
            self.assertIn("Maximum investment for MTL Monthly is ₹10,00,000", res_fail["error"])

    def test_mtl_daily_max_boundaries(self):
        # Exact max: ₹25,00,000
        res_ok = calculate_mtl_returns(2500000, "daily")
        self.assertNotIn("error", res_ok)
        self.assertEqual(res_ok["profit_rupees"], 450000.0)
        self.assertEqual(res_ok["final_maturity_amount"], 2950000.0)

        # Above max
        for amt in [2500000.01, 2500001, 3000000, 5000000]:
            res_fail = calculate_mtl_returns(amt, "daily")
            self.assertIn("error", res_fail)
            self.assertIn("Maximum investment for MTL Daily is ₹25,00,000", res_fail["error"])

    def test_mtl_repayment_type_string_robustness(self):
        # Test various case, whitespace, substring permutations
        for s in ["daily", "DAILY", "Daily EDI", "  edi  ", "DAILY_EDI"]:
            res = calculate_mtl_returns(200000, s)
            self.assertEqual(res["product_name"], "MTL 14M Daily (EDI)")

        for s in ["monthly", "MONTHLY", "Monthly EMI", " emi ", "emi", None, "", "other"]:
            res = calculate_mtl_returns(200000, s)
            self.assertEqual(res["product_name"], "MTL 14M Monthly (EMI)")


class TestManualLendingAndRule4Stress(unittest.TestCase):
    """Adversarial stress testing for Manual Lending & Rule 4 Steps A-G under high NPA."""

    def test_manual_lending_amount_boundaries(self):
        # Below ₹250
        for amt in [-500, 0, 1, 100, 249, 249.99]:
            res = calculate_manual_lending(amt, 12)
            self.assertIn("error", res)
            self.assertIn("Minimum manual lending amount is ₹250", res["error"])

        # Exact ₹250
        res_min = calculate_manual_lending(250, 12)
        self.assertNotIn("error", res_min)
        self.assertEqual(res_min["principal"], 250.0)
        self.assertEqual(res_min["profit_rupees"], 60.0)
        self.assertEqual(res_min["final_amount"], 310.0)

        # Exact ₹50,00,000 (Platform max limit)
        res_max = calculate_manual_lending(5000000, 12)
        self.assertNotIn("error", res_max)
        self.assertEqual(res_max["principal"], 5000000.0)
        self.assertEqual(res_max["profit_rupees"], 1200000.0)
        self.assertEqual(res_max["final_amount"], 6200000.0)

        # Above ₹50,00,000
        for amt in [5000000.01, 5000001, 6000000, 10000000]:
            res_fail = calculate_manual_lending(amt, 12)
            self.assertIn("error", res_fail)
            self.assertIn("Maximum platform lending limit is ₹50,00,000", res_fail["error"])

    def test_manual_lending_tenure_boundaries_and_strict_9m_rejection(self):
        # 9-month tenure must be unconditionally rejected
        res_9m_std = calculate_manual_lending(50000, 9)
        self.assertIn("error", res_9m_std)
        self.assertIn("9-month tenure is strictly not available", res_9m_std["error"])

        res_9m_custom = calculate_manual_lending(50000, 9, custom_borrower_rate_pct=36.0, custom_npa_rate_pct=4.0)
        self.assertIn("error", res_9m_custom)
        self.assertIn("9-month tenure is strictly not available", res_9m_custom["error"])

        # Other invalid tenures
        for invalid_t in [-10, -1, 0, 1, 7, 8, 10, 11, 13, 14, 24, 36, 120]:
            res = calculate_manual_lending(50000, invalid_t)
            self.assertIn("error", res, f"Expected rejection for tenure {invalid_t}")

        # All valid tenures: 2, 3, 4, 5, 6, 12
        for valid_t in [2, 3, 4, 5, 6, 12]:
            res = calculate_manual_lending(50000, valid_t)
            self.assertNotIn("error", res)
            expected_xirr = 24.0 if valid_t >= 12 else 18.0
            self.assertEqual(res["annualized_xirr_pct"], expected_xirr)

    def test_manual_lending_all_platform_fee_tiers(self):
        # 2m -> 1%, 3m -> 1%, 4m -> 4%, 5m -> 4%, 6m -> 3%, 12m -> 6%
        fee_map = {2: 1.0, 3: 1.0, 4: 4.0, 5: 4.0, 6: 3.0, 12: 6.0}
        for t, expected_fee in fee_map.items():
            res = calculate_manual_lending(100000, t, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=0.0)
            self.assertEqual(res["platform_fee_pct"], expected_fee)
            self.assertEqual(res["step_e_platform_fee_rupees"], 100000 * (expected_fee / 100.0))

    def test_rule_4_standard_worked_example(self):
        # ₹1,00,000 for 12 months with 40% borrower interest and 5% NPA
        # Step A: Principal = 100,000
        # Step B: NPA Loss = 100,000 * 5% = 5,000
        # Step C: Performing Principal = 95,000
        # Step D: Gross Interest = 95,000 * 40% * (12/12) = 38,000
        # Step E: Platform Fee = 100,000 * 6% = 6,000
        # Step F: Net Profit = 38,000 - 6,000 - 5,000 = 27,000
        # Step G: Net ROI = (27,000 / 100,000) * (12/12) * 100 = 27.0%
        res = calculate_manual_lending(100000, 12, custom_borrower_rate_pct=40.0, custom_npa_rate_pct=5.0)
        self.assertEqual(res["step_a_principal"], 100000.0)
        self.assertEqual(res["step_b_npa_loss_rupees"], 5000.0)
        self.assertEqual(res["step_c_performing_principal"], 95000.0)
        self.assertEqual(res["step_d_gross_interest"], 38000.0)
        self.assertEqual(res["step_e_platform_fee_rupees"], 6000.0)
        self.assertEqual(res["step_f_net_profit_rupees"], 27000.0)
        self.assertEqual(res["step_g_net_annualized_roi_pct"], 27.0)
        self.assertEqual(res["final_total_amount"], 127000.0)

    def test_rule_4_high_npa_stress_50_pct(self):
        """Stress test Rule 4 Steps A-G with a massive 50% NPA default rate."""
        # Principal = 100,000, Tenure = 12m, Borrower Rate = 30%, NPA = 50%, Fee = 6%
        # Step A: Principal = 100,000
        # Step B: NPA Loss = 100,000 * 50% = 50,000
        # Step C: Performing = 50,000
        # Step D: Gross Interest = 50,000 * 30% * (12/12) = 15,000
        # Step E: Platform Fee = 100,000 * 6% = 6,000
        # Step F: Net Profit = 15,000 - 6,000 - 50,000 = -41,000 (Negative Profit / Capital Loss)
        # Step G: Net ROI = (-41,000 / 100,000) * 100 = -41.0%
        # Final Total Amount = 100,000 + (-41,000) = 59,000
        res = calculate_manual_lending(100000, 12, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=50.0)
        self.assertEqual(res["step_a_principal"], 100000.0)
        self.assertEqual(res["step_b_npa_loss_rupees"], 50000.0)
        self.assertEqual(res["step_c_performing_principal"], 50000.0)
        self.assertEqual(res["step_d_gross_interest"], 15000.0)
        self.assertEqual(res["step_e_platform_fee_rupees"], 6000.0)
        self.assertEqual(res["step_f_net_profit_rupees"], -41000.0)
        self.assertEqual(res["step_g_net_annualized_roi_pct"], -41.0)
        self.assertEqual(res["final_total_amount"], 59000.0)
        self.assertIn("summary_hinglish", res)

    def test_rule_4_total_default_npa_stress_100_pct(self):
        """Stress test Rule 4 Steps A-G with 100% total default catastrophe (0 performing)."""
        # Principal = 100,000, Tenure = 12m, Borrower Rate = 36%, NPA = 100%, Fee = 6%
        # Step A: Principal = 100,000
        # Step B: NPA Loss = 100,000 * 100% = 100,000
        # Step C: Performing = 0.0 (Zero performing principal)
        # Step D: Gross Interest = 0.0 * 36% = 0.0
        # Step E: Platform Fee = 100,000 * 6% = 6,000
        # Step F: Net Profit = 0.0 - 6,000 - 100,000 = -106,000
        # Step G: Net ROI = (-106,000 / 100,000) * 100 = -106.0%
        # Final Total Amount = 100,000 + (-106,000) = -6,000
        res = calculate_manual_lending(100000, 12, custom_borrower_rate_pct=36.0, custom_npa_rate_pct=100.0)
        self.assertEqual(res["step_a_principal"], 100000.0)
        self.assertEqual(res["step_b_npa_loss_rupees"], 100000.0)
        self.assertEqual(res["step_c_performing_principal"], 0.0)
        self.assertEqual(res["step_d_gross_interest"], 0.0)
        self.assertEqual(res["step_e_platform_fee_rupees"], 6000.0)
        self.assertEqual(res["step_f_net_profit_rupees"], -106000.0)
        self.assertEqual(res["step_g_net_annualized_roi_pct"], -106.0)
        self.assertEqual(res["final_total_amount"], -6000.0)

    def test_rule_4_short_tenure_100_pct_npa_stress(self):
        """Stress test Rule 4 with 100% NPA on short 2-month tenure (1% fee)."""
        # Principal = 50,000, Tenure = 2m, Borrower Rate = 24%, NPA = 100%, Fee = 1%
        # Step A: 50,000
        # Step B: 50,000
        # Step C: 0.0
        # Step D: 0.0
        # Step E: 50,000 * 1% = 500
        # Step F: -50,500
        # Step G: (-50500 / 50000) * (12/2) * 100 = -1.01 * 600 = -606.0%
        res = calculate_manual_lending(50000, 2, custom_borrower_rate_pct=24.0, custom_npa_rate_pct=100.0)
        self.assertEqual(res["step_a_principal"], 50000.0)
        self.assertEqual(res["step_c_performing_principal"], 0.0)
        self.assertEqual(res["step_e_platform_fee_rupees"], 500.0)
        self.assertEqual(res["step_f_net_profit_rupees"], -50500.0)
        self.assertEqual(res["step_g_net_annualized_roi_pct"], -606.0)
        self.assertEqual(res["final_total_amount"], -500.0)

    def test_rule_4_zero_npa_and_zero_rate_boundaries(self):
        # 0% NPA, 0% Borrower Rate
        res = calculate_manual_lending(100000, 6, custom_borrower_rate_pct=0.0, custom_npa_rate_pct=0.0)
        self.assertEqual(res["step_b_npa_loss_rupees"], 0.0)
        self.assertEqual(res["step_c_performing_principal"], 100000.0)
        self.assertEqual(res["step_d_gross_interest"], 0.0)
        self.assertEqual(res["step_e_platform_fee_rupees"], 3000.0)  # 3% for 6m
        self.assertEqual(res["step_f_net_profit_rupees"], -3000.0)
        self.assertEqual(res["step_g_net_annualized_roi_pct"], -6.0)

    def test_rule_4_rate_invalid_input_rejections(self):
        # Negative borrower rate
        res_neg_rate = calculate_manual_lending(50000, 12, custom_borrower_rate_pct=-0.1)
        self.assertIn("error", res_neg_rate)

        # Negative NPA
        res_neg_npa = calculate_manual_lending(50000, 12, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=-0.01)
        self.assertIn("error", res_neg_npa)

        # NPA > 100%
        res_over_npa = calculate_manual_lending(50000, 12, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=100.01)
        self.assertIn("error", res_over_npa)


class TestSipAdversarialBoundaries(unittest.TestCase):
    """Adversarial testing for SIP returns."""

    def test_sip_amount_boundaries(self):
        self.assertIn("error", calculate_sip_returns(0, 12.0, 3))
        self.assertIn("error", calculate_sip_returns(-1000, 12.0, 3))
        res_1 = calculate_sip_returns(1, 12.0, 1)
        self.assertNotIn("error", res_1)
        self.assertEqual(res_1["total_invested_rupees"], 12.0)

    def test_sip_duration_boundaries(self):
        self.assertIn("error", calculate_sip_returns(5000, 12.0, 0))
        self.assertIn("error", calculate_sip_returns(5000, 12.0, -1))
        res_50y = calculate_sip_returns(1000, 12.0, 50)
        self.assertNotIn("error", res_50y)
        self.assertEqual(res_50y["total_invested_rupees"], 600000.0)
        self.assertGreater(res_50y["maturity_value_rupees"], 600000.0)

    def test_sip_rate_boundaries(self):
        self.assertIn("error", calculate_sip_returns(5000, -0.01, 3))
        # 0% annual rate
        res_0 = calculate_sip_returns(5000, 0.0, 3)
        self.assertEqual(res_0["total_invested_rupees"], 180000.0)
        self.assertEqual(res_0["maturity_value_rupees"], 180000.0)
        self.assertEqual(res_0["wealth_gained_rupees"], 0.0)


class TestProductRecommendationAdversarialBoundaries(unittest.TestCase):
    """Adversarial testing for get_product_recommendation."""

    def test_recommendation_platform_limits(self):
        # Under ₹250
        for amt in [-1000, 0, 1, 249, 249.99]:
            res = get_product_recommendation(amt)
            self.assertFalse(res["is_valid"])
            self.assertIn("Minimum platform investment", res["error"])

        # Above ₹50L
        for amt in [5000000.01, 5000001, 10000000]:
            res = get_product_recommendation(amt)
            self.assertFalse(res["is_valid"])
            self.assertIn("Maximum platform lending limit", res["error"])

    def test_recommendation_strict_9_month_rejection(self):
        # 9-month tenure must be unconditionally rejected regardless of amount or risk
        for amt in [250, 10000, 50000, 100000, 1000000, 5000000]:
            for risk in ["low", "medium", "high", "conservative", None]:
                res = get_product_recommendation(amt, risk, 9)
                self.assertFalse(res["is_valid"], f"Failed for amt={amt}, risk={risk}")
                self.assertIn("9-month", res["error"])
                self.assertIn("suggestion", res)

    def test_recommendation_sub_25k_routing(self):
        # Amounts between ₹250 and ₹24,999.99 route to Manual Lending
        for amt in [250, 500, 5000, 24999, 24999.99]:
            res = get_product_recommendation(amt, "medium", 6)
            self.assertTrue(res["is_valid"])
            self.assertEqual(res["recommended_product"], "Manual Lending")
            self.assertEqual(res["eligible_tenures"], [2, 3, 4, 5, 6, 12])

    def test_recommendation_mtl_and_stl_routing(self):
        # 12-month or low risk -> MTL
        res_low = get_product_recommendation(100000, "low", 12)
        self.assertEqual(res_low["recommended_product"], "MTL 14M Daily (EDI)")

        res_med_12 = get_product_recommendation(100000, "medium", 12)
        self.assertEqual(res_med_12["recommended_product"], "MTL 14M Monthly (EMI)")

        # Short term 3-5m -> STL 5M
        for t in [3, 4, 5]:
            res = get_product_recommendation(50000, "medium", t)
            self.assertEqual(res["recommended_product"], "STL 5M")

        # 6m -> STL 7M
        res_6m = get_product_recommendation(50000, "medium", 6)
        self.assertEqual(res_6m["recommended_product"], "STL 7M")


class TestPropertyBasedFuzzingAndMonteCarlo(unittest.TestCase):
    """Monte Carlo fuzzing & property-based stress verification (2,000 cases)."""

    def test_fuzz_all_financial_functions_resilience(self):
        """Generates 2,000 random inputs across all functions ensuring zero crashes."""
        random.seed(42)

        for i in range(500):
            # Fuzz calculate_stl_returns
            amt = random.uniform(-10000, 5000000)
            tenure = random.choice([None, -5, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 50])
            res_stl = calculate_stl_returns(amt, tenure)
            self.assertIsInstance(res_stl, dict)
            if "error" not in res_stl:
                self.assertGreaterEqual(res_stl["principal"], 25000)
                self.assertLessEqual(res_stl["principal"], 2500000)
                self.assertIn(res_stl["tenure_months"], [3, 4, 5, 6])
                self.assertAlmostEqual(
                    res_stl["final_maturity_amount"],
                    res_stl["principal"] + res_stl["profit_rupees"],
                    places=1
                )

        for i in range(500):
            # Fuzz calculate_mtl_returns
            amt = random.uniform(-10000, 5000000)
            rep = random.choice([None, "", "monthly", "daily", "EDI", "EMI", "invalid_123", "   "])
            res_mtl = calculate_mtl_returns(amt, rep)
            self.assertIsInstance(res_mtl, dict)
            if "error" not in res_mtl:
                self.assertGreaterEqual(res_mtl["principal"], 100000)
                self.assertIn(res_mtl["annualized_xirr_pct"], [18.0, 24.0])

        for i in range(500):
            # Fuzz calculate_manual_lending (standard & Rule 4 custom)
            amt = random.uniform(-10000, 6000000)
            tenure = random.choice([-5, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 24, 100])
            custom_rate = random.choice([None, random.uniform(-20, 100)])
            custom_npa = random.choice([None, random.uniform(-10, 120)])

            res_man = calculate_manual_lending(amt, tenure, custom_rate, custom_npa)
            self.assertIsInstance(res_man, dict)
            if "error" not in res_man:
                self.assertGreaterEqual(amt, 250)
                self.assertLessEqual(amt, 5000000)
                self.assertIn(tenure, [2, 3, 4, 5, 6, 12])
                self.assertNotEqual(tenure, 9)
                if custom_rate is not None:
                    self.assertGreaterEqual(custom_rate, 0)
                    self.assertGreaterEqual(custom_npa if custom_npa is not None else 3.5, 0)
                    self.assertLessEqual(custom_npa if custom_npa is not None else 3.5, 100)
                    # Verify mathematical identity: final_total_amount == principal + net_profit
                    self.assertAlmostEqual(
                        res_man["final_total_amount"],
                        res_man["step_a_principal"] + res_man["step_f_net_profit_rupees"],
                        places=1
                    )

        for i in range(500):
            # Fuzz get_product_recommendation
            amt = random.uniform(-10000, 6000000)
            risk = random.choice([None, "", "low", "medium", "high", "conservative", "aggressive"])
            tenure = random.choice([None, -5, 0, 1, 3, 4, 5, 6, 9, 12, 24])

            res_rec = get_product_recommendation(amt, risk, tenure)
            self.assertIsInstance(res_rec, dict)
            if res_rec["is_valid"]:
                self.assertGreaterEqual(amt, 250)
                self.assertLessEqual(amt, 5000000)
                self.assertNotEqual(tenure, 9)
            else:
                self.assertIn("error", res_rec)


if __name__ == "__main__":
    unittest.main()
