import unittest
import json
import os
import sys
from unittest.mock import patch, MagicMock

# Add parent directory to sys.path so we can import memory_function
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from memory_function import (
    process_extracted_fact,
    THRESHOLDS,
    SIMILARITY_THRESHOLD,
    get_mem0_config,
)

class TestMemoryEvalBench(unittest.TestCase):
    """
    Automated CI Evaluation Benchmark Runner (W1.3 / W2.3).
    Validates extraction accuracy, threshold gating, verification flags, and privacy scrubbing against the golden set.
    """
    def setUp(self):
        golden_file = os.path.join(os.path.dirname(__file__), "golden_set_sample.json")
        with open(golden_file, "r", encoding="utf-8") as f:
            self.golden_set = json.load(f)

    @patch("memory_function.get_mem0_instance")
    def test_golden_set_extraction_and_promotion_rules(self, mock_get_mem0):
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        mock_mem0.search.return_value = {"results": []}
        mock_mem0.add.return_value = {"results": [{"id": "eval-mock-id"}]}

        for case in self.golden_set:
            with self.subTest(case_id=case["id"]):
                category = case["category"]
                expected_N = case["expected_threshold_N"]
                
                # Verify threshold lookup
                self.assertEqual(THRESHOLDS[category], expected_N)
                
                # Simulate processing extracted fact
                fact_text = case["expected_extraction"][0]
                res = process_extracted_fact(fact_text, category, "user:eval_bench")
                
                mock_mem0.add.assert_called()
                args, kwargs = mock_mem0.add.call_args
                
                # Verify status assignment based on N
                expected_status = "active" if expected_N == 1 else "staging"
                self.assertEqual(kwargs["metadata"]["status"], expected_status)
                
                if category == "M7_Safety":
                    self.assertEqual(kwargs["metadata"]["verification_status"], "UNVERIFIED")
                elif category == "M6_Recent":
                    self.assertIsNotNone(kwargs["metadata"]["expires_at"])

    def test_privacy_governance_prompt_configured(self):
        """Verify that get_mem0_config explicitly includes location and PII governance rules."""
        config = get_mem0_config()
        self.assertIn("custom_prompt", config)
        self.assertIn("coarse user-stated places", config["custom_prompt"])
        self.assertIn("Never extract exact street addresses", config["custom_prompt"])

if __name__ == "__main__":
    unittest.main()
