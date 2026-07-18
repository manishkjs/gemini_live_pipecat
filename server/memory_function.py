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
                    "model": "gemini-2.5-flash",
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

def get_memory_file_path() -> str:
    """Return path to local fallback user memories storage file."""
    return os.path.join(os.path.dirname(__file__), "user_memories.json")

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
        }
    },
    required=["query"]
)

async def save_user_memory_handler(params: FunctionCallParams):
    """Handle save_user_memory tool call via embedded Mem0 engine."""
    memory_text = params.arguments.get("memory_text", "").strip()
    category = params.arguments.get("category", "general").strip()

    if not memory_text:
        await params.result_callback({"content": "Error: memory_text cannot be empty."})
        return

    mem0_engine = get_mem0_instance()

    if mem0_engine:
        try:
            loop = asyncio.get_running_loop()
            def _add_mem0():
                return mem0_engine.add(memory_text, user_id="default_user", metadata={"category": category})

            res = await loop.run_in_executor(None, _add_mem0)
            logger.info(f"[Mem0] Saved memory in-process: {memory_text}")
            result_msg = f"Memory saved successfully to Mem0: {memory_text}"
        except Exception as e:
            logger.error(f"[Mem0] Failed to save memory: {e}")
            result_msg = _save_local_memory(memory_text, category)
    else:
        result_msg = _save_local_memory(memory_text, category)

    await params.result_callback({"content": result_msg})

def _save_local_memory(memory_text: str, category: str) -> str:
    """Fallback local JSON storage for user memories."""
    file_path = get_memory_file_path()
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
        "category": category,
        "memory_text": memory_text
    }
    memories.append(new_entry)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(memories, f, indent=2)
        logger.info(f"[LocalMemory] Saved: {memory_text}")
        return f"Memory saved successfully: '{memory_text}'"
    except Exception as e:
        logger.error(f"Failed to write local memory: {e}")
        return f"Failed to save memory locally: {e}"

async def search_user_memory_handler(params: FunctionCallParams):
    """Handle search_user_memory tool call via embedded Mem0 engine."""
    query = params.arguments.get("query", "").strip()

    if not query:
        await params.result_callback({"content": "Please provide a valid query to search memory."})
        return

    mem0_engine = get_mem0_instance()

    if mem0_engine:
        try:
            loop = asyncio.get_running_loop()
            def _search_mem0():
                return mem0_engine.search(query, filters={"user_id": "default_user"})

            res = await loop.run_in_executor(None, _search_mem0)
            logger.info(f"[Mem0] Searched memory in-process query: '{query}'")

            results_list = res.get("results", []) if isinstance(res, dict) else res
            facts = []
            for item in results_list:
                if isinstance(item, dict) and "memory" in item:
                    facts.append(item["memory"])
                elif isinstance(item, str):
                    facts.append(item)

            if not facts:
                result_text = f"No memories found matching query '{query}' in Mem0."
            else:
                formatted = [f"- {f}" for f in facts]
                result_text = f"Found the following memories for '{query}':\n" + "\n".join(formatted)
        except Exception as e:
            logger.error(f"[Mem0] Failed to search memory: {e}")
            result_text = _search_local_memory(query)
    else:
        result_text = _search_local_memory(query)

    await params.result_callback({"content": result_text})

def _search_local_memory(query: str) -> str:
    """Fallback keyword search in local memory file."""
    file_path = get_memory_file_path()
    if not os.path.exists(file_path):
        return f"No memories saved yet for query '{query}'."

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
        return f"No memories found matching '{query}'."

    formatted = [f"- {m}" for m in matches]
    return f"Retrieved memories for '{query}':\n" + "\n".join(formatted)
