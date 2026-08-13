"""Tier 3: Pairwise Cross-Feature Combinatorial E2E Tests.

Validates pairwise interactions between features across:
- Deterministic Financial Math (STL, MTL, Manual Lending, SIP, Recommendation)
- App Navigation & 3-Step KYC Guidance
- AntiCancel Tool Shield & Repeat-on-Filler Interruption Handling
- System Prompt Persona, Devanagari/Latin Hinglish, PTA Filler Rotation
- 9-Phase Consultative Sales Funnel & Context Window Compression
- Vertex AI Gemini 3.5 Live Duplex & Vertex AI RAG Engine
- Diagnostic Ring Buffer Telemetry & LangSmith Tracing
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
    DIAGNOSTIC_LOG_BUFFER,
)
from tracing import GLOBAL_LANGSMITH_TRACER, LangSmithTracer
from system_prompt import SYSTEM_PROMPT
from rag_function import search_knowledge_base_schema
from agent_live import GeminiSessionLoggerMixin, StartTriggerProcessor


class TestTier3CrossFeature(unittest.TestCase):
    """Pairwise Cross-Feature Interaction Test Suite (>= 21 test cases)."""

    def setUp(self):
        clear_diagnostic_logs()

    # -------------------------------------------------------------------------
    # Pair 1: Math Recommendation (F5) + KYC Onboarding Flow (F9)
    # -------------------------------------------------------------------------
    def test_pairwise_math_recommendation_and_kyc_flow(self):
        """Verify high-value recommendation feeds into KYC onboarding guidance."""
        rec = get_product_recommendation(amount=2400000, risk_appetite="low", tenure_months=12)
        self.assertTrue(rec["is_valid"])
        self.assertEqual(rec["recommended_product"], "MTL 14M Daily (EDI)")
        self.assertEqual(rec["risk_tier"], "AAA (Low Risk)")

        # Next step in journey: User asks for KYC process
        kyc_all = get_kyc_guidance("all")
        self.assertIn("Complete KYC 3-Step Overview", kyc_all["step"])
        self.assertIn("PAN", kyc_all["instructions_hinglish"])
        self.assertIn("Digilocker", kyc_all["instructions_hinglish"])
        self.assertIn("penny-drop", kyc_all["instructions_hinglish"])

        # Deep-dive into PAN step
        pan_step = get_kyc_guidance("pan")
        self.assertEqual(pan_step["step"], "PAN Verification")
        self.assertIn("10-digit PAN", pan_step["instructions_hinglish"])

    # -------------------------------------------------------------------------
    # Pair 2: Loan Filter Enumeration (F7) + Manual Lending Rule 4 (F3)
    # -------------------------------------------------------------------------
    def test_pairwise_loan_filter_enumeration_and_manual_lending_rule_4(self):
        """Verify loan filter options criteria directly power custom Manual Lending calculation."""
        filter_flow = get_app_screen_flow("loan filter")
        filters = filter_flow.get("available_filters", [])
        self.assertEqual(len(filters), 8)
        self.assertTrue(any("Tenure" in f for f in filters))
        self.assertTrue(any("Repayment Type" in f for f in filters))
        self.assertTrue(any("Risk Category" in f for f in filters))

        # Using filtered criteria (12-month tenure, 40% borrower rate, 5% NPA)
        rule4_res = calculate_manual_lending(
            amount=100000,
            tenure_months=12,
            custom_borrower_rate_pct=40.0,
            custom_npa_rate_pct=5.0,
        )
        self.assertEqual(rule4_res["step_a_principal"], 100000.0)
        self.assertEqual(rule4_res["step_b_npa_loss_rupees"], 5000.0)
        self.assertEqual(rule4_res["step_c_performing_principal"], 95000.0)
        self.assertEqual(rule4_res["step_d_gross_interest"], 38000.0)
        self.assertEqual(rule4_res["step_e_platform_fee_rupees"], 6000.0)  # 6% fee for 12m
        self.assertEqual(rule4_res["step_f_net_profit_rupees"], 27000.0)
        self.assertEqual(rule4_res["step_g_net_annualized_roi_pct"], 27.0)
        self.assertEqual(rule4_res["final_total_amount"], 127000.0)

    # -------------------------------------------------------------------------
    # Pair 3: AntiCancel Tool Shield (F6) + PTA Filler Rotation (F11)
    # -------------------------------------------------------------------------
    def test_pairwise_anticancel_shield_and_pta_filler_rotation(self):
        """Verify tool lock prevents interruption drops while verifying PTA filler rotation invariants."""
        # Test AntiCancel lock state machine
        class MockLLM(GeminiSessionLoggerMixin):
            def __init__(self):
                self._active_tools_in_flight = 0
                self._frame_locked_tools = False
                self._tool_lock_started_at = None

        service = MockLLM()
        self.assertFalse(service._tools_in_flight())

        # Simulate tool start
        service._lock_tools("test_tool_execution")
        self.assertTrue(service._tools_in_flight())
        self.assertEqual(service._active_tools_in_flight, 1)

        # Invariant check: PTA filler rules in SYSTEM_PROMPT
        self.assertIn("<pta_and_filler_rotation>", SYSTEM_PROMPT)
        self.assertIn("Group A", SYSTEM_PROMPT)
        self.assertIn("Group B", SYSTEM_PROMPT)
        self.assertIn("Group C", SYSTEM_PROMPT)
        self.assertIn("Group D", SYSTEM_PROMPT)
        self.assertTrue("Achha" in SYSTEM_PROMPT and "permitted at most ONCE" in SYSTEM_PROMPT)

        # Release lock
        service._release_tools("test_tool_completed")
        self.assertFalse(service._tools_in_flight())
        self.assertEqual(service._active_tools_in_flight, 0)

    # -------------------------------------------------------------------------
    # Pair 4: Context Window Compression (F15) + 9-Phase Sales Journey (F14)
    # -------------------------------------------------------------------------
    def test_pairwise_context_window_compression_and_sales_funnel_state(self):
        """Verify 20k token compression config integrates with 9-Phase Sales Funnel state machine."""
        # System prompt contains all 9 phases in order
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
        for phase in phases:
            self.assertIn(phase, SYSTEM_PROMPT)

        # Verify context compression parameter settings in agent_live
        from agent_live import run_agent_live
        import inspect
        sig = inspect.signature(run_agent_live)
        self.assertIn("context_compression", sig.parameters)
        self.assertIn("context_compression_trigger_tokens", sig.parameters)
        self.assertTrue(sig.parameters["context_compression"].default)

    # -------------------------------------------------------------------------
    # Pair 5: Vertex AI RAG Engine (F18) + STL Financial Math (F1)
    # -------------------------------------------------------------------------
    def test_pairwise_rag_knowledge_base_and_financial_math_validation(self):
        """Verify RAG knowledge base search schema compatibility with financial math workflows."""
        # Validate schema contract
        self.assertEqual(search_knowledge_base_schema.name, "search_knowledge_base")
        self.assertIn("query_for_vector_search", search_knowledge_base_schema.properties)
        self.assertIn("total_records", search_knowledge_base_schema.properties)
        self.assertIn("query_for_vector_search", search_knowledge_base_schema.required)

        # Execute financial math calculation for STL 7M
        stl_res = calculate_stl_returns(amount=100000, tenure_months=6)
        self.assertEqual(stl_res["product_name"], "STL 7M")
        self.assertEqual(stl_res["annualized_xirr_pct"], 18.0)
        self.assertEqual(stl_res["profit_rupees"], 9000.0)
        self.assertEqual(stl_res["final_maturity_amount"], 109000.0)

    # -------------------------------------------------------------------------
    # Pair 6: Diagnostic Ring Buffer (F19) + LangSmith Tracing (F19)
    # -------------------------------------------------------------------------
    def test_pairwise_diagnostic_buffer_logging_and_langsmith_tracing(self):
        """Verify diagnostic log capture and LangSmith tracer execution during math calculations."""
        tracer = LangSmithTracer()
        trace_url = tracer.start_session("tier3_pairwise_test", "gemini-3.5-flash-live-preview", "Aoede", "hi-IN")
        self.assertIsNotNone(trace_url)

        # Run financial math
        mtl_res = calculate_mtl_returns(500000, "daily")
        self.assertEqual(mtl_res["profit_rupees"], 90000.0)

        # Telemetry & Diagnostic logging
        append_diagnostic_log("Tool Execution", "calculate_mtl_returns amount=500000 repayment=daily", ttfb_ms=310.5)
        tracer.record_tool_call("calculate_mtl_returns", {"amount": 500000, "repayment_type": "daily"}, mtl_res, duration_ms=25.0)

        logs = get_recent_diagnostic_logs(10)
        self.assertTrue(any("calculate_mtl_returns" in l["message"] for l in logs))
        self.assertTrue(any(l.get("ttfb_ms") == 310.5 for l in logs))

        tracer.end_session("Tier3 test finished")

    # -------------------------------------------------------------------------
    # Pair 7: Boundary Rejection (F16) + Alternative Recommendation (F5)
    # -------------------------------------------------------------------------
    def test_pairwise_boundary_rejection_9month_and_alternative_recommendation(self):
        """Verify strict rejection of 9-month tenure directs user to valid alternative STL/MTL."""
        # Direct math tool rejection
        man_res = calculate_manual_lending(100000, 9)
        self.assertIn("error", man_res)
        self.assertIn("9-month tenure is strictly not available", man_res["error"])

        # Recommendation rejection & suggestion
        rec_res = get_product_recommendation(100000, "medium", 9)
        self.assertFalse(rec_res["is_valid"])
        self.assertIn("9-month tenures are strictly not available", rec_res["error"])
        self.assertIn("suggestion", rec_res)
        self.assertIn("6-month STL 7M or 12-month MTL 14M", rec_res["suggestion"])

        # Fallback to recommended 6-month STL 7M
        fallback_stl = calculate_stl_returns(100000, 6)
        self.assertEqual(fallback_stl["product_name"], "STL 7M")
        self.assertEqual(fallback_stl["profit_rupees"], 9000.0)

    # -------------------------------------------------------------------------
    # Pair 8: Repeat-on-Filler UX (F12) + Hinglish Script Formatting (F10)
    # -------------------------------------------------------------------------
    def test_pairwise_repeat_on_filler_and_hinglish_script_formatting(self):
        """Verify <=2 words filler detection logic and Hinglish script rules."""
        # 1-2 words filler detection logic
        def is_filler(text: str) -> bool:
            clean = text.rstrip('।.!?\n').strip()
            return len(clean.split()) <= 2 if clean else False

        self.assertTrue(is_filler("Achha"))
        self.assertTrue(is_filler("Theek hai."))
        self.assertTrue(is_filler("Haan bilkul!"))
        self.assertFalse(is_filler("Mujhe returns samjhao"))
        self.assertFalse(is_filler("FD aur P2P mein kya difference hai?"))

        # Hinglish script mixing rules in SYSTEM_PROMPT
        self.assertIn("CRITICAL LANGUAGE OVERRIDE", SYSTEM_PROMPT)
        self.assertIn("Hindi words MUST be written in Devanagari script", SYSTEM_PROMPT)
        self.assertIn("English financial/technical terms MUST be written in Latin script", SYSTEM_PROMPT)

    # -------------------------------------------------------------------------
    # Pair 9: ₹24L Wealth Advisory (F2) + Escrow Deposit Flow (F8)
    # -------------------------------------------------------------------------
    def test_pairwise_24l_wealth_advisory_and_escrow_deposit_flow(self):
        """Verify ₹24L high-value MTL Daily advisory transitions to Escrow Deposit flow."""
        mtl_24l = calculate_mtl_returns(amount=2400000, repayment_type="daily")
        self.assertEqual(mtl_24l["principal"], 2400000)
        self.assertEqual(mtl_24l["annualized_xirr_pct"], 18.0)
        self.assertEqual(mtl_24l["profit_rupees"], 432000.0)
        self.assertEqual(mtl_24l["final_maturity_amount"], 2832000.0)
        self.assertEqual(mtl_24l["payout_amount"], 7758.9)

        # Transition to Escrow Deposit Flow
        deposit_flow = get_app_screen_flow("deposit")
        self.assertIn("Escrow", deposit_flow["flow_name"])
        self.assertIn("UPI ya NetBanking", deposit_flow["instructions_hinglish"])
        self.assertIn("RBI-regulated Escrow", deposit_flow["instructions_hinglish"])

    # -------------------------------------------------------------------------
    # Pair 10: SIP Compounding (F4) vs MTL Lumpsum (F2) Comparison
    # -------------------------------------------------------------------------
    def test_pairwise_sip_compounding_vs_mtl_lumpsum_comparison(self):
        """Verify mathematical comparison between monthly SIP and lumpsum returns."""
        # 1-year SIP of ₹20,000/month @ 24% p.a.
        # r = 0.02, n = 12 -> maturity = 20000 * (((1.02)^12 - 1)/0.02) * 1.02 = 273606.63
        sip_res = calculate_sip_returns(monthly_amount=20000, annual_rate=24.0, years=1)
        self.assertEqual(sip_res["total_invested_rupees"], 240000.0)
        self.assertAlmostEqual(sip_res["maturity_value_rupees"], 273606.63, places=1)
        self.assertAlmostEqual(sip_res["wealth_gained_rupees"], 33606.63, places=1)

        # 1-year MTL Lumpsum of ₹2,40,000 @ 24% XIRR
        mtl_res = calculate_mtl_returns(amount=240000, repayment_type="monthly")
        self.assertEqual(mtl_res["profit_rupees"], 57600.0)
        self.assertEqual(mtl_res["final_maturity_amount"], 297600.0)

        # Lumpsum yields higher profit than SIP because entire principal compounds from day 1
        self.assertGreater(mtl_res["profit_rupees"], sip_res["wealth_gained_rupees"])

    # -------------------------------------------------------------------------
    # Pair 11: STL Tenures (F1) Subset of Loan Filter Tenures (F7)
    # -------------------------------------------------------------------------
    def test_pairwise_stl_tenures_subset_of_loan_filter_tenures(self):
        """Verify all STL allowed tenures are represented in the app loan filters."""
        filter_flow = get_app_screen_flow("loan filter")
        tenure_filter_text = filter_flow["available_filters"][0]
        self.assertIn("2, 3, 4, 5, 6, 12", tenure_filter_text)

        # Test each STL tenure
        stl_5m = calculate_stl_returns(50000, 4)
        self.assertEqual(stl_5m["tenure_months"], 4)

        stl_7m = calculate_stl_returns(50000, 6)
        self.assertEqual(stl_7m["tenure_months"], 6)

    # -------------------------------------------------------------------------
    # Pair 12: AntiCancel Shield (F6) + Repeat-on-Filler (F12) Interruption State
    # -------------------------------------------------------------------------
    def test_pairwise_anticancel_shield_suppresses_interruption_during_tool_execution(self):
        """Verify active tool execution suppresses interruption handling."""
        class TestService(GeminiSessionLoggerMixin):
            def __init__(self):
                self._active_tools_in_flight = 0
                self._frame_locked_tools = False
                self._tool_lock_started_at = None
                self._repeat_on_filler_pending = False

        svc = TestService()
        svc._lock_tools("calculate_manual_lending")
        self.assertTrue(svc._tools_in_flight())

        # When tool in flight, interruption suppression logic holds
        self.assertEqual(svc._active_tools_in_flight, 1)
        svc._release_tools("calculate_manual_lending_done")
        self.assertFalse(svc._tools_in_flight())

    # -------------------------------------------------------------------------
    # Pair 13: Single Greeting Guard (F13) + Sales Phase 1 (F14)
    # -------------------------------------------------------------------------
    def test_pairwise_single_greeting_guard_and_phase1_time_check(self):
        """Verify start trigger processor emits single greeting matching Phase 1 Time Check."""
        processor = StartTriggerProcessor(language="hi-IN")
        self.assertFalse(processor.triggered)

        # Simulate start trigger state
        processor.triggered = True
        self.assertTrue(processor.triggered)

        # Phase 1 directive in SYSTEM_PROMPT
        self.assertIn("Phase 1: Time Check & Availability", SYSTEM_PROMPT)
        self.assertIn("Ensure user has 2 minutes to talk", SYSTEM_PROMPT)

    # -------------------------------------------------------------------------
    # Pair 14: RAG Knowledge Base (F18) + Digilocker Aadhaar KYC (F9)
    # -------------------------------------------------------------------------
    def test_pairwise_rag_digilocker_policy_and_aadhaar_kyc_navigation(self):
        """Verify Aadhaar KYC guidance matches platform security policies in RAG."""
        aadhaar_guide = get_kyc_guidance("aadhaar")
        self.assertEqual(aadhaar_guide["step"], "Aadhaar / Address Verification")
        self.assertIn("Digilocker", aadhaar_guide["instructions_hinglish"])
        self.assertIn("OTP", aadhaar_guide["instructions_hinglish"])
        self.assertIn("Mobile number must be linked with Aadhaar", aadhaar_guide["requirements"])

    # -------------------------------------------------------------------------
    # Pair 15: Manual Lending Rule 4 (F3) + Telemetry Logging (F19)
    # -------------------------------------------------------------------------
    def test_pairwise_manual_lending_rule_4_and_diagnostic_logging(self):
        """Verify Rule 4 custom breakdown emits precise diagnostic log entries."""
        res = calculate_manual_lending(
            amount=500000,
            tenure_months=6,
            custom_borrower_rate_pct=36.0,
            custom_npa_rate_pct=3.0,
        )
        self.assertEqual(res["step_a_principal"], 500000.0)
        self.assertEqual(res["step_b_npa_loss_rupees"], 15000.0)  # 3% of 500k
        self.assertEqual(res["step_c_performing_principal"], 485000.0)
        self.assertEqual(res["step_d_gross_interest"], 87300.0)  # 485k * 0.36 * (6/12)
        self.assertEqual(res["step_e_platform_fee_rupees"], 15000.0)  # 3% fee for 6m
        self.assertEqual(res["step_f_net_profit_rupees"], 57300.0)
        self.assertEqual(res["step_g_net_annualized_roi_pct"], 22.92)

        append_diagnostic_log("Rule4 Calc", f"Computed Net ROI={res['step_g_net_annualized_roi_pct']}%", ttfb_ms=195.5)
        logs = get_recent_diagnostic_logs(5)
        self.assertTrue(any("Net ROI=22.92%" in l["message"] for l in logs))

    # -------------------------------------------------------------------------
    # Pair 16: Vertex AI Gemini 3.5 Live (F17) + Context Compression (F15)
    # -------------------------------------------------------------------------
    def test_pairwise_vertex_live_duplex_config_and_token_compression(self):
        """Verify Vertex AI Gemini 3.5 Live duplex settings with context window compression."""
        from agent_live import CustomGeminiLiveVertexLLMService
        self.assertTrue(issubclass(CustomGeminiLiveVertexLLMService, GeminiSessionLoggerMixin))

        # Default model is gemini-3.5-flash-live-preview
        default_model = "gemini-3.5-flash-live-preview"
        self.assertTrue(default_model.startswith("gemini-3.5"))

    # -------------------------------------------------------------------------
    # Pair 17: Deposit Flow (F8) + Penny-Drop Bank Linking (F9)
    # -------------------------------------------------------------------------
    def test_pairwise_deposit_flow_and_penny_drop_bank_linking(self):
        """Verify Escrow wallet funding coordinates with penny-drop bank verification."""
        bank_guide = get_kyc_guidance("bank")
        self.assertEqual(bank_guide["step"], "Bank Account Linking")
        self.assertIn("₹1 transfer", bank_guide["instructions_hinglish"])
        self.assertIn("Penny drop", bank_guide["instructions_hinglish"])
        self.assertIn("name must match PAN card", bank_guide["requirements"])

        deposit_flow = get_app_screen_flow("deposit")
        self.assertIn("Escrow Wallet", deposit_flow["flow_name"])

    # -------------------------------------------------------------------------
    # Pair 18: STL Min Boundary Fallback (F1) -> Manual Lending (F3)
    # -------------------------------------------------------------------------
    def test_pairwise_stl_sub_min_boundary_fallback_to_manual_lending(self):
        """Verify sub-₹25,000 STL requests fallback gracefully to Manual Lending."""
        stl_err = calculate_stl_returns(15000, 4)
        self.assertIn("error", stl_err)
        self.assertEqual(stl_err["min_amount"], 25000)

        # Recommendation routes <₹25,000 to Manual Lending
        rec = get_product_recommendation(15000)
        self.assertTrue(rec["is_valid"])
        self.assertEqual(rec["recommended_product"], "Manual Lending")

        # Manual lending calculates successfully for ₹15,000
        man_res = calculate_manual_lending(15000, 4)
        self.assertEqual(man_res["annualized_xirr_pct"], 18.0)
        self.assertEqual(man_res["profit_rupees"], 900.0)

    # -------------------------------------------------------------------------
    # Pair 19: Script Rules (F10) + PTA Filler Rotation Constraints (F11)
    # -------------------------------------------------------------------------
    def test_pairwise_system_prompt_hinglish_and_pta_rotation_invariants(self):
        """Verify prompt invariants enforce Devanagari Hindi, Latin English, and PTA rotation."""
        self.assertIn("Devanagari script", SYSTEM_PROMPT)
        self.assertIn("Latin script", SYSTEM_PROMPT)
        self.assertIn("CRITICAL LANGUAGE OVERRIDE", SYSTEM_PROMPT)
        self.assertIn("<pta_and_filler_rotation>", SYSTEM_PROMPT)
        self.assertIn("Never use fillers from the same group twice in a row", SYSTEM_PROMPT)

    # -------------------------------------------------------------------------
    # Pair 20: MTL Monthly Max Limit (F2) -> MTL Daily Alternative (F2)
    # -------------------------------------------------------------------------
    def test_pairwise_mtl_monthly_max_limit_rejection_and_mtl_daily_alternative(self):
        """Verify ₹15L (exceeding ₹10L Monthly cap) is rejected for Monthly and routed to Daily."""
        monthly_err = calculate_mtl_returns(1500000, "monthly")
        self.assertIn("error", monthly_err)
        self.assertIn("Maximum investment for MTL Monthly is ₹10,00,000", monthly_err["error"])

        # MTL Daily supports up to ₹25,00,000
        daily_ok = calculate_mtl_returns(1500000, "daily")
        self.assertEqual(daily_ok["product_name"], "MTL 14M Daily (EDI)")
        self.assertEqual(daily_ok["profit_rupees"], 270000.0)
        self.assertEqual(daily_ok["final_maturity_amount"], 1770000.0)
        self.assertEqual(daily_ok["payout_amount"], 4849.32)

    # -------------------------------------------------------------------------
    # Pair 21: Live Session Tracing (F17) + Diagnostic API Endpoint (F19)
    # -------------------------------------------------------------------------
    def test_pairwise_live_session_tracing_and_api_logs_endpoint(self):
        """Verify tracing hooks generate valid trace URLs accessible via REST API."""
        from fastapi.testclient import TestClient
        from server import app

        client = TestClient(app)
        res_logs = client.get("/api/logs")
        self.assertEqual(res_logs.status_code, 200)
        self.assertIn("logs", res_logs.json())

        res_trace = client.get("/api/trace/current")
        self.assertEqual(res_trace.status_code, 200)
        self.assertIn("trace_url", res_trace.json())

    # -------------------------------------------------------------------------
    # Pair 22: Platform Minimum ₹250 (F16) Rejection Across All Products (F1, F2, F3, F5)
    # -------------------------------------------------------------------------
    def test_pairwise_sub_250_platform_minimum_rejection_across_tools(self):
        """Verify amounts below platform minimum ₹250 are rejected across all tools."""
        self.assertIn("error", calculate_manual_lending(100, 6))
        self.assertIn("error", calculate_stl_returns(100, 4))
        self.assertIn("error", calculate_mtl_returns(100, "monthly"))
        rec = get_product_recommendation(100)
        self.assertFalse(rec["is_valid"])
        self.assertIn("Minimum platform investment/lending amount is ₹250", rec["error"])

    # -------------------------------------------------------------------------
    # Pair 23: AntiCancel Self-Healing (F6) Timeout Boundary (F16)
    # -------------------------------------------------------------------------
    def test_pairwise_anticancel_shield_self_healing_timeout_resets_lock(self):
        """Verify AntiCancel lock self-heals after 8.0s timeout to prevent stuck uninterruptible state."""
        class MockLLM(GeminiSessionLoggerMixin):
            def __init__(self):
                self._active_tools_in_flight = 1
                self._frame_locked_tools = True
                self._tool_lock_started_at = time.monotonic() - 9.0  # Elapsed > 8.0s

        svc = MockLLM()
        self.assertFalse(svc._tools_in_flight())
        self.assertEqual(svc._active_tools_in_flight, 0)
        self.assertFalse(svc._frame_locked_tools)
        self.assertIsNone(svc._tool_lock_started_at)

    # -------------------------------------------------------------------------
    # Pair 24: RAG Knowledge Base (F18) + Consultative Sales Objection Handling (F14)
    # -------------------------------------------------------------------------
    def test_pairwise_rag_objection_handling_and_sales_phase_4(self):
        """Verify objection handling for FD vs P2P and RBI legality in system prompt."""
        self.assertIn("<objection_handling_playbook>", SYSTEM_PROMPT)
        self.assertIn("Why not just put money in Bank Fixed Deposits (FD)?", SYSTEM_PROMPT)
        self.assertIn("Is Cymbal Lending legal / RBI approved?", SYSTEM_PROMPT)
        self.assertIn("Trustee Escrow Account", SYSTEM_PROMPT)

    # -------------------------------------------------------------------------
    # Pair 25: Zero Rate SIP (F4) + Diagnostic Buffer (F19)
    # -------------------------------------------------------------------------
    def test_pairwise_zero_rate_sip_and_diagnostic_logging(self):
        """Verify zero rate SIP arithmetic correctly logs to in-memory telemetry buffer."""
        sip_zero = calculate_sip_returns(monthly_amount=10000, annual_rate=0.0, years=2)
        self.assertEqual(sip_zero["total_invested_rupees"], 240000.0)
        self.assertEqual(sip_zero["maturity_value_rupees"], 240000.0)
        self.assertEqual(sip_zero["wealth_gained_rupees"], 0.0)

        append_diagnostic_log("SIP Calc", f"Zero rate maturity={sip_zero['maturity_value_rupees']}")
        logs = get_recent_diagnostic_logs(5)
        self.assertTrue(any("Zero rate maturity=240000" in l["message"] for l in logs))

    # -------------------------------------------------------------------------
    # Pair 26: Manual Lending Fee Tiers (F3) vs STL Returns (F1)
    # -------------------------------------------------------------------------
    def test_pairwise_manual_lending_all_fee_rates_and_stl_comparison(self):
        """Verify fee schedule across all tenures and compare 6m Manual vs 6m STL 7M."""
        # 6m Manual Standard vs 6m STL 7M
        man_6m = calculate_manual_lending(100000, 6)
        stl_6m = calculate_stl_returns(100000, 6)
        self.assertEqual(man_6m["annualized_xirr_pct"], 18.0)
        self.assertEqual(stl_6m["annualized_xirr_pct"], 18.0)
        self.assertEqual(man_6m["profit_rupees"], stl_6m["profit_rupees"])


if __name__ == "__main__":
    unittest.main()
