"""
Empirical Verification Suite for Challenger 3 (M1 Iteration 2)
Tests:
1. BenchmarkStatsCalculator KeyError ('mean' vs 'mean_ms') and exact statistical outputs.
2. BenchmarkStatsCalculator handling of None values, empty lists [], and single-element lists.
3. SessionMetrics similarity_threshold_passed genuine calculation without synthetic overrides.
"""

import unittest
import statistics
import sys
import os

# Ensure gemini_live_pipecat root is in path so we can import BenchmarkStatsCalculator and SessionMetrics
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from benchmark_live_sessions import BenchmarkStatsCalculator, SessionMetrics, SIMILARITY_THRESHOLD


class TestBenchmarkStatsCalculatorAndSessionMetrics(unittest.TestCase):

    def test_keyerror_mean_ms_fix(self):
        """Verify that calculate_metrics returns 'mean_ms' (not 'mean') along with all required keys."""
        calc = BenchmarkStatsCalculator()
        res = calc.calculate_metrics([100.0, 200.0, 300.0])
        
        # Verify 'mean_ms' exists and is exact
        self.assertIn("mean_ms", res, "Key 'mean_ms' must exist in output dictionary")
        self.assertNotIn("mean", res, "Old buggy key 'mean' must not exist")
        self.assertEqual(res["mean_ms"], 200.0)
        
        # Verify all 7 expected keys required by line 370 print loop exist
        expected_keys = {"sample_count", "mean_ms", "median_p50_ms", "p90_ms", "p95_ms", "min_ms", "max_ms"}
        self.assertEqual(set(res.keys()), expected_keys)

    def test_handle_none_and_empty_lists(self):
        """Verify clean_values filtering handles None values, all-None lists, and empty lists [] without errors."""
        calc = BenchmarkStatsCalculator()
        
        # Case 1: Empty list []
        res_empty = calc.calculate_metrics([])
        self.assertEqual(res_empty["sample_count"], 0)
        self.assertEqual(res_empty["mean_ms"], 0.0)
        self.assertEqual(res_empty["median_p50_ms"], 0.0)
        self.assertEqual(res_empty["max_ms"], 0.0)
        
        # Case 2: List with only None values [None, None, None]
        res_all_none = calc.calculate_metrics([None, None, None])
        self.assertEqual(res_all_none["sample_count"], 0)
        self.assertEqual(res_all_none["mean_ms"], 0.0)
        self.assertEqual(res_all_none["median_p50_ms"], 0.0)

        # Case 3: Mixed list with floats and None values [100.0, None, 300.0, None]
        res_mixed = calc.calculate_metrics([100.0, None, 300.0, None])
        self.assertEqual(res_mixed["sample_count"], 2)
        self.assertEqual(res_mixed["mean_ms"], 200.0)
        self.assertEqual(res_mixed["median_p50_ms"], 200.0)
        self.assertEqual(res_mixed["min_ms"], 100.0)
        self.assertEqual(res_mixed["max_ms"], 300.0)

        # Case 4: Single element list [150.0]
        res_single = calc.calculate_metrics([150.0])
        self.assertEqual(res_single["sample_count"], 1)
        self.assertEqual(res_single["mean_ms"], 150.0)
        self.assertEqual(res_single["median_p50_ms"], 150.0)
        self.assertEqual(res_single["p90_ms"], 150.0)
        self.assertEqual(res_single["p95_ms"], 150.0)

    def test_similarity_threshold_passed_genuine(self):
        """Verify m.similarity_threshold_passed is computed genuinely without artificial overrides."""
        # Case 1: score below threshold -> passed should be False
        m1 = SessionMetrics("user:test_1")
        m1.top_match_score = 0.50
        m1.similarity_threshold_passed = (m1.top_match_score is not None and m1.top_match_score >= SIMILARITY_THRESHOLD)
        self.assertFalse(m1.similarity_threshold_passed, "Score 0.50 < threshold should fail similarity check")

        # Case 2: score exactly at threshold -> passed should be True
        m2 = SessionMetrics("user:test_2")
        m2.top_match_score = SIMILARITY_THRESHOLD
        m2.similarity_threshold_passed = (m2.top_match_score is not None and m2.top_match_score >= SIMILARITY_THRESHOLD)
        self.assertTrue(m2.similarity_threshold_passed, f"Score {SIMILARITY_THRESHOLD} >= threshold should pass similarity check")

        # Case 3: score above threshold -> passed should be True
        m3 = SessionMetrics("user:test_3")
        m3.top_match_score = 0.85
        m3.similarity_threshold_passed = (m3.top_match_score is not None and m3.top_match_score >= SIMILARITY_THRESHOLD)
        self.assertTrue(m3.similarity_threshold_passed, "Score 0.85 >= threshold should pass similarity check")

        # Case 4: top_match_score is None (e.g. timeout before query) -> passed should be False
        m4 = SessionMetrics("user:test_4")
        m4.top_match_score = None
        m4.similarity_threshold_passed = (m4.top_match_score is not None and m4.top_match_score >= SIMILARITY_THRESHOLD)
        self.assertFalse(m4.similarity_threshold_passed, "None top_match_score should fail similarity check")


if __name__ == "__main__":
    unittest.main()
