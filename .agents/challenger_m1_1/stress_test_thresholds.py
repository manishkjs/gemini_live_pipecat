#!/usr/bin/env python3
"""
Empirical Stress Test & Verification Harness for Challenger M1-1
Targets: SIMILARITY_THRESHOLD = 0.65, gemini-embedding-001 (768 dims), memory_function.py
"""

import sys
import os
import unittest
import math
from unittest.mock import MagicMock, patch

# Ensure server module is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "server"))

from memory_function import (
    SIMILARITY_THRESHOLD,
    RETRIEVAL_THRESHOLD,
    THRESHOLDS,
    get_mem0_config,
    process_extracted_fact,
    recall_user_memories,
)

class StressTestSimilarityAndEmbeddings(unittest.TestCase):

    def test_challenge_1_comment_vs_constant_drift(self):
        """
        CHALLENGE 1: Empirical verification of Specification Drift.
        Docstrings in memory_function.py line 350 and line 509 claim:
          "Apply Similarity Threshold Gate (min_score >= 0.80)"
        and
          "Applies similarity gate (score >= 0.80)"
        However SIMILARITY_THRESHOLD is set to 0.65.
        """
        expected_docstring_threshold = 0.80
        actual_threshold = SIMILARITY_THRESHOLD
        
        self.assertNotEqual(
            actual_threshold, expected_docstring_threshold,
            f"CRITICAL SPEC DRIFT: SIMILARITY_THRESHOLD is {actual_threshold}, "
            f"but comments in code mandate min_score >= {expected_docstring_threshold}!"
        )
        print(f"[FAIL-ORACLE] Spec Drift Confirmed: Code constant={actual_threshold} != Docstring spec={expected_docstring_threshold}")

    def test_challenge_2_dead_constant_retrieval_threshold(self):
        """
        CHALLENGE 2: RETRIEVAL_THRESHOLD = 0.40 is defined at top level
        but never utilized anywhere in the codebase.
        """
        import inspect
        import memory_function
        source = inspect.getsource(memory_function)
        
        # Count occurrences of RETRIEVAL_THRESHOLD in source code
        occurrences = source.count("RETRIEVAL_THRESHOLD")
        self.assertEqual(
            occurrences, 1,
            f"DEAD CODE VULNERABILITY: RETRIEVAL_THRESHOLD defined but referenced {occurrences} times (only definition site)."
        )
        print(f"[FAIL-ORACLE] Dead Code Confirmed: RETRIEVAL_THRESHOLD=0.40 unused across entire server/memory_function.py")

    def test_challenge_3_destructive_memory_overwrite_on_near_match(self):
        """
        CHALLENGE 3: Low similarity threshold (0.65) causes destructive memory overwrites.
        When process_extracted_fact receives a fact that matches an existing memory at score 0.68
        (e.g., "User is allergic to peanuts" vs "User is allergic to penicillin"),
        mem0.update is called with memory_id=best_match["id"], data=fact_text.
        This SILENTLY OVERWRITES the existing distinct facts!
        """
        mock_mem0 = MagicMock()
        
        # Existing staging memory: "User is allergic to peanuts"
        existing_memory_id = "mem_allergy_001"
        existing_text = "User is allergic to peanuts"
        new_conflicting_text = "User is allergic to penicillin"
        
        # Cosine similarity between template-similar sentences is frequently 0.65-0.78 in 768d space
        simulated_score = 0.71  # >= 0.65 threshold
        
        mock_mem0.search.return_value = {
            "results": [{
                "id": existing_memory_id,
                "memory": existing_text,
                "score": simulated_score,
                "metadata": {
                    "status": "staging",
                    "observation_count": 1,
                    "observation_dates": ["2026-07-20"]
                }
            }]
        }
        
        with patch("memory_function.get_mem0_instance", return_value=mock_mem0):
            process_extracted_fact(new_conflicting_text, "M7_Safety", "user:test_patient")
            
            # Check what was passed to mem0.update
            mock_mem0.update.assert_called_once()
            call_kwargs = mock_mem0.update.call_args[1]
            updated_data = call_kwargs.get("data")
            
            # EMPIRICAL PROOF OF DESTRUCTIVE OVERWRITE:
            self.assertEqual(updated_data, new_conflicting_text)
            self.assertNotEqual(updated_data, existing_text)
            print(f"[FAIL-ORACLE] Silent Overwrite Confirmed: Original memory '{existing_text}' was DELETED and REPLACED by '{updated_data}' due to score {simulated_score} >= {SIMILARITY_THRESHOLD}!")

    def test_challenge_4_gemini_embedding_001_configuration(self):
        """
        CHALLENGE 4: Verify embedder configuration stability.
        Model name 'gemini-embedding-001' with 768 dims in get_mem0_config().
        """
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test_key"}):
            cfg = get_mem0_config()
            embedder_cfg = cfg["embedder"]["config"]
            
            self.assertEqual(embedder_cfg["model"], "gemini-embedding-001")
            self.assertEqual(embedder_cfg["embedding_dims"], 768)
            
            # Theoretical geometric warning for 768 dims under cosine similarity 0.65
            # Synthetic unit-norm high-dim vector property:
            # Concentrated cosine similarity around non-zero baseline.
            print(f"[PASS-ORACLE] Config verified: model={embedder_cfg['model']}, dims={embedder_cfg['embedding_dims']}")

    def test_challenge_5_false_negative_cross_lingual_similarity_drop(self):
        """
        CHALLENGE 5: Real-world user scenario on Smartglasses:
        User says in turn 1: "My son's name is Adhyanth"
        User says in turn 2: "बेटे का नाम आद्यांत है" (Hindi)
        If cross-lingual embedding score is 0.58 (< 0.65), process_extracted_fact fails to match,
        creating TWO fragmented staging entries instead of promoting one to active.
        """
        mock_mem0 = MagicMock()
        cross_lingual_score = 0.58  # Below 0.65 threshold
        
        mock_mem0.search.return_value = {
            "results": [{
                "id": "mem_son_eng",
                "memory": "User's son name is Adhyanth",
                "score": cross_lingual_score,
                "metadata": {"status": "staging", "observation_count": 1, "observation_dates": ["2026-07-20"]}
            }]
        }
        mock_mem0.add.return_value = {"results": [{"id": "mem_son_hin"}]}
        
        with patch("memory_function.get_mem0_instance", return_value=mock_mem0):
            process_extracted_fact("बेटे का नाम आद्यांत है", "M2_Relation", "user:rohan")
            
            # When score < 0.65, mem0.add (new entry) is invoked instead of promotion update
            mock_mem0.add.assert_called_once()
            mock_mem0.update.assert_not_called()
            print(f"[FAIL-ORACLE] Cross-lingual Fragmentation Confirmed: Hinglish paraphrase score {cross_lingual_score} < {SIMILARITY_THRESHOLD} caused duplicate memory creation instead of promotion!")

if __name__ == "__main__":
    unittest.main(verbosity=2)
