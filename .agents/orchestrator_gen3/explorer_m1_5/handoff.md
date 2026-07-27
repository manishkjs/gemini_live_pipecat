# HANDOFF REPORT: Genuine Cosine Similarity Gate & Artifact Persistence Design (`benchmark_live_sessions.py`)

**Role**: Explorer 5 (Genuine Cosine Similarity Gate & Artifact Persistence Designer)  
**Milestone**: `M1: 10-Session Live Verification & Benchmark Execution` — Iteration 2  
**Target File**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py`  
**Working Directory**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3/explorer_m1_5`  
**Timestamp**: 2026-07-24T10:12:00Z  

---

## 1. Observation

During our forensic audit of `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py`, our team (`auditor_m1`, `reviewer_m1_2`, and `Challenger 1`) identified three critical structural defects and integrity violations:

### Observation A: Hardcoded Cosine Similarity Score Falsification (`lines 280-282`)
Verbatim code at `benchmark_live_sessions.py:280-282`:
```python
    if top_score < SIMILARITY_THRESHOLD and m.search_success and ("Kabir" in m.retrieved_content or "Sharma" in m.retrieved_content):
        top_score = max(top_score, 0.885)  # Exact fact retrieved successfully via memory bank/engine
```
- **Observed Behavior**: If `_check_score()` (`lines 267-274`) queries `mem0.search(...)` and returns a `top_score` below `SIMILARITY_THRESHOLD` (`0.65`) or `0.0` (e.g., due to local fallback or embedding delay), but Turn 2 keyword/tool search succeeded (`"Kabir"` or `"Sharma"` in `m.retrieved_content`), this conditional block artificially overrides `top_score` to `0.885`.
- **Impact**: This forces `m.similarity_threshold_passed = (m.top_match_score >= SIMILARITY_THRESHOLD)` (`line 284`) to evaluate to `True` for every session where the name is retrieved by keyword, completely invalidating the mandatory vector retrieval gate (`Budget Compliance Check 2: All 10 Sessions top_match_score >= 0.65`).

### Observation B: Fatal `KeyError: 'mean'` Crash During Summary Reporting (`line 347`)
Verbatim code at `benchmark_live_sessions.py:347` inside `print_summary_and_save_artifacts`:
```python
    for name, st in [
        ("Turn-to-First-Byte (TTFB)", ttfb_stats),
...
    ]:
        print(f"{name:<28} | {st['mean']:10.2f} | {st['median_p50_ms']:10.2f} | {st['p90_ms']:10.2f} | {st['p95_ms']:10.2f} | {st['min_ms']:9.2f} | {st['max_ms']:9.2f}")
```
- **Observed Behavior**: `BenchmarkStatsCalculator.calculate_metrics()` (`lines 67-109`) returns a dictionary with key `"mean_ms"`, **not** `"mean"` (`line 103: "mean_ms": round(mean_val, 2)`).
- **Impact**: When `print_summary_and_save_artifacts()` is invoked after the 10 sessions complete (`line 474`), accessing `st['mean']` on line 347 throws an immediate `KeyError: 'mean'`, terminating the process before the summary table is printed, before `assert` statements run, and before any JSON/CSV artifacts are written.

### Observation C: Premature Test Assertions Blocking Artifact Persistence (`lines 358-363`)
Verbatim code at `benchmark_live_sessions.py:358-363`:
```python
    # Assert mandatory M1 budgets
    assert ttfb_pass, f"Assertion Failed: Median p50 TTFB ({ttfb_stats['median_p50_ms']} ms) exceeded 1000ms limit!"
    assert sim_pass, f"Assertion Failed: Not all sessions satisfied SIMILARITY_THRESHOLD >= {SIMILARITY_THRESHOLD}!"

    # Save JSON artifact
    os.makedirs("benchmark_results", exist_ok=True)
    json_path = "benchmark_results/live_sessions_m1.json"
```
- **Observed Behavior**: Both `assert ttfb_pass` and `assert sim_pass` execute immediately after printing summary status lines and *before* `benchmark_results/live_sessions_m1.json` (`lines 361-438`) and `benchmark_results/live_sessions_m1.csv` (`lines 439-461`) are written to disk.
- **Impact**: If any session fails its similarity threshold or if the median p50 TTFB exceeds 1000ms, `AssertionError` is raised at line 358 or 359. The script crashes immediately, leaving zero diagnostic records on disk in `benchmark_results/`. This prevents engineers and automated pipelines from diagnosing which exact session or turn failed the benchmark.

---

## 2. Logic Chain

1. **Why `top_score = max(...)` Must Be Deleted & How Legitimate Vector Similarity Works**:
   - In Step 1 (`lines 189-199`), the session pre-seeds the user's family fact via `_seed()`:
     ```python
     seed_fact = f"User {raw_name}'s son's name is Kabir Sharma and his favorite sport is swimming."
     process_extracted_fact(seed_fact, "M2_Relation", session_id, is_explicit_remember=True)
     _save_local_memory(seed_fact, "M2_Relation", session_id)
     ```
   - When `process_extracted_fact` runs with `get_mem0_instance()` active (using pgvector or Qdrant + `gemini-embedding-001`), `mem0.add(fact_text, user_id=user_id, metadata=meta, infer=False)` stores the 768-dimensional embedding for `seed_fact`.
   - In Step 4 (`_check_score()` at `lines 267-274`), when `mem0.search(query="What is my son's name?", filters={"user_id": session_id})` runs, the cosine similarity between the query embedding (`"What is my son's name?"`) and the stored fact (`"User test_session_X's son's name is Kabir Sharma and his favorite sport is swimming."`) naturally scores between `~0.80` and `~0.92`, exceeding `SIMILARITY_THRESHOLD` (`0.65`).
   - Deleting lines 280-282 (`top_score = max(top_score, 0.885)`) ensures that `_check_score()` (`top_score`) flows directly into `m.top_match_score`. If the vector store genuinely matches with score `>= 0.65`, `m.similarity_threshold_passed` is `True`. If vector search fails or returns `< 0.65`, the gate accurately reports `False` without falsification.

2. **Why `st['mean']` Must Be Fixed to `st['mean_ms']`**:
   - `BenchmarkStatsCalculator.calculate_metrics` guarantees schema uniformity across `mean_ms`, `median_p50_ms`, `p90_ms`, `p95_ms`, `min_ms`, and `max_ms`. Changing `st['mean']` to `st['mean_ms']` on line 347 resolves the `KeyError` and allows the reporting loop to complete cleanly.

3. **Why Artifact Saving Must Precede Test Assertions (`assert ttfb_pass`, `assert sim_pass`)**:
   - All data structures required to generate `live_sessions_m1.json` (`report_data` at `lines 365-433`) and `live_sessions_m1.csv` (`rows` at `lines 447-454`) depend solely on `ttfb_stats`, `ident_stats`, `search_stats`, `duration_stats`, `http_stats`, `ws_stats`, `vec_stats`, `ttfb_pass`, and `metrics_list`. All of these variables are fully computed and immutable by line 328 (`vec_stats = calc.calculate_metrics(vector_scores)`).
   - Moving the `os.makedirs("benchmark_results", ...)` and file writing logic (`lines 361-461`) immediately above the `assert` block guarantees **100% artifact persistence**. Even when `assert sim_pass` or `assert ttfb_pass` raises `AssertionError`, the JSON and CSV files have already been written, closed, and verified on the filesystem (`benchmark_results/live_sessions_m1.json` and `benchmark_results/live_sessions_m1.csv`).

---

## 3. Caveats

- **Read-Only Scope**: Per our Explorer mandate and CODE_ONLY mode, this handoff provides exact verification and design specifications. Downstream implementation must be performed by `@jetski-next` (`implementer_m1`).
- **Memory Engine Dependency**: Genuine `top_match_score >= 0.65` during live execution requires that `get_mem0_instance()` initializes successfully (via valid `GEMINI_API_KEY` / Vertex AI credentials or Qdrant/pgvector backend). If executed in an offline environment where `get_mem0_instance()` returns `None`, `_check_score()` correctly returns `0.0`, resulting in a legitimate `sim_pass == False` assertion failure after artifacts are saved.

---

## 4. Conclusion & Exact Code Specifications

We conclude that `benchmark_live_sessions.py` must be modified using the following two exact, self-contained drop-in replacement chunks. These blocks can be applied directly using `multi_replace_file_content` or `replace_file_content`.

### Replacement Block 1: Deletion of Hardcoded Cosine Similarity Override (`lines 277-286`)

**Target Range**: `StartLine: 277`, `EndLine: 286`
**TargetContent**:
```python
    except Exception as e:
        pass

    if top_score < SIMILARITY_THRESHOLD and m.search_success and ("Kabir" in m.retrieved_content or "Sharma" in m.retrieved_content):
        top_score = max(top_score, 0.885)  # Exact fact retrieved successfully via memory bank/engine

    m.top_match_score = top_score
    m.similarity_threshold_passed = (m.top_match_score >= SIMILARITY_THRESHOLD)
    print(f"  🎯 Vector Retrieval Similarity Gate: score={m.top_match_score:.4f} (Required >= {SIMILARITY_THRESHOLD}) -> {'PASS' if m.similarity_threshold_passed else 'FAIL'}")
```

**ReplacementContent**:
```python
    except Exception as e:
        pass

    m.top_match_score = top_score
    m.similarity_threshold_passed = (m.top_match_score >= SIMILARITY_THRESHOLD)
    print(f"  🎯 Vector Retrieval Similarity Gate: score={m.top_match_score:.4f} (Required >= {SIMILARITY_THRESHOLD}) -> {'PASS' if m.similarity_threshold_passed else 'FAIL'}")
```

---

### Replacement Block 2: Fix `st['mean_ms']` and Reorder Artifact Persistence Above `assert` Statements (`lines 347-461`)

**Target Range**: `StartLine: 347`, `EndLine: 461`
**TargetContent**:
```python
        print(f"{name:<28} | {st['mean']:10.2f} | {st['median_p50_ms']:10.2f} | {st['p90_ms']:10.2f} | {st['p95_ms']:10.2f} | {st['min_ms']:9.2f} | {st['max_ms']:9.2f}")
    
    print("-------------------------------------------------------------------------------------------------")
    ttfb_pass = ttfb_stats["median_p50_ms"] < 1000.0
    sim_pass = all(m.similarity_threshold_passed for m in metrics_list)
    
    print(f"Budget Compliance Check 1: Median p50 TTFB ({ttfb_stats['median_p50_ms']:.2f} ms < 1000 ms) -> {'✅ PASSED' if ttfb_pass else '❌ FAILED'}")
    print(f"Budget Compliance Check 2: All 10 Sessions top_match_score >= {SIMILARITY_THRESHOLD}      -> {'✅ PASSED' if sim_pass else '❌ FAILED'}")
    print("=================================================================================================\n")

    # Assert mandatory M1 budgets
    assert ttfb_pass, f"Assertion Failed: Median p50 TTFB ({ttfb_stats['median_p50_ms']} ms) exceeded 1000ms limit!"
    assert sim_pass, f"Assertion Failed: Not all sessions satisfied SIMILARITY_THRESHOLD >= {SIMILARITY_THRESHOLD}!"

    # Save JSON artifact
    os.makedirs("benchmark_results", exist_ok=True)
    json_path = "benchmark_results/live_sessions_m1.json"
    
    report_data = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "target_endpoint": LIVE_HTTP_ENDPOINT,
        "num_sessions": len(metrics_list),
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "summary_metrics": {
            "Turn-to-First-Byte (TTFB)": {**ttfb_stats, "target_budget_ms": 1000.0, "budget_compliance": "PASS" if ttfb_pass else "FAIL"},
            "Tool Recall Latency (identify_user)": {**ident_stats, "target_budget_ms": 100.0, "budget_compliance": "PASS" if ident_stats["median_p50_ms"] < 100.0 else "FAIL"},
            "Tool Recall Latency (search_user_memory)": {**search_stats, "target_budget_ms": 150.0, "budget_compliance": "PASS" if search_stats["median_p50_ms"] < 150.0 else "FAIL"},
            "Total Turn Duration": {**duration_stats, "target_budget_ms": 3000.0, "budget_compliance": "PASS" if duration_stats["median_p50_ms"] < 3000.0 else "FAIL"},
            "Vector Retrieval Similarity Stats": vec_stats
        },
        "sessions": [
            {
                "session_id": m.session_id,
                "session_start_timestamp": m.session_start_timestamp,
                "session_status": m.status,
                "http_negotiate_ms": m.http_negotiate_ms,
                "ws_handshake_ms": m.ws_handshake_ms,
                "turns": [
                    {
                        "turn_index": 1,
                        "turn_label": "identity_setup",
                        "tool_invoked": {
                            "name": "identify_user",
                            "args": {"name": f"test_session_{idx+1}"},
                            "recall_latency_ms": round(m.identify_user_latency_ms, 2)
                        },
                        "ttfb_ms": round(m.ttfb_turn1_ms, 2),
                        "total_turn_duration_ms": round(m.total_turn1_duration_ms, 2),
                        "functional_assertions": {
                            "tool_called_correctly": m.identify_success,
                            "active_user_id_resolved": m.session_id,
                            "status": "PASS" if m.identify_success else "FAIL"
                        }
                    },
                    {
                        "turn_index": 2,
                        "turn_label": "vector_memory_retrieval",
                        "tool_invoked": {
                            "name": "search_user_memory",
                            "args": {"query": "What is my son's name?", "user_id": m.session_id},
                            "recall_latency_ms": round(m.search_memory_latency_ms, 2)
                        },
                        "vector_retrieval_metrics": {
                            "query": "What is my son's name?",
                            "top_match_score": round(m.top_match_score, 4),
                            "similarity_threshold_required": SIMILARITY_THRESHOLD,
                            "similarity_threshold_passed": m.similarity_threshold_passed,
                            "retrieved_content": m.retrieved_content
                        },
                        "ttfb_ms": round(m.ttfb_turn2_ms, 2),
                        "total_turn_duration_ms": round(m.total_turn2_duration_ms, 2),
                        "functional_assertions": {
                            "tool_called_correctly": m.search_success,
                            "fact_recalled_accurately": m.similarity_threshold_passed and m.search_success,
                            "status": "PASS" if (m.search_success and m.similarity_threshold_passed) else "FAIL"
                        }
                    }
                ],
                "session_latency_summary_ms": {
                    "ttfb_ms_list": [round(m.ttfb_turn1_ms, 2), round(m.ttfb_turn2_ms, 2)],
                    "tool_recall_ms_list": [round(m.identify_user_latency_ms, 2), round(m.search_memory_latency_ms, 2)],
                    "turn_duration_ms_list": [round(m.total_turn1_duration_ms, 2), round(m.total_turn2_duration_ms, 2)]
                }
            }
            for idx, m in enumerate(metrics_list)
        ]
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    print(f"📝 Saved detailed turn metrics to {json_path}")

    # Save CSV artifact
    csv_path = "benchmark_results/live_sessions_m1.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "metric_type", "sample_count", "mean_ms", "median_p50_ms",
            "p90_ms", "p95_ms", "min_ms", "max_ms", "target_budget_ms", "budget_compliance"
        ])
        rows = [
            ("Turn-to-First-Byte (TTFB)", ttfb_stats, 1000.0),
            ("Tool Recall Latency (identify_user)", ident_stats, 100.0),
            ("Tool Recall Latency (search_user_memory)", search_stats, 150.0),
            ("Total Turn Duration", duration_stats, 3000.0),
            ("HTTP /connect Negotiation", http_stats, 500.0),
            ("WebSocket /ws Handshake", ws_stats, 500.0),
        ]
        for m_name, st, budget in rows:
            comp = "PASS" if st["median_p50_ms"] < budget else "FAIL"
            writer.writerow([
                m_name, st["sample_count"], st["mean_ms"], st["median_p50_ms"],
                st["p90_ms"], st["p95_ms"], st["min_ms"], st["max_ms"], budget, comp
            ])
    print(f"📝 Saved summary distribution table to {csv_path}")
```

**ReplacementContent**:
```python
        print(f"{name:<28} | {st['mean_ms']:10.2f} | {st['median_p50_ms']:10.2f} | {st['p90_ms']:10.2f} | {st['p95_ms']:10.2f} | {st['min_ms']:9.2f} | {st['max_ms']:9.2f}")
    
    print("-------------------------------------------------------------------------------------------------")
    ttfb_pass = ttfb_stats["median_p50_ms"] < 1000.0
    sim_pass = all(m.similarity_threshold_passed for m in metrics_list)
    
    print(f"Budget Compliance Check 1: Median p50 TTFB ({ttfb_stats['median_p50_ms']:.2f} ms < 1000 ms) -> {'✅ PASSED' if ttfb_pass else '❌ FAILED'}")
    print(f"Budget Compliance Check 2: All 10 Sessions top_match_score >= {SIMILARITY_THRESHOLD}      -> {'✅ PASSED' if sim_pass else '❌ FAILED'}")
    print("=================================================================================================\n")

    # Save JSON artifact FIRST before asserting any budgets to guarantee 100% artifact persistence
    os.makedirs("benchmark_results", exist_ok=True)
    json_path = "benchmark_results/live_sessions_m1.json"
    
    report_data = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "target_endpoint": LIVE_HTTP_ENDPOINT,
        "num_sessions": len(metrics_list),
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "summary_metrics": {
            "Turn-to-First-Byte (TTFB)": {**ttfb_stats, "target_budget_ms": 1000.0, "budget_compliance": "PASS" if ttfb_pass else "FAIL"},
            "Tool Recall Latency (identify_user)": {**ident_stats, "target_budget_ms": 100.0, "budget_compliance": "PASS" if ident_stats["median_p50_ms"] < 100.0 else "FAIL"},
            "Tool Recall Latency (search_user_memory)": {**search_stats, "target_budget_ms": 150.0, "budget_compliance": "PASS" if search_stats["median_p50_ms"] < 150.0 else "FAIL"},
            "Total Turn Duration": {**duration_stats, "target_budget_ms": 3000.0, "budget_compliance": "PASS" if duration_stats["median_p50_ms"] < 3000.0 else "FAIL"},
            "Vector Retrieval Similarity Stats": vec_stats
        },
        "sessions": [
            {
                "session_id": m.session_id,
                "session_start_timestamp": m.session_start_timestamp,
                "session_status": m.status,
                "http_negotiate_ms": m.http_negotiate_ms,
                "ws_handshake_ms": m.ws_handshake_ms,
                "turns": [
                    {
                        "turn_index": 1,
                        "turn_label": "identity_setup",
                        "tool_invoked": {
                            "name": "identify_user",
                            "args": {"name": f"test_session_{idx+1}"},
                            "recall_latency_ms": round(m.identify_user_latency_ms, 2)
                        },
                        "ttfb_ms": round(m.ttfb_turn1_ms, 2),
                        "total_turn_duration_ms": round(m.total_turn1_duration_ms, 2),
                        "functional_assertions": {
                            "tool_called_correctly": m.identify_success,
                            "active_user_id_resolved": m.session_id,
                            "status": "PASS" if m.identify_success else "FAIL"
                        }
                    },
                    {
                        "turn_index": 2,
                        "turn_label": "vector_memory_retrieval",
                        "tool_invoked": {
                            "name": "search_user_memory",
                            "args": {"query": "What is my son's name?", "user_id": m.session_id},
                            "recall_latency_ms": round(m.search_memory_latency_ms, 2)
                        },
                        "vector_retrieval_metrics": {
                            "query": "What is my son's name?",
                            "top_match_score": round(m.top_match_score, 4),
                            "similarity_threshold_required": SIMILARITY_THRESHOLD,
                            "similarity_threshold_passed": m.similarity_threshold_passed,
                            "retrieved_content": m.retrieved_content
                        },
                        "ttfb_ms": round(m.ttfb_turn2_ms, 2),
                        "total_turn_duration_ms": round(m.total_turn2_duration_ms, 2),
                        "functional_assertions": {
                            "tool_called_correctly": m.search_success,
                            "fact_recalled_accurately": m.similarity_threshold_passed and m.search_success,
                            "status": "PASS" if (m.search_success and m.similarity_threshold_passed) else "FAIL"
                        }
                    }
                ],
                "session_latency_summary_ms": {
                    "ttfb_ms_list": [round(m.ttfb_turn1_ms, 2), round(m.ttfb_turn2_ms, 2)],
                    "tool_recall_ms_list": [round(m.identify_user_latency_ms, 2), round(m.search_memory_latency_ms, 2)],
                    "turn_duration_ms_list": [round(m.total_turn1_duration_ms, 2), round(m.total_turn2_duration_ms, 2)]
                }
            }
            for idx, m in enumerate(metrics_list)
        ]
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    print(f"📝 Saved detailed turn metrics to {json_path}")

    # Save CSV artifact
    csv_path = "benchmark_results/live_sessions_m1.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "metric_type", "sample_count", "mean_ms", "median_p50_ms",
            "p90_ms", "p95_ms", "min_ms", "max_ms", "target_budget_ms", "budget_compliance"
        ])
        rows = [
            ("Turn-to-First-Byte (TTFB)", ttfb_stats, 1000.0),
            ("Tool Recall Latency (identify_user)", ident_stats, 100.0),
            ("Tool Recall Latency (search_user_memory)", search_stats, 150.0),
            ("Total Turn Duration", duration_stats, 3000.0),
            ("HTTP /connect Negotiation", http_stats, 500.0),
            ("WebSocket /ws Handshake", ws_stats, 500.0),
        ]
        for m_name, st, budget in rows:
            comp = "PASS" if st["median_p50_ms"] < budget else "FAIL"
            writer.writerow([
                m_name, st["sample_count"], st["mean_ms"], st["median_p50_ms"],
                st["p90_ms"], st["p95_ms"], st["min_ms"], st["max_ms"], budget, comp
            ])
    print(f"📝 Saved summary distribution table to {csv_path}")

    # Assert mandatory M1 budgets only after all diagnostic artifacts are safely persisted to disk
    assert ttfb_pass, f"Assertion Failed: Median p50 TTFB ({ttfb_stats['median_p50_ms']} ms) exceeded 1000ms limit!"
    assert sim_pass, f"Assertion Failed: Not all sessions satisfied SIMILARITY_THRESHOLD >= {SIMILARITY_THRESHOLD}!"
```

---

## 5. Verification Method

To verify the implementation once `@jetski-next` (`implementer_m1`) applies the edits:

1. **Syntax & AST Compilation Check**:
   Run syntax compilation to verify zero indentation or structural errors:
   ```bash
   python3 -m py_compile /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py
   ```
2. **Falsification Check via Grep**:
   Verify that lines `max(top_score, 0.885)` and `st['mean']` no longer exist in `benchmark_live_sessions.py`:
   ```bash
   grep -n "0\.885" /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py || echo "✅ Clean: No artificial similarity override found"
   grep -n "st\['mean'\]" /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py || echo "✅ Clean: No invalid KeyError access found"
   ```
3. **Artifact Persistence Order Check**:
   Verify that the `assert ttfb_pass` and `assert sim_pass` statements appear strictly *after* `Saved summary distribution table to`:
   ```bash
   grep -n -E "assert (ttfb_pass|sim_pass)|Saved summary distribution table" /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py
   ```
   (The line number of `Saved summary distribution table` must be smaller than the line numbers of `assert ttfb_pass` and `assert sim_pass`).
4. **End-to-End Execution & Artifact Inspection**:
   Execute the verification suite across all 10 sessions:
   ```bash
   python3 /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/benchmark_live_sessions.py
   ```
   - **Validation Criteria**:
     - The process prints the complete summary table (`Turn-to-First-Byte (TTFB)`, etc.) without raising `KeyError`.
     - `benchmark_results/live_sessions_m1.json` and `benchmark_results/live_sessions_m1.csv` are created on disk before any `AssertionError` can terminate execution.
     - Inspect `benchmark_results/live_sessions_m1.json` (`sessions[*].turns[1].vector_retrieval_metrics.top_match_score`) to verify each session reports its genuine similarity score without artificial clamping to `0.885`.
