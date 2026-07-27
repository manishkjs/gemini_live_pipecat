# BRIEFING.md

## 🔒 My Identity
- **Role**: Project Orchestrator (`teamwork_preview_orchestrator`)
- **Archetype**: Project Orchestrator
- **Working Directory**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen3`
- **Parent Conversation ID**: `e3a82a5c-7705-4f75-a4e2-22d30389a0ce` (Sentinel)
- **Level**: Project Orchestrator (Top)

## 🔒 Key Constraints
- **DISPATCH-ONLY**: MUST delegate all code execution, script creation, testing, verification runs, and log checks to subagents via `invoke_subagent`.
- **NO DIRECT WRITING/EDITING**: NEVER write or modify source code or verification scripts directly. May only write `.md` metadata files in `.agents/` folder.
- **NEVER RUN BUILDS/TESTS/BENCHMARKS DIRECTLY**: Require workers and reviewers to do so.
- **BINARY FORENSIC AUDIT VETO**: Non-negotiable binary veto on integrity violations.
- **SUCCESSION TRIGGER**: When spawn count >= 16 and subagents complete, spawn self-successor and hand off.

## 🔒 My Workflow
- **Pattern**: Project Pattern (Orchestrator -> Explorer -> Worker -> Reviewer -> Challenger -> Forensic Auditor cycle / or Milestone decomposition)
- **Iteration Config**: Explorer count = 3, Reviewer count = 2, Challenger count = 2, Auditor count = 1. Max iterations = 32.
- **Scope**: Verify the live production Lenskart Memory Bot (`https://lenskart-memory-bot-853612069841.us-central1.run.app`) across 10 distinct simulated user sessions (`user:test_session_1` through `user:test_session_10`). Check functional correctness (`identify_user(name="manish")` and `search_user_memory` via query `"What is my son's name?"` with `SIMILARITY_THRESHOLD >= 0.65`), profile latency (TTFB, Tool execution, Total Turn Latency; compute Mean, Median p50 < 1000ms, p90, p95, Min, Max), and verify zero system log errors (`gcloud logging read`).

## Succession Status
- Spawn count: 18 / 16
- Pending subagents: none
- Successor spawned: `1bfafd3d-618a-4a8e-854b-ff9657b77f46`
- Successor generation: `gen4`

## Team Roster
- `df8744b1-e564-41b1-bd3e-8b769af4fcef` (Explorer 1): Protocol & Client Architecture Investigator | Status: completed
- `129b4c02-5fc7-4a1e-8040-fdf476db1088` (Explorer 2): Latency Profiling & Statistics Designer | Status: completed
- `238ddd9c-3f06-4e6a-8197-e110215001d4` (Explorer 3): Execution & Cloud Run Log Analyst | Status: completed
- `8b7409b7-7e4d-4b0e-b98a-cf7bb0403cef` (Worker M1): Live Verification Suite Worker | Status: completed (REJECTED in Iteration 1)
- `527a24e2-278f-4d8d-8ef5-4ffb28ee62e2` (Reviewer 1): Verification & Code Reviewer 1 | Status: completed
- `21fd46b4-be46-4524-9fe9-069958148501` (Reviewer 2): Verification & Code Reviewer 2 | Status: completed (REQUEST_CHANGES - Integrity Violation)
- `b8091ef1-5e09-46d4-9218-2b03a5cbb6a6` (Challenger 1): Adversarial Stress Tester 1 | Status: completed
- `5f0a0268-bb4a-4932-95e2-4704a659fefc` (Challenger 2): Adversarial Stress Tester 2 | Status: completed
- `25296ac6-0d21-4f89-ad5b-91ab1fc855d0` (Forensic Auditor): Forensic Integrity Auditor | Status: completed (INTEGRITY VIOLATION)
- `198961cf-5575-4cc6-a7ac-8c04bae005a5` (Explorer 4): Genuine Latency Architecture Designer | Status: completed
- `7325d413-465b-4fb7-9a09-88f4a66ca170` (Explorer 5): Genuine Similarity & Persistence Designer | Status: completed
- `d6ae51e6-82e4-4710-990a-02432dbfb6c9` (Explorer 6): Authentic TTFB Measurement Analyst | Status: completed
- `821291bb-3723-4f69-b636-fcf614f4c6f4` (Worker M2): Remediation Implementation Worker | Status: completed
- `d9e8dbad-1fca-4c62-9940-5b38e6c26fd6` (Reviewer 3): Iteration 2 Code Reviewer 1 | Status: completed (APPROVED)
- `4b028c05-b93c-4fa6-b0ee-eb9d96427a1f` (Reviewer 4): Iteration 2 Code Reviewer 2 | Status: completed (APPROVED)
- `af67d7cf-9558-4027-a398-2fb235b3658e` (Challenger 3): Iteration 2 Adversarial Stress Tester 1 | Status: completed (Verified Safe)
- `047d2b8e-51ae-4112-bce9-6d53c3a75f1b` (Challenger 4): Iteration 2 Adversarial Stress Tester 2 | Status: completed (Verified Safe)
- `645df768-5ac9-4649-9832-3dbbcece3205` (Forensic Auditor 2): Iteration 2 Forensic Auditor | Status: completed (CLEAN)

## Active Mission & Context
- Mission: Milestone 1 (`M1: 10-Session Live Verification & Benchmark Execution`) is `DONE` & verified (`CLEAN` forensic audit). Milestone 2 (`M2: Cloud Run System Log Audit & Executive Report`) is `IN_PROGRESS`.
- Status: Cumulative spawn count (`18 / 16`) reached threshold. Executing self-succession (`orchestrator_gen4`) to execute M2 and deliver final report to Sentinel (`e3a82a5c-7705-4f75-a4e2-22d30389a0ce`).
