---
name: gemini-live
description: Technical reference, routing invariants, Pipecat duplex voice pipelines, CallSlots server-state tool handlers, PhaseCard prompt architecture, Speech-to-Text v2 (Chirp), IAM permissions, prompt optimization, interruption recovery, and production deployment.
---

# Gemini Live Voice Engine & Duplex Protocol Reference (`SKILL.md`)

> **Public Reference & Repository**:
> - **Documentation Site**: https://manishkjs.github.io/gemini_live_pipecat/
> - **Source Repository**: https://github.com/manishkjs/gemini_live_pipecat
> - **Vertex AI Live API Best Practices**: https://cloud.google.com/vertex-ai/generative-ai/docs/live-api/best-practices
> - **Gemini Live Asynchronous Function Calling Guide**: https://ai.google.dev/gemini-api/docs/live-api/tools
> - **Provisioned Throughput (PT) Live API Guide**: https://cloud.google.com/vertex-ai/generative-ai/docs/provisioned-throughput/live-api

---

## 1. Protocol, Endpoints & Framing Matrix

| Parameter | Google AI Studio (Public Production) | Vertex AI (`us-central1`, Enterprise GA) |
|---|---|---|
| **Base Host** | `generativelanguage.googleapis.com` | `us-central1-aiplatform.googleapis.com` |
| **API Version** | `v1alpha` or `v1beta` | `v1beta1` *(never use `v1` for Live WebSockets)* |
| **WebSocket Path** | `/ws/google.ai.generativelanguage.{ver}.GenerativeService.BidiGenerateContent` | `/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent` |
| **Auth Method** | `?key=$GEMINI_API_KEY` | `Authorization: Bearer $(gcloud auth print-access-token)` (ADC) |
| **Headers** | `Content-Type: application/json` | `Content-Type: application/json` |
| **Gemini 2.5 Native Audio** | `models/gemini-2.5-flash-native-audio-preview-09-2025` | `projects/<PROJECT_ID>/locations/us-central1/publishers/google/models/gemini-2.5-flash-native-audio` |
| **Gemini 3.1 Flash Live** | `models/gemini-3.1-flash-live-preview` | `projects/<PROJECT_ID>/locations/us-central1/publishers/google/models/gemini-3.1-flash-live-preview` |
| **Gemini 3.5 Flash Live** | — | `projects/<PROJECT_ID>/locations/us-central1/publishers/google/models/gemini-3.5-flash-live-preview` |
| **Gemini 3.8 Live Preview** | `models/gemini-3.8-live`<br>`models/gemini-3.8-live-extended-thinking` (`v1alpha`) | `projects/<PROJECT_ID>/locations/us-central1/publishers/google/models/gemini-3.8-live-preview`<br>`.../models/gemini-3.8-live-extended-thinking-preview` (`v1beta1`) |

### Protocol & Framing Invariants
* **Vertex AI 3.8 Naming & Version Rule**: On Vertex AI (`us-central1`), always use `api_version="v1beta1"` and include the `-preview` suffix (`gemini-3.8-live-preview` or `gemini-3.8-live-extended-thinking-preview`). Passing `api_version="v1"` or omitting `-preview` fails on Vertex AI.
* **Org Policy Allowlist (`constraints/vertexai.allowedModels`)**: When configuring GCP Organization Policies for Gemini Live models, the `:predict` suffix is mandatory (e.g. `projects/*/locations/us-central1/publishers/google/models/gemini-3.5-flash-live-preview:predict`).
* **Transparent Session Resumption & Indexing Protocol**:
  - Enable in setup: pass `session_resumption: { transparent: true }` in `BidiGenerateContentSetup`.
  - Listen for server `session_resumption_update` frames carrying `resumable: true`, `new_handle`, and `last_consumed_client_message_index`.
  - **Index `0` vs `1` Invariant**: Client message indexing **MUST start at `1`**. Index `0` is strictly reserved by the server for the initial configuration setup message.
  - **Buffer Pruning & Replay**: Maintain an in-flight send buffer; prune acknowledged messages using `last_consumed_client_message_index`. Upon disconnect (`go_away`, error `1000`/`1006`), reconnect with `new_handle`, replay unacknowledged messages, and **re-index the first message sent on the new connection starting at `1`**.
  - **Proactive `go_away` Signal**: Catch server `go_away` frames during backend pod migration to proactively reconnect with `new_handle` rather than waiting for socket failure (`1006`).
* **Session Lifecycle Rotation (10 to 15 min)**: The server terminates sessions periodically with `1008` after emitting `session_resumption_update`. Reconnect using `session_resumption_handle=new_handle`.
* **Modality Enforcement (No Hybrid Text Mode)**: `responseModalities: ["AUDIO"]` only. Sending `["AUDIO", "TEXT"]` or `["TEXT"]` on native audio endpoints triggers close code `1007` or an API error. Native audio models cannot return text-only output to feed a third-party TTS engine (such as ElevenLabs); custom third-party voices require a full STT $\rightarrow$ LLM $\rightarrow$ TTS cascade pipeline.
* **Audio Formats**: Input must be PCM 16kHz 16-bit little-endian mono (`audio/pcm;rate=16000`) sent in 20-40ms chunks. Output is PCM 24kHz 16-bit mono (`audio/pcm;rate=24000`).
* **Setup Handshake ACK**: Vertex AI yields `{"setupComplete": {"sessionId": "<UUID>"}}`. Do not transmit any audio or client content frames before `setupComplete` is received. When proxying from a browser, buffer client setup messages while fetching GCP OAuth access tokens, then flush in order once upstream connects.
* **Safe WebSocket Close Filtering**: Close codes `1005` and `1006` are reserved pseudo-codes and cannot be passed to `ws.close()`. Filter upstream close codes to `1000` before relaying to browser clients.
* **Provisioned Throughput (PT) & Session-Boundary Spillover**: GA Live API native audio models support Provisioned Throughput on Vertex AI. Automatic spillover from PT to Pay-As-You-Go (PayGo) occurs strictly **at the session boundary (between WebSocket sessions)**, never mid-session. Once a WebSocket handshake completes on PT or PayGo, that session remains locked to that billing tier for its entire duration.
* **Immutable System Instructions & Mid-Session Steering**: System instructions are fixed at session establishment (`BidiGenerateContentSetup`) and cannot be mutated mid-session. Updating `system_instruction` requires closing and restarting the WebSocket connection. To dynamically steer behavior or advance SOP phases mid-call without disconnecting, inject background context via `sendClientContent` with `turnComplete: false` or use `CustomGeminiLiveVertexLLMService.inject_directive(text, tag)`.

---

## 2. Reasoning Config, `CallSlots` Tool Handler & `PhaseCard` Architecture

### A. Reasoning Config: `thinking_budget=0` (2.5) vs. `ThinkingLevel.MINIMAL` (3.x)
* **Gemini 2.5** uses a numeric `thinking_budget` (`thinking_budget=0` cleanly disables reasoning latency).
* **Gemini 3.x (`3.1`, `3.5`, `3.8`)** uses discrete `ThinkingLevel` (`MINIMAL`, `LOW`, `MEDIUM`, `HIGH`). Passing `thinking_budget=0` to Gemini 3.8 Live degrades multi-step tool parameter copying and slot accuracy.

```python
from google.genai import types

def build_live_thinking_config(model_name: str, disable_reasoning: bool = True) -> types.ThinkingConfig:
    model_lower = (model_name or "").lower()
    if "gemini-3" in model_lower:
        level = getattr(types.ThinkingLevel, "MINIMAL", "minimal")
        return types.ThinkingConfig(
            thinking_level=level,
            include_thoughts=False,
        )
    return types.ThinkingConfig(
        thinking_budget=0 if disable_reasoning else 256,
        include_thoughts=False,
    )
```

### B. The `CallSlots` Server-State Tool Handler Pattern
On Gemini 3.1, 3.5, and 3.8 Live, `LiveConnectConfig.tools` schemas and tool responses stored in session history are **re-billed on every subsequent turn** (`cached_content_token_count = 0`).
1. **Never Duplicate Tool Lists in `system_instruction` (`+650 to 800 tok/turn`)**: Set `live_tool_names=None` so frameworks do not auto-append an `"Available Live API Tools"` directory into `system_instruction`.
2. **Never Leak Transport Headers or Constant Parameters into `FunctionDeclaration`**: Strip HTTP `method`, `url`, `headers` (`X-ADMIN-KEY`, `Authorization`), and static session fields before constructing `FunctionDeclaration` objects.
3. **Cache Lookup Dicts under Short IDs (`EC-1..EC-3`)**: Return a `~25-token` speakable summary to Gemini instead of `~800 tokens` of raw JSON, and execute deterministic follow-ups (`send_whatsapp_details`, `get_store_contact`) inside `handle_create_appointment_booking()` in Python (collapsing 3 LLM tool turns into 1 Python call).

### C. The 5-Layer `PhaseCard` Prompt Sandwich
To prevent **Language Recency Drift** (staying in Hindi when the caller switches to English after 3+ turns) and **Consonant-Cluster Audio Garbling** (`"Meal logged"` slurred as `"globbed"`), wrap dynamic phase cards with:
1. **Top `<system_header>`**: Locks Persona Identity, Indian English accent, feminine Hindi morphology (`'मैं कर रही हूँ'`, `'बताती हूँ'`), and 3-sentence turn cap.
2. **Phase Directive (`[CURRENT PHASE: ...]`)**: `"Disregard instructions in earlier phase cards."`
3. **Live Session State (`render_state_summary`)**: `"Collected details: ... Still needed: ..."`
4. **Always-Active Invariants (`always_block`)**: Concise guardrails across all phases.
5. **Post-History `<system_footer>` (Recency Anchor)**:
   - `1) RESPOND IN THE EXACT SAME LANGUAGE AS THE USER'S LATEST UTTERANCE (English -> English, Hindi -> Hindi, Hinglish -> Hinglish).`
   - `2) DO NOT RE-ASK ANY SLOT ALREADY LISTED IN Collected details.`
   - `3) PHONETIC CLARITY: Prefer clean verbs ("Meal saved", "Recorded") over consonant clusters ("logged").`

---

## 3. Frontend Audio Engineering, Constraints & Resilience

### A. Source-Level Hardware & Web Audio Constraints
Audio must be cleaned at the source (browser Web Audio API) before entering any WebSocket or WebRTC transport:
```javascript
const stream = await navigator.mediaDevices.getUserMedia({
  audio: {
    sampleRate: 16000,
    echoCancellation: true,    // Critical: prevents AI hearing itself through speakers
    noiseSuppression: true,    // Improves STT SNR in background noise
    autoGainControl: true,     // Normalizes mic levels across user devices
    channelCount: 1,           // Mono audio stream
  },
});
```

### B. `AudioWorklet` Thread Isolation & Turn-1 Mic Gating
* Offload all raw PCM capturing and resampling from the main JavaScript UI thread to a dedicated **`AudioWorklet`** to prevent audio stuttering or dropped frames during DOM rendering.
* Use separate `AudioContext` instances for input capture (`16000 Hz`) and output playback (`24000 Hz`). Schedule sequential output playback via `AudioBufferSourceNode.nextStartTime` to eliminate gaps or overlaps.
* **Turn-1 Greeting Mic Gate**: Leaving the client duplex mic open while the bot plays its initial greeting meters **201 to 222 `AUDIO` input tokens** before the user says a word. Gate inbound audio frames until `TTSStoppedFrame` / greeting playback completes.

### C. Dynamic Buffering, Backpressure & Deferred Playback Queue
* **WebSocket Backpressure Management**: Monitor `websocket.bufferedAmount`. When exceeding high-water marks, queue audio client-side to prevent TCP socket bloat.
* **Deferred Audio Playback Queue for Async Tool Speech**: When an asynchronous background tool completes and triggers proactive model speech while an earlier conversational turn's audio is still playing out on the client speaker, buffer the incoming tool-response audio in a separate **deferred playback queue**. Drain the deferred queue only after the active playback buffer finishes or is flushed by user barge-in.

---

## 4. Turn Completion Truth (`onTurnComplete`) & Audio Debounce

There are three distinct "model finished" signals in a duplex WebSocket session. Conflating them causes cut-off sentences, premature timers, and race conditions:

| Signal | Definition | Firing Timing & Hazard |
|---|---|---|
| **Server `turnComplete`** | Server finished transmitting response chunks over the socket. | Fires **too early** while several seconds of PCM audio are still buffered and playing through the user's speakers. Injecting `turnComplete: true` text here immediately cuts off audible speech. |
| **Client `isAiSpeaking = false`** | Zero active `AudioBufferSourceNode` instances playing. | Unreliable on its own because brief network jitter between audio chunks causes momentary zero-source gaps. |
| **Composite `onTurnComplete`** | Both `serverTurnDone === true` AND `activeSources.size === 0` after a 300ms drain debounce. | The **sole authoritative signal** that the model is completely finished speaking. |

```javascript
// 1. When server emits turnComplete:
if (this.currentSources.size > 0) {
  this.serverTurnDone = true; // Audio still playing out; defer callback
} else {
  this.fireTurnComplete();    // Playout already drained; fire immediately
}

// 2. When an AudioBufferSourceNode finishes playing:
source.addEventListener('ended', () => {
  this.currentSources.delete(source);
  if (this.currentSources.size === 0) {
    this.speakingDebounce = setTimeout(() => {
      this.onAiSpeakingChange(false);
    }, 300);
    if (this.serverTurnDone) {
      this.fireTurnComplete();
    }
  }
});
```

---

## 5. Prompt Optimization & System Instruction Design Playbook

1. **Pre-Connect Complete SI vs. Mid-Session Interruptions**: Any `sendClientContent` call with `turnComplete: true` during an active session acts as a new user turn and aborts ongoing model speech. Assemble the complete System Instruction before connecting, or inject background updates with `turnComplete: false`.
2. **Positive Behavioral Framing over Negative Prohibitions**:
   - *Instead of*: `"Never narrate or announce when you call a function."`
   - *Use*: `"When you invoke a tool, stop speaking immediately and remain silent. Your sole job after emitting a tool call is to listen."`
3. **Language Pinning & Acoustic Noise Guardrails**:
   ```text
   LANGUAGE PINNING: You MUST speak exclusively in English (or specified target language). Every word you output must be in English regardless of background noise or caller accent.
   ACOUSTIC FILTERING: The caller is in a noisy environment. Ignore background conversations, side chatter, and non-directed sounds.
   ```
4. **The `"Stay Silent"` Transcription Trap**: **NEVER** instruct the Gemini Live model to `"stay silent"` or `"produce no audio"` in the prompt. When the model generates zero audio output for a turn, the Gemini Live backend suppresses `inputAudioTranscription` events as well, breaking transcript loggers and state trackers.
5. **Natural Language Prefixes over Bracket Tags**: Avoid bracketed tags like `[SCRIPT]` or `[CONTEXT]` in injected text, as native audio models frequently vocalize them aloud. Use conversational prefixes (`"System update for agent: ..."`).

---

## 6. Gemini Live API Turn Management, VAD & Greeting Recovery

### A. `AutomaticActivityDetection` (Server-Side VAD)
| Parameter | Optimal Production Setting | Rationale |
|---|---|---|
| `start_of_speech_sensitivity` | `LOW` | Eliminates false triggers from background room noise or user breathing. |
| `end_of_speech_sensitivity` | `LOW` | Allows natural mid-sentence pauses without prematurely cutting the user off. |
| `silence_duration_ms` | `1200` | Provides a balanced 1.2s breathing room before concluding user turns. |
| `TurnCoverage` | `TURN_INCLUDES_ALL_INPUT` | Preserves overlapping caller speech during barge-in so the model receives full interruption context. |

### B. Opening Greeting Interruption Recovery State Machine
When a caller interrupts the model during its opening greeting on Vertex AI Live API, the model retains its partial transcript context and skips the rest of the greeting rather than restarting cleanly. Track `introduction_complete` and `introduction_restart_injected` (single-shot latch):

```python
if not introduction_complete and not introduction_restart_injected:
    if "how can I assist you today" in cumulative_output_text:
        introduction_complete = True
    else:
        await session.send_client_content(
            turns=[
                types.Content(
                    role="user",
                    parts=[types.Part(
                        text="System update for agent: The caller did not hear your introduction due to audio interruption. "
                             "Please start again with your complete introduction: '<FULL_INTRO_TEXT>'"
                    )]
                )
            ],
            turn_complete=True
        )
        introduction_restart_injected = True
```

---

## 7. Tool-Calling Architecture: `SILENT` Scheduling, Fire-and-Forget & Defensive Guards

### A. Pattern 1: `FunctionResponseScheduling.SILENT` (For State-Bearing Tools)
Vertex AI Bidi WebSockets natively support `scheduling: "SILENT"` on tool responses. Ensure your WebSocket proxy or SDK wrapper **does NOT strip the `scheduling` field** when serializing `sendToolResponse`, and append `"SILENT EXECUTION."` to tool descriptions:
```javascript
const functionResponses = responses.map(r => ({
  id: r.id,
  name: r.name,
  response: r.response,
  scheduling: "SILENT" // Prevents double speech while updating model state
}));
this.session.sendToolResponse({ functionResponses });
```

### B. Pattern 2: Fire-and-Forget (For Stateless UI-Only Tools)
For purely visual client actions (highlighting a card, scrolling a panel), execute client-side and return `{ status: "OK" }`. **Never combine fire-and-forget tools with client-side audio gating (`muteUntilTurnComplete`)**, as dropping continuation speech triggers immediate false turn completion and a timeout loop.

### C. Defensive Client Guards
1. **Two-Tier Tool Deduplication**: Implement both per-batch boolean flags and cross-batch idempotency refs (`lastProcessedKey`), returning `{ status: "OK" }` for skipped duplicate calls.
2. **`MALFORMED_FUNCTION_CALL` Recovery**: Catch JSON parse errors (~30% of extended sessions) and send a brief retry directive.
3. **Independent `if` Dispatch in Receive Loop**: In `google-genai` `AsyncSession.receive()`, **never chain `server_content` fields with `elif`**. Terminal frames frequently bundle `model_turn` and `turn_complete=True` in the same packet; `if sc.turn_complete:` must be an independent `if` statement running last.

---

## 8. Session Cycling, Silent Conductor & Unit Economics (`gemini-3.8-live` vs. `gpt-live-1`)

### A. Managed Session Cycling (15-Minute Sliding Window Grounding)
When structured catalog/page data changes or at 12-minute rotation boundaries:
1. Keep the browser `AudioContext` and `MediaStream` (`getUserMedia`) alive across WebSocket reconnects (zero mic permission prompts).
2. Inject a rolling **Session Log** (`10 context summaries + 20 transcript turns`) plus parallel-summarized (`generateContent`) grounding data into the fresh System Instruction.

### B. Silent Conductor Split Architecture (Voice UI Navigation)
To prevent native audio models from inventing or altering UI option IDs (`"science_and_nature"` instead of `"science"`):
1. **Live Voice Session**: Handles natural duplex dialogue and emits `inputAudioTranscription`.
2. **Silent Conductor (Non-Live `generateContent`)**: Maps user transcripts + valid option tree JSON to exact option IDs.
3. **Background State Sync**: Client applies UI changes and sends updated state to Live via `sendClientContent` with `turnComplete: false`.

### C. Rate Card, 90% Prefix Cache & Cost Reconciliation (`other_input_token`)
* **Always Reconcile `other_input_token`**:
  ```python
  accounted_in = text_in + audio_in + image_in + video_in + cache_in
  other_input_token = max(0, prompt_token_count - accounted_in)
  ```
  Map `other_input_token` to the `text_input` rate so gateway residuals on AI Studio (`157 to 229 tok/turn`) are never omitted. On Vertex AI `us-central1` (`v1beta1`), `gemini-3.8-live-preview` exhibits **zero (`0`) `other_input_token` residual**.
* **5-Turn Call Scorecard (`1,000` SI tok, `80s` call duration)**:
  - **`gemini-3.8-live` (with 90% input audio + text cache)**: **`$0.0253` (`₹2.18`)** (`~$0.62/hr`)
  - **`gemini-3.8-live` (uncached baseline)**: **`$0.0332` (`₹2.86`)** (`~$0.84/hr`)
  - **`gemini-3.8-live-extended-thinking` (with 90% cache)**: **`$0.0433` (`₹3.72`)** (`~$2.95/hr`)
  - **OpenAI `gpt-live-1` (`$0.05/min` voice socket) + `gpt-5.6-luna`**: **`$0.0683` (`₹5.88`)** (`~$3.09/hr`)
  - **OpenAI `gpt-live-1` (`$0.05/min` voice socket) + `gpt-6-astra`**: **`$0.1397` (`₹12.01`)** (`~$5.83/hr`)
