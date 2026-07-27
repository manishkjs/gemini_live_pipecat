# Adversarial Stress-Test Handoff Report — Challenger 1 (Milestone 1)

**Working Directory**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/challenger_m1_1`
**Target File**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py`

---

## 1. Observation

### Observation 1: Fatal Dictionary Key Discrepancy (`KeyError: 'mean'`)
In `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py`, `BenchmarkStatsCalculator.calculate_metrics(values: List[float]) -> Dict[str, float]` returns the following dictionary structure on lines 101–109:
```python
        return {
            "sample_count": n,
            "mean_ms": round(mean_val, 2),
            "median_p50_ms": round(p50_val, 2),
            "p90_ms": round(p90_val, 2),
            "p95_ms": round(p95_val, 2),
            "min_ms": round(min_val, 2),
            "max_ms": round(max_val, 2)
        }
```
However, in `print_summary_and_save_artifacts(metrics_list: List[SessionMetrics])` on line 347, the console report printing loop attempts to access `st['mean']`:
```python
    for name, st in [
        ("Turn-to-First-Byte (TTFB)", ttfb_stats),
        ("identify_user Tool Recall", ident_stats),
        ("search_user_memory Recall", search_stats),
        ("Total Turn Duration", duration_stats),
        ("HTTP /connect Negotiation", http_stats),
        ("WebSocket /ws Handshake", ws_stats),
    ]:
        print(f"{name:<28} | {st['mean']:10.2f} | {st['median_p50_ms']:10.2f} | {st['p90_ms']:10.2f} | {st['p95_ms']:10.2f} | {st['min_ms']:9.2f} | {st['max_ms']:9.2f}")
```
Notably, on line 458 (`csv.writer` logic below), the code correctly uses `st["mean_ms"]`:
```python
            writer.writerow([
                m_name, st["sample_count"], st["mean_ms"], st["median_p50_ms"],
                st["p90_ms"], st["p95_ms"], st["min_ms"], st["max_ms"], budget, comp
            ])
```
Because `'mean'` does not exist in `st` (`"mean_ms"` is the key), executing `print_summary_and_save_artifacts` will unconditionally crash with `KeyError: 'mean'`.

---

### Observation 2: Artificial Similarity Score Override (`0.885` Bypass)
In `run_single_session_flow(session_idx: int)` on lines 265–286, vector retrieval scoring against `SIMILARITY_THRESHOLD = 0.65` is evaluated as follows:
```python
    # Step 4: Check exact similarity score against mem0 / threshold
    top_score = 0.0
    try:
        def _check_score():
            mem0 = get_mem0_instance()
            if mem0:
                s_res = mem0.search(query="What is my son's name?", filters={"user_id": session_id})
                r_list = s_res.get("results", []) if isinstance(s_res, dict) else s_res
                if isinstance(r_list, list) and len(r_list) > 0 and isinstance(r_list[0], dict):
                    return float(r_list[0].get("score", 1.0))
            return 0.0
        loop = asyncio.get_running_loop()
        top_score = await asyncio.wait_for(loop.run_in_executor(None, _check_score), timeout=10.0)
    except Exception as e:
        pass

    if top_score < SIMILARITY_THRESHOLD and m.search_success and ("Kabir" in m.retrieved_content or "Sharma" in m.retrieved_content):
        top_score = max(top_score, 0.885)  # Exact fact retrieved successfully via memory bank/engine

    m.top_match_score = top_score
    m.similarity_threshold_passed = (m.top_match_score >= SIMILARITY_THRESHOLD)
```
If `mem0.search(...)` returns `top_score = 0.20` (or `0.0` due to error/disconnect), but `m.search_success` is true (`"Kabir Sharma"` returned by the mock/LLM service), line 281 forces `top_score` to `0.885`. This ensures `m.similarity_threshold_passed = True` even when the vector retrieval engine fails to meet `SIMILARITY_THRESHOLD >= 0.65`.

---

### Observation 3: Statistical Calculation Engine Edge Cases (`n=10`, identical values, quantiles)
In `BenchmarkStatsCalculator.calculate_metrics(values: List[float])` (lines 87–100):
```python
        if n >= 2:
            try:
                quantiles_100 = statistics.quantiles(sorted_vals, n=100, method='inclusive')
                p90_val = quantiles_100[89]
                p95_val = quantiles_100[94]
            except Exception:
                idx_90 = min(int(round(0.90 * (n - 1))), n - 1)
                idx_95 = min(int(round(0.95 * (n - 1))), n - 1)
                p90_val = sorted_vals[idx_90]
                p95_val = sorted_vals[idx_95]
        else:
            p90_val = max_val
            p95_val = max_val
```
- For $N=10$ (`sample_count = 10` sessions): Python's `statistics.quantiles(sorted_vals, n=100, method='inclusive')` produces $100 - 1 = 99$ cut points via linear interpolation. The exact interpolation formulas for sorted data $V_0, \dots, V_9$ ($m = N-1 = 9$) are:
  - 90th percentile index: $x_{90} = \frac{90}{100} \times 9 = 8.1 \implies V_8 + 0.1 \times (V_9 - V_8)$ (stored at `quantiles_100[89]`).
  - 95th percentile index: $x_{95} = \frac{95}{100} \times 9 = 8.55 \implies V_8 + 0.55 \times (V_9 - V_8)$ (stored at `quantiles_100[94]`).
- If `statistics.quantiles` raises an exception (fallback path): `idx_90 = min(int(round(0.90 * 9)), 9) = min(8, 9) = 8` ($V_8$), and `idx_95 = min(int(round(0.95 * 9)), 9) = min(9, 9) = 9` ($V_9$). This avoids `IndexError` cleanly (`8 < 10` and `9 < 10`), though it rounds to integer indices rather than interpolating.
- For identical latency values across all 10 sessions ($V_0 = \dots = V_9 = 100.0$): Both `quantiles_100` and fallback produce exactly `100.0` with zero variance. No `ZeroDivisionError` or bounds exceptions occur.
- For $N=0$: Early return on line 68 safely yields `sample_count: 0` and `0.0` for all fields.
- For $N=1$: Handled by `else:` branch (`p90_val = max_val`, `p95_val = max_val`) without index bounds issues.

---

## 2. Logic Chain

1. **Crash during execution of benchmark report**: When `benchmark_live_sessions.py` runs through `main() -> print_summary_and_save_artifacts(metrics_list)`, `calc.calculate_metrics(...)` returns a dict whose mean key is explicitly named `"mean_ms"`. The loop on line 347 references `st['mean']`. By the definition of Python dictionary access, this raises an unhandled `KeyError: 'mean'`, preventing the output JSON and CSV files from being saved on lines 435 and 441.
2. **Loss of strictness in similarity gate check**: Milestone 1 mandates verifying that `SIMILARITY_THRESHOLD >= 0.65` is met for `"What is my son's name?"` queries across all 10 sessions. Because of line 281 (`top_score = max(top_score, 0.885)`), if `search_user_memory` returns `"Kabir Sharma"` via mock callback or exact match, any failing vector score ($< 0.65$) or `0.0` is silently overwritten to `0.885`. Consequently, `assert sim_pass` (line 359) cannot detect a broken or underperforming vector search index (`mem0`), masking potential vector retrieval regressions in production.
3. **Statistical calculation robustness for $N=10$**: `BenchmarkStatsCalculator` is mathematically safe from index bounds crashes for $N=10$, $N=1$, or $N=0$. However, linear interpolation in `statistics.quantiles` (`method='inclusive'`) vs the integer-rounding fallback formula (`min(int(round(p * (n-1))), n-1)`) will yield slightly different percentile values for $N=10$ (`8.1` vs `8` for p90, `8.55` vs `9` for p95) if the fallback path is ever triggered.

---

## 3. Caveats

- **No caveats regarding `calculate_metrics` safety**: We verified boundary edge cases (`values = []`, `[42.5]`, `[100.0]*10`, duplicates, negative values) and confirmed no unhandled `IndexError` or `ZeroDivisionError` occurs inside `BenchmarkStatsCalculator.calculate_metrics`.
- **In-Memory Mocking in Turn 2**: Our evaluation focused strictly on the gating logic and calculation engine in `benchmark_live_sessions.py`. Whether `mem0.search` returns real vector scores or `0.0` depends on live server state and backend initializations during end-to-end execution.

---

## 4. Conclusion

1. **CRITICAL BUG (Must Fix before M1 Benchmark Execution)**: `st['mean']` on line 347 of `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py` MUST be changed to `st['mean_ms']`. Otherwise, `benchmark_live_sessions.py` will crash on line 347 with `KeyError: 'mean'` every time it runs.
2. **TEST GATING VULNERABILITY (Strictness Compromise)**: Line 281 (`top_score = max(top_score, 0.885)`) masks vector similarity threshold failures ($top\_score < 0.65$). For strict empirical verification of `SIMILARITY_THRESHOLD >= 0.65` as required by M1, this artificial override should be documented or removed so that true `mem0` vector retrieval scores are asserted.
3. **Statistical Calculation Engine ($N=10$)**: `BenchmarkStatsCalculator.calculate_metrics` handles $N=10$, identical values, and small sample sizes without throwing indexing errors.

---

## 5. Verification Method

To independently verify these adversarial findings:

1. **Inspect line 347 vs line 103 & line 458 in `benchmark_live_sessions.py`**:
   Execute `sed -n '101,109p;345,349p;456,460p' /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py` to confirm that `calculate_metrics` returns `"mean_ms"` (line 103), `csv.writer` uses `"mean_ms"` (line 458), while `print()` attempts `st['mean']` (line 347).
2. **Execute standalone stress test harness**:
   Run `python3 -c "import sys; sys.path.insert(0, '/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat'); from benchmark_live_sessions import BenchmarkStatsCalculator, SessionMetrics, print_summary_and_save_artifacts; m = SessionMetrics('s1'); m.ttfb_turn1_ms = 10; print_summary_and_save_artifacts([m])"`
   *(This triggers exact `KeyError: 'mean'` at line 347).*
3. **Verify similarity override bypass**:
   Inspect lines 280–282 of `benchmark_live_sessions.py`:
   `sed -n '280,285p' /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py`
