import unittest
import json
import os
import sys
from unittest.mock import patch, MagicMock

# Add parent directory to sys.path so we can import memory_function
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from memory_function import (
    process_extracted_fact,
    recall_user_memories,
    is_roleplay_or_popculture_fact,
    extract_graph_triples,
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
                fact_text = case["expected_extraction"][0]
                
                # Verify base threshold lookup or roleplay dynamic override
                is_roleplay = is_roleplay_or_popculture_fact(fact_text, category)
                base_N = 1 if is_roleplay else THRESHOLDS[category]
                self.assertEqual(base_N, expected_N)
                
                # Simulate processing extracted fact
                res = process_extracted_fact(fact_text, category, "user:eval_bench")
                
                mock_mem0.add.assert_called()
                args, kwargs = mock_mem0.add.call_args
                
                # Verify status assignment based on N
                expected_status = "active" if expected_N == 1 else "staging"
                self.assertEqual(kwargs["metadata"]["status"], expected_status)
                
                if "expected_graph_triples" in case:
                    self.assertEqual(kwargs["metadata"]["graph_triples"], case["expected_graph_triples"])
                
                if category == "M7_Safety":
                    self.assertEqual(kwargs["metadata"]["verification_status"], "UNVERIFIED")
                elif category == "M6_Recent":
                    self.assertIsNotNone(kwargs["metadata"]["expires_at"])

    @patch("memory_function.get_mem0_instance")
    def test_roleplay_and_graph_triples_across_users(self, mock_get_mem0):
        """
        Verify that graph triples and roleplay facts (Shaktiman, Kilvish, Kabir, Adhyanth)
        are exactly stored as active and retrieved across distinct user IDs (user:manish, user:rohan, default_user).
        """
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        mock_mem0.search.return_value = {"results": []}
        mock_mem0.add.return_value = {"results": [{"id": "roleplay-mock-id"}]}

        users_to_test = ["user:manish", "user:rohan", "default_user"]
        roleplay_cases = [case for case in self.golden_set if "roleplay" in case["id"]]
        self.assertGreaterEqual(len(roleplay_cases), 3)

        for user_id in users_to_test:
            stored_memories = []
            for case in roleplay_cases:
                fact_text = case["expected_extraction"][0]
                category = case["category"]
                
                res = process_extracted_fact(fact_text, category, user_id)
                args, kwargs = mock_mem0.add.call_args
                
                self.assertEqual(kwargs["metadata"]["status"], "active")
                self.assertEqual(kwargs["metadata"]["graph_triples"], case["expected_graph_triples"])
                
                stored_memories.append({
                    "memory": fact_text,
                    "metadata": kwargs["metadata"]
                })

            # Mock mem0.get_all to return our stored active memories when recall_user_memories queries
            mock_mem0.get_all.return_value = {"results": stored_memories}
            
            recalled_shaktiman = recall_user_memories("Shaktiman", user_id)
            self.assertTrue(any("Shaktiman" in m for m in recalled_shaktiman))
            
            recalled_kilvish = recall_user_memories("Kilvish", user_id)
            self.assertTrue(any("Kilvish" in m for m in recalled_kilvish))
            
            recalled_kabir = recall_user_memories("Kabir", user_id)
            self.assertTrue(any("Kabir" in m for m in recalled_kabir))

    def test_privacy_governance_prompt_configured(self):
        """Verify that get_mem0_config explicitly includes location and PII governance rules."""
        config = get_mem0_config()
        self.assertIn("custom_prompt", config)
        self.assertIn("coarse user-stated places", config["custom_prompt"])
        self.assertIn("Never extract exact street addresses", config["custom_prompt"])

if __name__ == "__main__":
    unittest.main()
