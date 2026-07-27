# Plan: Fix Mem0 Text Embedding 404 Error, Update Tests, Git Branch & Cloud Run Deploy

## Project Goal
Fix Mem0 Text Embedding 404 error by migrating/upgrading to `gemini-embedding-001` with `768` dimensions and `SIMILARITY_THRESHOLD=0.65`. Update unit tests in `test_memory_function.py`, verify build/test passes, commit changes to branch `mem0-implementation`, and deploy service `lenskart-memory-bot` to Cloud Run.

## Decomposed Milestones

### Milestone 1: Codebase Investigation & Embedding Model Bugfix
- **Objective**: Identify all occurrences of text embedding models, Mem0 configuration, dimensions, and similarity thresholds in `gemini_live_pipecat`. Upgrade embedding model to `gemini-embedding-001`, dimensions to `768`, and `SIMILARITY_THRESHOLD` to `0.65`.
- **Unit Testing**: Update `test_memory_function.py` and run python test suite to ensure tests pass.
- **Roles**:
  - `teamwork_preview_explorer` (3 agents in parallel / investigation phase)
  - `teamwork_preview_worker` (1 agent to implement changes and verify tests)
  - `teamwork_preview_reviewer` (2 agents to review and run test commands)
  - `teamwork_preview_challenger` (2 agents to empirically stress-test edge cases)
  - `teamwork_preview_auditor` (1 agent to conduct forensic integrity audit)
- **Gate Criteria**: Passing tests, positive review, challenger pass, clean forensic audit.

### Milestone 2: Git Branch & Version Control Management
- **Objective**: Ensure branch `mem0-implementation` exists/is active, stage modified files (`test_memory_function.py` and embedding files), and commit changes cleanly.
- **Roles**:
  - `teamwork_preview_worker` (1 agent to execute git branch creation and commit)
  - `teamwork_preview_reviewer` (1 agent to verify git status and log)

### Milestone 3: Cloud Run Deployment & Production Health Check
- **Objective**: Deploy `gemini_live_pipecat` to Cloud Run service `lenskart-memory-bot`. Verify service endpoint or deployment status.
- **Roles**:
  - `teamwork_preview_worker` (1 agent to trigger and monitor cloud run deployment)
  - `teamwork_preview_reviewer` (1 agent to audit and confirm active deployment state)

## Execution Strategy & Discipline
- Dispatch workers exclusively using `invoke_subagent`.
- Pass mandatory integrity warnings to all workers.
- Verify every claim via test/build command outputs provided by subagents.
- Gate each milestone strictly before proceeding.
