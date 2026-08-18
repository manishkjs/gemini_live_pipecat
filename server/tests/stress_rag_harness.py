"""Empirical Stress Testing, Concurrency Harness, Latency Profiler,
and Adversarial Fuzzing Suite for Dual-Layer Redis RAG Cache and Tool Handler.
"""

import asyncio
import gc
import json
import math
import os
import random
import re
import string
import sys
import time
import tracemalloc
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock, MagicMock

# Add server directory to path
_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from redis_cache import RedisRAGCache, rag_cache, tokenize_text
from rag_function import (
    search_knowledge_base_handler,
)
from pipecat.services.llm_service import FunctionCallParams


def percentile(data: List[float], p: float) -> float:
    """Calculate the p-th percentile (0..100) of a sorted list."""
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    d0 = data[int(f)] * (c - k)
    d1 = data[int(c)] * (k - f)
    return d0 + d1


# ============================================================================
# 1. High Concurrency Load Test
# ============================================================================
async def run_concurrency_load_test(concurrency_levels=(100, 250, 500, 1000)) -> Dict[str, Any]:
    print("\n========================================================")
    print("🚀 RUNNING TEST 1: HIGH CONCURRENCY LOAD TESTING")
    print("========================================================")
    
    test_queries = [
        "minimum amount to lend",
        "maximum amount per PAN ₹50 Lakh",
        "14 month EMI option interest rate",
        "CTO February 2025 update Dipesh Karki",
        "RBI compliant escrow account ICICI Trusteeship",
        "TDS deduction Form 26AS interest",
        "Short Term Lending STL interest rate 12 to 15 percent",
        "maximum amount in lump sum lending ₹25 Lakhs",
        "historical recovery rate 96.18 percent",
        "instant 3 step KYC PAN Aadhaar",
    ]

    cache = RedisRAGCache()
    await cache.prewarm_sheet_knowledge()

    results = {}

    for count in concurrency_levels:
        queries = [random.choice(test_queries) for _ in range(count)]
        exceptions = []
        latencies_ms = []

        async def worker(q: str):
            t0 = time.perf_counter()
            try:
                res = await cache.search_sheet_knowledge(q, top_k=3)
                elapsed = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(elapsed)
                if not res:
                    exceptions.append(f"Empty result for {q}")
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(elapsed)
                exceptions.append(str(e))

        t_start = time.perf_counter()
        tasks = [worker(q) for q in queries]
        await asyncio.gather(*tasks)
        total_time_ms = (time.perf_counter() - t_start) * 1000.0

        latencies_sorted = sorted(latencies_ms)
        min_lat = min(latencies_sorted) if latencies_sorted else 0.0
        max_lat = max(latencies_sorted) if latencies_sorted else 0.0
        mean_lat = sum(latencies_sorted) / len(latencies_sorted) if latencies_sorted else 0.0
        p50_lat = percentile(latencies_sorted, 50)
        p95_lat = percentile(latencies_sorted, 95)
        p99_lat = percentile(latencies_sorted, 99)
        rps = (count / (total_time_ms / 1000.0)) if total_time_ms > 0 else 0.0

        print(f"\n[Concurrency = {count:4d} simultaneous async queries]")
        print(f"  ├─ Total Time: {total_time_ms:7.2f} ms | Throughput: {rps:9.1f} RPS")
        print(f"  ├─ Latency (Min / Mean / Max): {min_lat:.3f} ms / {mean_lat:.3f} ms / {max_lat:.3f} ms")
        print(f"  ├─ Percentiles (p50 / p95 / p99): {p50_lat:.3f} ms / {p95_lat:.3f} ms / {p99_lat:.3f} ms")
        print(f"  └─ Errors / Unhandled Exceptions: {len(exceptions)}")

        results[str(count)] = {
            "count": count,
            "total_time_ms": total_time_ms,
            "rps": rps,
            "min_ms": min_lat,
            "mean_ms": mean_lat,
            "max_ms": max_lat,
            "p50_ms": p50_lat,
            "p95_ms": p95_lat,
            "p99_ms": p99_lat,
            "error_count": len(exceptions),
            "exceptions": exceptions,
        }

    return results


# ============================================================================
# 2. Latency Distribution Analysis (Cold & Warm Paths, Tool Handler E2E)
# ============================================================================
async def run_latency_distribution_test(iterations: int = 1000) -> Dict[str, Any]:
    print("\n========================================================")
    print("⏱️ RUNNING TEST 2: LATENCY DISTRIBUTION ANALYSIS (1,000 QUERIES)")
    print("========================================================")

    # 100 diverse query templates representing typical real user inputs
    base_queries = [
        "minimum amount to lend",
        "maximum amount per PAN ₹50 Lakh",
        "14 month EMI option",
        "CTO February 2025 update",
        "RBI compliant escrow account",
        "TDS deduction Form 26AS",
        "Short Term Lending STL interest rate",
        "maximum amount in lump sum lending",
        "historical returns 12 to 24 percent",
        "NPA and default recovery framework",
        "KYC process for NRI investors",
        "ICICI trusteeship safe platform bankruptcy",
        "penny drop verification process",
        "monthly EMI payout vs daily payout",
        "pre-closure penalty on lending",
        "auto-invest rules and criteria",
        "how are borrower credit scores checked",
        "what happens if borrower defaults",
        "STL tenure 2 months 3 months",
        "MTL tenure 6 months 12 months",
    ]

    cache = RedisRAGCache()
    await cache.prewarm_sheet_knowledge()

    # Part A: Cold Searches (Cache Bypassed / Unique Queries)
    cold_latencies: List[float] = []
    for i in range(iterations):
        # Generate unique variations to avoid cache
        rand_suffix = f" {i} variation {random.randint(1, 100000)}"
        q = random.choice(base_queries) + rand_suffix
        t0 = time.perf_counter()
        res = await cache.search_sheet_knowledge(q, top_k=3)
        elapsed = (time.perf_counter() - t0) * 1000.0
        cold_latencies.append(elapsed)

    cold_sorted = sorted(cold_latencies)

    # Part B: Warm Searches (Exact Cache Hits)
    warm_latencies: List[float] = []
    # Pre-populate exact cache
    for q in base_queries:
        await cache.search_sheet_knowledge(q, top_k=3)

    for _ in range(iterations):
        q = random.choice(base_queries)
        t0 = time.perf_counter()
        res = await cache.search_sheet_knowledge(q, top_k=3)
        elapsed = (time.perf_counter() - t0) * 1000.0
        warm_latencies.append(elapsed)

    warm_sorted = sorted(warm_latencies)

    # Part C: search_knowledge_base_handler End-to-End Latency
    handler_latencies: List[float] = []
    for i in range(iterations):
        q = random.choice(base_queries)
        callback = AsyncMock()
        params = MagicMock()
        params.arguments = {"query_for_vector_search": q, "total_records": 3}
        params.result_callback = callback

        t0 = time.perf_counter()
        await search_knowledge_base_handler(params)
        elapsed = (time.perf_counter() - t0) * 1000.0
        handler_latencies.append(elapsed)

    handler_sorted = sorted(handler_latencies)

    def stats(data: List[float]) -> Dict[str, float]:
        return {
            "min": min(data),
            "max": max(data),
            "mean": sum(data) / len(data),
            "p50": percentile(data, 50),
            "p90": percentile(data, 90),
            "p95": percentile(data, 95),
            "p99": percentile(data, 99),
            "p99_9": percentile(data, 99.9),
        }

    cold_stats = stats(cold_sorted)
    warm_stats = stats(warm_sorted)
    handler_stats = stats(handler_sorted)

    print("\n[A. Cold Search Path (BM25 Index Evaluation on Unique Queries)]")
    print(f"  ├─ Min: {cold_stats['min']:.4f} ms | Mean: {cold_stats['mean']:.4f} ms | Max: {cold_stats['max']:.4f} ms")
    print(f"  └─ p50: {cold_stats['p50']:.4f} ms | p95: {cold_stats['p95']:.4f} ms | p99: {cold_stats['p99']:.4f} ms | p99.9: {cold_stats['p99_9']:.4f} ms")

    print("\n[B. Warm Cache Path (Exact L1 Query Hash Hits)]")
    print(f"  ├─ Min: {warm_stats['min']:.4f} ms | Mean: {warm_stats['mean']:.4f} ms | Max: {warm_stats['max']:.4f} ms")
    print(f"  └─ p50: {warm_stats['p50']:.4f} ms | p95: {warm_stats['p95']:.4f} ms | p99: {warm_stats['p99']:.4f} ms | p99.9: {warm_stats['p99_9']:.4f} ms")

    print("\n[C. Tool Handler E2E Path (search_knowledge_base_handler)]")
    print(f"  ├─ Min: {handler_stats['min']:.4f} ms | Mean: {handler_stats['mean']:.4f} ms | Max: {handler_stats['max']:.4f} ms")
    print(f"  └─ p50: {handler_stats['p50']:.4f} ms | p95: {handler_stats['p95']:.4f} ms | p99: {handler_stats['p99']:.4f} ms | p99.9: {handler_stats['p99_9']:.4f} ms")

    return {
        "cold": cold_stats,
        "warm": warm_stats,
        "handler": handler_stats,
    }


# ============================================================================
# 3. Extreme Input Fuzzing (Adversarial, Unicode, Null Bytes, ReDoS, Long Strings)
# ============================================================================
async def run_input_fuzzing_test() -> Dict[str, Any]:
    print("\n========================================================")
    print("💥 RUNNING TEST 3: EXTREME ADVERSARIAL INPUT FUZZING")
    print("========================================================")

    cache = RedisRAGCache()
    await cache.prewarm_sheet_knowledge()

    fuzz_vectors: List[Tuple[str, Any]] = [
        ("Null Byte Prefix", "\x00minimum amount to lend"),
        ("Embedded Null Bytes", "maximum\x00amount\x00per\x00PAN\x0050\x00lakh"),
        ("All Null Bytes", "\x00" * 100),
        ("Null Byte Suffix", "14 month EMI\x00"),
        ("Single Emoji", "💰"),
        ("Multiple Emojis", "💰🚀📈🤖🔥🏦💸"),
        ("Emoji Mixed Query", "What is the minimum 💰 lending amount ₹250? 🔥"),
        ("Unicode RTL Overrides", "\u202e\u200f\u202d\u200e what is lending limit \u202c"),
        ("Zero-Width Joiners & Spaces", "m\u200bi\u200cn\u200di\u200dm\u200bu\u200bm amount"),
        ("Combining Diacritical Marks", "ḿíńíḿúḿ áḿóúńt́"),
        ("Non-BMP Plane Characters", "𝕸𝖎𝖓𝖎𝖒𝖚𝖒 𝖆𝖒𝖔𝖚𝖓𝖙 𝖙𝖔 𝖑𝖊𝖓𝖉 𝟚𝟝𝟘"),
        ("CJK Characters", "最低融资金额 ₹250 借出"),
        ("Arabic Characters", "الحد الأدنى لمبلغ الإقراض"),
        ("Devanagari Script", "कम से कम कितना पैसा लेंड कर सकते हैं? ₹250"),
        ("1K Character String", "lending " * 125),
        ("10K Character String", "minimum amount to lend 250 " * 370),
        ("50K Character String", "a" * 50000),
        ("100K Massive String", "query_text " * 9000),
        ("ReDoS Catastrophic Backtracking Pattern 1", "((a+)+)+$"),
        ("ReDoS Catastrophic Backtracking Pattern 2", "a" * 50 + "!"),
        ("Regex Metacharacters Spectrum", "^$.*+?()[]{}|\\/^$()[]{}|\\/"),
        ("Unbalanced Braces & Brackets", "[[[{{{(())}}]]][[[((("),
        ("HTML / Script Injection", "<script>alert('xss')</script><b>bold</b>"),
        ("SQL Injection Vector 1", "' OR '1'='1'; DROP TABLE users; --"),
        ("SQL Injection Vector 2", "UNION SELECT null, null, username, password FROM users --"),
        ("Format String Injection", "%s%s%s%s%s%n%d%x"),
        ("JNDI / Log4j Injection String", "${jndi:ldap://127.0.0.1:1389/Exploit}"),
        ("Raw JSON String", json.dumps({"query": "minimum amount", "limit": 50})),
        ("Nested JSON String", json.dumps({"a": {"b": {"c": {"d": [1, 2, 3]}}}})),
        ("Windows Path Traversal", "..\\..\\..\\..\\windows\\system32\\cmd.exe"),
        ("Unix Path Traversal", "../../../../../../etc/passwd"),
    ]

    # Generate 500 random garbage strings
    for i in range(500):
        length = random.choice([5, 20, 100, 500, 2000])
        chars = string.ascii_letters + string.digits + string.punctuation + " \t\n\r" + "₹$€£¥" + "😀😁😂🤣"
        rand_str = "".join(random.choice(chars) for _ in range(length))
        fuzz_vectors.append((f"Random Garbage #{i+1} (len={length})", rand_str))

    fuzz_failures: List[Dict[str, Any]] = []
    total_fuzz_count = len(fuzz_vectors)

    t0 = time.perf_counter()
    for label, vector in fuzz_vectors:
        try:
            # 1. Test tokenize_text
            tokens = tokenize_text(str(vector))
            self_check = isinstance(tokens, list)
            if not self_check:
                fuzz_failures.append({"label": label, "error": "tokenize_text did not return list"})

            # 2. Test search_sheet_knowledge
            res = await cache.search_sheet_knowledge(str(vector), top_k=3)
            if not isinstance(res, str):
                fuzz_failures.append({"label": label, "error": "search_sheet_knowledge did not return str"})

            # 3. Test get & set
            await cache.set(str(vector), f"fuzzed_response_for_{label}")
            retrieved = await cache.get(str(vector))
            if retrieved != f"fuzzed_response_for_{label}":
                fuzz_failures.append({"label": label, "error": f"Cache get/set mismatch: got {retrieved}"})

            # 4. Test search_knowledge_base_handler
            callback = AsyncMock()
            params = MagicMock()
            params.arguments = {"query_for_vector_search": vector, "total_records": 3}
            params.result_callback = callback
            await search_knowledge_base_handler(params)
            callback.assert_called_once()
            cb_content = callback.call_args[0][0].get("content")
            if not isinstance(cb_content, str) or len(cb_content) == 0:
                fuzz_failures.append({"label": label, "error": "Handler did not return non-empty content"})

        except Exception as e:
            fuzz_failures.append({"label": label, "vector": str(vector)[:60], "error": f"Unhandled Exception: {type(e).__name__}: {e}"})

    total_fuzz_time_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n[Fuzzing Results Summary]")
    print(f"  ├─ Total Fuzz Vectors Executed: {total_fuzz_count}")
    print(f"  ├─ Total Execution Time: {total_fuzz_time_ms:.2f} ms (Avg: {total_fuzz_time_ms / total_fuzz_count:.3f} ms/vector)")
    print(f"  ├─ Unhandled Exceptions / Failures: {len(fuzz_failures)}")
    if fuzz_failures:
        print("  └─ ⚠️ Detected Failures:")
        for f in fuzz_failures[:10]:
            print(f"     - {f['label']}: {f['error']}")
    else:
        print("  └─ ✅ ZERO unhandled exceptions across all adversarial fuzz vectors!")

    # Test Type Mutations for FunctionCallParams
    type_mutations = [
        ("None Arguments", None),
        ("Empty Dict Arguments", {}),
        ("Integer Query", {"query_for_vector_search": 12345}),
        ("Float Query", {"query_for_vector_search": 99.99}),
        ("Boolean Query", {"query_for_vector_search": True}),
        ("List Query", {"query_for_vector_search": ["minimum", "amount"]}),
        ("Dict Query", {"query_for_vector_search": {"sub": "query"}}),
        ("Negative total_records", {"query_for_vector_search": "minimum amount", "total_records": -5}),
        ("Huge total_records", {"query_for_vector_search": "minimum amount", "total_records": 10000}),
        ("String total_records", {"query_for_vector_search": "minimum amount", "total_records": "three"}),
    ]

    type_failures = []
    for label, args in type_mutations:
        try:
            callback = AsyncMock()
            params = MagicMock()
            params.arguments = args
            params.result_callback = callback
            await search_knowledge_base_handler(params)
            callback.assert_called_once()
            content = callback.call_args[0][0].get("content")
            if not isinstance(content, str) or len(content) == 0:
                type_failures.append({"label": label, "error": "Handler failed to produce content"})
        except Exception as e:
            type_failures.append({"label": label, "error": f"Unhandled Exception: {type(e).__name__}: {e}"})

    print(f"\n[Type Mutation Results Summary]")
    print(f"  ├─ Type Mutations Tested: {len(type_mutations)}")
    print(f"  └─ Failures: {len(type_failures)}")

    return {
        "total_fuzzed": total_fuzz_count + len(type_mutations),
        "failures": fuzz_failures + type_failures,
        "total_time_ms": total_fuzz_time_ms,
    }


# ============================================================================
# 4. Cache Invalidation, Memory Leak & Resource Profiling
# ============================================================================
async def run_memory_and_invalidation_test(iterations: int = 10000) -> Dict[str, Any]:
    print("\n========================================================")
    print("🧠 RUNNING TEST 4: MEMORY LEAK & CACHE INVALIDATION CHECK")
    print("========================================================")

    gc.collect()
    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()

    cache = RedisRAGCache()
    await cache.prewarm_sheet_knowledge()

    print(f"  ├─ Pre-warmed Sheet Records: {len(cache._sheet_records)}")
    print(f"  ├─ BM25 Inverted Index Postings Tokens: {len(cache._sheet_token_index)}")

    # Phase 1: High Volume Write/Read Cycle (10,000 operations)
    t0 = time.perf_counter()
    for i in range(iterations):
        k = f"test_key_{i}"
        v = f"test_value_{i}_with_some_long_payload_text_data_{i}"
        await cache.set(k, v)

    set_time_ms = (time.perf_counter() - t0) * 1000.0

    # Read back verified
    mismatches = 0
    t0 = time.perf_counter()
    for i in range(iterations):
        k = f"test_key_{i}"
        val = await cache.get(k)
        if val != f"test_value_{i}_with_some_long_payload_text_data_{i}":
            mismatches += 1
    get_time_ms = (time.perf_counter() - t0) * 1000.0

    # Phase 2: Invalidation / Overwrite
    t0 = time.perf_counter()
    for i in range(iterations):
        k = f"test_key_{i}"
        v_updated = f"updated_value_{i}"
        await cache.set(k, v_updated)
    overwrite_time_ms = (time.perf_counter() - t0) * 1000.0

    # Verify overwritten value
    overwrite_mismatches = 0
    for i in range(min(500, iterations)):
        k = f"test_key_{i}"
        val = await cache.get(k)
        if val != f"updated_value_{i}":
            overwrite_mismatches += 1

    snapshot2 = tracemalloc.take_snapshot()
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    total_allocated_diff = sum(stat.size_diff for stat in top_stats)
    tracemalloc.stop()

    print(f"  ├─ Set 10,000 keys Time: {set_time_ms:.2f} ms ({set_time_ms/iterations:.4f} ms/op)")
    print(f"  ├─ Get 10,000 keys Time: {get_time_ms:.2f} ms ({get_time_ms/iterations:.4f} ms/op)")
    print(f"  ├─ Overwrite 10,000 keys Time: {overwrite_time_ms:.2f} ms")
    print(f"  ├─ Verification Mismatches: {mismatches} (Set/Get), {overwrite_mismatches} (Overwrite)")
    print(f"  ├─ Total RAM Net Heap Growth: {total_allocated_diff / (1024 * 1024):.2f} MB for 10k cache entries")
    print(f"  └─ Average memory per cached entry: {total_allocated_diff / iterations:.1f} bytes")

    return {
        "iterations": iterations,
        "set_time_ms": set_time_ms,
        "get_time_ms": get_time_ms,
        "overwrite_time_ms": overwrite_time_ms,
        "mismatches": mismatches + overwrite_mismatches,
        "heap_growth_mb": total_allocated_diff / (1024 * 1024),
        "bytes_per_entry": total_allocated_diff / iterations,
    }


# ============================================================================
# 5. Differential Testing Oracle Comparison
# ============================================================================
class BruteForceSheetOracle:
    """Naive brute-force oracle scanning all records linearly without inverted index optimizations."""
    def __init__(self, json_path: str):
        with open(json_path, "r", encoding="utf-8") as f:
            self.records = [r for r in json.load(f) if r.get("question") != "Questions"]

    def naive_search(self, query: str, top_k: int = 3) -> str:
        q_tokens = set(tokenize_text(query))
        if not q_tokens:
            return ""
        
        matches = []
        for r in self.records:
            q_text = r.get("question", "")
            a_text = r.get("answer", "")
            cat_text = f"{r.get('category', '')} {r.get('subcategory', '')}"
            
            doc_tokens = set(tokenize_text(f"{q_text} {cat_text} {a_text}"))
            overlap = len(q_tokens.intersection(doc_tokens))
            if overlap > 0:
                matches.append((overlap, r))
        
        if not matches:
            return ""
        
        matches.sort(key=lambda x: x[0], reverse=True)
        top = matches[:top_k]
        formatted = []
        for i, (ov, r) in enumerate(top, 1):
            q = r.get("question", "")
            a = r.get("answer", "")
            cat = r.get("category", "General")
            subcat = r.get("subcategory", "")
            cat_display = f"{cat} - {subcat}" if subcat else cat
            formatted.append(f"{i}. Q: {q}\nA: {a} (Category: {cat_display})")
        return "\n\n".join(formatted)


async def run_differential_oracle_test(sample_count: int = 200) -> Dict[str, Any]:
    print("\n========================================================")
    print("⚖️ RUNNING TEST 5: DIFFERENTIAL ORACLE TESTING")
    print("========================================================")

    json_path = os.path.join(_SERVER_DIR, "data", "sheet_knowledge.json")
    oracle = BruteForceSheetOracle(json_path)
    cache = RedisRAGCache()
    await cache.prewarm_sheet_knowledge(json_path)

    # Pick 200 real questions from dataset
    sampled_questions = [r["question"] for r in random.sample(oracle.records, min(sample_count, len(oracle.records)))]
    
    matches_found_by_both = 0
    oracle_found_but_cache_missed = 0
    cache_found_but_oracle_missed = 0
    both_empty = 0

    for q in sampled_questions:
        oracle_res = oracle.naive_search(q, top_k=3)
        cache_res = await cache.search_sheet_knowledge(q, top_k=3)

        if oracle_res and cache_res:
            matches_found_by_both += 1
        elif oracle_res and not cache_res:
            oracle_found_but_cache_missed += 1
        elif not oracle_res and cache_res:
            cache_found_but_oracle_missed += 1
        else:
            both_empty += 1

    print(f"  ├─ Queries Sampled from Sheet: {sample_count}")
    print(f"  ├─ Mutual Matches Found: {matches_found_by_both} ({matches_found_by_both/sample_count*100:.1f}%)")
    print(f"  ├─ Cache Missed (Oracle hit): {oracle_found_but_cache_missed}")
    print(f"  ├─ Cache Hit (Oracle missed): {cache_found_but_oracle_missed}")
    print(f"  └─ Both Empty: {both_empty}")

    return {
        "sampled": sample_count,
        "mutual_matches": matches_found_by_both,
        "oracle_only": oracle_found_but_cache_missed,
        "cache_only": cache_found_but_oracle_missed,
        "both_empty": both_empty,
    }


# ============================================================================
# Main Orchestrator
# ============================================================================
async def main():
    print("════════════════════════════════════════════════════════════════════")
    print("🔥 GEMINI LIVE PIPECAT DUAL-LAYER REDIS RAG STRESS TEST SUITE")
    print("════════════════════════════════════════════════════════════════════")

    t_all_start = time.perf_counter()

    t1_results = await run_concurrency_load_test()
    t2_results = await run_latency_distribution_test(iterations=1000)
    t3_results = await run_input_fuzzing_test()
    t4_results = await run_memory_and_invalidation_test(iterations=10000)
    t5_results = await run_differential_oracle_test(sample_count=200)

    total_suite_time_ms = (time.perf_counter() - t_all_start) * 1000.0

    print("\n════════════════════════════════════════════════════════════════════")
    print("🏆 FINAL EMPIRICAL STRESS TEST BENCHMARK REPORT")
    print("════════════════════════════════════════════════════════════════════")
    print(f"1. High Concurrency (1000 simultaneous queries):")
    c1000 = t1_results["1000"]
    print(f"   - Mean Latency: {c1000['mean_ms']:.3f} ms | p99: {c1000['p99_ms']:.3f} ms | RPS: {c1000['rps']:.1f} | Errors: {c1000['error_count']}")
    
    print(f"2. Latency SLA (< 5.0ms @ p99):")
    cold_p99 = t2_results["cold"]["p99"]
    warm_p99 = t2_results["warm"]["p99"]
    handler_p99 = t2_results["handler"]["p99"]
    print(f"   - Cold Path p99: {cold_p99:.4f} ms [{'PASS (<5ms)' if cold_p99 < 5.0 else 'FAIL'}]")
    print(f"   - Warm Path p99: {warm_p99:.4f} ms [{'PASS (<5ms)' if warm_p99 < 5.0 else 'FAIL'}]")
    print(f"   - Tool Handler p99: {handler_p99:.4f} ms [{'PASS (<5ms)' if handler_p99 < 5.0 else 'FAIL'}]")

    print(f"3. Input Fuzzing (0 unhandled exceptions):")
    print(f"   - Total Vectors Fuzzed: {t3_results['total_fuzzed']}")
    print(f"   - Unhandled Exceptions: {len(t3_results['failures'])} [{'PASS (0 errors)' if len(t3_results['failures']) == 0 else 'FAIL'}]")

    print(f"4. Memory Stability & Invalidation:")
    print(f"   - 10k Operations Heap Growth: {t4_results['heap_growth_mb']:.2f} MB")
    print(f"   - Mismatches: {t4_results['mismatches']} [{'PASS' if t4_results['mismatches'] == 0 else 'FAIL'}]")

    print(f"5. Total Benchmark Runtime: {total_suite_time_ms / 1000.0:.2f} s")
    print("════════════════════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    asyncio.run(main())
