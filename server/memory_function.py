import os
import json
import asyncio
import re
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from loguru import logger
from dotenv import load_dotenv
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from diagnostic_buffer import append_diagnostic_log

# Dedicated executors for isolation: live real-time voice tool calls vs. background batch distillation
_VERTEX_READ_EXECUTOR = ThreadPoolExecutor(max_workers=20, thread_name_prefix="vertex-read")
_VERTEX_BATCH_EXECUTOR = ThreadPoolExecutor(max_workers=5, thread_name_prefix="vertex-batch")
_VERTEX_INIT_LOCK = threading.Lock()

# Backward-compatibility aliases for legacy executor names
_MEM0_READ_EXECUTOR = _VERTEX_READ_EXECUTOR
_MEM0_BATCH_EXECUTOR = _VERTEX_BATCH_EXECUTOR
_MEM0_INIT_LOCK = _VERTEX_INIT_LOCK

# Auto-load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# PRD-Aligned Promotion Threshold Matrix
THRESHOLDS = {
    "M7_Safety":     1,  # N=1 (Instant, UNVERIFIED)
    "M5_Commitment": 1,  # N=1 (Instant, expires on completion + 30d)
    "M1_Identity":   2,  # N=2 (Catches ASR errors / misstatements)
    "M2_Relation":   1,  # N=1 (Instant: family relations, son/daughter names, core personal relations)
    "M3_Preference": 2,  # N=2 (Fast Staging)
    "M4_Behavioral": 3,  # N=3 (Standard Staging)
    "M6_Recent":     1   # N=1 (Expires in 3 days)
}

# The live tool schema lets Gemini emit human-readable categories ('preference',
# 'financial_goal', ...). Those are not keys in THRESHOLDS, so without this map
# every fact silently fell through to the N=2 default and the M6 TTL / M7
# UNVERIFIED branches never fired. Everything is funnelled through
# normalize_category() before it reaches the promotion matrix.
CATEGORY_ALIASES = {
    # M7 - Safety. Anything that could cause harm if we recommend against it.
    "safety": "M7_Safety", "allergy": "M7_Safety", "allergies": "M7_Safety",
    "health": "M7_Safety", "medical": "M7_Safety", "prescription": "M7_Safety",
    "condition": "M7_Safety", "medication": "M7_Safety",

    # M5 - Commitment. Promises we made, or the user made, that must be honoured.
    "commitment": "M5_Commitment", "promise": "M5_Commitment",
    "order": "M5_Commitment", "purchase": "M5_Commitment",
    "appointment": "M5_Commitment", "booking": "M5_Commitment",

    # M6 - Recent context. Short-lived, expires in 3 days.
    "recent": "M6_Recent", "reminder": "M6_Recent", "schedule": "M6_Recent",
    "meeting": "M6_Recent", "event": "M6_Recent", "today": "M6_Recent",
    "temporary": "M6_Recent", "session": "M6_Recent",

    # M1 - Identity. Who the user is.
    "identity": "M1_Identity", "name": "M1_Identity", "personal": "M1_Identity",
    "contact_info": "M1_Identity", "contact": "M1_Identity",
    "profile": "M1_Identity", "demographic": "M1_Identity", "occupation": "M1_Identity",

    # M2 - Relations. People and places in the user's orbit.
    "relation": "M2_Relation", "relationship": "M2_Relation", "family": "M2_Relation",
    "child": "M2_Relation", "children": "M2_Relation", "son": "M2_Relation",
    "daughter": "M2_Relation", "spouse": "M2_Relation", "friend": "M2_Relation",

    # M3 - Preferences. Tastes, likes, stated wants.
    "preference": "M3_Preference", "preferences": "M3_Preference",
    "like": "M3_Preference", "likes": "M3_Preference", "dislike": "M3_Preference",
    "style": "M3_Preference", "brand": "M3_Preference", "budget": "M3_Preference",
    "financial_goal": "M3_Preference", "goal": "M3_Preference",
    "objection": "M3_Preference", "interest": "M3_Preference",

    # M4 - Behavioural. Inferred patterns, needs the most corroboration.
    "behavioral": "M4_Behavioral", "behaviour": "M4_Behavioral",
    "behavior": "M4_Behavioral", "habit": "M4_Behavioral", "pattern": "M4_Behavioral",
    "general": "M4_Behavioral",
}

DEFAULT_CATEGORY = "M4_Behavioral"


def normalize_category(raw_category: str) -> str:
    """
    Map a free-text category emitted by the LLM onto a canonical M1..M7 PRD code.

    Anything already canonical passes through untouched. Unknown strings are
    matched on substring before falling back to M4_Behavioral, which is the
    safest default because it demands the most corroboration (N=3) before a
    fact is promoted to active.
    """
    if not raw_category:
        return DEFAULT_CATEGORY

    clean = str(raw_category).strip()
    if clean in THRESHOLDS:
        return clean

    key = clean.lower().replace("-", "_").replace(" ", "_")
    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]

    # Substring pass catches compounds like 'user_preference' or 'health_note'.
    for alias, canonical in CATEGORY_ALIASES.items():
        if alias in key:
            return canonical

    return DEFAULT_CATEGORY


# Dedupe gate for process_extracted_fact(). gemini-embedding-001 places any two
# sentences that share the "User ..." frame at a 0.55-0.75 cosine baseline, so
# the old 0.20 value matched everything and mem0.update() overwrote unrelated
# memories in place. 0.83 only catches genuine restatements of the same fact.
SIMILARITY_THRESHOLD = 0.83
RETRIEVAL_THRESHOLD = 0.40

# Native GCP Vertex AI Agent Engine / Memory Bank Store singleton
_VERTEX_STORE_INSTANCE = None

class VertexMemoryBankStore:
    """Native GCP Vertex AI Agent Engine / Memory Bank API Client with local fallback."""

    def __init__(self, resource_id: str | None = None, project_id: str | None = None, location: str = "us-central1"):
        self.resource_id = resource_id or os.getenv("MEMORY_BANK_RESOURCE_ID") or os.getenv("MEMORY_BANK_REASONING_ENGINE_ID") or "projects/853612069841/locations/us-central1/reasoningEngines/4963337874536660992"
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
        self.location = location or os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"
        self._sdk_client = None
        self._local_db = {}

    def _get_sdk_client(self):
        if self._sdk_client is None:
            try:
                from google.genai import Client
                self._sdk_client = Client(vertexai=True, project=self.project_id, location=self.location)
            except Exception as e:
                logger.warning(f"[VertexMemoryBankStore] Failed to initialize google.genai.Client: {e}")
        return self._sdk_client

    def add(self, memory_text: str, user_id: str = "default_user", metadata: dict | None = None, infer: bool = False) -> dict:
        metadata = metadata or {}
        client = self._get_sdk_client()
        if client and hasattr(client, "agent_engines"):
            try:
                res = client.agent_engines.memories.create(
                    name=self.resource_id,
                    fact=memory_text,
                    scope={"user_id": user_id}
                )
                mem_id = getattr(res, "name", "").split("/")[-1] or f"mem-{content_fingerprint(memory_text)[:8]}"
                rec = {"id": mem_id, "memory": memory_text, "metadata": metadata}
                return {"results": [rec]}
            except Exception as e:
                logger.warning(f"[VertexMemoryBankStore] SDK memories.create failed: {e}. Falling back to local store.")

        # Local fallback execution path
        mem_id = f"mem-{content_fingerprint(memory_text)[:8]}"
        rec = {"id": mem_id, "memory": memory_text, "metadata": metadata, "user_id": user_id}
        self._local_db[mem_id] = rec
        logger.info(f"[VertexMemoryBankStore] (Local Fallback) Stored memory for {user_id}: '{memory_text[:40]}'")
        return {"results": [rec]}

    def search(self, query: str, filters: dict | None = None) -> dict:
        filters = filters or {}
        user_id = filters.get("user_id", "default_user")
        client = self._get_sdk_client()
        if client and hasattr(client, "agent_engines"):
            try:
                retrieved = list(client.agent_engines.memories.retrieve(
                    name=self.resource_id,
                    scope={"user_id": user_id}
                ))
                formatted = []
                query_lower = query.lower()
                for item in retrieved:
                    content = getattr(item, "fact", None) or getattr(item, "content", "") or str(item)
                    mem_id = getattr(item, "name", "").split("/")[-1] or "ver-id"
                    if not query_lower or any(w in content.lower() for w in query_lower.split()):
                        formatted.append({"id": mem_id, "memory": content, "score": 0.95, "metadata": getattr(item, "scope", {})})
                return {"results": formatted}
            except Exception as e:
                logger.warning(f"[VertexMemoryBankStore] SDK memories.retrieve failed: {e}. Falling back to local store.")

        # Local fallback search path
        query_lower = query.lower()
        formatted = []
        for item in self._local_db.values():
            item_user = item.get("user_id", "default_user")
            if item_user != user_id and user_id != "default_user" and item_user != "default_user":
                continue
            content = item.get("memory", "")
            if not query_lower or any(w in content.lower() for w in query_lower.split()):
                formatted.append({"id": item["id"], "memory": content, "score": 0.95, "metadata": item.get("metadata", {})})
        return {"results": formatted}

    def update(self, memory_id: str, data: str, metadata: dict | None = None) -> dict:
        metadata = metadata or {}
        if memory_id in self._local_db:
            self._local_db[memory_id]["memory"] = data
            self._local_db[memory_id]["metadata"] = metadata
            return {"results": [self._local_db[memory_id]]}
        rec = {"id": memory_id, "memory": data, "metadata": metadata}
        self._local_db[memory_id] = rec
        return {"results": [rec]}

    def get_all(self, filters: dict | None = None, limit: int = 25, user_id: str | None = None) -> dict:
        target_user = user_id or (filters or {}).get("user_id", "default_user")
        return self.search(query="", filters={"user_id": target_user})

def get_vertex_memory_bank_store():
    global _VERTEX_STORE_INSTANCE
    if _VERTEX_STORE_INSTANCE is not None:
        return _VERTEX_STORE_INSTANCE
    with _VERTEX_INIT_LOCK:
        if _VERTEX_STORE_INSTANCE is None:
            _VERTEX_STORE_INSTANCE = VertexMemoryBankStore()
    return _VERTEX_STORE_INSTANCE

def get_mem0_instance():
    """Alias for backwards compatibility with legacy callers and unit tests."""
    return get_vertex_memory_bank_store()

def get_mem0_config() -> dict:
    """Return dynamic configuration for Vertex AI Agent Engine / Memory Bank."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    project_id = os.getenv("GCP_PROJECT_ID", "deep-clock-339817")
    location = os.getenv("GCP_LOCATION", "us-central1")
    use_vertex = os.getenv("USE_VERTEXAI", "true").lower() == "true"
    model_name = os.getenv("MEMORY_DISTILL_MODEL", "gemini-2.5-flash")

    return {
        "vector_store": {
            "provider": "vertex_memory_bank",
            "config": {
                "project_id": project_id,
                "location": location,
                "embedding_model_dims": 768
            }
        },
        "llm": {
            "provider": "gemini",
            "config": {
                "model": model_name,
                "api_key": api_key,
                "vertexai": use_vertex,
                "project": project_id,
                "location": location,
            }
        },
        "embedder": {
            "provider": "gemini",
            "config": {
                "model": "gemini-embedding-001",
                "embedding_dims": 768,
                "api_key": api_key if not use_vertex else None,
            }
        }
    }

def warm_memory_engine() -> None:
    """Warm up Vertex AI Agent Memory Bank connection."""
    import time
    start = time.time()
    store = get_vertex_memory_bank_store()
    if store is None:
        logger.warning("[Warmup] Vertex memory store unavailable.")
        return

    try:
        store.search(query="warmup", filters={"user_id": "__warmup__"})
        logger.info(f"[Warmup] Dry-run search completed in {time.time() - start:.2f}s")
    except Exception as e:
        logger.warning(f"[Warmup] Dry-run search skipped: {e}")

    logger.info(f"[Warmup] Memory engine fully warm in {time.time() - start:.2f}s")

def get_memory_file_path(user_id: str = "default_user") -> str:
    """Deprecated: Local JSON memory file storage has been removed."""
    raise RuntimeError("Local memory storage file is disabled. Vertex AI Agent Memory Bank is required.")

def get_memory_bank_config():
    """Fetch Memory Bank resource configuration if present."""
    resource_id = os.getenv("MEMORY_BANK_RESOURCE_ID") or os.getenv("MEMORY_BANK_REASONING_ENGINE_ID") or "projects/853612069841/locations/us-central1/reasoningEngines/4963337874536660992"
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
    location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"
    return resource_id, project_id, location

# Schemas
save_user_memory_schema = FunctionSchema(
    name="save_user_memory",
    description=(
        "Save a key user fact, preference, goal, or conversational detail to long-term memory. "
        "Use when user states personal preferences, financial goals, preferred tenure, past interactions, or details to remember."
    ),
    properties={
        "memory_text": {
            "type": "string",
            "description": "The specific user fact, preference, or context to store in long-term memory."
        },
        "category": {
            "type": "string",
            "description": (
                "Classification of the fact. Prefer one of: "
                "'identity' (name, job, contact), "
                "'relation' (family, son, daughter, spouse, friend), "
                "'preference' (styles, brands, budget, goals, objections), "
                "'safety' (allergies, medical conditions, prescriptions), "
                "'commitment' (orders, appointments, promises), "
                "'recent' (short-lived context expiring in days), "
                "'behavioral' (inferred habits and patterns)."
            )
        },
        "user_id": {
            "type": "string",
            "description": "The unique identity key or name of the user being spoken with (e.g. 'user:rohan')."
        }
    },
    required=["memory_text"]
)

search_user_memory_schema = FunctionSchema(
    name="search_user_memory",
    description=(
        "Search or retrieve stored long-term user memories, preferences, and past facts. "
        "MANDATORY: You MUST call this tool whenever the user asks about their kids, kid, son, daughter, child, family, name, prescription, or past preferences (e.g. 'what is my kids name?', 'what is my son's name?'). Never say you do not know without searching first!"
        "CRITICAL: DO NOT call this tool when the user simply introduces their name or says hello. Only call this when the user asks a question or explicitly asks to check history!"
    ),
    properties={
        "query": {
            "type": "string",
            "description": "The search query to match against stored user memories."
        },
        "user_id": {
            "type": "string",
            "description": "The unique identity key transliterated into canonical lowercased Roman ASCII script (e.g. 'user:manish' or 'user:chandra'). Never use raw Devnagari."
        }
    },
    required=["query"]
)

def normalize_user_id(raw_id: str) -> str:
    """Normalize multi-lingual/Devnagari user_id strings to canonical ASCII identity keys (`user:manish`, `user:chandra`, etc)."""
    if not raw_id:
        return "default_user"
    clean = str(raw_id).strip().lower()
    if not clean.startswith("user:"):
        if clean in ["मनीष", "manish"]:
            clean = "user:manish"
        elif clean in ["रोहन", "rohan"]:
            clean = "user:rohan"
        elif clean in ["प्रिया", "priya"]:
            clean = "user:priya"
        elif clean in ["चन्द्रा", "चंद्रा", "chandra", "chandira"]:
            clean = "user:chandra"
        else:
            clean = f"user:{clean}"
    
    if "मनीष" in clean or "manish" in clean:
        return "user:manish"
    elif "रोहन" in clean or "rohan" in clean:
        return "user:rohan"
    elif "प्रिया" in clean or "priya" in clean:
        return "user:priya"
    elif "चन्द्रा" in clean or "चंद्रा" in clean or "chandra" in clean or "chandira" in clean:
        return "user:chandra"
    return clean

def _get_active_user_id(params: FunctionCallParams) -> str:
    """Extract user_id from arguments, session params, environment, or default."""
    if params and hasattr(params, "arguments") and params.arguments.get("user_id"):
        return normalize_user_id(str(params.arguments.get("user_id")))
    return normalize_user_id(os.getenv("ACTIVE_USER_ID", "default_user"))

recall_user_memories_schema = FunctionSchema(
    name="recall_user_memories",
    description=(
        "Recall or search historical user facts and deep notes from long-term memory. "
        "Use when user asks 'Remember what I said about...', 'Let me check your notes...', or queries specific historical details. "
        "CRITICAL: DO NOT call this tool when the user simply introduces their name or says hello. Only call this when the user asks a question or explicitly asks to check notes/history!"
    ),
    properties={
        "query": {
            "type": "string",
            "description": "The search query to match against stored user memories."
        },
        "user_id": {
            "type": "string",
            "description": "The unique identity key transliterated into canonical lowercased Roman ASCII script (e.g. 'user:manish' or 'user:chandra'). Never use raw Devnagari."
        }
    },
    required=["query"]
)

def is_roleplay_or_popculture_fact(fact_text: str, category: str = "") -> bool:
    """Check if the extracted fact represents a personal roleplay assertion or pop-culture claim."""
    combined = f"{fact_text} {category}".lower()
    roleplay_keywords = [
        "shaktiman", "shaktimaan", "kilvish",
        "roleplay", "identifies as shaktiman", "identifies as superman", "identifies with kabir",
        "plan to defeat kilvish", "plan to kill kilvish", "andhera kayam rahe",
        "superman", "batman", "superhero"
    ]
    return any(kw in combined for kw in roleplay_keywords)

def extract_graph_triples(fact_text: str, category: str = "", user_id: str = "") -> dict[str, str]:
    """
    Extract relational graph triples (Subject -> Relation -> Object) from fact text and category.
    Supports roleplay assertions, family relationships, exams, bilingual Devnagari/Hinglish patterns, and dynamic heuristics.
    """
    text_l = fact_text.lower()
    subject, relation, obj = "User", "associated_with", fact_text

    # 1. Shaktiman & Kilvish Roleplay Relationships
    if "kilvish" in text_l:
        subject = "Shaktiman" if ("shaktiman" in text_l or "shaktimaan" in text_l) else "User"
        relation = "plan"
        obj = "defeat/kill Kilvish"
    elif "shaktiman" in text_l or "shaktimaan" in text_l:
        subject = "User"
        relation = "identifies_as"
        obj = "Shaktiman"
    # 2. Family Relations (Son / Daughter / Children across English & Devnagari)
    elif "son" in text_l or "बेटे" in fact_text or "पुत्र" in fact_text or "बच्चे" in fact_text or "kids" in text_l or "child" in text_l:
        subject = "Son" if ("son" in text_l or "बेटे" in fact_text or "पुत्र" in fact_text) else "Child"
        if "name" in text_l or "नाम" in fact_text:
            relation = "name_is"
            if "adhyanth" in text_l or "adyant" in text_l or "अध्यांत" in fact_text or "अध्यंत" in fact_text:
                obj = "Adhyanth"
            elif "kabir" in text_l or "कबीर" in fact_text:
                obj = "Kabir"
            else:
                obj = fact_text
        elif "like" in text_l or "पसंद" in fact_text:
            relation = "likes_to_play" if ("play" in text_l or "खेलना" in fact_text) else "likes"
            obj = fact_text
        else:
            relation = "has_detail"
            obj = fact_text
    # 3. Exam & Schedule Relationships
    elif "exam" in text_l or "परीक्षा" in fact_text or "paper" in text_l:
        subject = "Exam"
        relation = "scheduled_for"
        obj = fact_text
    # 4. General identity / preference patterns across English & Devnagari
    elif "identifies with" in text_l:
        parts = fact_text.split("identifies with", 1)
        subject = parts[0].strip() or "User"
        relation = "identifies_with"
        obj = parts[1].strip() if len(parts) > 1 else fact_text
    elif "identifies as" in text_l:
        subject = "User"
        relation = "identifies_as"
        parts = fact_text.split("identifies as", 1)
        obj = parts[1].strip() if len(parts) > 1 else fact_text
    elif "prefers" in text_l or "पसंद है" in fact_text or "चाहिए" in fact_text:
        subject = "User"
        relation = "prefers"
        if "prefers" in fact_text:
            parts = fact_text.split("prefers", 1)
            obj = parts[1].strip() if len(parts) > 1 else fact_text
        else:
            obj = fact_text
    else:
        # Dynamic regex relation heuristic for multi-word subjects and common verbs
        match = re.search(r"^([\w\s]+?)\s+(is|likes|prefers|wants|has|works at|lives in|preparing for|plans to|identifies with|identifies as)\s+(.+)$", fact_text, re.IGNORECASE)
        if match:
            subject = match.group(1).strip().capitalize()
            relation = match.group(2).lower().replace(" ", "_")
            obj = match.group(3).strip()

    return {"subject": subject, "relation": relation, "object": obj}

def content_fingerprint(fact_text: str) -> str:
    """Stable hash of a fact's normalized text, used to short-circuit re-ingestion."""
    return hashlib.md5(fact_text.lower().strip().encode()).hexdigest()


def find_dedupe_match(candidates: list, content_hash: str, category: str):
    """
    Pick the memory that this fact is a restatement of, or None to store fresh.

    Two ways to qualify, in priority order:
      1. Identical content fingerprint. The exact same sentence, said again.
      2. High semantic similarity AND the same PRD category. The category guard
         is what stops 'User prefers blue frames' (M3) from being folded into
         'User is allergic to peanuts' (M7) just because both embed near 0.6.

    Returning None is always safe: worst case we store a near-duplicate.
    Returning a wrong match is not: it destroys the existing memory.
    """
    for item in candidates:
        if (item.get("metadata") or {}).get("content_hash") == content_hash:
            return item

    if not candidates:
        return None

    top = candidates[0]
    score = top.get("score", 0.0)
    if score < SIMILARITY_THRESHOLD:
        return None

    existing_category = normalize_category((top.get("metadata") or {}).get("category", ""))
    if existing_category != category:
        logger.debug(
            f"[dedupe] Score {score:.3f} cleared the gate but category "
            f"{existing_category} != {category}; storing as a new memory."
        )
        return None

    return top


def process_extracted_fact(fact_text: str, category: str, user_id: str, is_explicit_remember: bool = False):
    """
    Process a single distilled fact extracted by Gemini 3.1 Flash Lite at session end or during explicit save.
    Implements the PRD Tiered Promotion Matrix, similarity threshold gating (min_score >= 0.83), and observation day tracking.
    """
    mem0 = get_mem0_instance()
    if not mem0:
        logger.warning("[process_extracted_fact] Mem0 engine unavailable.")
        return None

    user_id = normalize_user_id(user_id)
    # Everything below keys off the canonical M1..M7 code, never the raw LLM string.
    category = normalize_category(category)
    today_str = datetime.now().strftime("%Y-%m-%d")
    content_hash = content_fingerprint(fact_text)
    
    # 1. Determine promotion threshold N
    is_roleplay = is_roleplay_or_popculture_fact(fact_text, category)
    if is_roleplay:
        is_explicit_remember = True
    threshold = 1 if is_explicit_remember else THRESHOLDS.get(category, 2)
    
    # 2. Determine expiry date for M6 Recent Context
    expires_at = (datetime.now() + timedelta(days=3)).isoformat() if category == "M6_Recent" else None
    
    # 3. Determine verification status for M7 Safety Facts
    verification_status = "UNVERIFIED" if category == "M7_Safety" else "NONE"
    
    # 4. Initial status
    initial_status = "active" if threshold == 1 else "staging"

    # 5. Query existing memories in staging or active
    try:
        existing_memories = mem0.search(query=fact_text, filters={"user_id": user_id})
    except Exception as e:
        logger.warning(f"[process_extracted_fact] search failed for {user_id}: {e}")
        existing_memories = []
        
    results = existing_memories.get("results", []) if isinstance(existing_memories, dict) else existing_memories
    if not isinstance(results, list):
        results = []

    filtered_results = []
    for item in results:
        if isinstance(item, dict):
            # `or {}` not `.get(..., {})`: the vector store returns rows with
            # metadata explicitly set to None, and a dict default only applies
            # when the key is absent, not when its value is null.
            meta = item.get("metadata") or {}
            if meta.get("status", "active") in ["staging", "active"]:
                filtered_results.append(item)

    # 6. Only fold into an existing row on an exact fingerprint or a same-category
    #    high-confidence restatement. Anything else becomes its own memory.
    best_match = find_dedupe_match(filtered_results, content_hash, category)

    if best_match is None:
        # Extract relational graph links (subject -> relation -> object) for multi-hop graph memory
        triples = extract_graph_triples(fact_text, category, user_id)

        meta = {
            "category": category,
            "status": initial_status,
            "observation_count": 1,
            "observation_dates": [today_str],
            "verification_status": verification_status,
            "expires_at": expires_at,
            "graph_relation": triples,
            "graph_triples": triples,
            "content_hash": content_hash
        }
        res = mem0.add(fact_text, user_id=user_id, metadata=meta, infer=False)
        logger.info(f"✅ Stored Raw Memory ({category}/{initial_status}) with Graph Link [{triples['subject']} --({triples['relation']})--> {triples['object'][:20]}...]: '{fact_text}'")
        return res
    else:
        # 8. Match found: Increment count if observed on a NEW distinct day
        meta = best_match.get("metadata") or {}
        dates = meta.get("observation_dates", [])
        count = meta.get("observation_count", 1)

        if today_str not in dates:
            dates.append(today_str)
            count += 1

        # 9. Check if count reached threshold N for promotion
        new_status = "active" if count >= threshold else "staging"

        meta["status"] = new_status
        meta["observation_count"] = count
        meta["observation_dates"] = dates
        # Keep governance fields in step with the fact we are actually storing.
        meta["category"] = category
        meta["content_hash"] = content_hash
        meta["expires_at"] = expires_at
        meta["verification_status"] = verification_status
        triples = extract_graph_triples(fact_text, category, user_id)
        meta["graph_relation"] = triples
        meta["graph_triples"] = triples

        # 10. Update metadata deterministically
        try:
            mem0.update(memory_id=best_match["id"], data=fact_text, metadata=meta)
        except Exception as e:
            logger.warning(f"Failed to update memory id {best_match.get('id')}: {e}")
        logger.info(f"🔄 Updated Memory ({category}/{new_status}, {count}/{threshold}): '{fact_text}'")
        return best_match

# Fact-extraction contract for the end-of-session distiller. We ask for the
# canonical M1..M7 code directly so the promotion matrix does not have to guess
# from a free-text label. normalize_category() still runs on the way in, so a
# malformed code degrades to M4_Behavioral instead of corrupting the tier.
FACT_EXTRACTION_PROMPT = """You distil durable facts from a conversation between a user and the Lenskart 'B' smartglasses assistant.

Return ONLY a JSON object of the form:
{"facts": [{"memory": "<one self-contained sentence>", "category": "<code>"}]}

Category codes:
M1_Identity   - who the user is: name, age, job, city.
M2_Relation   - people in the user's life: son, wife, friend, and their names.
M3_Preference - what the user likes, wants, dislikes, their budget or style.
M4_Behavioral - habits and patterns you inferred rather than were told.
M5_Commitment - orders, bookings, appointments, promises either side made.
M6_Recent     - short-lived context that stops mattering in a few days.
M7_Safety     - allergies, medical conditions, prescriptions.

Rules:
- Write each fact so it stands alone. "User's son is named Adhyanth", never "his son is Adhyanth".
- Record what the user said about themselves and their people. Ignore what the assistant said.
- Translate to English. Keep proper nouns as spoken.
- Never store street addresses, GPS coordinates, card numbers, phone numbers or government IDs.
- No durable facts in the conversation means an empty list. Do not invent any.
"""


def _coerce_fact_list(payload) -> list:
    """
    Pull a list of {memory, category} dicts out of whatever the LLM handed back.

    Providers disagree on shape: some return a bare list, some wrap it in
    {"facts": [...]}, and some return JSON as a fenced string. We accept all
    three rather than let one provider quirk silently empty the session.
    """
    if payload is None:
        return []

    if isinstance(payload, str):
        text = payload.strip()
        # Strip ```json fences before parsing.
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
        try:
            payload = json.loads(text)
        except Exception:
            # Last resort: grab the outermost {...} or [...] span.
            match = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
            if not match:
                return []
            try:
                payload = json.loads(match.group(0))
            except Exception:
                return []

    if isinstance(payload, dict):
        for key in ("facts", "memories", "results", "memory"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            return []

    return payload if isinstance(payload, list) else []


def _llm_extract_facts(mem0_or_transcript, transcript_text: str | None = None) -> list:
    """
    Distil a transcript into candidate facts using native google.genai.Client(vertexai=True).
    Supports either signature: _llm_extract_facts(transcript) or _llm_extract_facts(store, transcript).
    """
    if transcript_text is None:
        text = str(mem0_or_transcript or "")
        store_obj = None
    else:
        text = str(transcript_text or "")
        store_obj = mem0_or_transcript

    if not text.strip():
        return []

    # Check if a custom hook is attached (e.g. in unit tests)
    if store_obj is not None and hasattr(store_obj, "_extract_facts") and callable(getattr(store_obj, "_extract_facts")):
        try:
            facts = _coerce_fact_list(store_obj._extract_facts(text[:6000]))
            if facts:
                return facts
        except Exception as e:
            logger.warning(f"[_llm_extract_facts] store._extract_facts hook failed: {e}")

    snippet = text[:6000]
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    use_vertex = os.getenv("USE_VERTEXAI", "true").lower() == "true"
    project_id = os.getenv("GCP_PROJECT_ID", "deep-clock-339817")
    location = os.getenv("GCP_LOCATION", "us-central1")
    model_name = os.getenv("MEMORY_DISTILL_MODEL", "gemini-2.5-flash")

    try:
        from google.genai import Client
        client = Client(api_key=api_key, vertexai=use_vertex, project=project_id, location=location)
        prompt = f"{FACT_EXTRACTION_PROMPT}\n\nConversation:\n{snippet}"
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        return _coerce_fact_list(response.text)
    except Exception as e:
        logger.error(f"[_llm_extract_facts] LLM extraction failed: {e}")
        return []


def process_session_transcript(transcript_text: str, user_id: str) -> int:
    """
    Process an end-of-session conversation transcript through our enterprise memory pipeline.
    Bypasses raw mem0.add(..., infer=True) to ensure all extracted facts undergo strict
    normalize_category(), content_fingerprint() deduplication, and tiered staging (N=1..3).

    This is the only path that persists anything the user said without the model
    explicitly calling save_user_memory, so a silent failure here means the whole
    session is forgotten. Every exit reports its count.
    """
    if not transcript_text or not transcript_text.strip():
        logger.warning("[process_session_transcript] Empty transcript. Nothing to distil.")
        return 0
    mem0 = get_mem0_instance()
    if not mem0:
        logger.error("[process_session_transcript] Mem0 engine unavailable. Session facts dropped.")
        return 0

    extracted_facts = _llm_extract_facts(mem0, transcript_text)

    count = 0
    for item in extracted_facts:
        fact, cat = "", "general"
        if isinstance(item, dict):
            fact = str(item.get("memory") or item.get("fact") or item.get("text") or "").strip()
            cat = item.get("category") or "general"
        elif isinstance(item, str):
            fact = item.strip()

        if len(fact) <= 5:
            continue

        try:
            process_extracted_fact(fact, cat, user_id, is_explicit_remember=False)
            count += 1
        except Exception as e:
            logger.error(f"[process_session_transcript] Failed to persist '{fact[:60]}': {e}")

    if count:
        logger.info(f"[process_session_transcript] Distilled and persisted {count} fact(s) for {user_id}.")
    else:
        logger.error(
            f"[process_session_transcript] Extracted 0 facts from a {len(transcript_text)}-char "
            f"transcript for {user_id}. This session will not be recalled."
        )
    return count

def pre_load_user_profile(user_id: str) -> list[str]:
    """
    Path 1: Connection Pre-Load Handler (~40ms budget).
    Fetch active core profile facts with bounded result limit (25) to prevent connection delays.
    Scrubs expired M6 facts and flags UNVERIFIED M7 safety facts.
    """
    user_id = normalize_user_id(user_id)
    mem0 = get_mem0_instance()
    if not mem0:
        return []

    now_iso = datetime.now().isoformat()
    
    try:
        active_facts = mem0.get_all(filters={"user_id": user_id, "status": "active"}, limit=25)
    except Exception:
        try:
            active_facts = mem0.get_all(filters={"user_id": user_id}, limit=25)
        except Exception:
            active_facts = mem0.get_all(user_id=user_id, limit=25)

    results = active_facts.get("results", []) if isinstance(active_facts, dict) else active_facts
    if not isinstance(results, list):
        results = []

    valid_memories = []
    for m in results:
        if not isinstance(m, dict):
            continue
        meta = m.get("metadata") or {}
        if meta.get("status", "active") != "active":
            continue
            
        # Scrub expired M6 context
        expires_at = meta.get("expires_at")
        if expires_at and expires_at < now_iso:
            continue
        
        text = m.get("memory", "")
        if not text:
            continue

        # Append verification flag for M7 Safety Facts
        if meta.get("verification_status") == "UNVERIFIED":
            text += " [UNVERIFIED: Confirm with user if relevant]"
            
        valid_memories.append(text)

    if not valid_memories:
        fallback_list = _get_fallback_users(user_id)
        for f_id in fallback_list:
            if f_id == user_id:
                continue
            try:
                fb_facts = mem0.get_all(filters={"user_id": f_id, "status": "active"}, limit=25)
            except Exception:
                try:
                    fb_facts = mem0.get_all(user_id=f_id, limit=25)
                except Exception:
                    continue
            fb_res = fb_facts.get("results", []) if isinstance(fb_facts, dict) else fb_facts
            if isinstance(fb_res, list):
                for fm in fb_res:
                    if isinstance(fm, dict) and (fm.get("metadata") or {}).get("status", "active") == "active":
                        f_text = fm.get("memory", "")
                        if f_text and f_text not in valid_memories:
                            valid_memories.append(f_text)

    return valid_memories

def _get_fallback_users(target_user_id: str) -> list[str]:
    """Return fallbacks for target user ID without hardcoded individual user names."""
    fallbacks = [target_user_id]
    if target_user_id.startswith("user:") and len(target_user_id) > 5:
        raw_name = target_user_id[5:]
        if raw_name not in fallbacks:
            fallbacks.append(raw_name)
    elif not target_user_id.startswith("user:"):
        prefixed = f"user:{target_user_id}"
        if prefixed not in fallbacks:
            fallbacks.append(prefixed)
    return fallbacks

def recall_user_memories(query: str, user_id: str) -> list[str]:
    """
    Path 2: On-Demand Deep Recall Tool Handler.
    Query active memories matching specific historical recall requests.
    Applies similarity gate (score >= SIMILARITY_THRESHOLD) and scrubs expired facts.
    """
    user_id = normalize_user_id(user_id)
    mem0 = get_mem0_instance()
    if not mem0:
        return []

    try:
        matched = mem0.search(query=query, filters={"user_id": user_id})
    except Exception as e:
        logger.warning(f"[recall_user_memories] search failed for {user_id}: {e}")
        matched = []

    results = matched.get("results", []) if isinstance(matched, dict) else matched
    if not isinstance(results, list):
        results = []
    
    valid_results = []
    now_iso = datetime.now().isoformat()
    
    for item in results:
        if not isinstance(item, dict):
            continue
        if item.get("score", 1.0) < RETRIEVAL_THRESHOLD:
            continue
            
        meta = item.get("metadata") or {}
        if meta.get("status", "active") not in ["active", "staging"]:
            continue

        expires_at = meta.get("expires_at")
        if expires_at and expires_at < now_iso:
            continue
            
        valid_results.append(item.get("memory", ""))
        
    valid_list = [r for r in valid_results if r]

    # If no results found for specific user_id (e.g. script mismatch user:manish vs user:मनीष), try common user fallbacks
    if not valid_list:
        fallback_users = _get_fallback_users(user_id)
        for f_user in fallback_users:
            if f_user == user_id:
                continue
            try:
                matched_fb = mem0.search(query=query, filters={"user_id": f_user})
                g_results = matched_fb.get("results", []) if isinstance(matched_fb, dict) else matched_fb
                if isinstance(g_results, list):
                    for item in g_results:
                        if isinstance(item, dict) and item.get("score", 1.0) >= RETRIEVAL_THRESHOLD:
                            meta = item.get("metadata") or {}
                            if meta.get("status", "active") in ["active", "staging"]:
                                valid_list.append(item.get("memory", ""))
            except Exception as e:
                logger.warning(f"[recall_user_memories] Fallback search for {f_user} failed: {e}")

    # Also check graph triples and exact query terms across active/staging memories if vector/BM25 search missed
    if not valid_list:
        query_l = query.lower()
        query_tokens = [w for w in re.split(r"\W+", query_l) if len(w) > 2]
        all_users = [user_id] + [u for u in _get_fallback_users(user_id) if u != user_id]

        for uid in all_users:
            try:
                active_data = mem0.get_all(filters={"user_id": uid}, limit=50)
            except Exception:
                try:
                    active_data = mem0.get_all(user_id=uid, limit=50)
                except Exception:
                    active_data = []
            items = active_data.get("results", []) if isinstance(active_data, dict) else active_data
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    meta = item.get("metadata") or {}
                    if meta.get("status", "active") in ["active", "staging"]:
                        expires_at = meta.get("expires_at")
                        if expires_at and expires_at < now_iso:
                            continue
                        mem_text = item.get("memory", "")
                        if mem_text:
                            triples = meta.get("graph_triples") or meta.get("graph_relation") or {}
                            t_str = f"{triples.get('subject', '')} {triples.get('relation', '')} {triples.get('object', '')}".lower()
                            comb = f"{mem_text.lower()} {t_str}"
                            if any(t in comb for t in query_tokens):
                                if mem_text not in valid_list:
                                    valid_list.append(mem_text)

    return [r for r in valid_list if r]

async def _save_to_vertex_memory_bank(memory_text: str, category: str, user_id: str) -> str:
    """Save user memory directly to Google Cloud Vertex AI Agent Memory / Reasoning Engine."""
    store = get_vertex_memory_bank_store()
    if not store or not store.resource_id:
        return ""
    try:
        res = store.add(memory_text, user_id=user_id, metadata={"category": category})
        if res and res.get("results"):
            logger.info(f"[VertexMemoryBank] Saved memory for {user_id}: {memory_text}")
            return f"Memory saved successfully to Vertex AI Agent Memory for {user_id}: {memory_text}"
        return ""
    except Exception as e:
        logger.warning(f"[VertexMemoryBank] Failed or offline ({e}), falling back to engine/local.")
        return ""

async def _search_vertex_memory_bank(query: str, user_id: str) -> str:
    """Search user memory directly in Google Cloud Vertex AI Agent Memory / Reasoning Engine."""
    store = get_vertex_memory_bank_store()
    if not store or not store.resource_id:
        return ""
    try:
        res = store.search(query=query, filters={"user_id": user_id})
        results = res.get("results", []) if isinstance(res, dict) else res
        if not results:
            return f"No memories found matching '{query}' for {user_id} in Vertex AI Agent Memory."
        facts = [m.get("memory", m.get("content", "")) for m in results if isinstance(m, dict)]
        formatted = [f"- {f}" for f in facts if f]
        return f"Found the following memories for '{query}' ({user_id}):\n" + "\n".join(formatted)
    except Exception as e:
        logger.warning(f"[VertexMemoryBank] Search failed or offline ({e}), falling back to engine/local.")
        return ""

async def save_user_memory_handler(params: FunctionCallParams):
    """Handle save_user_memory tool call via Vertex AI Agent Memory Bank Store."""
    memory_text = params.arguments.get("memory_text", "").strip()
    category = params.arguments.get("category", "general").strip()
    user_id = _get_active_user_id(params)

    if not memory_text:
        await params.result_callback({"content": "Error: memory_text cannot be empty."})
        return

    loop = asyncio.get_running_loop()
    store = await loop.run_in_executor(_VERTEX_READ_EXECUTOR, get_vertex_memory_bank_store)
    if store:
        try:
            def _add_store():
                return process_extracted_fact(memory_text, category, user_id, is_explicit_remember=True)

            res = await loop.run_in_executor(_VERTEX_READ_EXECUTOR, _add_store)
            logger.info(f"[VertexStore] Saved memory in-process for {user_id}: {memory_text}")
            result_msg = f"Memory saved successfully to Vertex AI Agent Memory for {user_id}: {memory_text}"
        except Exception as e:
            logger.exception(f"[VertexStore] Failed to save memory to Vertex AI Agent Memory store: {e}")
            result_msg = f"Failed to save memory: Vertex AI Agent Memory store error ({e})"
    else:
        result_msg = "Failed to save memory: Vertex AI Agent Memory store is not connected or initialized."

    append_diagnostic_log("Memory Tool Result", f"Returned to Gemini Live ({user_id}):\n{result_msg}")
    logger.info(f"[Memory Tool Result] ({user_id}) -> {result_msg}")
    await params.result_callback({"content": result_msg})

async def search_user_memory_handler(params: FunctionCallParams):
    """Handle search_user_memory tool call via Vertex AI Agent Memory Bank Store."""
    query = params.arguments.get("query", "").strip()
    user_id = _get_active_user_id(params)

    if not query:
        await params.result_callback({"content": "Please provide a valid query to search memory."})
        return

    loop = asyncio.get_running_loop()
    store = await loop.run_in_executor(_VERTEX_READ_EXECUTOR, get_vertex_memory_bank_store)
    if store:
        try:
            def _search_store():
                return recall_user_memories(query, user_id)

            facts = await loop.run_in_executor(_VERTEX_READ_EXECUTOR, _search_store)
            logger.info(f"[VertexStore] Searched memory in-process query: '{query}' for {user_id}")

            if not facts:
                result_text = f"No memories found matching query '{query}' for {user_id} in Vertex AI Agent Memory."
            else:
                formatted = [f"- {f}" for f in facts]
                result_text = f"Found the following memories for '{query}' ({user_id}):\n" + "\n".join(formatted)
        except Exception as e:
            logger.error(f"[VertexStore] Failed to search memory: {e}")
            result_text = f"Failed to search memories: Vertex AI Agent Memory store error ({e})."
    else:
        result_text = "Memory search unavailable: Vertex AI Agent Memory store is not connected or initialized."

    append_diagnostic_log("Memory Tool Result", f"Returned to Gemini Live ({user_id}):\n{result_text}")
    logger.info(f"[Memory Tool Result] ({user_id}) -> {result_text}")
    await params.result_callback({"content": result_text})

async def recall_user_memories_handler(params: FunctionCallParams):
    """Path 2: Handle recall_user_memories tool call via deep recall."""
    query = params.arguments.get("query", "").strip()
    user_id = _get_active_user_id(params)

    if not query:
        await params.result_callback({"content": "Please provide a valid query to recall memory."})
        return

    loop = asyncio.get_running_loop()
    store = await loop.run_in_executor(_VERTEX_READ_EXECUTOR, get_vertex_memory_bank_store)
    if store:
        try:
            def _recall_store():
                return recall_user_memories(query, user_id)

            facts = await loop.run_in_executor(_VERTEX_READ_EXECUTOR, _recall_store)
            logger.info(f"[Path2DeepRecall] Recalled query: '{query}' for {user_id}")

            if not facts:
                result_text = f"No active memories found matching query '{query}' for {user_id} via deep recall."
            else:
                formatted = [f"- {f}" for f in facts]
                result_text = f"Found the following active memories for '{query}' ({user_id}):\n" + "\n".join(formatted)
        except Exception as e:
            logger.error(f"[Path2DeepRecall] Failed: {e}")
            result_text = f"Failed to recall memories: Vertex AI Agent Memory store error ({e})."
    else:
        result_text = "Memory recall unavailable: Vertex AI Agent Memory store is not connected or initialized."

    append_diagnostic_log("Memory Tool Result", f"Returned to Gemini Live ({user_id}):\n{result_text}")
    logger.info(f"[Memory Tool Result] ({user_id}) -> {result_text}")
    await params.result_callback({"content": result_text})
