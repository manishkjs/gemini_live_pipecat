import os
import sys
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock

_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from redis_cache import RedisRAGCache
from rag_function import search_knowledge_base_handler

class TestRedisRAGCache(unittest.IsolatedAsyncioTestCase):
    """Audits Redis and L1 in-memory caching engine."""

    async def test_normalization_and_key_generation(self):
        cache = RedisRAGCache()
        norm1 = cache.normalize_query("TDS kitna katega Form 26AS par?")
        norm2 = cache.normalize_query("What is the TDS and Form 26AS?")
        self.assertIn("tds", norm1)
        self.assertIn("26as", norm1)
        self.assertIn("tds", norm2)
        self.assertIn("26as", norm2)

    async def test_l1_in_memory_get_and_set(self):
        cache = RedisRAGCache()
        await cache.set("rbi safety", "Cymbal Lending is RBI registered.")
        res = await cache.get("rbi safety")
        self.assertEqual(res, "Cymbal Lending is RBI registered.")

    async def test_prewarming_sheet_knowledge(self):
        cache = RedisRAGCache()
        count = await cache.prewarm_sheet_knowledge()
        self.assertGreater(count, 0)
        
        # Verify direct hit
        res = await cache.search_sheet_knowledge("minimum amount to lend")
        self.assertIsNotNone(res)
        self.assertTrue("250" in res or "Rupees 250" in res or "₹250" in res)

    async def test_l2_write_async_enabled_spawns_background_task(self):
        """Verify L2 Redis writeback executes via non-blocking background task when async is enabled."""
        cache = RedisRAGCache()
        cache.l2_write_async = True
        cache.is_connected = True
        mock_redis = AsyncMock()
        cache.redis_client = mock_redis

        await cache.set("async_key", "async_value")

        # L1 cache must be populated immediately
        key = cache._get_key("async_key")
        self.assertEqual(cache._l1_cache[key], "async_value")

        # Yield to event loop to allow background task to complete
        await asyncio.sleep(0.01)
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        self.assertEqual(call_args[0][0], key)
        self.assertEqual(call_args[0][1], "async_value")

    async def test_l2_write_sync_when_async_disabled(self):
        """Verify L2 Redis writeback executes synchronously when RAG_L2_WRITE_ASYNC is disabled."""
        cache = RedisRAGCache()
        cache.l2_write_async = False
        cache.is_connected = True
        mock_redis = AsyncMock()
        cache.redis_client = mock_redis

        await cache.set("sync_key", "sync_value")

        key = cache._get_key("sync_key")
        self.assertEqual(cache._l1_cache[key], "sync_value")
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        self.assertEqual(call_args[0][0], key)
        self.assertEqual(call_args[0][1], "sync_value")

    async def test_prenormalized_string_arrays_populated(self):
        """Verify _doc_q_clean and _doc_a_clean are pre-computed during startup pre-warming."""
        cache = RedisRAGCache()
        count = await cache.prewarm_sheet_knowledge()
        self.assertGreater(count, 0)
        self.assertEqual(len(cache._doc_q_clean), len(cache._sheet_records))
        self.assertEqual(len(cache._doc_a_clean), len(cache._sheet_records))
        for q_clean in cache._doc_q_clean:
            self.assertNotIn("₹", q_clean)
        for a_clean in cache._doc_a_clean:
            self.assertNotIn("₹", a_clean)

    async def test_handler_single_lookup_delegation_no_redundant_outer_cache_calls(self):
        """Verify search_knowledge_base_handler delegates directly to search_sheet_knowledge without outer cache get/set."""
        from unittest.mock import patch
        import rag_function

        callback_mock = AsyncMock()
        params = MagicMock()
        params.arguments = {"query_for_vector_search": "test query delegation", "total_records": 3}
        params.result_callback = callback_mock

        with patch.object(rag_function.rag_cache, "search_sheet_knowledge", new_callable=AsyncMock) as mock_search, \
             patch.object(rag_function.rag_cache, "get", new_callable=AsyncMock) as mock_get, \
             patch.object(rag_function.rag_cache, "set", new_callable=AsyncMock) as mock_set:

            mock_search.return_value = "Delegated Result Match"
            await search_knowledge_base_handler(params)

            # Outer get and set must NOT be called
            mock_get.assert_not_called()
            mock_set.assert_not_called()

            # Direct search_sheet_knowledge must be called
            mock_search.assert_called_once_with("test query delegation", top_k=3)
            callback_mock.assert_called_once_with({"content": "Delegated Result Match"})


if __name__ == "__main__":
    unittest.main()
