# E2E Test Infra: Gemini Live Sub-Millisecond Memorystore RAG

## Test Philosophy
- Opaque-box and requirement-driven testing.
- Methodology: Category-Partition + Boundary Value Analysis + Pairwise Interaction + Real-World Workload Testing.
- Target latency: Tool execution < 5.0ms (Average < 1.0ms) with zero dead air.

## Feature Inventory & Test Mapping
| # | Feature | Requirement | Tier 1 (Feature) | Tier 2 (Boundary) | Tier 3 (Cross-Feature) | Tier 4 (Workload) |
|---|---------|-------------|:----------------:|:-----------------:|:----------------------:|:-----------------:|
| 1 | Google Sheet Q&A Dataset Ingestion | ORIGINAL_REQUEST §R1 | ≥5 | ≥5 | ✓ | ✓ |
| 2 | Dual-Layer Redis/L1 Cache & Indexing | ORIGINAL_REQUEST §R1 | ≥5 | ≥5 | ✓ | ✓ |
| 3 | Decoupled Remote Vertex AI RAG | ORIGINAL_REQUEST §R2 | ≥5 | ≥5 | ✓ | ✓ |
| 4 | Startup Pre-warming Lifespan | ORIGINAL_REQUEST §R2, §R4 | ≥5 | ≥5 | ✓ | ✓ |
| 5 | Memorystore Valkey MCP Pattern | ORIGINAL_REQUEST §R3 | ≥5 | ≥5 | ✓ | ✓ |
| 6 | Sub-ms Grounded Query Retrieval | ORIGINAL_REQUEST §R4 | ≥5 | ≥5 | ✓ | ✓ |

## Test Architecture
- Test Runner: Python unittest / pytest (`server/tests/test_sheet_redis_rag.py`)
- Invocation: `PYTHONPATH=server ./server/venv/bin/python server/tests/test_sheet_redis_rag.py`
- Pass/Fail Semantics: 100% assertions pass, 0 failures, 0 errors.

## Test Tiers
1. **Tier 1 - Feature Coverage**:
   - Ingestion of 896 valid records into JSON and Redis.
   - Header exclusion and schema field validation (`question`, `answer`, `category`).
   - Keyword / token index creation and lookup.
   - Cache hit/miss lifecycle.
   - Tool callback execution via `search_knowledge_base_handler`.

2. **Tier 2 - Boundary & Corner Cases**:
   - Empty/whitespace query handling without throwing exceptions.
   - Currency symbol normalization (`₹`, `Rs.`, `Rupees`, `INR`).
   - Multiline answer preservation (40 records with `\n`).
   - Special unicode characters and quotes (`’`, `“`, `”`, `—`, `%`).
   - Redis offline / fallback resilience (L1 in-memory instant fallback).

3. **Tier 3 - Cross-Feature & Query Semantics**:
   - Query: "minimum amount to lend" -> returns ₹250 manual lending threshold.
   - Query: "maximum amount per PAN ₹50 Lakh" -> returns ₹50 Lakh statutory ceiling & CA net worth certificate threshold.
   - Query: "14 month EMI option" -> returns MTL tenure & 18%+ interest rate.
   - Query: "CTO February 2025 update" -> returns Dipesh Karki and STL ₹100 Cr milestone.
   - Fallback to Canonical Domain Knowledge when sheet search yields no match.

4. **Tier 4 - Real-World Latency & High-Throughput Workload**:
   - 100-query benchmark across representative lending questions.
   - Assert Average Latency < 2.0ms.
   - Assert p99 Latency < 5.0ms.
   - FastAPI server startup lifespan pre-warming time < 50ms.

5. **Tier 5 - Adversarial Coverage Hardening**:
   - Adversarial white-box gap auditing (Challenger-driven).
   - Extreme input fuzzing and concurrency stress tests.
