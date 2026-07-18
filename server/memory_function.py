import os
import json
import asyncio
import re
from datetime import datetime
from loguru import logger
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
import google.auth
import google.auth.transport.requests
import requests

def get_memory_file_path() -> str:
    """Return path to local fallback user memories storage file."""
    return os.path.join(os.path.dirname(__file__), "user_memories.json")

def get_memory_bank_config():
    """Fetch Memory Bank / Reasoning Engine resource configuration if present."""
    resource_id = os.getenv("MEMORY_BANK_RESOURCE_ID") or os.getenv("MEMORY_BANK_REASONING_ENGINE_ID")
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"

    if resource_id and not resource_id.startswith("projects/"):
        # Format as full resource path if short ID given
        resource_id = f"projects/{project_id}/locations/{location}/reasoningEngines/{resource_id}"

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
    """Handle save_user_memory tool call."""
    memory_text = params.arguments.get("memory_text", "").strip()
    category = params.arguments.get("category", "general").strip()

    if not memory_text:
        await params.result_callback({"content": "Error: memory_text cannot be empty."})
        return

    resource_id, project_id, location = get_memory_bank_config()

    if resource_id:
        # Call Vertex AI Agent Platform Memory Bank REST API
        try:
            loop = asyncio.get_running_loop()
            def _call_memory_bank_api():
                credentials, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                auth_req = google.auth.transport.requests.Request()
                credentials.refresh(auth_req)
                
                url = f"https://{location}-aiplatform.googleapis.com/v1beta1/{resource_id}/memories"
                headers = {
                    "Authorization": f"Bearer {credentials.token}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "fact": memory_text,
                    "scope": {"user_id": "default_user", "category": category}
                }
                res = requests.post(url, headers=headers, json=payload, timeout=10)
                res.raise_for_status()
                return res.json()

            api_res = await loop.run_in_executor(None, _call_memory_bank_api)
            logger.info(f"[MemoryBank] Saved via API: {memory_text}")
            result_msg = f"Memory saved successfully to Agent Platform Memory Bank: {memory_text}"
        except Exception as e:
            logger.error(f"[MemoryBank] API save failed: {e}")
            result_msg = f"Error saving to Agent Platform Memory Bank: {e}"
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
    """Handle search_user_memory tool call."""
    query = params.arguments.get("query", "").strip()

    if not query:
        await params.result_callback({"content": "Please provide a valid query to search memory."})
        return

    resource_id, project_id, location = get_memory_bank_config()

    if resource_id:
        try:
            loop = asyncio.get_running_loop()
            def _query_memory_bank_api():
                credentials, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                auth_req = google.auth.transport.requests.Request()
                credentials.refresh(auth_req)
                
                url = f"https://{location}-aiplatform.googleapis.com/v1beta1/{resource_id}/memories:retrieve"
                headers = {
                    "Authorization": f"Bearer {credentials.token}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "query": query,
                    "scope": {"user_id": "default_user"}
                }
                res = requests.post(url, headers=headers, json=payload, timeout=10)
                res.raise_for_status()
                return res.json()

            api_res = await loop.run_in_executor(None, _query_memory_bank_api)
            logger.info(f"[MemoryBank] Searched via API query: {query}")
            retrieved = api_res.get("retrievedMemories", []) or api_res.get("memories", [])
            facts = []
            for item in retrieved:
                m = item.get("memory", item) if isinstance(item, dict) else item
                fact_str = m.get("fact") or m.get("text") if isinstance(m, dict) else str(m)
                if fact_str:
                    facts.append(fact_str)

            if not facts:
                result_text = f"No memories found matching query '{query}' in Agent Platform Memory Bank."
            else:
                formatted = [f"- {f}" for f in facts]
                result_text = f"Found the following memories in Agent Platform Memory Bank for '{query}':\n" + "\n".join(formatted)
        except Exception as e:
            logger.error(f"[MemoryBank] API search failed: {e}")
            result_text = f"Error querying Agent Platform Memory Bank: {e}"
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
