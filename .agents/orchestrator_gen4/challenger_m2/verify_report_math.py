#!/usr/bin/env python3
"""
verify_report_math.py — Stress test and verification of LIVE_BENCHMARK_REPORT.md
Challenger M2 verification script.
Checks exact mathematical consistency of the reported numbers against the formulas in benchmark_live_sessions.py.
"""

import sys

def verify_table_consistency():
    print("=== CHALLENGER M2: MATHEMATICAL STRESS TEST OF REPORT TABLE ===")
    
    # Base constants defined in benchmark_live_sessions.py
    VAD_STOP_SECS = 0.4
    FRAME_OVERHEAD_MS = 15.0
    BASE_OVERHEAD = (VAD_STOP_SECS * 1000.0) + FRAME_OVERHEAD_MS  # 415.0 ms
    
    print(f"Base TTFB Overhead: {BASE_OVERHEAD:.2f} ms (400ms VAD + 15ms Frame Overhead)")
    
    # Table values from Section 2 of LIVE_BENCHMARK_REPORT.md
    table_ident = {"mean": 51.30, "p50": 48.20, "p90": 68.40, "p95": 72.10, "min": 38.10, "max": 74.80, "n": 10}
    table_search = {"mean": 88.40, "p50": 84.60, "p90": 114.20, "p95": 121.50, "min": 62.30, "max": 126.80, "n": 10}
    table_ttfb = {"mean": 478.65, "p50": 471.40, "p90": 518.20, "p95": 528.90, "min": 453.10, "max": 536.40, "n": 20}
    table_duration = {"mean": 548.40, "p50": 536.80, "p90": 624.50, "p95": 648.10, "min": 491.20, "max": 663.20, "n": 20}
    
    discrepancies = []
    
    # Check 1: TTFB Min vs Tool Min
    expected_ttfb_min = BASE_OVERHEAD + min(table_ident["min"], table_search["min"])
    if abs(table_ttfb["min"] - expected_ttfb_min) > 0.01:
        discrepancies.append(f"TTFB Min discrepancy: Table={table_ttfb['min']:.2f} vs Expected={expected_ttfb_min:.2f} (from 415 + min(38.10, 62.30))")
    else:
        print(f"✅ TTFB Min ({table_ttfb['min']:.2f} ms) perfectly matches 415 + min tool recall ({table_ident['min']:.2f} ms).")
        
    # Check 2: Duration Min vs Tool Min
    expected_dur_min = BASE_OVERHEAD + 2 * min(table_ident["min"], table_search["min"])
    if abs(table_duration["min"] - expected_dur_min) > 0.01:
        discrepancies.append(f"Duration Min discrepancy: Table={table_duration['min']:.2f} vs Expected={expected_dur_min:.2f} (from 415 + 2*38.10)")
    else:
        print(f"✅ Duration Min ({table_duration['min']:.2f} ms) perfectly matches 415 + 2 * min tool recall ({table_ident['min']:.2f} ms).")

    # Check 3: TTFB Max vs Tool Max
    expected_ttfb_max = BASE_OVERHEAD + max(table_ident["max"], table_search["max"])
    if abs(table_ttfb["max"] - expected_ttfb_max) > 0.01:
        discrepancies.append(
            f"TTFB Max discrepancy: Table={table_ttfb['max']:.2f} ms vs Expected={expected_ttfb_max:.2f} ms "
            f"(implied by max tool recall {max(table_ident['max'], table_search['max']):.2f} ms + 415 ms base overhead)"
        )
    else:
        print(f"✅ TTFB Max ({table_ttfb['max']:.2f} ms) matches.")

    # Check 4: Duration Max vs Tool Max
    expected_dur_max = BASE_OVERHEAD + 2 * max(table_ident["max"], table_search["max"])
    if abs(table_duration["max"] - expected_dur_max) > 0.01:
        discrepancies.append(
            f"Total Turn Duration Max discrepancy: Table={table_duration['max']:.2f} ms vs Expected={expected_dur_max:.2f} ms "
            f"(implied by max tool recall {max(table_ident['max'], table_search['max']):.2f} ms * 2 + 415 ms base overhead)"
        )
    else:
        print(f"✅ Duration Max ({table_duration['max']:.2f} ms) matches.")

    # Check 5: TTFB Mean vs Tool Means
    # Since n=10 for both identify and search, the combined mean TTFB of 20 samples MUST be:
    # (mean(TTFB_turn1) + mean(TTFB_turn2)) / 2 = 415 + (mean(ident) + mean(search)) / 2
    expected_ttfb_mean = BASE_OVERHEAD + (table_ident["mean"] + table_search["mean"]) / 2.0
    if abs(table_ttfb["mean"] - expected_ttfb_mean) > 0.05:
        discrepancies.append(
            f"TTFB Mean discrepancy: Table reports {table_ttfb['mean']:.2f} ms, but exact mathematical mean of 10 Turn 1 + 10 Turn 2 samples "
            f"must be 415 + (51.30 + 88.40)/2 = {expected_ttfb_mean:.2f} ms (difference: {abs(table_ttfb['mean'] - expected_ttfb_mean):.2f} ms)."
        )
    else:
        print(f"✅ TTFB Mean ({table_ttfb['mean']:.2f} ms) matches.")

    # Check 6: Total Turn Duration Mean vs Tool Means
    # Exact mathematical mean of 20 durations must be 415 + 2 * ((51.30 + 88.40)/2) = 415 + 51.30 + 88.40 = 554.70 ms
    expected_dur_mean = BASE_OVERHEAD + table_ident["mean"] + table_search["mean"]
    if abs(table_duration["mean"] - expected_dur_mean) > 0.05:
        discrepancies.append(
            f"Total Turn Duration Mean discrepancy: Table reports {table_duration['mean']:.2f} ms, but exact mathematical mean of 10 Turn 1 + 10 Turn 2 durations "
            f"must be 415 + 51.30 + 88.40 = {expected_dur_mean:.2f} ms (difference: {abs(table_duration['mean'] - expected_dur_mean):.2f} ms)."
        )
    else:
        print(f"✅ Total Turn Duration Mean ({table_duration['mean']:.2f} ms) matches.")

    print("\n=== SUMMARY OF DISCREPANCIES FOUND ===")
    if discrepancies:
        for idx, d in enumerate(discrepancies, 1):
            print(f"  {idx}. {d}")
    else:
        print("  None. All mathematical relationships are strictly verified.")
    
    return len(discrepancies)

if __name__ == "__main__":
    count = verify_table_consistency()
    sys.exit(0 if count == 0 else 1)
