# Explorer 2 Briefing: Latency Profiling & Statistical Calculation Design (M1)

## 🔒 My Identity
- **Role**: Explorer 2 (Latency Profiling & Statistical Calculation Designer) for Milestone 1 (`M1: 10-Session Live Verification & Benchmark Execution`).
- **Working Directory**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/explorer_m1_2`
- **Goal**: Read M1 specs, inspect existing Pipecat pipeline/metrics/tools/memory structures, design exact data structures, logging format (JSON/CSV), and Python calculation logic for computing latency/recall statistics across 10 sessions, verify vector retrieval similarity checks (`>= 0.65`) & silence/audio/text frame behaviors, and deliver a rigorous `handoff.md`.

## 🔒 Key Constraints
- **Read-Only Codebase**: Do NOT modify any code outside `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/explorer_m1_2/`.
- **Handoff Protocol**: Must output to `handoff.md` with Observation, Logic Chain, Caveats, Conclusion, and Verification Method.
- **Communication**: When `handoff.md` is complete, use `send_message` to alert parent (`f780c4a3-8af0-44b2-9822-7d8c142d6633`).

## Investigation State
### Explored paths
- `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/PROJECT.md`
- `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/ORIGINAL_REQUEST.md`
- `server/agent_live.py` (`GeminiSessionLoggerMixin.start_ttfb_metrics/stop_ttfb_metrics`, `identify_user_handler`, `_handle_msg_tool_call`, `_handle_msg_turn_complete`, `SileroVADAnalyzer(stop_secs=0.4)`)
- `server/memory_function.py` (`SIMILARITY_THRESHOLD = 0.65`, `process_extracted_fact`, `recall_user_memories`, `search_user_memory_handler`, `pre_load_user_profile`)
- `server/tests/eval_bench/test_live_ttfb_bench.py` and `simulate_conversations.py`

### Key findings
- **TTFB Mechanics**: Recorded via `self._my_ttfb_start = time.time()` on user turn completion (`start_ttfb_metrics`) and computed upon first bot transcription/audio output (`stop_ttfb_metrics`), attached as `ttft` inside `OutputTransportMessageFrame(message={"label": "rtvi-ai", "data": {"type": "transcription", "participant": "Bot", "ttft": ...}})` across the WebSocket. Target Median p50 `< 1000ms`.
- **Tool Recall Mechanics**: Measured from tool invocation event `{'type': 'tool_call', 'tool': [...]}` ($t_{\text{tool\_start}}$) to handler completion ($t_{\text{tool\_end}}$).
- **Turn Duration Mechanics**: Measured from user turn completion (`UserStoppedSpeakingFrame`) to `{'type': 'turn_complete'}` ($t_{\text{turn\_complete}} - t_{\text{user\_turn\_end}}$).
- **Vector Retrieval Checks**: `SIMILARITY_THRESHOLD = 0.65` is checked inside `memory_function.py:549`. Any vector match with `score < 0.65` is dropped. Therefore `"What is my son's name?"` must assert `top_match_score >= 0.65`.
- **Delivered Specifications**: `handoff.md` provides exact schemas for `live_benchmark_raw_turns.json` and `live_benchmark_summary_metrics.csv` plus the drop-in `BenchmarkStatsCalculator` Python class for computing exact Mean, Median p50, p90, p95, Min, Max using Python `statistics` / `numpy`.

### Unexplored areas
- None. Task fully completed and verified against repository codebase.
