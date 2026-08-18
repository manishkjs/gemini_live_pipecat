# Project: Gemini Live Sub-Millisecond Memorystore RAG & Sheet Knowledge Ingestion

## Architecture
- **Voice Pipeline**: Pipecat + Gemini Live duplex voice WebSocket streaming server in `server/server.py`.
- **RAG Knowledge Engine**: Decoupled from remote Vertex AI RAG (`asia-south1`, ~3,500ms latency) to local Dual-Layer L1 In-Memory BM25 Token Inverted Index (<0.2ms) + L2 Google Cloud Memorystore for Valkey/Redis (`10.198.162.203:6379` in `us-central1`, `cymbal:sheet_rag:*`, <0.8ms).
- **Dataset**: 100% of rows (896 valid Q&A records, ~1,100 raw lines) from Google Sheet `1JI9MOdsqIZAPedATGdODWCDJ-nm9R-ZJ57taZtNrsiM` extracted via `gsheets` CLI and pre-warmed at startup.
- **Control Plane**: Google Cloud Memorystore for Valkey Remote MCP Server (`https://memorystore.googleapis.com/mcp`).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Google Sheet Q&A Dataset Ingestion | Extract all 896 valid Q&A pairs from Sheet `1JI9MOdsqIZAPedATGdODWCDJ-nm9R-ZJ57taZtNrsiM` via `gsheets` JSON CLI, clean multiline answers, and format to `server/data/sheet_knowledge.json`. | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Dual-Layer Redis/L1 Key Schema & BM25 Inverted Index | Implement `cymbal:sheet_rag:doc:*`, `cymbal:sheet_rag:token:*`, `cymbal:sheet_rag:query:*`, and `cymbal:sheet_rag:meta` with field-weighted BM25 token ranking in `server/redis_cache.py`. | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Decouple Remote Vertex AI RAG | Remove slow `vertexai.preview.rag` network calls from `search_knowledge_base_handler` in `server/rag_function.py`, fix syntax errors, and route queries directly to Dual-Layer cache with canonical domain fallback. | M2 | ORIGINAL_REQUEST §R2 |
| 4 | Startup Pre-warming & Lifespan Integration | Update FastAPI `lifespan()` in `server/server.py` to pre-warm both canonical domain rules and sheet knowledge dataset into RAM/Redis. | M2 | ORIGINAL_REQUEST §R2, §R4 |
| 5 | Memorystore Valkey MCP Server Integration Pattern | Document and configure Memorystore for Valkey MCP server interface and wire environment variables in `server/.env`. | M3 | ORIGINAL_REQUEST §R3 |
| 6 | Sub-Millisecond Retrieval Verification (<5ms, Zero Dead Air) | Verify specific lending queries ("minimum amount to lend", "maximum amount per PAN ₹50 Lakh", "14 month EMI option", "CTO February 2025 update") with < 5ms latency. | M4 | ORIGINAL_REQUEST §R4 |
| 7 | End-to-End Test Suite Pass & Adversarial Coverage Hardening | Run all test tiers in `server/tests/test_sheet_redis_rag.py` and pass 100%. | M4 | ORIGINAL_REQUEST §R4 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Sheet Ingestion & Dual-Layer Redis Cache | Extract 896 Q&A records, build `sheet_knowledge.json`, update `requirements.txt` with `redis>=5.0.0`, implement BM25 token index and `cymbal:sheet_rag:*` key schema in `server/redis_cache.py`. | none | DONE |
| M2 | Vertex RAG Decoupling & Server Pre-warming | Fix `server/rag_function.py`, decouple Vertex RAG, route tool handler to L1/L2 cache, update `server/server.py` lifespan prewarming, update `server/.env`. | M1 | DONE |
| M3 | Memorystore Valkey MCP Integration | Define Memorystore MCP server integration schema, tool mapping, and environment settings. | none | DONE |
| M4 | E2E Verification & Adversarial Coverage Hardening | Pass 100% of test suite `server/tests/test_sheet_redis_rag.py` across Tiers 1-4 and Tier 5 adversarial hardening. | M1, M2, M3 | DONE |

## Interface Contracts
### `server/redis_cache.py` ↔ `server/rag_function.py`
- `rag_cache.search_sheet_knowledge(query: str, top_k: int = 3) -> str`: Returns formatted Q&A text matches or empty string if no relevant match.
- `rag_cache.get(query: str) -> Optional[str]`: Returns cached response for exact/normalized query hash key (`cymbal:sheet_rag:query:*`).
- `rag_cache.set(query: str, response: str, ttl: int = 86400)`: Stores formatted response under normalized query hash.
- `rag_cache.prewarm_sheet_knowledge(file_path: Optional[str] = None) -> int`: Loads records, builds BM25 index, syncs to Redis, returns total record count.

### `server/rag_function.py` ↔ `server/agent_live.py` / Pipecat LLM
- `search_knowledge_base_schema`: JSON schema matching `query_for_vector_search` (string) and `total_records` (integer).
- `search_knowledge_base_handler(params: FunctionCallParams)`: Async callback invoking `params.result_callback({"content": result})` within < 5ms.

## Code Layout
- `server/data/sheet_knowledge.json`: Sanitized JSON array of 896 Q&A records.
- `server/scripts/ingest_sheet_knowledge.py`: Standalone CLI script for extracting from Google Sheet and syncing to Redis.
- `server/redis_cache.py`: Dual-Layer L1/L2 RedisRAGCache client with BM25 inverted index.
- `server/rag_function.py`: Tool definition and sub-millisecond handler.
- `server/server.py`: FastAPI server with startup lifespan pre-warming.
- `server/.env`: Memorystore host/port and environment settings.
- `server/mcp_config.json`: Memorystore Valkey Remote MCP server configuration.
- `server/requirements.txt`: Python package dependencies including `redis>=5.0.0`.
- `server/tests/test_sheet_redis_rag.py`: E2E automated test suite.
