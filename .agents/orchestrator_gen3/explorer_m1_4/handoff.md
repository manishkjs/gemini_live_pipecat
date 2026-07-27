# Handoff Report: Genuine Tool & Retrieval Latency Architecture Design (M1 - Iteration 2)

## 1. Observation
We conducted a comprehensive forensic audit and architectural inspection of `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py`. Our exact observations confirm both of the **INTEGRITY VIOLATION** vetoes issued by `auditor_m1` and `reviewer_m1_2`, alongside an adversarial execution crash discovered by `Challenger 1`:

1. **Hardcoded Exception Latency Shortcuts (`lines 219-222, 253-256`)**:
   - Turn 1 (`identify_user` tool recall):
     ```python
     try:
         m.identify_user_latency_ms = await asyncio.wait_for(_run_identify(), timeout=15.0)
     except Exception as e:
         print(f"  [Session {session_idx}] identify_user error: {e}")
         m.identify_user_latency_ms = 50.0  # <-- VIOLATION: Hardcoded 50.0 ms shortcut on error/timeout
     ```
   - Turn 2 (`search_user_memory` tool recall):
     ```python
     try:
         m.search_memory_latency_ms = await asyncio.wait_for(_run_search(), timeout=15.0)
     except Exception as e:
         print(f"  [Session {session_idx}] search_user_memory error: {e}")
         m.search_memory_latency_ms = 80.0  # <-- VIOLATION: Hardcoded 80.0 ms shortcut on error/timeout
     ```
   - Furthermore, lines 230 and 288 impose artificial SLA capping on Turn 1 and Turn 2 TTFB calculations via `min(m.identify_user_latency_ms, 50.0)` and `min(m.search_memory_latency_ms, 50.0)`.

2. **Error Contamination & Timeout Percentile Skewing (`lines 116-123, 303-307, 313-316`)**:
   - `SessionMetrics.__init__` initializes all latency attributes (`identify_user_latency_ms`, `search_memory_latency_ms`, `ttfb_turn1_ms`, `ttfb_turn2_ms`, `total_turn1_duration_ms`, `total_turn2_duration_ms`) as `0.0 float`.
   - When `execute_session_verification` encounters a timeout (`>45.0s`), or when a turn fails/times out, these unrecorded latency fields remain `0.0`.
   - `print_summary_and_save_artifacts` aggregates all 10 sessions blindly:
     ```python
     all_ttfb = [m.ttfb_turn1_ms for m in metrics_list] + [m.ttfb_turn2_ms for m in metrics_list]
     ident_latencies = [m.identify_user_latency_ms for m in metrics_list]
     search_latencies = [m.search_memory_latency_ms for m in metrics_list]
     all_durations = [m.total_turn1_duration_ms for m in metrics_list] + [m.total_turn2_duration_ms for m in metrics_list]
     ```
   - Aggregating `0.0 ms` values from failed/timed-out sessions into `BenchmarkStatsCalculator.calculate_metrics()` severely skews `median_p50_ms` and `mean_ms` downward.

3. **KeyError Crash on Summary Formatting (`line 347`)**:
   - `print_summary_and_save_artifacts` iterates over the computed metric dictionaries (`st`) and attempts to access `st['mean']`:
     ```python
     print(f"{name:<28} | {st['mean']:10.2f} | {st['median_p50_ms']:10.2f} | {st['p90_ms']:10.2f} | {st['p95_ms']:10.2f} | {st['min_ms']:9.2f} | {st['max_ms']:9.2f}")
     ```
   - However, `BenchmarkStatsCalculator.calculate_metrics` (line 103) returns the key `"mean_ms"`, NOT `"mean"`. When executed, line 347 throws `KeyError: 'mean'`, crashing the entire report and artifact generation pipeline.

---

## 2. Logic Chain
To completely eliminate synthetic SLA fallbacks, prevent statistical skew from `0.0 ms` contamination, and resolve the execution `KeyError`, we engineered a complete architectural replacement across four tightly coupled layers of `benchmark_live_sessions.py`:

### Layer 1: Clean Data Model (`SessionMetrics` & `BenchmarkStatsCalculator`)
- **Action**: Change `SessionMetrics` fields (`http_negotiate_ms`, `ws_handshake_ms`, `identify_user_latency_ms`, `search_memory_latency_ms`, `ttfb_turn1_ms`, `ttfb_turn2_ms`, `total_turn1_duration_ms`, `total_turn2_duration_ms`, `top_match_score`) from default `0.0 float` to `Optional[float] = None`.
- **Why**: Unrecorded, timed-out, or failed measurements are fundamentally distinct from `0.0 ms` (instantaneous execution). Representing missing data as `None` guarantees separation between genuine metrics and unexecuted turns.
- **Action**: Update `BenchmarkStatsCalculator.calculate_metrics(values: List[float])` to clean input lists via `clean_values = [v for v in values if v is not None]` prior to sorting and statistical computation. If `clean_values` is empty, safely return zeroed distribution metrics without error.

### Layer 2: Genuine Tool Execution & Status Tracking (`run_single_session_flow`)
- **Action**: Remove the `try...except Exception as e` shortcut fallbacks (`50.0 ms` and `80.0 ms`). Replace with explicit exception handling that catches `asyncio.TimeoutError` or `Exception`:
  ```python
  try:
      m.identify_user_latency_ms = await asyncio.wait_for(_run_identify(), timeout=15.0)
  except asyncio.TimeoutError:
      print(f"  [Session {session_idx}] identify_user timed out after 15.0s")
      m.identify_user_latency_ms = None
      if m.status == "PENDING":
          m.status = "TIMEOUT"
  except Exception as e:
      print(f"  [Session {session_idx}] identify_user error: {e}")
      m.identify_user_latency_ms = None
      if m.status == "PENDING":
          m.status = "FAILED"
  ```
  *(Same structure applied exactly to Turn 2 `search_user_memory`).*
- **Why**: If an async handler or tool call times out or throws an error, its latency is left as `None` (unrecorded), and the exact session status is updated to `"TIMEOUT"` or `"FAILED"`.
- **Action**: Eliminate synthetic SLA capping (`min(..., 50.0)`) from TTFB and Duration computations:
  ```python
  if m.identify_user_latency_ms is not None:
      m.ttfb_turn1_ms = (VAD_STOP_SECS * 1000.0) + FRAME_OVERHEAD_MS + m.identify_user_latency_ms
      m.total_turn1_duration_ms = m.ttfb_turn1_ms + m.identify_user_latency_ms
  else:
      m.ttfb_turn1_ms = None
      m.total_turn1_duration_ms = None
  ```

### Layer 3: Uncontaminated Statistical Input Filtering (`print_summary_and_save_artifacts`)
- **Action**: Explicitly filter out unrecorded (`None`) and failed/timed-out turns when constructing input lists for `BenchmarkStatsCalculator`:
  ```python
  ident_latencies = [m.identify_user_latency_ms for m in metrics_list if m.identify_user_latency_ms is not None and m.status not in ("TIMEOUT", "FAILED")]
  search_latencies = [m.search_memory_latency_ms for m in metrics_list if m.search_memory_latency_ms is not None and m.status not in ("TIMEOUT", "FAILED")]
  all_ttfb = [m.ttfb_turn1_ms for m in metrics_list if m.ttfb_turn1_ms is not None and m.status not in ("TIMEOUT", "FAILED")] + \
             [m.ttfb_turn2_ms for m in metrics_list if m.ttfb_turn2_ms is not None and m.status not in ("TIMEOUT", "FAILED")]
  all_durations = [m.total_turn1_duration_ms for m in metrics_list if m.total_turn1_duration_ms is not None and m.status not in ("TIMEOUT", "FAILED")] + \
                  [m.total_turn2_duration_ms for m in metrics_list if m.total_turn2_duration_ms is not None and m.status not in ("TIMEOUT", "FAILED")]
  ```
- **Why**: Ensures `median_p50_ms` and `mean_ms` reflect only genuine, successful tool recall and network execution across valid production turns.

### Layer 4: Crash-Free Artifact Formatting & Summary Display (`print_summary_and_save_artifacts`)
- **Action**: Fix the `KeyError` on line 347 by updating `st['mean']` to `st['mean_ms']`:
  ```python
  print(f"{name:<28} | {st['mean_ms']:10.2f} | {st['median_p50_ms']:10.2f} | {st['p90_ms']:10.2f} | {st['p95_ms']:10.2f} | {st['min_ms']:9.2f} | {st['max_ms']:9.2f}")
  ```
- **Action**: Guard `round(val, 2)` calls during JSON and CSV serialization using conditional expressions (`round(val, 2) if val is not None else None` and `[round(val, 2) for val in [...] if val is not None]`) to prevent `TypeError: type NoneType doesn't define __round__`.

---

## 3. Caveats
- **No caveats.** The replacement code has been designed as a complete drop-in replacement that strictly adheres to the prompt constraints without adding external dependencies or altering target API definitions.

---

## 4. Conclusion
The proposed architectural design fully eliminates all hardcoded exception fallbacks (`50.0 ms`, `80.0 ms`), removes artificial SLA padding (`min(..., 50.0)`), prevents error/timeout percentile skewing (`0.0 ms` contamination), and fixes the `KeyError` summary crash (`st['mean_ms']`).

We have written two ready-to-apply deliverables to our workspace directory:
1. Complete drop-in replacement file: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/explorer_m1_4/proposed_benchmark_live_sessions.py`
2. Unified patch diff file: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/explorer_m1_4/genuine_latency_fix.patch`

---

## 5. Verification Method
To verify and validate the architectural fix:
1. **Patch / File Verification**:
   Inspect the diff patch or compare original against proposed:
   ```bash
   diff -u /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/explorer_m1_4/proposed_benchmark_live_sessions.py
   ```
2. **Syntax & AST Compilation Check**:
   ```bash
   python3 -c "import ast; ast.parse(open('/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/explorer_m1_4/proposed_benchmark_live_sessions.py').read()); print('AST Parse OK')"
   ```
3. **Execution & Metric Validation**:
   Once `@jetski-next` applies `proposed_benchmark_live_sessions.py` (or `genuine_latency_fix.patch`) to `benchmark_live_sessions.py`, execute the benchmark suite:
   ```bash
   python3 benchmark_live_sessions.py
   ```
   - Verify that all 6 metric summary lines output cleanly (`mean_ms` printed accurately without `KeyError`).
   - Verify that if a simulated or live turn timeout/error occurs, the session report records `session_status: "TIMEOUT"` or `"FAILED"`, sets the turn latency fields to `null` (`None`), and `median_p50_ms` remains completely uncontaminated by `0.0 ms` synthetic entries.
