import asyncio
import hashlib
import os
import re
from typing import Optional, Dict, Any
from loguru import logger

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None


class RedisRAGCache:
    """High-speed Dual-Layer (L1 In-Memory + L2 Redis) Caching Engine for Voice RAG."""

    def __init__(self, redis_url: Optional[str] = None, default_ttl_seconds: int = 86400):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.default_ttl_seconds = default_ttl_seconds
        self.redis_client: Optional[Any] = None
        self.is_connected = False
        self._l1_cache: Dict[str, str] = {}
        self._init_task: Optional[asyncio.Task] = None

    async def initialize(self) -> bool:
        """Asynchronously connect to Redis and verify connection."""
        if not aioredis:
            logger.warning("[RedisCache] redis-py is not installed. Using In-Memory L1 Cache.")
            return False

        try:
            self.redis_client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
            )
            # Ping test with short timeout
            await asyncio.wait_for(self.redis_client.ping(), timeout=0.6)
            self.is_connected = True
            logger.info(f"🔴 [RedisCache] Connected to Redis instance at {self.redis_url}")
            return True
        except Exception as e:
            self.is_connected = False
            logger.warning(f"[RedisCache] Redis not reachable ({e}). Operating in high-speed L1 In-Memory mode.")
            return False

    def normalize_query(self, query: str) -> str:
        """Normalize conversational queries to extract semantic intent keywords."""
        if not query:
            return ""
        q = query.lower().strip()
        # Remove punctuation
        q = re.sub(r"[^\w\s\d]", " ", q)
        # Strip common English and Hindi stop/filler words
        stop_words = {
            "kya", "hai", "mujhe", "batao", "batayein", "bataiye", "bata", "sakte", "ho", "hoga",
            "ka", "ki", "ke", "ko", "mein", "par", "se", "aur", "toh", "karo", "karenge",
            "what", "is", "the", "tell", "me", "about", "how", "can", "i", "get", "do", "you", "have", "please"
        }
        tokens = [w for w in q.split() if w not in stop_words and len(w) > 1]
        tokens.sort()
        return " ".join(tokens)

    def _get_key(self, query: str) -> str:
        normalized = self.normalize_query(query)
        hash_val = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return f"cymbal:rag:{hash_val}"

    async def get(self, query: str) -> Optional[str]:
        """Fetch cached answer from L1 Memory (<0.01ms) or L2 Redis (<1ms)."""
        key = self._get_key(query)
        if not key:
            return None

        # 1. L1 In-Memory Cache Lookup (<0.01ms)
        if key in self._l1_cache:
            return self._l1_cache[key]

        # 2. L2 Redis Lookup (<1ms)
        if self.is_connected and self.redis_client:
            try:
                res = await asyncio.wait_for(self.redis_client.get(key), timeout=0.1)
                if res:
                    self._l1_cache[key] = res
                    return res
            except Exception as e:
                logger.debug(f"[RedisCache] Redis get error: {e}")

        return None

    async def set(self, query: str, content: str, ttl: Optional[int] = None) -> None:
        """Store result in both L1 Memory and L2 Redis."""
        key = self._get_key(query)
        if not key or not content:
            return

        ttl = ttl or self.default_ttl_seconds

        # Store in L1
        self._l1_cache[key] = content

        # Store in L2 Redis
        if self.is_connected and self.redis_client:
            try:
                await self.redis_client.set(key, content, ex=ttl)
            except Exception as e:
                logger.debug(f"[RedisCache] Redis set error: {e}")

    async def prewarm(self, canonical_data: Dict[str, str]) -> int:
        """Pre-warm Redis and L1 cache with canonical domain knowledge."""
        count = 0
        for topic_key, content in canonical_data.items():
            await self.set(topic_key, content)
            count += 1
        logger.info(f"⚡ [RedisCache] Pre-warmed {count} canonical knowledge topics into cache.")
        return count


# Global cache singleton
rag_cache = RedisRAGCache()
