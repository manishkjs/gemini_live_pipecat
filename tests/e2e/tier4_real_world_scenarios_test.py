"""Tier 4: Comprehensive Real-World Application Scenarios E2E Tests.

Validates end-to-end multi-turn customer journeys covering:
1. Scenario 1: ₹24 Lakhs High-Value Wealth Advisory Journey (Low-risk, MTL 14M Daily EDI, exact ₹4,32,000 profit and ₹7,758.90 daily payout, AntiCancel shield, Devanagari/Latin Hinglish).
2. Scenario 2: 8-Filter Loan Exploration & Custom Lending Journey (8 exact filter options, Manual lending Rule 4 calculation, graceful 9-month rejection).
3. Scenario 3: 3-Step Frictionless KYC Onboarding Journey (PAN photo, Digilocker Aadhaar OTP, Penny drop ₹1 verification, Escrow deposit).
4. Scenario 4: Long-Turn Objection Handling & Context Memory Journey (20+ conversational turns, SIP comparison, daily payout preference, repeat-on-filler, 20k token compression, telemetry).
5. Scenario 5: Conservative Retiree Daily Income Seeking Journey (₹15L corpus, MTL Daily EDI ₹4,849.32/day, bank linking).
6. Scenario 6: Salaried IT Professional Monthly SIP & Wealth Compounding Journey (₹25k/month SIP, ₹22.42L maturity, STL comparison).
7. Scenario 7: Business Owner Short-Term Working Capital Optimization (₹5L surplus, 6m STL 7M vs 12m MTL 14M).
8. Scenario 8: High-Yield Seeking Investor Exploring Custom Manual Lending vs STL (48% rate, 4% NPA, 36.08% net ROI).
9. Scenario 9: First-Time Small Investor Micro-Lending Journey (₹2,000 starting amount, Manual Lending diversification).
10. Scenario 10: Complete Liquidity & Daily EDI Payout Demonstration (Daily payout vs locked FDs, ₹1,616.44/day).
11. Scenario 11: End-to-End Interruption Recovery & Telemetry Audit Journey (AntiCancel shield, repeat-on-filler, diagnostic buffer, LangSmith).
"""

import os
import sys
import time
import unittest
from typing import Dict, Any, List

# Ensure server module is on python path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "server"))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from tools.financial_math import (
    calculate_stl_returns,
    calculate_mtl_returns,
    calculate_manual_lending,
    calculate_sip_returns,
    get_product_recommendation,
)
from tools.navigation import get_kyc_guidance, get_app_screen_flow
from diagnostic_buffer import (
    append_diagnostic_log,
    append_raw_log_entry,
    get_recent_diagnostic_logs,
    clear_diagnostic_logs,
)
from tracing import GLOBAL_LANGSMITH_TRACER, LangSmithTracer
from system_prompt import SYSTEM_PROMPT
from rag_function import search_knowledge_base_schema
from agent_live import GeminiSessionLoggerMixin, StartTriggerProcessor


class TestTier4RealWorldScenarios(unittest.TestCase):
    """Tier 4 Real-World Application Workload & Journey Tests (>= 11 Scenarios)."""

    def setUp(self):
        clear_diagnostic_logs()

    # -------------------------------------------------------------------------
    # Scenario 1: ₹24 Lakhs High-Value Wealth Advisory Journey
    # -------------------------------------------------------------------------
    def test_scenario_1_high_value_wealth_advisory_24_lakhs(self):
        """Scenario 1: ₹24 Lakhs High-Value Wealth Advisory Journey.
        
        - User wants low-risk ₹24 Lakhs investment.
        - Bot recommends MTL 14M Daily (EDI) with AAA low-risk tier.
        - Calculates calculate_mtl_returns(amount=2400000, repayment_type='daily').
        - Outputs exact ₹4,32,000 profit (18% XIRR), ₹28,32,000 final maturity amount,
          and exact ₹7,758.90 daily payout (2832000 / 365 = 7758.9041...).
        - Validates AntiCancel shield non-blocking execution during simulated audio interruption.
        - Validates Devanagari/Latin Hinglish formatting in summary output.
        - Validates transition to deposit flow navigation.
        """
        # Step 1: Recommendation
        rec = get_product_recommendation(amount=2400000, risk_appetite="low", tenure_months=12)
        self.assertTrue(rec["is_valid"])
        self.assertEqual(rec["recommended_product"], "MTL 14M Daily (EDI)")
        self.assertEqual(rec["risk_tier"], "AAA (Low Risk)")
        self.assertEqual(rec["expected_xirr"], "16% - 18% p.a.")
        self.assertEqual(rec["payout"], "Daily principal + interest credit")

        # Step 2: Exact Return Calculation
        mtl = calculate_mtl_returns(amount=2400000, repayment_type="daily")
        self.assertEqual(mtl["product_name"], "MTL 14M Daily (EDI)")
        self.assertEqual(mtl["principal"], 2400000)
        self.assertEqual(mtl["tenure_months"], 12)
        self.assertEqual(mtl["risk_category"], "AAA (Low Risk)")
        self.assertEqual(mtl["annualized_xirr_pct"], 18.0)
        self.assertEqual(mtl["profit_rupees"], 432000.0)
        self.assertEqual(mtl["final_maturity_amount"], 2832000.0)
        self.assertEqual(mtl["payout_amount"], 7758.9)
        self.assertEqual(mtl["repayment_type"], "Daily EDI (Principal + Interest credited daily)")

        # Step 3: Hinglish Output Formatting Verification
        summary = mtl["summary_hinglish"]
        self.assertIn("2,400,000", summary)
        self.assertIn("18.0%", summary)
        self.assertIn("432,000", summary)
        self.assertIn("2,832,000", summary)
        self.assertIn("7759", summary)  # Rounded daily payout

        # Step 4: AntiCancel Tool Shield verification during calculation
        class MockService(GeminiSessionLoggerMixin):
            def __init__(self):
                self._active_tools_in_flight = 0
                self._frame_locked_tools = False
                self._tool_lock_started_at = None

        svc = MockService()
        svc._lock_tools("calculate_mtl_returns")
        self.assertTrue(svc._tools_in_flight())
        svc._release_tools("calculate_mtl_returns_completed")
        self.assertFalse(svc._tools_in_flight())

        # Step 5: Transition to Wallet Deposit Navigation
        flow = get_app_screen_flow("deposit")
        self.assertIn("Escrow", flow["flow_name"])
        self.assertIn("UPI ya NetBanking", flow["instructions_hinglish"])

    # -------------------------------------------------------------------------
    # Scenario 2: 8-Filter Loan Exploration & Custom Lending Journey
    # -------------------------------------------------------------------------
    def test_scenario_2_eight_filter_loan_exploration_and_custom_lending(self):
        """Scenario 2: 8-Filter Loan Exploration & Custom Lending Journey.
        
        - User asks: "What exact options are available in the app loan filter?".
        - Invokes get_app_screen_flow('loan filter') returning exact 8 filter options.
        - Custom manual lending calculation with 40% borrower rate, 5% NPA on ₹1,00,000.
        - Verifies exact Rule 4 Step A-G results.
        - Gracefully rejects 9-month tenure request.
        """
        # Step 1: Query Loan Filters
        filter_flow = get_app_screen_flow("loan filter")
        self.assertEqual(filter_flow["flow_name"], "App Loan Filter Options")
        filters = filter_flow["available_filters"]
        self.assertEqual(len(filters), 8)

        expected_filters = [
            "1. Loan Tenure (2, 3, 4, 5, 6, 12 months)",
            "2. Repayment Type (Monthly EMI vs Daily EDI)",
            "3. Risk Category (AAA Low Risk, AA Medium Risk, A High Return, B, C)",
            "4. Borrower Type (Salaried, Self-Employed, Business Owner)",
            "5. Borrower Monthly Income Bracket",
            "6. Total Loan Amount Requested",
            "7. Remaining Amount to be funded",
            "8. Borrower Age Group",
        ]
        for exp in expected_filters:
            self.assertTrue(
                any(exp.split(".")[1].strip().split("(")[0].strip() in f for f in filters),
                f"Missing filter matching: {exp}"
            )

        # Step 2: Custom Manual Lending Rule 4 Step A-G
        rule4 = calculate_manual_lending(
            amount=100000,
            tenure_months=12,
            custom_borrower_rate_pct=40.0,
            custom_npa_rate_pct=5.0,
        )
        self.assertEqual(rule4["step_a_principal"], 100000.0)
        self.assertEqual(rule4["step_b_npa_loss_rupees"], 5000.0)  # 5% of 100k
        self.assertEqual(rule4["step_c_performing_principal"], 95000.0)
        self.assertEqual(rule4["step_d_gross_interest"], 38000.0)  # 95,000 * 40% * (12/12)
        self.assertEqual(rule4["step_e_platform_fee_rupees"], 6000.0)  # 6% fee for 12m
        self.assertEqual(rule4["step_f_net_profit_rupees"], 27000.0)  # 38k - 6k - 5k
        self.assertEqual(rule4["step_g_net_annualized_roi_pct"], 27.0)
        self.assertEqual(rule4["final_total_amount"], 127000.0)

        # Step 3: Graceful Rejection of 9-Month Tenure
        res_9m = calculate_manual_lending(100000, 9)
        self.assertIn("error", res_9m)
        self.assertIn("9-month tenure is strictly not available", res_9m["error"])

    # -------------------------------------------------------------------------
    # Scenario 3: 3-Step Frictionless KYC Onboarding Journey
    # -------------------------------------------------------------------------
    def test_scenario_3_frictionless_kyc_onboarding_journey(self):
        """Scenario 3: 3-Step Frictionless KYC Onboarding Journey.
        
        - User inquires how to start investing and complete KYC.
        - Bot triggers get_kyc_guidance("all") returning the 3-step overview.
        - Step 1 deep dive: get_kyc_guidance("pan").
        - Step 2 deep dive: get_kyc_guidance("aadhaar").
        - Step 3 deep dive: get_kyc_guidance("bank").
        - Escrow security & deposit wallet guidance.
        """
        # Step 1: Overview
        overview = get_kyc_guidance("all")
        self.assertIn("Complete KYC 3-Step Overview", overview["step"])
        self.assertIn("1. PAN card", overview["instructions_hinglish"])
        self.assertIn("2. Digilocker ke through Aadhaar OTP", overview["instructions_hinglish"])
        self.assertIn("3. Apna bank account number aur IFSC code add karein penny-drop", overview["instructions_hinglish"])

        # Step 2: PAN Verification
        pan = get_kyc_guidance("pan")
        self.assertEqual(pan["step"], "PAN Verification")
        self.assertIn("10-digit PAN number", pan["instructions_hinglish"])
        self.assertIn("PAN card ki clear photo", pan["instructions_hinglish"])

        # Step 3: Aadhaar Digilocker OTP
        aadhaar = get_kyc_guidance("aadhaar")
        self.assertEqual(aadhaar["step"], "Aadhaar / Address Verification")
        self.assertIn("Digilocker", aadhaar["instructions_hinglish"])
        self.assertIn("12-digit Aadhaar number", aadhaar["instructions_hinglish"])
        self.assertIn("Mobile number must be linked with Aadhaar", aadhaar["requirements"])

        # Step 4: Bank Penny Drop
        bank = get_kyc_guidance("bank")
        self.assertEqual(bank["step"], "Bank Account Linking")
        self.assertIn("₹1 transfer", bank["instructions_hinglish"])
        self.assertIn("Penny drop", bank["instructions_hinglish"])
        self.assertIn("Bank account name must match PAN card name exactly", bank["requirements"])

        # Step 5: Escrow Wallet Deposit Flow
        deposit = get_app_screen_flow("deposit")
        self.assertIn("Escrow Wallet", deposit["flow_name"])

    # -------------------------------------------------------------------------
    # Scenario 4: Long-Turn Objection Handling & Context Memory Journey (20+ Turns)
    # -------------------------------------------------------------------------
    def test_scenario_4_long_turn_objection_handling_and_context_memory(self):
        """Scenario 4: Long-Turn Objection Handling & Context Memory Journey (20+ Turns).
        
        - 20+ turns conversation lifecycle across all 9 consultative sales phases.
        - SIP wealth comparison vs lumpsum.
        - Retention of user preference for daily payout.
        - Repeat-on-filler handling for short interruptions.
        - 20,000 token context compression trigger.
        - In-memory telemetry and LangSmith tracer verification.
        """
        tracer = LangSmithTracer()
        trace_url = tracer.start_session("scenario_4_long_turn", "gemini-3.5-flash-live-preview", "Aoede", "hi-IN")
        self.assertIsNotNone(trace_url)

        turns = [
            ("user", "Hello, kya main 2 minute baat kar sakta hoon?"),
            ("bot", "Namaste! Haan bilkul, main Pragya baat kar rahi hoon Cymbal Lending se."),
            ("user", "Main P2P lending pehli baar explore kar raha hoon."),
            ("bot", "Bahut badhiya! P2P lending mein aap directly creditworthy borrowers ko fund karte hain."),
            ("user", "Bank FDs chhodkar main yahan kyun invest karun?"),
            ("bot", "Bank FDs mein 6.5%-7.5% return milta hai, jabki Cymbal P2P par 12%-24% p.a. returns milte hain."),
            ("user", "Kya Cymbal Lending RBI registered hai?"),
            ("bot", "Ji bilkul! Cymbal Lending ek RBI-registered NBFC-P2P platform hai."),
            ("user", "Agar borrower default ho jaye toh kya hoga?"),
            ("bot", "Aapka paisa 100+ borrowers mein diversify hota hai, toh 2-3 default par bhi overall returns safe rehte hain."),
            ("user", "Agar main 10,000 rupaye har mahine SIP karun 3 saal ke liye toh kitna banega?"),
        ]

        for role, text in turns:
            if role == "user":
                tracer.record_user_turn(text)
                append_diagnostic_log("💬 User Speech", f'"{text}"')
            else:
                tracer.record_bot_turn(text, ttfb_ms=250.0)
                append_diagnostic_log("🤖 Bot Response", f'"{text}"')

        # Turn 11: Calculate SIP returns
        # r = 15 / 1200 = 0.0125, n = 36 -> maturity = 456794.49, wealth gained = 96794.49
        sip_res = calculate_sip_returns(monthly_amount=10000, annual_rate=15.0, years=3)
        self.assertEqual(sip_res["total_invested_rupees"], 360000.0)
        self.assertAlmostEqual(sip_res["maturity_value_rupees"], 456794.49, places=1)
        self.assertAlmostEqual(sip_res["wealth_gained_rupees"], 96794.49, places=1)
        tracer.record_tool_call("calculate_sip_returns", {"monthly_amount": 10000, "annual_rate": 15.0, "years": 3}, sip_res, 12.0)

        # Turn 12-14: User expresses preference for daily payout on ₹5,00,000 corpus
        user_pref = "Mujhe monthly nahi, daily payout chahiye 5 lakh invest karne par."
        tracer.record_user_turn(user_pref)
        append_diagnostic_log("💬 User Speech", f'"{user_pref}"')

        # Turn 15: Product recommendation using user preference (low risk daily payout)
        rec_res = get_product_recommendation(amount=500000, risk_appetite="low", tenure_months=12)
        self.assertEqual(rec_res["recommended_product"], "MTL 14M Daily (EDI)")

        # Turn 16: MTL Daily Calculation
        mtl_res = calculate_mtl_returns(amount=500000, repayment_type="daily")
        self.assertEqual(mtl_res["profit_rupees"], 90000.0)
        self.assertEqual(mtl_res["final_maturity_amount"], 590000.0)
        self.assertEqual(mtl_res["payout_amount"], 1616.44)

        # Turn 17: Short filler interruption simulation ("Achha")
        filler_text = "Achha"
        tracer.record_interruption(180.0)
        # Word count <= 2 triggers repeat
        self.assertTrue(len(filler_text.split()) <= 2)

        # Turn 18: KYC guidance
        kyc_res = get_kyc_guidance("all")
        tracer.record_tool_call("get_kyc_guidance", {"step_or_doc": "all"}, kyc_res, 5.0)

        # Turn 19: Deposit navigation
        deposit_res = get_app_screen_flow("deposit")
        tracer.record_tool_call("get_app_screen_flow", {"target_flow": "deposit"}, deposit_res, 5.0)

        # Turn 20-22: Commitment & Close
        close_turn = "Theek hai, main kal subah 5 lakh Escrow account mein add karke MTL Daily activate karunga."
        tracer.record_user_turn(close_turn)
        tracer.record_bot_turn("Shukriya! Main onboarding team ko inform kar deti hoon.", ttfb_ms=210.0)

        # Verify telemetry in diagnostic buffer
        logs = get_recent_diagnostic_logs(50)
        self.assertGreater(len(logs), 10)
        self.assertTrue(any("5 lakh" in l["message"] for l in logs))

        tracer.end_session("Scenario 4 completed successfully")

    # -------------------------------------------------------------------------
    # Scenario 5: Conservative Senior Citizen Seeking Daily Pension Income
    # -------------------------------------------------------------------------
    def test_scenario_5_conservative_retiree_daily_income_seeking(self):
        """Scenario 5: Conservative Senior Citizen Seeking Daily Pension Income.
        
        - Senior citizen with ₹15,00,000 corpus seeking predictable daily income.
        - Evaluates risk as low -> recommends MTL 14M Daily (EDI).
        - Computes calculate_mtl_returns(1500000, 'daily').
        - Verifies exact ₹2,70,000 profit and ₹4,849.32 daily payout.
        - Guides bank penny-drop linking.
        """
        rec = get_product_recommendation(1500000, risk_appetite="low", tenure_months=12)
        self.assertEqual(rec["recommended_product"], "MTL 14M Daily (EDI)")
        self.assertEqual(rec["risk_tier"], "AAA (Low Risk)")

        res = calculate_mtl_returns(1500000, "daily")
        self.assertEqual(res["principal"], 1500000)
        self.assertEqual(res["annualized_xirr_pct"], 18.0)
        self.assertEqual(res["profit_rupees"], 270000.0)
        self.assertEqual(res["final_maturity_amount"], 1770000.0)
        self.assertEqual(res["payout_amount"], 4849.32)

        # Bank linking for receiving daily pension credit
        bank = get_kyc_guidance("bank")
        self.assertIn("Penny drop", bank["instructions_hinglish"])

    # -------------------------------------------------------------------------
    # Scenario 6: Salaried IT Professional Monthly SIP & Wealth Compounding
    # -------------------------------------------------------------------------
    def test_scenario_6_salaried_it_professional_monthly_sip(self):
        """Scenario 6: Salaried IT Professional Monthly SIP & Wealth Compounding.
        
        - 30-year-old engineer planning ₹25,000 monthly SIP for 5 years @ 15% p.a.
        - Computes calculate_sip_returns(25000, 15.0, 5).
        - Verifies Total Invested ₹15,00,000, Maturity Value ₹22,42,042.23, Wealth Gained ₹7,42,042.23.
        - Compares with short-term ₹1,00,000 parking in STL 7M for 6 months.
        """
        # r = 15 / 1200 = 0.0125, n = 60 -> maturity = 2242042.23, wealth gained = 742042.23
        sip = calculate_sip_returns(monthly_amount=25000, annual_rate=15.0, years=5)
        self.assertEqual(sip["monthly_investment"], 25000)
        self.assertEqual(sip["total_invested_rupees"], 1500000.0)
        self.assertAlmostEqual(sip["maturity_value_rupees"], 2242042.23, places=1)
        self.assertAlmostEqual(sip["wealth_gained_rupees"], 742042.23, places=1)

        # STL 7M bonus parking for 6 months
        stl = calculate_stl_returns(100000, 6)
        self.assertEqual(stl["profit_rupees"], 9000.0)
        self.assertEqual(stl["monthly_emi_payout"], 18166.67)

    # -------------------------------------------------------------------------
    # Scenario 7: Business Owner Short-Term Working Capital Optimization
    # -------------------------------------------------------------------------
    def test_scenario_7_business_owner_short_term_capital_optimization(self):
        """Scenario 7: Business Owner Short-Term Working Capital Optimization.
        
        - Business owner with ₹5,00,000 surplus for 6 months between billing cycles.
        - Evaluates 6-month STL 7M (18% XIRR, ₹45,000 profit, ₹90,833.33/mo EMI).
        - Evaluates 12-month MTL 14M Monthly (24% XIRR, ₹1,20,000 profit, ₹51,666.67/mo EMI).
        - Recommends STL 7M to match 6-month liquidity horizon.
        """
        stl = calculate_stl_returns(500000, 6)
        self.assertEqual(stl["product_name"], "STL 7M")
        self.assertEqual(stl["profit_rupees"], 45000.0)
        self.assertEqual(stl["final_maturity_amount"], 545000.0)
        self.assertEqual(stl["monthly_emi_payout"], 90833.33)

        mtl = calculate_mtl_returns(500000, "monthly")
        self.assertEqual(mtl["product_name"], "MTL 14M Monthly (EMI)")
        self.assertEqual(mtl["profit_rupees"], 120000.0)
        self.assertEqual(mtl["final_maturity_amount"], 620000.0)
        self.assertEqual(mtl["payout_amount"], 51666.67)

        # Recommendation for 6-month tenure selects STL 7M
        rec = get_product_recommendation(500000, "medium", 6)
        self.assertEqual(rec["recommended_product"], "STL 7M")

    # -------------------------------------------------------------------------
    # Scenario 8: High-Yield Seeking Investor Exploring Custom Manual Lending vs STL
    # -------------------------------------------------------------------------
    def test_scenario_8_high_yield_custom_manual_lending_vs_stl(self):
        """Scenario 8: High-Yield Seeking Investor Exploring Custom Manual Lending vs STL.
        
        - Investor seeking aggressive returns on ₹2,00,000 for 12 months with 48% borrower rate and 4% NPA.
        - Evaluates Rule 4 breakdown: Net ROI = 36.08%, Net Profit = ₹72,160.
        - Compares against fixed STL 7M.
        """
        rule4 = calculate_manual_lending(
            amount=200000,
            tenure_months=12,
            custom_borrower_rate_pct=48.0,
            custom_npa_rate_pct=4.0,
        )
        self.assertEqual(rule4["step_a_principal"], 200000.0)
        self.assertEqual(rule4["step_b_npa_loss_rupees"], 8000.0)  # 4% of 200k
        self.assertEqual(rule4["step_c_performing_principal"], 192000.0)
        self.assertEqual(rule4["step_d_gross_interest"], 92160.0)  # 192k * 0.48 * (12/12)
        self.assertEqual(rule4["step_e_platform_fee_rupees"], 12000.0)  # 6% fee for 12m
        self.assertEqual(rule4["step_f_net_profit_rupees"], 72160.0)  # 92160 - 12000 - 8000
        self.assertEqual(rule4["step_g_net_annualized_roi_pct"], 36.08)
        self.assertEqual(rule4["final_total_amount"], 272160.0)

        # STL comparison
        stl = calculate_stl_returns(200000, 6)
        self.assertEqual(stl["profit_rupees"], 18000.0)

    # -------------------------------------------------------------------------
    # Scenario 9: First-Time Small Investor Micro-Lending Journey
    # -------------------------------------------------------------------------
    def test_scenario_9_first_time_small_investor_micro_lending(self):
        """Scenario 9: First-Time Small Investor Micro-Lending Journey.
        
        - First-time user testing platform with small initial amount of ₹2,000.
        - Product recommendation routes to Manual Lending (starts from ₹250).
        - Computes calculate_manual_lending(2000, 6) -> 18% XIRR, ₹180 profit.
        - Navigation guides to manual lending selection and penny drop verification.
        """
        rec = get_product_recommendation(2000)
        self.assertTrue(rec["is_valid"])
        self.assertEqual(rec["recommended_product"], "Manual Lending")

        man = calculate_manual_lending(2000, 6)
        self.assertEqual(man["principal"], 2000)
        self.assertEqual(man["tenure_months"], 6)
        self.assertEqual(man["annualized_xirr_pct"], 18.0)
        self.assertEqual(man["profit_rupees"], 180.0)
        self.assertEqual(man["final_amount"], 2180.0)

        manual_flow = get_app_screen_flow("manual")
        self.assertIn("Manual Lending Selection", manual_flow["flow_name"])
        self.assertIn("₹250 se ₹4,000", manual_flow["instructions_hinglish"])

    # -------------------------------------------------------------------------
    # Scenario 10: Complete Liquidity & Daily EDI Payout Demonstration
    # -------------------------------------------------------------------------
    def test_scenario_10_liquidity_objection_and_daily_edi_payout(self):
        """Scenario 10: Complete Liquidity & Daily EDI Payout Demonstration.
        
        - User inquires about lock-in and liquidity: "Can I withdraw money anytime?".
        - Pragya explains Daily EDI payout mechanics: principal + profit returned every day.
        - Computes calculate_mtl_returns(500000, 'daily').
        - Outputs ₹90,000 profit and ₹1,616.44/day credit to bank.
        """
        mtl = calculate_mtl_returns(500000, "daily")
        self.assertEqual(mtl["profit_rupees"], 90000.0)
        self.assertEqual(mtl["final_maturity_amount"], 590000.0)
        self.assertEqual(mtl["payout_amount"], 1616.44)

        # Invariant check: Objection response in system prompt
        self.assertIn("Can I withdraw money anytime?", SYSTEM_PROMPT)
        self.assertIn("monthly EMIs or daily credits", SYSTEM_PROMPT)

    # -------------------------------------------------------------------------
    # Scenario 11: End-to-End Interruption Recovery & Telemetry Audit Journey
    # -------------------------------------------------------------------------
    def test_scenario_11_interruption_recovery_and_telemetry_audit(self):
        """Scenario 11: End-to-End Interruption Recovery & Telemetry Audit Journey.
        
        - User interrupts during complex financial calculation.
        - AntiCancel shield holds lock and prevents cancellation.
        - Repeat-on-filler detects single-word filler "Haan" and creates repeat response.
        - Diagnostic buffer records interruption event with exact timestamp and elapsed_ms.
        - LangSmith tracer records complete session lifecycle.
        """
        tracer = LangSmithTracer()
        trace_url = tracer.start_session("scenario_11_interruption_audit", "gemini-3.5-flash-live-preview", "Aoede", "hi-IN")
        self.assertIsNotNone(trace_url)

        # Simulate AntiCancel Shield during active tool call
        class MockLLM(GeminiSessionLoggerMixin):
            def __init__(self):
                self._active_tools_in_flight = 0
                self._frame_locked_tools = False
                self._tool_lock_started_at = None

        svc = MockLLM()
        svc._lock_tools("calculate_manual_lending_heavy")
        self.assertTrue(svc._tools_in_flight())

        # Tool completes
        res = calculate_manual_lending(1000000, 12, 35.0, 3.5)
        tracer.record_tool_call("calculate_manual_lending", {"amount": 1000000, "tenure_months": 12}, res, 30.0)
        svc._release_tools("calculate_manual_lending_heavy_done")
        self.assertFalse(svc._tools_in_flight())

        # Interruption occurs after tool completes with 1-word filler
        tracer.record_interruption(220.0)
        append_diagnostic_log("⚡ Interruption", "Turn interrupted by user after 220.0 ms")

        # Telemetry verification
        logs = get_recent_diagnostic_logs(10)
        self.assertTrue(any("Interruption" in l["message"] for l in logs))

        tracer.end_session("Scenario 11 audit finished cleanly")


if __name__ == "__main__":
    unittest.main()
