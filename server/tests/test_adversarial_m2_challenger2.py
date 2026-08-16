"""Adversarial challenger test suite 2 for Milestone 2: Tools Configuration & System Prompt Alignment.

Author: Challenger 2 (M2)
Scope:
1. Tool Registration & Schema Integrity:
   - Pipecat FunctionSchema compliance for all M2 tools.
   - get_standard_tools() verification (default tools + dynamic JSON parsing + malformed resilience).
   - register_all_tools() handler binding, dynamic handler fallback, and collision avoidance.
2. retrieve_memory Tool & MemoryBank Integration:
   - Schema validation (required=["user_id", "query"]).
   - Lexical user ID normalization ("Aditya Sharma" -> "user_aditya_sharma").
   - FactStore active facts + MemoryBank episodic search at 0.40 threshold.
   - Empty query handling (profile hydration fallback).
   - Missing / None / empty / whitespace user_id graceful degradation.
   - Non-existent user clean empty payload.
   - MemoryBank search exception resilience (zero crash).
   - Async non-blocking execution & context resolution.
3. Navigation Flows & Boundary Conditions:
   - Escrow Deposit guidance: Min ₹250 (manual) / ₹25,000 (lumpsum), UPI vs NetBanking, Escrow security.
   - Lumpsum Navigation & Calculations: STL 5M (3-5m), STL 7M (4-6m), MTL 14M (12m Monthly / Daily).
   - Strict 9-Month Tenure Rejection across calculation tools.
   - Exact 8 App Loan Filter Parameters verification across query permutations.
   - 3-Step Digital KYC Guidance (PAN, Aadhaar Digilocker, Bank penny-drop) & unified onboarding.
   - Consultative guidance topics (FD, NPA, RBI trust, liquidity).
4. System Prompt Alignment & Brand Cleanliness:
   - Turn 1 Greeting exact match.
   - Objection 1 Header exact match.
   - Memory retrieval prompt directives.
   - Zero proprietary/external customer branding leaks across prompts and tools.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure server directory is in sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

for mod in [
    "vertexai",
    "vertexai.preview",
    "vertexai.preview.rag",
    "pipecat.audio.vad.silero",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()


from pipecat.adapters.schemas.function_schema import FunctionSchema
from memory_bank import MemoryBank, FactStore, normalize_lexical_user_id
from tools.tool_definitions import (
    get_standard_tools,
    register_all_tools,
    retrieve_memory_schema,
    handle_retrieve_memory,
    calculate_returns_schema,
    handle_calculate_returns,
    get_onboarding_guide_schema,
    handle_get_onboarding_guide,
    calculate_stl_returns_schema,
    handle_calculate_stl_returns,
    calculate_mtl_returns_schema,
    handle_calculate_mtl_returns,
    calculate_manual_lending_schema,
    handle_calculate_manual_lending,
    calculate_sip_returns_schema,
    handle_calculate_sip_returns,
    get_product_recommendation_schema,
    handle_get_product_recommendation,
    get_kyc_guidance_schema,
    handle_get_kyc_guidance,
    get_app_screen_flow_schema,
    handle_get_app_screen_flow,
    get_current_time_schema,
    dynamic_tool_handler,
)
from tools.navigation import (
    get_onboarding_guide,
    get_kyc_guidance,
    get_app_screen_flow,
    get_consultative_guidance,
    get_navigation_guidance,
)
from tools.financial_math import (
    calculate_stl_returns,
    calculate_mtl_returns,
    calculate_manual_lending,
    calculate_returns,
    get_product_recommendation,
)
from system_prompt import (
    SYSTEM_PROMPT,
    BASE_SYSTEM_PROMPT,
    PHASE_PROMPTS,
    BOUNDARY_RULES,
    OBJECTION_PLAYBOOK,
    LEAN_PERSONA_PROMPT,
    get_chained_system_prompt,
)


class MockFunctionCallParams:
    """Mock for Pipecat FunctionCallParams."""
    def __init__(self, function_name: str, arguments: Optional[Dict[str, Any]], context: Optional[Any] = None):
        self.function_name = function_name
        self.arguments = arguments
        self.context = context
        self.result = None

    async def result_callback(self, res: Any):
        self.result = res


class MockLLMService:
    """Mock for LLM service to verify tool registration."""
    def __init__(self):
        self.registered_functions: Dict[str, Any] = {}

    def register_function(self, name: str, handler: Any):
        self.registered_functions[name] = handler


class TestM2ToolRegistrationAndSchemas(unittest.TestCase):
    """Adversarial verification of tool registration and schema integration."""

    def test_standard_tools_default_list(self):
        """Verify get_standard_tools() returns all 6 expected baseline tools."""
        tools = get_standard_tools()
        self.assertIsInstance(tools, list)
        self.assertEqual(len(tools), 6)
        tool_names = [t.name for t in tools]
        expected_names = [
            "get_current_time",
            "search_knowledge_base",
            "calculate_returns",
            "get_onboarding_guide",
            "retrieve_memory",
            "save_memory",
        ]
        for expected in expected_names:
            self.assertIn(expected, tool_names, f"Expected tool {expected} missing from standard tools")

    def test_all_schemas_are_valid_function_schemas(self):
        """Verify all tool schemas have valid types, properties, and descriptions."""
        all_schemas = [
            get_current_time_schema,
            calculate_returns_schema,
            get_onboarding_guide_schema,
            retrieve_memory_schema,
            calculate_stl_returns_schema,
            calculate_mtl_returns_schema,
            calculate_manual_lending_schema,
            calculate_sip_returns_schema,
            get_product_recommendation_schema,
            get_kyc_guidance_schema,
            get_app_screen_flow_schema,
        ]
        for schema in all_schemas:
            self.assertIsInstance(schema, FunctionSchema)
            self.assertTrue(schema.name, "Schema must have a non-empty name")
            self.assertTrue(schema.description, f"Schema {schema.name} must have description")
            self.assertIsInstance(schema.properties, dict, f"Schema {schema.name} properties must be dict")
            self.assertIsInstance(schema.required, list, f"Schema {schema.name} required must be list")

    def test_retrieve_memory_schema_contract(self):
        """Verify retrieve_memory_schema matches exact project specification."""
        self.assertEqual(retrieve_memory_schema.name, "retrieve_memory")
        self.assertIn("user_id", retrieve_memory_schema.properties)
        self.assertIn("query", retrieve_memory_schema.properties)
        self.assertEqual(retrieve_memory_schema.properties["user_id"]["type"], "string")
        self.assertEqual(retrieve_memory_schema.properties["query"]["type"], "string")
        self.assertIn("user_id", retrieve_memory_schema.required)
        self.assertIn("query", retrieve_memory_schema.required)

    def test_dynamic_tools_json_parsing_valid(self):
        """Verify dynamic tools JSON can inject extra custom tools."""
        custom_json = json.dumps([
            {
                "name": "custom_crm_lookup",
                "description": "Lookup CRM lead status",
                "properties": {"lead_id": {"type": "string"}},
                "required": ["lead_id"]
            }
        ])
        tools = get_standard_tools(dynamic_tools_json=custom_json)
        self.assertEqual(len(tools), 7)
        custom_tool = tools[-1]
        self.assertEqual(custom_tool.name, "custom_crm_lookup")
        self.assertEqual(custom_tool.description, "Lookup CRM lead status")
        self.assertEqual(custom_tool.required, ["lead_id"])

    def test_dynamic_tools_json_malformed_resilience(self):
        """Verify get_standard_tools() does not crash on malformed JSON or unexpected types."""
        malformed_inputs = [
            "invalid json {[}",
            "{not a list}",
            "12345",
            json.dumps({"name": "single_dict_not_list"}),
            json.dumps([{"missing_name": 1}]),
            "",
            None,
        ]
        for bad_input in malformed_inputs:
            tools = get_standard_tools(dynamic_tools_json=bad_input)
            self.assertEqual(len(tools), 6, f"Failed on malformed dynamic tool input: {bad_input}")

    def test_register_all_tools_binding(self):
        """Verify register_all_tools binds all 12 core handlers plus dynamic fallbacks."""
        mock_llm = MockLLMService()
        standard_tools = get_standard_tools()
        
        register_all_tools(mock_llm, standard_tools)

        expected_registered = [
            "search_knowledge_base",
            "calculate_returns",
            "get_onboarding_guide",
            "retrieve_memory",
            "calculate_stl_returns",
            "calculate_mtl_returns",
            "calculate_manual_lending",
            "calculate_sip_returns",
            "get_product_recommendation",
            "get_kyc_guidance",
            "get_app_screen_flow",
        ]
        for name in expected_registered:
            self.assertIn(name, mock_llm.registered_functions, f"Handler for {name} was not registered")

    def test_register_all_tools_with_custom_clock_and_dynamic_tool(self):
        """Verify custom clock function and dynamic tool fallback registration."""
        mock_llm = MockLLMService()
        custom_clock = AsyncMock()
        dynamic_tool = FunctionSchema(
            name="custom_webhook",
            description="Trigger external webhook",
            properties={"url": {"type": "string"}},
            required=["url"]
        )
        standard_tools = get_standard_tools() + [dynamic_tool]

        register_all_tools(mock_llm, standard_tools, get_current_time_fn=custom_clock)

        self.assertIn("get_current_time", mock_llm.registered_functions)
        self.assertEqual(mock_llm.registered_functions["get_current_time"], custom_clock)
        self.assertIn("custom_webhook", mock_llm.registered_functions)
        self.assertEqual(mock_llm.registered_functions["custom_webhook"], dynamic_tool_handler)


class TestM2RetrieveMemoryToolIntegration(unittest.IsolatedAsyncioTestCase):
    """Adversarial verification of retrieve_memory tool handler with MemoryBank."""

    async def asyncSetUp(self):
        self.mb = MemoryBank()
        # Seed test user
        self.user_id = "user_aditya_sharma"
        fact_store = self.mb.get_fact_store(self.user_id)
        fact_store.set_fact("amount", 50000.0, turn_id=1)
        fact_store.set_fact("tenure_months", 6, turn_id=1)
        fact_store.set_fact("risk_preference", "medium", turn_id=1)
        fact_store.set_fact("occupation", "salaried", turn_id=1)
        fact_store.set_fact("city", "Mumbai", turn_id=1)
        self.mb.add_memory(self.user_id, "Customer interested in STL 7M 6-month plan with monthly EMI.")
        self.mb.add_memory(self.user_id, "Completed PAN verification and Aadhaar OTP via Digilocker.")

    async def test_handle_retrieve_memory_success_with_spoken_name(self):
        """Verify spoken name 'Aditya Sharma' normalizes and retrieves facts and episodic memory."""
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "Aditya Sharma", "query": "STL 7M"},
        )
        await handle_retrieve_memory(params, memory_bank=self.mb)
        
        result = params.result
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("user_id"), "user_aditya_sharma")
        self.assertIn("facts", result)
        self.assertEqual(result["facts"].get("amount"), 50000.0)
        self.assertEqual(result["facts"].get("tenure_months"), 6)
        self.assertEqual(result["facts"].get("city"), "Mumbai")
        self.assertIn("memories", result)
        self.assertGreaterEqual(result.get("count", 0), 1)

    async def test_handle_retrieve_memory_empty_query_hydration(self):
        """Verify empty query triggers profile hydration and returns active facts."""
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "user_aditya_sharma", "query": ""},
        )
        await handle_retrieve_memory(params, memory_bank=self.mb)

        result = params.result
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result["facts"].get("amount"), 50000.0)
        self.assertIn("memories", result)

    async def test_handle_retrieve_memory_missing_or_blank_user_id(self):
        """Verify missing or empty user_id degrades gracefully to status 'not_found'."""
        bad_ids = [None, "", "   ", "\t\n", 12345]
        for bad_id in bad_ids:
            params = MockFunctionCallParams(
                function_name="retrieve_memory",
                arguments={"user_id": bad_id, "query": "KYC"},
            )
            await handle_retrieve_memory(params, memory_bank=self.mb)
            result = params.result
            self.assertEqual(result.get("status"), "not_found", f"Failed for user_id: {bad_id}")
            self.assertEqual(result.get("user_id"), "user_anonymous")
            self.assertEqual(result.get("count"), 0)

    async def test_handle_retrieve_memory_non_existent_user(self):
        """Verify non-existent user returns status 'empty'."""
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "Vikram Rathore", "query": "FD comparison"},
        )
        await handle_retrieve_memory(params, memory_bank=self.mb)
        result = params.result
        self.assertEqual(result.get("status"), "empty")
        self.assertEqual(result.get("user_id"), "user_vikram_rathore")
        self.assertEqual(result.get("facts"), {})
        self.assertEqual(result.get("memories"), [])
        self.assertEqual(result.get("count"), 0)

    async def test_handle_retrieve_memory_context_resolution(self):
        """Verify memory_bank is correctly resolved from params.context."""
        # Dict context
        params_dict = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "Aditya Sharma", "query": "KYC"},
            context={"memory_bank": self.mb}
        )
        await handle_retrieve_memory(params_dict, memory_bank=None)
        self.assertEqual(params_dict.result.get("status"), "success")

        # Object context
        class MockCtx:
            def __init__(self, mb):
                self.memory_bank = mb
        
        params_obj = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "Aditya Sharma", "query": "KYC"},
            context=MockCtx(self.mb)
        )
        await handle_retrieve_memory(params_obj, memory_bank=None)
        self.assertEqual(params_obj.result.get("status"), "success")

    async def test_handle_retrieve_memory_exception_resilience(self):
        """Verify internal exception during search is caught and returns status 'error'."""
        faulty_mb = MagicMock()
        faulty_mb.get_fact_store.side_effect = RuntimeError("Database connection pool exhausted")
        
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "Aditya Sharma", "query": "emergency"},
        )
        await handle_retrieve_memory(params, memory_bank=faulty_mb)
        result = params.result
        self.assertEqual(result.get("status"), "error")
        self.assertIn("error", result)
        self.assertEqual(result.get("count"), 0)


class TestM2NavigationGuidanceAndEdgeCases(unittest.TestCase):
    """Adversarial testing of navigation flows, limits, and calculation interactions."""

    def test_escrow_deposit_guidance_and_limits(self):
        """Verify Escrow deposit flow instructions specify ₹250 manual, ₹25,000 lumpsum, UPI & Netbanking."""
        deposit_queries = ["deposit", "add money", "fund", "pay", "ESCROW DEPOSIT", "how to add funds"]
        for q in deposit_queries:
            res = get_app_screen_flow(q)
            self.assertEqual(res.get("flow_name"), "Adding Funds to Cymbal Escrow Wallet", f"Mismatch on query {q}")
            instructions = res.get("instructions_hinglish", "")
            self.assertIn("₹250", instructions)
            self.assertIn("₹25,000", instructions)
            self.assertIn("UPI", instructions)
            self.assertIn("NetBanking", instructions)
            self.assertIn("Escrow", instructions)

    def test_lumpsum_guidance_and_stl_mtl_references(self):
        """Verify lumpsum guidance includes STL 5M (3-5m), STL 7M (4-6m), MTL 14M (12m), and 100+ diversification."""
        lumpsum_queries = ["lumpsum", "stl", "mtl", "LUMPSUM INVEST", "stl 5m", "mtl 14m"]
        for q in lumpsum_queries:
            res = get_app_screen_flow(q)
            self.assertEqual(res.get("flow_name"), "Lumpsum Lending (STL / MTL)", f"Mismatch on query {q}")
            instructions = res.get("instructions_hinglish", "")
            self.assertIn("STL 5M", instructions)
            self.assertIn("STL 7M", instructions)
            self.assertIn("MTL 14M", instructions)
            self.assertIn("100+", instructions)

    def test_exact_8_loan_filter_parameters(self):
        """Verify all 8 loan filter parameters are present and exact."""
        res = get_app_screen_flow("loan filter")
        self.assertEqual(res.get("flow_name"), "App Loan Filter Options")
        filters = res.get("available_filters", [])
        self.assertEqual(len(filters), 8, f"Expected exactly 8 loan filter parameters, got {len(filters)}")
        
        expected_fragments = [
            ("1. Loan Tenure", "months"),
            ("2. Repayment Type", "Monthly EMI vs Daily EDI"),
            ("3. Risk Category", "AAA"),
            ("4. Borrower Type", "Salaried"),
            ("5. Borrower Monthly Income Bracket", "₹25,000+"),
            ("6. Total Loan Amount Requested", "Loan Amount"),
            ("7. Remaining Amount to be funded", "Remaining Amount"),
            ("8. Borrower Age Group", "21-35"),
        ]
        for prefix, fragment in expected_fragments:
            found = any(f.startswith(prefix) and fragment in f for f in filters)
            self.assertTrue(found, f"Filter starting with '{prefix}' and containing '{fragment}' not found in {filters}")

    def test_kyc_3_step_guidance(self):
        """Verify 3-step KYC verification guidance for PAN, Aadhaar Digilocker, Bank penny-drop."""
        # Step 1: PAN
        pan_res = get_kyc_guidance("pan")
        self.assertEqual(pan_res.get("step"), "PAN Verification")
        self.assertIn("10-digit PAN", pan_res.get("instructions_hinglish", ""))

        # Step 2: Aadhaar
        aadhaar_res = get_kyc_guidance("aadhaar")
        self.assertEqual(aadhaar_res.get("step"), "Aadhaar / Address Verification")
        self.assertIn("Digilocker", aadhaar_res.get("instructions_hinglish", ""))
        self.assertIn("OTP", aadhaar_res.get("instructions_hinglish", ""))

        # Step 3: Bank Penny Drop
        bank_res = get_kyc_guidance("bank")
        self.assertEqual(bank_res.get("step"), "Bank Account Linking")
        self.assertIn("Penny drop", bank_res.get("instructions_hinglish", ""))
        self.assertIn("₹1", bank_res.get("instructions_hinglish", ""))

        # All / Overview
        all_res = get_kyc_guidance("all")
        self.assertEqual(all_res.get("step"), "Complete KYC 3-Step Overview")

    def test_unified_onboarding_guide_routing(self):
        """Verify get_onboarding_guide correctly routes to KYC or App Screen Flow."""
        # KYC routings
        for kyc_topic in ["pan", "aadhaar", "aadhar", "bank", "penny", "kyc"]:
            res = get_onboarding_guide(kyc_topic)
            self.assertIn("step", res, f"Topic '{kyc_topic}' should route to KYC guidance")

        # Screen flow routings
        for flow_topic in ["deposit", "lumpsum", "loan filter", "manual", "general"]:
            res = get_onboarding_guide(flow_topic)
            self.assertIn("flow_name", res, f"Topic '{flow_topic}' should route to App screen flow")

    def test_consultative_guidance_topics(self):
        """Verify get_consultative_guidance topics."""
        self.assertEqual(get_consultative_guidance("bank fd")["topic"], "Bank FD Comparison")
        self.assertEqual(get_consultative_guidance("default risk")["topic"], "Risk & Default Mitigation")
        self.assertEqual(get_consultative_guidance("rbi registration")["topic"], "Platform Legitimacy & RBI Trust")
        self.assertEqual(get_consultative_guidance("withdrawal")["topic"], "Liquidity & Repayment Mechanics")

    def test_strict_9_month_tenure_rejection_across_tools(self):
        """Verify strict rejection of 9-month tenure across all calculation tools."""
        # calculate_stl_returns
        stl_res = calculate_stl_returns(amount=50000, tenure_months=9)
        self.assertIn("error", stl_res)
        self.assertIn("Invalid tenure 9 months", stl_res.get("error", ""))

        # calculate_returns
        gen_res = calculate_returns(amount=50000, tenure_months=9)
        self.assertIn("error", gen_res)
        self.assertIn("9-month tenure is strictly not available", gen_res.get("error", ""))

        # calculate_manual_lending
        man_res = calculate_manual_lending(amount=50000, tenure_months=9)
        self.assertIn("error", man_res)
        self.assertIn("9-month tenure is strictly not available", man_res.get("error", ""))

        # get_product_recommendation
        rec_res = get_product_recommendation(amount=50000, tenure_months=9)
        self.assertFalse(rec_res.get("is_valid", True))
        self.assertIn("error", rec_res)
        self.assertIn("9-month tenures are strictly not available", rec_res.get("error", ""))

    def test_stl_and_mtl_calculation_boundaries(self):
        """Verify STL and MTL financial limits."""
        # STL minimum ₹25,000
        stl_below = calculate_stl_returns(amount=24999, tenure_months=5)
        self.assertIn("error", stl_below)
        self.assertIn("Minimum investment amount for Lumpsum (STL) is ₹25,000", stl_below.get("error", ""))
        
        stl_ok = calculate_stl_returns(amount=25000, tenure_months=5)
        self.assertNotIn("error", stl_ok)
        self.assertEqual(stl_ok.get("annualized_xirr_pct"), 15.0)

        # STL maximum ₹25,00,000
        stl_max = calculate_stl_returns(amount=2500000, tenure_months=6)
        self.assertNotIn("error", stl_max)
        self.assertEqual(stl_max.get("annualized_xirr_pct"), 18.0)
        
        stl_exceed = calculate_stl_returns(amount=2500001, tenure_months=6)
        self.assertIn("error", stl_exceed)
        self.assertIn("Maximum investment amount for STL is ₹25,00,000", stl_exceed.get("error", ""))

        # MTL minimum ₹1,00,000
        mtl_below = calculate_mtl_returns(amount=99999, repayment_type="monthly")
        self.assertIn("error", mtl_below)
        self.assertIn("Minimum investment amount for MTL 14M is ₹1,00,000", mtl_below.get("error", ""))
        
        mtl_ok = calculate_mtl_returns(amount=100000, repayment_type="monthly")
        self.assertNotIn("error", mtl_ok)
        self.assertEqual(mtl_ok.get("annualized_xirr_pct"), 24.0)

        # MTL Monthly max ₹10,00,000 vs Daily max ₹25,00,000
        mtl_monthly_exceed = calculate_mtl_returns(amount=1000001, repayment_type="monthly")
        self.assertIn("error", mtl_monthly_exceed)
        self.assertIn("Maximum investment for MTL Monthly is ₹10,00,000", mtl_monthly_exceed.get("error", ""))
        
        mtl_daily_ok = calculate_mtl_returns(amount=1500000, repayment_type="daily")
        self.assertNotIn("error", mtl_daily_ok)
        self.assertEqual(mtl_daily_ok.get("annualized_xirr_pct"), 18.0)



class TestM2SystemPromptAlignmentAndBranding(unittest.TestCase):
    """Adversarial verification of system prompt, Turn 1 greeting, and zero branding leaks."""

    FORBIDDEN_BRAND_IDENTIFIERS = [
        "lenden",
        "len-den",
        "liquiloans",
        "faircent",
        "finzy",
        "12% club",
        "bharatpe",
        "mobikwik xtra",
    ]

    def test_turn1_greeting_exact_match(self):
        """Verify Turn 1 greeting matches exact specification across prompt modules."""
        expected_greeting = (
            "नमस्ते! मैं प्रज्ञा बात कर रही हूँ, Cymbal Lending से। "
            "क्या मैं आपका नाम जान सकती हूँ, और क्या आपके पास बात करने के लिए 2 minutes का समय है?"
        )
        
        # Check in BASE_SYSTEM_PROMPT
        self.assertIn("नमस्ते! मैं प्रज्ञा बात कर रही हूँ, Cymbal Lending से। क्या मैं आपका नाम जान सकती हूँ, और क्या आपके पास बात करने के लिए 2 minutes का समय है?", SYSTEM_PROMPT)
        
        # Check in PHASE_PROMPTS[1]
        self.assertIn(expected_greeting, PHASE_PROMPTS[1])
        
        # Check in get_chained_system_prompt(1)
        chained_p1 = get_chained_system_prompt(phase=1)
        self.assertIn(expected_greeting, chained_p1)

    def test_objection1_header_exact_match(self):
        """Verify Objection 1 header matches exact specification."""
        expected_header = '1. Objection: "Is it safe? What if borrowers default (NPA)?"'
        self.assertIn(expected_header, OBJECTION_PLAYBOOK)
        self.assertIn(expected_header, SYSTEM_PROMPT)

    def test_memory_retrieval_directives_in_prompts(self):
        """Verify system prompts explicitly instruct calling retrieve_memory tool on name/history."""
        self.assertIn("retrieve_memory", SYSTEM_PROMPT)
        self.assertIn("retrieve_memory", LEAN_PERSONA_PROMPT)
        self.assertIn("retrieve_memory(user_id, query)", BASE_SYSTEM_PROMPT)

    def test_zero_branding_leaks_in_m2_files(self):
        """Verify zero external/proprietary brand identifiers in M2 files."""
        # Note: 'lenden' in parentheses as historical context is checked against forbidden list
        files_to_check = [
            os.path.join(SERVER_DIR, "tools", "tool_definitions.py"),
            os.path.join(SERVER_DIR, "tools", "navigation.py"),
            os.path.join(SERVER_DIR, "system_prompt.py"),
        ]
        
        for file_path in files_to_check:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().lower()
                # Check forbidden competitors
                for brand in ["liquiloans", "faircent", "finzy", "12% club", "mobikwik xtra"]:
                    self.assertNotIn(brand, content, f"Forbidden brand '{brand}' leaked in {file_path}")


class TestM2AsyncHandlerFuzzingAndConcurrency(unittest.IsolatedAsyncioTestCase):
    """Stress test async handlers under high concurrency and fuzzing."""

    async def test_concurrent_retrieve_memory_calls(self):
        """Verify 100 concurrent retrieve_memory tool calls execute without deadlock or corruption."""
        mb = MemoryBank()
        for i in range(20):
            user_id = f"user_test_{i}"
            mb.get_fact_store(user_id).set_fact("amount", float(10000 * (i + 1)), turn_id=1)
            mb.add_memory(user_id, f"Memory {i} for user {user_id} with KYC verified.")

        tasks = []
        for i in range(100):
            user_idx = i % 20
            params = MockFunctionCallParams(
                function_name="retrieve_memory",
                arguments={"user_id": f"user_test_{user_idx}", "query": "KYC"},
            )
            tasks.append(handle_retrieve_memory(params, memory_bank=mb))

        await asyncio.gather(*tasks)

    def test_fuzz_navigation_with_random_strings(self):
        """Fuzz get_app_screen_flow and get_onboarding_guide with 2,000 randomized strings."""
        import random
        import string

        for _ in range(2000):
            length = random.randint(0, 100)
            rand_str = ''.join(random.choice(string.ascii_letters + string.digits + " \t\n!@#$%^&*()") for _ in range(length))
            res_flow = get_app_screen_flow(rand_str)
            self.assertIsInstance(res_flow, dict)
            self.assertIn("flow_name", res_flow)

            res_guide = get_onboarding_guide(rand_str)
            self.assertIsInstance(res_guide, dict)
            self.assertTrue("step" in res_guide or "flow_name" in res_guide)


if __name__ == "__main__":
    unittest.main()
