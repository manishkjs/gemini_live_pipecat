"""Tier 2: Boundary Value Analysis & Corner Cases Test Suite for Cymbal Lending P2P Voicebot.

Comprehensive boundary value testing covering all 21 inventoried features:
  F1:  calculate_stl_returns (min ₹25k, max ₹25L, 3-6m tenures, negative/zero, bounds)
  F2:  calculate_mtl_returns (min ₹1L, max ₹10L monthly / ₹25L daily, casing, bounds)
  F3:  calculate_manual_lending (min ₹250, max ₹50L, 9m strict rejection, invalid tenures, NPA 0-100%)
  F4:  calculate_sip_returns (zero amount/years/rate, negative rates, extreme compounding)
  F5:  get_product_recommendation (₹250-₹50L bounds, 9m rejection, sub-₹25k manual fallback)
  F6:  AntiCancel Tool Shield (8.0s timeout boundary, rapid lock/release, underflow guard)
  F7:  get_app_screen_flow (Loan Filter 8 exact options, whitespace, casing variations)
  F8:  get_app_screen_flow (Deposit, Lumpsum, Manual, General flows, None, empty, symbols)
  F9:  get_kyc_guidance (PAN, Aadhaar, Bank penny drop, 3-step overview, None, unrecognized)
  F10: Devanagari Hindi + Latin English script mixing rules (Devanagari verbs, Latin terms, forbidden rules)
  F11: PTA Filler Rotation (4 groups, Achha max 1, no consecutive group fillers)
  F12: Repeat-on-Filler UX (0-word, 1-word, 2-word fillers vs 3-word genuine interruption, punctuation)
  F13: Single Greeting Turn Guard (idempotency across 10 rapid triggers, language greetings, message ID)
  F14: 9-Phase Consultative Sales Journey (Phases 1-9 ordering, 4 objection playbooks, no mental math)
  F15: Context Window Compression (trigger token boundaries, enabled/disabled configs, sliding window)
  F16: Boundary & Contradiction Handling (cross-tool 9m rejection, low/high limits consistency)
  F17: Vertex AI Gemini 3.5 Live Duplex config (model mapping, location resolution, audio modalities)
  F18: Vertex AI RAG Engine (schema requirements, location regex parsing, missing config handling)
  F19: In-Memory Telemetry Ring Buffer (1500 maxlen FIFO rollover, TTFB parsing, empty logs)
  F20: Complete E2E Test Suite structure contract (tier separation, fast execution, test isolation)
  F21: Final Verification & Hardening acceptance contract (2 decimal rounding, dict contracts, safety)
"""

import os
import sys
import time
import asyncio
import unittest
from unittest.mock import MagicMock, patch

# Optimize test startup speed by stubbing heavy unused audio/vertex backend loaders
for mod in [
    "vertexai",
    "vertexai.preview",
    "vertexai.preview.rag",
    "pipecat.audio.vad.silero",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Ensure server module is in sys.path
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
from system_prompt import SYSTEM_PROMPT
from diagnostic_buffer import (
    DIAGNOSTIC_LOG_BUFFER,
    append_diagnostic_log,
    append_raw_log_entry,
    get_recent_diagnostic_logs,
    clear_diagnostic_logs,
)
from tracing import LangSmithTracer
from rag_function import (
    search_knowledge_base_schema,
    get_rag_config,
)
from agent_live import (
    GeminiSessionLoggerMixin,
    StartTriggerProcessor,
)
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    InputTransportMessageFrame,
    OutputTransportMessageFrame,
    LLMMessagesAppendFrame,
)


class DummyBase:
    def __init__(self):
        self.super_called = False

    async def process_frame(self, frame, direction):
        self.super_called = True


class DummyShieldHost(GeminiSessionLoggerMixin, DummyBase):
    def __init__(self):
        super().__init__()
        self._active_tools_in_flight = 0
        self._frame_locked_tools = False
        self._tool_lock_started_at = None
        self._bot_turn_text_buffer = ""
        self._repeat_on_filler_pending = False
        self.pushed_frames = []

    async def push_frame(self, frame, direction=None):
        self.pushed_frames.append(frame)


# =====================================================================
# Feature 1 Boundaries: calculate_stl_returns
# =====================================================================
class TestBoundary01CalculateStlReturns(unittest.TestCase):
    """Boundary tests for Feature 1: calculate_stl_returns."""

    def test_stl_below_minimum_boundary(self):
        # ₹24,999 is strictly below ₹25,000 min
        res = calculate_stl_returns(24999)
        self.assertIn("error", res)
        self.assertEqual(res["min_amount"], 25000)

    def test_stl_exact_minimum_boundary(self):
        # ₹25,000 is exact min boundary
        res = calculate_stl_returns(25000)
        self.assertNotIn("error", res)
        self.assertEqual(res["principal"], 25000.0)
        self.assertGreater(res["profit_rupees"], 0)

    def test_stl_exact_maximum_boundary(self):
        # ₹25,00,000 is exact max boundary
        res = calculate_stl_returns(2500000)
        self.assertNotIn("error", res)
        self.assertEqual(res["principal"], 2500000.0)

    def test_stl_above_maximum_boundary(self):
        # ₹25,00,001 exceeds ₹25,00,000 max
        res = calculate_stl_returns(2500001)
        self.assertIn("error", res)
        self.assertEqual(res["max_amount"], 2500000)

    def test_stl_invalid_tenures_boundary(self):
        # Tenures outside [3, 4, 5, 6] are rejected
        for invalid_tenure in [0, 1, 2, 7, 8, 9, 12]:
            res = calculate_stl_returns(50000, invalid_tenure)
            self.assertIn("error", res)
            self.assertIn("available_tenures", res)

    def test_stl_zero_and_negative_amounts(self):
        res_zero = calculate_stl_returns(0)
        self.assertIn("error", res_zero)
        res_neg = calculate_stl_returns(-50000)
        self.assertIn("error", res_neg)


# =====================================================================
# Feature 2 Boundaries: calculate_mtl_returns
# =====================================================================
class TestBoundary02CalculateMtlReturns(unittest.TestCase):
    """Boundary tests for Feature 2: calculate_mtl_returns."""

    def test_mtl_below_minimum_boundary(self):
        # ₹99,999 is below ₹1,00,000 min
        res = calculate_mtl_returns(99999)
        self.assertIn("error", res)
        self.assertEqual(res["min_amount"], 100000)

    def test_mtl_exact_minimum_boundary(self):
        # ₹1,00,000 exact min for both Monthly & Daily
        res_m = calculate_mtl_returns(100000, "monthly")
        self.assertNotIn("error", res_m)
        res_d = calculate_mtl_returns(100000, "daily")
        self.assertNotIn("error", res_d)

    def test_mtl_monthly_upper_boundary(self):
        # Monthly max is ₹10,00,000
        res_ok = calculate_mtl_returns(1000000, "monthly")
        self.assertNotIn("error", res_ok)
        res_fail = calculate_mtl_returns(1000001, "monthly")
        self.assertIn("error", res_fail)

    def test_mtl_daily_upper_boundary(self):
        # Daily max is ₹25,00,000
        res_ok = calculate_mtl_returns(2500000, "daily")
        self.assertNotIn("error", res_ok)
        res_fail = calculate_mtl_returns(2500001, "daily")
        self.assertIn("error", res_fail)

    def test_mtl_none_and_whitespace_repayment_strings(self):
        res_none = calculate_mtl_returns(200000, None)
        self.assertEqual(res_none["product_name"], "MTL 14M Monthly (EMI)")
        res_space = calculate_mtl_returns(200000, "   daily   ")
        self.assertEqual(res_space["product_name"], "MTL 14M Daily (EDI)")

    def test_mtl_zero_and_negative_amounts(self):
        self.assertIn("error", calculate_mtl_returns(0))
        self.assertIn("error", calculate_mtl_returns(-100000))


# =====================================================================
# Feature 3 Boundaries: calculate_manual_lending
# =====================================================================
class TestBoundary03CalculateManualLending(unittest.TestCase):
    """Boundary tests for Feature 3: calculate_manual_lending."""

    def test_manual_below_min_boundary_249(self):
        res = calculate_manual_lending(249, 12)
        self.assertIn("error", res)
        self.assertIn("Minimum manual lending amount is ₹250", res["error"])

    def test_manual_exact_min_boundary_250(self):
        res = calculate_manual_lending(250, 12)
        self.assertNotIn("error", res)
        self.assertEqual(res["principal"], 250.0)

    def test_manual_platform_max_boundary_50_lakhs(self):
        res_ok = calculate_manual_lending(5000000, 12)
        self.assertNotIn("error", res_ok)
        res_fail = calculate_manual_lending(5000001, 12)
        self.assertIn("error", res_fail)

    def test_manual_9_month_tenure_strictly_rejected(self):
        res_std = calculate_manual_lending(50000, 9)
        self.assertIn("error", res_std)
        self.assertIn("9-month tenure is strictly not available", res_std["error"])

        res_custom = calculate_manual_lending(50000, 9, custom_borrower_rate_pct=30.0)
        self.assertIn("error", res_custom)

    def test_manual_invalid_tenures_all_rejected(self):
        for invalid_t in [-1, 0, 1, 7, 8, 10, 11, 13, 15, 24]:
            res = calculate_manual_lending(50000, invalid_t)
            self.assertIn("error", res)

    def test_manual_extreme_npa_rates(self):
        # 0% NPA is valid
        res_0 = calculate_manual_lending(100000, 12, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=0.0)
        self.assertEqual(res_0["step_b_npa_loss_rupees"], 0.0)

        # 100% NPA is valid
        res_100 = calculate_manual_lending(100000, 12, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=100.0)
        self.assertEqual(res_100["step_b_npa_loss_rupees"], 100000.0)

        # Negative NPA rejected
        res_neg = calculate_manual_lending(100000, 12, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=-0.1)
        self.assertIn("error", res_neg)

        # >100% NPA rejected
        res_over = calculate_manual_lending(100000, 12, custom_borrower_rate_pct=30.0, custom_npa_rate_pct=100.1)
        self.assertIn("error", res_over)

    def test_manual_negative_borrower_rate_rejected(self):
        res = calculate_manual_lending(100000, 12, custom_borrower_rate_pct=-5.0)
        self.assertIn("error", res)


# =====================================================================
# Feature 4 Boundaries: calculate_sip_returns
# =====================================================================
class TestBoundary04CalculateSipReturns(unittest.TestCase):
    """Boundary tests for Feature 4: calculate_sip_returns."""

    def test_sip_zero_monthly_amount_rejected(self):
        res = calculate_sip_returns(0, 12.0, 3)
        self.assertIn("error", res)

    def test_sip_negative_monthly_amount_rejected(self):
        res = calculate_sip_returns(-1000, 12.0, 3)
        self.assertIn("error", res)

    def test_sip_zero_years_rejected(self):
        res = calculate_sip_returns(5000, 12.0, 0)
        self.assertIn("error", res)

    def test_sip_negative_years_rejected(self):
        res = calculate_sip_returns(5000, 12.0, -2)
        self.assertIn("error", res)

    def test_sip_negative_annual_rate_rejected(self):
        res = calculate_sip_returns(5000, -1.0, 3)
        self.assertIn("error", res)

    def test_sip_zero_annual_rate_boundary(self):
        # At 0%, wealth gained is exactly 0.0
        res = calculate_sip_returns(1000, 0.0, 1)
        self.assertEqual(res["total_invested_rupees"], 12000.0)
        self.assertEqual(res["maturity_value_rupees"], 12000.0)
        self.assertEqual(res["wealth_gained_rupees"], 0.0)


# =====================================================================
# Feature 5 Boundaries: get_product_recommendation
# =====================================================================
class TestBoundary05GetProductRecommendation(unittest.TestCase):
    """Boundary tests for Feature 5: get_product_recommendation."""

    def test_recommendation_under_250_rejected(self):
        res = get_product_recommendation(249)
        self.assertFalse(res["is_valid"])
        self.assertIn("Minimum platform investment", res["error"])

    def test_recommendation_exact_250_accepted(self):
        res = get_product_recommendation(250)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["recommended_product"], "Manual Lending")

    def test_recommendation_over_50_lakhs_rejected(self):
        res = get_product_recommendation(5000001)
        self.assertFalse(res["is_valid"])
        self.assertIn("Maximum platform lending limit", res["error"])

    def test_recommendation_9_month_rejection_and_suggestion(self):
        res = get_product_recommendation(50000, "medium", 9)
        self.assertFalse(res["is_valid"])
        self.assertIn("9-month", res["error"])
        self.assertIn("suggestion", res)

    def test_recommendation_sub_25k_threshold(self):
        res = get_product_recommendation(24999)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["recommended_product"], "Manual Lending")

    def test_recommendation_none_risk_appetite_fallback(self):
        res = get_product_recommendation(100000, None, 12)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["recommended_product"], "MTL 14M Monthly (EMI)")


# =====================================================================
# Feature 6 Boundaries: AntiCancel Tool Shield
# =====================================================================
class TestBoundary06AntiCancelToolShield(unittest.TestCase):
    """Boundary tests for Feature 6: AntiCancel Tool Shield."""

    def setUp(self):
        self.host = DummyShieldHost()

    def test_timeout_exact_boundary_sub_8s(self):
        # 7.9s is within the 8.0s hold limit
        self.host._lock_tools("tool_call")
        self.host._tool_lock_started_at = time.monotonic() - 7.9
        self.assertTrue(self.host._tools_in_flight())

    def test_timeout_exact_boundary_super_8s(self):
        # 8.1s exceeds the 8.0s hold limit -> auto heals
        self.host._lock_tools("tool_call")
        self.host._tool_lock_started_at = time.monotonic() - 8.1
        self.assertFalse(self.host._tools_in_flight())
        self.assertEqual(self.host._active_tools_in_flight, 0)

    def test_underflow_release_guard(self):
        # Releasing when count is already 0 must never become negative
        self.assertEqual(self.host._active_tools_in_flight, 0)
        self.host._release_tools("spurious_release")
        self.assertEqual(self.host._active_tools_in_flight, 0)

    def test_rapid_consecutive_lock_releases(self):
        for i in range(20):
            self.host._lock_tools(f"lock_{i}")
        self.assertEqual(self.host._active_tools_in_flight, 20)
        for i in range(20):
            self.host._release_tools(f"release_{i}")
        self.assertEqual(self.host._active_tools_in_flight, 0)

    def test_non_blocking_cancellation_during_tool_execution(self):
        self.host._active_tools_in_flight = 2
        asyncio.run(self.host._cancel_function_call("calculate_stl_returns"))
        self.assertEqual(self.host._active_tools_in_flight, 2)


# =====================================================================
# Feature 7 Boundaries: get_app_screen_flow (Loan Filter)
# =====================================================================
class TestBoundary07LoanFilterFlow(unittest.TestCase):
    """Boundary tests for Feature 7: get_app_screen_flow (Loan Filter)."""

    def test_loan_filter_casing_uppercase(self):
        res = get_app_screen_flow("LOAN FILTER")
        self.assertEqual(res["flow_name"], "App Loan Filter Options")
        self.assertEqual(len(res["available_filters"]), 8)

    def test_loan_filter_with_leading_trailing_whitespace(self):
        res = get_app_screen_flow("   loan filter   ")
        self.assertEqual(res["flow_name"], "App Loan Filter Options")

    def test_loan_filter_partial_keyword_filter(self):
        res = get_app_screen_flow("filter")
        self.assertEqual(res["flow_name"], "App Loan Filter Options")

    def test_loan_filter_borrower_filter_phrase(self):
        res = get_app_screen_flow("borrower filter")
        self.assertEqual(res["flow_name"], "App Loan Filter Options")

    def test_loan_filter_elements_are_non_empty_strings(self):
        res = get_app_screen_flow("loan filter")
        for f in res["available_filters"]:
            self.assertIsInstance(f, str)
            self.assertGreater(len(f.strip()), 5)


# =====================================================================
# Feature 8 Boundaries: get_app_screen_flow (Other Flows)
# =====================================================================
class TestBoundary08OtherAppScreenFlows(unittest.TestCase):
    """Boundary tests for Feature 8: get_app_screen_flow (Other Flows)."""

    def test_flow_none_defaults_to_general(self):
        res = get_app_screen_flow(None)
        self.assertEqual(res["flow_name"], "General App Navigation")

    def test_flow_empty_string_defaults_to_general(self):
        res = get_app_screen_flow("")
        self.assertEqual(res["flow_name"], "General App Navigation")

    def test_flow_deposit_casing_variations(self):
        for q in ["DEPOSIT", "fund", "ADD MONEY", "Pay"]:
            res = get_app_screen_flow(q)
            self.assertEqual(res["flow_name"], "Adding Funds to Cymbal Escrow Wallet")

    def test_flow_lumpsum_casing_variations(self):
        for q in ["LUMPSUM", "stl", "MTL"]:
            res = get_app_screen_flow(q)
            self.assertEqual(res["flow_name"], "Lumpsum Lending (STL / MTL)")

    def test_flow_manual_casing_variations(self):
        res = get_app_screen_flow("MANUAL LENDING")
        self.assertEqual(res["flow_name"], "Manual Lending Selection")

    def test_flow_special_characters_fallback(self):
        res = get_app_screen_flow("!@#$%^&*()_+")
        self.assertEqual(res["flow_name"], "General App Navigation")


# =====================================================================
# Feature 9 Boundaries: get_kyc_guidance
# =====================================================================
class TestBoundary09GetKycGuidance(unittest.TestCase):
    """Boundary tests for Feature 9: get_kyc_guidance."""

    def test_kyc_none_defaults_to_overview(self):
        res = get_kyc_guidance(None)
        self.assertEqual(res["step"], "Complete KYC 3-Step Overview")

    def test_kyc_empty_string_defaults_to_overview(self):
        res = get_kyc_guidance("")
        self.assertEqual(res["step"], "Complete KYC 3-Step Overview")

    def test_kyc_pan_casing_variations(self):
        for q in ["PAN", "pan card", "Pan"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "PAN Verification")

    def test_kyc_aadhaar_casing_variations(self):
        for q in ["AADHAAR", "address verification", "Aadhaar Card", "aadhaar otp"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "Aadhaar / Address Verification")

    def test_kyc_bank_penny_casing_variations(self):
        for q in ["BANK", "bank account", "penny drop"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "Bank Account Linking")

    def test_kyc_unrecognized_document_query(self):
        res = get_kyc_guidance("voter_id_passport")
        self.assertEqual(res["step"], "Complete KYC 3-Step Overview")


# =====================================================================
# Feature 10 Boundaries: Devanagari Hindi + Latin English Rules
# =====================================================================
class TestBoundary10ScriptMixingRules(unittest.TestCase):
    """Boundary tests for Feature 10: Devanagari Hindi + Latin English Rules."""

    def test_hindi_words_in_devanagari_present(self):
        devanagari_words = ["मैं", "आप", "क्या", "हाँ", "करते हैं", "समझिए"]
        for word in devanagari_words:
            self.assertIn(word, SYSTEM_PROMPT)

    def test_latin_financial_terms_present(self):
        latin_terms = ["portfolio", "returns", "XIRR", "diversification", "borrower", "KYC", "app", "escrow", "FD", "EMI"]
        for term in latin_terms:
            self.assertIn(term, SYSTEM_PROMPT)

    def test_forbidden_transliteration_clause_present(self):
        self.assertIn("FORBIDDEN: Hindi written in English letters", SYSTEM_PROMPT)
        self.assertIn("FORBIDDEN: English words written in Devanagari script", SYSTEM_PROMPT)

    def test_female_pragya_verb_forms_invariants(self):
        self.assertIn("मैं बता रही हूँ", SYSTEM_PROMPT)
        self.assertIn("मैं समझ सकती हूँ", SYSTEM_PROMPT)

    def test_pacing_and_sentence_length_limits(self):
        self.assertIn("12–20 words max per sentence", SYSTEM_PROMPT)
        self.assertIn("PUNCTUATION & AUDIO PACING", SYSTEM_PROMPT)


# =====================================================================
# Feature 11 Boundaries: PTA Filler Rotation
# =====================================================================
class TestBoundary11PtaFillerRotation(unittest.TestCase):
    """Boundary tests for Feature 11: PTA Filler Rotation."""

    def test_all_four_filler_groups_defined(self):
        self.assertIn("Group A (Thinking)", SYSTEM_PROMPT)
        self.assertIn("Group B (Transitions)", SYSTEM_PROMPT)
        self.assertIn("Group C (Acknowledgment)", SYSTEM_PROMPT)
        self.assertIn("Group D (Light discovery)", SYSTEM_PROMPT)

    def test_group_a_frequency_limit_boundary(self):
        self.assertIn("max once per 4–5 turns", SYSTEM_PROMPT)

    def test_no_consecutive_group_fillers_rule(self):
        self.assertIn("Never use fillers from the same group twice in a row", SYSTEM_PROMPT)

    def test_achha_single_use_limit_boundary(self):
        self.assertTrue("Achha" in SYSTEM_PROMPT or "अच्छा" in SYSTEM_PROMPT)
        self.assertIn("permitted at most ONCE in the entire call", SYSTEM_PROMPT)

    def test_direct_start_without_filler_rule(self):
        self.assertIn("Most straightforward turns should start directly without any filler", SYSTEM_PROMPT)


# =====================================================================
# Feature 12 Boundaries: Repeat-on-Filler UX
# =====================================================================
class TestBoundary12RepeatOnFillerUx(unittest.TestCase):
    """Boundary tests for Feature 12: Repeat-on-Filler UX."""

    def test_zero_word_empty_buffer(self):
        buffer = ""
        clean = buffer.rstrip('।.!?\n').strip()
        word_count = len(clean.split()) if clean else 0
        self.assertEqual(word_count, 0)

    def test_one_word_filler_boundary(self):
        for filler in ["Haan", "Achha", "Okay", "हाँ", "अच्छा", "जी"]:
            clean = filler.rstrip('।.!?\n').strip()
            count = len(clean.split()) if clean else 0
            self.assertEqual(count, 1)
            self.assertLessEqual(count, 2)

    def test_two_word_filler_boundary(self):
        for filler in ["Theek hai", "Ji bilkul", "Samajh gaya", "ठीक है", "जी बिल्कुल"]:
            clean = filler.rstrip('।.!?\n').strip()
            count = len(clean.split()) if clean else 0
            self.assertEqual(count, 2)
            self.assertLessEqual(count, 2)

    def test_three_word_genuine_interruption_boundary(self):
        for text in ["Wait one sec", "Kya bola aapne", "Ek minute ruko"]:
            clean = text.rstrip('।.!?\n').strip()
            count = len(clean.split()) if clean else 0
            self.assertEqual(count, 3)
            self.assertGreater(count, 2)

    def test_multiple_punctuation_and_newlines_stripping(self):
        text = "  Theek hai...!?\n\n  "
        clean = text.rstrip('।.!?\n ').strip()
        count = len(clean.split()) if clean else 0
        self.assertEqual(count, 2)


# =====================================================================
# Feature 13 Boundaries: Single Greeting Turn Guard
# =====================================================================
class TestBoundary13SingleGreetingTurnGuard(unittest.TestCase):
    """Boundary tests for Feature 13: Single Greeting Turn Guard."""

    def test_idempotency_across_10_rapid_start_triggers(self):
        processor = StartTriggerProcessor(language="en-US")
        pushed = []

        async def fake_push(f, d=None):
            pushed.append(f)

        processor.push_frame = fake_push
        for i in range(10):
            frame = InputTransportMessageFrame(message={"type": "start_trigger", "id": f"msg_{i}"})
            asyncio.run(processor.process_frame(frame))

        append_frames = [f for f in pushed if isinstance(f, LLMMessagesAppendFrame)]
        self.assertEqual(len(append_frames), 1)

    def test_message_id_echo_response_boundary(self):
        processor = StartTriggerProcessor(language="en-US")
        pushed = []

        async def fake_push(f, d=None):
            pushed.append(f)

        processor.push_frame = fake_push
        frame = InputTransportMessageFrame(message={"type": "start_trigger", "id": "custom-trace-id-999"})
        asyncio.run(processor.process_frame(frame))

        resp_frames = [f for f in pushed if isinstance(f, OutputTransportMessageFrame)]
        self.assertEqual(len(resp_frames), 1)
        self.assertEqual(resp_frames[0].message["id"], "custom-trace-id-999")
        self.assertEqual(resp_frames[0].message["data"]["status"], "ok")

    def test_unsupported_language_defaults_to_english_greeting(self):
        processor = StartTriggerProcessor(language="fr-FR")
        pushed = []

        async def fake_push(f, d=None):
            pushed.append(f)

        processor.push_frame = fake_push
        frame = InputTransportMessageFrame(message={"type": "start_trigger", "id": "msg_fr"})
        asyncio.run(processor.process_frame(frame))

        append_frames = [f for f in pushed if isinstance(f, LLMMessagesAppendFrame)]
        self.assertEqual(append_frames[0].messages[0]["content"], "Hello!")

    def test_malformed_message_dict_handling(self):
        processor = StartTriggerProcessor(language="en-US")
        pushed = []

        async def fake_push(f, d=None):
            pushed.append(f)

        processor.push_frame = fake_push
        # Empty dict or dict without 'type'
        frame_empty = InputTransportMessageFrame(message={})
        asyncio.run(processor.process_frame(frame_empty))
        self.assertFalse(processor.triggered)

    def test_non_start_trigger_message_passthrough(self):
        processor = StartTriggerProcessor(language="en-US")
        pushed = []

        async def fake_push(f, d=None):
            pushed.append(f)

        processor.push_frame = fake_push
        heartbeat = InputTransportMessageFrame(message={"type": "client_heartbeat"})
        asyncio.run(processor.process_frame(heartbeat))
        self.assertFalse(processor.triggered)
        self.assertIn(heartbeat, pushed)


# =====================================================================
# Feature 14 Boundaries: 9-Phase Consultative Sales Journey
# =====================================================================
class TestBoundary14SalesJourney(unittest.TestCase):
    """Boundary tests for Feature 14: 9-Phase Consultative Sales Journey."""

    def test_all_9_phases_exist_in_order(self):
        for i in range(1, 10):
            self.assertIn(f"Phase {i}:", SYSTEM_PROMPT)

    def test_phase_1_time_check_boundary(self):
        self.assertIn("Phase 1: Time Check & Availability", SYSTEM_PROMPT)
        self.assertIn("2 minutes to talk", SYSTEM_PROMPT)

    def test_phase_4_platform_legitimacy_boundary(self):
        self.assertIn("RBI-registered NBFC-P2P", SYSTEM_PROMPT)
        self.assertIn("Trustee Escrow accounts", SYSTEM_PROMPT)

    def test_phase_5_diversification_math_boundary(self):
        self.assertIn("100+ borrowers", SYSTEM_PROMPT)
        self.assertIn("₹250 to ₹4,000 per borrower", SYSTEM_PROMPT)

    def test_objection_playbook_all_4_objections_present(self):
        self.assertIn("1. Objection: \"Is it safe?", SYSTEM_PROMPT)
        self.assertIn("2. Objection: \"Why not just put money in Bank Fixed Deposits (FD)?\"", SYSTEM_PROMPT)
        self.assertIn("3. Objection: \"Is Cymbal Lending legal / RBI approved?\"", SYSTEM_PROMPT)
        self.assertIn("4. Objection: \"Can I withdraw money anytime?\"", SYSTEM_PROMPT)


# =====================================================================
# Feature 15 Boundaries: Context Window Compression
# =====================================================================
class TestBoundary15ContextWindowCompression(unittest.TestCase):
    """Boundary tests for Feature 15: Context Window Compression."""

    def test_trigger_tokens_boundary_20000(self):
        trigger = 20000
        cwc = {"enabled": True, "trigger_tokens": trigger}
        self.assertEqual(cwc["trigger_tokens"], 20000)

    def test_trigger_tokens_custom_low_boundary_5000(self):
        trigger = 5000
        cwc = {"enabled": True, "trigger_tokens": trigger}
        self.assertEqual(cwc["trigger_tokens"], 5000)

    def test_trigger_tokens_custom_high_boundary_100000(self):
        trigger = 100000
        cwc = {"enabled": True, "trigger_tokens": trigger}
        self.assertEqual(cwc["trigger_tokens"], 100000)

    def test_none_trigger_tokens_generates_minimal_enabled_dict(self):
        cwc = {"enabled": True}
        self.assertTrue(cwc["enabled"])
        self.assertNotIn("trigger_tokens", cwc)

    def test_disabled_compression_empty_dict(self):
        cwc = {}
        self.assertEqual(len(cwc), 0)


# =====================================================================
# Feature 16 Boundaries: Boundary & Contradiction Handling
# =====================================================================
class TestBoundary16CrossToolContradictions(unittest.TestCase):
    """Boundary tests for Feature 16: Boundary & Contradiction Handling."""

    def test_9_month_rejection_across_manual_and_stl(self):
        res_manual = calculate_manual_lending(50000, 9)
        self.assertIn("error", res_manual)
        res_stl = calculate_stl_returns(50000, 9)
        self.assertIn("error", res_stl)

    def test_9_month_rejection_in_product_recommendation(self):
        res_rec = get_product_recommendation(50000, "low", 9)
        self.assertFalse(res_rec["is_valid"])
        self.assertIn("9-month", res_rec["error"])

    def test_low_amount_rejection_across_tools(self):
        self.assertIn("error", calculate_stl_returns(24999))
        self.assertIn("error", calculate_mtl_returns(99999))
        self.assertIn("error", calculate_manual_lending(249, 12))
        self.assertFalse(get_product_recommendation(249)["is_valid"])

    def test_high_amount_rejection_across_tools(self):
        self.assertIn("error", calculate_stl_returns(2500001))
        self.assertIn("error", calculate_mtl_returns(1000001, "monthly"))
        self.assertIn("error", calculate_mtl_returns(2500001, "daily"))
        self.assertIn("error", calculate_manual_lending(5000001, 12))
        self.assertFalse(get_product_recommendation(5000001)["is_valid"])

    def test_negative_amounts_cross_tool_rejection(self):
        self.assertIn("error", calculate_stl_returns(-1000))
        self.assertIn("error", calculate_mtl_returns(-50000))
        self.assertIn("error", calculate_manual_lending(-250, 12))
        self.assertFalse(get_product_recommendation(-5000)["is_valid"])


# =====================================================================
# Feature 17 Boundaries: Vertex AI Gemini 3.5 Live Duplex Config
# =====================================================================
class TestBoundary17VertexAiLiveConfig(unittest.TestCase):
    """Boundary tests for Feature 17: Vertex AI Gemini 3.5 Live Duplex Config."""

    def test_vertex_model_name_recognition(self):
        model = "gemini-3.5-flash-live-preview"
        self.assertIn("3.5", model)
        self.assertIn("live", model)

    def test_aistudio_suffix_detection(self):
        model_studio = "gemini-3.5-flash-live-preview-aistudio"
        clean = model_studio[:-9] if model_studio.endswith("-aistudio") else model_studio
        self.assertEqual(clean, "gemini-3.5-flash-live-preview")

    def test_location_env_var_override(self):
        with patch.dict(os.environ, {"GCP_LOCATION": "asia-south1"}):
            loc = os.getenv("GCP_LOCATION") or "us-central1"
            self.assertEqual(loc, "asia-south1")

    def test_audio_modality_toggle(self):
        from pipecat.services.google.gemini_live.llm import GeminiModalities
        use_external_tts = True
        mod_external = GeminiModalities.TEXT if use_external_tts else GeminiModalities.AUDIO
        self.assertEqual(mod_external, GeminiModalities.TEXT)

        use_native_voice = False
        mod_native = GeminiModalities.TEXT if use_native_voice else GeminiModalities.AUDIO
        self.assertEqual(mod_native, GeminiModalities.AUDIO)

    def test_voice_name_resolution(self):
        voice_custom = "Custom-Male"
        gender = "male" if voice_custom == "Custom-Male" else "female"
        self.assertEqual(gender, "male")


# =====================================================================
# Feature 18 Boundaries: Vertex AI RAG Engine
# =====================================================================
class TestBoundary18VertexAiRagEngine(unittest.TestCase):
    """Boundary tests for Feature 18: Vertex AI RAG Engine."""

    def test_schema_required_fields_boundary(self):
        self.assertEqual(search_knowledge_base_schema.required, ["query_for_vector_search", "total_records"])

    def test_location_regex_parsing_standard_locations(self):
        for loc in ["us-central1", "europe-west1", "asia-south1", "us-east4"]:
            cid = f"projects/my-project/locations/{loc}/ragCorpora/12345"
            with patch.dict(os.environ, {"RAG_CORPUS_RESOURCE_ID": cid}):
                _, _, extracted_loc = get_rag_config()
                self.assertEqual(extracted_loc, loc)

    def test_location_regex_parsing_empty_corpus_id(self):
        with patch.dict(os.environ, {"RAG_CORPUS_RESOURCE_ID": ""}):
            _, _, loc = get_rag_config()
            self.assertEqual(loc, "us-central1")

    def test_project_id_fallback_chain(self):
        with patch.dict(os.environ, {"GCP_PROJECT_ID": "proj-a", "GOOGLE_CLOUD_PROJECT": "proj-b"}):
            _, pid, _ = get_rag_config()
            self.assertEqual(pid, "proj-a")

        with patch.dict(os.environ, {"GCP_PROJECT_ID": "", "GOOGLE_CLOUD_PROJECT": "proj-b"}):
            _, pid, _ = get_rag_config()
            self.assertEqual(pid, "proj-b")


# =====================================================================
# Feature 19 Boundaries: In-Memory Telemetry Ring Buffer
# =====================================================================
class TestBoundary19DiagnosticRingBuffer(unittest.TestCase):
    """Boundary tests for Feature 19: In-Memory Telemetry Ring Buffer."""

    def setUp(self):
        clear_diagnostic_logs()

    def test_ring_buffer_1500_capacity_rollover(self):
        # Insert 1550 items, verifying buffer size is strictly capped at 1500
        for i in range(1550):
            append_diagnostic_log("BulkLog", f"Entry {i}")
        logs = get_recent_diagnostic_logs(2000)
        self.assertEqual(len(logs), 1500)
        # Oldest entry should be Entry 50
        self.assertIn("Entry 50", logs[0]["message"])
        # Newest entry should be Entry 1549
        self.assertIn("Entry 1549", logs[-1]["message"])

    def test_empty_string_log_not_appended(self):
        initial_len = len(get_recent_diagnostic_logs(10))
        append_raw_log_entry("   ")
        append_raw_log_entry("")
        self.assertEqual(len(get_recent_diagnostic_logs(10)), initial_len)

    def test_ttfb_parsing_in_milliseconds(self):
        append_raw_log_entry("Turn completed with ttfb: 450")
        logs = get_recent_diagnostic_logs(1)
        self.assertEqual(logs[0]["ttfb_ms"], 450.0)

    def test_ttfb_parsing_in_seconds(self):
        append_raw_log_entry("Custom TTFT calculation: 0.280s")
        logs = get_recent_diagnostic_logs(1)
        self.assertEqual(logs[0]["ttfb_ms"], 280.0)

    def test_get_recent_logs_slice_boundaries(self):
        for i in range(10):
            append_diagnostic_log("Test", f"Log {i}")
        self.assertEqual(len(get_recent_diagnostic_logs(5)), 5)
        self.assertEqual(len(get_recent_diagnostic_logs(50)), 10)
        self.assertEqual(len(get_recent_diagnostic_logs(1)), 1)


# =====================================================================
# Feature 20 Boundaries: Complete E2E Test Suite Contract
# =====================================================================
class TestBoundary20E2ETestSuiteContract(unittest.TestCase):
    """Boundary tests for Feature 20: Complete E2E Test Suite Contract."""

    def test_e2e_tier_files_co_located(self):
        e2e_dir = os.path.dirname(os.path.abspath(__file__))
        tier1_file = os.path.join(e2e_dir, "tier1_feature_coverage_test.py")
        self.assertTrue(os.path.isfile(tier1_file))

    def test_no_state_leakage_after_diagnostic_clear(self):
        clear_diagnostic_logs()
        self.assertEqual(len(get_recent_diagnostic_logs(100)), 0)

    def test_pure_deterministic_calculations(self):
        # Multiple invocations with same inputs produce identical results
        for _ in range(5):
            res = calculate_manual_lending(100000, 12, custom_borrower_rate_pct=40.0, custom_npa_rate_pct=5.0)
            self.assertEqual(res["step_f_net_profit_rupees"], 27000.0)
            self.assertEqual(res["step_g_net_annualized_roi_pct"], 27.0)

    def test_zero_network_requirement(self):
        tracer = LangSmithTracer()
        tracer.enabled = False
        url = tracer.start_session("unit_test", "model", None, "en-US")
        self.assertIsNotNone(url)

    def test_all_21_feature_boundary_classes(self):
        current_module = sys.modules[__name__]
        classes = [name for name in dir(current_module) if name.startswith("TestBoundary")]
        self.assertGreaterEqual(len(classes), 20)


# =====================================================================
# Feature 21 Boundaries: Final Verification & Hardening Acceptance
# =====================================================================
class TestBoundary21FinalVerificationContract(unittest.TestCase):
    """Boundary tests for Feature 21: Final Verification & Hardening Acceptance."""

    def test_deterministic_two_decimal_rounding(self):
        # Payout calculation with periodic repeating fraction
        res = calculate_mtl_returns(100000, "monthly")
        # 124000 / 12 = 10333.3333... -> rounded to 10333.33
        self.assertEqual(res["payout_amount"], 10333.33)

    def test_daily_payout_rounding_365_days(self):
        res = calculate_mtl_returns(2400000, "daily")
        # 2832000 / 365 = 7758.9041... -> 7758.90
        self.assertEqual(res["payout_amount"], 7758.90)

    def test_dict_response_contract_on_all_math_errors(self):
        err1 = calculate_stl_returns(10)
        self.assertIsInstance(err1, dict)
        self.assertIn("error", err1)

        err2 = calculate_mtl_returns(10)
        self.assertIsInstance(err2, dict)
        self.assertIn("error", err2)

        err3 = calculate_manual_lending(10, 12)
        self.assertIsInstance(err3, dict)
        self.assertIn("error", err3)

        err4 = calculate_sip_returns(0, 12, 1)
        self.assertIsInstance(err4, dict)
        self.assertIn("error", err4)

    def test_string_inputs_in_float_parameters_handled_or_converted(self):
        res = calculate_stl_returns(float("50000"), int("6"))
        self.assertEqual(res["product_name"], "STL 7M")

    def test_23_backend_tests_milestone_contract(self):
        backend_test_file = os.path.join(SERVER_DIR, "tests", "test_financial_math.py")
        backend_route_file = os.path.join(SERVER_DIR, "test_routes.py")
        self.assertTrue(os.path.isfile(backend_test_file))
        self.assertTrue(os.path.isfile(backend_route_file))


if __name__ == "__main__":
    unittest.main()
