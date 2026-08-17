import asyncio
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

# Stop words and conversational filler words for English and Hindi / Hinglish queries
STOP_WORDS: Set[str] = {
    "kya", "hai", "mujhe", "batao", "batayein", "bataiye", "bata", "sakte", "ho", "hoga",
    "ka", "ki", "ke", "ko", "mein", "par", "se", "aur", "toh", "karo", "karenge",
    "what", "is", "the", "tell", "me", "about", "how", "can", "i", "get", "do", "you", "have", "please",
    "in", "on", "at", "to", "for", "of", "with", "a", "an", "and", "or", "are", "your", "from"
}


def tokenize_text(text: Any) -> List[str]:
    """Tokenize text into cleaned semantic tokens with currency normalization."""
    if text is None:
        return []
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        return []
    t = text.lower()
    # Normalize currency representations
    t = t.replace("₹", " rs rupees inr ")
    # Replace curly quotes and unicode dashes
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-")
    # Extract alphanumeric words: preserve single-digit numbers (0-9) and alphanumeric words >= 1 char if not stop words
    tokens = [w for w in re.findall(r"[a-zA-Z0-9]+", t) if (len(w) > 1 or w.isdigit()) and w not in STOP_WORDS]
    return tokens


class RedisRAGCache:
    """High-speed Dual-Layer (L1 In-Memory + L2 Memorystore/Redis) Caching & BM25 Engine."""

    def __init__(self, redis_url: Optional[str] = None, default_ttl_seconds: int = 86400):
        # Resolve Google Cloud Memorystore or Redis connection parameters
        host = os.getenv("MEMORYSTORE_HOST") or os.getenv("REDIS_HOST") or "10.198.162.203"
        port = os.getenv("MEMORYSTORE_PORT") or os.getenv("REDIS_PORT") or "6379"
        auth = os.getenv("MEMORYSTORE_AUTH") or os.getenv("REDIS_PASSWORD") or os.getenv("REDIS_AUTH")
        use_tls = os.getenv("MEMORYSTORE_TLS", "false").lower() in ("true", "1") or os.getenv("REDIS_TLS", "false").lower() in ("true", "1")

        if redis_url:
            self.redis_url = redis_url
        elif os.getenv("REDIS_URL"):
            self.redis_url = os.getenv("REDIS_URL")
        elif host:
            scheme = "rediss" if use_tls else "redis"
            auth_part = f":{auth}@" if auth else ""
            self.redis_url = f"{scheme}://{auth_part}{host}:{port}/0"
        else:
            self.redis_url = "redis://10.198.162.203:6379/0"

        self.default_ttl_seconds = default_ttl_seconds
        self.redis_client: Optional[Any] = None
        self.is_connected = False

        # L1 in-memory caches and BM25 indexing structures
        self._l1_cache: Dict[str, str] = {}
        self._sheet_records: List[Dict[str, Any]] = []
        self._sheet_token_index: Dict[str, Set[int]] = defaultdict(set)
        self._doc_tokens_q: List[Counter] = []
        self._doc_tokens_c: List[Counter] = []
        self._doc_tokens_a: List[Counter] = []
        self._doc_lengths: List[float] = []
        self._avg_dl: float = 1.0
        self._idf: Dict[str, float] = {}
        self._is_prewarmed = False

    async def initialize(self) -> bool:
        """Asynchronously connect to Google Cloud Memorystore / Redis instance with graceful fallback."""
        if not aioredis:
            logger.warning("[RedisCache] redis-py is not installed. Operating in high-speed L1 In-Memory mode.")
            self.is_connected = False
            return False

        try:
            self.redis_client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=0.4,
                socket_connect_timeout=0.4,
            )
            # Ping test with short timeout
            await asyncio.wait_for(self.redis_client.ping(), timeout=0.5)
            self.is_connected = True
            logger.info(f"☁️🔴 [Memorystore:Redis] Connected successfully to instance at {self.redis_url}")
            return True
        except Exception as e:
            self.is_connected = False
            logger.warning(
                f"☁️🔴 [Memorystore:Redis] Memorystore instance not reachable at {self.redis_url} ({e}). "
                "Operating in high-speed L1 In-Memory mode (<0.01ms)."
            )
            return False

    def normalize_query(self, query: Any) -> str:
        """Normalize conversational queries to extract deterministic semantic intent tokens."""
        if not query:
            return ""
        tokens = tokenize_text(query)
        tokens.sort()
        return " ".join(tokens)

    def _get_key(self, query: Any) -> str:
        """Generate normalized hash key for dual-layer caching."""
        normalized = self.normalize_query(query)
        if not normalized:
            normalized = str(query).lower().strip() if query is not None else ""
        hash_val = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return f"cymbal:sheet_rag:query:{hash_val}"

    async def get(self, query: Any) -> Optional[str]:
        """Fetch cached answer from L1 Memory (<0.01ms) or L2 Redis (<1ms)."""
        if not query:
            return None

        key = self._get_key(query)

        # 1. L1 In-Memory Cache Lookup (<0.01ms)
        if key in self._l1_cache:
            return self._l1_cache[key]

        # Check legacy key fallback in L1
        legacy_key = f"cymbal:rag:{hashlib.sha256(self.normalize_query(query).encode('utf-8')).hexdigest()[:16]}"
        if legacy_key in self._l1_cache:
            return self._l1_cache[legacy_key]

        # 2. L2 Redis Lookup (<1ms)
        if self.is_connected and self.redis_client:
            try:
                res = await asyncio.wait_for(self.redis_client.get(key), timeout=0.1)
                if res:
                    self._l1_cache[key] = res
                    return res
                # Check legacy key in Redis
                res_legacy = await asyncio.wait_for(self.redis_client.get(legacy_key), timeout=0.1)
                if res_legacy:
                    self._l1_cache[key] = res_legacy
                    return res_legacy
            except Exception as e:
                logger.debug(f"[RedisCache] Redis get error: {e}")

        return None

    async def set(self, query: Any, content: str, ttl: Optional[int] = None) -> None:
        """Store result in both L1 Memory and L2 Redis."""
        if not query or not content:
            return

        key = self._get_key(query)
        ttl = ttl or self.default_ttl_seconds

        # Store in L1 In-Memory
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

    async def prewarm_sheet_knowledge(self, json_path: Optional[str] = None) -> int:
        """Load, BM25 index, and pre-warm Google Sheet Q&A dataset into L1/L2 Redis."""
        path = json_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sheet_knowledge.json")
        if not os.path.exists(path):
            logger.warning(f"[RedisCache] Sheet knowledge JSON not found at {path}")
            return 0

        try:
            with open(path, "r", encoding="utf-8") as f:
                records = json.load(f)

            # Filter out any lingering header row if present
            if records and records[0].get("question") == "Questions":
                records = records[1:]

            self._sheet_records = records
            total_n = len(records)

            self._doc_tokens_q = []
            self._doc_tokens_c = []
            self._doc_tokens_a = []
            self._doc_lengths = []
            self._sheet_token_index = defaultdict(set)

            # Build BM25 document counters and inverted index
            for idx, r in enumerate(records):
                t_q = tokenize_text(r.get("question", ""))
                t_c = tokenize_text(f"{r.get('category', '')} {r.get('subcategory', '')}")
                t_a = tokenize_text(r.get("answer", ""))

                self._doc_tokens_q.append(Counter(t_q))
                self._doc_tokens_c.append(Counter(t_c))
                self._doc_tokens_a.append(Counter(t_a))

                # Field weighted document length (Question=3.0, Cat=1.8, Answer=1.0)
                dl = len(t_q) * 3.0 + len(t_c) * 1.8 + len(t_a) * 1.0
                self._doc_lengths.append(dl)

                all_doc_tokens = set(t_q + t_c + t_a)
                for t in all_doc_tokens:
                    self._sheet_token_index[t].add(idx)

            self._avg_dl = sum(self._doc_lengths) / total_n if total_n > 0 else 1.0

            # Precalculate IDF for all tokens: ln(1 + (N - n(t) + 0.5) / (n(t) + 0.5))
            self._idf = {}
            for token, doc_ids in self._sheet_token_index.items():
                df = len(doc_ids)
                self._idf[token] = max(0.1, math.log(1.0 + (total_n - df + 0.5) / (df + 0.5)))

            # Populate top 250 frequent query keys into L1 and L2
            pipe = None
            if self.is_connected and self.redis_client:
                try:
                    pipe = self.redis_client.pipeline()
                    # Store dataset metadata
                    pipe.hset(
                        "cymbal:sheet_rag:meta",
                        mapping={
                            "total_docs": str(total_n),
                            "version": "1.0",
                            "last_synced_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    # Store documents in Redis
                    for r in records:
                        doc_key = f"cymbal:sheet_rag:doc:{r['id']}"
                        pipe.set(doc_key, json.dumps(r, ensure_ascii=False))
                    # Store token postings in Redis
                    for t, doc_ids in self._sheet_token_index.items():
                        token_key = f"cymbal:sheet_rag:token:{t}"
                        pipe.sadd(token_key, *list(doc_ids))
                except Exception as e:
                    logger.debug(f"[RedisCache] Redis pipeline prep error: {e}")
                    pipe = None

            for idx, r in enumerate(records[:250]):
                q = r.get("question", "")
                a = r.get("answer", "")
                cat = r.get("category", "General")
                formatted_1 = f"1. Q: {q}\nA: {a} (Category: {cat})"
                # Pre-warm query cache in L1 for direct question and topk1
                await self.set(f"{q}:topk:1", formatted_1)
                await self.set(q, a)

            if pipe:
                try:
                    await pipe.execute()
                except Exception as e:
                    logger.debug(f"[RedisCache] Redis pipeline execution error: {e}")

            self._is_prewarmed = True
            logger.info(
                f"⚡ [RedisCache] Pre-warmed & BM25-indexed {total_n} Google Sheet Q&A pairs "
                f"({len(self._sheet_token_index)} tokens) into Memorystore/L1 RAM."
            )
            return total_n
        except Exception as e:
            logger.error(f"[RedisCache] Error prewarming sheet knowledge: {e}")
            return 0

    async def search_sheet_knowledge(self, query: str, top_k: int = 3) -> str:
        """Sub-millisecond token-ranked BM25 search over Google Sheet Q&A dataset."""
        # Coerce top_k safely to integer between 1 and 10
        try:
            top_k = max(1, min(10, int(top_k)))
        except (ValueError, TypeError):
            top_k = 3

        if not self._is_prewarmed or not self._sheet_records:
            await self.prewarm_sheet_knowledge()

        if not self._sheet_records:
            return ""

        query_clean = str(query).strip() if query is not None else ""
        if not query_clean:
            return ""

        # 1. Exact query cache lookup with top_k dimension (<0.01ms)
        cache_query_key = f"{query_clean}:topk:{top_k}"
        cached_result = await self.get(cache_query_key)
        if cached_result:
            return cached_result

        q_tokens = tokenize_text(query_clean)
        if not q_tokens:
            return ""

        # 2. Retrieve candidate document IDs from inverted index
        candidate_doc_ids: Set[int] = set()
        for t in q_tokens:
            if t in self._sheet_token_index:
                candidate_doc_ids.update(self._sheet_token_index[t])

        if not candidate_doc_ids:
            return ""

        # 3. Field-Weighted BM25 Scoring
        # Parameters: k1 = 1.5, b = 0.75
        # Field Weights: Question = 3.0, Category = 1.8, Answer = 1.0
        # Exact Phrase Boost: +15.0 for Question match, +5.0 for Answer match
        k1 = 1.5
        b = 0.75
        scores: Dict[int, float] = {}
        q_raw_clean = query_clean.lower().replace("₹", "rs ").strip()

        for doc_id in candidate_doc_ids:
            rec = self._sheet_records[doc_id]
            dl = self._doc_lengths[doc_id]
            tf_q = self._doc_tokens_q[doc_id]
            tf_c = self._doc_tokens_c[doc_id]
            tf_a = self._doc_tokens_a[doc_id]

            score = 0.0
            for t in q_tokens:
                token_idf = self._idf.get(t, 0.1)
                # Field weighted TF
                tf_weighted = 3.0 * tf_q.get(t, 0) + 1.8 * tf_c.get(t, 0) + 1.0 * tf_a.get(t, 0)
                if tf_weighted > 0:
                    tf_component = (tf_weighted * (k1 + 1.0)) / (tf_weighted + k1 * (1.0 - b + b * (dl / self._avg_dl)))
                    score += token_idf * tf_component

            # Exact phrase substring bonus
            q_text = rec.get("question", "").lower().replace("₹", "rs ")
            a_text = rec.get("answer", "").lower().replace("₹", "rs ")

            if q_raw_clean and q_raw_clean in q_text:
                score += 15.0
            elif any(part in q_text for part in q_raw_clean.split("?") if len(part.strip()) > 6):
                score += 6.0

            if q_raw_clean and q_raw_clean in a_text:
                score += 5.0

            scores[doc_id] = score

        if not scores:
            return ""

        sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        results: List[str] = []
        for doc_id, score in sorted_docs:
            rec = self._sheet_records[doc_id]
            q = rec.get("question", "")
            a = rec.get("answer", "")
            cat = rec.get("category", "General")
            subcat = rec.get("subcategory", "")
            cat_display = f"{cat} - {subcat}" if subcat else cat
            results.append(f"Q: {q}\nA: {a} (Category: {cat_display})")

        formatted_result = "\n\n".join(f"{i}. {r}" for i, r in enumerate(results, 1))

        # Cache in L1 and L2
        await self.set(cache_query_key, formatted_result)
        return formatted_result


# Global cache singleton
rag_cache = RedisRAGCache()
