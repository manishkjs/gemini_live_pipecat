# Scope: Milestone 1 — Core Memory Profile Pre-load (`pre_load_user_profile` & Phase 1 Alignment)

## Architecture
- Module/package boundaries: `server/memory_function.py`, `server/agent_live.py`, `docs/plans/`
- Data flow: At WebSocket connection or session identification, `pre_load_user_profile(user_id, max_tokens=250)` retrieves user facts from Phase 1 Mem0 (`pgvector` on Cloud SQL) or mock/local store in test mode, formats/prioritizes them (`M7` -> `M5` -> `M4 (N=3)` -> `M1/M2/M3`), truncates strictly to `max_tokens` (~1000 chars or exact token estimate), and injects into Gemini Live `system_instruction`.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Core Memory Profile Pre-load | Create/verify `pre_load_user_profile` in `server/memory_function.py` and `server/agent_live.py` with strict 250-token ceiling, priority sorting, multi-tenant isolation, and complete unit tests (`test_memory_function.py`, `test_agent_memory_integration.py`). Also ensure `docs/plans/B_by_Lenskart_Memory_Engine_Architecture.md` reflects Milestone 1 Path 1 specifications accurately. | none | IN_PROGRESS |

## Interface Contracts
### `server/memory_function.py` ↔ `server/agent_live.py`
- `pre_load_user_profile(user_id: str, max_tokens: int = 250) -> str`
  - Returns formatted string of prioritized user facts (`M7 unverified allergies`, `M5 commitments`, `N=3 M4 habits`, `M1/M2/M3 identity & preferences`).
  - Enforces strict ceiling of `max_tokens` (e.g. 250 tokens / ~1000 characters).
  - Multi-tenant isolation: `user_id` strictly scopes query (e.g. `user:rohan` vs `user:priya`).
