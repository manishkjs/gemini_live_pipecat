"""Adversarial stress test suite for Milestone 1: Financial Math & Deterministic Calculations.

Tests:
1. Exact precision assertions on ₹24 Lakhs MTL daily payout.
2. Boundary values: ₹0, negative values, minimums (₹250, ₹25k, ₹100k), maximums (₹10L, ₹25L, ₹50L), overflows (₹100M).
3. Invalid tenures across all products (0, -1, 1, 7, 8, 9, 10, 11, 13, 14 months, floating-point tenures 3.5, 4.5, 5.5, 12.5).
4. Edge-case floating point rates (0%, 100%, negative rates, NPA > 100%, NPA < 0%).
5. Missing/None parameters and string type conversions in async handlers.
6. AntiCancel Tool Shield logic in agent_live (lock/release, frame suppression, 8.0s self-healing guard).
7. Zero crash / zero unhandled exception guarantee across all permutations.
"""

import unittest
import sys
import os
import asyncio
import time
from typing import Dict, Any
from unittest.mock import MagicMock, AsyncMock

# Add server directory to sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from tools.financial_math import (
    calculate_stl_returns,
    calculate_mtl_returns,
    calculate_manual_lending,
    calculate_sip_returns,
    get_product_recommendation,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    UserStartedSpeakingFrame,
    CancelFrame,
)


class TestAdversarialFinancialMath(unittest.TestCase):
    """Rigorous adversarial test suite for pure financial math functions."""

    # =========================================================================
    # 1. R1 REQUIREMENT: ₹24 LAKHS MTL DAILY PAYOUT PRECISION
    # =========================================================================

    def test_r1_24_lakhs_mtl_daily_exact_precision(self):
        """Verify exact precision on ₹24 Lakhs low-risk MTL Daily investment scenario."""
        res = calculate_mtl_returns(amount=2400000, repayment_type="daily")

        # Must not have error
        self.assertNotIn("error", res, f"Unexpected error returned for ₹24L: {res.get('error')}")

        # Assert exact fields
        self.assertEqual(res["product_name"], "MTL 14M Daily (EDI)")
        self.assertEqual(res["principal"], 2400000)
        self.assertEqual(res["tenure_months"], 12)
        self.assertEqual(res["risk_category"], "AAA (Low Risk)")
        self.assertEqual(res["annualized_xirr_pct"], 18.0)
        
        # Exact mathematical checks:
        # Profit = 24,00,000 * 0.18 * (12/12) = ₹4,32,000.00
        self.assertEqual(res["profit_rupees"], 432000.0)
        
        # Maturity = 24,00,000 + 4,32,000 = ₹28,32,000.00
        self.assertEqual(res["final_maturity_amount"], 2832000.0)
        
        # Daily payout = 28,32,000 / 365 = 7758.904109589... -> round(..., 2) = 7758.90
        self.assertEqual(res["payout_amount"], 7758.90)
        self.assertIn("Daily EDI", res["repayment_type"])

        # String case-insensitivity & variations
        for variation in ["DAILY", "Daily", "edi", "EDI", "Daily EDI", " daily ", "DAILY EDI"]:
            v_res = calculate_mtl_returns(amount=2400000.0, repayment_type=variation)
            self.assertEqual(v_res["profit_rupees"], 432000.0)
            self.assertEqual(v_res["final_maturity_amount"], 2832000.0)
            self.assertEqual(v_res["payout_amount"], 7758.90)

    # =========================================================================
    # 2. STL (SHORT TERM LUMPSUM) ADVERSARIAL BOUNDARIES & TENURES
    # =========================================================================

    def test_stl_amount_boundaries(self):
        """Test STL min ₹25k, max ₹25L, zero, negative, and overflow amounts."""
        # Boundary edges
        self.assertIn("error", calculate_stl_returns(0))
        self.assertIn("error", calculate_stl_returns(-1))
        self.assertIn("error", calculate_stl_returns(-25000))
        self.assertIn("error", calculate_stl_returns(24999))
        self.assertIn("error", calculate_stl_returns(24999.99))
        
        # Valid boundaries
        ok_min = calculate_stl_returns(25000)
        self.assertNotIn("error", ok_min)
        self.assertEqual(ok_min["principal"], 25000)

        ok_max = calculate_stl_returns(2500000)
        self.assertNotIn("error", ok_max)
        self.assertEqual(ok_max["principal"], 2500000)

        # Upper overflows
        self.assertIn("error", calculate_stl_returns(2500000.01))
        self.assertIn("error", calculate_stl_returns(2500001))
        self.assertIn("error", calculate_stl_returns(5000000))
        self.assertIn("error", calculate_stl_returns(100000000))

    def test_stl_invalid_and_floating_tenures(self):
        """Test all invalid and floating tenure permutations for STL (valid: 3, 4, 5, 6, or None)."""
        invalid_tenures = [-10, -1, 0, 1, 2, 7, 8, 9, 10, 11, 12, 13, 14, 24, 36, 100, 3.5, 4.2, 5.9]
        for t in invalid_tenures:
            res = calculate_stl_returns(50000, tenure_months=t)
            self.assertIn("error", res, f"Tenure {t} should have errored for STL")
            self.assertEqual(res.get("available_tenures"), [3, 4, 5, 6])

    def test_stl_valid_tenures_and_rates(self):
        """Verify STL 5M (15% for 3,4,5m) vs STL 7M (18% for 6m or None default 5m)."""
        # None default -> STL 7M, 5 months, 18%
        res_none = calculate_stl_returns(100000, None)
        self.assertEqual(res_none["product_name"], "STL 7M")
        self.assertEqual(res_none["tenure_months"], 5)
        self.assertEqual(res_none["annualized_xirr_pct"], 18.0)
        # Profit = 100,000 * 0.18 * (5/12) = 7500
        self.assertEqual(res_none["profit_rupees"], 7500.0)
        self.assertEqual(res_none["monthly_emi_payout"], 21500.0) # 107500 / 5

        # 3, 4, 5 months -> STL 5M, 15%
        for t in [3, 4, 5]:
            res = calculate_stl_returns(100000, t)
            self.assertEqual(res["product_name"], "STL 5M")
            self.assertEqual(res["annualized_xirr_pct"], 15.0)
            expected_profit = round(100000 * 0.15 * (t / 12.0), 2)
            self.assertEqual(res["profit_rupees"], expected_profit)

        # 6 months -> STL 7M, 18%
        res_6 = calculate_stl_returns(100000, 6)
        self.assertEqual(res_6["product_name"], "STL 7M")
        self.assertEqual(res_6["annualized_xirr_pct"], 18.0)
        self.assertEqual(res_6["profit_rupees"], 9000.0) # 100k * 0.18 * 0.5

    # =========================================================================
    # 3. MTL (MEDIUM TERM LUMPSUM) ADVERSARIAL BOUNDARIES & LIMITS
    # =========================================================================

    def test_mtl_amount_limits_per_repayment_mode(self):
        """Test MTL limits: Min ₹1L. Monthly Max ₹10L. Daily Max ₹25L."""
        # Below min ₹1L
        self.assertIn("error", calculate_mtl_returns(0, "monthly"))
        self.assertIn("error", calculate_mtl_returns(-100000, "daily"))
        self.assertIn("error", calculate_mtl_returns(99999.99, "monthly"))
        self.assertIn("error", calculate_mtl_returns(99999.99, "daily"))

        # Monthly limits: 1L - 10L
        ok_monthly_min = calculate_mtl_returns(100000, "monthly")
        self.assertNotIn("error", ok_monthly_min)
        ok_monthly_max = calculate_mtl_returns(1000000, "monthly")
        self.assertNotIn("error", ok_monthly_max)
        self.assertIn("error", calculate_mtl_returns(1000000.01, "monthly"))
        self.assertIn("error", calculate_mtl_returns(1500000, "monthly"))

        # Daily limits: 1L - 25L
        ok_daily_min = calculate_mtl_returns(100000, "daily")
        self.assertNotIn("error", ok_daily_min)
        ok_daily_max = calculate_mtl_returns(2500000, "daily")
        self.assertNotIn("error", ok_daily_max)
        self.assertIn("error", calculate_mtl_returns(2500000.01, "daily"))
        self.assertIn("error", calculate_mtl_returns(5000000, "daily"))

    def test_mtl_repayment_type_string_variations(self):
        """Test various strings and None fallback for repayment_type."""
        # None fallback -> defaults to monthly
        res_none = calculate_mtl_returns(500000, None)
        self.assertEqual(res_none["product_name"], "MTL 14M Monthly (EMI)")
        self.assertEqual(res_none["annualized_xirr_pct"], 24.0)

        # Non-daily string fallback -> defaults to monthly
        res_other = calculate_mtl_returns(500000, "bullet")
        self.assertEqual(res_other["product_name"], "MTL 14M Monthly (EMI)")

    # =========================================================================
    # 4. MANUAL LENDING BOUNDARIES, FEES & RULE 4 STEPS A-G
    # =========================================================================

    def test_manual_lending_amount_boundaries(self):
        """Test Manual Lending min ₹250, max ₹50 Lakhs."""
        self.assertIn("error", calculate_manual_lending(0))
        self.assertIn("error", calculate_manual_lending(-500))
        self.assertIn("error", calculate_manual_lending(249.99))
        
        ok_min = calculate_manual_lending(250)
        self.assertNotIn("error", ok_min)

        ok_max = calculate_manual_lending(5000000)
        self.assertNotIn("error", ok_max)

        self.assertIn("error", calculate_manual_lending(5000000.01))
        self.assertIn("error", calculate_manual_lending(100000000))

    def test_manual_lending_tenure_validation(self):
        """Test strict tenure restrictions (valid: 2, 3, 4, 5, 6, 12; 9 is strictly forbidden)."""
        # Non-positive
        self.assertIn("error", calculate_manual_lending(10000, 0))
        self.assertIn("error", calculate_manual_lending(10000, -1))
        self.assertIn("error", calculate_manual_lending(10000, -6))

        # 9 months specific rejection
        res_9 = calculate_manual_lending(10000, 9)
        self.assertIn("error", res_9)
        self.assertIn("9-month", res_9["error"])

        # Other invalid tenures and floating points
        for t in [1, 7, 8, 10, 11, 13, 14, 15, 18, 24, 36, 2.5, 3.7, 6.2]:
            res = calculate_manual_lending(10000, t)
            self.assertIn("error", res, f"Tenure {t} must be rejected in Manual Lending")

        # Valid tenures
        for t in [2, 3, 4, 5, 6, 12]:
            res = calculate_manual_lending(10000, t)
            self.assertNotIn("error", res, f"Tenure {t} must be valid in Manual Lending")

    def test_manual_lending_custom_portfolio_steps_a_to_g(self):
        """Stress-test Rule 4 Steps A-G across all fee tiers and rate combinations."""
        # Fee tiers:
        # 2m -> 1%, 3m -> 1%, 4m -> 4%, 5m -> 4%, 6m -> 3%, 12m -> 6%
        fee_expectations = {2: 1.0, 3: 1.0, 4: 4.0, 5: 4.0, 6: 3.0, 12: 6.0}

        for tenure, expected_fee in fee_expectations.items():
            principal = 200000.0
            borrower_rate = 36.0
            npa_rate = 4.0

            res = calculate_manual_lending(
                amount=principal,
                tenure_months=tenure,
                custom_borrower_rate_pct=borrower_rate,
                custom_npa_rate_pct=npa_rate,
            )

            self.assertNotIn("error", res)
            
            # Step A: Principal
            self.assertEqual(res["step_a_principal"], principal)
            
            # Step B: NPA Loss = Principal * (NPA% / 100)
            expected_npa_loss = round(principal * (npa_rate / 100.0), 2)
            self.assertEqual(res["step_b_npa_loss_rupees"], expected_npa_loss)
            
            # Step C: Performing Principal = Principal - NPA Loss
            expected_perf = round(principal - expected_npa_loss, 2)
            self.assertEqual(res["step_c_performing_principal"], expected_perf)
            
            # Step D: Gross Interest = Performing * BorrowerRate * (Tenure/12)
            expected_gross = round(expected_perf * (borrower_rate / 100.0) * (tenure / 12.0), 2)
            self.assertEqual(res["step_d_gross_interest"], expected_gross)
            
            # Step E: Platform Fee = Principal * Fee%
            self.assertEqual(res["platform_fee_pct"], expected_fee)
            expected_fee_rupees = round(principal * (expected_fee / 100.0), 2)
            self.assertEqual(res["step_e_platform_fee_rupees"], expected_fee_rupees)
            
            # Step F: Net Profit = Gross Interest - Platform Fee - NPA Loss
            expected_net_profit = round(expected_gross - expected_fee_rupees - expected_npa_loss, 2)
            self.assertEqual(res["step_f_net_profit_rupees"], expected_net_profit)
            
            # Step G: Net ROI = (Net Profit / Principal) * (12 / Tenure) * 100
            expected_roi = round((expected_net_profit / principal) * (12.0 / tenure) * 100.0, 2)
            self.assertEqual(res["step_g_net_annualized_roi_pct"], expected_roi)
            
            # Final Total = Principal + Net Profit
            self.assertEqual(res["final_total_amount"], round(principal + expected_net_profit, 2))

    def test_manual_lending_edge_rates(self):
        """Test negative rates, 0% rates, 100% rates, extreme NPA percentages."""
        # Negative borrower rate -> error
        self.assertIn("error", calculate_manual_lending(10000, 12, custom_borrower_rate_pct=-1.0))

        # Negative NPA rate -> error
        self.assertIn("error", calculate_manual_lending(10000, 12, custom_borrower_rate_pct=20, custom_npa_rate_pct=-0.5))

        # NPA > 100% -> error
        self.assertIn("error", calculate_manual_lending(10000, 12, custom_borrower_rate_pct=20, custom_npa_rate_pct=100.1))
        self.assertIn("error", calculate_manual_lending(10000, 12, custom_borrower_rate_pct=20, custom_npa_rate_pct=500.0))

        # 0% borrower rate (valid, produces net loss due to fee and NPA)
        res_zero_rate = calculate_manual_lending(10000, 12, custom_borrower_rate_pct=0.0, custom_npa_rate_pct=0.0)
        self.assertNotIn("error", res_zero_rate)
        self.assertEqual(res_zero_rate["step_d_gross_interest"], 0.0)
        self.assertEqual(res_zero_rate["step_e_platform_fee_rupees"], 600.0)
        self.assertEqual(res_zero_rate["step_f_net_profit_rupees"], -600.0)

        # 100% NPA (valid, all principal lost)
        res_100_npa = calculate_manual_lending(10000, 12, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=100.0)
        self.assertNotIn("error", res_100_npa)
        self.assertEqual(res_100_npa["step_b_npa_loss_rupees"], 10000.0)
        self.assertEqual(res_100_npa["step_c_performing_principal"], 0.0)
        self.assertEqual(res_100_npa["step_d_gross_interest"], 0.0)

    # =========================================================================
    # 5. SIP COMPOUNDING ADVERSARIAL STRESS
    # =========================================================================

    def test_sip_returns_boundaries_and_rates(self):
        """Test SIP calculation with 0%, negative, and extreme values."""
        # Non-positive monthly amount
        self.assertIn("error", calculate_sip_returns(0, 12.0, 3))
        self.assertIn("error", calculate_sip_returns(-1000, 12.0, 3))

        # Non-positive duration
        self.assertIn("error", calculate_sip_returns(5000, 12.0, 0))
        self.assertIn("error", calculate_sip_returns(5000, 12.0, -1))

        # Negative interest rate
        self.assertIn("error", calculate_sip_returns(5000, -5.0, 3))

        # 0% interest rate
        res_0 = calculate_sip_returns(5000, 0.0, 5)
        self.assertNotIn("error", res_0)
        self.assertEqual(res_0["total_invested_rupees"], 300000.0)
        self.assertEqual(res_0["maturity_value_rupees"], 300000.0)
        self.assertEqual(res_0["wealth_gained_rupees"], 0.0)

        # High interest rate (100% p.a.)
        res_100 = calculate_sip_returns(10000, 100.0, 2)
        self.assertNotIn("error", res_100)
        self.assertGreater(res_100["maturity_value_rupees"], res_100["total_invested_rupees"])

    # =========================================================================
    # 6. PRODUCT RECOMMENDATION ADVERSARIAL EDGES
    # =========================================================================

    def test_product_recommendation_all_branches(self):
        """Test all boundary cases, sub-₹25k manual lending recommendation, 9m rejection."""
        # Out of platform limits (< ₹250 or > ₹50L)
        res_below = get_product_recommendation(100)
        self.assertFalse(res_below["is_valid"])
        self.assertIn("error", res_below)

        res_above = get_product_recommendation(6000000)
        self.assertFalse(res_above["is_valid"])
        self.assertIn("error", res_above)

        # 9 months tenure rejection
        res_9 = get_product_recommendation(50000, tenure_months=9)
        self.assertFalse(res_9["is_valid"])
        self.assertIn("9-month", res_9["error"])

        # Sub-₹25k amounts -> Manual Lending recommendation
        res_sub25k = get_product_recommendation(5000)
        self.assertTrue(res_sub25k["is_valid"])
        self.assertEqual(res_sub25k["recommended_product"], "Manual Lending")

        # Low risk -> MTL Daily
        res_low = get_product_recommendation(100000, risk_appetite="low")
        self.assertEqual(res_low["recommended_product"], "MTL 14M Daily (EDI)")

        # Medium risk 12m -> MTL Monthly
        res_med12 = get_product_recommendation(100000, risk_appetite="medium", tenure_months=12)
        self.assertEqual(res_med12["recommended_product"], "MTL 14M Monthly (EMI)")

        # Short term 3m, 4m, 5m -> STL 5M
        for t in [3, 4, 5]:
            res_stl5 = get_product_recommendation(100000, tenure_months=t)
            self.assertEqual(res_stl5["recommended_product"], "STL 5M")

        # Short term 6m or default -> STL 7M
        res_stl7 = get_product_recommendation(100000, tenure_months=6)
        self.assertEqual(res_stl7["recommended_product"], "STL 7M")


class TestAdversarialAsyncHandlersAndShield(unittest.IsolatedAsyncioTestCase):
    """Adversarial testing of async tool handlers and AntiCancel Tool Shield."""

    async def test_async_handlers_robustness_with_missing_and_string_params(self):
        """Ensure async tool handlers safely cast types and handle missing/None arguments."""
        from agent_live import (
            handle_calculate_stl_returns,
            handle_calculate_mtl_returns,
            handle_calculate_manual_lending,
            handle_calculate_sip_returns,
            handle_get_product_recommendation,
        )

        async def run_handler(handler, args):
            cb_result = {}
            async def mock_callback(res):
                nonlocal cb_result
                cb_result = res

            mock_params = MagicMock()
            mock_params.arguments = args
            mock_params.result_callback = mock_callback
            await handler(mock_params)
            return cb_result

        # 1. STL Handler with string numbers and empty dict
        res_stl_str = await run_handler(handle_calculate_stl_returns, {"amount": "60000", "tenure_months": "4"})
        self.assertEqual(res_stl_str["principal"], 60000.0)
        self.assertEqual(res_stl_str["tenure_months"], 4)

        res_stl_empty = await run_handler(handle_calculate_stl_returns, {})
        self.assertEqual(res_stl_empty["principal"], 50000.0)

        # 2. MTL Handler with ₹24L string
        res_mtl = await run_handler(handle_calculate_mtl_returns, {"amount": "2400000", "repayment_type": "daily"})
        self.assertEqual(res_mtl["profit_rupees"], 432000.0)
        self.assertEqual(res_mtl["payout_amount"], 7758.90)

        # 3. Manual Lending Handler with strings
        res_man = await run_handler(handle_calculate_manual_lending, {
            "amount": "100000",
            "tenure_months": "6",
            "custom_borrower_rate_pct": "30.0",
            "custom_npa_rate_pct": "2.0"
        })
        self.assertEqual(res_man["step_a_principal"], 100000.0)
        self.assertEqual(res_man["borrower_rate_pct"], 30.0)

        # 4. SIP Handler with strings
        res_sip = await run_handler(handle_calculate_sip_returns, {
            "monthly_amount": "5000",
            "annual_rate": "12.5",
            "years": "3"
        })
        self.assertEqual(res_sip["monthly_investment"], 5000.0)
        self.assertEqual(res_sip["duration_years"], 3)

        # 5. Recommendation Handler with strings
        res_rec = await run_handler(handle_get_product_recommendation, {
            "amount": "100000",
            "risk_appetite": "low",
            "tenure_months": "12"
        })
        self.assertEqual(res_rec["recommended_product"], "MTL 14M Daily (EDI)")

    async def test_anticancel_tool_shield_logic(self):
        """Stress-test GeminiSessionLoggerMixin AntiCancel tool lock and interruption suppression."""
        from agent_live import GeminiSessionLoggerMixin

        class BaseProcessor(FrameProcessor):
            def __init__(self):
                super().__init__()
                self.processed_frames = []

            async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
                self.processed_frames.append(frame)

        class MockService(GeminiSessionLoggerMixin, BaseProcessor):
            def __init__(self):
                super().__init__()
                self._active_tools_in_flight = 0
                self._frame_locked_tools = False
                self._tool_lock_started_at = None
                self.pushed_frames = []

            async def push_frame(self, frame, direction=None):
                self.pushed_frames.append(frame)

        service = MockService()

        # 1. Initially no tools in flight
        self.assertFalse(service._tools_in_flight())

        # 2. Lock tools (e.g. FunctionCallInProgressFrame)
        service._lock_tools("test start")
        self.assertTrue(service._tools_in_flight())
        self.assertEqual(service._active_tools_in_flight, 1)

        # 3. InterruptionFrame must be suppressed during tool in flight
        int_frame = InterruptionFrame()
        user_speaking_frame = UserStartedSpeakingFrame()

        await service.process_frame(int_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(len(service.processed_frames), 0, "InterruptionFrame should be suppressed when tool is in flight")

        await service.process_frame(user_speaking_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(len(service.processed_frames), 0, "UserStartedSpeakingFrame should be suppressed when tool is in flight")

        # 4. Release tools
        service._release_tools("test complete")
        self.assertFalse(service._tools_in_flight())
        self.assertEqual(service._active_tools_in_flight, 0)

        # 5. InterruptionFrame when tools are NOT in flight -> processed normally downstream
        await service.process_frame(int_frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(len(service.processed_frames), 1, "InterruptionFrame should pass through when tools are not in flight")

        # 6. Self-healing lock guard: if lock held > 8.0s, it auto-releases
        service._lock_tools("stuck tool simulation")
        self.assertTrue(service._tools_in_flight())
        # Force start time to 10 seconds ago
        service._tool_lock_started_at = time.monotonic() - 10.0
        self.assertFalse(service._tools_in_flight(), "Stuck tool lock should self-heal after 8.0s timeout")
        self.assertEqual(service._active_tools_in_flight, 0)


if __name__ == "__main__":
    unittest.main()
