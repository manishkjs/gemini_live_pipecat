# Original User Request

## 2026-07-24T09:34:57Z

Verify the live production Lenskart Memory Bot (`https://lenskart-memory-bot-853612069841.us-central1.run.app`) across 10 distinct simulated user sessions. Check functional correctness (multi-tenant identity setup, `search_user_memory` vector retrieval via `gemini-embedding-001`, silence cut-off) and generate a comprehensive latency profile (Turn-to-First-Byte / TTFB, tool execution latency, and overall turn duration).

Requirements:
- R1. Automated Live Session Verification Suite (10 Distinct Sessions): Create and execute an automated verification script that initiates 10 separate client sessions (`user:test_session_1` through `user:test_session_10`) against the live Cloud Run endpoint `https://lenskart-memory-bot-853612069841.us-central1.run.app`. Verify exact core interaction flow (`identify_user(name="manish")` and `search_user_memory` via query `"What is my son's name?"` with `SIMILARITY_THRESHOLD >= 0.65`).
- R2. Comprehensive Latency Profiling across 10 Sessions: Accurately measure and log TTFB, Tool Recall Latency (`identify_user` and `search_user_memory`), and Total Turn Latency. Compute summary statistics (Mean, Median p50, p90, p95, Min, Max). Median p50 TTFB must be under `<1000ms`.
- R3. Final Verification Report & Error Audit: Inspect Cloud Run system logs (`gcloud logging read`) during/after run to confirm zero unhandled exceptions, zero `404 NOT_FOUND` embedding errors, and zero `NameError` crashes. Compile findings and latency distribution table into an executive summary report artifact.
