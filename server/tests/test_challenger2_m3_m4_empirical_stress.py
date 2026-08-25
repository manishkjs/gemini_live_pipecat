"""Challenger 2 Comprehensive Empirical Stress-Testing Harness.

Evaluates:
1. `search_knowledge_base_handler` single-lookup and L1 cache hit response times (< 5ms).
2. `RedisRAGCache.set()` with `RAG_L2_WRITE_ASYNC=true` vs `false` under high throughput and simulated network delay.
3. BM25 candidate scoring loop with pre-normalized keys (`_doc_q_clean`, `_doc_a_clean`) vs on-the-fly cleaning.
4. `get_tools_for_profile` with 'lean', 'full', invalid profiles, and custom dynamic JSON schemas.
5. Server startup verification on port 7860 with `TOOL_PROFILE=lean` and `TOOL_PROFILE=full`.
"""

import asyncio
import gc
import json
import math
import os
import random
import socket
import string
import subprocess
import sys
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from redis_cache import RedisRAGCache, rag_cache, tokenize_text
from rag_function import search_knowledge_base_handler
from pipecat.services.llm_service import FunctionCallParams
from tools.tool_definitions import (
    get_tools_for_profile,
    get_live_streaming_tools,
    get_standard_tools,
    calculate_returns_schema,
    search_knowledge_base_schema,
    retrieve_memory_schema,
    save_memory_schema,
    get_current_time_schema,
    get_onboarding_guide_schema,
)


def calc_stats(latencies_ms: List[float]) -> Dict[str, float]:
    if not latencies_ms:
        return {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "ops_sec": 0.0}
    sorted_l = sorted(latencies_ms)
    n = len(sorted_l)
    
    def pct(p: float) -> float:
        k = (n - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_l[int(k)]
        return sorted_l[int(f)] * (c - k) + sorted_l[int(c)] * (k - f)
    
    total_time_s = sum(sorted_l) / 1000.0
    return {
        "count": n,
        "min": sorted_l[0],
        "max": sorted_l[-1],
        "mean": sum(sorted_l) / n,
        "p50": pct(50),
        "p90": pct(90),
        "p95": pct(95),
        "p99": pct(99),
        "ops_sec": (n / total_time_s) if total_time_s > 0 else float("inf"),
    }


class Challenger2EmpiricalStressSuite(unittest.IsolatedAsyncioTestCase):

    # =========================================================================
    # Scope 1: search_knowledge_base_handler Single-Lookup & L1 Cache Hit Latency
    # =========================================================================
    async def test_01_search_knowledge_base_handler_l1_latency_and_edge_cases(self):
        """Stress-test single-lookup handler and prove L1 cache hits execute in <5ms (sub-ms target)."""
        print("\n--- [SCOPE 1] Stress-Testing search_knowledge_base_handler & L1 Cache ---")
        
        # Prewarm cache
        await rag_cache.prewarm_sheet_knowledge()
        self.assertTrue(rag_cache._is_prewarmed)
        self.assertGreater(len(rag_cache._sheet_records), 0)

        queries = [
            "minimum amount to lend",
            "what is the interest rate for 14 month plan",
            "is cymbal lending rbi registered",
            "maximum investment limit per pan",
            "instant kyc process aadhaar pan",
            "tds deduction on interest earnings",
            "who is the cto of cymbal lending",
            "short term lending 5m returns",
            "can i withdraw money before tenure ends",
            "how is recovery handled for defaulting borrowers",
        ]

        # 1. Warm-up lookup to populate L1 cache
        for q in queries:
            cb = AsyncMock()
            params = MagicMock(spec=FunctionCallParams)
            params.arguments = {"query_for_vector_search": q, "total_records": 3}
            params.result_callback = cb
            await search_knowledge_base_handler(params)
            cb.assert_called_once()

        # 2. Benchmark L1 cache hit response times over 1,000 iterations
        l1_latencies_ms = []
        for _ in range(1000):
            q = random.choice(queries)
            cb = AsyncMock()
            params = MagicMock(spec=FunctionCallParams)
            params.arguments = {"query_for_vector_search": q, "total_records": 3}
            params.result_callback = cb

            t0 = time.perf_counter()
            await search_knowledge_base_handler(params)
            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000.0
            l1_latencies_ms.append(elapsed_ms)
            cb.assert_called_once()

        stats = calc_stats(l1_latencies_ms)
        print(f"L1 Cache Hit Stats (N=1000): Mean={stats['mean']:.4f}ms, P50={stats['p50']:.4f}ms, "
              f"P95={stats['p95']:.4f}ms, P99={stats['p99']:.4f}ms, Max={stats['max']:.4f}ms, "
              f"Throughput={stats['ops_sec']:.0f} ops/sec")

        # Invariant Assertions
        self.assertLess(stats["mean"], 1.0, f"Mean L1 cache hit time must be <1ms, got {stats['mean']:.4f}ms")
        self.assertLess(stats["p95"], 2.0, f"P95 L1 cache hit time must be <2ms, got {stats['p95']:.4f}ms")
        self.assertLess(stats["p99"], 5.0, f"P99 L1 cache hit time must be <5ms, got {stats['p99']:.4f}ms")

        # 3. Edge Case Fuzzing on search_knowledge_base_handler
        edge_cases = [
            ("", "empty string"),
            ("   ", "whitespace only"),
            (None, "None query"),
            (12345, "integer query"),
            (True, "boolean query"),
            ("a" * 5000, "5,000 char long string"),
            ("SELECT * FROM users WHERE 1=1;", "SQL injection probe"),
            ("<script>alert('xss')</script>", "XSS script payload"),
            ("₹ 50,000 lending rate 2026?!@#$", "Special symbols & currency"),
            ("क्रेडिट स्कोर क्या होना चाहिए लोन के लिए?", "Hindi Devanagari query"),
            ("kya mujhe tds certificate milega form 16a?", "Hinglish query"),
        ]

        for val, desc in edge_cases:
            cb = AsyncMock()
            params = MagicMock(spec=FunctionCallParams)
            params.arguments = {"query_for_vector_search": val, "total_records": -10}
            params.result_callback = cb
            t0 = time.perf_counter()
            await search_knowledge_base_handler(params)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            cb.assert_called_once()
            res_content = cb.call_args[0][0].get("content", "")
            self.assertIsInstance(res_content, str, f"Failed on edge case: {desc}")
            self.assertLess(elapsed_ms, 50.0, f"Edge case '{desc}' took too long: {elapsed_ms:.2f}ms")

    # =========================================================================
    # Scope 2: RedisRAGCache.set() RAG_L2_WRITE_ASYNC=true vs false Throughput
    # =========================================================================
    async def test_02_redis_rag_cache_async_vs_sync_writeback(self):
        """Benchmark RedisRAGCache.set() under high throughput with simulated network round-trip."""
        print("\n--- [SCOPE 2] Benchmarking RedisRAGCache.set() (Async vs Sync L2 Writeback) ---")

        SIMULATED_NETWORK_DELAY_S = 0.002  # 2ms Redis network latency simulation
        ITERATIONS = 500

        class MockSlowRedis:
            def __init__(self):
                self.calls = 0
                self.lock = asyncio.Lock()

            async def set(self, key, value, ex=None):
                await asyncio.sleep(SIMULATED_NETWORK_DELAY_S)
                async with self.lock:
                    self.calls += 1
                return True

        # Test Sync Mode (RAG_L2_WRITE_ASYNC = False)
        cache_sync = RedisRAGCache()
        cache_sync.l2_write_async = False
        cache_sync.is_connected = True
        mock_redis_sync = MockSlowRedis()
        cache_sync.redis_client = mock_redis_sync

        sync_latencies_ms = []
        t0_sync = time.perf_counter()
        for i in range(ITERATIONS):
            t_op_0 = time.perf_counter()
            await cache_sync.set(f"query_sync_{i}", f"content_sync_{i}")
            sync_latencies_ms.append((time.perf_counter() - t_op_0) * 1000.0)
        t_sync_total = time.perf_counter() - t0_sync

        sync_stats = calc_stats(sync_latencies_ms)
        print(f"Sync Writeback (N={ITERATIONS}): Total={t_sync_total*1000.0:.2f}ms, "
              f"Mean={sync_stats['mean']:.4f}ms, P50={sync_stats['p50']:.4f}ms, "
              f"P95={sync_stats['p95']:.4f}ms, Throughput={sync_stats['ops_sec']:.1f} ops/sec")

        # Test Async Mode (RAG_L2_WRITE_ASYNC = True)
        cache_async = RedisRAGCache()
        cache_async.l2_write_async = True
        cache_async.is_connected = True
        mock_redis_async = MockSlowRedis()
        cache_async.redis_client = mock_redis_async

        async_latencies_ms = []
        t0_async = time.perf_counter()
        for i in range(ITERATIONS):
            t_op_0 = time.perf_counter()
            await cache_async.set(f"query_async_{i}", f"content_async_{i}")
            async_latencies_ms.append((time.perf_counter() - t_op_0) * 1000.0)
        t_async_total = time.perf_counter() - t0_async

        async_stats = calc_stats(async_latencies_ms)
        print(f"Async Writeback (N={ITERATIONS}): Total={t_async_total*1000.0:.2f}ms, "
              f"Mean={async_stats['mean']:.4f}ms, P50={async_stats['p50']:.4f}ms, "
              f"P95={async_stats['p95']:.4f}ms, Throughput={async_stats['ops_sec']:.1f} ops/sec")

        # Wait for background tasks to complete and verify task cleanup
        await asyncio.sleep(0.1)
        while cache_async._bg_tasks:
            await asyncio.sleep(0.01)

        self.assertEqual(mock_redis_async.calls, ITERATIONS)
        self.assertEqual(len(cache_async._bg_tasks), 0, "All background tasks must be cleanly discarded upon completion.")

        # Speedup Verification
        speedup = sync_stats["mean"] / max(0.0001, async_stats["mean"])
        print(f"Async Writeback Speedup Factor: {speedup:.1f}x faster on the caller thread")
        self.assertGreater(speedup, 5.0, f"Async writeback should be at least 5x faster than sync with network latency. Got {speedup:.1f}x")
        self.assertLess(async_stats["mean"], 1.0, f"Async writeback mean latency should be <1.0ms (sub-ms), got {async_stats['mean']:.4f}ms")

        # Test Error Resilience when Async Redis fails
        class FailingRedis:
            async def set(self, key, value, ex=None):
                await asyncio.sleep(0.001)
                raise ConnectionResetError("Simulated Redis network drop")

        cache_failing = RedisRAGCache()
        cache_failing.l2_write_async = True
        cache_failing.is_connected = True
        cache_failing.redis_client = FailingRedis()

        # Should not raise exception to the caller
        await cache_failing.set("resilience_query", "resilience_content")
        # L1 cache must still be populated immediately
        key = cache_failing._get_key("resilience_query")
        self.assertEqual(cache_failing._l1_cache[key], "resilience_content")
        await asyncio.sleep(0.05)
        self.assertEqual(len(cache_failing._bg_tasks), 0)

    # =========================================================================
    # Scope 3: BM25 Candidate Scoring Loop Pre-Normalization Benchmark
    # =========================================================================
    async def test_03_bm25_candidate_scoring_prenormalization_benchmark(self):
        """Benchmark BM25 candidate scoring loop with pre-normalized keys vs on-the-fly cleaning."""
        print("\n--- [SCOPE 3] Benchmarking BM25 Pre-Normalized Keys vs On-The-Fly Cleaning ---")

        cache = RedisRAGCache()
        await cache.prewarm_sheet_knowledge()
        self.assertTrue(cache._is_prewarmed)
        n_docs = len(cache._sheet_records)
        self.assertGreater(n_docs, 0)
        self.assertEqual(len(cache._doc_q_clean), n_docs)
        self.assertEqual(len(cache._doc_a_clean), n_docs)

        # Generate 1,000 diverse test queries
        seed_vocab = [
            "minimum", "maximum", "lending", "interest", "returns", "rbi", "pan", "aadhaar",
            "kyc", "tds", "tax", "26as", "cto", "dipesh", "karki", "ceo", "lumpsum", "monthly",
            "daily", "edi", "emi", "stl", "mtl", "manual", "recovery", "default", "escrow",
            "icici", "risk", "sip", "tenure", "withdrawal", "lockin", "charges", "fees", "50000",
            "250", "2500000", "5000000", "12%", "15%", "18%", "24%", "40%", "rupees", "inr"
        ]

        fuzz_queries = []
        for _ in range(500):
            token_count = random.randint(1, 6)
            q = " ".join(random.sample(seed_vocab, token_count))
            fuzz_queries.append(q)

        # Include specific conversational queries
        conversational_queries = [
            "mujhe 50000 invest karna hai kitna return milega",
            "minimum deposit kitna hai",
            "kya cymbal rbi registered nbfc p2p hai",
            "what is the maximum tenure available for stl",
            "how to complete bank penny drop verification",
            "what happens if borrower defaults on payments",
            "tds kitna katega 26as me reflect hoga ya nahi",
            "dipesh karki update february 2025",
            "can i invest 25 lakh in lumpsum",
            "manual lending me custom npa filter kaise lagaye",
        ]
        test_queries = fuzz_queries + conversational_queries * 10
        random.shuffle(test_queries)

        k1 = 1.5
        b = 0.75

        # 1. Benchmark On-The-Fly Cleaning Loop
        t0_onthefly = time.perf_counter()
        onthefly_scores = []
        for q_clean in test_queries:
            q_tokens = tokenize_text(q_clean)
            candidate_ids = set()
            for t in q_tokens:
                if t in cache._sheet_token_index:
                    candidate_ids.update(cache._sheet_token_index[t])
            if not candidate_ids:
                continue

            q_raw_clean = q_clean.lower().replace("₹", "rs ").strip()
            q_raw_parts = [part for part in q_raw_clean.split("?") if len(part.strip()) > 6]
            scores = {}
            for doc_id in candidate_ids:
                rec = cache._sheet_records[doc_id]
                dl = cache._doc_lengths[doc_id]
                tf_q = cache._doc_tokens_q[doc_id]
                tf_c = cache._doc_tokens_c[doc_id]
                tf_a = cache._doc_tokens_a[doc_id]

                score = 0.0
                for t in q_tokens:
                    token_idf = cache._idf.get(t, 0.1)
                    tf_weighted = 3.0 * tf_q.get(t, 0) + 1.8 * tf_c.get(t, 0) + 1.0 * tf_a.get(t, 0)
                    if tf_weighted > 0:
                        tf_comp = (tf_weighted * (k1 + 1.0)) / (tf_weighted + k1 * (1.0 - b + b * (dl / cache._avg_dl)))
                        score += token_idf * tf_comp

                # ON-THE-FLY string transforms (legacy bottleneck)
                q_text = rec.get("question", "").lower().replace("₹", "rs ")
                a_text = rec.get("answer", "").lower().replace("₹", "rs ")

                if q_raw_clean and q_raw_clean in q_text:
                    score += 15.0
                elif any(part in q_text for part in q_raw_parts):
                    score += 6.0
                if q_raw_clean and q_raw_clean in a_text:
                    score += 5.0

                scores[doc_id] = score
            onthefly_scores.append(scores)
        t_onthefly_total = (time.perf_counter() - t0_onthefly) * 1000.0

        # 2. Benchmark Pre-Normalized Keys Loop (Optimized M3 implementation)
        t0_prenorm = time.perf_counter()
        prenorm_scores = []
        for q_clean in test_queries:
            q_tokens = tokenize_text(q_clean)
            candidate_ids = set()
            for t in q_tokens:
                if t in cache._sheet_token_index:
                    candidate_ids.update(cache._sheet_token_index[t])
            if not candidate_ids:
                continue

            q_raw_clean = q_clean.lower().replace("₹", "rs ").strip()
            q_raw_parts = [part for part in q_raw_clean.split("?") if len(part.strip()) > 6]
            scores = {}
            for doc_id in candidate_ids:
                dl = cache._doc_lengths[doc_id]
                tf_q = cache._doc_tokens_q[doc_id]
                tf_c = cache._doc_tokens_c[doc_id]
                tf_a = cache._doc_tokens_a[doc_id]

                score = 0.0
                for t in q_tokens:
                    token_idf = cache._idf.get(t, 0.1)
                    tf_weighted = 3.0 * tf_q.get(t, 0) + 1.8 * tf_c.get(t, 0) + 1.0 * tf_a.get(t, 0)
                    if tf_weighted > 0:
                        tf_comp = (tf_weighted * (k1 + 1.0)) / (tf_weighted + k1 * (1.0 - b + b * (dl / cache._avg_dl)))
                        score += token_idf * tf_comp

                # PRE-NORMALIZED arrays (Zero string allocations per candidate doc)
                q_text = cache._doc_q_clean[doc_id]
                a_text = cache._doc_a_clean[doc_id]

                if q_raw_clean and q_raw_clean in q_text:
                    score += 15.0
                elif any(part in q_text for part in q_raw_parts):
                    score += 6.0
                if q_raw_clean and q_raw_clean in a_text:
                    score += 5.0

                scores[doc_id] = score
            prenorm_scores.append(scores)
        t_prenorm_total = (time.perf_counter() - t0_prenorm) * 1000.0

        # Verify exact mathematical and ranking equality across all queries
        self.assertEqual(len(onthefly_scores), len(prenorm_scores))
        for s_onthefly, s_prenorm in zip(onthefly_scores, prenorm_scores):
            self.assertEqual(set(s_onthefly.keys()), set(s_prenorm.keys()))
            for k in s_onthefly:
                self.assertAlmostEqual(s_onthefly[k], s_prenorm[k], places=6)

        speedup_scoring = t_onthefly_total / max(0.001, t_prenorm_total)
        print(f"BM25 Scoring (N={len(test_queries)} queries):\n"
              f"  - On-the-fly cleaning time: {t_onthefly_total:.2f}ms ({t_onthefly_total/len(test_queries)*1000.0:.1f} µs/query)\n"
              f"  - Pre-normalized keys time: {t_prenorm_total:.2f}ms ({t_prenorm_total/len(test_queries)*1000.0:.1f} µs/query)\n"
              f"  - Efficiency Speedup: {speedup_scoring:.2f}x faster scoring loop")

        self.assertLess(t_prenorm_total / len(test_queries), 1.0, "Pre-normalized scoring must take < 1.0ms per query")

    # =========================================================================
    # Scope 4: get_tools_for_profile Stress-Testing & Dynamic JSON Schemas
    # =========================================================================
    def test_04_tool_profiles_fuzzing_and_dynamic_schema_validation(self):
        """Stress-test tool profiles with valid, invalid, boundary cases and dynamic JSON schemas."""
        print("\n--- [SCOPE 4] Stress-Testing get_tools_for_profile & Dynamic Schemas ---")

        # 1. Standard Lean Profile
        lean_tools = get_tools_for_profile("lean")
        self.assertEqual(len(lean_tools), 4)
        lean_names = [t.name for t in lean_tools]
        self.assertEqual(lean_names, ["calculate_returns", "search_knowledge_base", "retrieve_memory", "save_memory"])

        # 2. Standard Full Profile
        full_tools = get_tools_for_profile("full")
        self.assertEqual(len(full_tools), 6)
        full_names = [t.name for t in full_tools]
        self.assertEqual(full_names, [
            "get_current_time",
            "search_knowledge_base",
            "calculate_returns",
            "get_onboarding_guide",
            "retrieve_memory",
            "save_memory",
        ])

        # 3. Profile Case & Whitespace Variations
        for val in ["LEAN", "lean ", "  LEAN  ", "lEaN"]:
            tools = get_tools_for_profile(val)
            self.assertEqual(len(tools), 4, f"Failed for profile variant: '{val}'")

        for val in ["FULL", "full ", "  FULL  ", "FuLl"]:
            tools = get_tools_for_profile(val)
            self.assertEqual(len(tools), 6, f"Failed for profile variant: '{val}'")

        # 4. Invalid Profiles (must gracefully fallback to lean)
        invalid_profiles = ["custom", "ultra", "none", "123", "", "   ", "unknown_mode", None]
        for inv in invalid_profiles:
            tools = get_tools_for_profile(inv)
            self.assertEqual(len(tools), 4, f"Invalid profile '{inv}' did not fallback to lean (4 tools)")

        # 5. Dynamic JSON Schema Fuzzing
        # Valid dynamic schemas
        valid_single_tool = json.dumps([{
            "name": "check_cibil_score",
            "description": "Fetch real-time CIBIL score for PAN card.",
            "properties": {"pan_number": {"type": "string"}},
            "required": ["pan_number"]
        }])
        t_dyn1 = get_tools_for_profile("lean", dynamic_tools_json=valid_single_tool)
        self.assertEqual(len(t_dyn1), 5)
        self.assertEqual(t_dyn1[-1].name, "check_cibil_score")

        # 100 Dynamic Tools Scale Stress Test
        dyn_100_list = [
            {
                "name": f"dynamic_custom_tool_{i}",
                "description": f"Custom auto-generated tool #{i}",
                "properties": {f"param_{i}": {"type": "string"}},
                "required": [f"param_{i}"]
            }
            for i in range(100)
        ]
        dyn_100_json = json.dumps(dyn_100_list)
        t_dyn_100 = get_tools_for_profile("lean", dynamic_tools_json=dyn_100_json)
        self.assertEqual(len(t_dyn_100), 104)
        self.assertEqual(t_dyn_100[-1].name, "dynamic_custom_tool_99")

        # Malformed / Adversarial Dynamic JSON Schemas
        malformed_inputs = [
            ("MALFORMED_JSON", "Plain non-JSON string"),
            ("{unclosed json object", "Unclosed JSON"),
            ("[1, 2, 3]", "List of integers instead of tool objects"),
            ("{\"name\": \"single_dict\"}", "Dict instead of List"),
            ("[null, null]", "List with null elements"),
            ("[{}, {\"no_name\": \"value\"}]", "Dicts missing 'name' field"),
            ("", "Empty string"),
            ("   ", "Whitespace string"),
            (None, "None input"),
        ]

        for m_val, m_desc in malformed_inputs:
            tools_res = get_tools_for_profile("lean", dynamic_tools_json=m_val)
            self.assertEqual(len(tools_res), 4, f"Malformed input '{m_desc}' failed resilience check: {tools_res}")

        print("Tool Profile & Dynamic Schema stress tests passed 100%.")

    # =========================================================================
    # Scope 5: Server Startup Verification on Port 7860 (lean & full)
    # =========================================================================
    def test_05_server_startup_lean_and_full_verification(self):
        """Verify server clean startup and responsiveness on port 7860 in both lean and full modes."""
        print("\n--- [SCOPE 5] Verifying Server Startup on Port 7860 (Lean & Full) ---")
        import urllib.request
        import urllib.error

        test_port = 7860
        python_bin = os.path.join(_SERVER_DIR, "venv", "bin", "python")
        if not os.path.exists(python_bin):
            python_bin = sys.executable

        def wait_for_server(port: int, timeout_s: float = 25.0) -> bool:
            t0 = time.time()
            while time.time() - t0 < timeout_s:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/connect/system-prompt", timeout=1.0) as resp:
                        if resp.status == 200:
                            return True
                except Exception:
                    time.sleep(0.3)
            return False

        for profile in ["lean", "full"]:
            print(f"Testing server startup with TOOL_PROFILE={profile} on port {test_port}...")
            env = os.environ.copy()
            env["PORT"] = str(test_port)
            env["TOOL_PROFILE"] = profile
            env["RAG_L2_WRITE_ASYNC"] = "true"

            proc = subprocess.Popen(
                [python_bin, "server.py"],
                cwd=_SERVER_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            try:
                started = wait_for_server(test_port, timeout_s=25.0)
                self.assertTrue(started, f"Server failed to start within timeout for TOOL_PROFILE={profile}")

                # Test /connect/system-prompt endpoint
                with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/connect/system-prompt") as resp:
                    self.assertEqual(resp.status, 200)
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("system_prompt", data)
                    self.assertGreater(len(data["system_prompt"]), 100)

                # Test /api/logs endpoint
                with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/api/logs") as resp:
                    self.assertEqual(resp.status, 200)
                    logs_data = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("logs", logs_data)

                # Test /connect endpoint POST
                req = urllib.request.Request(
                    f"http://127.0.0.1:{test_port}/connect",
                    data=json.dumps({"model": "gemini-3.5-flash-live-preview"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req) as resp:
                    self.assertEqual(resp.status, 200)
                    conn_data = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("ws_url", conn_data)
                    self.assertIn("/ws", conn_data["ws_url"])

                print(f"Server successfully verified for TOOL_PROFILE={profile} on port {test_port}.")

            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                time.sleep(0.5)


if __name__ == "__main__":
    unittest.main()
