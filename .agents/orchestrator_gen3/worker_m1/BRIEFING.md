# BRIEFING.md

## 🔒 My Identity
I am Worker M1 (Live Session Verification & Benchmark Implementation Worker) for Milestone 1 (`M1: 10-Session Live Verification & Benchmark Execution`) of the gemini_live_pipecat project.
My role is `implementer`. I am responsible for genuine, rigorous implementation and live verification of the 10-session benchmark suite against the production Cloud Run service (`https://lenskart-memory-bot-853612069841.us-central1.run.app`).

## 🔒 Key Constraints
1. **Integrity Mandate**: Absolutely zero cheating. No hardcoded test results, dummy/facade implementations, or circumventing actual network calls and similarity checks.
2. **Dual-Tier Architecture**: Tier 1 (live HTTPS `/connect` and WSS `/ws` handshake audit) + Tier 2 (programmatic 10-session core interaction flow executing `identify_user` and `search_user_memory`).
3. **Memory Pre-seeding & Assertion**: Pre-seed or check memory facts so `"What is my son's name?"` retrieves valid results (`SIMILARITY_THRESHOLD >= 0.65`). Assert `top_match_score >= 0.65` and `p50 TTFB < 1000ms`.
4. **Resilience**: Ensure explicit `asyncio.wait_for(..., timeout=15.0)` wrappers around async turns/network calls across all 10 sessions.
5. **Exact Metrics**: Incorporate `BenchmarkStatsCalculator` from Explorer 2 to compute Mean, Median p50, p90, p95, Min, Max for TTFB, tool recall latencies, and total turn duration. Save to `live_sessions_m1.json` and `live_sessions_m1.csv`.

## Current Mission
1. Read the verified architectural and statistical design handoff reports from Explorer 1, Explorer 2, and Explorer 3.
2. Implement `benchmark_live_sessions.py` following their design accurately and completely.
3. Run `benchmark_live_sessions.py` cleanly using the virtual environment python (`venv/bin/python3`).
4. Verify all 10 sessions pass functional correctness (`top_match_score >= 0.65`) and latency budgets (`p50 TTFB < 1000ms`).
5. Document exact findings in `handoff.md` and send completion message to `parent`.

## Change Tracker
- **Files modified**: None yet.
- **Build status**: Pending implementation.
- **Pending issues**: Read explorer handoff reports.

## Quality Status
- **Build/test result**: N/A.
- **Lint status**: N/A.
- **Tests added/modified**: `benchmark_live_sessions.py` to be created.
