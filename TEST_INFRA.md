# E2E Test Infra: Cymbal Lending Voicebot

## Test Philosophy
- Opaque-box, requirement-driven. Derived from ORIGINAL_REQUEST.md.
- Hermetic zero-network mock architecture for Gemini Live, Vertex AI Flash, Pipecat audio frame pipelines, and Vector embeddings.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial + Real-World Workload Testing.

## Feature Inventory & Test Coverage Mapping
| # | Feature | Source (Requirement) | Tier 1 (Unit/Feature) | Tier 2 (Boundary/Edge) | Tier 3 (Cross-Feature) | Tier 4 (Real-World) |
|---|---------|---------------------|:---------------------:|:----------------------:|:----------------------:|:-------------------:|
| 1 | Lexical Identity Resolution | ORIGINAL_REQUEST §R1 | 5 tests | 5 tests | ✓ | ✓ |
| 2 | FactStore 8-Key State & History | ORIGINAL_REQUEST §R2 | 5 tests | 5 tests | ✓ | ✓ |
| 3 | Hypothetical Parameter 6-Turn TTL | ORIGINAL_REQUEST §R2 | 5 tests | 5 tests | ✓ | ✓ |
| 4 | Dual-Threshold Vector Engine (0.83/0.40) | ORIGINAL_REQUEST §R2 | 5 tests | 5 tests | ✓ | ✓ |
| 5 | 90-Day Cross-Session Hydration | ORIGINAL_REQUEST §R2 | 5 tests | 5 tests | ✓ | ✓ |
| 6 | `retrieve_memory` Tool Schema & Handler | ORIGINAL_REQUEST §R3 | 5 tests | 5 tests | ✓ | ✓ |
| 7 | Post-Session Downcar Worker & MD5 Hash | ORIGINAL_REQUEST §R4 | 5 tests | 5 tests | ✓ | ✓ |
| 8 | 8 Decision Stages & State Transitions | ORIGINAL_REQUEST §R5 | 5 tests | 5 tests | ✓ | ✓ |
| 9 | State Transition Gates (Skip/Committed/Close) | ORIGINAL_REQUEST §R5 | 5 tests | 5 tests | ✓ | ✓ |
| 10 | Hysteresis (2-Turn) & Staleness Guard (5-Turn) | ORIGINAL_REQUEST §R5 | 5 tests | 5 tests | ✓ | ✓ |
| 11 | Numeric Consistency Ledger | ORIGINAL_REQUEST §R5 | 5 tests | 5 tests | ✓ | ✓ |
| 12 | 5-Tier Human Escalation Matrix | ORIGINAL_REQUEST §R5 | 5 tests | 5 tests | ✓ | ✓ |
| 13 | Screen Navigation Flows (Deposit, KYC, Filters) | ORIGINAL_REQUEST §R6 | 5 tests | 5 tests | ✓ | ✓ |

## Test Architecture
- Test runner: `PYTHONPATH=server:server/tests ./venv/bin/python -m unittest discover -s server/tests -v`
- Pass/fail semantics: 100% passing tests (0 failures, 0 errors)
- Execution time: < 5.0 seconds total

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Aditya Sharma: First-Time Investor Journey | Turn 1 Elicitation, Discovery, Math Calculation, KYC, Downcar Extraction | Medium |
| 2 | Rajesh Kumar: HNW Multi-Session Profile Rehydration | 90-Day Profile Hydration, MTL Daily ₹24L, Downcar Idempotency | High |
| 3 | Skeptical Investor: Adversarial Objection & Escalation | Hysteresis Cooldown, NPA Objections, 5-Tier Escalation Callback Booking | High |
| 4 | Out-of-Bounds Parameter Rejection & Recovery | 9-Month Tenure Rejection, ₹60L Ceiling Rejection, Recovery to Valid STL/MTL | Medium |
