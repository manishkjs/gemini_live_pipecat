"""Sync and bridge layer between Google Cloud Enterprise Memory Bank and L2 Redis / Memorystore.

Enables:
1. Copying / syncing user memories and structured facts from GCP Cloud Memory Bank to L2 Redis.
2. Fast (<1ms) user profile hydration from Redis cache during live duplex voice calls.
3. Dual-write on post-call extraction to both Cloud Memory Bank and L2 Redis.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from memory_bank import (
    GCPAgentEngineMemoryBank,
    MemoryBank,
    normalize_lexical_user_id,
)
from redis_cache import rag_cache


class MemoryRedisSyncer:
    """Manages synchronization between GCP Cloud Memory Bank and L2 Redis."""

    def __init__(self, gcp_bank: Optional[GCPAgentEngineMemoryBank] = None, cache=None):
        self.gcp_bank = gcp_bank or GCPAgentEngineMemoryBank()
        self.cache = cache or rag_cache

    async def sync_user_to_redis(self, user_id: str) -> Dict[str, Any]:
        """Fetch all facts and memories for user_id from GCP Memory Bank and store in Redis."""
        uid = normalize_lexical_user_id(user_id)
        logger.info(f"🔄 [MemoryRedisSync] Syncing memory for '{uid}' from GCP Memory Bank to L2 Redis...")

        # 1. Retrieve cloud memories from GCP Agent Engine
        cloud_memories = []
        if self.gcp_bank and self.gcp_bank.is_available():
            try:
                cloud_memories = self.gcp_bank.search_memories(
                    user_id=uid,
                    query="investment plan tenure amount risk goal KYC timeline",
                    limit=10,
                )
            except Exception as e:
                logger.error(f"[MemoryRedisSync] Error searching GCP Memory Bank for {uid}: {e}")

        # 2. Extract facts and summary
        mem_texts = [m.get("content", "") for m in cloud_memories if m.get("content")]

        sync_payload = {
            "user_id": uid,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "source": "gcp_enterprise_agent_platform_memory_bank",
            "memory_count": len(mem_texts),
            "memories": mem_texts,
        }

        # 3. Store into L1 Memory & L2 Redis
        profile_key = f"user:{uid}:profile"
        memories_key = f"user:{uid}:memories"
        facts_key = f"user:{uid}:facts"

        # Format profile summary text for the live agent
        if mem_texts:
            formatted_summary = (
                f"Returning Customer Profile ({uid}):\n"
                + "\n".join(f"- {m}" for m in mem_texts)
            )
        else:
            formatted_summary = f"New Customer Profile ({uid}): No prior investment history found."

        # Cache in Redis and L1
        await self.cache.set(profile_key, formatted_summary)
        await self.cache.set(memories_key, json.dumps(mem_texts))
        await self.cache.set(facts_key, json.dumps(sync_payload))

        logger.info(f"✅ [MemoryRedisSync] Successfully synced {len(mem_texts)} memories for '{uid}' into L2 Redis/Memorystore.")
        return sync_payload

    async def sync_all_known_users(self, user_ids: Optional[List[str]] = None) -> Dict[str, int]:
        """Sync a list of known users to Redis."""
        default_users = ["user_manish", "default_user", "manish", "user_rahul", "user_priya"]
        users_to_sync = user_ids or default_users

        results = {}
        for uid in set(users_to_sync):
            try:
                res = await self.sync_user_to_redis(uid)
                results[uid] = res.get("memory_count", 0)
            except Exception as e:
                logger.error(f"[MemoryRedisSync] Failed to sync user {uid}: {e}")
                results[uid] = -1

        return results

    async def get_user_profile(self, user_id: str) -> Optional[str]:
        """Fetch user profile in <1ms from Redis/L1; fall back to GCP Memory Bank if miss."""
        uid = normalize_lexical_user_id(user_id)
        profile_key = f"user:{uid}:profile"

        # 1. Fast Cache Hit (<1ms)
        cached_profile = await self.cache.get(profile_key)
        if cached_profile:
            logger.info(f"⚡ [MemoryRedisSync:Hit] Instant user profile retrieved from Redis/L1 for '{uid}'")
            return cached_profile

        # 2. Cache Miss: Sync from GCP Memory Bank and cache
        logger.info(f"[MemoryRedisSync:Miss] Hydrating '{uid}' from GCP Cloud Memory Bank...")
        await self.sync_user_to_redis(uid)
        return await self.cache.get(profile_key)


# Global syncer instance
memory_redis_syncer = MemoryRedisSyncer()


if __name__ == "__main__":
    import sys
    async def main():
        syncer = MemoryRedisSyncer()
        users = sys.argv[1:] if len(sys.argv) > 1 else ["user_manish", "default_user", "manish"]
        logger.info(f"🚀 Running manual GCP Memory Bank -> L2 Redis sync for users: {users}")
        res = await syncer.sync_all_known_users(users)
        print("\n--- Sync Summary ---")
        for u, count in res.items():
            print(f"User: {u} -> Synced {count} memories")

    asyncio.run(main())
