#!/usr/bin/env python3
"""
Stress harness for BenchmarkStatsCalculator & similarity gating in benchmark_live_sessions.py
Challenger 1 Empirical Verification Suite
"""

import sys
import os
import statistics
import traceback
import json

# Add parent directory so we can import benchmark_live_sessions
sys.path.insert(0, "/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat")

try:
    from benchmark_live_sessions import BenchmarkStatsCalculator, SessionMetrics, print_summary_and_save_artifacts
    print("✅ Successfully imported BenchmarkStatsCalculator & SessionMetrics")
except Exception as e:
    print(f"❌ Failed to import from benchmark_live_sessions.py: {e}")
    traceback.print_exc()
    sys.exit(1)

def test_1_key_error_in_print_summary():
    print("\n--- TEST 1: Testing print_summary_and_save_artifacts KeyError ---")
    metrics_list = []
    for i in range(1, 11):
        m = SessionMetrics(f"user:test_session_{i}")
        m.http_negotiate_ms = 100.0 + i
        m.ws_handshake_ms = 50.0 + i
        m.identify_user_latency_ms = 40.0 + i
        m.search_memory_latency_ms = 60.0 + i
        m.ttfb_turn1_ms = 455.0 + i
        m.ttfb_turn2_ms = 475.0 + i
        m.total_turn1_duration_ms = 495.0 + i
        m.total_turn2_duration_ms = 535.0 + i
        m.top_match_score = 0.70
        m.similarity_threshold_passed = True
        metrics_list.append(m)

    try:
        # Redirect stdout or run directly
        print_summary_and_save_artifacts(metrics_list)
        print("❌ Unexpected: print_summary_and_save_artifacts did NOT raise KeyError!")
    except KeyError as ke:
        print(f"✅ CONFIRMED BUG: print_summary_and_save_artifacts threw KeyError: {ke}")
    except Exception as e:
        print(f"⚠️ Threw different exception: {type(e).__name__}: {e}")
        traceback.print_exc()

def test_2_identical_latency_values():
    print("\n--- TEST 2: All 10 sessions return identical latency values (e.g. 100.0 ms) ---")
    vals = [100.0] * 10
    res = BenchmarkStatsCalculator.calculate_metrics(vals)
    print(f"Input: {vals}")
    print(f"Result: {json.dumps(res, indent=2)}")
    assert res["mean_ms"] == 100.0
    assert res["median_p50_ms"] == 100.0
    assert res["p90_ms"] == 100.0
    assert res["p95_ms"] == 100.0
    print("✅ Identical latency values handled without exception.")

def test_3_sample_count_10_quantiles():
    print("\n--- TEST 3: n=10 sample_count quantiles(n=100) behavior & indexing ---")
    # Let's test with 10 distinct values: [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    vals = [float(i * 10) for i in range(1, 11)]
    res = BenchmarkStatsCalculator.calculate_metrics(vals)
    print(f"Input: {vals}")
    print(f"Result from calculate_metrics: {json.dumps(res, indent=2)}")
    
    # Let's check what statistics.quantiles(vals, n=100, method='inclusive') actually returns
    q100 = statistics.quantiles(vals, n=100, method='inclusive')
    print(f"statistics.quantiles(vals, n=100, method='inclusive')[89] (p90): {q100[89]}")
    print(f"statistics.quantiles(vals, n=100, method='inclusive')[94] (p95): {q100[94]}")
    
    # Let's check fallback if quantiles threw an exception or method='exclusive'
    idx_90 = min(int(round(0.90 * (len(vals) - 1))), len(vals) - 1)
    idx_95 = min(int(round(0.95 * (len(vals) - 1))), len(vals) - 1)
    print(f"Fallback formula idx_90={idx_90} -> val={vals[idx_90]}")
    print(f"Fallback formula idx_95={idx_95} -> val={vals[idx_95]}")

def test_4_edge_cases():
    print("\n--- TEST 4: Boundary Edge Cases (Empty, n=1, n=2, duplicates, negatives, floats) ---")
    cases = [
        ("Empty list []", []),
        ("Single element [42.5]", [42.5]),
        ("Two elements [10.0, 90.0]", [10.0, 90.0]),
        ("Large numbers [1e9, 1e9+10]", [1e9, 1e9+10]),
        ("Duplicate boundaries [0.0, 0.0, 0.0]", [0.0, 0.0, 0.0])
    ]
    for label, data in cases:
        try:
            res = BenchmarkStatsCalculator.calculate_metrics(data)
            print(f"  {label} -> PASS: sample_count={res['sample_count']}, p50={res['median_p50_ms']}, p90={res['p90_ms']}, p95={res['p95_ms']}")
        except Exception as e:
            print(f"  {label} -> FAIL: {e}")
            traceback.print_exc()

def test_5_similarity_threshold_bypass_check():
    print("\n--- TEST 5: Verify similarity threshold override vulnerability ---")
    # In run_single_session_flow:
    # If top_score < SIMILARITY_THRESHOLD and m.search_success and ("Kabir" in m.retrieved_content or "Sharma" in m.retrieved_content):
    #     top_score = max(top_score, 0.885)
    # Let's verify what happens if actual vector search returns 0.20 (below threshold 0.65)
    SIMILARITY_THRESHOLD = 0.65
    top_score = 0.20
    search_success = True
    retrieved_content = "Kabir Sharma is his son"
    
    print(f"Before override: top_score={top_score}, threshold={SIMILARITY_THRESHOLD}")
    if top_score < SIMILARITY_THRESHOLD and search_success and ("Kabir" in retrieved_content or "Sharma" in retrieved_content):
        top_score = max(top_score, 0.885)
    similarity_threshold_passed = (top_score >= SIMILARITY_THRESHOLD)
    print(f"After override: top_score={top_score}, passed={similarity_threshold_passed}")
    assert similarity_threshold_passed is True
    print("✅ CONFIRMED: Even when vector similarity score is 0.20 (< 0.65 threshold), the hardcoded check overrides top_score to 0.885 and passes the gate!")

if __name__ == "__main__":
    test_1_key_error_in_print_summary()
    test_2_identical_latency_values()
    test_3_sample_count_10_quantiles()
    test_4_edge_cases()
    test_5_similarity_threshold_bypass_check()
