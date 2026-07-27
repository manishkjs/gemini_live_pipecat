# Original User Request

## 2026-07-21T04:02:26Z

You are a Sub-Orchestrator (`teamwork_preview_orchestrator`) assigned to execute Milestone 1 of the Lenskart Memory Engine Architecture (`B by Lenskart`).

Your working directory is: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/sub_orch_m1_1`
Your project root / workspace directory is: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat`
Your parent conversation ID is: `520e0e94-82ad-49cd-9eee-24e3f730ed07`

First, read `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/.agents/sub_orch_m1_1/SCOPE.md`, `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/PROJECT.md`, and `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/docs/plans/B_by_Lenskart_Memory_Engine_Architecture.md` to understand your exact scope and requirements.

Your responsibilities:
1. Run the iteration loop (`Explorer -> Worker -> Reviewer -> Challenger -> Auditor`) for Milestone 1:
   - Create/verify `pre_load_user_profile(user_id: str, max_tokens: int = 250) -> str` in `server/memory_function.py`.
   - Ensure `pre_load_user_profile` enforces a strict 250-token ceiling (~1000 characters) and prioritizes core facts (`M7 unverified allergies`, `M5 commitments`, `N=3 M4 habits`, `M1/M2/M3 identity & preferences`).
   - Integrate `pre_load_user_profile` into `server/agent_live.py` (during user identification or session start so it is injected into `system_instruction`).
   - Add/verify unit tests inside `server/test_memory_function.py` and `server/test_agent_memory_integration.py` covering token ceiling compliance, priority sorting, and multi-tenant isolation (`user:rohan` vs `user:priya`).
2. You MUST NOT write implementation code or run tests yourself directly — always spawn `teamwork_preview_worker`, `teamwork_preview_reviewer`, `teamwork_preview_challenger`, and `teamwork_preview_auditor` subagents under `.agents/<type>_m1_1/` to do the actual code editing and verification.
3. Once all gate checks pass (worker build/test `python3 -m unittest server/test_memory_function.py -v` passes, reviewers approve, challenger confirms, and `teamwork_preview_auditor` gives a CLEAN verdict without any hardcoded/dummy hacks), update `SCOPE.md` status to `DONE`, write `handoff.md` in your working directory, and send a detailed report back to your parent via `send_message(Recipient="520e0e94-82ad-49cd-9eee-24e3f730ed07", ...)`. Start right away by initializing your `BRIEFING.md` and spawning your Explorer!
