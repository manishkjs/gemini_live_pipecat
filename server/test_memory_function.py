import unittest
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch
from memory_function import (
    save_user_memory_schema,
    search_user_memory_schema,
    save_user_memory_handler,
    search_user_memory_handler,
    get_memory_bank_config,
    THRESHOLDS,
    SIMILARITY_THRESHOLD,
    get_mem0_config,
    process_extracted_fact,
    pre_load_user_profile,
    recall_user_memories,
    recall_user_memories_handler,
    is_roleplay_or_popculture_fact,
    extract_graph_triples,
)

class TestMemoryFunction(unittest.IsolatedAsyncioTestCase):
    async def test_save_and_search_local_memory_fallback(self):
        test_file = os.path.join(os.path.dirname(__file__), "test_user_memories_tmp.json")
        if os.path.exists(test_file):
            os.remove(test_file)

        try:
            with patch("memory_function.get_mem0_instance", return_value=None):
                with patch("memory_function.get_memory_file_path", return_value=test_file):
                    # Test saving memory
                    mock_cb_save = AsyncMock()
                    params_save = MagicMock()
                    params_save.arguments = {
                        "memory_text": "User prefers a 12-month tenure for loan",
                        "category": "preference"
                    }
                    params_save.result_callback = mock_cb_save

                    await save_user_memory_handler(params_save)
                    mock_cb_save.assert_called_once()
                    saved_res = mock_cb_save.call_args[0][0]
                    self.assertIn("saved successfully", saved_res.get("content", "").lower())

                    # Verify JSON file content
                    self.assertTrue(os.path.exists(test_file))
                    with open(test_file, "r") as f:
                        data = json.load(f)
                    self.assertEqual(len(data), 1)
                    self.assertEqual(data[0]["memory_text"], "User prefers a 12-month tenure for loan")

                    # Test searching memory
                    mock_cb_search = AsyncMock()
                    params_search = MagicMock()
                    params_search.arguments = {"query": "tenure"}
                    params_search.result_callback = mock_cb_search

                    await search_user_memory_handler(params_search)
                    mock_cb_search.assert_called_once()
                    search_res = mock_cb_search.call_args[0][0]
                    self.assertIn("12-month tenure", search_res.get("content", ""))

        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

    async def test_empty_memory_text_validation(self):
        mock_cb = AsyncMock()
        params = MagicMock()
        params.arguments = {"memory_text": ""}
        params.result_callback = mock_cb

        await save_user_memory_handler(params)
        mock_cb.assert_called_once()
        res = mock_cb.call_args[0][0]
        self.assertIn("cannot be empty", res.get("content", "").lower())

    async def test_mem0_engine_save_success(self):
        mock_cb = AsyncMock()
        params = MagicMock()
        params.arguments = {"memory_text": "User lives in Bangalore", "category": "location"}
        params.result_callback = mock_cb

        mock_mem0 = MagicMock()
        mock_mem0.add.return_value = {"results": [{"id": "1", "memory": "User lives in Bangalore"}]}

        with patch("memory_function.get_mem0_instance", return_value=mock_mem0):
            await save_user_memory_handler(params)
            mock_cb.assert_called_once()
            self.assertIn("mem0", mock_cb.call_args[0][0]["content"].lower())

    async def test_mem0_engine_search_success(self):
        mock_cb = AsyncMock()
        params = MagicMock()
        params.arguments = {"query": "location"}
        params.result_callback = mock_cb

        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = {"results": [{"memory": "User lives in Bangalore"}]}

        with patch("memory_function.get_mem0_instance", return_value=mock_mem0):
            await search_user_memory_handler(params)
            mock_cb.assert_called_once()
            self.assertIn("Bangalore", mock_cb.call_args[0][0]["content"])

    async def test_multi_tenant_isolation(self):
        """Verify that user:rohan and user:priya maintain completely isolated memory stores."""
        test_file_rohan = os.path.join(os.path.dirname(__file__), "user_memories_user_rohan.json")
        test_file_priya = os.path.join(os.path.dirname(__file__), "user_memories_user_priya.json")
        if os.path.exists(test_file_rohan): os.remove(test_file_rohan)
        if os.path.exists(test_file_priya): os.remove(test_file_priya)

        try:
            with patch("memory_function.get_mem0_instance", return_value=None), patch("memory_function.get_memory_bank_config", return_value=(None, None, None)):
                # Save Rohan's memory
                mock_cb_rohan = AsyncMock()
                params_rohan = MagicMock()
                params_rohan.arguments = {"memory_text": "Rohan likes cricket", "category": "sports", "user_id": "user:rohan"}
                params_rohan.result_callback = mock_cb_rohan
                await save_user_memory_handler(params_rohan)

                # Save Priya's memory
                mock_cb_priya = AsyncMock()
                params_priya = MagicMock()
                params_priya.arguments = {"memory_text": "Priya likes tennis", "category": "sports", "user_id": "user:priya"}
                params_priya.result_callback = mock_cb_priya
                await save_user_memory_handler(params_priya)

                # Search Priya's memory for Rohan's fact
                mock_cb_search = AsyncMock()
                params_search = MagicMock()
                params_search.arguments = {"query": "cricket", "user_id": "user:priya"}
                params_search.result_callback = mock_cb_search
                await search_user_memory_handler(params_search)
                self.assertIn("No memories found", mock_cb_search.call_args[0][0]["content"])
        finally:
            if os.path.exists(test_file_rohan): os.remove(test_file_rohan)
            if os.path.exists(test_file_priya): os.remove(test_file_priya)

class TestMem0PgvectorAndTwoPath(unittest.TestCase):
    def test_prd_constants_and_pgvector_config(self):
        self.assertEqual(SIMILARITY_THRESHOLD, 0.65)
        self.assertEqual(THRESHOLDS["M7_Safety"], 1)
        self.assertEqual(THRESHOLDS["M4_Behavioral"], 3)
        
        with patch.dict(os.environ, {"CLOUDSQL_PG_DSN": "postgresql://user:pass@127.0.0.1:5432/memories"}):
            config = get_mem0_config()
            self.assertEqual(config["embedder"]["provider"], "gemini")
            self.assertEqual(config["embedder"]["config"]["model"], "gemini-embedding-001")
            self.assertEqual(config["embedder"]["config"]["embedding_dims"], 768)
            self.assertEqual(config["vector_store"]["provider"], "pgvector")
            self.assertEqual(config["vector_store"]["config"]["connection_string"], "postgresql://user:pass@127.0.0.1:5432/memories")
            self.assertEqual(config["vector_store"]["config"]["embedding_model_dims"], 768)

    @patch("memory_function.get_mem0_instance")
    def test_process_extracted_fact_raw_insert_and_promotion(self, mock_get_mem0):
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        
        # Test 1: No match -> Raw insert (infer=False)
        mock_mem0.search.return_value = {"results": []}
        mock_mem0.add.return_value = {"results": [{"id": "mem-1"}]}
        
        res = process_extracted_fact("User likes coffee", "M3_Preference", "user:test")
        mock_mem0.add.assert_called_once()
        args, kwargs = mock_mem0.add.call_args
        self.assertFalse(kwargs["infer"])
        self.assertEqual(kwargs["metadata"]["status"], "staging") # N=2 for M3_Preference
        
        # Test 2: Match found on new day -> Promotion
        mock_mem0.search.return_value = {
            "results": [{
                "id": "mem-2",
                "score": 0.88, # >= 0.65 SIMILARITY_THRESHOLD
                "metadata": {
                    "status": "staging",
                    "observation_count": 1,
                    "observation_dates": ["2026-07-20"]
                }
            }]
        }
        res2 = process_extracted_fact("User prefers black coffee", "M3_Preference", "user:test")
        mock_mem0.update.assert_called_once()
        update_kwargs = mock_mem0.update.call_args[1]
        self.assertEqual(update_kwargs["metadata"]["status"], "active")
        self.assertEqual(update_kwargs["metadata"]["observation_count"], 2)

    @patch("memory_function.get_mem0_instance")
    def test_path1_pre_load_user_profile(self, mock_get_mem0):
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        mock_mem0.get_all.return_value = {
            "results": [
                {"memory": "User lives in Delhi", "metadata": {"status": "active"}},
                {"memory": "User is allergic to peanuts", "metadata": {"status": "active", "verification_status": "UNVERIFIED"}},
                {"memory": "Expired fact", "metadata": {"status": "active", "expires_at": "2026-01-01T00:00:00"}}
            ]
        }
        valid = pre_load_user_profile("user:test")
        self.assertEqual(len(valid), 2)
        self.assertIn("User lives in Delhi", valid[0])
        self.assertIn("[UNVERIFIED: Confirm with user if relevant]", valid[1])

    @patch("memory_function.get_mem0_instance")
    def test_path2_recall_user_memories(self, mock_get_mem0):
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        mock_mem0.search.return_value = {
            "results": [
                {"memory": "Gaana subscription active", "score": 0.85, "metadata": {"status": "active"}},
                {"memory": "Low score fact", "score": 0.35, "metadata": {"status": "active"}}
            ]
        }
        recalled = recall_user_memories("Gaana", "user:test")
        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0], "Gaana subscription active")

    @patch("memory_function.get_mem0_instance")
    def test_roleplay_and_graph_triples_unit(self, mock_get_mem0):
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        mock_mem0.search.return_value = {"results": []}
        mock_mem0.add.return_value = {"results": [{"id": "unit-mock-id"}]}

        self.assertTrue(is_roleplay_or_popculture_fact("I am Shaktiman and plan to kill Kilvish", "M1_Identity"))
        triples = extract_graph_triples("User says I am Shaktiman and my plan is to kill Kilvish")
        self.assertEqual(triples, {"subject": "Shaktiman", "relation": "plan", "object": "defeat/kill Kilvish"})

        res = process_extracted_fact("User identifies as Shaktiman", "M4_Behavioral", "user:manish")
        args, kwargs = mock_mem0.add.call_args
        self.assertEqual(kwargs["metadata"]["status"], "active")
        self.assertEqual(kwargs["metadata"]["graph_triples"], {"subject": "User", "relation": "identifies_as", "object": "Shaktiman"})

if __name__ == "__main__":
    unittest.main()
