"""Gemini Enterprise Agent Memory Bank Engine & Lexical Identity Resolver.

Provides:
1. `normalize_lexical_user_id(raw_name: str) -> str`:
   Deterministic normalization of spoken/conversational customer names into canonical user keys
   (e.g., 'Aditya Sharma' -> 'user_aditya_sharma', 'Mr. Rajesh Kumar' -> 'user_rajesh_kumar',
   'Mera naam Priya Patel hai' -> 'user_priya_patel').
2. `FactStore`:
   Structured fact store tracking the 8 canonical financial keys:
   `amount`, `tenure_months`, `risk_preference`, `timeline`, `goal`, `occupation`, `city`, `experience`.
   Maintains turn-by-turn change history audit trail, tracks hypothetical vs confirmed values,
   and enforces 6-turn TTL for hypothetical exploration parameters.
3. `MemoryBank`:
   In-memory vector similarity engine with dual-threshold logic:
   - 0.83 Deduplication threshold (updates existing record in place).
   - 0.40 Retrieval threshold (returns relevant episodic memories).
   - MD5 content hash idempotency.
   - 90-day cross-session profile hydration combining structured facts and episodic memories.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("memory_bank")

try:
    import agentplatform
except ImportError:
    agentplatform = None


# ═══════════════════════════════════════════════════════════════════════
# 1. CANONICAL CONSTANTS & CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

CANONICAL_FACT_KEYS: Set[str] = {
    "amount",
    "tenure_months",
    "risk_preference",
    "timeline",
    "goal",
    "occupation",
    "city",
    "experience",
}

KEY_ALIASES: Dict[str, str] = {
    "tenure": "tenure_months",
    "tenure_month": "tenure_months",
    "months": "tenure_months",
    "risk": "risk_preference",
    "risk_appetite": "risk_preference",
    "location": "city",
    "profession": "occupation",
    "job": "occupation",
    "inv_experience": "experience",
    "horizon": "timeline",
    "investment_goal": "goal",
}

HYPOTHETICAL_TTL_TURNS: int = 6
DEDUPLICATION_THRESHOLD: float = 0.83
RETRIEVAL_THRESHOLD: float = 0.40
DEFAULT_HYDRATION_LOOKBACK_DAYS: int = 90


# ═══════════════════════════════════════════════════════════════════════
# 2. LEXICAL USER ID NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════

HINDI_NAME_MAP = {
    "मनीष": "manish", "आदित्य": "aditya", "शर्मा": "sharma", "राजेश": "rajesh",
    "कुमार": "kumar", "प्रिया": "priya", "पटेल": "patel", "अमित": "amit",
    "रोहित": "rohit", "सुनील": "sunil", "दीपक": "deepak", "राहुल": "rahul",
    "विकास": "vikas", "संजय": "sanjay", "विजय": "vijay", "अजय": "ajay",
    "विक्रम": "vikram", "सिंह": "singh", "गुप्ता": "gupta", "वर्मा": "verma",
    "सुनीता": "sunita", "राव": "rao", "अंजलि": "anjali", "पूजा": "pooja", "नेहा": "neha",
    "अद्यांत": "adyant", "अद्वैत": "advait", "आर्यन": "aryan", "अभिषेक": "abhishek"
}


def get_existing_user_ids(memory_bank: Optional[Any] = None) -> List[str]:
    """Retrieves all existing registered user IDs exclusively from GCP Cloud Memory Bank."""
    mb = memory_bank or globals().get("_GLOBAL_MEMORY_BANK")
    if mb and hasattr(mb, "cloud_bank") and mb.cloud_bank and mb.cloud_bank.is_available():
        try:
            uids = mb.cloud_bank.get_all_user_ids()
            if uids:
                return uids
        except Exception:
            pass
    elif mb and hasattr(mb, "get_all_user_ids"):
        try:
            uids = mb.get_all_user_ids()
            if uids:
                return uids
        except Exception:
            pass

    # Direct agentplatform client query if memory bank instance not passed
    if agentplatform and os.getenv("GCP_AGENT_ENGINE_ID"):
        try:
            project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT", "deep-clock-339817")
            location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
            engine_id = os.getenv("GCP_AGENT_ENGINE_ID")
            client = agentplatform.Client(project=project_id, location=location)
            mems = list(client.agent_engines.memories.list(name=engine_id))
            uids = set()
            for m in mems:
                scope = getattr(m, "scope", None) or {}
                if isinstance(scope, dict) and "user_id" in scope:
                    uids.add(scope["user_id"])
            return [u for u in uids if u and u not in ("user_anonymous", "default_user")]
        except Exception:
            pass
    return []


def match_closest_existing_user_id(
    utterance: str,
    memory_bank: Optional[Any] = None,
    threshold: float = 0.5,
) -> Optional[str]:
    """Polls existing user IDs in memory and maps utterance to closest registered user lexically."""
    if not utterance or not isinstance(utterance, str) or not utterance.strip():
        return None

    existing_uids = get_existing_user_ids(memory_bank=memory_bank)
    if not existing_uids:
        return None

    text = utterance.lower()
    for h, l in HINDI_NAME_MAP.items():
        if h in utterance:
            text = text + " " + l

    best_uid = None
    best_score = 0.0

    for uid in existing_uids:
        raw_uid_name = uid.replace("user_", "").replace("_", " ").strip()
        uid_tokens = [tok for tok in raw_uid_name.split() if tok]
        if not uid_tokens:
            continue

        first_name = uid_tokens[0]
        # Match on first name or full name
        if first_name in text or difflib.get_close_matches(first_name, text.split(), cutoff=0.75):
            score = 0.85
            if len(uid_tokens) > 1 and all(tok in text for tok in uid_tokens):
                score = 1.0
        else:
            score = difflib.SequenceMatcher(None, raw_uid_name, text).ratio()

        if score > best_score:
            best_score = score
            best_uid = uid

    if best_score >= threshold and best_uid:
        return best_uid
    return None


def normalize_lexical_user_id(raw_name: Optional[str], memory_bank: Optional[Any] = None) -> str:
    """Normalizes spoken customer names into deterministic, sanitized keys.

    First checks against existing registered users in memory for closest lexical match.
    If no existing user matches, sanitizes into new canonical 'user_<name>' key.

    Examples:
        "Aditya Sharma" -> "user_aditya_sharma"
        "Mr. Rajesh Kumar" -> "user_rajesh_kumar"
        "Mera naam Priya Patel hai" -> "user_priya_patel"
        "अम हां, मेरे पास समय है। मेरा नाम मनीष है।" -> "user_manish_kumar" (if exists) or "user_manish"
        "Dr. Vikram Singh ji" -> "user_vikram_singh"
        "Namaste, main Deepak bol raha hoon" -> "user_deepak"
        "" -> "user_anonymous"
        None -> "user_anonymous"

    Args:
        raw_name: Raw input string containing customer name or spoken introduction.
        memory_bank: Optional MemoryBank instance to poll existing users from.

    Returns:
        Deterministic normalized user ID string prefixed with 'user_'.
    """
    if raw_name is None or not isinstance(raw_name, str):
        return "user_anonymous"

    text = raw_name.strip()
    if not text:
        return "user_anonymous"

    # 0. Poll existing user IDs in memory and map to closest registered user
    existing_match = match_closest_existing_user_id(text, memory_bank=memory_bank)
    if existing_match:
        return existing_match

    # 1. Map known Devanagari words to Latin transliterations for standalone names
    for hindi_tok, latin_tok in HINDI_NAME_MAP.items():
        if hindi_tok in text:
            text = text.replace(hindi_tok, f" {latin_tok} ")

    # Lowercase for uniform processing
    text = text.lower()

    # 2. Strip conversational introductory and framing phrases (ordered longest first)
    conversational_patterns = [
        r"\b(?:namaste|namaskar|hello|hi|hey|pranam)\b",
        r"\baap\s+baat\s+kar\s+rahe\s+hain\b",
        r"\byou\s+are\s+talking\s+to\b",
        r"\bmera\s+naam\s+hai\b",
        r"\bmera\s+naam\b",
        r"\bmy\s+name\s+is\b",
        r"\bthis\s+is\b",
        r"\bi\s+am\b",
        r"\bi\'m\b",
        r"\bcall\s+me\b",
        r"\bmain\s+hoon\b",
        r"\bbaat\s+kar\s+raha\s+hoon\b",
        r"\bbaat\s+kar\s+rahi\s+hoon\b",
        r"\bbol\s+raha\s+hoon\b",
        r"\bbol\s+rahi\s+hoon\b",
        r"\bbaat\s+kar\s+rahe\s+hain\b",
        r"\bspeaking\b",
        r"\bhaan\s+ji\b",
        r"\bhaan\b",
        r"\bmain\b",
        r"\bhai\b",
        r"\bhoon\b",
        r"\bse\b",
    ]
    for pattern in conversational_patterns:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    # 3. Strip honorifics & titles (prefixes and suffixes)
    honorific_patterns = [
        r"\b(?:mr|mrs|ms|miss|dr|prof|sir|madam|esq)(?:\.|\b)",
        r"\b(?:shri|shree|smt|shrimati|kumari)(?:\.|\b)",
        r"\b(?:ji|jee|sahab|saab)\b",
        r"(?:डॉक्टर|डॉ|श्री|श्रीमती|सुश्री|कुमारी|प्रोफेसर|जी|साहब|साहब|सर|मैडम)(?:\.|\b)?",
    ]
    for pattern in honorific_patterns:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    # 4. Strip existing 'user_' prefix if already present
    text = re.sub(r"^user[_\-\s]+", " ", text, flags=re.IGNORECASE)

    # 5. Remove all non-alphanumeric characters (keep ASCII letters and digits)
    text = re.sub(r"[^a-z0-9\s_\-]", " ", text)

    # 6. Collapse multiple spaces/hyphens/underscores into single underscores
    tokens = [tok for tok in re.split(r"[\s_\-]+", text) if tok]

    # 7. Filter filler tokens
    filler_tokens = {
        "dr", "smt", "mr", "mrs", "ms", "miss", "prof", "shri", "shree",
        "shrimati", "kumari", "sir", "madam", "esq", "ji", "jee", "sahab",
        "saab", "hai", "hoon", "main", "haan", "speaking"
    }
    filtered = [tok for tok in tokens if tok not in filler_tokens]
    if filtered:
        tokens = filtered

    if not tokens or tokens == ["anonymous"]:
        return "user_anonymous"

    cleaned = "_".join(tokens)
    return f"user_{cleaned}"


# ═══════════════════════════════════════════════════════════════════════
# 3. STRUCTURED FACT STORE
# ═══════════════════════════════════════════════════════════════════════

class FactStore:
    """Tracks structured financial facts with turn-by-turn audit history and 6-turn TTL.

    The 8 canonical financial keys:
    - amount: Loan/investment principal in Rupees.
    - tenure_months: Duration in months.
    - risk_preference: Risk category (e.g. low, moderate, high).
    - timeline: Investment horizon.
    - goal: Financial goal (e.g. retirement, child education).
    - occupation: Employment/business type.
    - city: Investor location.
    - experience: P2P/investing experience.
    """

    def __init__(self, canonical_keys: Optional[Set[str]] = None, ttl_turns: int = HYPOTHETICAL_TTL_TURNS):
        self._canonical_keys = set(canonical_keys or CANONICAL_FACT_KEYS)
        self._ttl_turns = ttl_turns
        self._facts: Dict[str, Any] = {}
        self._hypothetical_meta: Dict[str, Dict[str, Any]] = {}
        self._history: List[Dict[str, Any]] = []

    def _normalize_key(self, key: str) -> str:
        """Normalizes and validates key against canonical keys and known aliases."""
        if not key or not isinstance(key, str):
            raise ValueError(f"Fact key must be a non-empty string, got: {key!r}")
        normalized = key.strip().lower()
        if normalized in KEY_ALIASES:
            normalized = KEY_ALIASES[normalized]
        if normalized not in self._canonical_keys:
            raise ValueError(
                f"Invalid fact key '{key}'. Allowed canonical keys: {sorted(self._canonical_keys)}"
            )
        return normalized

    def set_fact(
        self,
        key: str,
        value: Any,
        turn_id: int,
        is_hypothetical: bool = False,
    ) -> None:
        """Sets a structured fact value and records the change in history.

        Args:
            key: Fact key (must be one of the canonical 8 keys or valid alias).
            value: Value to set (or None to clear).
            turn_id: Current conversational turn index.
            is_hypothetical: If True, marks this fact as a tentative/hypothetical exploration
                value subject to 6-turn TTL expiration.
        """
        canonical_key = self._normalize_key(key)
        old_value = self._facts.get(canonical_key)

        # Audit history entry
        change_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "turn_id": turn_id,
            "key": canonical_key,
            "old_value": old_value,
            "new_value": value,
            "is_hypothetical": is_hypothetical,
            "action": "set_hypothetical" if is_hypothetical else "set_fact",
        }
        self._history.append(change_record)

        if is_hypothetical:
            # Preserve original non-hypothetical value if previously existed
            if canonical_key in self._hypothetical_meta:
                prev_val = self._hypothetical_meta[canonical_key]["previous_value"]
            else:
                prev_val = old_value

            self._hypothetical_meta[canonical_key] = {
                "set_turn": turn_id,
                "previous_value": prev_val,
            }
            if value is not None:
                self._facts[canonical_key] = value
            else:
                self._facts.pop(canonical_key, None)
        else:
            # Confirmed fact clears any hypothetical TTL tracking
            self._hypothetical_meta.pop(canonical_key, None)
            if value is not None:
                self._facts[canonical_key] = value
            else:
                self._facts.pop(canonical_key, None)

    def get_fact(self, key: str) -> Optional[Any]:
        """Returns current active value for a canonical key, or None if unset/expired."""
        try:
            canonical_key = self._normalize_key(key)
        except ValueError:
            return None
        return self._facts.get(canonical_key)

    def get_all_facts(self) -> Dict[str, Any]:
        """Returns a dictionary containing all currently active, non-expired facts."""
        return dict(self._facts)

    def is_fact_hypothetical(self, key: str) -> bool:
        """Returns True if the given key currently holds a hypothetical value."""
        try:
            canonical_key = self._normalize_key(key)
        except ValueError:
            return False
        return canonical_key in self._hypothetical_meta

    def get_hypothetical_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        """Returns hypothetical metadata (set_turn, previous_value) if key is hypothetical."""
        try:
            canonical_key = self._normalize_key(key)
        except ValueError:
            return None
        return self._hypothetical_meta.get(canonical_key)

    def tick_turn(self, turn_id: int) -> List[Dict[str, Any]]:
        """Advances turn counter and enforces 6-turn TTL for hypothetical facts.

        When `turn_id - set_turn >= 6`, the hypothetical value expires and reverts
        to its previous confirmed value (or is removed), logging the expiration in history.

        Args:
            turn_id: Current conversational turn number.

        Returns:
            List of expiration events triggered during this tick.
        """
        expired_events = []
        for key, meta in list(self._hypothetical_meta.items()):
            set_turn = meta["set_turn"]
            if (turn_id - set_turn) >= self._ttl_turns:
                expired_value = self._facts.get(key)
                reverted_value = meta["previous_value"]

                if reverted_value is not None:
                    self._facts[key] = reverted_value
                else:
                    self._facts.pop(key, None)

                self._hypothetical_meta.pop(key, None)

                event = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "turn_id": turn_id,
                    "key": key,
                    "old_value": expired_value,
                    "new_value": reverted_value,
                    "is_hypothetical": False,
                    "action": "expire_hypothetical",
                    "reason": f"Hypothetical TTL expired at turn {turn_id} (set at turn {set_turn})",
                }
                self._history.append(event)
                expired_events.append(event)

        return expired_events

    def get_change_history(self) -> List[Dict[str, Any]]:
        """Returns the full turn-by-turn change history audit log."""
        return [dict(entry) for entry in self._history]

    def clear(self) -> None:
        """Resets all facts, hypothetical tracking, and history log."""
        self._facts.clear()
        self._hypothetical_meta.clear()
        self._history.clear()

    def to_dict(self) -> Dict[str, Any]:
        """Serializes FactStore state to dictionary."""
        return {
            "facts": dict(self._facts),
            "hypothetical_meta": dict(self._hypothetical_meta),
            "history": [dict(e) for e in self._history],
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]], canonical_keys=None, ttl_turns=HYPOTHETICAL_TTL_TURNS) -> FactStore:
        """Deserializes FactStore from dictionary."""
        fs = cls(canonical_keys=canonical_keys, ttl_turns=ttl_turns)
        if isinstance(data, dict):
            fs._facts = dict(data.get("facts", {}))
            fs._hypothetical_meta = dict(data.get("hypothetical_meta", {}))
            fs._history = list(data.get("history", []))
        return fs


# ═══════════════════════════════════════════════════════════════════════
# 4. DETERMINISTIC VECTOR SIMILARITY ENGINE
# ═══════════════════════════════════════════════════════════════════════

SEMANTIC_CLUSTERS: Dict[str, Set[str]] = {
    "sem_amount": {
        "amount", "lakh", "lakhs", "crore", "crores", "rupees", "rs", "inr",
        "paisa", "paise", "money", "funds", "capital", "rupaye", "rupiya",
    },
    "sem_product": {
        "stl", "mtl", "sip", "p2p", "loan", "loans", "lending", "product",
        "products", "manual", "lump", "sum", "lumpsum",
    },
    "sem_tenure": {
        "months", "month", "year", "years", "tenure", "duration", "timeline",
        "period", "term", "time", "mahine", "saal",
    },
    "sem_risk": {
        "risk", "high", "low", "conservative", "moderate", "aggressive",
        "safe", "safety", "aaa", "surakshit", "risk_preference",
    },
    "sem_returns": {
        "payout", "payouts", "monthly", "daily", "edi", "returns", "return",
        "profit", "xirr", "interest", "yield", "gain", "munafa", "byaj",
    },
    "sem_kyc": {
        "kyc", "digilocker", "aadhaar", "pan", "document", "documents",
        "verification", "verify", "identity", "pramanpatra",
    },
    "sem_escrow": {
        "escrow", "upi", "netbanking", "deposit", "bank", "icici",
        "account", "transfer", "pay", "jama", "khata",
    },
    "sem_goal": {
        "goal", "retirement", "wealth", "savings", "future", "child",
        "education", "vacation", "marriage", "lakshya", "bachat",
    },
    "sem_occupation": {
        "occupation", "job", "business", "salaried", "employed",
        "profession", "doctor", "engineer", "service", "naukri", "vyapar",
    },
}

_WORD_TO_CLUSTER: Dict[str, str] = {}
for _cluster, _words in SEMANTIC_CLUSTERS.items():
    for _w in _words:
        _WORD_TO_CLUSTER[_w] = _cluster


class DefaultTextEmbedder:
    """Lightweight, deterministic text vectorizer for offline vector search.

    Combines word stemming, semantic clustering, and feature hashing into
    a normalized L2 unit vector.
    """

    DIMENSION: int = 2048
    STOPWORDS: Set[str] = {
        "is", "a", "the", "hai", "ka", "ki", "ke", "ko", "in", "to", "of",
        "and", "for", "with", "on", "at", "by", "from", "an", "are", "was",
        "were", "what", "who", "how", "kya", "ho", "user", "customer",
        "karna", "chahta", "chahte", "mein", "se", "pe", "or", "it",
    }

    def _stem(self, word: str) -> str:
        """Simple morphological suffix stemmer."""
        w = word.lower()
        for suffix in ["ing", "ment", "ments", "tion", "tions", "ed", "es", "s", "ly", "er", "ers"]:
            if len(w) > len(suffix) + 3 and w.endswith(suffix):
                return w[:-len(suffix)]
        return w

    def _hash_feature(self, feat: str) -> Tuple[int, float]:
        """Murmur/MD5 feature hashing with sign bit."""
        h = int(hashlib.md5(feat.encode("utf-8")).hexdigest(), 16)
        idx = h % self.DIMENSION
        sign = 1.0 if ((h >> 32) & 1) == 1 else -1.0
        return idx, sign

    def embed(self, text: str) -> List[float]:
        """Computes a deterministic L2-normalized dense embedding vector."""
        if not text or not isinstance(text, str):
            return [0.0] * self.DIMENSION

        text_clean = text.lower()
        words = re.findall(r"[a-zA-Z0-9\u0900-\u097F]+", text_clean)
        if not words:
            return [0.0] * self.DIMENSION

        feature_weights: Counter = Counter()

        for i, w in enumerate(words):
            stem = self._stem(w)
            if stem in self.STOPWORDS:
                continue

            feature_weights["w_" + stem] += 3.0

            # Semantic cluster mapping
            if w in _WORD_TO_CLUSTER:
                feature_weights["cl_" + _WORD_TO_CLUSTER[w]] += 2.5
            elif stem in _WORD_TO_CLUSTER:
                feature_weights["cl_" + _WORD_TO_CLUSTER[stem]] += 2.5

            # Subword character n-gram prefix
            if len(stem) >= 4:
                feature_weights["sub_" + stem[:4]] += 1.5

            # Word bigrams
            if i < len(words) - 1:
                next_stem = self._stem(words[i + 1])
                if next_stem not in self.STOPWORDS:
                    feature_weights["b_" + stem + "_" + next_stem] += 2.0

        vec = [0.0] * self.DIMENSION
        for feat, wt in feature_weights.items():
            idx, sign = self._hash_feature(feat)
            vec[idx] += sign * wt

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two unit vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    # Bound to [-1.0, 1.0] to protect against floating point precision errors
    return max(-1.0, min(1.0, dot))


# ═══════════════════════════════════════════════════════════════════════
# 5. ENTERPRISE AGENT MEMORY BANK
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# 5. GOOGLE CLOUD ENTERPRISE AGENT PLATFORM MEMORY BANK
# ═══════════════════════════════════════════════════════════════════════

class GCPAgentEngineMemoryBank:
    """Production client for Google Cloud Gemini Enterprise Agent Platform Memory Bank.

    API Reference:
    https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank
    Connects to Reasoning Engine Memory Bank via agentplatform.Client.agent_engines.memories.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        engine_id: Optional[str] = None,
    ):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT", "deep-clock-339817")
        self.location = location or os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.engine_id = engine_id or os.getenv("GCP_AGENT_ENGINE_ID")
        self.client = None

        if agentplatform and self.engine_id:
            try:
                self.client = agentplatform.Client(project=self.project_id, location=self.location)
                logger.info(f"☁️ [GCPMemoryBank] Connected to Google Cloud Enterprise Agent Platform Memory Bank: {self.engine_id}")
            except Exception as e:
                logger.warning(f"[GCPMemoryBank] Failed to initialize agentplatform client: {e}")

    def is_available(self) -> bool:
        return bool(self.client and self.engine_id)

    def add_memory(self, user_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        if not self.is_available() or not content or not content.strip():
            return False
        uid = normalize_lexical_user_id(user_id)
        try:
            op = self.client.agent_engines.memories.create(
                name=self.engine_id,
                fact=content.strip(),
                scope={"user_id": uid},
            )
            logger.info(f"☁️ [GCPMemoryBank] Persisted memory to GCP Cloud Memory Bank for user {uid}: {content[:60]}...")
            return True
        except Exception as e:
            logger.error(f"[GCPMemoryBank] Error creating cloud memory: {e}")
            return False

    def search_memories(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.is_available() or not query or not query.strip():
            return []
        uid = normalize_lexical_user_id(user_id)
        try:
            ret = self.client.agent_engines.memories.retrieve(
                name=self.engine_id,
                scope={"user_id": uid},
                similarity_search_params={"search_query": query.strip(), "top_k": limit},
            )
            results = []
            for r in ret:
                results.append({
                    "id": getattr(r.memory, "name", ""),
                    "user_id": uid,
                    "content": getattr(r.memory, "fact", ""),
                    "similarity": round(1.0 - getattr(r, "distance", 0.0), 4),
                    "score": round(1.0 - getattr(r, "distance", 0.0), 4),
                    "created_at": str(getattr(r.memory, "create_time", "")),
                    "updated_at": str(getattr(r.memory, "update_time", "")),
                    "source": "gcp_enterprise_agent_platform_memory_bank",
                })
            logger.info(f"☁️ [GCPMemoryBank] Retrieved {len(results)} cloud memories for {uid} matching '{query}'")
            return results
        except Exception as e:
            logger.error(f"[GCPMemoryBank] Error searching cloud memories: {e}")
            return []

    def list_memories(self, user_id: str) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        uid = normalize_lexical_user_id(user_id)
        try:
            mems = list(self.client.agent_engines.memories.list(
                name=self.engine_id,
                config={"filter": f'scope.user_id="{uid}"'}
            ))
            return [
                {
                    "id": m.name,
                    "user_id": uid,
                    "content": m.fact,
                    "created_at": str(m.create_time),
                    "updated_at": str(m.update_time),
                    "source": "gcp_enterprise_agent_platform_memory_bank",
                }
                for m in mems
            ]
        except Exception as e:
            logger.error(f"[GCPMemoryBank] Error listing cloud memories: {e}")
            return []

    def get_all_user_ids(self) -> List[str]:
        """Queries GCP Cloud Reasoning Engine to extract all distinct registered user IDs."""
        if not self.is_available():
            return []
        try:
            mems = list(self.client.agent_engines.memories.list(name=self.engine_id))
            uids = set()
            for m in mems:
                scope = getattr(m, "scope", None) or {}
                if isinstance(scope, dict) and "user_id" in scope:
                    uids.add(scope["user_id"])
            return [u for u in uids if u and u not in ("user_anonymous", "default_user")]
        except Exception as e:
            logger.warning(f"[GCPMemoryBank] Error listing cloud user IDs: {e}")
            return []

    def hydrate_user_profile(self, user_id: str, days_lookback: int = 90) -> Dict[str, Any]:
        if not self.is_available():
            return {"user_id": normalize_lexical_user_id(user_id), "facts": {}, "recent_memories": [], "episodic_memories": [], "memory_count": 0, "profile_hydrated": False}
        uid = normalize_lexical_user_id(user_id)
        cloud_mems = self.list_memories(uid)
        return {
            "user_id": uid,
            "facts": {},
            "recent_memories": cloud_mems,
            "episodic_memories": [m["content"] for m in cloud_mems],
            "memory_count": len(cloud_mems),
            "profile_hydrated": len(cloud_mems) > 0,
            "source": "gcp_enterprise_agent_platform_memory_bank",
        }


def _get_default_storage_path() -> str:
    """Returns the canonical storage path for persistent user memories."""
    env_path = os.getenv("MEMORY_BANK_STORAGE_PATH")
    if env_path:
        return env_path
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "user_memories.json")


class MemoryBank:
    """Enterprise Memory Bank with GCP Agent Platform Cloud integration and local cache.

    Attributes:
        dedup_threshold: 0.83 similarity threshold for deduplication.
        retrieval_threshold: 0.40 similarity threshold for query retrieval.
        lookback_days: 90 days lookback window for cross-session hydration.
        storage_path: Path to persistent JSON storage file.
        cloud_bank: Optional GCPAgentEngineMemoryBank production cloud client.
    """

    def __init__(
        self,
        embedder: Optional[Any] = None,
        dedup_threshold: float = DEDUPLICATION_THRESHOLD,
        retrieval_threshold: float = RETRIEVAL_THRESHOLD,
        lookback_days: int = DEFAULT_HYDRATION_LOOKBACK_DAYS,
        storage_path: Optional[str] = None,
        enable_cloud: Optional[bool] = None,
    ):
        self.embedder = embedder or DefaultTextEmbedder()
        self.dedup_threshold = dedup_threshold
        self.retrieval_threshold = retrieval_threshold
        self.lookback_days = lookback_days
        self.storage_path = storage_path if storage_path is not None else os.getenv("MEMORY_BANK_STORAGE_PATH", None)

        if enable_cloud is None:
            enable_cloud = os.getenv("ENABLE_CLOUD_MEMORY_BANK", "true").lower() in ("true", "1", "yes")

        # Connect to Google Cloud Gemini Enterprise Agent Platform Memory Bank
        self.cloud_bank: Optional[GCPAgentEngineMemoryBank] = None
        if enable_cloud and agentplatform and os.getenv("GCP_AGENT_ENGINE_ID"):
            try:
                self.cloud_bank = GCPAgentEngineMemoryBank()
            except Exception as e:
                logger.warning(f"[MemoryBank] Could not initialize GCP cloud bank: {e}")

        # user_id -> List of memory records
        self._memories: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        # user_id -> Dict of content_hash -> memory record
        self._hash_index: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        # user_id -> FactStore instance
        self._fact_stores: Dict[str, FactStore] = defaultdict(FactStore)

        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Loads persisted user memories and facts from disk."""
        if not self.storage_path or not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            users_data = data.get("users", {})
            for uid, udata in users_data.items():
                if "fact_store" in udata and udata["fact_store"]:
                    self._fact_stores[uid] = FactStore.from_dict(udata["fact_store"])
                mems = udata.get("memories", [])
                for m in mems:
                    if isinstance(m, dict) and "content" in m:
                        if "embedding" not in m or not m["embedding"]:
                            m["embedding"] = self.embedder.embed(m["content"])
                        self._memories[uid].append(m)
                        h_val = m.get("content_hash") or hashlib.md5(m["content"].encode("utf-8")).hexdigest()
                        self._hash_index[uid][h_val] = m
        except Exception:
            pass

    def _save_to_disk(self) -> None:
        """Persists memories and fact stores to disk atomically."""
        if not self.storage_path:
            return
        try:
            dir_name = os.path.dirname(os.path.abspath(self.storage_path))
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            users_data = {}
            all_uids = set(self._memories.keys()) | set(self._fact_stores.keys())
            for uid in all_uids:
                users_data[uid] = {
                    "fact_store": self._fact_stores[uid].to_dict() if uid in self._fact_stores else {},
                    "memories": [
                        {
                            "id": m.get("id"),
                            "user_id": m.get("user_id"),
                            "content": m.get("content"),
                            "metadata": m.get("metadata", {}),
                            "content_hash": m.get("content_hash"),
                            "created_at": m.get("created_at"),
                            "updated_at": m.get("updated_at"),
                        }
                        for m in self._memories[uid]
                    ]
                }
            tmp_path = f"{self.storage_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"users": users_data, "updated_at": datetime.now(timezone.utc).isoformat()}, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.storage_path)
        except Exception:
            pass

    def get_all_user_ids(self) -> List[str]:
        """Returns all distinct registered user IDs in the Memory Bank."""
        uids = set(self._memories.keys()) | set(self._fact_stores.keys())
        return [u for u in uids if u and u not in ("user_anonymous", "default_user")]

    def get_fact_store(self, user_id: str) -> FactStore:
        """Retrieves or creates the FactStore instance for a specific user."""
        uid = normalize_lexical_user_id(user_id, memory_bank=self)
        return self._fact_stores[uid]

    def save_facts_and_sync(self, user_id: str, facts: Dict[str, Any], turn_id: int = 0) -> None:
        """Sets confirmed facts on user's FactStore and flushes to storage."""
        fs = self.get_fact_store(user_id)
        for k, v in facts.items():
            if k in CANONICAL_FACT_KEYS and v is not None:
                try:
                    fs.set_fact(k, v, turn_id=turn_id, is_hypothetical=False)
                except ValueError:
                    pass
        self._save_to_disk()

    def add_memory(
        self,
        user_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        content_hash: Optional[str] = None,
    ) -> bool:
        """Adds a memory to GCP Cloud Memory Bank and local storage with MD5 idempotency."""
        if not content or not isinstance(content, str) or not content.strip():
            return False

        uid = normalize_lexical_user_id(user_id)
        clean_content = content.strip()
        hash_val = content_hash or hashlib.md5(clean_content.encode("utf-8")).hexdigest()
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Asynchronously / Synchronously commit to GCP Cloud Agent Platform Memory Bank
        if self.cloud_bank and self.cloud_bank.is_available():
            self.cloud_bank.add_memory(user_id=uid, content=clean_content, metadata=metadata)

        # 2. Idempotency Check via exact MD5 content hash
        if hash_val in self._hash_index[uid]:
            existing_mem = self._hash_index[uid][hash_val]
            if metadata:
                existing_mem["metadata"].update(metadata)
            existing_mem["updated_at"] = now_iso
            self._save_to_disk()
            return True

        # 3. Vector Embedding Computation
        vec = self.embedder.embed(clean_content)

        # 4. Dual-Threshold Deduplication Check (>= 0.83)
        best_sim = -1.0
        best_mem = None

        for mem in self._memories[uid]:
            sim = cosine_similarity(vec, mem["embedding"])
            if sim > best_sim:
                best_sim = sim
                best_mem = mem

        if best_sim >= self.dedup_threshold and best_mem is not None:
            old_hash = best_mem.get("content_hash")
            if old_hash and old_hash in self._hash_index[uid]:
                del self._hash_index[uid][old_hash]

            best_mem["content"] = clean_content
            best_mem["content_hash"] = hash_val
            best_mem["embedding"] = vec
            if metadata:
                best_mem["metadata"].update(metadata)
            best_mem["updated_at"] = now_iso
            self._hash_index[uid][hash_val] = best_mem
            self._save_to_disk()
            return True

        # 5. Insert New Memory Record
        new_record = {
            "id": str(uuid.uuid4()),
            "user_id": uid,
            "content": clean_content,
            "metadata": dict(metadata or {}),
            "content_hash": hash_val,
            "embedding": vec,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        self._memories[uid].append(new_record)
        self._hash_index[uid][hash_val] = new_record
        self._save_to_disk()
        return True

    def search_memories(
        self,
        user_id: str,
        query: str,
        threshold: Optional[float] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Retrieves memories for a user from GCP Cloud Memory Bank or local vector index."""
        if not query or not isinstance(query, str) or not query.strip():
            return []

        uid = normalize_lexical_user_id(user_id)

        # Query Google Cloud Agent Platform Memory Bank if available
        if self.cloud_bank and self.cloud_bank.is_available():
            cloud_results = self.cloud_bank.search_memories(user_id=uid, query=query, limit=limit)
            if cloud_results:
                return cloud_results

        effective_threshold = threshold if threshold is not None else self.retrieval_threshold
        query_vec = self.embedder.embed(query.strip())

        results = []
        for mem in self._memories[uid]:
            sim = cosine_similarity(query_vec, mem["embedding"])
            if sim >= effective_threshold:
                match_item = {
                    "id": mem["id"],
                    "user_id": mem["user_id"],
                    "content": mem["content"],
                    "metadata": dict(mem["metadata"]),
                    "content_hash": mem["content_hash"],
                    "similarity": round(sim, 4),
                    "score": round(sim, 4),
                    "created_at": mem["created_at"],
                    "updated_at": mem["updated_at"],
                }
                results.append(match_item)

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    def hydrate_user_profile(
        self,
        user_id: str,
        days_lookback: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Hydrates user profile from GCP Cloud Memory Bank and structured facts."""
        uid = normalize_lexical_user_id(user_id)
        lookback = days_lookback if days_lookback is not None else self.lookback_days

        # Query GCP Cloud Memory Bank if available
        if self.cloud_bank and self.cloud_bank.is_available():
            cloud_profile = self.cloud_bank.hydrate_user_profile(user_id=uid, days_lookback=lookback)
            if cloud_profile.get("memory_count", 0) > 0:
                fact_store = self.get_fact_store(uid)
                cloud_profile["facts"] = fact_store.get_all_facts()
                return cloud_profile

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=lookback, seconds=60)

        recent_memories: List[Dict[str, Any]] = []
        most_recent_ts: Optional[datetime] = None

        for mem in self._memories[uid]:
            ts_str = mem.get("updated_at") or mem.get("created_at")
            ts: Optional[datetime] = None
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    ts = now
            else:
                ts = now

            if ts >= cutoff:
                mem_copy = {
                    "id": mem["id"],
                    "user_id": mem["user_id"],
                    "content": mem["content"],
                    "metadata": dict(mem["metadata"]),
                    "content_hash": mem["content_hash"],
                    "created_at": mem["created_at"],
                    "updated_at": mem["updated_at"],
                }
                recent_memories.append(mem_copy)
                if most_recent_ts is None or ts > most_recent_ts:
                    most_recent_ts = ts

        recent_memories.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

        fact_store = self.get_fact_store(uid)
        active_facts = fact_store.get_all_facts()

        return {
            "user_id": uid,
            "facts": active_facts,
            "recent_memories": recent_memories,
            "episodic_memories": [m["content"] for m in recent_memories],
            "memory_count": len(recent_memories),
            "last_active": most_recent_ts.isoformat() if most_recent_ts else None,
            "lookback_days": lookback,
            "profile_hydrated": True,
        }

    def get_user_memories(self, user_id: str) -> List[Dict[str, Any]]:
        """Returns all memories for a given user."""
        uid = normalize_lexical_user_id(user_id)
        if self.cloud_bank and self.cloud_bank.is_available():
            return self.cloud_bank.list_memories(uid)
        return [
            {
                "id": m["id"],
                "user_id": m["user_id"],
                "content": m["content"],
                "metadata": dict(m["metadata"]),
                "content_hash": m["content_hash"],
                "created_at": m["created_at"],
                "updated_at": m["updated_at"],
            }
            for m in self._memories[uid]
        ]

    def clear(self, user_id: Optional[str] = None) -> None:
        """Clears memories and facts."""
        if user_id is not None:
            uid = normalize_lexical_user_id(user_id)
            self._memories.pop(uid, None)
            self._hash_index.pop(uid, None)
            if uid in self._fact_stores:
                self._fact_stores[uid].clear()
        else:
            self._memories.clear()
            self._hash_index.clear()
            self._fact_stores.clear()


__all__ = [
    "CANONICAL_FACT_KEYS",
    "HYPOTHETICAL_TTL_TURNS",
    "DEDUPLICATION_THRESHOLD",
    "RETRIEVAL_THRESHOLD",
    "DEFAULT_HYDRATION_LOOKBACK_DAYS",
    "normalize_lexical_user_id",
    "FactStore",
    "DefaultTextEmbedder",
    "cosine_similarity",
    "GCPAgentEngineMemoryBank",
    "MemoryBank",
]
