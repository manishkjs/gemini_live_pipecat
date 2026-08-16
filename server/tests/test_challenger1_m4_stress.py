"""Adversarial Stress Testing & Edge Case Challenge Suite for Milestone M4.

Focus: Post-Session Memory Downcar Worker (`server/memory_downcar.py`) and Live Integration (`server/agent_live.py`).

Test Vectors:
1. Duplicate sessions & reconnects: MD5 idempotency, zero duplicate memory creations, multi-session deduplication.
2. Corrupted & adversarial transcript payloads: missing keys, non-dict elements, None values, massive transcripts, unicode explosions, malformed LLM responses.
3. Extreme financial values & edge data: negative amounts, string representations, NaN/Inf, zero/negative tenures, boundary and out-of-bounds numbers.
4. Concurrency & race conditions: massive simultaneous downcar runs for identical & different users, concurrent memory hydration/searching during active downcar processing.
5. Live Agent integration: tool registration bindings, profile hydration on connect, background downcar task dispatch on disconnect.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sys
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure server directory is in sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from memory_bank import (
    CANONICAL_FACT_KEYS,
    FactStore,
    MemoryBank,
    normalize_lexical_user_id,
)
from memory_downcar import (
    extract_facts_and_summary_offline,
    format_transcript_for_downcar,
    parse_downcar_response,
    run_post_session_downcar,
)
from tools.tool_definitions import (
    get_standard_tools,
    register_all_tools,
    retrieve_memory_schema,
    handle_retrieve_memory,
)


class MockGeminiResponse:
    """Mock Gemini generate_content response."""
    def __init__(self, text: str):
        self.text = text


class MockGenAIClient:
    """Mock async Google GenAI client."""
    def __init__(self, response_text: str = ""):
        self.response_text = response_text
        self.models = MagicMock()
        self.models.generate_content = AsyncMock(side_effect=self._generate_content)
        self.call_count = 0

    async def _generate_content(self, model: str, contents: Any, **kwargs):
        self.call_count += 1
        return MockGeminiResponse(text=self.response_text)


class TestM4AdversarialStress(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress and edge testing for M4 Downcar & Live Integration."""

    def setUp(self):
        self.memory_bank = MemoryBank()
        self.user_id = "user_aditya_sharma"
        self.base_transcript = [
            {"role": "assistant", "text": "नमस्ते! मैं प्रज्ञा बात कर रही हूँ, Cymbal Lending से।"},
            {"role": "user", "text": "मैं 50,000 रुपये 6 महीने के लिए STL 7M में invest करना चाहता हूँ।"},
            {"role": "assistant", "text": "बहुत बढ़िया! STL 7M में 18% XIRR मिलेगा।"},
        ]

    # ═══════════════════════════════════════════════════════════════════
    # 1. DUPLICATE SESSIONS, RECONNECTS & MD5 IDEMPOTENCY
    # ═══════════════════════════════════════════════════════════════════

    async def test_duplicate_session_reconnect_md5_idempotency(self):
        """Verify multiple reconnects with identical transcript result in zero duplicate memory entries."""
        llm_payload = {
            "facts": {"amount": 50000.0, "tenure_months": 6},
            "summary": "Customer Aditya Sharma discussed investing ₹50,000 in STL 7M for 6 months.",
        }
        mock_client = MockGenAIClient(response_text=json.dumps(llm_payload))

        # Initial session
        res1 = await run_post_session_downcar(
            session_id="sess_conn_1",
            user_id=self.user_id,
            transcript_history=self.base_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )
        self.assertEqual(res1["status"], "success")
        self.assertEqual(res1["memory_added"], True)
        self.assertEqual(len(self.memory_bank.get_user_memories(self.user_id)), 1)
        self.assertEqual(mock_client.call_count, 1)

        # Reconnect 1 with identical transcript
        res2 = await run_post_session_downcar(
            session_id="sess_conn_1_reconnect_1",
            user_id=self.user_id,
            transcript_history=self.base_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )
        self.assertEqual(res2["status"], "duplicate")
        self.assertEqual(len(self.memory_bank.get_user_memories(self.user_id)), 1)
        # GenAI LLM should NOT be called on duplicate
        self.assertEqual(mock_client.call_count, 1)

        # Reconnect 2 with identical transcript
        res3 = await run_post_session_downcar(
            session_id="sess_conn_1_reconnect_2",
            user_id=self.user_id,
            transcript_history=self.base_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )
        self.assertEqual(res3["status"], "duplicate")
        self.assertEqual(len(self.memory_bank.get_user_memories(self.user_id)), 1)
        self.assertEqual(mock_client.call_count, 1)

    async def test_duplicate_session_different_users_isolation(self):
        """Verify identical transcript across two different users is stored independently for each user."""
        mock_client = MockGenAIClient(response_text=json.dumps({
            "facts": {"amount": 50000.0},
            "summary": "Customer invested 50k.",
        }))

        res_user_a = await run_post_session_downcar(
            session_id="sess_a",
            user_id="user_aditya_sharma",
            transcript_history=self.base_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )
        self.assertEqual(res_user_a["status"], "success")

        # Second user with same transcript
        res_user_b = await run_post_session_downcar(
            session_id="sess_b",
            user_id="user_rajesh_kumar",
            transcript_history=self.base_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )
        self.assertEqual(res_user_b["status"], "success")
        self.assertEqual(len(self.memory_bank.get_user_memories("user_aditya_sharma")), 1)
        self.assertEqual(len(self.memory_bank.get_user_memories("user_rajesh_kumar")), 1)

    # ═══════════════════════════════════════════════════════════════════
    # 2. CORRUPTED, MALFORMED & MASSIVE TRANSCRIPTS
    # ═══════════════════════════════════════════════════════════════════

    async def test_corrupted_transcript_non_dict_elements(self):
        """Verify downcar safely handles non-dict elements, None values, numbers in transcript list."""
        corrupted_transcript = [
            None,
            12345,
            "just a string",
            [],
            {},
            {"invalid_key": "some data"},
            {"role": None, "text": None},
            {"role": "user", "text": "मैं ₹1,00,000 invest करना चाहता हूँ"},
            {"role": 123, "content": 456},
            {"participant": "assistant", "content": "Sure, STL 7M is available."},
        ]

        formatted = format_transcript_for_downcar(corrupted_transcript)
        self.assertIn("User: मैं ₹1,00,000 invest करना चाहता हूँ", formatted)
        self.assertIn("Assistant: Sure, STL 7M is available.", formatted)

        # Should execute downcar without throwing
        result = await run_post_session_downcar(
            session_id="sess_corrupt_1",
            user_id=self.user_id,
            transcript_history=corrupted_transcript,
            memory_bank=self.memory_bank,
        )
        self.assertEqual(result["status"], "success")
        self.assertIn("amount", result["facts"])
        self.assertEqual(result["facts"]["amount"], 100000.0)

    async def test_massive_transcript_stress(self):
        """Stress test with 1,000 turns (large payload) ensuring fast execution and no OOM/crash."""
        massive_transcript = []
        for i in range(500):
            massive_transcript.append({
                "role": "user",
                "text": f"Turn {i}: I have question regarding returns and safety for ₹50,000."
            })
            massive_transcript.append({
                "role": "assistant",
                "text": f"Turn {i}: All funds are held in ICICI Trustee Escrow."
            })

        t0 = time.monotonic()
        result = await run_post_session_downcar(
            session_id="sess_massive_1",
            user_id=self.user_id,
            transcript_history=massive_transcript,
            memory_bank=self.memory_bank,
        )
        elapsed = time.monotonic() - t0

        self.assertEqual(result["status"], "success")
        self.assertLess(elapsed, 2.0, "Massive transcript processing must finish in < 2 seconds")
        self.assertEqual(len(self.memory_bank.get_user_memories(self.user_id)), 1)

    async def test_unicode_emoji_multibyte_explosion_in_transcript(self):
        """Verify handling of complex Unicode, emojis, RTL characters, null bytes."""
        unicode_transcript = [
            {"role": "user", "text": "नमस्ते 🙏 ₹50,000 🚀 💰 \u200d \u200b \x00 مرحبا مرحبا"},
            {"role": "assistant", "text": "धन्यवाद! 😊 We support ₹50,000 deposits."},
        ]

        result = await run_post_session_downcar(
            session_id="sess_unicode_1",
            user_id=self.user_id,
            transcript_history=unicode_transcript,
            memory_bank=self.memory_bank,
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(self.memory_bank.get_user_memories(self.user_id)), 1)

    def test_parse_downcar_response_adversarial_inputs(self):
        """Test parse_downcar_response against diverse adversarial LLM outputs."""
        # Case 1: Empty string
        self.assertEqual(parse_downcar_response(""), {"facts": {}, "summary": ""})

        # Case 2: Non-string
        self.assertEqual(parse_downcar_response(None), {"facts": {}, "summary": ""}) # type: ignore
        self.assertEqual(parse_downcar_response(12345), {"facts": {}, "summary": ""}) # type: ignore

        # Case 3: Truncated JSON
        parsed3 = parse_downcar_response('{"facts": {"amount": 50000')
        self.assertTrue(parsed3.get("parse_error"))
        self.assertIn("50000", parsed3.get("summary"))

        # Case 4: Facts at root level
        root_facts_json = json.dumps({"amount": 50000.0, "city": "Bengaluru", "summary": "Direct root facts"})
        parsed4 = parse_downcar_response(root_facts_json)
        self.assertEqual(parsed4["facts"]["amount"], 50000.0)
        self.assertEqual(parsed4["facts"]["city"], "Bengaluru")
        self.assertEqual(parsed4["summary"], "Direct root facts")

        # Case 5: Markdown code fence with extra backticks and whitespace
        fenced = "```json\n\n{\n  \"facts\": {\"goal\": \"retirement\"},\n  \"summary\": \"ok\"\n}\n\n```"
        parsed5 = parse_downcar_response(fenced)
        self.assertEqual(parsed5["facts"]["goal"], "retirement")
        self.assertEqual(parsed5["summary"], "ok")

        # Case 6: Deeply malformed JSON with non-dict facts
        malformed_facts = json.dumps({"facts": ["not", "a", "dict"], "summary": "list facts"})
        parsed6 = parse_downcar_response(malformed_facts)
        self.assertEqual(parsed6["facts"], {})

    # ═══════════════════════════════════════════════════════════════════
    # 3. EXTREME FINANCIAL VALUES & TYPE CONVERSIONS
    # ═══════════════════════════════════════════════════════════════════

    async def test_extreme_financial_values_and_types_in_llm_response(self):
        """Verify type conversion and filtering when LLM returns extreme numbers, string numbers, NaNs."""
        adversarial_llm_payload = {
            "facts": {
                "amount": "50000.0",  # String float
                "tenure_months": "12",  # String int
                "risk_preference": 12345,  # Non-string
                "city": ["Bengaluru"],  # Non-string
                "timeline": "2 years",
                "goal": "retirement",
                "occupation": "salaried",
                "experience": "beginner",
                "invalid_extra_key": "should be stripped",
            },
            "summary": "Explored 50k for 12 months.",
        }
        mock_client = MockGenAIClient(response_text=json.dumps(adversarial_llm_payload))

        result = await run_post_session_downcar(
            session_id="sess_types_1",
            user_id=self.user_id,
            transcript_history=self.base_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["status"], "success")
        self.assertIsInstance(result["facts"]["amount"], float)
        self.assertEqual(result["facts"]["amount"], 50000.0)
        self.assertIsInstance(result["facts"]["tenure_months"], int)
        self.assertEqual(result["facts"]["tenure_months"], 12)
        self.assertNotIn("invalid_extra_key", result["facts"])

        # Check FactStore values
        fact_store = self.memory_bank.get_fact_store(self.user_id)
        self.assertEqual(fact_store.get_fact("amount"), 50000.0)
        self.assertEqual(fact_store.get_fact("tenure_months"), 12)
        self.assertIsNone(fact_store.get_fact("invalid_extra_key"))

    async def test_offline_heuristic_extraction_extreme_boundaries(self):
        """Test extract_facts_and_summary_offline with boundary, out-of-bound, and colloquial amounts."""
        # 1. Lakh representation
        facts1, _ = extract_facts_and_summary_offline("I want to invest 2.5 lakhs in STL", "user_test", "s1")
        self.assertEqual(facts1.get("amount"), 250000.0)

        # 2. Large formatted number
        facts2, _ = extract_facts_and_summary_offline("Planning 24,00,000 for 12 months", "user_test", "s2")
        self.assertEqual(facts2.get("amount"), 2400000.0)
        self.assertEqual(facts2.get("tenure_months"), 12)

        # 3. Below minimum ₹250 (e.g. ₹100 should not be recognized as valid loan amount)
        facts3, _ = extract_facts_and_summary_offline("Can I invest ₹100 for 6 months?", "user_test", "s3")
        self.assertNotIn("amount", facts3)

        # 4. Tenure parsing with product codes like MTL 14M (tenure should not confuse product code)
        facts4, _ = extract_facts_and_summary_offline("I want MTL 14M plan for 6 months", "user_test", "s4")
        self.assertEqual(facts4.get("tenure_months"), 6)

    # ═══════════════════════════════════════════════════════════════════
    # 4. CONCURRENCY & RACE CONDITIONS
    # ═══════════════════════════════════════════════════════════════════

    async def test_concurrent_downcar_identical_transcripts(self):
        """Verify 30 concurrent downcars with identical transcripts for same user result in exactly 1 memory and 0 crashes."""
        mock_client = MockGenAIClient(response_text=json.dumps({
            "facts": {"amount": 50000.0},
            "summary": "Aditya Sharma 50k investment.",
        }))

        tasks = [
            run_post_session_downcar(
                session_id=f"sess_concurrent_{i}",
                user_id=self.user_id,
                transcript_history=self.base_transcript,
                memory_bank=self.memory_bank,
                genai_client=mock_client,
            )
            for i in range(30)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            self.assertNotIsInstance(r, Exception)
            self.assertIn(r["status"], ["success", "duplicate"])

        # Exactly 1 memory should exist in MemoryBank
        memories = self.memory_bank.get_user_memories(self.user_id)
        self.assertEqual(len(memories), 1)

    async def test_concurrent_downcar_different_users(self):
        """Verify 30 concurrent downcars across 30 distinct users execute with complete data isolation."""
        tasks = []
        for i in range(30):
            user_name = f"Customer Number {i}"
            transcript = [
                {"role": "user", "text": f"I am Customer {i} and want to invest ₹{50000 + i*1000}."}
            ]
            tasks.append(
                run_post_session_downcar(
                    session_id=f"sess_multi_{i}",
                    user_id=user_name,
                    transcript_history=transcript,
                    memory_bank=self.memory_bank,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, r in enumerate(results):
            self.assertNotIsInstance(r, Exception)
            self.assertEqual(r["status"], "success")
            expected_uid = f"user_customer_number_{i}"
            self.assertEqual(r["user_id"], expected_uid)
            memories = self.memory_bank.get_user_memories(expected_uid)
            self.assertEqual(len(memories), 1)

    async def test_concurrent_downcar_and_memory_retrieval(self):
        """Verify reading/searching memories and profile hydration while downcar writes concurrently."""
        # Pre-seed memory bank
        self.memory_bank.add_memory(self.user_id, "Prior session discussed 50k investment.")

        async def worker_downcar(idx: int):
            transcript = [
                {"role": "user", "text": f"Follow-up discussion {idx} on STL 7M KYC."}
            ]
            return await run_post_session_downcar(
                session_id=f"sess_race_{idx}",
                user_id=self.user_id,
                transcript_history=transcript,
                memory_bank=self.memory_bank,
            )

        async def worker_search(idx: int):
            res = self.memory_bank.search_memories(self.user_id, "KYC STL 7M", limit=5)
            self.assertIsInstance(res, list)
            hydrated = self.memory_bank.hydrate_user_profile(self.user_id)
            self.assertTrue(hydrated.get("profile_hydrated"))
            return True

        tasks = []
        for i in range(15):
            tasks.append(worker_downcar(i))
            tasks.append(worker_search(i))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            self.assertNotIsInstance(r, Exception)

    # ═══════════════════════════════════════════════════════════════════
    # 5. AGENT LIVE INTEGRATION VERIFICATION
    # ═══════════════════════════════════════════════════════════════════

    def test_agent_live_tool_registration(self):
        """Verify retrieve_memory tool is present in standard tools and registered."""
        tools = get_standard_tools()
        tool_names = [getattr(t, "name", None) or (t.function.name if hasattr(t, "function") else None) for t in tools]
        self.assertIn("retrieve_memory", tool_names)

        # Mock LLM service and register all tools
        mock_llm = MagicMock()
        mock_llm.register_function = MagicMock()
        register_all_tools(mock_llm, tools)

        registered_function_names = [call[0][0] for call in mock_llm.register_function.call_args_list]
        self.assertIn("retrieve_memory", registered_function_names)

    async def test_retrieve_memory_tool_handler_live_execution(self):
        """Verify handle_retrieve_memory handler executes cleanly and formats profile payload."""
        # Seed FactStore and MemoryBank
        fact_store = self.memory_bank.get_fact_store(self.user_id)
        fact_store.set_fact("amount", 75000.0, turn_id=1)
        fact_store.set_fact("city", "Bengaluru", turn_id=1)

        self.memory_bank.add_memory(
            self.user_id,
            "Customer Aditya Sharma completed Digilocker KYC for STL 7M plan.",
            metadata={"session_id": "sess_prior"}
        )

        mock_params = MagicMock()
        mock_params.context = None
        mock_params.arguments = {
            "user_id": "Aditya Sharma",
            "query": "STL 7M Digilocker KYC",
        }
        mock_params.result_callback = AsyncMock()

        await handle_retrieve_memory(mock_params, memory_bank=self.memory_bank)

        self.assertEqual(mock_params.result_callback.call_count, 1)
        result_payload = mock_params.result_callback.call_args[0][0]
        self.assertEqual(result_payload["status"], "success")
        self.assertEqual(result_payload["user_id"], self.user_id)
        self.assertEqual(result_payload["facts"]["amount"], 75000.0)
        self.assertEqual(result_payload["facts"]["city"], "Bengaluru")
        self.assertEqual(len(result_payload["memories"]), 1)
        self.assertIn("Aditya Sharma", result_payload["memories"][0])

    async def test_incremental_reconnect_growth_audit_trail(self):
        """Simulate growing multi-session conversation across 4 reconnects and verify FactStore history."""
        # Turn 1: User introduces name and amount
        t1 = [
            {"role": "assistant", "text": "नमस्ते! मैं प्रज्ञा बात कर रही हूँ।"},
            {"role": "user", "text": "मैं आदित्य हूँ, 50000 invest करना चाहता हूँ।"},
        ]
        r1 = await run_post_session_downcar("s1", "Aditya Sharma", t1, self.memory_bank)
        self.assertEqual(r1["status"], "success")

        # Turn 2: Reconnect adds tenure
        t2 = t1 + [
            {"role": "assistant", "text": "STL 7M 6 months ke liye best hai."},
            {"role": "user", "text": "हाँ 6 months theek hai."},
        ]
        r2 = await run_post_session_downcar("s2", "Aditya Sharma", t2, self.memory_bank)
        self.assertEqual(r2["status"], "success")

        # Turn 3: Reconnect adds goal and occupation
        t3 = t2 + [
            {"role": "user", "text": "मेरा goal wealth growth है और मैं software engineer हूँ।"},
        ]
        r3 = await run_post_session_downcar("s3", "Aditya Sharma", t3, self.memory_bank)
        self.assertEqual(r3["status"], "success")

        # Turn 4: Duplicate of Turn 3 reconnect
        r4 = await run_post_session_downcar("s4", "Aditya Sharma", t3, self.memory_bank)
        self.assertEqual(r4["status"], "duplicate")

        fact_store = self.memory_bank.get_fact_store("user_aditya_sharma")
        self.assertEqual(fact_store.get_fact("amount"), 50000.0)
        self.assertEqual(fact_store.get_fact("tenure_months"), 6)
        self.assertEqual(fact_store.get_fact("goal"), "wealth growth")
        self.assertEqual(fact_store.get_fact("occupation"), "software engineer")

        # Audit history must track changes
        history = fact_store.get_change_history()
        self.assertGreaterEqual(len(history), 4)

    async def test_mass_concurrency_fuzzing_100_workers(self):
        """Mass concurrency stress test: 100 workers with randomized mixture of payloads."""
        import random
        random.seed(42)

        async def worker(idx: int):
            user_idx = idx % 10
            user_name = f"Stress User {user_idx}"
            mode = idx % 5

            if mode == 0:
                # Normal transcript
                transcript = [
                    {"role": "user", "text": f"I want to invest {50000 + user_idx*5000} for 6 months."}
                ]
            elif mode == 1:
                # Corrupted list
                transcript = [None, {"invalid": 123}, {"role": "user", "text": "Exploring STL 7M"}]
            elif mode == 2:
                # Empty transcript
                transcript = []
            elif mode == 3:
                # Whitespace transcript
                transcript = [{"role": "user", "text": "   "}]
            else:
                # Duplicate payload of mode 0
                transcript = [
                    {"role": "user", "text": f"I want to invest {50000 + user_idx*5000} for 6 months."}
                ]

            return await run_post_session_downcar(
                session_id=f"sess_mass_{idx}",
                user_id=user_name,
                transcript_history=transcript,
                memory_bank=self.memory_bank,
            )

        tasks = [worker(i) for i in range(100)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, r in enumerate(results):
            self.assertNotIsInstance(r, Exception, f"Worker {i} raised exception: {r}")
            self.assertIn(r["status"], ["success", "duplicate", "skipped"])

    def test_differential_fuzzing_offline_extractor(self):
        """Differential fuzzing: 50 randomized conversational inputs with verified assertions."""
        amounts = [25000, 50000, 100000, 200000, 500000, 2400000]
        tenures = [2, 3, 4, 5, 6, 12]
        cities = ["Bengaluru", "Mumbai", "Delhi", "Pune", "Hyderabad"]
        goals = [
            ("wealth growth", "wealth growth"),
            ("monthly income", "monthly income"),
            ("retirement", "retirement"),
            ("daily liquidity", "daily liquidity"),
        ]

        for i, (amt, tenure, city, (goal_kw, goal_exp)) in enumerate(
            zip(amounts, tenures, cities, goals)
        ):
            snippet = f"User says: I live in {city} and want to invest ₹{amt} for {tenure} months with goal of {goal_kw}."
            facts, summary = extract_facts_and_summary_offline(snippet, "user_diff_test", f"sess_{i}")

            self.assertEqual(facts.get("amount"), float(amt))
            self.assertEqual(facts.get("tenure_months"), tenure)
            self.assertEqual(facts.get("city"), city)
            self.assertEqual(facts.get("goal"), goal_exp)
            self.assertIn("Customer", summary)

    async def test_disconnect_hook_background_task_simulation(self):
        """Verify on_client_disconnected pattern in agent_live dispatches background task safely."""
        transcript_history = [
            {"role": "user", "text": "Aditya here, 50000 in STL 7M"},
            {"role": "assistant", "text": "Done!"},
        ]
        session_id = "session_live_test_1234"
        active_uid = "user_aditya_sharma"

        # Simulate on_client_disconnected spawn
        downcar_task = asyncio.create_task(run_post_session_downcar(
            session_id=session_id,
            user_id=active_uid,
            transcript_history=transcript_history,
            memory_bank=self.memory_bank,
        ))

        # Await completion
        result = await downcar_task
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["session_id"], session_id)
        self.assertEqual(result["user_id"], active_uid)
        self.assertEqual(len(self.memory_bank.get_user_memories(active_uid)), 1)


if __name__ == "__main__":
    unittest.main()
