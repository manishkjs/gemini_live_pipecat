# Mem0 Local Memory Layer Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the high-latency GCP REST API calls in long-term memory operations with an embedded, low-latency **Mem0** engine running in-process to reduce tool latency from ~2.7s down to ~200-400ms.

**Architecture:** Mem0 (`mem0ai`) runs embedded inside `server/memory_function.py`. It uses a local SQLite/Qdrant vector store and Gemini 2.5 Flash for fact extraction. Tool calls `save_user_memory` and `search_user_memory` interface with the embedded `Memory()` instance.

**Tech Stack:** Python 3.13, `mem0ai`, `qdrant-client`, `google-genai` / `langchain-google-genai`, SQLite.

---

### Phase 1: Installation & Configuration

1. **Installation Location:**
   - Package: `mem0ai` installed inside the virtual environment `./venv` (`./venv/bin/pip install mem0ai`).
   - Storage Location: Local SQLite/Vector database stored under `server/data/mem0_store.db` or `~/.mem0/`.

2. **Configuration Setup:**
   - Configure `Mem0` config in `server/memory_function.py`:
     ```python
     config = {
         "vector_store": {
             "provider": "qdrant",
             "config": {
                 "location": ":memory:" # or local path server/data/qdrant
             }
         },
         "llm": {
             "provider": "gemini",
             "config": {
                 "model": "gemini-2.5-flash",
                 "api_key": os.getenv("GEMINI_API_KEY")
             }
         }
     }
     m = Memory.from_config(config)
     ```

---

### Phase 2: Tool Integration (`server/memory_function.py`)

1. **`save_user_memory_handler`**:
   - Instead of sending HTTP POST to `https://us-central1-aiplatform.googleapis.com/.../memories`:
   - Call `m.add(memory_text, user_id="default_user", metadata={"category": category})`
   - Mem0 automatically extracts core entities & relationships and updates the graph/vector index locally in ~100-200ms.

2. **`search_user_memory_handler`**:
   - Instead of sending HTTP POST to `.../memories:retrieve`:
   - Call `results = m.search(query, user_id="default_user", limit=5)`
   - Formats matched facts directly into bullet points and returns them to Gemini in ~100ms.

---

### Phase 3: Verification & Latency Benchmarking

1. **Unit Testing:**
   - Run `unittest` in `test_memory_function.py` to verify `add` and `search` operations.
2. **End-to-End Latency Test:**
   - Launch `server.py` and execute voice turns asking for memory retrieval.
   - Measure TTFB reduction (expecting overall turn latency to drop from ~3.6s to < 1.2s).
