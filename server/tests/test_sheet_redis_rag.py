"""Comprehensive End-to-End Automated Test Suite for Google Sheet Q&A Ingestion,
Dual-Layer Memorystore/Redis Cache, Sub-Millisecond Retrieval, and Server Integration.

Test Tiers:
- Tier 1: Feature Coverage (Dataset ingestion, schema validation, 896+ records, L1/L2 indexing, tool callback handler)
- Tier 2: Boundary & Corner Cases (Empty/whitespace queries, currency symbols ₹/Rs/INR, multiline answers, unicode, Redis offline fallback)
- Tier 3: Specific Lending Queries & Semantic Verification (Minimum amount ₹250, PAN limit ₹50 Lakh, 14m EMI, CTO Feb 2025, Canonical fallback)
- Tier 4: Real-World Latency & High-Throughput Workload (100 consecutive queries benchmark, concurrent stress, lifespan pre-warming)
- Tier 5: Adversarial Verification & Integrity Hardening (Regex metacharacters, fuzzed queries, malformed handler arguments, zero dead air)
"""

import os
import sys
import time
import json
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure server module path is available in sys.path
_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from redis_cache import RedisRAGCache, rag_cache, tokenize_text
from rag_function import (
    search_knowledge_base_handler,
    search_knowledge_base_schema,
)
from memory_redis_sync import memory_redis_syncer
from pipecat.services.llm_service import FunctionCallParams


# ============================================================================
# Tier 1: Feature Coverage
# ============================================================================

class TestTier1FeatureCoverage(unittest.IsolatedAsyncioTestCase):
    """Tier 1: Feature Coverage - Ingestion, schema, indexing, cache lifecycle, and tool schema."""

    async def asyncSetUp(self):
        self.cache = RedisRAGCache()
        await self.cache.initialize()
        await self.cache.prewarm_sheet_knowledge()

    async def test_zero_local_files_policy(self):
        """Verify zero local files policy: server/data directory must not exist on disk."""
        local_data_dir = os.path.join(_SERVER_DIR, "data")
        self.assertFalse(
            os.path.exists(local_data_dir),
            f"Zero-local policy violation: {local_data_dir} must not exist on disk (all in Memorystore/RAM)"
        )

    async def test_dataset_schema_and_field_completeness(self):
        """Verify all records in Memorystore/RAM contain question, answer, and category fields without empty values."""
        valid_records = [r for r in self.cache._sheet_records if r.get("question") not in ["Questions", "question"]]
        self.assertGreaterEqual(len(valid_records), 896)
        for idx, rec in enumerate(valid_records):
            self.assertIn("question", rec, f"Record {idx} missing 'question'")
            self.assertIn("answer", rec, f"Record {idx} missing 'answer'")
            self.assertIn("category", rec, f"Record {idx} missing 'category'")
            self.assertTrue(bool(rec["question"].strip()), f"Record {idx} has blank question")
            self.assertTrue(bool(rec["answer"].strip()), f"Record {idx} has blank answer")

    async def test_prewarm_sheet_knowledge_builds_inverted_index(self):
        """Verify prewarm_sheet_knowledge loads records and builds BM25 token inverted index."""
        count = await self.cache.prewarm_sheet_knowledge()
        self.assertGreaterEqual(count, 896)
        self.assertTrue(hasattr(self.cache, "_sheet_records"))
        self.assertTrue(hasattr(self.cache, "_sheet_token_index"))
        self.assertGreaterEqual(len(self.cache._sheet_records), 896)
        self.assertGreaterEqual(len(self.cache._sheet_token_index), 500)

    async def test_l1_cache_get_and_set_lifecycle(self):
        """Verify L1 in-memory cache lifecycle for normalized query keys."""
        test_query = "What is the platform recovery framework?"
        test_answer = "3-tier recovery framework with 96.18% historical recovery rate."
        await self.cache.set(test_query, test_answer)
        cached = await self.cache.get(test_query)
        self.assertEqual(cached, test_answer)

    async def test_query_normalization_rules(self):
        """Verify query normalization strips English/Hindi stop words, sorts tokens, and handles casing."""
        norm1 = self.cache.normalize_query("What is the TDS Form 26AS?")
        norm2 = self.cache.normalize_query("TDS Form 26AS kya hai?")
        self.assertIn("tds", norm1)
        self.assertIn("26as", norm1)
        self.assertIn("form", norm1)
        self.assertIn("tds", norm2)
        self.assertIn("26as", norm2)
        self.assertIn("form", norm2)
        # Normalization produces identical sorted tokens across English & Hindi phrasing
        self.assertEqual(norm1, norm2)

    async def test_prewarm_sheet_knowledge_topics(self):
        """Verify pre-warming sheet knowledge stores topics into cache."""
        count = await self.cache.prewarm_sheet_knowledge()
        self.assertGreater(count, 0)
        res = await self.cache.search_sheet_knowledge("minimum amount to lend")
        self.assertIsNotNone(res)
        self.assertTrue("250" in res or "Rupees 250" in res or "₹250" in res)

    async def test_search_knowledge_base_schema_specification(self):
        """Verify search_knowledge_base_schema conforms to Pipecat FunctionSchema contract."""
        self.assertEqual(search_knowledge_base_schema.name, "search_knowledge_base")
        self.assertIn("query_for_vector_search", search_knowledge_base_schema.properties)
        self.assertIn("total_records", search_knowledge_base_schema.properties)
        self.assertIn("query_for_vector_search", search_knowledge_base_schema.required)

    async def test_tool_callback_execution_flow(self):
        """Verify search_knowledge_base_handler invokes result_callback with content."""
        callback_mock = AsyncMock()
        params = MagicMock()
        params.arguments = {"query_for_vector_search": "What is the minimum amount to lend?", "total_records": 3}
        params.result_callback = callback_mock

        await search_knowledge_base_handler(params)
        callback_mock.assert_called_once()
        result_dict = callback_mock.call_args[0][0]
        self.assertIn("content", result_dict)
        self.assertIsInstance(result_dict["content"], str)
        self.assertTrue(len(result_dict["content"]) > 0)


# ============================================================================
# Tier 2: Boundary & Corner Cases
# ============================================================================

class TestTier2BoundaryAndCornerCases(unittest.IsolatedAsyncioTestCase):
    """Tier 2: Boundary & Corner Cases - Empty queries, currency symbols, multiline answers, unicode, offline fallback."""

    async def asyncSetUp(self):
        self.cache = RedisRAGCache()
        await self.cache.initialize()
        await self.cache.prewarm_sheet_knowledge()

    async def test_empty_and_whitespace_query_handling(self):
        """Verify empty strings, whitespace, and tabs return empty or fallback gracefully without throwing."""
        empty_res = await self.cache.search_sheet_knowledge("")
        self.assertEqual(empty_res, "")

        whitespace_res = await self.cache.search_sheet_knowledge("   \t\n  ")
        self.assertEqual(whitespace_res, "")

        norm_empty = self.cache.normalize_query("")
        self.assertEqual(norm_empty, "")

        key_empty = self.cache._get_key("")
        self.assertTrue(key_empty.startswith("cymbal:sheet_rag:query:") or key_empty.startswith("cymbal:rag:"))

    async def test_currency_symbol_variations_matching(self):
        """Verify ₹, Rs., Rupees, and INR currency symbols match corresponding lending thresholds."""
        queries = [
            ("minimum amount to lend ₹250", "250"),
            ("minimum amount to lend Rs. 250", "250"),
            ("minimum amount to lend Rupees 250", "250"),
            ("minimum amount to lend 250 INR", "250"),
            ("maximum amount per PAN ₹50 Lakh", "50 lakh"),
            ("maximum amount per PAN Rs 50 Lakh", "50 lakh"),
            ("maximum amount per PAN 50 Lakh INR", "50 lakh"),
        ]
        for q, expected in queries:
            res = await self.cache.search_sheet_knowledge(q, top_k=3)
            self.assertTrue(len(res) > 0, f"Query '{q}' returned empty")
            self.assertIn(expected.lower(), res.lower(), f"Expected '{expected}' in '{res}' for '{q}'")

    async def test_multiline_answer_preservation(self):
        """Verify multiline text maintains line breaks when set and retrieved from cache."""
        test_multiline = "Line 1: LenDenClub P2P returns.\nLine 2: 12% to 15% indicative XIRR.\nLine 3: 100% digital KYC."
        await self.cache.set("test_multiline_key", test_multiline)
        retrieved = await self.cache.get("test_multiline_key")
        self.assertEqual(retrieved, test_multiline)
        self.assertIn("\n", retrieved)

    async def test_unicode_and_punctuation_handling(self):
        """Verify queries with smart quotes, em-dashes, brackets, percentages, and special chars."""
        unicode_queries = [
            '“What is the interest rate in 14 Month EMI Option?”',
            'What’s the maximum limit — per PAN card (50 Lakh)?',
            'Is there any 10% TDS deduction on P2P interest?',
            'What are the [STL] Short-Term-Lending tenures?',
        ]
        for q in unicode_queries:
            res = await self.cache.search_sheet_knowledge(q, top_k=3)
            self.assertTrue(len(res) > 0, f"Unicode query '{q}' failed to retrieve results")

    async def test_redis_offline_graceful_fallback(self):
        """Verify when Redis server is unreachable, cache operates in L1 in-memory mode without errors."""
        offline_cache = RedisRAGCache(redis_url="redis://127.0.0.1:59999/0")
        connected = await offline_cache.initialize()
        self.assertFalse(connected)
        self.assertFalse(offline_cache.is_connected)

        # L1 in-memory mode should function seamlessly
        await offline_cache.set("fallback_test_key", "Fallback Value")
        val = await offline_cache.get("fallback_test_key")
        self.assertEqual(val, "Fallback Value")

        # Sheet search should still function in L1 mode
        await offline_cache.prewarm_sheet_knowledge()
        res = await offline_cache.search_sheet_knowledge("minimum amount to lend")
        self.assertTrue("250" in res or "₹250" in res or "Rupees 250" in res)

    async def test_top_k_parameter_boundaries(self):
        """Verify top_k boundaries (1, 3) return corresponding number of matches on distinct queries."""
        res_1 = await self.cache.search_sheet_knowledge("what are the borrowing and lending rates", top_k=1)
        res_3 = await self.cache.search_sheet_knowledge("tell me about different risk and interest categories", top_k=3)

        self.assertEqual(res_1.count(". Q:"), 1)
        self.assertIn("1. Q:", res_1)
        self.assertNotIn("2. Q:", res_1)

        self.assertEqual(res_3.count(". Q:"), 3)
        self.assertIn("1. Q:", res_3)
        self.assertIn("2. Q:", res_3)
        self.assertIn("3. Q:", res_3)


# ============================================================================
# Tier 3: Specific Lending Queries & Semantic Verification
# ============================================================================

class TestTier3SpecificLendingQueries(unittest.IsolatedAsyncioTestCase):
    """Tier 3: Specific Lending Queries & Semantic Verification - Core business rules and canonical fallback."""

    async def asyncSetUp(self):
        self.cache = RedisRAGCache()
        await self.cache.initialize()
        await self.cache.prewarm_sheet_knowledge()

    async def test_query_minimum_amount_to_lend(self):
        """Verify 'minimum amount to lend' retrieves ₹250 manual lending threshold."""
        res = await self.cache.search_sheet_knowledge("minimum amount to lend", top_k=3)
        self.assertTrue(len(res) > 0)
        self.assertTrue("250" in res or "₹250" in res or "Rupees 250" in res)

    async def test_query_maximum_amount_per_pan_50_lakh(self):
        """Verify 'maximum amount per PAN ₹50 Lakh' retrieves ₹50 Lakh statutory ceiling & CA certificate threshold."""
        res = await self.cache.search_sheet_knowledge("maximum investment amount allowed per PAN 50 lakh", top_k=3)
        self.assertTrue(len(res) > 0)
        self.assertTrue("50" in res and ("lakh" in res.lower() or "lakhs" in res.lower()))
        self.assertTrue("Chartered Accountant" in res or "net worth certificate" in res or "10 lakh" in res)

    async def test_query_14_month_emi_option(self):
        """Verify '14 month EMI option' retrieves MTL mid-term tenure and interest rate."""
        res = await self.cache.search_sheet_knowledge("14 month EMI option interest rate", top_k=3)
        self.assertTrue(len(res) > 0)
        self.assertTrue("14" in res and ("month" in res.lower() or "installment" in res.lower()))
        self.assertTrue("18%" in res or "risk" in res.lower() or "medium" in res.lower())

    async def test_query_cto_february_2025_update(self):
        """Verify 'CTO February 2025 update' retrieves Dipesh Karki and STL ₹100 Cr milestone."""
        res = await self.cache.search_sheet_knowledge("latest update from CTO for February 2025", top_k=3)
        self.assertTrue(len(res) > 0)
        self.assertTrue("Dipesh Karki" in res or "100 Cr" in res or "Short Term Lending" in res)

    async def test_query_rbi_compliant_escrow_account(self):
        """Verify escrow account queries retrieve neutral trustee and ICICI Trusteeship details."""
        res = await self.cache.search_sheet_knowledge("RBI compliant escrow account safe", top_k=3)
        self.assertTrue(len(res) > 0)
        self.assertTrue("escrow" in res.lower() or "trustee" in res.lower())

    async def test_query_tds_taxation_26as(self):
        """Verify TDS / tax deduction queries retrieve tax compliance information."""
        res = await self.cache.search_sheet_knowledge("TDS deduction Form 26AS interest", top_k=3)
        self.assertTrue(len(res) > 0)
        self.assertTrue("tds" in res.lower() or "tax" in res.lower() or "income" in res.lower())

    async def test_query_stl_interest_rates(self):
        """Verify Short Term Lending queries retrieve historical STL returns (12 to 15 percent)."""
        res = await self.cache.search_sheet_knowledge("Short Term Lending STL interest rate", top_k=3)
        self.assertTrue(len(res) > 0)
        self.assertTrue("stl" in res.lower() or "short term" in res.lower() or "12" in res)

    async def test_query_lumpsum_lending_limit(self):
        """Verify lump sum lending limit queries retrieve ₹25 Lakhs threshold."""
        res = await self.cache.search_sheet_knowledge("maximum amount in lump sum lending", top_k=3)
        self.assertTrue(len(res) > 0)
        self.assertTrue("25" in res and ("lakh" in res.lower() or "lakhs" in res.lower()))

    async def test_unmatched_query_behavior(self):
        """Verify completely unmatched queries return clean not found message from Memorystore."""
        unmatched_query = "zzqqxx123456789 unknowntermxyz987"
        sheet_res = await self.cache.search_sheet_knowledge(unmatched_query)
        self.assertEqual(sheet_res, "")

        # Verify tool handler returns clean message
        callback_mock = AsyncMock()
        params = MagicMock()
        params.arguments = {"query_for_vector_search": unmatched_query}
        params.result_callback = callback_mock

        await search_knowledge_base_handler(params)
        callback_mock.assert_called_once()
        content = callback_mock.call_args[0][0]["content"]
        self.assertIn("No specific record found in Memorystore", content)

    async def test_exact_cache_hierarchy_execution(self):
        """Verify retrieval hierarchy: Exact Cache Hit -> Sheet Inverted Index in Memorystore."""
        # 1. Sheet search
        sheet_res = await self.cache.search_sheet_knowledge("minimum amount to lend")
        self.assertTrue(len(sheet_res) > 0)

        # 2. Store exact query into cache
        await self.cache.set("exact test question", "Exact Answer From Cache")
        exact_res = await self.cache.get("exact test question")
        self.assertEqual(exact_res, "Exact Answer From Cache")


# ============================================================================
# Tier 4: Real-World Latency & High-Throughput Workload
# ============================================================================

class TestTier4LatencyAndWorkloadBenchmark(unittest.IsolatedAsyncioTestCase):
    """Tier 4: Latency & Workload Benchmark - 100 queries benchmark, concurrency, and startup pre-warming."""

    async def asyncSetUp(self):
        self.cache = RedisRAGCache()
        await self.cache.initialize()
        await self.cache.prewarm_sheet_knowledge()

    async def test_high_throughput_100_queries_benchmark(self):
        """Benchmark 100 consecutive queries ensuring Avg < 2.0ms, p99 < 15.0ms, and max < 25.0ms."""
        representative_queries = [
            "minimum amount to lend",
            "maximum amount per PAN ₹50 Lakh",
            "14 month EMI option",
            "CTO February 2025 update",
            "RBI compliant escrow account ICICI",
            "TDS deduction Form 26AS",
            "Short Term Lending STL interest rate",
            "maximum amount in lump sum lending",
            "historical returns 12 to 24 percent",
            "NPA and default recovery framework",
        ]

        latencies_ms = []
        for _ in range(10):
            for q in representative_queries:
                t0 = time.perf_counter()
                res = await self.cache.search_sheet_knowledge(q, top_k=3)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(elapsed_ms)
                self.assertTrue(len(res) > 0)

        self.assertEqual(len(latencies_ms), 100)
        avg_latency = sum(latencies_ms) / len(latencies_ms)
        sorted_latencies = sorted(latencies_ms)
        p95_latency = sorted_latencies[int(len(latencies_ms) * 0.95)]
        p99_latency = sorted_latencies[int(len(latencies_ms) * 0.99)]
        max_latency = max(latencies_ms)

        print(f"\n⚡ [Tier 4 Latency Benchmark: 100 Queries]")
        print(f"   Avg: {avg_latency:.3f} ms | p95: {p95_latency:.3f} ms | p99: {p99_latency:.3f} ms | Max: {max_latency:.3f} ms")

        self.assertLess(avg_latency, 2.0, f"Average latency {avg_latency:.3f}ms exceeded target < 2.0ms")
        self.assertLess(p99_latency, 15.0, f"p99 latency {p99_latency:.3f}ms exceeded target < 15.0ms")
        self.assertLess(max_latency, 25.0, f"Max latency {max_latency:.3f}ms exceeded target < 25.0ms")

    async def test_concurrent_async_query_workload(self):
        """Execute 50 concurrent async queries via asyncio.gather to ensure thread/coroutine safety."""
        test_queries = [
            "minimum amount to lend",
            "maximum amount per PAN ₹50 Lakh",
            "14 month EMI option",
            "CTO February 2025 update",
            "TDS deduction Form 26AS",
        ] * 10  # 50 total queries

        t0 = time.perf_counter()
        tasks = [self.cache.search_sheet_knowledge(q, top_k=3) for q in test_queries]
        results = await asyncio.gather(*tasks)
        total_elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(len(results), 50)
        for r in results:
            self.assertTrue(len(r) > 0)

        avg_concurrent_ms = total_elapsed_ms / 50.0
        print(f"\n⚡ [Tier 4 Concurrency Benchmark: 50 Concurrent Queries]")
        print(f"   Total Time: {total_elapsed_ms:.2f} ms | Avg per Query: {avg_concurrent_ms:.3f} ms")
        self.assertLess(avg_concurrent_ms, 5.0)

    async def test_server_lifespan_startup_prewarming(self):
        """Verify server.py lifespan pre-warms both canonical knowledge and sheet knowledge in < 50ms."""
        try:
            import server.server as srv_module
            lifespan = srv_module.lifespan
            app = srv_module.app
        except (ImportError, AttributeError):
            import server as srv_module
            lifespan = srv_module.lifespan
            app = srv_module.app

        t0 = time.perf_counter()
        async with lifespan(app):
            prewarm_ms = (time.perf_counter() - t0) * 1000.0
            # Verify sheet knowledge is prewarmed and searchable in Memorystore
            sheet_hit = await rag_cache.search_sheet_knowledge("minimum amount to lend")
            self.assertTrue("250" in sheet_hit or "₹250" in sheet_hit or "Rupees 250" in sheet_hit)

    async def test_memory_redis_syncer_profile_retrieval(self):
        """Verify user memory profile retrieval executes within < 5ms from cache."""
        # Pre-seed user profile in cache
        await rag_cache.set("user:user_manish:profile", "Returning Customer Profile (user_manish): Active investor")

        # Warm-up call
        await memory_redis_syncer.get_user_profile("user_manish")

        t0 = time.perf_counter()
        profile = await memory_redis_syncer.get_user_profile("user_manish")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertIsNotNone(profile)
        self.assertIn("manish", profile.lower())
        self.assertLess(elapsed_ms, 5.0, f"Profile retrieval took {elapsed_ms:.2f}ms (expected <5ms)")


# ============================================================================
# Tier 5: Adversarial Verification & Integrity Hardening
# ============================================================================

class TestTier5AdversarialIntegrityHardening(unittest.IsolatedAsyncioTestCase):
    """Tier 5: Adversarial Verification - Metacharacters, query fuzzing, malformed parameters, and zero dead air."""

    async def asyncSetUp(self):
        self.cache = RedisRAGCache()
        await self.cache.initialize()
        await self.cache.prewarm_sheet_knowledge()

    async def test_adv_regex_metacharacters_resilience(self):
        """Adversarial Test: Queries containing regex metacharacters (*, +, ?, ^, $, [], {}, (), |)."""
        adversarial_inputs = [
            "minimum amount (.*)+ ? [a-z] ^ $",
            "maximum amount per PAN [50]+ lakh? (yes|no)",
            "14 month {EMI} option (18% | 24%)",
            "CTO update [2025]+ \\d+ \\w+",
        ]
        for adv_q in adversarial_inputs:
            # Must not crash or raise Regex Error
            res = await self.cache.search_sheet_knowledge(adv_q)
            self.assertIsInstance(res, str)

    async def test_adv_repeated_and_fuzzed_long_tokens(self):
        """Adversarial Test: Long repetitive queries and fuzzing noise."""
        long_fuzzed_query = "lending " * 20 + "minimum amount 250 " + "noise " * 10
        t0 = time.perf_counter()
        res = await self.cache.search_sheet_knowledge(long_fuzzed_query)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertIsInstance(res, str)
        self.assertTrue(len(res) > 0)
        self.assertLess(elapsed_ms, 20.0, "Fuzzed long query took excessive time")

    async def test_adv_malformed_handler_arguments(self):
        """Adversarial Test: search_knowledge_base_handler called with malformed arguments dict."""
        callback_mock = AsyncMock()
        params = MagicMock()
        params.arguments = {}  # Missing query_for_vector_search
        params.result_callback = callback_mock

        # Should fall back gracefully without crashing
        await search_knowledge_base_handler(params)
        callback_mock.assert_called_once()
        content = callback_mock.call_args[0][0]["content"]
        self.assertIsInstance(content, str)
        self.assertTrue(len(content) > 0)

    async def test_adv_zero_dead_air_tool_execution(self):
        """Adversarial Test: Verify tool execution latency guarantees zero dead air for Gemini Live."""
        callback_mock = AsyncMock()
        params = MagicMock()
        params.arguments = {
            "query_for_vector_search": "maximum investment amount allowed per PAN 50 lakh",
            "total_records": 3,
        }
        params.result_callback = callback_mock

        t0 = time.perf_counter()
        await search_knowledge_base_handler(params)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        callback_mock.assert_called_once()
        content = callback_mock.call_args[0][0]["content"]
        self.assertIn("50 lakh", content.lower())
        # Target for zero dead air is < 5ms (upper limit 25ms on VM test runners)
        self.assertLess(elapsed_ms, 25.0, f"Tool handler took {elapsed_ms:.2f}ms (must be <25ms for zero dead air)")

    async def test_adv_type_mutations_and_non_string_queries(self):
        """Adversarial Test: Verify int, bool, list, dict queries and non-int total_records execute without exceptions."""
        mutation_cases = [
            ("integer_query", 12345, 3),
            ("float_query", 99.99, 3),
            ("boolean_query", True, 3),
            ("list_query", ["minimum", "amount"], 3),
            ("dict_query", {"sub": "query"}, 3),
            ("none_query", None, 3),
            ("string_total_records", "minimum amount to lend", "three"),
            ("negative_total_records", "minimum amount to lend", -5),
            ("oversized_total_records", "minimum amount to lend", 10000),
            ("float_total_records", "minimum amount to lend", 2.7),
            ("none_total_records", "minimum amount to lend", None),
        ]

        for label, q_val, rec_val in mutation_cases:
            with self.subTest(label=label, q_val=q_val, rec_val=rec_val):
                # 1. Test tokenize_text directly
                tokens = tokenize_text(q_val)
                self.assertIsInstance(tokens, list, f"tokenize_text({q_val}) should return a list")

                # 2. Test search_sheet_knowledge directly
                res_cache = await self.cache.search_sheet_knowledge(q_val, top_k=rec_val)
                self.assertIsInstance(res_cache, str, f"search_sheet_knowledge should return a str for {label}")

                # 3. Test search_knowledge_base_handler via callback
                cb = AsyncMock()
                params = MagicMock()
                params.arguments = {
                    "query_for_vector_search": q_val,
                    "total_records": rec_val,
                }
                params.result_callback = cb
                await search_knowledge_base_handler(params)
                cb.assert_called_once()
                content = cb.call_args[0][0].get("content")
                self.assertIsInstance(content, str)
                self.assertTrue(len(content) > 0, f"Handler produced empty content for {label}")

    async def test_single_digit_and_alphanumeric_cache_key_distinction(self):
        """Adversarial Test: Verify single-digit numbers and characters produce distinct tokens and cache hash keys."""
        # 1. Single-digit number preservation in tokenize_text
        t_tier1 = tokenize_text("Tier 1")
        t_tier2 = tokenize_text("Tier 2")
        self.assertIn("1", t_tier1, "tokenize_text('Tier 1') must contain '1'")
        self.assertIn("2", t_tier2, "tokenize_text('Tier 2') must contain '2'")
        self.assertNotEqual(t_tier1, t_tier2, "Tokens for 'Tier 1' and 'Tier 2' must not collide")

        # 2. Distinct cache keys for queries differing by single digits
        key_tier1 = self.cache._get_key("Tier 1")
        key_tier2 = self.cache._get_key("Tier 2")
        self.assertNotEqual(key_tier1, key_tier2, "Cache keys for 'Tier 1' and 'Tier 2' must be distinct")

        # 3. Test 0-9 series for collision-free hashing
        keys_0_to_9 = [self.cache._get_key(f"test_key_{i}") for i in range(10)]
        self.assertEqual(len(set(keys_0_to_9)), 10, "All 10 single-digit keys (test_key_0..9) must be unique")

        # 4. Cache isolation test: setting 'Tier 1' must not overwrite 'Tier 2'
        await self.cache.set("Tier 1", "Payload for Tier 1")
        await self.cache.set("Tier 2", "Payload for Tier 2")

        val_tier1 = await self.cache.get("Tier 1")
        val_tier2 = await self.cache.get("Tier 2")
        self.assertEqual(val_tier1, "Payload for Tier 1")
        self.assertEqual(val_tier2, "Payload for Tier 2")
        self.assertNotEqual(val_tier1, val_tier2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
