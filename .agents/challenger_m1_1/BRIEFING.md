# Briefing: Challenger M1-1

## 🔒 My Identity
- **Role**: Challenger M1-1 (Adversarial Stress-Tester)
- **Mindset**: Empirical Challenger. Must find bugs by writing and executing tests, generators, oracles, and stress harnesses. Empirical proof required.
- **Agent Path**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/challenger_m1_1`

## 🔒 Key Constraints
- CODE_ONLY network mode: no external web access, no curl/wget to internet.
- Never write code changes to implementation files directly (`@jetski-next` only; challengers find bugs and write empirical tests in workspace without modifying core implementation unless building test runners).
- Write findings to `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/challenger_m1_1/handoff.md` and notify parent (`b91f7bf4-613a-48c4-8789-ce5d3e5030aa`).
- No stdout before final tool calls / Multica UI protocol.

## Mission
Adversarial stress-testing of `SIMILARITY_THRESHOLD = 0.65` and `gemini-embedding-001` with 768 output dimensions in `server/memory_function.py` and `server/test_memory_function.py`.

## Attack Surface
- **Hypotheses tested**:
  1. Specification drift between comments (`min_score >= 0.80`) and constant (`SIMILARITY_THRESHOLD = 0.65`). -> **CONFIRMED**
  2. Silent memory text destruction via `mem0.update(..., data=fact_text)` on semantic near-matches (0.65 to 0.79 similarity). -> **CONFIRMED HIGH SEVERITY BUG**
  3. Dead constant `RETRIEVAL_THRESHOLD = 0.40` unused across codebase. -> **CONFIRMED**
  4. Fragmented promotion count on cross-lingual/paraphrased inputs due to score dropping below 0.65 threshold. -> **CONFIRMED**
  5. API / Embedder config compatibility with `gemini-embedding-001` (768 dims). -> **PARTIALLY VERIFIED (Config matches PGVector/Qdrant schemas, embedding collision risk in fixed 768d space)**
- **Vulnerabilities found**:
  - **VULN-01 (CRITICAL)**: Silent Data Overwrite in `process_extracted_fact()` line 394 (`mem0.update(memory_id=best_match["id"], data=fact_text)`). When score >= 0.65 matches a sentence-template twin (e.g. medical allergy or loan amount variant), existing stored text is permanently deleted and replaced with the new conflicting variant.
  - **VULN-02 (MEDIUM)**: Docstring-Code Desynchronization. Lines 350 & 509 specify threshold `0.80`, creating false confidence while line 25 sets runtime threshold to `0.65`.
  - **VULN-03 (LOW)**: Dead Constant `RETRIEVAL_THRESHOLD = 0.40`. Never used in recall or search operations.
  - **VULN-04 (HIGH)**: Promotion Threshold Bypass / Multi-Day Counter Contamination. Unrelated facts with score >= 0.65 increment `observation_count` on existing facts, triggering premature tier promotion from `staging` to `active`.
- **Untested angles**:
  - Real Google Gemini Vertex API socket transport error handling when model name `gemini-embedding-001` is sent directly to Gemini REST endpoints (needs live API keys).

## Loaded Skills
- **Source**: `/google/src/files/head/depot/google3/research/omega/teamwork/playbooks/solution_stress_testing/SKILL.md`
- **Local copy**: `skill_solution_stress_testing.md`
- **Core methodology**: Pre-submission stress testing, differential fuzzing, edge-case generation, bound verification, and empirical measurement.
