"""Consolidated E2E Test Suite Runner for Cymbal Lending P2P Voicebot.

Executes all 4 E2E test tiers and backend unit/route test suites:
- Tier 1: Category-Partition Feature Coverage (tests/e2e/tier1_feature_coverage_test.py)
- Tier 2: Boundary Value Analysis & Edge Cases (tests/e2e/tier2_boundary_corner_test.py)
- Tier 3: Pairwise Cross-Feature Combinations (tests/e2e/tier3_cross_feature_test.py)
- Tier 4: Real-World Application Workloads & Journeys (tests/e2e/tier4_real_world_scenarios_test.py)
- Backend Unit Tests (server/tests/test_financial_math.py)
- Backend Integration/Route Tests (server/test_routes.py)

Generates a detailed summary table and exits with code 0 if and only if 100% of tests pass.
"""

import os
import sys
import time
import unittest
import importlib
from typing import Dict, Any, List

# Setup sys.path for server and tests directories
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SERVER_DIR = os.path.join(PROJECT_ROOT, "server")
TESTS_E2E_DIR = os.path.join(PROJECT_ROOT, "tests", "e2e")

for p in [PROJECT_ROOT, SERVER_DIR, TESTS_E2E_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)


def run_suite_and_collect_stats(name: str, module_name: str) -> Dict[str, Any]:
    """Import and run a unittest test module, collecting granular statistics."""
    loader = unittest.TestLoader()
    try:
        module = importlib.import_module(module_name)
    except Exception as e:
        print(f"❌ Failed to import module {module_name}: {e}")
        return {
            "name": name,
            "module": module_name,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "skipped": 0,
            "duration": 0.0,
            "pass_rate": 0.0,
            "success": False,
        }

    suite = loader.loadTestsFromModule(module)
    total_tests = suite.countTestCases()

    # Capture test execution output
    start_time = time.perf_counter()
    runner = unittest.TextTestRunner(stream=open(os.devnull, 'w'), verbosity=0)
    result = runner.run(suite)
    duration = time.perf_counter() - start_time

    failed_count = len(result.failures)
    error_count = len(result.errors)
    skipped_count = len(result.skipped)
    passed_count = total_tests - failed_count - error_count - skipped_count
    pass_rate = (passed_count / total_tests * 100.0) if total_tests > 0 else 0.0
    is_success = result.wasSuccessful()

    return {
        "name": name,
        "module": module_name,
        "total": total_tests,
        "passed": passed_count,
        "failed": failed_count,
        "errors": error_count,
        "skipped": skipped_count,
        "duration": duration,
        "pass_rate": pass_rate,
        "success": is_success,
    }


def main():
    print("\n" + "=" * 92)
    print(" " * 20 + "CYMBAL LENDING P2P VOICEBOT E2E TEST SUITE")
    print("=" * 92 + "\n")

    test_suites_to_run = [
        ("Tier 1: Feature Coverage (Category-Partition)", "tier1_feature_coverage_test"),
        ("Tier 2: Boundary & Corner Cases", "tier2_boundary_corner_test"),
        ("Tier 3: Cross-Feature Combinations (Pairwise)", "tier3_cross_feature_test"),
        ("Tier 4: Real-World Application Workloads", "tier4_real_world_scenarios_test"),
        ("Backend: Financial Math Unit Tests", "tests.test_financial_math"),
        ("Backend: Phase Engine & Prompt Yielding", "tests.test_phase_engine"),
        ("Backend: Routes & Diagnostics Integration", "test_routes"),
    ]

    results: List[Dict[str, Any]] = []

    for name, mod in test_suites_to_run:
        print(f"▶ Running {name} ({mod})...")
        stats = run_suite_and_collect_stats(name, mod)
        status_symbol = "✅" if stats["success"] else "❌"
        print(f"  {status_symbol} {stats['passed']}/{stats['total']} tests passed in {stats['duration']:.3f}s\n")
        results.append(stats)

    # Calculate aggregate totals
    total_tests = sum(r["total"] for r in results)
    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    total_errors = sum(r["errors"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    total_duration = sum(r["duration"] for r in results)
    overall_pass_rate = (total_passed / total_tests * 100.0) if total_tests > 0 else 0.0
    all_passed = (total_failed == 0 and total_errors == 0 and total_tests > 0)

    # Print Summary Table
    print("=" * 92)
    print(" " * 32 + "CONSOLIDATED TEST RESULTS")
    print("=" * 92)
    header = f"{'Suite Name':<46} | {'Tests':>6} | {'Passed':>6} | {'Failed':>6} | {'Errors':>6} | {'Time (s)':>8} | {'Rate':>6}"
    print(header)
    print("-" * 46 + "-+-" + "-" * 6 + "-+-" + "-" * 6 + "-+-" + "-" * 6 + "-+-" + "-" * 6 + "-+-" + "-" * 8 + "-+-" + "-" * 6)

    for r in results:
        row = (
            f"{r['name']:<46} | "
            f"{r['total']:>6} | "
            f"{r['passed']:>6} | "
            f"{r['failed']:>6} | "
            f"{r['errors']:>6} | "
            f"{r['duration']:>7.3f}s | "
            f"{r['pass_rate']:>5.1f}%"
        )
        print(row)

    print("-" * 46 + "-+-" + "-" * 6 + "-+-" + "-" * 6 + "-+-" + "-" * 6 + "-+-" + "-" * 6 + "-+-" + "-" * 8 + "-+-" + "-" * 6)
    total_row = (
        f"{'TOTAL CONSOLIDATED E2E SUITE':<46} | "
        f"{total_tests:>6} | "
        f"{total_passed:>6} | "
        f"{total_failed:>6} | "
        f"{total_errors:>6} | "
        f"{total_duration:>7.3f}s | "
        f"{overall_pass_rate:>5.1f}%"
    )
    print(total_row)
    print("=" * 92 + "\n")

    if all_passed:
        print("🎉 ALL TESTS PASSED! 100% SUCCESS RATE ACROSS TIERS 1-4 & BACKEND SUITES.\n")
        sys.exit(0)
    else:
        print(f"❌ TEST SUITE FAILED: {total_failed} failures, {total_errors} errors.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
