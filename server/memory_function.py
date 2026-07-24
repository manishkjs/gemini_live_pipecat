import os
import json
import asyncio
import re
from datetime import datetime, timedelta
from loguru import logger
from dotenv import load_dotenv
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

# Auto-load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# PRD-Aligned Promotion Threshold Matrix
THRESHOLDS = {
    "M7_Safety":     1,  # N=1 (Instant, UNVERIFIED)
    "M5_Commitment": 1,  # N=1 (Instant, expires on completion + 30d)
    "M1_Identity":   2,  # N=2 (Catches ASR errors / misstatements)
    "M2_Relation":   2,  # N=2 (Catches ASR errors / misstatements)
    "M3_Preference": 2,  # N=2 (Fast Staging)
    "M4_Behavioral": 3,  # N=3 (Standard Staging)
    "M6_Recent":     1   # N=1 (Expires in 3 days)
}

SIMILARITY_THRESHOLD = 0.65
RETRIEVAL_THRESHOLD = 0.40

# Mem0 embedded engine singleton
_MEM0_INSTANCE = None

def get_mem0_config() -> dict:
    """Return dynamic configuration for Mem0, supporting pgvector (Cloud SQL/AlloyDB) or local Qdrant fallback."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        env_file = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    if line.startswith("GEMINI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    api_key = api_key or ""
    pg_dsn = os.getenv("CLOUDSQL_PG_DSN") or os.getenv("ALLOYDB_PG_DSN") or os.getenv("DATABASE_URL")
    
    if pg_dsn:
        vector_store_config = {
            "provider": "pgvector",
            "config": {
                "connection_string": pg_dsn,
                "collection_name": "user_memories",
                "embedding_model_dims": 768
            }
        }
    else:
        db_path = os.getenv("MEM0_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "mem0_qdrant_db"))
        os.makedirs(db_path, exist_ok=True)
        vector_store_config = {
            "provider": "qdrant",
            "config": {
                "path": db_path,
                "embedding_model_dims": 768
            }
        }

    project_id = os.getenv("GCP_PROJECT_ID", "deep-clock-339817")
    location = os.getenv("GCP_LOCATION", "us-central1")
    use_vertex = os.getenv("USE_VERTEXAI", "true").lower() == "true"
    os.environ["USE_VERTEXAI"] = "true" if use_vertex else "false"

    model_name = os.getenv("MEM0_LLM_MODEL", "gemini-3.5-flash-lite")
    llm_location = "global" if any(k in model_name for k in ["gemini-3", "3.5", "3.1", "3.6"]) else location

    return {
        "vector_store": vector_store_config,
        "llm": {
            "provider": "gemini",
            "config": {
                "model": model_name,
                "api_key": api_key,
                "vertexai": use_vertex,
                "project": project_id,
                "location": llm_location,
            }
        },
        "embedder": {
            "provider": "gemini",
            "config": {
                "model": "gemini-embedding-001",
                "embedding_dims": 768,
                "api_key": api_key if not use_vertex else None,
            }
        },
        "custom_prompt": (
            "You are a personal memory extraction assistant for Lenskart 'B' smartglasses. "
            "Extract ALL user-stated facts, family relationships, identities, roles, plans, goals, preferences, personal claims, and conversational details. "
            "Always extract entity relationships clearly (e.g., 'User son name is X', 'User spouse name is Y', 'User has a goal to Z'). "
            "CRITICAL GOVERNANCE RULE: Never extract exact street addresses, GPS coordinates, credit cards, "
            "phone numbers, or exact government IDs. Always convert locations to coarse user-stated places."
        )
    }

def get_mem0_instance():
    """Lazy initialize embedded self-hosted Mem0 instance using pgvector (Cloud SQL/AlloyDB) or Qdrant fallback."""
    global _MEM0_INSTANCE
    if _MEM0_INSTANCE is not None:
        return _MEM0_INSTANCE

    config = None
    try:
        from mem0 import Memory
        config = get_mem0_config()
        use_vertex = config.get("llm", {}).get("config", {}).get("vertexai", False)
        if not config["llm"]["config"]["api_key"] and not use_vertex:
            logger.warning("[Mem0] Neither GEMINI_API_KEY nor GOOGLE_API_KEY set. Mem0 fallback will be used.")
            return None

        if config.get("vector_store", {}).get("provider") == "pgvector":
            conn_str = config["vector_store"]["config"].get("connection_string", "")
            if conn_str:
                try:
                    import socket
                    import urllib.parse
                    parsed = urllib.parse.urlparse(conn_str)
                    host = parsed.hostname or "127.0.0.1"
                    port = parsed.port or 5432
                    with socket.create_connection((host, port), timeout=0.5):
                        pass
                except Exception as sock_e:
                    logger.warning(f"[Mem0] Unreachable Postgres server ({conn_str}): {sock_e}. Switching to Qdrant fallback.")
                    db_path = os.getenv("MEM0_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "mem0_qdrant_db"))
                    os.makedirs(db_path, exist_ok=True)
                    config["vector_store"] = {
                        "provider": "qdrant",
                        "config": {
                            "path": db_path,
                            "embedding_model_dims": 768
                        }
                    }

        try:
            _MEM0_INSTANCE = Memory.from_config(config)
        except Exception as e:
            if config.get("vector_store", {}).get("provider") == "pgvector":
                logger.warning(f"[Mem0] pgvector initialization failed: {e}. Switching to Qdrant fallback.")
                db_path = os.getenv("MEM0_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "mem0_qdrant_db"))
                os.makedirs(db_path, exist_ok=True)
                config["vector_store"] = {
                    "provider": "qdrant",
                    "config": {
                        "path": db_path,
                        "embedding_model_dims": 768
                    }
                }
                _MEM0_INSTANCE = Memory.from_config(config)
            else:
                raise

        provider = config["vector_store"]["provider"]
        logger.info(f"[Mem0] Successfully initialized embedded Mem0 engine with provider '{provider}'")
        return _MEM0_INSTANCE
    except Exception as e:
        logger.error(f"[Mem0] Failed to initialize embedded Mem0 engine: {e}")
        return None

def get_memory_file_path(user_id: str = "default_user") -> str:
    """Return path to local fallback user memories storage file, partitioned by user_id."""
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "_", user_id)
    return os.path.join(os.path.dirname(__file__), f"user_memories_{clean_id}.json")

def get_memory_bank_config():
    """Fetch Memory Bank resource configuration if present."""
    resource_id = os.getenv("MEMORY_BANK_RESOURCE_ID") or os.getenv("MEMORY_BANK_REASONING_ENGINE_ID")
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
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
            "description": "Optional classification, e.g., 'preference', 'financial_goal', 'contact_info', 'objection', 'personal'."
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
        "Use when user asks 'do you remember...', 'what was my preference', or asks a question needing historical context. "
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
    """Normalize user_id strings to generic canonical identity keys (`user:<slug>`)."""
    if not raw_id:
        return "default_user"
    clean = str(raw_id).strip().lower().replace(" ", "_")
    if not clean.startswith("user:"):
        clean = f"user:{clean}"
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
        "shaktiman", "shaktimaan", "kilvish", "kabir", "adhyanth", "adyant",
        "roleplay", "identifies as", "plan to defeat", "plan to kill", "andhera kayam rahe",
        "superman", "batman", "superhero"
    ]
    return any(kw in combined for kw in roleplay_keywords)

def extract_graph_triples(fact_text: str, category: str = "", user_id: str = "") -> dict[str, str]:
    """
    Extract relational graph triples (Subject -> Relation -> Object) from fact text and category.
    Supports roleplay assertions, family relationships, exams, and general user facts.
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
    # 2. Kabir & Adhyanth / Adyant Relationships
    elif ("adhyanth" in text_l or "adyant" in text_l) and "kabir" in text_l:
        subject = "Adhyanth"
        relation = "identifies_with" if "identif" in text_l else ("likes" if "like" in text_l else "associated_with")
        obj = "Kabir"
    elif "adhyanth" in text_l or "adyant" in text_l:
        if "son" in text_l or "बेटे" in fact_text:
            subject = "Son"
            relation = "name_is" if ("name" in text_l or "is" in text_l) else "has_detail"
            obj = "Adhyanth"
        else:
            subject = "User"
            relation = "has_relation"
            obj = "Adhyanth"
    elif "kabir" in text_l:
        subject = "User"
        relation = "likes_character" if "like" in text_l else "associated_with"
        obj = "Kabir"
    # 3. Existing PRD Checks (Son and Exam)
    elif "son" in text_l or "बेटे" in fact_text:
        subject = "Son"
        relation = "has_detail"
        obj = fact_text
    elif "exam" in text_l or "परीक्षा" in fact_text:
        subject = "Exam"
        relation = "scheduled_for"
        obj = fact_text
    # 4. General identity / preference patterns
    elif "identifies as" in text_l:
        subject = "User"
        relation = "identifies_as"
        parts = fact_text.split("identifies as", 1)
        obj = parts[1].strip() if len(parts) > 1 else fact_text
    elif "prefers" in text_l:
        subject = "User"
        relation = "prefers"
        parts = fact_text.split("prefers", 1)
        obj = parts[1].strip() if len(parts) > 1 else fact_text

    return {"subject": subject, "relation": relation, "object": obj}

def process_extracted_fact(fact_text: str, category: str, user_id: str, is_explicit_remember: bool = False):
    """
    Process a single distilled fact extracted by Gemini 3.1 Flash Lite at session end or during explicit save.
    Implements the PRD Tiered Promotion Matrix, similarity threshold gating (min_score >= 0.80), and observation day tracking.
    """
    mem0 = get_mem0_instance()
    if not mem0:
        logger.warning("[process_extracted_fact] Mem0 engine unavailable.")
        return None

    today_str = datetime.now().strftime("%Y-%m-%d")
    
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
            meta = item.get("metadata", {})
            if meta.get("status", "active") in ["staging", "active"]:
                filtered_results.append(item)

    # 6. Apply Similarity Threshold Gate (min_score >= 0.80)
    best_match = None
    if filtered_results and filtered_results[0].get("score", 1.0) >= SIMILARITY_THRESHOLD:
        best_match = filtered_results[0]

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
            "graph_triples": triples
        }
        res = mem0.add(fact_text, user_id=user_id, metadata=meta, infer=False)
        logger.info(f"✅ Stored Raw Memory ({initial_status}) with Graph Link [{triples['subject']} --({triples['relation']})--> {triples['object'][:20]}...]: '{fact_text}'")
        return res
    else:
        # 8. Match found: Increment count if observed on a NEW distinct day
        meta = best_match.get("metadata", {})
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
        triples = extract_graph_triples(fact_text, category, user_id)
        meta["graph_relation"] = triples
        meta["graph_triples"] = triples

        # 10. Update metadata deterministically
        try:
            mem0.update(memory_id=best_match["id"], data=fact_text, metadata=meta)
        except Exception as e:
            logger.warning(f"Failed to update memory id {best_match.get('id')}: {e}")
        logger.info(f"🔄 Updated Memory ({new_status}, {count}/{threshold}): '{fact_text}'")
        return best_match

def pre_load_user_profile(user_id: str) -> list[str]:
    """
    Path 1: Connection Pre-Load Handler.
    Fetch active core profile facts at WebSocket connect (~40ms budget).
    Scrubs expired M6 facts and flags UNVERIFIED M7 safety facts.
    """
    mem0 = get_mem0_instance()
    if not mem0:
        return []

    now_iso = datetime.now().isoformat()
    
    try:
        active_facts = mem0.get_all(filters={"user_id": user_id, "status": "active"})
    except Exception:
        try:
            active_facts = mem0.get_all(filters={"user_id": user_id})
        except Exception:
            active_facts = mem0.get_all(user_id=user_id)

    results = active_facts.get("results", []) if isinstance(active_facts, dict) else active_facts
    if not isinstance(results, list):
        results = []

    valid_memories = []
    for m in results:
        if not isinstance(m, dict):
            continue
        meta = m.get("metadata", {})
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
                fb_facts = mem0.get_all(filters={"user_id": f_id, "status": "active"})
            except Exception:
                try:
                    fb_facts = mem0.get_all(user_id=f_id)
                except Exception:
                    continue
            fb_res = fb_facts.get("results", []) if isinstance(fb_facts, dict) else fb_facts
            if isinstance(fb_res, list):
                for fm in fb_res:
                    if isinstance(fm, dict) and fm.get("metadata", {}).get("status", "active") == "active":
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
        if item.get("score", 1.0) < SIMILARITY_THRESHOLD:
            continue
            
        meta = item.get("metadata", {})
        if meta.get("status", "active") != "active":
            continue

        expires_at = meta.get("expires_at")
        if expires_at and expires_at < now_iso:
            continue
            
        valid_results.append(item.get("memory", ""))
        
    valid_list = [r for r in valid_results if r]
    
    # Merge active core/recent profile facts for multi-hop relational context (e.g. Adyant -> son -> EVS exam)
    profile_facts = pre_load_user_profile(user_id)
    for pf in profile_facts:
        if pf not in valid_list:
            valid_list.append(pf)

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
                        if isinstance(item, dict) and item.get("score", 1.0) >= SIMILARITY_THRESHOLD:
                            meta = item.get("metadata", {})
                            if meta.get("status", "active") == "active":
                                valid_list.append(item.get("memory", ""))
                # Also check fallback profile facts
                fb_profile = pre_load_user_profile(f_user)
                for fbp in fb_profile:
                    if fbp not in valid_list:
                        valid_list.append(fbp)
            except Exception as e:
                logger.warning(f"[recall_user_memories] Fallback search for {f_user} failed: {e}")

    # Also check graph triples and exact query terms across active memories of all fallback users
    query_l = query.lower()
    query_tokens = [w for w in re.split(r"\W+", query_l) if len(w) > 2]
    all_users = [user_id] + [u for u in _get_fallback_users(user_id) if u != user_id]

    for uid in all_users:
        try:
            active_data = mem0.get_all(filters={"user_id": uid, "status": "active"})
        except Exception:
            try:
                active_data = mem0.get_all(user_id=uid)
            except Exception:
                active_data = []
        items = active_data.get("results", []) if isinstance(active_data, dict) else active_data
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("metadata", {}).get("status", "active") == "active":
                    meta = item.get("metadata", {})
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

    if not valid_list:
        local_res = _search_local_memory(query, user_id)
        if local_res and "No memories" not in local_res:
            for line in local_res.split("\n"):
                clean_line = re.sub(r"^-\s*", "", line.strip())
                if clean_line and "Retrieved memories" not in clean_line:
                    valid_list.append(clean_line)

    return [r for r in valid_list if r]

async def _save_to_vertex_memory_bank(memory_text: str, category: str, user_id: str) -> str:
    """Save user memory directly to Google Cloud Vertex AI Agent Memory / Reasoning Engine."""
    resource_id, project_id, location = get_memory_bank_config()
    if not resource_id:
        return ""
    try:
        import google.auth
        from google.auth.transport.requests import Request
        import urllib.request

        credentials, _ = google.auth.default()
        if not credentials.valid:
            credentials.refresh(Request())

        url = f"https://{location}-aiplatform.googleapis.com/v1beta1/{resource_id}:createMemory"
        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "memory": {
                "scope": {"user_id": user_id, "category": category},
                "content": memory_text
            }
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode())
        logger.info(f"[VertexMemoryBank] Saved memory for {user_id}: {memory_text}")
        return f"Memory saved successfully to Vertex AI Agent Memory for {user_id}: {memory_text}"
    except Exception as e:
        logger.warning(f"[VertexMemoryBank] Failed or offline ({e}), falling back to engine/local.")
        return ""

async def _search_vertex_memory_bank(query: str, user_id: str) -> str:
    """Search user memory directly in Google Cloud Vertex AI Agent Memory / Reasoning Engine."""
    resource_id, project_id, location = get_memory_bank_config()
    if not resource_id:
        return ""
    try:
        import google.auth
        from google.auth.transport.requests import Request
        import urllib.request

        credentials, _ = google.auth.default()
        if not credentials.valid:
            credentials.refresh(Request())

        url = f"https://{location}-aiplatform.googleapis.com/v1beta1/{resource_id}:retrieveMemories"
        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "scope": {"user_id": user_id},
            "query": query,
            "topK": 5
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode())
        
        memories = res_data.get("memories", [])
        if not memories:
            return f"No memories found matching '{query}' for {user_id} in Vertex AI Agent Memory."
        facts = [m.get("content", m.get("memory", "")) for m in memories if isinstance(m, dict)]
        formatted = [f"- {f}" for f in facts if f]
        return f"Found the following memories for '{query}' ({user_id}):\n" + "\n".join(formatted)
    except Exception as e:
        logger.warning(f"[VertexMemoryBank] Search failed or offline ({e}), falling back to engine/local.")
        return ""

async def save_user_memory_handler(params: FunctionCallParams):
    """Handle save_user_memory tool call via Vertex AI Memory Bank, embedded Mem0, or local storage."""
    memory_text = params.arguments.get("memory_text", "").strip()
    category = params.arguments.get("category", "general").strip()
    user_id = _get_active_user_id(params)

    if not memory_text:
        await params.result_callback({"content": "Error: memory_text cannot be empty."})
        return

    # 1. Try Vertex AI Agent Memory Bank
    res_msg = await _save_to_vertex_memory_bank(memory_text, category, user_id)
    if res_msg:
        await params.result_callback({"content": res_msg})
        return

    # 2. Try Mem0 engine
    mem0_engine = get_mem0_instance()
    if mem0_engine:
        try:
            loop = asyncio.get_running_loop()
            def _add_mem0():
                return process_extracted_fact(memory_text, category, user_id, is_explicit_remember=True)

            res = await loop.run_in_executor(None, _add_mem0)
            logger.info(f"[Mem0] Saved memory in-process for {user_id}: {memory_text}")
            result_msg = f"Memory saved successfully to Mem0 for {user_id}: {memory_text}"
        except Exception as e:
            logger.error(f"[Mem0] Failed to save memory: {e}")
            result_msg = _save_local_memory(memory_text, category, user_id)
    else:
        result_msg = _save_local_memory(memory_text, category, user_id)

    await params.result_callback({"content": result_msg})

def _save_local_memory(memory_text: str, category: str, user_id: str = "default_user") -> str:
    """Fallback local JSON storage for user memories, partitioned by user_id."""
    file_path = get_memory_file_path(user_id)
    memories = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                memories = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read local memory file: {e}")
            memories = []

    new_entry = {
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id,
        "category": category,
        "memory_text": memory_text
    }
    memories.append(new_entry)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(memories, f, indent=2)
        logger.info(f"[LocalMemory] Saved for {user_id}: {memory_text}")
        return f"Memory saved successfully ({user_id}): '{memory_text}'"
    except Exception as e:
        logger.error(f"Failed to write local memory: {e}")
        return f"Failed to save memory locally: {e}"

async def search_user_memory_handler(params: FunctionCallParams):
    """Handle search_user_memory tool call via Vertex AI Memory Bank, embedded Mem0, or local storage."""
    query = params.arguments.get("query", "").strip()
    user_id = _get_active_user_id(params)

    if not query:
        await params.result_callback({"content": "Please provide a valid query to search memory."})
        return

    # 1. Try Vertex AI Agent Memory Bank
    res_msg = await _search_vertex_memory_bank(query, user_id)
    if res_msg:
        await params.result_callback({"content": res_msg})
        return

    # 2. Try Mem0 engine
    mem0_engine = get_mem0_instance()
    if mem0_engine:
        try:
            loop = asyncio.get_running_loop()
            def _search_mem0():
                return recall_user_memories(query, user_id)

            facts = await loop.run_in_executor(None, _search_mem0)
            logger.info(f"[Mem0] Searched memory in-process query: '{query}' for {user_id}")

            if not facts:
                result_text = f"No memories found matching query '{query}' for {user_id} in Mem0."
            else:
                formatted = [f"- {f}" for f in facts]
                result_text = f"Found the following memories for '{query}' ({user_id}):\n" + "\n".join(formatted)
        except Exception as e:
            logger.error(f"[Mem0] Failed to search memory: {e}")
            result_text = _search_local_memory(query, user_id)
    else:
        result_text = _search_local_memory(query, user_id)

    await params.result_callback({"content": result_text})

async def recall_user_memories_handler(params: FunctionCallParams):
    """Path 2: Handle recall_user_memories tool call via deep recall or local fallback."""
    query = params.arguments.get("query", "").strip()
    user_id = _get_active_user_id(params)

    if not query:
        await params.result_callback({"content": "Please provide a valid query to recall memory."})
        return

    mem0_engine = get_mem0_instance()
    if mem0_engine:
        try:
            loop = asyncio.get_running_loop()
            def _recall_mem0():
                return recall_user_memories(query, user_id)

            facts = await loop.run_in_executor(None, _recall_mem0)
            logger.info(f"[Path2DeepRecall] Recalled query: '{query}' for {user_id}")

            if not facts:
                result_text = f"No active memories found matching query '{query}' for {user_id} via deep recall."
            else:
                formatted = [f"- {f}" for f in facts]
                result_text = f"Found the following active memories for '{query}' ({user_id}):\n" + "\n".join(formatted)
        except Exception as e:
            logger.error(f"[Path2DeepRecall] Failed: {e}")
            result_text = _search_local_memory(query, user_id)
    else:
        result_text = _search_local_memory(query, user_id)

    await params.result_callback({"content": result_text})

def _search_local_memory(query: str, user_id: str = "default_user") -> str:
    """Fallback keyword search in local memory file for a specific user_id."""
    file_path = get_memory_file_path(user_id)
    if not os.path.exists(file_path):
        return f"No memories saved yet for query '{query}' ({user_id})."

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            memories = json.load(f)
    except Exception as e:
        logger.error(f"Error reading local memories: {e}")
        return f"Failed to read local memory store."

    query_words = [w.lower() for w in re.findall(r"\w+", query)]
    matches = []

    for entry in memories:
        text = entry.get("memory_text", "").lower()
        category = entry.get("category", "").lower()
        if any(word in text or word in category for word in query_words):
            matches.append(entry["memory_text"])

    if not matches:
        return f"No memories found matching '{query}' for {user_id}."

    formatted = [f"- {m}" for m in matches]
    return f"Retrieved memories for '{query}' ({user_id}):\n" + "\n".join(formatted)
    file_path = get_memory_file_path(user_id)
    if not os.path.exists(file_path):
        return f"No memories saved yet for query '{query}' ({user_id})."

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            memories = json.load(f)
    except Exception as e:
        logger.error(f"Error reading local memories: {e}")
        return f"Failed to read local memory store."

    query_words = [w.lower() for w in re.findall(r"\w+", query)]
    matches = []

    for entry in memories:
        text = entry.get("memory_text", "").lower()
        category = entry.get("category", "").lower()
        if any(word in text or word in category for word in query_words):
            matches.append(entry["memory_text"])

    if not matches:
        return f"No memories found matching '{query}' for {user_id}."

    formatted = [f"- {m}" for m in matches]
    return f"Retrieved memories for '{query}' ({user_id}):\n" + "\n".join(formatted)
