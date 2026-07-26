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
    process_session_transcript,
    normalize_category,
    content_fingerprint,
    find_dedupe_match,
    pre_load_user_profile,
    recall_user_memories,
    recall_user_memories_handler,
    is_roleplay_or_popculture_fact,
    extract_graph_triples,
    normalize_user_id,
)

class TestMemoryFunction(unittest.IsolatedAsyncioTestCase):
    async def test_save_and_search_alloydb_error_when_instance_none(self):
        with patch("memory_function.get_mem0_instance", return_value=None):
            # Test saving memory when AlloyDB is disconnected/uninitialized
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
            self.assertIn("failed to save memory: alloydb pgvector store is not connected", saved_res.get("content", "").lower())

            # Test searching memory when AlloyDB is disconnected/uninitialized
            mock_cb_search = AsyncMock()
            params_search = MagicMock()
            params_search.arguments = {"query": "tenure"}
            params_search.result_callback = mock_cb_search

            await search_user_memory_handler(params_search)
            mock_cb_search.assert_called_once()
            search_res = mock_cb_search.call_args[0][0]
            self.assertIn("memory search unavailable: alloydb pgvector store is not connected", search_res.get("content", "").lower())

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
        """Verify that user:rohan and user:priya maintain completely isolated memory stores via user_id filters."""
        mock_mem0 = MagicMock()
        mock_mem0.search.side_effect = lambda query, filters: {"results": [{"memory": "Rohan likes cricket", "metadata": {"status": "active"}, "score": 0.95}]} if filters.get("user_id") == "user:rohan" else {"results": []}
        mock_mem0.get_all.return_value = {"results": []}

        with patch("memory_function.get_mem0_instance", return_value=mock_mem0), patch("memory_function.get_memory_bank_config", return_value=(None, None, None)):
            mock_cb_search = AsyncMock()
            params_search = MagicMock()
            params_search.arguments = {"query": "cricket", "user_id": "user:priya"}
            params_search.result_callback = mock_cb_search
            await search_user_memory_handler(params_search)
            self.assertIn("No memories found", mock_cb_search.call_args[0][0]["content"])
            mock_mem0.search.assert_any_call(query="cricket", filters={"user_id": "user:priya"})

class TestMem0PgvectorAndTwoPath(unittest.TestCase):
    def test_prd_constants_and_pgvector_config(self):
        # 0.83 not 0.20: gemini-embedding-001 puts unrelated "User ..." sentences
        # at a 0.55-0.75 baseline, so a low gate makes update() clobber good data.
        self.assertEqual(SIMILARITY_THRESHOLD, 0.83)
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
        
        # Test 2: Match found on new day, same category -> Promotion
        mock_mem0.search.return_value = {
            "results": [{
                "id": "mem-2",
                "score": 0.88,  # >= 0.83 SIMILARITY_THRESHOLD
                "metadata": {
                    "status": "staging",
                    "category": "M3_Preference",
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
    def test_high_score_across_categories_never_overwrites(self, mock_get_mem0):
        """A near-identical embedding in a different PRD tier must not be clobbered.

        This is the regression guard for the bug where a peanut allergy (M7) was
        destroyed by a frame preference (M3) that merely embedded close to it.
        """
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        mock_mem0.search.return_value = {
            "results": [{
                "id": "mem-safety",
                "score": 0.97,
                "metadata": {"status": "active", "category": "M7_Safety", "observation_count": 1}
            }]
        }
        mock_mem0.add.return_value = {"results": [{"id": "mem-new"}]}

        process_extracted_fact("User prefers blue titanium frames", "preference", "user:test")

        mock_mem0.update.assert_not_called()
        mock_mem0.add.assert_called_once()
        self.assertEqual(mock_mem0.add.call_args[1]["metadata"]["category"], "M3_Preference")

    @patch("memory_function.get_mem0_instance")
    def test_identical_fact_dedupes_on_content_hash(self, mock_get_mem0):
        """An exact restatement folds into the existing row even below the score gate."""
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        text = "User prefers blue titanium frames"
        mock_mem0.search.return_value = {
            "results": [{
                "id": "mem-dupe",
                "score": 0.11,  # well under the gate
                "metadata": {
                    "status": "staging",
                    "category": "M3_Preference",
                    "content_hash": content_fingerprint(text),
                    "observation_count": 1,
                    "observation_dates": ["2026-07-20"]
                }
            }]
        }
        process_extracted_fact(text, "preference", "user:test")
        mock_mem0.update.assert_called_once()
        mock_mem0.add.assert_not_called()

    def test_normalize_category_maps_llm_strings_to_prd_codes(self):
        """The tool schema emits human words; the matrix keys on M1..M7."""
        self.assertEqual(normalize_category("preference"), "M3_Preference")
        self.assertEqual(normalize_category("financial_goal"), "M3_Preference")
        self.assertEqual(normalize_category("personal"), "M1_Identity")
        self.assertEqual(normalize_category("contact_info"), "M1_Identity")
        self.assertEqual(normalize_category("allergy"), "M7_Safety")
        self.assertEqual(normalize_category("reminder"), "M6_Recent")
        self.assertEqual(normalize_category("family"), "M2_Relation")
        # Canonical codes pass straight through.
        self.assertEqual(normalize_category("M7_Safety"), "M7_Safety")
        # Unknown and empty fall back to the most conservative tier (N=3).
        self.assertEqual(normalize_category(""), "M4_Behavioral")
        self.assertEqual(normalize_category("something_unmapped"), "M4_Behavioral")

    @patch("memory_function.get_mem0_instance")
    def test_governance_fields_fire_for_llm_category_strings(self, mock_get_mem0):
        """TTL and UNVERIFIED must trigger on 'recent'/'safety', not just M6/M7."""
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        mock_mem0.search.return_value = {"results": []}
        mock_mem0.add.return_value = {"results": [{"id": "m"}]}

        process_extracted_fact("User has a supplier meeting tomorrow", "recent", "user:test")
        meta = mock_mem0.add.call_args[1]["metadata"]
        self.assertEqual(meta["category"], "M6_Recent")
        self.assertIsNotNone(meta["expires_at"])

        mock_mem0.add.reset_mock()
        process_extracted_fact("User is severely allergic to peanuts", "safety", "user:test")
        meta = mock_mem0.add.call_args[1]["metadata"]
        self.assertEqual(meta["category"], "M7_Safety")
        self.assertEqual(meta["verification_status"], "UNVERIFIED")

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
                {"memory": "Low score fact", "score": 0.15, "metadata": {"status": "active"}}
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
        # Real family names must NOT be flagged as roleplay
        self.assertFalse(is_roleplay_or_popculture_fact("User's son name is Adhyanth", "relation"))
        self.assertFalse(is_roleplay_or_popculture_fact("My son Kabir is 5 years old", "family"))

        triples = extract_graph_triples("User says I am Shaktiman and my plan is to kill Kilvish")
        self.assertEqual(triples, {"subject": "Shaktiman", "relation": "plan", "object": "defeat/kill Kilvish"})

        triples_hindi = extract_graph_triples("मेरे बेटे का नाम अध्यांत है", "family")
        self.assertEqual(triples_hindi, {"subject": "Son", "relation": "name_is", "object": "Adhyanth"})

        res = process_extracted_fact("User identifies as Shaktiman", "M4_Behavioral", "user:manish")
        args, kwargs = mock_mem0.add.call_args
        self.assertEqual(kwargs["metadata"]["status"], "active")
        self.assertEqual(kwargs["metadata"]["graph_triples"], {"subject": "User", "relation": "identifies_as", "object": "Shaktiman"})

    @patch("memory_function.get_mem0_instance")
    def test_process_session_transcript_pipeline(self, mock_get_mem0):
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        mock_mem0._extract_facts.return_value = [
            {"memory": "User prefers titanium frames", "category": "preference"},
            {"memory": "User has a doctor appointment tomorrow", "category": "recent"}
        ]
        mock_mem0.search.return_value = {"results": []}
        mock_mem0.add.return_value = {"results": [{"id": "post-session-id"}]}

        count = process_session_transcript("User: I like titanium frames. Also doc appt tomorrow.", "user:manish")
        self.assertEqual(count, 2)
        self.assertEqual(mock_mem0.add.call_count, 2)
        # Verify first item processed through normalize_category -> M3_Preference
        first_call_meta = mock_mem0.add.call_args_list[0][1]["metadata"]
        self.assertEqual(first_call_meta["category"], "M3_Preference")
        # Verify second item processed -> M6_Recent with TTL
        second_call_meta = mock_mem0.add.call_args_list[1][1]["metadata"]
        self.assertEqual(second_call_meta["category"], "M6_Recent")
        self.assertIsNotNone(second_call_meta["expires_at"])

    def test_normalize_user_id_devnagari(self):
        self.assertEqual(normalize_user_id("मनीष"), "user:manish")
        self.assertEqual(normalize_user_id("user:मनीष"), "user:manish")
        self.assertEqual(normalize_user_id("चन्द्रा"), "user:chandra")
        self.assertEqual(normalize_user_id("user:chandira"), "user:chandra")
        self.assertEqual(normalize_user_id("रोहन"), "user:rohan")

    # ── Regression: null metadata from the vector store ──────────────────
    #
    # Production crash, 2026-07-26:
    #   ERROR memory_function:save_user_memory_handler - [Mem0] Failed to
    #   save memory: 'NoneType' object has no attribute 'get'
    #
    # Every write in that session died here, so the bot could only recall
    # facts seeded before the regression. Rows written by mem0.add(...) with
    # infer=False come back from search() with metadata explicitly set to
    # None. dict.get("metadata", {}) returns None in that case -- the default
    # only applies when the key is ABSENT, not when its value is null.

    def test_find_dedupe_match_survives_null_metadata(self):
        candidates = [{"id": "m1", "score": 0.99, "memory": "User likes football", "metadata": None}]
        # Must not raise. A row with no metadata has no content_hash and no
        # category, so it can never qualify as a confident restatement.
        self.assertIsNone(find_dedupe_match(candidates, "deadbeef", "M3_Preference"))

    @patch("memory_function.get_mem0_instance")
    def test_process_extracted_fact_survives_null_metadata(self, mock_get_mem0):
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        # Exactly what AlloyDB returned in the failing session.
        mock_mem0.search.return_value = {
            "results": [
                {"id": "m1", "score": 0.91, "memory": "User's son is named Adhyanth", "metadata": None},
                {"id": "m2", "score": 0.72, "memory": "User likes strawberries"},
            ]
        }
        mock_mem0.add.return_value = {"results": [{"id": "new-id"}]}

        res = process_extracted_fact(
            "User's son likes to play football.", "preference", "user:manish", is_explicit_remember=True
        )

        # The write must land rather than blow up in the dedupe scan.
        self.assertIsNotNone(res)
        mock_mem0.add.assert_called_once()
        meta = mock_mem0.add.call_args[1]["metadata"]
        self.assertEqual(meta["category"], "M3_Preference")
        self.assertEqual(meta["status"], "active")


if __name__ == "__main__":
    unittest.main()
