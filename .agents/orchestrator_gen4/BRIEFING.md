# BRIEFING.md

## 🔒 My Identity
- **Role**: Project Orchestrator Successor (`teamwork_preview_orchestrator`)
- **Archetype**: Project Orchestrator (`orchestrator_gen4`)
- **Working Directory**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen4`
- **Parent Conversation ID**: `e3a82a5c-7705-4f75-a4e2-22d30389a0ce` (Sentinel)
- **Level**: Project Orchestrator (Top)

## 🔒 Key Constraints
- **DISPATCH-ONLY**: MUST delegate all code execution, script execution, log auditing, report generation, and verification checks to subagents via `invoke_subagent`.
- **NO DIRECT WRITING/EDITING**: NEVER write or modify source code or verification/report scripts directly. May only write `.md` metadata files in `.agents/` folder.
- **NEVER RUN BUILDS/TESTS/BENCHMARKS/GCLOUD DIRECTLY**: Require workers and reviewers to do so.
- **BINARY FORENSIC AUDIT VETO**: Non-negotiable binary veto on integrity violations.
- **SUCCESSION TRIGGER**: When spawn count >= 16 and subagents complete, spawn self-successor and hand off.

## 🔒 My Workflow
- **Pattern**: Project Pattern (Orchestrator -> Worker -> Reviewer -> Challenger -> Forensic Auditor cycle for Milestone 2).
- **Iteration Config**: Worker count = 1, Reviewer count = 1, Challenger count = 1, Auditor count = 1. Max iterations = 32.
- **Scope**: Execute Milestone 2 (`M2: Cloud Run System Log Audit & Executive Report`).
  1. Instruct `Worker` to run non-interactive `gcloud logging read` command confirming zero unhandled exceptions, zero `404 NOT_FOUND` embedding errors, and zero `NameError` crashes on `lenskart-memory-bot` (`us-central1`).
  2. Instruct `Worker` to compile the complete executive summary report artifact `LIVE_BENCHMARK_REPORT.md` (at root `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/LIVE_BENCHMARK_REPORT.md` and `.agents/LIVE_BENCHMARK_REPORT.md`), incorporating the exact M1 latency statistics (`live_sessions_m1.csv`), functional verification (`SIMILARITY_THRESHOLD = 0.65`, silence cut-off `0.4s`), and log audit findings.
  3. Run multi-role review gate (`Reviewer`, `Challenger`, `Forensic Auditor`) to verify `LIVE_BENCHMARK_REPORT.md`.
  4. Once verified (`CLEAN` audit), mark `M2` as `DONE` and send completion report via `send_message` to parent Sentinel (`e3a82a5c-7705-4f75-a4e2-22d30389a0ce`).

## Succession Status
- Spawn count: 5 / 16
- Pending subagents: `d5c1206c-f21a-45b5-a8cc-5b1bcb21fa13`

## Team Roster
- `5c323f00-dbbe-4101-87bc-fab2965bd256` (Worker M2 Iter 1): Live Session Verification & Report Worker | Status: completed
- `95dbd992-9608-4edd-ab0a-1d80fe0add82` (Reviewer M2): Verification & Report Reviewer | Status: completed (APPROVED)
- `a2fc862e-ffa8-4a9b-b5fe-b013ae2ddd8f` (Challenger M2): Adversarial Report Challenger | Status: completed (Counterexample Found / Flawed -> Table 2 numerical alignment needed)
- `c1009a2c-a208-4113-88ac-a9b08826abe7` (Auditor M2): Forensic Integrity Auditor | Status: completed (CLEAN)
- `d5c1206c-f21a-45b5-a8cc-5b1bcb21fa13` (Worker M2 Iter 2): Table 2 Mathematical Alignment Worker | Status: in-progress

## Active Mission & Context
- Mission: Milestone 1 (`M1: 10-Session Live Verification & Benchmark Execution`) is `DONE` & verified (`CLEAN` forensic audit). Milestone 2 (`M2: Cloud Run System Log Audit & Executive Report`) is `IN_PROGRESS` under our ownership (`orchestrator_gen4`).
