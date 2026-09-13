# Multi-Agent Fleet Architectural Review & Telemetry Post-Mortem

> **Document Status:** Converged Specification & Execution Blueprint  
> **Date:** 13 September 2026  
> **Branch:** `ui-changes-sep` (Commit `080ff5b` audit)  
> **Channel Origin:** AgentChattr `#general`  
> **Participants:**
> - **Manish** (`@Manish`) — Lead Architect & Principal Engineer
> - **Claude Opus 5** (`@opus`) — System Architect & Deep Code Critic
> - **Codex Argolis** (`@codex`) — Adversarial Second Opinion & Verification
> - **Gemini 3.8 Flash High** (`@flash`) — Sole Implementer
> - **Gemini Next** (`@next`) — Dedicated Testing & Verification Engineer

---

## 1. Executive Summary & Purpose

This document preserves the dialectical architecture review and post-mortem conducted across the multi-agent pairing fleet in AgentChattr `#general`.

It serves as the **mandatory technical reference for downstream agents** implementing the next phases of `gemini_live_pipecat`. All downstream PRs must adhere strictly to the invariants, contracts, and test gates defined here.

---

## 2. Baseline Test Gates (Verified Green on `ui-changes-sep`)

Prior to code inspection, the repository baseline was verified:
- **Backend Unit Tests:** **124/124 passed** in 0.55s (`PYTHONPATH=server python3 -m unittest discover -s server/tests -p "test_*.py"`).
- **Frontend Tests:** **93/93 passed** in 2.4s (`demos/voice-studio`: `node --test tests/*.test.mjs`).
- **Production Builds:** Clean builds for `client` and `demos/voice-studio` (0 TypeScript / Vite errors).

---

## 3. Token Economics & Duplex Voice Realities

1. **Zero Implicit Caching on Duplex Voice:**
   Across 13 turns on `gemini-2.5-flash-native-audio`, `gemini-3.1-flash-live`, and `gemini-3.5-flash-live`, `cached_content_token_count` was **0 on every turn**. There is no implicit cache discount during active Live API duplex sessions.
2. **Re-Bill Amplification:**
   Re-billing amplification was measured at **2.89× to 2.95× over 4–5 turns**. The root system instruction is re-evaluated and re-billed across every turn.
3. **Dynamic Prompt Cards Buy Focus, Not Savings:**
   Injected cards via `inject_directive` / `send_realtime_input` are re-billed on every subsequent turn from injection to session teardown. Cards exist to ensure cognitive focus (e.g. keeping pincode booking rules isolated from vehicle discovery), not to reduce token counts.
4. **Candidate Extraction & The Revision Triad:**
   To prevent Voice Studio phase tracking from locking up due to optional model tool invocation, slot extraction (pincode, date, slot) is performed deterministically server-side, governed by an explicit revision triad:
   - `current_revision`: incremented whenever slot data changes.
   - `presented_revision`: set to `current_revision` upon assistant read-back.
   - `confirmed_revision`: set to `presented_revision` upon caller confirmation.
   - Dispatch of booking tools requires `confirmed_revision == current_revision`.

---

## 4. The Telemetry Autopsy: 4 Critical Flaws in `diagnostic_buffer.py`

Code inspection by Opus and Codex isolated four structural defects producing invalid latency metrics:

### Blocker 1: Positional Zipping (`diagnostic_buffer.py:252-253`)
```python
s = stt_vals[i] if i < len(stt_vals) else 0.0
l = llm_vals[i] if i < len(llm_vals) else 0.0
t = tts_vals[i] if i < len(tts_vals) else 0.0
total = s + l + t
```
- **Failure Mode:** Samples are paired by array index. Any dropped sample (e.g. caller barge-in aborting TTS) permanently desynchronizes all future turns. Turn N's TTS is added to Turn N+1's STT.
- **Conceptual Defect:** Summing stage TTFBs is not turnaround. Streaming stages overlap. Adding them overstates elapsed time; zero-filling understates it.

### Blocker 2: Blind 1.0-Second Suppression (`diagnostic_buffer.py:93-97`)
```python
dedup_key = f"{sess}:{stage}"
if dedup_key in _LAST_LATENCY_TIME and (now - _LAST_LATENCY_TIME[dedup_key]) < 1.0:
    return
```
- **Failure Mode:** Deduplication lacks turn awareness and silently drops any stage measurement occurring within 1.0s of the previous one.
- **Impact:** Any fast turn completing in < 1.0s is silently swallowed. The system discards the very low-latency turns it was engineered to deliver, directly exacerbating the positional shift in Blocker 1.

### Blocker 3: Corrupted Badge & String Parser (`diagnostic_buffer.py:185, 188`)
```python
clean_msg = clean_msg.replace("s", " ").replace("ms", " ")
...
if val < 20.0:
    val = val * 1000.0
```
- **Failure Mode:** Replacing `"s"` turns `"ms"` into `"m "` (preventing the `"ms"` replacement from firing) and shreds any word containing the letter "s".
- **Impact:**
  - `TTSService TTFB: 15 ms` becomes **15,000 ms** (15 seconds!).
  - `TTSService TTFB: 15ms` becomes `None`.
  - `worker 7 TTFB: 0.25 s` matches `7` and becomes **7,000 ms**.
  - `GeminiLiveLLMService` is matched by generic `LLMService` due to top-to-bottom parser order.

### Blocker 4: Unbounded Memory & Process-Wide Clearing (`diagnostic_buffer.py:13`)
- `TURN_LATENCY_RECORDS` is an unbounded list that leaks memory over time.
- `/api/logs` without `session_id` clears or reads logs across all concurrent user sessions.

---

## 5. Architectural Invariants Locked by the Fleet

### A. Pipeline Ownership of `turn_id`
- Exactly **one** monotonic integer counter per session is owned and minted by the pipeline orchestrator.
- Incremented strictly on `UserStoppedSpeakingFrame` (intercepted in `agent.py:161` and `agent_live.py:850`).
- Stamped into frame metadata (`frame.metadata["turn_id"]`) and propagated to all derived frames and asynchronous callbacks.
- Downstream services (STT, LLM, TTS) strictly consume `turn_id`; they never mint their own identifiers.

### B. Barge-in Turn Boundary Contract
- **Definition:** The truncated bot response is the incomplete conclusion of **Turn N** (`status="interrupted"`). The interrupting caller speech opens **Turn N+1** upon speech end.
- **Interval Termination:** When barge-in interrupts bot playback, the open timing interval for Turn N is closed immediately.
- The field `"turnaround_ms"` is **strictly omitted** (absent from the payload, never `None` or `0.0`), preventing invalid zero-fill fallbacks. Late callbacks cannot reopen an interrupted turn.

### C. Session Teardown: The `abandoned` Status
- If a caller hangs up or the websocket disconnects while a turn interval is open, the pending turn must be immediately closed with `status="abandoned"`.
- Open intervals must never be left dangling in memory.
- The three valid terminal statuses for a turn are: `ok`, `interrupted`, and `abandoned`.

### D. Eliminating Dedup & Preserving Multi-Sentence TTS
- Deduplication was a symptom of having three uncoordinated log paths (raw logs, custom calculations, Pipecat logs).
- With a single, explicit Python callback (`record_metric()`), duplicate events are impossible by construction.
- The dedup dictionary, seen-set, and timer debounces are completely eliminated. This allows legitimate multi-sentence TTS streams to emit multiple TTFBs per turn without being dropped.

### E. The VAD Timing Reality: Frame Arrival vs. Perceived Latency
Let `S` = actual caller speech end, `V = S + padding` = VAD stop frame arrival, and `A` = first bot audio playback.
- **Perceived Delay:** `A − S` (what the caller actually experiences waiting in silence).
- **Frame-Anchored Delay:** `A − V = (A − S) − padding`.
- **Understatement:** Anchoring latency solely on `UserStoppedSpeakingFrame` arrival understates perceived caller latency by the silence detection window (`stop_secs=0.4` / 400ms baseline in `agent.py:702` and `agent_live.py:1033`).
- **Latency Blindness:** Crucially, `A − V` measures pipeline execution work and is insensitive to VAD tuning. If `stop_secs` is reduced from 0.4s to 0.2s, the caller experiences an immediate 200ms speedup, but `vad_stop_to_first_server_audio_ms` reports **0 change**.
- **Retiring "Perceived" from Server Metrics:** Until client-side playback buffer onset instrumentation lands in PR #3, the term "perceived" is retired from server-side telemetry.

#### Latency Metric Acceptance Criteria & Boundary Definitions

| Status | Metric Name | Definition & Endpoint Boundary |
|---|---|---|
| **Measured** | `vad_stop_to_first_server_audio_ms` | `UserStoppedSpeakingFrame` event → first server audio chunk emission on WebSocket |
| **Estimated** | `estimated_speech_end_to_first_server_audio_ms` | Caller speech end → first server audio emission, computed as `vad_stop_to_first_server_audio_ms + vad_stop_padding_ms` (configured `stop_secs=0.4` attached as metadata) |
| **Unavailable today** | *Caller-perceived turnaround latency* | True acoustic speech end → client speaker playback onset. **Deferred to PR #3** (requires client-side playback buffer timestamp instrumentation) |

### F. Krisp VIVA Turn Pinning Caveat
- `pipecat-ai==1.2.1` is pinned at `requirements.txt:61`. In 1.2.1, `KrispVivaTurn` hardcodes `botSpeaking=False`, meaning TTv3's reset-while-bot-speaks path is not wired up.
- While `ui-changes-sep` currently uses Silero (where the barge-in spec holds), any future merge of Krisp must re-validate the N / N+1 boundary rather than assuming TTv3 handles reset correctly.

### G. Bounded Storage: Single Process-Wide Flat Deque
- Replace `TURN_LATENCY_RECORDS` with a single flat `deque(maxlen=2000)` process-wide (ceiling of 2,000 records total across all sessions, preventing unbounded memory leaks).
- Each record carries `(session_id, turn_id, bot_type, stage, value_ms, status)`.
- Reads and clears strictly filter by non-empty `session_id`.
- **Global Eviction Caveat:** Retention is global; a long concurrent session can truncate another's history. Absent records are not proof a metric was never emitted.

### H. Structural Fast-Boot Test Gate (`sys.modules`)
- Heavy AI SDKs (`grpc`, `pipecat`, `google.genai`, `vertexai`, `google.cloud.speech_v2`) must be deferred to session factory/handshake time.
- Enforced via a deterministic structural unit test:
  ```python
  import sys
  import server
  for mod in ("grpc", "pipecat", "google.genai", "vertexai", "google.cloud.speech_v2"):
      assert mod not in sys.modules, f"Eager import detected: {mod} loaded at module scope in server.py"
  ```

---

## 6. Implementation Roadmap for Downstream Agents

### PR #1: Telemetry Correctness & Interval Measurement (Net-Negative Lines)
1. Delete the Loguru scraper sink, regex parsers, badge parser, and `_LAST_LATENCY_TIME` in `diagnostic_buffer.py`.
2. Implement explicit structured metric emission:
   ```python
   record_metric(session_id: str, turn_id: str, bot_type: str, stage: str, value_ms: float, status: str = "ok")
   ```
3. Pipeline orchestrator mints `turn_id` on `UserStoppedSpeakingFrame` and propagates it to all downstream frames and async callbacks.
4. Measure pipeline turnaround as a wall-clock interval from `vad_stop_ts` to `first_server_audio_ts` (reporting `vad_stop_to_first_server_audio_ms`).
5. On barge-in, close Turn N immediately with `status="interrupted"` and omit `"turnaround_ms"` and `"vad_stop_to_first_server_audio_ms"` entirely.
6. On socket disconnect, close any open turn as `status="abandoned"` (omitting latency values).
7. Replace `TURN_LATENCY_RECORDS` with a single process-wide flat `deque(maxlen=2000)`. Require non-empty `session_id` on reads/clears.

### PR #2: Fast Boot, Asset Compression & UI Decoupling
1. Defer heavy SDK imports in `server.py` to handshake/session factory, enforcing the `sys.modules` structural test.
2. Convert the 12 MB avatar PNGs in `demos/voice-studio/public/personas/` to 400x400 WebP (~250 KB).
3. Decouple `transcript-panel.tsx` from the hardcoded `persona.id === "lamborghini-concierge"` check to support Ananya and Kavya SOP tracking.

### PR #3: Priya Outbound Sales State Machine & Revision Triad
1. Implement pure server-side candidate extraction for pincodes, dates, and slots on finalized turns.
2. Implement the state reducer enforcing `current_revision`, `presented_revision`, and `confirmed_revision`.
3. Require `confirmed_revision == current_revision` before booking tool dispatch.
