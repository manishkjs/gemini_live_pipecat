import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from redis_cache import RedisRAGCache
from rag_function import CANONICAL_DOMAIN_KNOWLEDGE, search_knowledge_base_handler

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

    async def test_prewarming_canonical_knowledge(self):
        cache = RedisRAGCache()
        count = await cache.prewarm(CANONICAL_DOMAIN_KNOWLEDGE)
        self.assertGreaterEqual(count, 8)
        
        # Verify direct hit
        rbi_val = await cache.get("rbi")
        self.assertIsNotNone(rbi_val)
        self.assertIn("RBI-registered NBFC-P2P", rbi_val)

    async def test_handler_instant_cache_hit(self):
        cache = RedisRAGCache()
        await cache.prewarm(CANONICAL_DOMAIN_KNOWLEDGE)
        
        callback_mock = AsyncMock()
        params = MagicMock()
        params.arguments = {"query_for_vector_search": "rbi compliance"}
        params.result_callback = callback_mock
        
        # Test handler execution
        await search_knowledge_base_handler(params)
        callback_mock.assert_called_once()
        content = callback_mock.call_args[0][0]["content"]
        self.assertIn("RBI-registered", content)

if __name__ == "__main__":
    unittest.main()
