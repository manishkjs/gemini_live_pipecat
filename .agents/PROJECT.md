# Project: Mem0 Embedding Bugfix & Deployment (`gemini_live_pipecat`)

## Architecture & Goal
- Upgrade Mem0 embedding configuration to solve 404 text embedding error.
- Model: `gemini-embedding-001`
- Output dimensions: `768`
- `SIMILARITY_THRESHOLD`: `0.65`
- Test file to update: `test_memory_function.py`
- Git target: branch `mem0-implementation`
- Cloud Run target service: `lenskart-memory-bot`

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Embedding & Unit Tests | Change embedding model config to `gemini-embedding-001` (768 dims, threshold 0.65), update `test_memory_function.py`, run unit tests | none | IN_PROGRESS |
| 2 | M2: Git Branching | Commit changes to branch `mem0-implementation` | M1 | PLANNED |
| 3 | M3: Cloud Run Deploy | Deploy updated container service `lenskart-memory-bot` to Cloud Run | M2 | PLANNED |

## Code Layout
- Repository Root: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat`
- Tests: `test_memory_function.py` (and potential unit test files)
