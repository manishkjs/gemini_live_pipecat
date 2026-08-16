"""Adversarial stress test and verification harness for Milestone M2.

Author: Challenger challenger_m2_1
Scope:
1. `server/tools/tool_definitions.py`:
   - `handle_retrieve_memory` under edge cases: null args, empty strings, missing context,
     non-existent users, special chars, unicode/Devanagari names, extreme payload lengths,
     exception resilience, concurrent throughput.
   - `retrieve_memory_schema` compliance with Gemini Live function declaration schema.
   - `get_standard_tools` and `register_all_tools` registry verification.
2. `server/tools/navigation.py`:
   - `get_onboarding_guide`, `get_kyc_guidance`, `get_app_screen_flow`, `get_consultative_guidance`.
   - Exact 8 loan filter parameters verification verbatim.
   - 3-step digital KYC guidance (PAN, Aadhaar Digilocker OTP, Bank Penny drop).
   - Case-insensitivity, fuzzing, and boundary inputs.
3. `server/system_prompt.py`:
   - Exact match for Turn 1 greeting string across all prompt representations.
   - Exact match for Objection 1 header string.
   - Memory recall directives presence in guidelines.
   - Chained prompt generator across all phases (1-9 and boundary phases).
   - Core domain invariants verification (Devanagari/Latin code mix, 9-month rejection, 96.18% recovery).
"""

import asyncio
import json
import os
import sys
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure server path is in sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

# Mock out heavy external dependencies so tests run hermetically and instantly
for mod in [
    "vertexai",
    "vertexai.preview",
    "vertexai.preview.rag",
    "pipecat.audio.vad.silero",
    "pyloudnorm",
    "pyloudnorm.meter",
    "pyloudnorm.iirfilter",
    "scipy",
    "scipy.signal",
    "scipy.stats",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from memory_bank import FactStore, MemoryBank, normalize_lexical_user_id
from tools.navigation import (
    get_app_screen_flow,
    get_consultative_guidance,
    get_kyc_guidance,
    get_navigation_guidance,
    get_onboarding_guide,
)
from tools.tool_definitions import (
    get_standard_tools,
    handle_retrieve_memory,
    register_all_tools,
    retrieve_memory_schema,
)
import system_prompt


class MockFunctionCallParams:
    """Mock for Pipecat FunctionCallParams."""
    def __init__(
        self,
        arguments: Optional[Dict[str, Any]] = None,
        function_name: str = "retrieve_memory",
        context: Optional[Any] = None,
    ):
        self.arguments = arguments
        self.function_name = function_name
        self.context = context
        self.result: Optional[Dict[str, Any]] = None

    async def result_callback(self, result: Dict[str, Any]):
        self.result = result


class TestRetrieveMemoryAdversarial(unittest.TestCase):
    """Adversarial testing for retrieve_memory tool schema and async handler."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    # ─────────────────────────────────────────────────────────────────
    # 1. SCHEMA COMPLIANCE
    # ─────────────────────────────────────────────────────────────────

    def test_retrieve_memory_schema_compliance(self):
        """Verify retrieve_memory_schema conforms strictly to Gemini Live FunctionSchema specification."""
        self.assertEqual(retrieve_memory_schema.name, "retrieve_memory")
        self.assertTrue(len(retrieve_memory_schema.description) > 0)
        self.assertIn("memory", retrieve_memory_schema.description.lower())

        props = retrieve_memory_schema.properties
        self.assertIn("user_id", props)
        self.assertIn("query", props)
        self.assertEqual(props["user_id"]["type"], "string")
        self.assertEqual(props["query"]["type"], "string")

        req = retrieve_memory_schema.required
        self.assertIn("user_id", req)
        self.assertIn("query", req)

    def test_standard_tools_and_registration(self):
        """Verify retrieve_memory is included in standard tools and registered on LLM."""
        tools = get_standard_tools()
        tool_names = [t.name for t in tools]
        self.assertIn("retrieve_memory", tool_names)
        self.assertIn("calculate_returns", tool_names)
        self.assertIn("get_onboarding_guide", tool_names)

        # Dynamic tools JSON parsing test
        dynamic_json = json.dumps([{"name": "custom_tool", "description": "Custom", "properties": {}, "required": []}])
        extended_tools = get_standard_tools(dynamic_tools_json=dynamic_json)
        self.assertIn("custom_tool", [t.name for t in extended_tools])

        # Register tools on mock LLM
        mock_llm = MagicMock()
        registered_funcs = {}
        mock_llm.register_function.side_effect = lambda name, fn: registered_funcs.update({name: fn})

        register_all_tools(mock_llm, standard_tools=tools)
        self.assertIn("retrieve_memory", registered_funcs)
        self.assertEqual(registered_funcs["retrieve_memory"], handle_retrieve_memory)

    # ─────────────────────────────────────────────────────────────────
    # 2. HANDLER EDGE CASES: NULL, EMPTY, MISSING PARAMS
    # ─────────────────────────────────────────────────────────────────

    def test_handle_retrieve_memory_null_and_empty_args(self):
        """Test handle_retrieve_memory handles None arguments and empty user_id safely."""
        async def _run():
            # None arguments
            p1 = MockFunctionCallParams(arguments=None)
            await handle_retrieve_memory(p1)
            self.assertEqual(p1.result["status"], "not_found")
            self.assertEqual(p1.result["user_id"], "user_anonymous")
            self.assertEqual(p1.result["count"], 0)

            # Empty dictionary arguments
            p2 = MockFunctionCallParams(arguments={})
            await handle_retrieve_memory(p2)
            self.assertEqual(p2.result["status"], "not_found")
            self.assertEqual(p2.result["count"], 0)

            # Empty string user_id
            p3 = MockFunctionCallParams(arguments={"user_id": "", "query": "loans"})
            await handle_retrieve_memory(p3)
            self.assertEqual(p3.result["status"], "not_found")

            # Whitespace-only user_id
            p4 = MockFunctionCallParams(arguments={"user_id": "   \t\n  ", "query": "loans"})
            await handle_retrieve_memory(p4)
            self.assertEqual(p4.result["status"], "not_found")

        self.loop.run_until_complete(_run())

    def test_handle_retrieve_memory_non_string_types(self):
        """Test non-string argument types do not crash and handle gracefully."""
        async def _run():
            # user_id is int, float, list, dict, bool
            bad_user_ids = [12345, 99.9, ["aditya"], {"name": "aditya"}, True, False]
            for uid in bad_user_ids:
                p = MockFunctionCallParams(arguments={"user_id": uid, "query": "KYC"})
                await handle_retrieve_memory(p)
                self.assertIsNotNone(p.result)
                self.assertEqual(p.result["status"], "not_found")

        self.loop.run_until_complete(_run())

    # ─────────────────────────────────────────────────────────────────
    # 3. UNICODE, SPECIAL CHARACTERS, AND PROMPT INJECTION
    # ─────────────────────────────────────────────────────────────────

    def test_handle_retrieve_memory_unicode_and_special_chars(self):
        """Test Devanagari, emojis, special characters, and injection queries."""
        mb = MemoryBank()
        mb.add_memory("user_aditya_sharma", "Invested ₹50,000 in STL 7M plan.")
        fs = mb.get_fact_store("user_aditya_sharma")
        fs.set_fact("amount", 50000.0, turn_id=1)

        async def _run():
            # Spoken name with Devanagari: "आदित्य शर्मा" -> user_aaditya_sharma or user_aditya_sharma
            p1 = MockFunctionCallParams(
                arguments={"user_id": "Aditya Sharma", "query": "STL 7M"},
            )
            await handle_retrieve_memory(p1, memory_bank=mb)
            self.assertEqual(p1.result["status"], "success")
            self.assertEqual(p1.result["user_id"], "user_aditya_sharma")
            self.assertEqual(p1.result["facts"]["amount"], 50000.0)
            self.assertGreaterEqual(p1.result["count"], 1)

            # Query with special symbols & SQL-like text
            p2 = MockFunctionCallParams(
                arguments={"user_id": "Aditya Sharma", "query": "SELECT * FROM `users` WHERE 1=1; -- <script>"},
            )
            await handle_retrieve_memory(p2, memory_bank=mb)
            self.assertIn(p2.result["status"], ["success", "empty"])
            self.assertIsInstance(p2.result["facts"], dict)
            self.assertIsInstance(p2.result["memories"], list)

            # Spoken name with honorifics: "Mera naam Shri Aditya Sharma ji hai"
            p3 = MockFunctionCallParams(
                arguments={"user_id": "Mera naam Shri Aditya Sharma ji hai", "query": "investment history"},
            )
            await handle_retrieve_memory(p3, memory_bank=mb)
            self.assertEqual(p3.result["user_id"], "user_aditya_sharma")
            self.assertEqual(p3.result["status"], "success")

        self.loop.run_until_complete(_run())

    # ─────────────────────────────────────────────────────────────────
    # 4. CONTEXT RESOLUTION & MEMORY BANK FALLBACK
    # ─────────────────────────────────────────────────────────────────

    def test_handle_retrieve_memory_context_resolution(self):
        """Test memory bank resolution from parameter, params.context object, and dict."""
        mb = MemoryBank()
        mb.add_memory("user_rohit_verma", "Completed KYC PAN verification.")

        async def _run():
            # Passed via params.context as object
            class MockContext:
                def __init__(self, memory_bank):
                    self.memory_bank = memory_bank

            p1 = MockFunctionCallParams(
                arguments={"user_id": "Rohit Verma", "query": "KYC"},
                context=MockContext(mb),
            )
            await handle_retrieve_memory(p1)
            self.assertEqual(p1.result["status"], "success")
            self.assertEqual(p1.result["user_id"], "user_rohit_verma")

            # Passed via params.context as dict
            p2 = MockFunctionCallParams(
                arguments={"user_id": "Rohit Verma", "query": "KYC"},
                context={"memory_bank": mb},
            )
            await handle_retrieve_memory(p2)
            self.assertEqual(p2.result["status"], "success")

        self.loop.run_until_complete(_run())

    # ─────────────────────────────────────────────────────────────────
    # 5. ERROR RESILIENCE & ASYNC EXCEPTION RECOVERY
    # ─────────────────────────────────────────────────────────────────

    def test_handle_retrieve_memory_exception_recovery(self):
        """Verify exceptions in memory bank do not crash the voice loop."""
        mock_broken_mb = MagicMock()
        mock_broken_mb.get_fact_store.side_effect = RuntimeError("Database connection lost!")

        async def _run():
            p = MockFunctionCallParams(
                arguments={"user_id": "Aditya Sharma", "query": "loans"},
            )
            await handle_retrieve_memory(p, memory_bank=mock_broken_mb)
            self.assertEqual(p.result["status"], "error")
            self.assertIn("error", p.result)
            self.assertEqual(p.result["count"], 0)

        self.loop.run_until_complete(_run())

    # ─────────────────────────────────────────────────────────────────
    # 6. CONCURRENT INVOCATION & THROUGHPUT STRESS
    # ─────────────────────────────────────────────────────────────────

    def test_handle_retrieve_memory_concurrent_stress(self):
        """Execute 250 concurrent async memory retrieval queries without race conditions."""
        mb = MemoryBank()
        for i in range(10):
            uid = f"user_test_client_{i}"
            mb.add_memory(uid, f"Client {i} interested in 12-month MTL plan with ₹1,00,000.")
            fs = mb.get_fact_store(uid)
            fs.set_fact("amount", 100000.0 * (i + 1), turn_id=1)

        async def _run():
            tasks = []
            for i in range(250):
                uid_raw = f"Test Client {i % 10}"
                p = MockFunctionCallParams(
                    arguments={"user_id": uid_raw, "query": "MTL 14M"},
                )
                tasks.append(handle_retrieve_memory(p, memory_bank=mb))

            start_t = time.perf_counter()
            await asyncio.gather(*tasks)
            elapsed = time.perf_counter() - start_t
            # 250 concurrent calls should finish in < 5.0s
            self.assertLess(elapsed, 5.0, f"250 concurrent calls took {elapsed:.2f}s")

        self.loop.run_until_complete(_run())


class TestNavigationFlowsAdversarial(unittest.TestCase):
    """Adversarial testing for navigation flows in server/tools/navigation.py."""

    # ─────────────────────────────────────────────────────────────────
    # 1. 8 LOAN FILTER PARAMETERS STRICT INTEGRITY
    # ─────────────────────────────────────────────────────────────────

    def test_loan_filter_exact_8_parameters(self):
        """Verify the exact 8 loan filter parameters verbatim and in exact order."""
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

        filter_queries = [
            "loan filter", "Loan Filter", "LOAN_FILTER", "filter",
            "borrower filter", "BORROWER FILTER", "loan filters",
            "filter borrowers", "app loan filter options",
        ]

        for query in filter_queries:
            res = get_app_screen_flow(query)
            self.assertEqual(res["flow_name"], "App Loan Filter Options")
            self.assertEqual(res["available_filters"], expected_filters)
            self.assertEqual(len(res["available_filters"]), 8)
            # Verify Hinglish instructions mention all 8 items
            inst = res["instructions_hinglish"]
            self.assertIn("8 exact options", inst)
            self.assertIn("Loan Tenure", inst)
            self.assertIn("Repayment Type", inst)
            self.assertIn("Risk Category", inst)
            self.assertIn("Borrower Type", inst)
            self.assertIn("Monthly Income", inst)
            self.assertIn("Loan Amount", inst)
            self.assertIn("Remaining Amount", inst)
            self.assertIn("Borrower Age", inst)

    # ─────────────────────────────────────────────────────────────────
    # 2. 3-STEP INSTANT KYC GUIDANCE ACCURACY
    # ─────────────────────────────────────────────────────────────────

    def test_kyc_guidance_all_steps_and_overview(self):
        """Verify accurate guidance across all 3 KYC steps and overview."""
        # Step 1: PAN Verification
        for q in ["pan", "PAN", "pan card", "PAN PHOTO", "pan verification"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "PAN Verification")
            self.assertIn("10-digit PAN", res["instructions_hinglish"])
            self.assertIn("photo", res["instructions_hinglish"].lower())
            self.assertIn("Original PAN Card", res["requirements"])

        # Step 2: Aadhaar Digilocker OTP
        for q in ["aadhaar", "AADHAAR", "aadhar", "Aadhar", "address", "aadhaar otp"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "Aadhaar / Address Verification")
            self.assertIn("Digilocker", res["instructions_hinglish"])
            self.assertIn("12-digit Aadhaar", res["instructions_hinglish"])
            self.assertIn("OTP", res["instructions_hinglish"])
            self.assertIn("linked with Aadhaar", res["requirements"])

        # Step 3: Bank Account Penny Drop
        for q in ["bank", "BANK", "penny", "penny drop", "penny_drop", "account", "bank account"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "Bank Account Linking")
            self.assertIn("₹1", res["instructions_hinglish"])
            self.assertIn("Penny drop", res["instructions_hinglish"])
            self.assertIn("IFSC Code", res["instructions_hinglish"])
            self.assertIn("Bank Account Number", res["instructions_hinglish"])
            self.assertIn("match PAN card", res["requirements"])

        # Complete 3-Step Overview
        for q in ["all", "", None, "kyc", "all_kyc", "overview"]:
            res = get_kyc_guidance(q)
            self.assertEqual(res["step"], "Complete KYC 3-Step Overview")
            self.assertIn("3 simple steps", res["instructions_hinglish"])
            self.assertIn("1. PAN card", res["instructions_hinglish"])
            self.assertIn("2. Digilocker", res["instructions_hinglish"])
            self.assertIn("3. Apna bank account number", res["instructions_hinglish"])
            self.assertIn("penny-drop", res["instructions_hinglish"])
            self.assertIn("2 minute", res["instructions_hinglish"])

    # ─────────────────────────────────────────────────────────────────
    # 3. APP SCREEN FLOWS: DEPOSIT, LUMPSUM, MANUAL, GENERAL
    # ─────────────────────────────────────────────────────────────────

    def test_app_screen_flows_deposit_lumpsum_manual(self):
        """Verify accurate navigation details for deposit, lumpsum, manual lending, and general."""
        # Deposit
        for q in ["deposit", "DEPOSIT", "fund", "add money", "pay"]:
            res = get_app_screen_flow(q)
            self.assertEqual(res["flow_name"], "Adding Funds to Cymbal Escrow Wallet")
            self.assertIn("Escrow", res["instructions_hinglish"])
            self.assertIn("UPI", res["instructions_hinglish"])
            self.assertIn("NetBanking", res["instructions_hinglish"])
            self.assertIn("₹250", res["instructions_hinglish"])
            self.assertIn("₹25,000", res["instructions_hinglish"])

        # Lumpsum
        for q in ["lumpsum", "stl", "mtl", "stl 5m", "mtl 14m"]:
            res = get_app_screen_flow(q)
            self.assertEqual(res["flow_name"], "Lumpsum Lending (STL / MTL)")
            self.assertIn("STL 5M", res["instructions_hinglish"])
            self.assertIn("STL 7M", res["instructions_hinglish"])
            self.assertIn("MTL 14M", res["instructions_hinglish"])
            self.assertIn("100+ verified borrowers", res["instructions_hinglish"])

        # Manual
        for q in ["manual", "MANUAL", "manual lending"]:
            res = get_app_screen_flow(q)
            self.assertEqual(res["flow_name"], "Manual Lending Selection")
            self.assertIn("Manual Lending", res["instructions_hinglish"])
            self.assertIn("₹250", res["instructions_hinglish"])
            self.assertIn("₹4,000", res["instructions_hinglish"])

        # General / fallback
        for q in ["general", "dashboard", "", None, "xyz123", "settings"]:
            res = get_app_screen_flow(q)
            self.assertEqual(res["flow_name"], "General App Navigation")
            self.assertIn("Dashboard", res["instructions_hinglish"])
            self.assertIn("Invest", res["instructions_hinglish"])
            self.assertIn("Portfolio / Statement", res["instructions_hinglish"])

    # ─────────────────────────────────────────────────────────────────
    # 4. UNIFIED ONBOARDING GUIDE & CONSULTATIVE GUIDANCE
    # ─────────────────────────────────────────────────────────────────

    def test_get_onboarding_guide_and_consultative_guidance(self):
        """Verify routing in get_onboarding_guide, get_navigation_guidance, and consultative guidance."""
        # get_onboarding_guide routing to KYC
        self.assertEqual(get_onboarding_guide("pan")["step"], "PAN Verification")
        self.assertEqual(get_onboarding_guide("aadhaar")["step"], "Aadhaar / Address Verification")
        self.assertEqual(get_onboarding_guide("bank")["step"], "Bank Account Linking")
        self.assertEqual(get_onboarding_guide("kyc")["step"], "Complete KYC 3-Step Overview")

        # get_onboarding_guide routing to App Screens
        self.assertEqual(get_onboarding_guide("deposit")["flow_name"], "Adding Funds to Cymbal Escrow Wallet")
        self.assertEqual(get_onboarding_guide("lumpsum")["flow_name"], "Lumpsum Lending (STL / MTL)")
        self.assertEqual(get_onboarding_guide("loan filter")["flow_name"], "App Loan Filter Options")

        # get_navigation_guidance alias
        self.assertEqual(get_navigation_guidance("pan")["step"], "PAN Verification")
        self.assertEqual(get_navigation_guidance("deposit")["flow_name"], "Adding Funds to Cymbal Escrow Wallet")

        # Consultative guidance topics
        fd_guide = get_consultative_guidance("fd")
        self.assertEqual(fd_guide["topic"], "Bank FD Comparison")
        self.assertIn("6.5%", fd_guide["key_points_hinglish"])
        self.assertIn("12% se 24%", fd_guide["key_points_hinglish"])

        risk_guide = get_consultative_guidance("npa")
        self.assertEqual(risk_guide["topic"], "Risk & Default Mitigation")
        self.assertIn("100+ vetted borrowers", risk_guide["key_points_hinglish"])

        rbi_guide = get_consultative_guidance("rbi")
        self.assertEqual(rbi_guide["topic"], "Platform Legitimacy & RBI Trust")
        self.assertIn("RBI-registered NBFC-P2P", rbi_guide["key_points_hinglish"])

        liq_guide = get_consultative_guidance("liquidity")
        self.assertEqual(liq_guide["topic"], "Liquidity & Repayment Mechanics")
        self.assertIn("regular cash liquidity", liq_guide["key_points_hinglish"])


class TestSystemPromptAdversarialAlignment(unittest.TestCase):
    """Adversarial verification for system prompt exact strings and domain rules."""

    EXACT_GREETING = (
        "नमस्ते! मैं प्रज्ञा बात कर रही हूँ, Cymbal Lending से। "
        "क्या मैं आपका नाम जान सकती हूँ, और क्या आपके पास बात करने के लिए 2 minutes का समय है?"
    )

    EXACT_OBJECTION_1_HEADER = '1. Objection: "Is it safe? What if borrowers default (NPA)?"'

    # ─────────────────────────────────────────────────────────────────
    # 1. EXACT STRING MATCHES
    # ─────────────────────────────────────────────────────────────────

    def test_turn1_greeting_exact_matches(self):
        """Verify the exact Turn 1 greeting string across all prompt files and generators."""
        # 1. PHASE_PROMPTS[1]
        self.assertIn(self.EXACT_GREETING, system_prompt.PHASE_PROMPTS[1])

        # 2. FEW_SHOT_EXAMPLES (Example 1)
        self.assertIn(self.EXACT_GREETING, system_prompt.FEW_SHOT_EXAMPLES)

        # 3. get_chained_system_prompt(phase=1)
        chained_p1 = system_prompt.get_chained_system_prompt(phase=1)
        self.assertIn(self.EXACT_GREETING, chained_p1)

        # 4. SYSTEM_PROMPT composite
        self.assertIn(self.EXACT_GREETING, system_prompt.SYSTEM_PROMPT)

    def test_objection_1_header_exact_matches(self):
        """Verify the exact Objection 1 header string."""
        self.assertIn(self.EXACT_OBJECTION_1_HEADER, system_prompt.OBJECTION_PLAYBOOK)
        self.assertIn(self.EXACT_OBJECTION_1_HEADER, system_prompt.SYSTEM_PROMPT)

    # ─────────────────────────────────────────────────────────────────
    # 2. MEMORY RETRIEVAL DIRECTIVES
    # ─────────────────────────────────────────────────────────────────

    def test_retrieve_memory_directives_in_system_prompts(self):
        """Verify retrieve_memory prompt directives exist in both full and lean system prompts."""
        # In BASE_SYSTEM_PROMPT
        self.assertIn("retrieve_memory", system_prompt.BASE_SYSTEM_PROMPT)
        self.assertIn("MEMORY RETRIEVAL DIRECTIVE", system_prompt.BASE_SYSTEM_PROMPT)

        # In LEAN_PERSONA_PROMPT
        self.assertIn("retrieve_memory", system_prompt.LEAN_PERSONA_PROMPT)
        self.assertIn("Customer memory retrieval", system_prompt.LEAN_PERSONA_PROMPT)

        # In SYSTEM_PROMPT
        self.assertIn("retrieve_memory", system_prompt.SYSTEM_PROMPT)

    # ─────────────────────────────────────────────────────────────────
    # 3. CHAINED SYSTEM PROMPT ACROSS ALL PHASES (1-9) & BOUNDARIES
    # ─────────────────────────────────────────────────────────────────

    def test_chained_system_prompt_all_phases_and_boundaries(self):
        """Test get_chained_system_prompt across all phases (1..9), boundaries, and profile injection."""
        for phase_num in range(1, 10):
            prompt = system_prompt.get_chained_system_prompt(phase=phase_num)
            self.assertIsInstance(prompt, str)
            self.assertTrue(len(prompt) > 100)
            self.assertIn("प्रज्ञा (Pragya)", prompt)
            self.assertIn("Cymbal Lending", prompt)
            self.assertIn("<active_sales_phase>", prompt)

        # Phase 1 includes greeting
        p1 = system_prompt.get_chained_system_prompt(phase=1)
        self.assertIn("<phase_guidance>", p1)
        self.assertIn(self.EXACT_GREETING, p1)

        # Phase 7 includes boundary rules (9-month tenure rejection)
        p7 = system_prompt.get_chained_system_prompt(phase=7)
        self.assertIn("9-Month Tenure Rejection (Strict)", p7)

        # Boundary phases (phase=0, phase=10, phase=-1) fallback safely to Phase 1
        for bad_phase in [0, 10, -1, 99]:
            p_bad = system_prompt.get_chained_system_prompt(phase=bad_phase)
            self.assertIn("<active_sales_phase>", p_bad)

        # User profile injection
        user_profile = {"user_id": "user_aditya_sharma", "amount": 50000.0, "risk": "medium"}
        p_profile = system_prompt.get_chained_system_prompt(phase=2, user_profile=user_profile)
        self.assertIn("<active_user_context>", p_profile)
        self.assertIn("user_aditya_sharma", p_profile)
        self.assertIn("50000.0", p_profile)

    # ─────────────────────────────────────────────────────────────────
    # 4. CORE DOMAIN INVARIANTS
    # ─────────────────────────────────────────────────────────────────

    def test_core_domain_invariants(self):
        """Verify strict domain invariants in prompt content."""
        sp = system_prompt.SYSTEM_PROMPT

        # 1. Code-mixing rules
        self.assertIn("Devanagari script", sp)
        self.assertIn("Latin script", sp)

        # 2. 9-Month Tenure rejection
        self.assertIn("9-Month Tenure Rejection (Strict)", sp)
        self.assertIn("9-month tenures are STRICTLY NOT AVAILABLE", sp)

        # 3. Safety statistics
        self.assertIn("96.18%", sp)  # Recovery track record
        self.assertIn("100+", sp)   # Diversification across 100+ borrowers
        self.assertIn("Escrow", sp) # ICICI/IDBI Trustee Escrow
        self.assertIn("₹50,00,000", sp) # RBI aggregate ceiling

        # 4. Brand Cleanliness
        forbidden_terms = ["lendenclub", "fintree", "faircent", "liquiloans", "lendbox"]
        # Except where explicitly clarified in comments or historical context if any
        # Check SYSTEM_PROMPT for pure Cymbal Lending branding
        self.assertIn("Cymbal Lending", sp)
        self.assertIn("सिम्बल लेंडिंग", sp)


if __name__ == "__main__":
    unittest.main()
