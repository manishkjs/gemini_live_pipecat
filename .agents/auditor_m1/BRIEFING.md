# BRIEFING.md

## 🔒 My Identity
- **Role**: Auditor M1 (Forensic Integrity Auditor)
- **Mission**: Strictly detect integrity violations in work product `server/test_memory_function.py` verified against `server/memory_function.py`.

## 🔒 Key Constraints
- Sole mission is to detect integrity violations in work products.
- Run every check from the Integrity Forensics section and verify all claims empirically. Trust NOTHING — verify EVERYTHING.
- If ANY check fails, verdict is INTEGRITY VIOLATION and reject the work product.
- Provide explicit verdict: `CLEAN` or `INTEGRITY VIOLATION`.
- 2-Phase Investigation Architecture: Phase 1 (Observe All) -> Phase 2 (Flag by Mode).
- Write full audit evidence and verdict to `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/auditor_m1/handoff.md` and notify parent (`b91f7bf4-613a-48c4-8789-ce5d3e5030aa`).

## Loaded Skills
- **Source**: System Forensic Auditor Protocol (`Integrity Forensics`)
- **Local copy**: N/A (embedded in agent system instructions)
- **Core methodology**: Forensic checks for hardcoded outputs, facades, fabricated outputs, mock bypasses, delegation violations.

## Current State & Plan
- [x] Initialized workspace and ORIGINAL_REQUEST.md
- [ ] Read `worker_m1` artifacts (`handoff.md`, `changes.md`)
- [ ] Conduct Phase 1 Source Analysis on `server/test_memory_function.py` and `server/memory_function.py`
- [ ] Conduct Phase 1 Behavioral & Static Diff Check
- [ ] Determine integrity mode and apply Phase 2 Flagging
- [ ] Generate Forensic Audit Report in `handoff.md`
- [ ] Notify parent via `send_message`

## Attack Surface
- **Hypotheses tested**: TBD
- **Vulnerabilities found**: TBD
- **Untested angles**: TBD
