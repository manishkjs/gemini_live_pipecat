# BRIEFING.md

## 🔒 My Identity
- **Role**: Project Orchestrator (`teamwork_preview_orchestrator`)
- **Archetype**: Project Orchestrator
- **Working Directory**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/orchestrator_gen2`
- **Parent Conversation ID**: `1bf14169-16d2-4513-9db6-3e4904953b2c`
- **Level**: Project Orchestrator (Top)

## 🔒 Key Constraints
- **DISPATCH-ONLY**: MUST delegate all code execution, modification, testing, builds, git operations, and cloud deployments to subagents via `invoke_subagent`.
- **NO DIRECT WRITING/EDITING**: NEVER write or modify source code files directly. May only write `.md` metadata files in `.agents/` folder.
- **NEVER RUN BUILDS/TESTS DIRECTLY**: Require workers and reviewers to do so.
- **BINARY FORENSIC AUDIT VETO**: Non-negotiable binary veto on integrity violations.
- **SUCCESSION TRIGGER**: When spawn count >= 16 and subagents complete, spawn self-successor and hand off.

## 🔒 My Workflow
- **Pattern**: Project Pattern (ephemeral Orchestrators / Explorer -> Worker -> Reviewer -> Challenger -> Forensic Auditor cycle)
- **Iteration Config**: Explorer count = 3, Reviewer count = 2, Challenger count = 2, Auditor count = 1. Max iterations = 32.
- **Scope**: Fix Mem0 Text Embedding 404 Error, upgrade to `gemini-embedding-001` with 768 output dimensions and `SIMILARITY_THRESHOLD=0.65` in `gemini_live_pipecat`. Update `test_memory_function.py`, verify unit tests, commit to branch `mem0-implementation`, deploy to Cloud Run `lenskart-memory-bot`.

## Succession Status
- Spawn count: 13 / 16
- Pending subagents: reviewer_m3

## Team Roster
- `ef92e921-deaa-4b20-ad1e-026af950af64` (Explorer 1): Codebase Embedding Explorer | Status: completed
- `ad3b0e60-63c6-4fe0-ab13-93b06c73dc12` (Explorer 2): Unit Test Analyst | Status: completed
- `d1f35445-dd7a-4483-be9d-7c113fb7ce36` (Explorer 3): DevOps Deployment Analyst | Status: completed
- `d8f2d55a-487c-490b-9450-7bf3971bdc90` (Worker M1): Code & Test Update Worker | Status: completed
- `fefc943d-65a1-4395-a363-ed1a38c22be8` (Reviewer 1): Verification & Code Reviewer | Status: completed (APPROVED)
- `2b927541-82ac-4cb2-9029-92da783f6ad8` (Reviewer 2): Verification & Code Reviewer | Status: completed (APPROVED)
- `b7d7c72b-22a7-4454-8c7a-68ae239e6e3f` (Challenger 1): Adversarial Stress Tester | Status: completed
- `efc1823d-2518-4623-972a-d968cac2ece9` (Challenger 2): Dimensionality Challenger | Status: completed
- `4034280f-deda-430e-b62d-db6beda97b8f` (Forensic Auditor): Integrity Auditor | Status: completed (CLEAN)
- `861c011e-620d-4fe1-a93c-26c62d7f45cb` (Worker M2): Git Branch & Commit Worker | Status: completed
- `00f4a410-513e-4aee-9053-ad6be269b664` (Reviewer M2): Git Verification Reviewer | Status: completed (APPROVED)
- `e4ff37c2-8f5c-4673-8876-9b62044c4ddd` (Worker M3): Cloud Run Deployment Worker | Status: completed
- `reviewer_m3` (Reviewer M3): Cloud Run Verification Reviewer | Status: in-progress

## Active Mission & Context
- Mission: Milestones 1 & 2 DONE. Milestone 3 deployment built & serving. Running Reviewer M3 verification.
- Status: Initial task assessment and plan creation.
