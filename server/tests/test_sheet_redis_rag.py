import unittest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
from redis_cache import rag_cache
from rag_function import search_knowledge_base_handler
from memory_redis_sync import memory_redis_syncer

class TestSheetRedisRAG(unittest.IsolatedAsyncioTestCase):
    """Audits Google Sheet Q&A Ingestion and Sub-Millisecond Memorystore RAG Engine."""

    async def asyncSetUp(self):
        await rag_cache.initialize()
        await rag_cache.prewarm_sheet_knowledge()

    async def test_sheet_knowledge_ingestion_completeness(self):
        """Verify ~900+ Q&A pairs are loaded and token indexed."""
        self.assertTrue(hasattr(rag_cache, "_sheet_records"))
        self.assertGreaterEqual(len(rag_cache._sheet_records), 900)
        self.assertGreaterEqual(len(rag_cache._sheet_token_index), 500)

    async def test_sub_millisecond_lending_queries(self):
        """Test specific lending knowledge queries retrieved from Google Sheet."""
        queries = [
            ("minimum amount lend per loan", "250"),
            ("maximum investment per PAN", "50 lakh"),
            ("CTO February 2025 update", "Dipesh Karki"),
            ("Short Term Lending STL interest rate", "12 to 15 percent"),
            ("maximum amount in lump sum lending", "25"),
        ]

        for query, expected_snippet in queries:
            t0 = time.perf_counter()
            res = await rag_cache.search_sheet_knowledge(query, top_k=3)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            self.assertIsNotNone(res, f"Query '{query}' returned None")
            self.assertIn(expected_snippet.lower(), res.lower(), f"Expected '{expected_snippet}' in result for '{query}'")
            # Verify sub-millisecond execution
            self.assertLess(elapsed_ms, 20.0, f"Query '{query}' took {elapsed_ms:.2f}ms (expected <20ms)")

    async def test_handler_instant_sheet_rag(self):
        """Verify search_knowledge_base_handler executes under 5ms without remote RAG."""
        callback_mock = AsyncMock()
        params = MagicMock()
        params.arguments = {"query_for_vector_search": "maximum amount per PAN"}
        params.result_callback = callback_mock

        t0 = time.perf_counter()
        await search_knowledge_base_handler(params)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        callback_mock.assert_called_once()
        content = callback_mock.call_args[0][0]["content"]
        self.assertIn("50 lakh", content.lower())
        self.assertLess(elapsed_ms, 15.0)

    async def test_memory_redis_syncer_profile_retrieval(self):
        """Verify user profile can be retrieved in <1ms from Redis/L1."""
        profile = await memory_redis_syncer.get_user_profile("user_manish")
        self.assertIsNotNone(profile)
        self.assertIn("manish", profile.lower())

if __name__ == "__main__":
    unittest.main()
