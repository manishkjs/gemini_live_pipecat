# Project: Cymbal Lending Voicebot — Gemini Enterprise Memory Bank & Consultative State Engine

## Architecture
The system consists of a real-time duplex voice pipeline using Pipecat and Gemini Live, integrated with deterministic financial tools, a dual-threshold vector and structured FactStore memory engine, an 8-stage decision state machine with transition gates, a numeric consistency ledger, a 5-tier escalation matrix, and an asynchronous post-session downcar memory extraction worker.

### Module Boundaries
- `server/memory_bank.py`: FactStore (8 canonical keys, turn-by-turn history, 6-turn TTL for hypothetical explore values), dual-threshold vector engine (0.83 deduplication, 0.40 retrieval, 90-day hydration), and `normalize_lexical_user_id`. [COMPLETED]
- `server/tools/tool_definitions.py`: Tool schemas and handlers including `retrieve_memory_schema`, `handle_retrieve_memory`, and registration in `get_standard_tools()`. [COMPLETED]
- `server/tools/navigation.py`: Complete screen-by-screen navigation flows (Escrow UPI/NetBanking deposit, STL/MTL selection, 3-step Digilocker KYC, 8 loan filter parameters). [COMPLETED]
- `server/system_prompt.py`: Turn 1 name elicitation greeting, Devanagari Hindi + Latin English code mixing, objection playbooks, memory recall directives. [COMPLETED]
- `server/phase_engine.py`: 8 Decision Stages (`UNAWARE` -> `DISENGAGED`), Stage Skip Guard (max +3), `COMMITTED` & Recommendation Gates (require amount), Close Gate (max 2 attempts), Hysteresis (2-turn cooldown on `HESITANT`), Staleness Guard (5-turn auto-advance), `NumericLedger`, and 5-Tier Human Escalation Matrix. [COMPLETED]
- `server/memory_downcar.py`: Asynchronous post-session background extraction worker with `gemini-2.5-flash-lite`, extracting 8 facts and episodic summary with idempotent MD5 content hash. [COMPLETED]
- `server/agent_live.py`: Pipecat pipeline lifecycle, tool registration, session hydration, and `on_client_disconnected` downcar trigger. [COMPLETED]
- `server/tests/`: Comprehensive 4-tier hermetic unit and integration test suite guaranteeing 100% pass rate. [COMPLETED - TEST_READY.md published]

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Lexical Identity Normalization | `normalize_lexical_user_id(raw_name)` -> deterministic `user_<normalized>` key | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Structured FactStore | 8 canonical financial keys (`amount`, `tenure_months`, `risk_preference`, `timeline`, `goal`, `occupation`, `city`, `experience`) | M1 | ORIGINAL_REQUEST §R2 |
| 3 | Fact Change History Log | Turn-by-turn audit trail with timestamps and values | M1 | ORIGINAL_REQUEST §R2 |
| 4 | Hypothetical Parameter TTL | 6-turn expiration for hypothetical exploration parameters | M1 | ORIGINAL_REQUEST §R2 |
| 5 | Dual-Threshold Vector Engine | 0.83 deduplication threshold, 0.40 retrieval threshold | M1 | ORIGINAL_REQUEST §R2 |
| 6 | 90-Day Cross-Session Hydration | Profile hydration from memories within 90 days | M1 | ORIGINAL_REQUEST §R2 |
| 7 | `retrieve_memory` Tool Schema & Handler | Non-blocking async tool to retrieve profile & episodic memories | M2 | ORIGINAL_REQUEST §R3 |
| 8 | System Prompt Turn 1 Elicitation & Memory Guidance | Elicit customer name on Turn 1 & prompt directives for memory recall | M2 | ORIGINAL_REQUEST §R1, §R3 |
| 9 | Screen-by-Screen Navigation Dataset | Escrow deposit, STL/MTL selection, 3-step Digilocker KYC, 8-filter options | M2 | ORIGINAL_REQUEST §R6 |
| 10 | 8 Decision Stages Enum | `UNAWARE`, `CURIOUS`, `INTERESTED`, `EVALUATING`, `HESITANT`, `READY`, `COMMITTED`, `DISENGAGED` | M3 | ORIGINAL_REQUEST §R5 |
| 11 | State Transition Gates & Skip Guard | Max 3 jumps forward unless `READY`, `COMMITTED` & Recommendation gates require `amount`, Close limiter max 2 attempts | M3 | ORIGINAL_REQUEST §R5 |
| 12 | Hysteresis & Staleness Guard | 2-turn cooldown on `HESITANT`, 5-turn auto-advance | M3 | ORIGINAL_REQUEST §R5 |
| 13 | Numeric Consistency Ledger | Track quoted returns, maturity amounts, EMI payouts across turns | M3 | ORIGINAL_REQUEST §R5 |
| 14 | 5-Tier Escalation Matrix | Repeated human requests (>=2) or questions (>=3) trigger callback booking | M3 | ORIGINAL_REQUEST §R5 |
| 15 | Post-Session Downcar Extraction Service | Background worker `run_post_session_downcar` with `gemini-2.5-flash-lite` | M4 | ORIGINAL_REQUEST §R4 |
| 16 | Idempotent MD5 Storage | Content MD5 hash prevents duplicate writes on reconnects | M4 | ORIGINAL_REQUEST §R4 |
| 17 | Disconnect Event Downcar Trigger | Hook `run_post_session_downcar` to `on_client_disconnected` in `agent_live.py` | M4 | ORIGINAL_REQUEST §R4 |
| 18 | E2E Testing Suite (Tiers 1-4) | Comprehensive hermetic test suite covering all features, boundaries, interactions, and real-world journeys | E2E_TEST | ORIGINAL_REQUEST Acceptance Criteria |
| 19 | Full E2E Test Suite Pass & Adversarial Hardening | 100% test pass on `python -m unittest discover -s server/tests` + Tier 5 adversarial verification | M5 | ORIGINAL_REQUEST Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Memory Bank Core & Lexical Identity | Implement `server/memory_bank.py` (FactStore, Vector Engine 0.83/0.40, Lexical Normalization, 90d Hydration) | none | DONE |
| M2 | Tools Configuration & Prompt Alignment | Implement `server/tools/tool_definitions.py` (`retrieve_memory`), `server/tools/navigation.py`, and `server/system_prompt.py` | M1 | DONE |
| M3 | 8 Decision Stages & Numeric Ledger | Implement `server/phase_engine.py` (8 Decision Stages, Skip/Committed/Recommendation/Close Gates, Hysteresis, Staleness, NumericLedger, 5-Tier Escalation) | M1 | DONE |
| M4 | Downcar Service & Live Integration | Implement `server/memory_downcar.py` and wire `server/agent_live.py` (disconnect hook, tool registration, session hydration) | M1, M2, M3 | DONE |
| E2E_TEST | E2E Testing Infrastructure Track | Create Tier 1-4 comprehensive test modules and publish `TEST_READY.md` | none (independent track) | DONE |
| M5 | Final E2E Pass & Adversarial Hardening | Pass 100% of E2E test suite + Tier 5 adversarial coverage hardening | M4, E2E_TEST | IN_PROGRESS |

## Interface Contracts
### `server/memory_bank.py`
- `normalize_lexical_user_id(raw_name: str) -> str`
- `FactStore`: `set_fact(key, value, turn_id, is_hypothetical=False)`, `get_fact(key)`, `get_all_facts()`, `tick_turn(turn_id)`, `get_change_history()`
- `MemoryBank`: `add_memory(user_id, content, metadata=None, content_hash=None) -> bool`, `search_memories(user_id, query, threshold=0.40, limit=5) -> List[Dict]`, `hydrate_user_profile(user_id, days_lookback=90) -> Dict`

### `server/tools/tool_definitions.py`
- `retrieve_memory_schema: FunctionSchema`
- `async def handle_retrieve_memory(params: FunctionCallParams)`

### `server/phase_engine.py`
- `DecisionStage(IntEnum)`: 8 stages
- `StageTransitionManager`: `can_transition(from_stage, to_stage, fact_store, user_intent, turn_id) -> Tuple[bool, str]`
- `NumericLedger`: `record_quote(principal, tenure_months, xirr_pct, profit, maturity_amount, monthly_emi=None)`, `verify_quote(principal, tenure_months, quoted_maturity) -> bool`
- `EscalationTracker`: `record_user_query(text)`, `record_human_request()`, `get_escalation_tier() -> int`

### `server/memory_downcar.py`
- `async def run_post_session_downcar(session_id: str, user_id: str, transcript_history: List[Dict[str, str]], memory_bank: Any) -> Dict[str, Any]`

## Code Layout
- Exclusive file ownership per milestone:
  - M1 Worker: `server/memory_bank.py` [COMPLETED]
  - M2 Worker: `server/tools/tool_definitions.py`, `server/tools/navigation.py`, `server/system_prompt.py` [COMPLETED]
  - M3 Worker: `server/phase_engine.py` [COMPLETED]
  - M4 Worker: `server/memory_downcar.py`, `server/agent_live.py` [COMPLETED]
  - E2E Test Writer: `server/tests/test_memory_bank.py`, `server/tests/test_retrieve_memory_tool.py`, `server/tests/test_memory_downcar.py`, `server/tests/test_decision_stages_gates.py`, `server/tests/test_numeric_ledger.py`, `server/tests/test_navigation_flows.py`, `server/tests/test_integration_memory_voice.py`, `server/tests/test_consultative_e2e_scenarios.py`, `server/tests/__init__.py` [COMPLETED]
