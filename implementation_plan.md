# Implementation Plan

## Overview
Reduce end-to-end voice latency (TTFT / time-to-first-audio and inter-turn dead air) in the Gemini Live + Pipecat voicebot on the `loan` branch by eliminating synchronous work from the audio/frame hot path, speeding up phase classification, slimming the RAG tool round-trip, pruning the live "tool tax", and making turn-taking thresholds tunable.

The pipeline hot path is: `transport.input() -> StartTriggerProcessor -> UserIdleProcessor -> context_aggregator.user() -> llm (CustomGeminiLive*) -> phase_processor -> [tts] -> transport.output()`. Today four things add avoidable latency or deliberation cost on this path:

1. **Blocking LangSmith HTTP on the hot path** — `GLOBAL_LANGSMITH_TRACER.record_user_turn()` is called inline in `GeminiSessionLoggerMixin._push_user_transcription` (`server/agent_live.py:304`) and `record_bot_turn()` in `_handle_msg_turn_complete` (`server/agent_live.py:532`). `RunTree.post()/patch()/end()` in `server/tracing.py` are synchronous network calls executed inside frame processing.
2. **Tier-1 phase regexes are re-compiled per utterance** — `ConsultativePhaseTracker.handle_user_transcript` (`server/phase_engine.py:457-512`) builds `re.search(rf"\b{re.escape(w)}\b", lower)` patterns dynamically on every user transcript, and Tier-2 Flash-Lite classification sends the *entire* dialogue history with a 4s timeout for any utterance the regex misses (including 1–2 word fillers).
3. **RAG tool round-trip has redundant hops** — `search_knowledge_base_handler` (`server/rag_function.py:44`) performs an extra `rag_cache.get(query)` before `search_sheet_knowledge()` which internally repeats the same cache check (`server/redis_cache.py:361`), then `await`s an L2 Redis `set()` before returning the result to the model; the BM25 scoring loop recomputes `lower().replace("₹","rs ")` per candidate document per query (`redis_cache.py:385,404-405`).
4. **14 tool schemas registered live** — `get_live_streaming_tools()` (`server/tools/tool_definitions.py`) declares 14 FunctionSchemas; per the repo's own cost architecture doc (Pillar 3 in `docs/GEMINI_LIVE_COST_OPTIMIZATION_ARCHITECTURE.md`), every schema is re-processed per audio frame and adds model "deliberation" latency before speech begins.

Additionally, turn-taking thresholds (Silero VAD `stop_secs=0.4`, `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)` in `run_agent_live`) are hardcoded and dominate perceived responsiveness but have no measurement harness to tune them safely.

High-level approach: (a) make all telemetry fire-and-forget, (b) make the phase engine's fast path truly zero-cost and gate the slow path, (c) collapse the RAG tool to a single cache probe + deferred writes with precomputed index fields, (d) introduce a config-driven lean tool profile, and (e) externalize turn-taking timings behind env vars with a benchmark harness to validate no regressions.

## Types
No new public API types are required. Internal additions:

- `ToolProfile` — module-level constant registry in `server/tools/tool_definitions.py`: mapping `"lean" -> List[FunctionSchema]` and `"full" -> List[FunctionSchema]`. Plain dicts/lists, no new classes.
- `PHASE_TIER1_RULES: List[Tuple[re.Pattern | List[str], int, str]]` — precompiled rule table in `server/phase_engine.py`: `(word-boundary regex pattern OR plain-substring keyword list, target_phase, matched_rule)`.
- `TracerTask: Tuple[str, Dict[str, Any]]` — lightweight envelope `(method_name, kwargs)` queued to the background tracer worker in `server/tracing.py`.

- New env-var contract (read via `os.getenv`, documented in `server/.env.example`):
  - `TOOL_PROFILE` (`"lean"|"full"`, default `"lean"`)
  - `TIER2_CLASSIFIER_TIMEOUT_S` (float, default `2.5`)
  - `TIER2_MAX_HISTORY_TURNS` (int, default `8`)
  - `VAD_STOP_SECS` (float, default `0.4`)
  - `USER_SPEECH_TIMEOUT_S` (float, default `0.6`)
  - `RAG_L2_WRITE_ASYNC` (`"true"|"false"`, default `"true"`)

## Files

- **`server/tracing.py`** (modify)
  - Add an asyncio-safe background flush mechanism: a bounded `queue.Queue` plus a single daemon worker thread (thread-based deliberately, since `record_*` may be called from the pipecat frame loop and must never block on the loop).
  - `record_user_turn`, `record_bot_turn`, `record_tool_call`, `record_interruption` change from executing `child.post()/end()/patch()` inline to enqueuing `(method, payload)` and returning immediately.
  - Worker executes the existing RunTree child creation/post/end/patch logic; exceptions logged at debug level and dropped.
  - Preserve `enabled`/`root_run` guards exactly; if `end_session()` is called, drain the queue synchronously (with 2s cap) before ending the root run so late turns aren't lost.
- **`server/agent_live.py`** (modify)
  - No signature changes to `run_agent_live`; read new env vars for `vad_analyzer` params (`stop_secs`), `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=...)`, and pass `tool_profile` through to `get_live_streaming_tools(...)`.
  - Callers of `GLOBAL_LANGSMITH_TRACER` stay untouched (their methods become non-blocking internally).
- **`server/phase_engine.py`** (modify)
  - Add module-level `PHASE_TIER1_RULES` precompiled table; rewrite Tier-1 section of `handle_user_transcript` to iterate the table.
  - Add filler short-circuit before Tier-2 dispatch (≤2 words AND in existing filler set — reuse the set already defined in `watcher_brain.py:134` by moving it to a shared module constant `FILLER_WORDS` in `phase_engine.py` and importing it in `watcher_brain.py`).
  - Read `TIER2_CLASSIFIER_TIMEOUT_S` and `TIER2_MAX_HISTORY_TURNS`; truncate `history` passed to `_async_ai_classify_intent` to last N turns.

- **`server/rag_function.py`** (modify)
  - Remove the redundant outer `await rag_cache.get(query)` (lines 43–48) — `RedisRAGCache.search_sheet_knowledge` already performs exact-cache lookup with the correct `topk` dimension.
  - Replace `await rag_cache.set(query, sheet_matches)` with a fire-and-forget write guarded by `RAG_L2_WRITE_ASYNC` (fall back to awaited set when disabled).
- **`server/redis_cache.py`** (modify)
  - At index time in `prewarm_sheet_knowledge`, additionally store `self._doc_text_q: List[str]` and `self._doc_text_a: List[str]` (pre-lowered, `₹`->`rs ` normalized question/answer strings).
  - In `search_sheet_knowledge`, replace per-doc `rec.get("question","").lower().replace("₹","rs ")` computations with lookups into the precomputed lists.
  - No changes to key schema (`cymbal:sheet_rag:*`) or BM25 parameters — cached entries remain valid.
- **`server/tools/tool_definitions.py`** (modify)
  - Add `LEAN_TOOL_NAMES = {"calculate_returns", "search_knowledge_base", "retrieve_memory"}` and build `TOOL_PROFILES` dict mapping profile name -> ordered schema list.
  - Extend `get_live_streaming_tools(dynamic_tools_json=None, tool_profile="lean")` to select from `TOOL_PROFILES`; keep `"full"` behavior identical to today.
  - Ensure `register_all_tools` still registers *handlers* for all schemas regardless of profile (handler registration is harmless; only declarations cost tokens), so switching profiles needs no other code change.
- **`server/watcher_brain.py`** (modify, minor)
  - Import shared `FILLER_WORDS` from `phase_engine` instead of local set (deduplication only; behavior identical).
- **`server/.env.example`** (modify)
  - Document all new env vars above with recommended values.
- **`server/tests/bench_hot_path.py`** (new)
  - Micro-benchmark harness (see Testing).
- **`implementation_plan.md`** (this file, new).

No files are deleted or moved.

## Functions

- **`LangSmithTracer.record_user_turn(self, text: str)`** — `server/tracing.py` — modify: enqueue instead of inline RunTree post. Same signature.
- **`LangSmithTracer.record_bot_turn(self, text: str, ttfb_ms=None, token_usage=None)`** — `server/tracing.py` — modify: enqueue instead of inline.
- **`LangSmithTracer.record_tool_call(self, name, args, result, duration_ms=None)`** — `server/tracing.py` — modify: enqueue.
- **`LangSmithTracer.record_interruption(self, elapsed_ms: float)`** — `server/tracing.py` — modify: enqueue.
- **`LangSmithTracer._worker_loop(self)`** — new private method, `server/tracing.py` — daemon thread body draining the queue, executing the existing child-run logic per item; exits when sentinel received.

- **`LangSmithTracer.end_session(self, summary=None)`** — `server/tracing.py` — modify: drain queue (max 2s) before finalizing root run.
- **`ConsultativePhaseTracker.handle_user_transcript(self, text, history=None)`** — `server/phase_engine.py` — modify: iterate precompiled `PHASE_TIER1_RULES`; return early from Tier-2 dispatch for filler utterances; clamp Tier-2 history.
- **`ConsultativePhaseTracker._async_ai_classify_intent(self, text, initial_phase, turn_id, history=None)`** — `server/phase_engine.py` — modify: use `TIER2_CLASSIFIER_TIMEOUT_S` and truncated history in the classifier prompt.
- **`search_knowledge_base_handler(params: FunctionCallParams)`** — `server/rag_function.py` — modify: drop redundant cache probe; defer cache writes.
- **`RedisRAGCache.prewarm_sheet_knowledge(...)`** — `server/redis_cache.py` — modify: build precomputed text lists alongside token counters.
- **`RedisRAGCache.search_sheet_knowledge(self, query, top_k=3)`** — `server/redis_cache.py` — modify: use precomputed text lists in phrase-bonus scoring; optionally defer `self.set(...)` write per `RAG_L2_WRITE_ASYNC`.
- **`get_live_streaming_tools(dynamic_tools_json=None, tool_profile="lean")`** — `server/tools/tool_definitions.py` — modify: new keyword arg with backward-compatible default resolution from `TOOL_PROFILE` env.
- **`run_agent_live(websocket, model, voice, language, ...)`** — `server/agent_live.py` — modify: read `VAD_STOP_SECS` / `USER_SPEECH_TIMEOUT_S` / `TOOL_PROFILE` and pass through; no signature change.

No functions are removed.

## Classes

- **`LangSmithTracer`** (`server/tracing.py`) — modify: add `self._queue: queue.Queue`, `self._worker_thread`, `_worker_loop()`, sentinel-based shutdown; public method signatures unchanged.
- **`RedisRAGCache`** (`server/redis_cache.py`) — modify: add `_doc_text_q` / `_doc_text_a` lists populated in prewarm; consumed in search.
- **`ConsultativePhaseTracker`** (`server/phase_engine.py`) — modify: internal only (rule table usage, gating logic).
- **`GeminiSessionLoggerMixin`**, **`UserIdleProcessor`**, **`StartTriggerProcessor`**, **`PhaseTransitionProcessor`**, **`WatcherBrain`**, memory classes — unchanged (WatcherBrain gets only the shared `FILLER_WORDS` import).

No classes are added or removed.

## Dependencies
None added or upgraded. All changes use stdlib (`queue`, `re`, `os`, `asyncio`) and existing packages. Note: `requirements.txt` currently pins both `psycopg2-binary` and `psycopg[binary]` and heavy NLP stacks (spacy/nltk/transformers/mem0ai) that are out of scope for this latency effort — recorded here as future image-size/startup work, not part of this plan.

## Testing

1. **Existing suites must stay green:**
   - `server/tests/test_phase_engine.py` — validates Tier-1/Tier-2 transitions after the rule-table refactor (transition outcomes must be identical for the same inputs).
   - `server/tests/test_redis_cache.py`, `test_sheet_redis_rag.py`, `stress_rag_harness.py` — validate BM25 ranking unchanged after precomputed-text refactor (same top-k ordering for canonical queries like "minimum amount to lend", "14 month EMI option").
   - `server/tests/test_watcher_brain.py` — filler-set dedup refactor.
   - Run: `cd server && python -m pytest tests/test_phase_engine.py tests/test_redis_cache.py tests/test_sheet_redis_rag.py tests/test_watcher_brain.py -x -q` (offline pieces; Redis-dependent tests fall back to L1 mode gracefully).
2. **New micro-benchmark `server/tests/bench_hot_path.py`:**
   - Times 10k iterations of `handle_user_transcript` Tier-1 evaluation over representative Hinglish utterances (target: ≥5x speedup vs dynamic-compile baseline, absolute <1ms/utterance).
   - Times `rag_cache.search_sheet_knowledge` p50/p95 cold and warm (warm p95 must stay <1ms in L1 mode).
   - Asserts `record_user_turn` returns in <0.1ms (enqueue-only) and that queued items still reach the LangSmith client when a fake client is injected.
3. **Manual/e2e validation:** connect with `client/` web UI, watch the existing diagnostics tiles (`⚡ TTFB Latency` via `append_diagnostic_log`, `llm_latency` metric frames) across 10+ turns comparing `TOOL_PROFILE=full` vs `lean`; confirm interruption/repeat-on-filler and phase transitions still fire (`client/diagnostics.html` timeline).

## Implementation Order

1. **P1 — Non-blocking telemetry** (`server/tracing.py`): queue + worker thread; drain-on-end_session. Zero behavioral change to trace output; removes sync HTTP from every turn. Verify with fake-client unit check + one live session.
2. **P2 — RAG hot path** (`server/rag_function.py`, `server/redis_cache.py`): remove redundant probe, defer L2 writes, precompute index texts. Run `test_redis_cache.py` + `stress_rag_harness.py` to prove identical rankings.
3. **P3 — Phase engine fast path** (`server/phase_engine.py`, shared `FILLER_WORDS` with `server/watcher_brain.py`): precompiled `PHASE_TIER1_RULES`, Tier-2 gating/clamping/timeout env vars. Run `test_phase_engine.py`.
4. **P4 — Lean tool profile** (`server/tools/tool_definitions.py`, `server/agent_live.py`, `server/.env.example`): `TOOL_PROFILE` selection; default `"lean"` behind env so `"full"` restores current behavior instantly. Confirm `PhaseTransitionProcessor` tool-name triggers still map (consolidated names preserved: `calculate_returns`, `search_knowledge_base`).
5. **P5 — Tunable turn-taking** (`server/agent_live.py`, `server/.env.example`): env-driven `VAD_STOP_SECS` / `USER_SPEECH_TIMEOUT_S` (defaults unchanged: 0.4 / 0.6 — tuning happens via measurement, not blind edits).
6. **P6 — Benchmark + regression pass**: add `bench_hot_path.py`, capture before/after numbers, run full offline test suite, one supervised live call validating diagnostics TTFT improvement and unchanged conversation behavior.

Steps 1–3 are independent and low-risk; step 4 changes model-visible surface and should land last among code changes so its TTFT effect is measurable in isolation.
