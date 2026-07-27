# Project: Live Production Verification & Latency Profiling (`lenskart-memory-bot`)

## Architecture & Goal
- Target Service Endpoint: `https://lenskart-memory-bot-853612069841.us-central1.run.app`
- Verification Scope: 10 distinct simulated user sessions (`user:test_session_1` through `user:test_session_10`).
- Functional Verification:
  - Multi-tenant identity setup (`identify_user(name="manish")`)
  - Vector memory retrieval (`search_user_memory` via query `"What is my son's name?"` with `SIMILARITY_THRESHOLD >= 0.65`)
  - Silence cut-off / audio interaction flow
- Latency Profiling:
  - Turn-to-First-Byte (TTFB) - target Median p50 `< 1000ms`
  - Tool Recall Latency (`identify_user` and `search_user_memory`)
  - Total Turn Duration
  - Summary statistics: Mean, Median p50, p90, p95, Min, Max
- Log Audit:
  - `gcloud logging read` for Cloud Run revision logs during/after run.
  - Confirm 0 unhandled exceptions, 0 `404 NOT_FOUND` embedding errors, 0 `NameError` crashes.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: 10-Session Live Verification & Benchmark Execution | Create `benchmark_live_sessions.py` (or inspect/adapt existing client suite), execute 10 distinct user sessions against `https://lenskart-memory-bot-853612069841.us-central1.run.app`, verify functional correctness and measure TTFB, Tool Recall, and Turn Latency stats. | none | DONE |
| 2 | M2: Cloud Run System Log Audit & Executive Report | Run `gcloud logging read` on `lenskart-memory-bot` to verify 0 unhandled exceptions, 0 embedding 404s, 0 NameErrors during the 10 sessions. Compile full latency profile table & findings into `LIVE_BENCHMARK_REPORT.md`. | M1 | IN_PROGRESS |

## Code Layout
- Repository Root: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat`
- Benchmark Output Artifacts: `LIVE_BENCHMARK_REPORT.md` (and any raw JSON/CSV log data produced by the worker)
