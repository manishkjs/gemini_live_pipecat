# Agent Memory Bank Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate Agent Memory capabilities (`save_user_memory` and `search_user_memory`) into the Gemini Live Pipecat voice agent using Google Cloud Agent Platform Memory Bank REST API with seamless local persistent JSON fallback.

**Architecture:** 
1. Create `server/memory_function.py` containing function schemas for `save_user_memory` and `search_user_memory`. The handler attempts to call Google Cloud Memory Bank REST API (`memories:generate` / `memories` / `memories:retrieve`) using ADC credentials from `google.auth` if `MEMORY_BANK_RESOURCE_ID` or `MEMORY_BANK_REASONING_ENGINE_ID` is configured. If not configured or unavailable, it falls back to a structured local persistent memory store (`server/user_memories.json`).
2. Update `server/agent_live.py` to register memory schemas and handlers, inject system prompt instructions for active memory usage, and handle memory responses in `_send_consolidated_results`.
3. Update `server/.env.example` and `server/system_prompt.py` to document environment variables and memory instructions.

**Tech Stack:** Python 3.13, Pipecat AI, Google Cloud Vertex AI / Agent Platform REST API, `google.auth`, `requests`, `FastAPI`.

---

### Task 1: Create Memory Function Module (`server/memory_function.py`)

**Files:**
- Create: `server/memory_function.py`
- Test: `server/test_memory_function.py`

**Step 1: Write the failing test**

```python
import pytest
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch
from memory_function import (
    save_user_memory_schema,
    search_user_memory_schema,
    save_user_memory_handler,
    search_user_memory_handler,
    get_memory_file_path,
)

@pytest.mark.asyncio
async def test_save_and_search_local_memory(tmp_path, monkeypatch):
    test_file = tmp_path / "user_memories.json"
    monkeypatch.setattr("memory_function.get_memory_file_path", lambda: str(test_file))

    # Test saving
    mock_cb_save = AsyncMock()
    params_save = MagicMock()
    params_save.arguments = {
        "memory_text": "User prefers a 12-month tenure for loan",
        "category": "preference"
    }
    params_save.result_callback = mock_cb_save

    await save_user_memory_handler(params_save)
    mock_cb_save.assert_called_once()
    assert "Memory saved" in str(mock_cb_save.call_args)

    # Test searching
    mock_cb_search = AsyncMock()
    params_search = MagicMock()
    params_search.arguments = {"query": "tenure"}
    params_search.result_callback = mock_cb_search

    await search_user_memory_handler(params_search)
    mock_cb_search.assert_called_once()
    assert "12-month tenure" in str(mock_cb_search.call_args)
```

**Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest server/test_memory_function.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memory_function'`

**Step 3: Implement `server/memory_function.py`**

Create `server/memory_function.py` with:
- `save_user_memory_schema`: `FunctionSchema` defining `memory_text` (required string) and `category` (optional string).
- `search_user_memory_schema`: `FunctionSchema` defining `query` (required string).
- `save_user_memory_handler(params)`: Calls Vertex AI Agent Platform Memory Bank REST API (`/v1beta1/{parent}/memories`) using `google.auth.default()` if `MEMORY_BANK_REASONING_ENGINE_ID` / `MEMORY_BANK_RESOURCE_ID` is set, else appends to local JSON file `server/user_memories.json`.
- `search_user_memory_handler(params)`: Queries Memory Bank REST API (`/v1beta1/{parent}/memories:retrieve`) if configured, else performs keyword match on local JSON file.

**Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest server/test_memory_function.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/memory_function.py server/test_memory_function.py
git commit -m "feat(memory): add memory_function module with Memory Bank API & local persistent store"
```

---

### Task 2: Integrate Memory Tools into Agent Live Pipeline (`server/agent_live.py`)

**Files:**
- Modify: `server/agent_live.py:500-580`
- Modify: `server/system_prompt.py`
- Modify: `server/.env.example`

**Step 1: Write failing integration test**

Create `server/test_agent_memory_integration.py` to verify tool registration and batching logic for `save_user_memory` and `search_user_memory`.

**Step 2: Run test to verify failure**

Run: `./venv/bin/pytest server/test_agent_memory_integration.py -v`
Expected: FAIL

**Step 3: Update `agent_live.py` and system prompt**

1. Import `save_user_memory_schema`, `search_user_memory_schema`, `save_user_memory_handler`, `search_user_memory_handler` from `memory_function`.
2. Add memory schemas to `ToolsSchema` in `run_agent_live`:
   ```python
   tools = ToolsSchema(
       standard_tools=[
           FunctionSchema(name="get_current_time", description="Get the current time.", properties={}, required=[]),
           search_knowledge_base_schema,
           save_user_memory_schema,
           search_user_memory_schema,
       ]
   )
   ```
3. Register functions with LLM service:
   ```python
   llm.register_function("save_user_memory", save_user_memory_handler)
   llm.register_function("search_user_memory", search_user_memory_handler)
   ```
4. Update `_send_consolidated_results` in `GeminiSessionLoggerMixin` to properly format and send memory tool results alongside RAG and time tools.
5. Update `SYSTEM_PROMPT` in `system_prompt.py` to include instructions on when to save user preferences/facts and search memory.

**Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest server/test_agent_memory_integration.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/agent_live.py server/system_prompt.py server/.env.example server/test_agent_memory_integration.py
git commit -m "feat(agent): register agent memory tools with Gemini Live pipeline and update system instructions"
```

---

### Task 3: End-to-End Local Verification

**Step 1: Run pytest suite**

Run: `./venv/bin/pytest server/ -v`
Expected: ALL PASS

**Step 2: Verify git status**

Run: `git status`
Expected: Clean working tree on `rag` branch with new commits.
