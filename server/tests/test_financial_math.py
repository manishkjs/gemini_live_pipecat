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

    def test_navigation_guidance(self):
        pan_guide = get_kyc_guidance("pan")
        self.assertIn("PAN", pan_guide["step"])

        deposit_guide = get_app_screen_flow("deposit")
        self.assertIn("Funds", deposit_guide["flow_name"])


if __name__ == "__main__":
    unittest.main()
