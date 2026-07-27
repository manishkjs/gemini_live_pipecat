# BRIEFING.md — Situational Awareness

## 🔒 My Identity
I am Explorer 1 (Existing Client & WebSocket/HTTP Protocol Investigator) for Milestone 1 (`M1: 10-Session Live Verification & Benchmark Execution`).
My working directory is `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/explorer_m1_1`.
My mission is to perform read-only investigation of the existing server/client communication protocols, identify how `identify_user` and `search_user_memory` function across 10 user sessions (`user:test_session_1` through `user:test_session_10`), and design the architecture and exact code structure for `benchmark_live_sessions.py` which will be implemented by the Worker agent.

## 🔒 Key Constraints
- Read-only codebase investigation: NEVER modify any source files or test files outside of `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/explorer_m1_1`.
- Follow the mandatory Handoff Protocol (`handoff.md` with Observation, Logic Chain, Caveats, Conclusion, Verification Method).
- All communication back to the parent agent must be done explicitly via `send_message` with Recipient `f780c4a3-8af0-44b2-9822-7d8c142d6633` (`parent`).

## Current Mission
1. Read `PROJECT.md` and `ORIGINAL_REQUEST.md` in `.agents/orchestrator_gen3/` to understand full requirements. (COMPLETED)
2. Investigate how clients connect to the live Cloud Run endpoint `https://lenskart-memory-bot-853612069841.us-central1.run.app` (`wss://` / HTTP endpoints). (COMPLETED)
3. Determine how `identify_user(name="manish")` and `search_user_memory` (with query `"What is my son's name?"` and `SIMILARITY_THRESHOLD >= 0.65`) work and how sessions (`user:test_session_1` to `user:test_session_10`) are handled. (COMPLETED)
4. Design the complete architecture and code structure for `benchmark_live_sessions.py`. (COMPLETED)
5. Produce `handoff.md` and send summary via `send_message`. (IN PROGRESS)

## Investigation State
- **Explored paths**:
  - `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/PROJECT.md`
  - `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/ORIGINAL_REQUEST.md`
  - `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/server.py`
  - `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/agent_live.py`
  - `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/memory_function.py`
  - `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/test_memory_function.py`
  - `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/test_agent_memory_integration.py`
  - `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/measure_live_pgvector_latency.py`
  - `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/tests/eval_bench/test_live_ttfb_bench.py`
  - `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/tests/eval_bench/simulate_conversations.py`
- **Key findings**:
  - `server.py` exposes `POST /connect` (returns `{"ws_url": ws_url}`), `GET /connect/system-prompt`, and `WEBSOCKET /ws`. Over `/ws`, `FastAPIWebsocketTransport` uses `CustomProtobufSerializer(ProtobufFrameSerializer)`, exchanging binary audio and Pipecat protobuf transport/message frames (e.g. `start_trigger`).
  - `identify_user(name=...)` (`agent_live.py:109-137`) calls `normalize_user_id(name)` and sets `os.environ["ACTIVE_USER_ID"] = clean_id` (e.g., `"user:test_session_1"`).
  - `search_user_memory(query=..., user_id=...)` (`memory_function.py:769-806`) uses `_get_active_user_id(params)` to fetch the active `user_id`. It queries Vertex AI Agent Memory or embedded `Mem0` (`recall_user_memories`). In `recall_user_memories` (`memory_function.py:522-632`), results from pgvector/Qdrant are strictly gated by `if item.get("score", 1.0) < SIMILARITY_THRESHOLD: continue` (`SIMILARITY_THRESHOLD = 0.65`), filtering out low-relevance matches.
  - Existing benchmarks (`test_live_ttfb_bench.py`) test `recall_user_memories_handler` and measure TTFB (`VAD stop delay 0.4s + frame dispatch overhead`) directly to avoid audio STT network jitter.
  - Designed dual-layer architecture for `benchmark_live_sessions.py` combining live Cloud Run network reachability/negotiation checks (`POST /connect`, `wss://.../ws` handshake TTFB) with exact 10-session functional & latency profiling across `user:test_session_1` through `user:test_session_10`.
- **Unexplored areas**: None (`M1` investigation complete).
