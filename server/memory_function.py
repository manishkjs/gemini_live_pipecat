import os
import json
import asyncio
import re
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

# Auto-load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Mem0 embedded engine singleton
_MEM0_INSTANCE = None

def get_mem0_instance():
    """Lazy initialize embedded self-hosted Mem0 instance using Qdrant local vector store & Gemini LLM/Embedder."""
    global _MEM0_INSTANCE
    if _MEM0_INSTANCE is not None:
        return _MEM0_INSTANCE

    try:
        from mem0 import Memory
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("[Mem0] Neither GEMINI_API_KEY nor GOOGLE_API_KEY set. Mem0 fallback will be used.")
            return None

        db_path = os.getenv("MEM0_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "mem0_qdrant_db"))
        os.makedirs(db_path, exist_ok=True)

        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": db_path,
                    "embedding_model_dims": 768
                }
            },
            "llm": {
                "provider": "gemini",
                "config": {
                    "model": "gemini-3.1-flash-lite",
                    "api_key": api_key
                }
            },
            "embedder": {
                "provider": "gemini",
                "config": {
                    "model": "models/gemini-embedding-001",
                    "embedding_dims": 768,
                    "api_key": api_key
                }
            }
        }

        _MEM0_INSTANCE = Memory.from_config(config)
        logger.info(f"[Mem0] Successfully initialized embedded self-hosted Mem0 engine at '{db_path}'")
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
        "Use when user asks 'do you remember...', 'what was my preference', or to recall context from previous interactions."
    ),
    properties={
        "query": {
            "type": "string",
            "description": "The search query to match against stored user memories."
        },
        "user_id": {
            "type": "string",
            "description": "The unique identity key or name of the user being spoken with (e.g. 'user:rohan')."
        }
    },
    required=["query"]
)

def _get_active_user_id(params: FunctionCallParams) -> str:
    """Extract user_id from arguments, session params, environment, or default."""
    if params and hasattr(params, "arguments") and params.arguments.get("user_id"):
        return str(params.arguments.get("user_id")).strip().lower()
    return os.getenv("ACTIVE_USER_ID", "default_user").strip().lower()

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
                # Pass infer=False for raw deterministic insertion when storing pre-extracted facts
                return mem0_engine.add(memory_text, user_id=user_id, metadata={"category": category}, infer=False)

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
                return mem0_engine.search(query, filters={"user_id": user_id})

            res = await loop.run_in_executor(None, _search_mem0)
            logger.info(f"[Mem0] Searched memory in-process query: '{query}' for {user_id}")

            results_list = res.get("results", []) if isinstance(res, dict) else res
            facts = []
            for item in results_list:
                if isinstance(item, dict) and "memory" in item:
                    facts.append(item["memory"])
                elif isinstance(item, str):
                    facts.append(item)

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
