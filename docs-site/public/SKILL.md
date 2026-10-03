---
name: gemini-live-external
description: >-
  Customer-safe and public GitHub documentation guide for building production
  voice-to-voice (V2V) AI agents with the Gemini Live API (Gemini 2.5 Flash
  Native Audio & Gemini 3.1 Flash Live) and Pipecat. Covers all 25 architectural
  domains: bidirectional WebSocket protocol and compatibility guards, STT/TTS
  cascaded routing, IAM and local SSH tunneling, Pipecat 1.2+ Silero VAD and
  receive-loop invariants, diagnostic ring buffers, latency formulas, non-blocking
  tool calling with AntiCancel shields and CallSlots pruning, guided state
  machines, persona grammar headers, sub-millisecond BM25/Redis RAG, Frontcar/Downcar
  memory banks, Live token accounting (bidirectional audio accumulation, barge-in
  truncation, SlidingWindow 5000/3500 compression, FactStore, Turn-0 cold-start
  guards, and 7 counter-intuitive truths), Cloud Run deployment, Web Audio
  AudioWorklet isolation, onTurnComplete 300ms debounce, prompt engineering,
  greeting recovery, Silent Conductor UI navigation, framework trade-offs, and
  multi-tier Voice QA. Use ONLY when authoring external customer-facing guides,
  public GitHub documentation, or docs-site artifacts. For all internal workflows,
  use gemini-live-internal.
---

# Gemini Live API & Pipecat Production Engineering Reference (Complete 25-Section Handbook)

> **Skill Routing Rule**: Use `gemini-live-external` **only** when generating external customer-facing documentation, public GitHub repository content, or `docs-site/` files. For all internal engineering, debugging, benchmarking, and analysis, always use **`gemini-live-internal`**.

---

## 1. Protocol, Endpoints, Model Compatibility & Framing Matrix

| Parameter | Google AI Studio (Developer API) | Vertex AI (Production GA & Preview) |
|---|---|---|
| **Base Host** | `generativelanguage.googleapis.com` | `{region}-aiplatform.googleapis.com` (for example `us-central1-aiplatform.googleapis.com`) |
| **API Version** | `v1alpha` or `v1beta` | `v1beta1` *(do not use `v1` for Live Bidi endpoints)* |
| **WebSocket Path** | `/ws/google.ai.generativelanguage.{ver}.GenerativeService.BidiGenerateContent` | `/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent` |
| **Auth Method** | `?key=$GEMINI_API_KEY` | `Authorization: Bearer $(gcloud auth print-access-token)` (Application Default Credentials) |
| **Headers** | `Content-Type: application/json` | `Content-Type: application/json` |
| **Supported Models** | `models/gemini-3.1-flash-live-preview` | `projects/{PROJECT_ID}/locations/us-central1/publishers/google/models/gemini-live-2.5-flash-native-audio` |
| **Usage Metadata Fidelity** | Includes a per-turn unattributed `prompt_token_count` residual (`93 to 221 tok/turn`) and omits `thoughts_token_count` from `total_token_count` | Exact reconciliation (`prompt_token_count == Prompt_TEXT + Prompt_AUDIO`, `residual = 0`) and includes `thoughts_token_count` in `total_token_count` |

### Protocol, Framing & Model Compatibility Invariants (Gemini 2.5 vs. Gemini 3.1 Live)

When building or migrating between `gemini-live-2.5-flash-native-audio` and `gemini-3.1-flash-live-preview`, enforce these seven protocol invariants:

1. **`response_modalities` Must Be Singleton `["AUDIO"]`**:
   - Never pass `["AUDIO", "TEXT"]` in `LiveConnectConfig`. Requesting dual modalities triggers an immediate WebSocket close with `1007 Invalid Argument`. Retrieve text transcripts via `input_audio_transcription` and `output_audio_transcription`.
2. **`proactive_audio` & `enable_affective_dialog` Compatibility Guard**:
   - `gemini-live-2.5-flash-native-audio` supports `proactive_audio=True` and `enable_affective_dialog=True`.
   - Setting either flag on `gemini-3.1-flash-live-preview` triggers a `1007` WebSocket handshake failure. Gate both parameters behind `"2.5" in model_id`.
3. **Wire Format Changes (`realtime_input` vs. `client_content`)**:
   - On Gemini 3.1 Live, `send_realtime_input(media=...)` is deprecated in favor of `send_realtime_input(audio=Blob(data=pcm, mime_type="audio/pcm;rate=16000"))` and `send_realtime_input(text=...)`.
   - `send_client_content` on Gemini 3.1 Live only supports **appending** turns (`turn_complete=True` or `turn_complete=False`) and cannot replace prior conversation history mid-session.
4. **Thinking Configuration (`thinking_level` vs. `thinking_budget`)**:
   - **Gemini 2.5 Flash Native Audio**: Accepts `ThinkingConfig(thinking_budget=0, include_thoughts=False)` to disable thinking completely.
   - **Gemini 3.1 Flash Live**: Uses discrete `ThinkingLevel` (`"MINIMAL"`, `"LOW"`, `"MEDIUM"`, `"HIGH"`). Never pass `thinking_budget=0` to Gemini 3.1 Live; it degrades multi-step tool parameter copying and slot accuracy in multi-turn tool workflows. Always configure `ThinkingConfig(thinking_level="MINIMAL", include_thoughts=False)`.
5. **S2ST Interpreter Mode vs. Conversational Agent Mode**:
   - Do not combine `TranslationConfig` (continuous speech-to-speech simultaneous interpretation) with conversational system instructions or function calling. Keep unidirectional S2ST interpreter pipelines and interactive bidirectional voice agents strictly separate.
6. **Session Lifecycle Rotation (10 to 15 min)**:
   - The server rotates WebSocket connections after 10 to 15 minutes with close code `1008` after emitting a `session_resumption_update` event. Reconnect automatically using `session_resumption_handle=new_handle`.
7. **Audio Formats & Setup Handshake ACK**:
   - **Input Audio (User to Gemini)**: PCM 16kHz 16-bit little-endian mono (`audio/pcm;rate=16000`).
   - **Output Audio (Gemini to Client)**: PCM 24kHz 16-bit little-endian mono (`audio/pcm;rate=24000`).
   - **Setup Handshake ACK**: Vertex AI emits `{"setupComplete": {"sessionId": "<UUID>"}}` before streaming audio.

---

## 2. Speech-to-Text Routing & Cascaded Model Hierarchy

### A. Speech-to-Text (STT) & Reasoning Config Invariants
* **Live Transcription (`input_audio_transcription` & `output_audio_transcription`)**:
  - Enable both `input_audio_transcription=AudioTranscriptionConfig()` and `output_audio_transcription=AudioTranscriptionConfig()` inside `LiveConnectConfig` so your backend receives real-time user and assistant transcripts alongside native audio streams.
  - **AI Studio `AudioTranscriptionConfig` Invariant**: The `language_codes` field inside `AudioTranscriptionConfig` is only supported on Vertex AI (`USE_VERTEXAI=true`). Passing `language_codes` in Google AI Studio mode (`GEMINI_API_KEY`) raises:
    `ValueError: language_codes parameter is only supported in Vertex AI mode, not in Gemini Developer API mode.`
    When operating in AI Studio mode, instantiate `AudioTranscriptionConfig()` with zero arguments.
  - **Model-Generation Thinking Config Invariant (`thinking_budget=0` vs. `ThinkingLevel.MINIMAL`)**:
    ```python
    from google.genai import types

    if "2.5" in model_id:
        thinking_cfg = types.ThinkingConfig(thinking_budget=0, include_thoughts=False)
    else:
        level = getattr(types.ThinkingLevel, "MINIMAL", "minimal")
        thinking_cfg = types.ThinkingConfig(thinking_level=level, include_thoughts=False)
    ```
  - **Pipecat 1.2+ `LLMUserAggregator` Turn Invariant**: `LLMUserAggregator` ignores `InterimTranscriptionFrame`. Custom STT services must emit `TranscriptionFrame` and call `_handle_transcription(transcript, is_final=True)` to commit speech text into the LLM turn context.
  - **Pipecat 1.2+ VAD Config Invariant**: `FastAPIWebsocketParams` does not accept `vad_analyzer` (passing it raises a `TypeError`). Connect `VADProcessor` directly inside the frame pipeline.
* **`chirp_3` (Cloud Speech-to-Text v2 Multilingual Sidecar)**:
  - **Location Invariant**: Must use `location="us"` (US Multi-Region) with regional endpoint `us-speech.googleapis.com`. Calling `us-central1` fails with `400 Expected resource location to be us`.
  - **Languages**: Pass `language_codes=["en-US", "hi-IN"]` for simultaneous multilingual recognition.
  - **Streaming**: Set `enable_interim_results=True` for low-latency partial transcripts.
* **`chirp_2`**: Hosted in `location="us-central1"` (`us-central1-speech.googleapis.com`).
* **`latest_long` / `latest_short` / `telephony`**: Available in `us-central1` and `global`.

### B. Cascaded Model Tier Standards (STT -> LLM -> TTS Alternative Pipeline)
When operating a modular cascaded pipeline alongside native Speech-to-Speech:
* **Default STT**: Cloud Speech-to-Text v2 (`chirp_3` in `location="us"`) or Gemini Live STT (`response_modalities=["TEXT"]`).
* **Default LLM**: `gemini-2.5-flash-lite` or `gemini-2.5-flash` (`thinking_budget=0` for low-latency dialogue).
* **Default TTS**: Cloud Text-to-Speech `chirp_3` HD voices or Gemini TTS (`gemini-2.5-flash-preview-tts`).

---

## 3. IAM Permissions & Local Dev Tunneling

### Required Roles by Service
Grant the runtime service account the following least-privilege IAM roles:
* **Vertex AI Live & LLMs**: `roles/aiplatform.user` (`aiplatform.endpoints.predict`).
* **Speech-to-Text v2**: `roles/speech.client` (`speech.recognizers.recognize`).
* **Text-to-Speech**: `roles/texttospeech.client` (`texttospeech.synthesize`).
* **Session / Memory Storage (Optional)**: `roles/datastore.user` or `roles/storage.objectAdmin`.
* **ADC Quota Project**: Local developer credentials require `gcloud auth application-default set-quota-project <YOUR_GCP_PROJECT_ID>`.

### SSH Tunneling Invariant (Remote Linux VM -> Local Browser)
* Avoid HTTP reverse proxies that strip WebSocket `Upgrade` headers or block `wss://` audio streams.
* Forward the application port over SSH so your local browser connects to `localhost`:
  ```bash
  ssh -L 7860:localhost:7860 user@your-dev-vm.example.com
  ```
  Open `http://localhost:7860/` in Chrome, which treats `localhost` as a secure context (`window.isSecureContext === true`) for `navigator.mediaDevices.getUserMedia()` microphone capture.

---

## 4. Duplex Voice Pipeline, Idle Routing & Silero VAD Architecture

### A. Silero VAD Processor Invariant (Pipecat 1.2+)
* **`FastAPIWebsocketParams` Limitation**: In Pipecat 1.2+, WebSocket transports (`FastAPIWebsocketTransport`) do not run VAD internally. Passing `vad_analyzer` to `FastAPIWebsocketParams` is ignored or raises a `TypeError`.
* **Canonical VAD Pipeline Pattern**:
  1. Instantiate `SileroVADAnalyzer` with conversational parameters:
     ```python
     from pipecat.audio.vad.silero import SileroVADAnalyzer
     from pipecat.audio.vad.vad_analyzer import VADParams
     from pipecat.processors.audio.vad_processor import VADProcessor

     vad_analyzer = SileroVADAnalyzer(
         params=VADParams(
             confidence=0.7,      # Strict speech probability threshold (filters breaths/clicks)
             start_secs=0.2,      # 200ms speech onset confirmation
             stop_secs=0.4,       # 400ms natural conversational pause threshold
             min_volume=0.6,      # Minimum volume threshold to ignore ambient room noise
         )
     )
     vad_processor = VADProcessor(vad_analyzer=vad_analyzer)
     ```
  2. Insert `vad_processor` immediately after `start_trigger` in `pipeline_elements` to emit `VADUserStartedSpeakingFrame` and `VADUserStoppedSpeakingFrame` downstream:
     ```python
     pipeline_elements = [
         transport.input(),
         start_trigger,
         vad_processor,
         stt,
         TranscriptionBroadcaster(participant="User"),
         context_aggregator.user(),
         llm,
         TranscriptionBroadcaster(participant="Bot"),
         tts,
         context_aggregator.assistant(),
         transport.output()
     ]
     ```
  3. Pass `vad_analyzer` to `LLMUserAggregatorParams` so turn-taking boundaries synchronize with LLM context aggregation:
     ```python
     user_params = LLMUserAggregatorParams(vad_analyzer=vad_analyzer)
     context_aggregator = LLMContextAggregatorPair(context, user_params=user_params)
     ```

### B. Greeting Turn Invariant (Anti-Duplicate Audio)
* In `StartTriggerProcessor.process_frame()`, push **ONLY** `LLMRunFrame()`.
* **NEVER** push both `LLMContextFrame` and `LLMRunFrame()`. `LLMUserAggregator` emits context automatically upon receiving `LLMRunFrame()`; pushing both triggers duplicate parallel greeting speech.

### C. Pipecat Upstream Frame Routing & User Idle Management
* **Upstream Silence Blindness Hazard**: Pipecat transports push audio downstream to the LLM, and the LLM emits `TranscriptionFrame`, `UserStartedSpeakingFrame`, and `InterruptionFrame` downstream. Any `FrameProcessor` (such as `UserIdleProcessor`) placed *upstream* of the LLM never sees downstream transcription frames. A short idle timeout (such as 5s) will mistakenly treat active user speech as silence and disconnect the call.
* **The Solution**: Wire direct activity reporting from the LLM service to the idle processor:
  ```python
  # agent_live.py
  if hasattr(self, "user_idle_processor") and self.user_idle_processor:
      self.user_idle_processor.record_activity("speech_transcription")
  ```
* **Cadence Guidelines**: Use a 15s idle timer with check-in prompts at 15s, 30s, and 45s, disconnecting only after 60s of uninterrupted silence.

### D. Pipecat WebSocket Receive Loop Invariant: Never Chain `server_content` Fields with `elif`
* **The Terminal Frame Co-Occurrence Trap**: In `google-genai` `AsyncSession.receive()`, Gemini Live frequently sends a terminal WebSocket frame where **both** `message.server_content.model_turn` (the final audio chunk) **and** `message.server_content.turn_complete = True` (or `output_transcription`) are populated on the same message.
* **Anti-Pattern (`elif` Chain)**: Chaining `if sc.interrupted: ... elif sc.model_turn: ... elif sc.turn_complete: ... elif sc.output_transcription:` causes `_handle_msg_turn_complete` and `_handle_msg_output_transcription` to be skipped whenever `model_turn` is present on the final frame. Consequently, Pipecat never emits `LLMFullResponseEndFrame` for that turn, stalling `LLMAssistantResponseAggregator` and mis-bucketing per-turn usage rollups.
* **Canonical Pattern (Independent `if` Blocks)**:
  ```python
  sc = message.server_content
  if sc:
      if sc.interrupted:
          await host.broadcast_interruption()
      if sc.model_turn:
          await host._handle_msg_model_turn(message)
      if sc.input_transcription:
          await host._handle_msg_input_transcription(message)
      if sc.output_transcription:
          await host._handle_msg_output_transcription(message)
      if sc.grounding_metadata:
          await host._handle_msg_grounding_metadata(message)
      if sc.turn_complete:
          await host._handle_msg_turn_complete(message)
  if message.tool_call:
      await host._handle_msg_tool_call(message)
  ```

### E. Pipecat `ContextWindowCompressionConfig` & `SlidingWindow` Wiring Invariant
* **Silent No-Op Anti-Pattern**: Passing a plain dictionary (`{"enabled": True, "trigger_tokens": ...}`) or storing `target_tokens` inside `kwargs["extra"]` on `GeminiLiveInputParams` is silently ignored by Pipecat, leaving long calls with unbounded audio and tool-result history.
* **Canonical Pattern**: Always construct a typed `types.ContextWindowCompressionConfig` with `trigger_tokens=5000` (the Vertex AI minimum trigger floor) and `types.SlidingWindow(target_tokens=3500)`:
  ```python
  from google.genai import types

  if compression_enabled and trigger_tokens:
      target_tokens = target_tokens or 3500
      kwargs["context_window_compression"] = types.ContextWindowCompressionConfig(
          trigger_tokens=trigger_tokens,
          sliding_window=types.SlidingWindow(target_tokens=target_tokens),
      )
  ```

---

## 5. Live Observability & Diagnostic Buffer

* **Zero-Disk In-Memory Ring Buffer**: Intercept Loguru and Python standard logging into a bounded `deque(maxlen=1500)` in `diagnostic_buffer.py`, exposed via `GET /api/logs` and `POST /api/logs/clear` (polled every 1.5s by the debug UI).
* **Token Fragment Filtering**: Never log single-word streaming fragments:
  - **User**: Flush complete sentences upon end-of-sentence punctuation (`.`, `।`, `?`, `!`) or VAD stop.
  - **Bot**: Accumulate streaming output chunks in `_bot_turn_text_buffer`; log the complete turn upon `_handle_msg_turn_complete` or `_handle_msg_interrupted`.

---

## 6. Latency Measurement & Telemetry Invariants

### A. First-Packet Live TTFB (Gemini Live)
Calculate Time-to-First-Byte (TTFB) on whichever arrives first from the model turn (text transcription or PCM audio chunk):
```python
if getattr(self, "_current_turn_ttft", None) is None and getattr(self, "_my_ttfb_start", None) is not None:
    self._current_turn_ttft = time.time() - self._my_ttfb_start
    self._my_ttfb_start = None
```

### B. Speech-to-Text Latency & Turnaround Formulas

1. **Cloud Speech v2 (`CustomGoogleSTTService`)**:
   * **The 2ms Audio Stream Trap**: Continuous raw audio frames flow every 20ms during silence. Calculating `now - last_audio_time` yields bogus ~2ms readings.
   * **Exact Speech Offset Formula**:
     ```text
     STT_Latency = t_now - (T_stream_start + result_end_offset.total_seconds())
     ```
   * **`datetime.timedelta` SDK Invariant**: In the Google Cloud Speech v2 Python SDK, `result_end_offset` is a native `datetime.timedelta` object (`dur.total_seconds()`), not a protobuf duration with `.nanos`.

2. **Streaming Live STT (`CustomGeminiTranscribeLiveService`)**:
   * **Real-Time Turnaround Formula**:
     - If user has finished speaking: `STT_Latency = t_now - t_user_stopped_speaking` (typically 80ms to 350ms).
     - If speech is ongoing in real time: `STT_Latency = t_now - t_last_audio_sent` (typically 50ms to 150ms).
   * **The Utterance Duration Anti-Pattern**: Never calculate `t_now - t_user_started_speaking` as STT latency. That measures the total duration of the spoken sentence (such as 7.8s to 9.1s) rather than speech processing turnaround delay.
   * **Turn State Reset Invariant**: Immediately upon emitting `TranscriptionFrame` and calling `_handle_transcription(is_final=True)`, reset `self._user_started_speaking_time = None` and `self._user_stopped_speaking_time = None`.

### C. Strict Metric Binding, Turn Buffering & Token Event Normalization
* **Label Binding**: `isCascade = this.connectedBotType === "tts-llm-stt"`.
  - **Gemini Live**: Displays `Live TTFB: {ms}ms`.
  - **STT-LLM-TTS**: Displays `STT: {ms}ms | LLM TTFB: {ms}ms | TTS: {ms}ms`.
* **Async Turn Buffering (`pendingLLMLatency`)**: Store early-arriving LLM latencies in a buffer and bind them when creating the bot DOM bubble so they never attach to the previous turn's bubble.
* **Cross-Turn Metric Flushing & Isolation**:
  - `resetMetrics()` must purge all latency buffers on every connection start.
  - Clear `this.lastTurnSTTLatency = null` immediately after rendering on a bubble so previous turn metrics never bleed into subsequent turns.
  - Cap TTFB turnaround timers at `< 15.0s` to prevent idle timeout skew.
* **Token Accumulation & Modality Enum Normalization**:
  - Accumulate token and cost metrics strictly once per turn on the discrete `usage` event (`turnComplete`), never inside streaming audio chunk callbacks (`onMessage`) which fire 15 to 30 times per turn.
  - Normalize Python GenAI SDK `MediaModality` enums (`str(m.modality).split(".")[-1].upper()`) before JSON serialization so keys like `"mediamodality.text"` never break modality rate-card lookups in TypeScript.

---

## 7. Tool-Calling Architecture, `AntiCancel` Shield & `CallSlots` Pattern

### A. Session Resumption Handles vs. Stable Session IDs
* **Ephemeral Handles**: The Live API mints a new `session_resumption_handle` after every turn.
* **Stable Session ID**: All turn handles map to a single immutable **Session ID** (`setupComplete.sessionId`). Index logs, CRM records, and observability traces by the stable Session ID.

### B. Eliminating Redundant Tool-Call Loops
1. **Application-Layer State Machines**: Move deterministic state routing into the Python or client application layer.
2. **Lean System Instructions**: Keep persona, voice style, tone, and safety in the root System Instruction; strip out heavy multi-branch decision trees.
3. **Dynamic Tool Allow-Lists**: Expose only the minimal subset of tools valid for the active conversation state.

### C. Non-Blocking Function Calling (`behavior: "NON_BLOCKING"`)
* **Setup Declaration**: Declare `"behavior": "NON_BLOCKING"` in `function_declarations` so the model can speak a natural filler phrase (*"Let me check your account details..."*) while your backend executes the API call.
* **Avoid Prompt Hijacking**: Never intercept tool calls to dispatch `send_client_content("speak exactly...")` with `turn_complete=True`.
* **Correct Pattern**:
  1. Guide the persona in the System Instruction to acknowledge the lookup naturally before emitting the tool call.
  2. Execute the tool asynchronously in the background via `asyncio.create_task(...)`.
  3. Send `tool_response` (`FunctionResponse`) with `scheduling="WHEN_IDLE"` over the live WebSocket upon completion so the tool result is voiced as soon as the current filler audio finishes without clipping the model's sentence.

### D. Tool Response Scheduling Protocol (`WHEN_IDLE` vs. `SILENT` vs. `INTERRUPT`)
* **`WHEN_IDLE` (Default for User-Facing Lookups)**: Queues the tool result until the model finishes speaking its current filler sentence, then immediately generates the spoken answer.
* **`SILENT` (For Background State Sync Only)**: Absorbs the tool payload into session context without generating new speech.
  - **Caution on Gemini 3.1 Flash Live**: If the model speaks a filler sentence (*"One moment while I check..."*), finishes its turn (`turnComplete`), and then receives a `FunctionResponse` with `scheduling="SILENT"`, the model will remain silent until the user speaks again. Always use `WHEN_IDLE` whenever the caller expects an immediate spoken answer after a filler phrase.
```python
func_response = types.FunctionResponse(
    id=function_id,
    name=function_name,
    response=result_payload,
    scheduling=types.FunctionResponseScheduling.WHEN_IDLE,
)
```

### E. Pipecat `AntiCancel` Tool Shield, 8.0s Watchdog & Terminal `speaking_Hold`
When a user coughs or says *"okay"* while an asynchronous tool call (such as an order lookup or appointment booking) is in flight, Pipecat's default interruption handler cancels the running `asyncio` task, dropping the API write mid-flight. Protect tool execution with three guards:
1. **Override `_cancel_function_call(self, function_name: str | None)`**: Log `[AntiCancel] Refusing to cancel in-flight function call` and return cleanly without cancelling the background `asyncio.Task`.
2. **Frame Interception with 8.0s Watchdog (`process_frame`)**: While `_tools_in_flight()` is active (`_active_tools_in_flight > 0` within `TOOL_LOCK_MAX_HOLD_SECS = 8.0s`), suppress `InterruptionFrame`, `UserStartedSpeakingFrame`, and `FunctionCallCancelFrame`. **Never suppress `CancelFrame`** (the pipeline disconnect/shutdown signal, or containers will leak on disconnect).
3. **Client-Side `speaking_Hold` During Terminal Actions (`transfer_call` / `end_call`)**: When the model invokes a terminal tool while speaking a farewell (*"Please hold while I connect you to a specialist..."*), do not tear down the audio stream while farewell speech is still buffered in the browser. Enter a client-side `speaking_Hold` state: pause mic forwarding (`send_realtime_input`), wait for the client to emit `playback_drained` once the `AudioWorklet` ring buffer empties, and only then execute the handoff or hangup.

### F. The `CallSlots` Server-State Tool Handler Pattern (Eliminating the 3-Part Tool Token Tax)
On Gemini 3.1 Flash Live, `LiveConnectConfig.tools` schemas and tool-call responses in session history are re-billed on **every subsequent turn**. To prevent a multi-tool workflow from adding `2,000+` tokens/turn and `4,800+` tokens of tool-response history bloat:

1. **Never Auto-Inject Tool Lists (`live_tool_names`) into `system_instruction`**:
   - Tool declarations belong exclusively in `LiveConnectConfig.tools`. Auto-generating an `"Available Live API Tools"` directory into `system_instruction` duplicates billing by **`+650 to 800 tokens/turn`**. Set `live_tool_names=None`.
2. **Strictly Whitelist `FunctionDeclaration` Fields (Never Leak HTTP Metadata or Constants)**:
   - When converting REST tool configs into `google.genai.types.FunctionDeclaration` objects, strip `method`, `url`, `headers`, and static server fields.
   - Move all static or session-scoped parameters into the server Python handler rather than asking the model to generate constants.
3. **Cache Lookup Objects by Monotonic Short IDs (`EC-1`, `EC-2`) & Return Compact `~25-Token` Summaries**:
   - Returning a raw `~800-token` JSON array from a lookup tool (such as a branch or clinic finder) leaves those 800 tokens in the Live conversation context for every remaining turn (`800 tok * 6 remaining turns = ~4,800 tok/call`).
   - Instead, cache the full dictionary objects in server session state (`CallSlots.centres`) under monotonic query-scoped short IDs (`EC-1..EC-3` for pincode 1; `EC-4..EC-6` if the caller asks about a second pincode) and return a **`~25-token` speakable string** (`"EC-1: Koramangala (2.1 km) | EC-2: Indiranagar (4.0 km)"`).
   - Always guard lookups with `store = self.centres.get(centre_id)` so a hallucinated ID (`EC-9`) returns a speakable recovery prompt rather than raising an unhandled `KeyError`.
4. **Collapse Deterministic Post-Action Tool Chains into the Python Handler**:
   - If booking an appointment is always followed by sending a messaging confirmation (`232 tok/turn` schema) and returning branch contact details (`183 tok/turn` schema), execute both follow-up API calls **directly inside `handle_create_appointment_booking()` in Python**. This removes 2 tool schemas from `LiveConnectConfig.tools` and collapses **3 sequential LLM tool turns into 1 Python round-trip**.

---

## 8. Guided State Machine & Phase Engine Architecture

### A. Core Architectural Pattern
Structure complex enterprise calls into discrete, predictable **Intent Phases**:
1. **Definite Intent Principle**: Define `definite_intent` (business goal), `conversational_boundaries` (forbidden actions), and `allowed_tools` for each phase.
2. **Phase-Specific Tool Whitelisting**: Restrict execution of action or calculation tools to designated phases. Phases for discovery, consent, and education keep `allowed_tools: []`.
3. **Zero Search Tools for Core Domain Directives**: Ground core brand credentials, regulatory disclosures, and safety rules directly in conversational prompt cards with zero tool calls.

```python
@dataclass
class PhaseDefinition:
    phase_id: int
    title: str
    definite_intent: str               # Explicit purpose of this phase
    allowed_tools: List[str]           # Whitelisted tools for this state
    conversational_directive: str      # Spoken behavioral instructions and guidelines
    fast_path_keywords: List[str]      # 0ms regex triggers for immediate state switching
```

### B. Dual-Tier Dynamic Phase Router
```text
+---------------------------------------------------+
|       User Utterance (Live Transcription)         |
+---------------------------------------------------+
                          |
                          v
+---------------------------------------------------+
|         Tier 1: Fast-Path Regex (0ms)             |
+---------------------------------------------------+
          |                               |
  [Match Found]                     [No Regex Match]
          |                               |
          |                               v
          |             +-----------------------------------+
          |             | Tier 2: Async Semantic Classifier |
          |             |     (Flash-Lite, <120ms)          |
          |             +-----------------------------------+
          |                               |
          |                     [Confidence >= 0.70]
          |                               |
          +---------------+---------------+
                          |
                          v
+---------------------------------------------------+
|       await transition_to(target_phase)           |
|      Update Active Phase State & Metrics          |
+---------------------------------------------------+
```

1. **Tier 1 (Instant 0ms Fast-Path)**: Regex evaluation on transcribed user sentences for high-confidence explicit intents (`$0` cost, `0ms` latency).
2. **Tier 2 (Async Background LLM Classifier)**: Non-blocking semantic classification using `gemini-2.5-flash-lite` when Tier 1 finds no match.
3. **Hysteresis & Confidence Gate**: Only transition states if `confidence >= 0.70` and the target phase transition is valid.

### C. JIT Prompt Yielding (`clientContent`) & Mid-Speech Collision Invariant
* **Critical Protocol Truth (`BidiGenerateContentClientContent` Interruption Hazard)**: Sending `BidiGenerateContentClientContent` during active model generation **unconditionally interrupts** the model's in-flight speech (`turn_complete=False` only avoids starting a new response turn; it does *not* prevent cutting off active audio generation).
* **Mid-Speech Guard & Queue Flushing**: Always queue phase transitions that occur while `self._is_bot_speaking` is true, and flush them inside `on_bot_stopped_speaking` with `turn_complete=False`:
```python
async def transition_to(self, target_phase: int, trigger_reason: str):
    async with self._lock:
        if self._is_bot_speaking:
            self._pending_phase = target_phase
            self._pending_reason = trigger_reason
        else:
            await self._yield_prompt_to_gemini(target_phase, trigger_reason)

async def on_bot_stopped_speaking(self):
    self._is_bot_speaking = False
    if self._pending_phase is not None:
        phase, reason = self._pending_phase, self._pending_reason
        self._pending_phase, self._pending_reason = None, None
        await self._yield_prompt_to_gemini(phase, reason)
```

### D. Direct Transcription Hook & Dual-Stream UI Invariant
Override `_push_user_transcription` inside the LLM service to stream User bubbles to the client UI, record observability traces, and trigger the state machine:
```python
async def _push_user_transcription(self, text: str, result=None):
    await super()._push_user_transcription(text, result)
    if text and text.strip():
        clean_text = text.strip()
        await self.push_frame(OutputTransportMessageFrame(message={
            "label": "rtvi-ai", "type": "server-message",
            "data": {"type": "transcription", "participant": "User", "text": clean_text}
        }))
        GLOBAL_LANGSMITH_TRACER.record_user_turn(clean_text)
        if hasattr(self, "phase_tracker") and self.phase_tracker:
            await self.phase_tracker.handle_user_transcript(clean_text)
```

### E. Deterministic Transition Gates & Consistency Ledger
* **Stage Skip Guard**: Block anomalous forward jumps greater than `N` stages (such as max `+3`) in a single turn.
* **Prerequisite Fact Gating**: Gated phases cannot be entered until required facts are recorded in the session `FactStore`.
* **Numeric Consistency Ledger**: Record all bot-quoted numbers and validate bounds before quoting to guarantee 100% cross-turn consistency.

---

## 9. State Machine Disambiguation & Anti-Looping Discipline

### A. Disambiguating Turn 1 Greetings vs. Mid-Call Farewells
* **The Greeting Loop Anti-Pattern**: If callback requests or wrap-up phrases route back to Phase 1, the bot re-introduces itself from the start of the script.
* **Strict Funnel Invariant**:
  1. **Phase 1 (Opening & Availability)**: Restricted strictly to the Turn 1 opening. Never route back to Phase 1 mid-call.
  2. **Phase 9 (Commitment & Close)**: Any mid-call concluding signal, farewell, or callback request (`"bye"`, `"alvida"`, `"thank you bye"`, `"chalo bye"`, `"baad mein baat karte hain"`) **must route to Phase 9**.
* **Tier-1 Fast-Path Regex for Farewells (0ms, $0)**:
  ```python
  if self.current_phase > 1 and re.search(r" (bye|boy|by|alvida|thank you|thanks|chalo bye|ok bye|theek hai bye|wrap up|chalta hu|chalti hu|rakhta hu|rakhti hu|baad mein baat|later) ", lower):
      await self.transition_to(9, trigger_reason="Tier-1 Regex: User wrapping up call / farewell")
  ```

### B. Dynamic Commitment Validation (No Rigid Scripts)
* In Phase 9, dynamically remind the customer of the specific option explored in the current session (such as the 12-month return plan, minimum deposit, or appointment slot) and confirm whether they are ready to proceed or prefer a scheduled follow-up. Close cleanly with zero loops.

---

## 10. Speaker Persona & Grammatical Agreement across Prompt Cards

### A. The JIT Prompt Card Persona Drift Trap
When Prompt Cards are injected Just-In-Time via `send_client_content(turn_complete=False)`, the prompt card becomes the most recent instruction in context. If speaker identity and grammatical gender constraints are omitted from the card, multilingual models frequently drift into default masculine Hindi verb forms (*"बता रहा हूँ"*, *"देता हूँ"*).

### B. Mandatory Prompt Card Header Standard
Every dynamically yielded Prompt Card must include the speaker identity and grammatical agreement rules using natural-language prefixes (never square brackets, which native audio models can vocalize aloud):
```python
directive_text = (
    f"System update for agent - Active Phase {target_phase} ({card['title']}):\n"
    f"Speaker Persona: Pragya (Female Senior Wealth Manager at Cymbal Lending).\n"
    f"Mandatory Female Grammar: Always speak in 100% consistent feminine Hindi grammar for yourself.\n"
    f"• REQUIRED FEMININE VERBS: 'मैं बता रही हूँ', 'करती हूँ', 'देती हूँ', 'मदद करूँगी', 'समझ गई'\n"
    f"• FORBIDDEN MASCULINE VERBS: Never use masculine verb forms ('रहा हूँ', 'करता हूँ', 'देता हूँ', 'करूँगा').\n\n"
    f"{card['directive']}\n\n"
    f"Context: {trigger_reason}\n"
    f"Rule: Always use Devanagari for Hindi words and Latin script for English financial terms."
)
```

---

## 11. Sub-Millisecond Near-Process Dual-Layer RAG Caching

### A. The Remote Vector Search Dead Air Hazard
* **The Anti-Pattern**: Calling remote vector database search APIs inside an active voice turn takes **3,200ms to 3,800ms**, introducing over 3 seconds of dead air.
* **Dual-Layer Near-Process Hierarchy**:
  1. **L1 In-Memory Process RAM (`<0.05ms`)**: Compile domain Q&A pairs into an Okapi BM25 inverted index in process memory on startup for sub-millisecond retrieval.
  2. **L2 Cloud Memorystore Valkey / Redis (`~1.0ms`)**: Use a regional GCP Memorystore instance in `us-central1` for cross-instance shared state and normalized query hash keys (`cymbal:sheet_rag:*`).
  3. **Graceful Fallback**: If L2 Redis is unreachable, fall back immediately to the local L1 RAM BM25 index without blocking the live voice stream.
* **Proactive vs. Reactive RAG Injection**:
  - **Proactive Background RAG (Between Turns)**: Inject retrieved context silently via `LiveClientContent(turns=[Content(role="user", parts=[Part.from_text("System context update: ...")])], turn_complete=False)`. Because `turn_complete=False`, the model absorbs the context without generating unsolicited speech.
  - **Reactive On-Demand RAG (User Asks a Specific Question)**: Expose a non-blocking `search_knowledge_base` tool returning `FunctionResponse(..., scheduling="WHEN_IDLE")`.

---

## 12. Dual-Brain Frontcar / Downcar Architecture & Enterprise Memory Bank

### A. Frontcar vs. Downcar Decoupling
* **Frontcar (Fast Path - Synchronous Duplex Voice)**: Ultra-lean real-time pipeline (`gemini-3.1-flash-live-preview` or `gemini-live-2.5-flash-native-audio`) focused on conversational persona, audio pacing, active phase intent, and non-blocking tool execution. At session connect (`t = 0ms`), inject the user's compact Markdown profile (`< 500` tokens) into `system_instruction`. Zero heavy database writes occur on the audio thread.
* **Downcar (Slow Path - Asynchronous Post-Session Worker)**: Triggered on `on_client_disconnected`. Uses `gemini-2.5-flash-lite` (`response_mime_type="application/json"`) to parse session transcripts, extract canonical user facts and action items, generate episodic summaries, and persist them to your cloud memory store.

### B. Dual-Threshold Vector Memory Standard
* **Deduplication Gate (`SIMILARITY_THRESHOLD = 0.83`)**: Enforce `cosine_similarity >= 0.83` (plus category match and MD5 `content_hash`) when updating or inserting memory facts so distinct concepts never overwrite each other.
* **Retrieval Gate (`RETRIEVAL_THRESHOLD = 0.40`)**: For semantic recall (`retrieve_memory`), use `threshold = 0.40`. Conversational questions embed at `0.65 to 0.78` cosine similarity against declarative facts; using `0.83` for retrieval causes false-negative recall misses.
* **Stateless Container Rule**: Never store user facts in local container files (`/tmp` or local SQLite) on Cloud Run. Persist to a managed cloud store (`Firestore`, `Cloud SQL`, or `Vertex AI Agent Engine Memory Bank`).

### C. Spoken Lexical User Identity Normalization
Standardize spoken introductions by stripping conversational framing (*"My name is..."*), removing boundary-aware honorifics (`Dr.`, `Mr.`, `Smt.`), and sanitizing symbols while preserving alphanumeric IDs (`user_<name>`).

---

## 13. Token Modality, Cost Accounting & Context Compression Architecture

### A. Published Rate Card (Vertex AI & Google AI Studio)
| Token Category | Gemini 2.5 Flash Native Audio (per 1M Tokens) | Gemini 3.1 Flash Live Preview (per 1M Tokens) | Modality & Billing Mechanics |
|---|---:|---:|---|
| **Prompt TEXT** | `$0.50` | `$0.75` | System instructions, tool declarations (on 3.1 Live), text turns, and tool responses |
| **Prompt AUDIO** | `$3.00` | `$3.00` | `~25 tokens/sec` (`~1,500 tok/min`; budget `~27.8 tok/sec` / `~1,668 tok/min` / `~$0.0050/min` as a conservative planning figure; includes both user speech **and** carried played model audio) |
| **Candidate TEXT / Thoughts** | `$2.00` | `$4.50` | Output text transcripts and thinking tokens (`thoughts_token_count`) |
| **Candidate AUDIO** | `$12.00` | `$12.00` | `~25 tokens/sec` of generated model speech (`~1,500 tokens/min` = `$0.018/min`) |

### B. Dual-Engine Optimization Architecture: 5,000-Token Trigger Floor vs. Lean SI & JIT Prompt Cards
* **The 5,000-Token Trigger Invariant**: Vertex AI Live enforces a minimum threshold of **5,000 tokens** (`trigger_tokens=5000`, `target_tokens=3500`) for sliding-window context compression.
* **The Lean SI Mismatch**:
  - In an optimized voice pipeline, the root System Instruction (SI) is intentionally compact (`~225 to 500` tokens) containing only core persona, tone, grammatical rules, and safety boundaries.
  - Because the Live protocol is append-only, every injected prompt card and every turn of user and bot speech accumulates in session history until the `5,000`-token trigger is reached (typically around Turn 7 to 12).
* **The Dual-Engine Solution**:
  1. **Early Turns (Lean Static SI + Dynamic JIT Prompt Cards)**:
     - Keep the root SI under `500` tokens (`120` tokens for the opening card, `~500` tokens average across phases).
     - Yield Phase Directives and compliance scripts Just-In-Time via `send_client_content(turn_complete=False)` only when entering a new conversation phase.
     - Never stuff static multi-page decision trees or unused tool schemas into the root SI.
  2. **Long Calls (Sliding-Window Compression `5000 / 3500` + `FactStore`)**:
     - Once total context reaches `5,000` tokens, `SlidingWindow(target_tokens=3500)` automatically evicts the oldest dialogue turns (including their accumulated user and model audio tokens) while preserving the initial `system_instruction`.
     - `FactStore` (`< 60` tokens) restores structured continuity across compaction boundaries.

### C. Bidirectional Audio Accumulation & Sliding-Window Eviction Dynamics
* **Why `Prompt AUDIO` Grows Rapidly (`UserInputAudio + PlayedModelOutputAudio`)**:
  - Unlike text-only APIs where prior assistant replies are compact text tokens, a native Speech-to-Speech session retains **both** the user's input speech audio **and** the model's played output audio in the active conversation history (`Prompt AUDIO`, billed at `$3.00 / 1M` on every subsequent turn), alongside their text transcripts in `Prompt TEXT`:
    ```text
    Prompt_AUDIO(turn k) = sum_{i=1..k} UserInputAudio(i) + sum_{i=1..k-1} PlayedModelOutputAudio(i)
    ```
  - **Production Telemetry Proof (Vertex AI `gemini-live-2.5-flash-native-audio`, 3 Tools Declared)**:
    - **Turn 1**: `Prompt = 279` (`236 TEXT` = `211` SI + `25` user ASR text, `43 AUDIO` user greeting), `Response = 223` (`181 AUDIO` played bot speech, `42 TEXT` bot transcript).
    - **Turn 2**: `Prompt = 556` (`AUDIO = 271` = `43` Turn 1 user audio + **`181` Turn 1 played bot audio** + `47` Turn 2 user audio; `TEXT = 285` = `236` Turn 1 text + **`42` Turn 1 bot text** + `7` Turn 2 user ASR text), `Response = 212` (`170 AUDIO`, `42 TEXT`).
* **Barge-In Truncation Reduces Subsequent `Prompt AUDIO`**:
  - When a caller interrupts the model mid-sentence (barge-in), the server truncates the unplayed tail of the model's audio turn from session history based on playback duration. On the next turn, only the model audio tokens actually played before the interruption are carried forward into `Prompt AUDIO`.
  - **Automated Benchmark Trap**: Because the server finishes streaming audio packets over the WebSocket faster than real-time playback duration (`generated_audio_duration`), an automated test script that sends `client_content(turn_complete=True)` immediately upon receiving `turnComplete` without waiting for real-time audio playout triggers server-side barge-in truncation, slicing the model's audio out of history and under-measuring real production `Prompt AUDIO` growth.
* **Sliding-Window Audio Eviction**:
  - When `ContextWindowCompressionConfig(trigger_tokens=5000, sliding_window=SlidingWindow(target_tokens=3500))` fires, the server evicts the oldest conversation turns (for example contracting `Prompt AUDIO` from `2,689 -> 1,794` and `2,015 -> 799` tokens) while keeping the root `system_instruction` intact.
  - Because audio input costs `$3.00 / 1M` vs. `$0.50 to $0.75 / 1M` for text input (`4x to 6x` rate ratio), evicting `1,216` audio tokens saves the cost equivalent of `4,864 to 7,296` text tokens.

### D. `FactStore` Restoration Protocol & 10-Turn Cap Invariant
* **The Context Amnesia Footgun**: When sliding-window compaction evicts early dialogue turns, the model can forget facts stated in Turns 1 to 3 (such as customer name, pin code, or loan amount) unless those facts are preserved cleanly.
* **The `FactStore` Invariant**:
  - Detect compaction via `current_prompt < (last_prompt - 150)`.
  - Maintain a compact `< 60-token` JSON `FactStore` of extracted entities plus a capped window of recent transcript lines, and inject them via `send_client_content(turns=[Content(...)], turn_complete=False)`.
* **The 10-Turn Cap Rule**:
  - Never re-inject the entire session transcript on a 30-turn call (which would inject `1,250+` text tokens and defeat compression).
  - **Strictly cap injected dialogue to the last 10 turns** (`history[-10:]`):
    ```python
    capped_history = history[-10:] if len(history) > 10 else history
    injected_lines = [f"{turn['role']}: {turn['text']}" for turn in capped_history]
    ```
* **Prompt Restoration Template (Zero Bracket Tags)**:
  ```text
  System update for agent - Conversation Transcript Log (Last 10 Turns):
  <injected_turns>

  Instructions for agent:
  - Continue the conversation with the caller from the latest turn.
  - Retain all customer details, numbers, preferences, and agreements stated above.
  - Do not repeat greetings, do not re-introduce yourself, and do not verbally acknowledge this transcript update.
  ```

### E. Total Transcription History Backend Observability Invariant
* **Zero Silent Drops**: Log every dialogue turn in real time and in session summaries within the backend logger:
  1. **Per-Turn Logs**: Log `[Transcript User (Turn N)]: <text>` and `[Transcript Assistant (Turn N)]: <text>`.
  2. **At Compaction Injection**: Log the complete session transcription history alongside the 10-turn restoration payload.
  3. **At Client Disconnect**: In `on_client_disconnected`, emit the numbered session transcript (`1. User: ...`, `2. Assistant: ...`).

### F. Audio vs. Text Token Dynamics & Compression Alert Guarding
* **Composite Prompt Tokens**: On Vertex AI, `prompt_token_count` equals `Prompt_TEXT + Prompt_AUDIO` (`residual = 0`). On Google AI Studio (`gemini-3.1-flash-live-preview`), `prompt_token_count` exceeds `Prompt_TEXT + Prompt_AUDIO` by `93 to 221` tokens per turn (see §13.H). Never compute billed volume by summing `prompt_tokens_details` alone; always read `prompt_token_count` and bill any positive difference `max(0, prompt_token_count - sum(details))` at the text input rate.
* **Guard Observability Alerts**: Configure monitoring dashboards so context-compression alerts only fire when `prompt_token_count` crosses `>= 4,500` tokens followed by a sustained drop (`> 1,000` tokens).

### G. Tool Declaration & Tool Response Token Accounting (`Prompt TEXT`)
* **Gemini 2.5 Flash Native Audio (`0` Tool Schema Tokens in `prompt_token_count`)**: On `gemini-live-2.5-flash-native-audio`, the turn-by-turn `prompt_token_count` counts `system_instruction` text tokens (`225` tok) and omits declared `tools` (`function_declarations`) schemas (`0` billed tool schema tokens per turn), billing tool payloads only when tools are invoked and their `FunctionResponse` payloads enter conversation history.
* **Gemini 3.x Live Architecture (Full Developer-Turn Tool Schema Billing + History Carry)**: On 3.x Live pipelines where `function_declarations` are serialized into the developer system turn (as well as every returned `FunctionResponse` in session history), declared tool schemas (`~70 to 250` tokens per concise tool, or `2,300 to 3,500+` tokens/turn for 16 verbose tools) and tool outputs are re-billed on **every subsequent turn**.
* **Pruning Invariant**: Register only the 1 to 3 essential real-time tools required for the active workflow and apply the `CallSlots` pattern (§7.F) so neither tool schemas nor `800`-token JSON lookup responses bloat your `5,000`-token context window.

### H. Cross-Endpoint `usage_metadata` Reconciliation Invariant (Vertex AI vs. AI Studio)

Paired multi-turn sessions on identical Pipecat clients and prompts establish exact reconciliation behaviors across endpoints:

1. **Google AI Studio (`gemini-3.1-flash-live-preview`) Unattributed `Prompt` Residual**:
   ```text
   T0 (greeting): Prompt: 795  (TEXT 501, AUDIO 201)  -> details sum 702   residual  93
   T1           : Prompt: 1091 (TEXT 538, AUDIO 418)  -> details sum 956   residual 135
   T2           : Prompt: 1343 (TEXT 578, AUDIO 594)  -> details sum 1172  residual 171
   T3           : Prompt: 1692 (TEXT 633, AUDIO 838)  -> details sum 1471  residual 221
                                                         TOTAL RESIDUAL    620 = 12.6%
   ```
   - On AI Studio, `response_tokens_details` reports `AUDIO` only (`0 TEXT` out), while `prompt_token_count` includes internal turn formatting and the carried output text transcript that are not broken out in `prompt_tokens_details`.
   - AI Studio also sets `total_token_count = prompt_token_count + response_token_count`, omitting `thoughts_token_count` from `total_token_count` even when `thoughts_token_count` is populated.
2. **Vertex AI (`gemini-live-2.5-flash-native-audio`) Zero Residual**:
   - On Vertex AI, `prompt_token_count == Prompt_TEXT + Prompt_AUDIO` (`residual = 0` on every turn), `response_tokens_details` explicitly breaks out both `AUDIO` and `TEXT`, and `total_token_count == prompt_token_count + response_token_count + thoughts_token_count`.
3. **Cost-Calculator Invariant**:
   - Any Live pricing module must compute `residual_input = max(0, prompt_token_count - sum(prompt_tokens_details))` and include `thoughts_token_count` explicitly when computing total turn cost.

### I. Pre-Speech Greeting Audio Metering on AI Studio (`gemini-3.1-flash-live-preview`)

On Google AI Studio, `gemini-3.1-flash-live-preview` bills **`~196 to 201` audio prompt tokens on Turn 1 before the user has spoken** if the client microphone stream is already open during the bot's greeting playback:

```text
05:58:48.8  WebSocket connected (mic streaming silence)
05:58:49.8  Bot started speaking (greeting)
05:58:56.4  usage_metadata: Prompt: 795 (TEXT: 501, AUDIO: 201)   # 7.6s of open mic
```

Because the Live API re-bills active context on every subsequent turn, those `201` Turn-1 silence tokens compound to **`804+` extra audio tokens over 4 turns**.

* **Mitigation**: Gate client microphone forwarding until `TTSStoppedFrame` (or client greeting playback drain) fires on Turn 1. When Turn 1 is triggered cleanly without open-mic audio before the greeting completes, Turn 1 `Prompt AUDIO` is `0`.

### J. Zero Implicit Context Caching Discount (`cached_content_token_count = 0`)

Across all production Gemini Live endpoints (`gemini-live-2.5-flash-native-audio` on Vertex AI and `gemini-3.1-flash-live-preview` on Google AI Studio), `cached_content_token_count` is **`0` (`None`) on every turn**. System instructions, declared tool schemas (on 3.1 Live), and carried conversation history in the active window are billed at standard input rates on every turn:

| Model | Turn 1 `Prompt TEXT` for an Identical 225-Token System Instruction (0 Tools) |
|---|---|
| `gemini-live-2.5-flash-native-audio` | **225 tokens** (the system instruction with zero extra scaffolding) |
| `gemini-3.1-flash-live-preview` | **501 tokens** (225 instruction + 276 model preamble scaffolding) |

What can look at first glance like "2.5 caching the system prompt" is actually `2.5-flash-native-audio` having a smaller fixed preamble (`225` vs. `501` tokens) and omitting tool schemas from `prompt_token_count`. Both models re-bill their active context window on every turn (`~2.9x` cumulative re-bill amplification over 4 to 5 turns).

### K. Thinking Token Accounting (`thoughts_token_count`)
* On `gemini-live-2.5-flash-native-audio` with `thinking_budget=0` and `gemini-3.1-flash-live-preview` with `ThinkingLevel.MINIMAL` (`include_thoughts=False`), `thoughts_token_count` is `0` (`None`) on standard conversational turns.
* Always keep `thinking_level="MINIMAL"` and `include_thoughts=False` on 3.1 Live for real-time voice agents; higher thinking levels (`LOW`, `MEDIUM`, or `HIGH`) add both turn latency and output-rate thinking token spend (`$4.50 / 1M`) across multi-turn calls.

### L. Parametric Per-Call Cost Model & Turn-by-Turn Calculator

Because **both user speech (`u_aud`) and played model output audio (`b_aud_kept`)** accumulate in `Prompt AUDIO` on every turn until `SlidingWindow(5000/3500)` triggers, and **both user ASR text (`u_txt`) and model output text (`b_txt`)** accumulate in `Prompt TEXT`:

```python
def calculate_live_session_cost(
    si_tokens: int = 500,
    tool_tokens: int = 200,
    turns: int = 6,
    user_sec_per_turn: float = 4.0,
    bot_sec_per_turn: float = 6.0,
    barge_in_play_ratio: float = 1.0,
    model: str = "gemini-3.1-flash-live-preview",
    sliding_window_trigger: int = 5000,
    sliding_window_target: int = 3500,
) -> dict:
    # Turn-by-turn token and USD calculator matching Gemini Live production billing.
    u_aud = int(round(user_sec_per_turn * 25))
    b_aud_gen = int(round(bot_sec_per_turn * 25))
    b_aud_kept = int(round(b_aud_gen * barge_in_play_ratio))
    u_txt = int(round(u_aud * 0.15))
    b_txt = int(round(b_aud_gen * 0.25))

    if model == "gemini-live-2.5-flash-native-audio":
        r_txt_in, r_txt_out, r_aud_in, r_aud_out = 0.50, 2.00, 3.00, 12.00
        base_txt = si_tokens  # 2.5 omits static tool_tokens from prompt_token_count
        thoughts_per_turn = 0
    else:
        r_txt_in, r_txt_out, r_aud_in, r_aud_out = 0.75, 4.50, 3.00, 12.00
        base_txt = si_tokens + 276 + tool_tokens  # 3.1 adds +276 preamble scaffolding
        thoughts_per_turn = 0  # 0 with ThinkingLevel.MINIMAL

    cum_txt_in = 0
    cum_aud_in = 0
    hist_turns = []  # list of (turn_txt, turn_aud)

    for _ in range(1, turns + 1):
        hist_txt = sum(x[0] for x in hist_turns)
        hist_aud = sum(x[1] for x in hist_turns)
        cur_txt = base_txt + hist_txt + u_txt
        cur_aud = hist_aud + u_aud

        if sliding_window_trigger and (cur_txt + cur_aud) > sliding_window_trigger:
            while hist_turns and ( base_txt + sum(x[0] for x in hist_turns) + u_txt + sum(x[1] for x in hist_turns) + u_aud ) > sliding_window_target:
                hist_turns.pop(0)
            cur_txt = base_txt + sum(x[0] for x in hist_turns) + u_txt
            cur_aud = sum(x[1] for x in hist_turns) + u_aud

        cum_txt_in += cur_txt
        cum_aud_in += cur_aud
        hist_turns.append((u_txt + b_txt, u_aud + b_aud_kept))

    resp_aud = turns * b_aud_gen
    resp_txt = turns * (b_txt + thoughts_per_turn)

    usd = (
        cum_txt_in * r_txt_in
        + cum_aud_in * r_aud_in
        + resp_aud * r_aud_out
        + resp_txt * r_txt_out
    ) / 1e6

    return {
        "prompt_text_tokens": cum_txt_in,
        "prompt_audio_tokens": cum_aud_in,
        "response_audio_tokens": resp_aud,
        "response_text_and_thought_tokens": resp_txt,
        "total_usd": round(usd, 5),
    }
```

### M. Duplex Voice Compounding Economics: The "Carried Audio Tax" & Who Drives Call Cost

Empirical measurements on an 18-turn uncompressed session (`54,315` total billed tokens, `$0.1178` on Gemini 2.5 Flash Native Audio) illustrate why carried audio history dominates multi-turn voice spend:

```text
+------------------------------------------------------------------------+
|  Audio Prompt Input (Carried Audio History) : 25,365 tok -> $0.0761 (64.6%) |
|  Audio Response Output (Generated Speech)   :  2,268 tok -> $0.0272 (23.1%) |
|  Text Prompt Input (System & Cards)         : 25,904 tok -> $0.0130 (11.0%) |
|  Text Response Output (Transcripts)         :    778 tok -> $0.0016  (1.3%) |
|  --------------------------------------------------------------------  |
|  TOTAL                                      : 54,315 tok -> $0.1178 (100%)  |
+------------------------------------------------------------------------+
```

1. **Why `$12.00 / 1M` Audio Output Is Only 23.1% of Total Spend**:
   - Although generated bot speech has the highest unit price (`$12.00 / 1M` tokens = `$0.018 / min`), `Candidate AUDIO` is billed **only once** on the turn it is spoken.
2. **Why `Prompt AUDIO` (`$3.00 / 1M`) Drives 64.6% of the Call Bill**:
   - Every turn's user audio and played bot audio remain in `Prompt AUDIO` and are re-billed at `$3.00 / 1M` on every subsequent turn until `SlidingWindow(5000/3500)` evicts old turns.
   - By Turn 14 of an uncompressed call (`2,363` accumulated audio tokens in prompt), even a one-word user acknowledgment (*"Yes"*) re-processes all `2,363` prior audio tokens at `$3.00 / 1M`.
   - Note why the 18-turn trace above cost `$0.1178`: it already used a compact `~500`-token root prompt (`25,904` cumulative text tokens across 18 turns) rather than a monolithic `4,500`-token static SOP (`81,000` cumulative text tokens).
   - Combining all three optimization levers (Pillar 1 `SlidingWindow(5000/3500)` for long calls + Pillar 2 JIT Prompt Cards capping active instructions at `~500` tokens + Pillar 3 rolling audio-to-text pruning / `FactStore` `< 60` tokens for calls under 15 turns) reduces a 3-minute, 18-turn enterprise call from **`$0.246` (`$0.082/min` with a 4,500-token static prompt and unpruned audio)** down to **`$0.093` (`$0.031/min`, a 62% reduction)**.

### N. Interruption Economics & Barge-In Math (Output Savings vs. Extra-Turn Prompt Fee)

When a user interrupts the bot mid-speech (`server_content.interrupted == True`), two opposing cost effects occur:

1. **What You Save (Aborted Output Audio + Truncated History)**:
   - The server stops generating remaining audio (`saving $12.00 / 1M` on ungenerated output tokens) and truncates the unplayed tail of the bot's turn so unplayed audio tokens are not carried forward into future `Prompt AUDIO` turns.
   - Example: Cutting off a `300`-token bot monologue after `50` played tokens saves `250` output audio tokens (`$0.0030`) plus `250 * $3.00 / 1M = $0.00075` on every subsequent turn.
2. **The Hidden Trap (The "Micro-Interruption Prompt Fee")**:
   - Input prompt evaluation for the interrupted turn has **already occurred and been billed** before the first audio chunk was generated.
   - If the interruption was a false barge-in (a cough, throat clear, or backchannel *"uh-huh"* that triggers an extra conversational turn), the model must run a brand-new prompt evaluation across the entire active context window (`3,500 to 4,000` tokens):
     ```text
     Extra Turn Prompt Cost = (2,300 audio tok * $3.00/1M) + (1,700 text tok * $0.50/1M) = $0.00775
     Net Impact of False Barge-In = $0.00300 saved - $0.00775 extra turn = -$0.00475 net loss
     ```
3. **Golden Rule of Interruption**:
   - **Decisive Interruption (Saves Money)**: Caller cuts off an unwanted explanation and pivots directly to the next step (*"Skip that, book the 10 AM slot"*), replacing a turn and truncating carried bot audio.
   - **Fragmented False Barge-In (Burns Money)**: Coughs or backchannel fillers (`"uh-huh"`) split one turn into two, re-billing the entire context history. Tune `StartSensitivity.START_SENSITIVITY_LOW` and `SileroVADAnalyzer(confidence=0.7, start_secs=0.2)` to filter out non-speech bursts.

### O. Model Comparison & Production Decision Matrix (`2.5 Native Audio` vs. `3.1 Flash Live`)

| Dimension | `gemini-live-2.5-flash-native-audio` (GA) | `gemini-3.1-flash-live-preview` (Preview) |
|---|---|---|
| **Deployment Endpoints** | Vertex AI (`us-central1`, `v1beta1`) | Google AI Studio (`v1alpha` / `v1beta`) |
| **Pricing Rates (In / Out)** | Text: `$0.50` / `$2.00`, Audio: `$3.00` / `$12.00` | Text: `$0.75` / `$4.50`, Audio: `$3.00` / `$12.00` |
| **Fixed Prompt Scaffolding (T0)** | `225` tokens (0 extra preamble scaffolding) | `501` tokens (`+276` model preamble scaffolding) |
| **Tool Schema & Response Accounting** | `0` billed tokens for static `function_declarations`; bills `FunctionResponse` payloads in history | Bills `+276` preamble tokens, all declared `tools` schemas, and every `FunctionResponse` payload in history on every turn (`CallSlots` pruning required) |
| **Thinking Configuration** | `ThinkingConfig(thinking_budget=0)` | `ThinkingConfig(thinking_level="MINIMAL")` (never pass `thinking_budget=0`) |
| **Proactive Audio & Affective Dialog** | Supported (`proactive_audio=True`, `enable_affective_dialog=True`) | Unsupported (causes `1007` handshake error if set) |
| **Usage Metadata Reconciliation** | 100% exact (`residual = 0` on every turn) | `93 to 221 tok/turn` unattributed residual on AI Studio (`prompt_token_count - sum(details)`) |
| **Ideal Use Case** | Cost-sensitive high-volume voice bots and affective dialogue | Low-latency multi-step reasoning, expressive multilingual voice agents, and dynamic tool workflows |

### P. Enterprise Voice Agent Design Principles

1. **Target 6 to 8 Turns for Transactional Funnels**:
   - A focused 6-turn booking or verification call stays well below the 5,000-token compaction trigger and costs **`~$0.025 to $0.035`** in total.
2. **Enable `SlidingWindow(5000, 3500)` on Every Session**:
   - Keeps active context between `3,500` and `5,000` tokens so 15-to-30-minute support calls scale linearly (`~$0.06/min` with `SlidingWindow` alone, or `~$0.031/min` when combined with JIT prompt cards and rolling audio-to-text pruning as shown in §13.M) rather than quadratically.
3. **Decouple UI Progress Telemetry from Model Tool Calling**:
   - Never rely on the voice model to call a `get_phase_card` or `track_progress` tool just to update the browser UI.
   - Run server-side regex and async Flash-Lite transcription tracking (`PhaseTracker`) on incoming user transcripts for **`0ms` voice latency, `$0` Live tool token overhead, and deterministic UI state updates**.
4. **Gate the Microphone on Turn 1**:
   - Keep client mic audio gated until the opening greeting finishes playing (`TTSStoppedFrame`) so ambient room noise during the greeting is never metered into Turn 1 `Prompt AUDIO`.

### Q. The Turn-0 Cold-Start Trap: Why Initial Tokens Ballooned to 1,254 (RCA & Guard Invariant)

#### The Incident
During live benchmarking of an automotive concierge agent (*"Cymbal Auto"*), Turn 1 token consumption spiked to **1,254 total tokens**, despite the Root System Instruction (SI) being authored to be compact (`488` tokens).

#### The Root Cause Investigation
Telemetry from the raw session trace revealed a 3-step chain reaction on Turn 0:
1. **Initial Handshake (Turn 0 Setup)**:
   - At connection time, the server reported `Prompt: 488 (TEXT: 488, AUDIO: 0)`.
2. **Premature Autonomous Tool Dispatch on Turn 0**:
   - Before speaking the opening greeting, the model autonomously evaluated its tools and invoked `switch_phase(phase_id="SOP_02_DISCOVERY")`.
   - Because the tool handler executed synchronously, the server injected the **535-token** `SOP_02_DISCOVERY` prompt card into active session context *before* the first audio greeting was generated.
3. **Prompt Ballooning**:
   - The prompt jumped from `488` to **`1,023` text tokens** (`488` root SI + `535` discovery card).
   - The model then generated its spoken greeting (`231` response tokens = `40` text + `191` audio), resulting in **`1,023 prompt + 231 response = 1,254 billed tokens on Turn 1`**:

```text
+------------------------------------------------------------------------+
|  Turn 0 Connection    :  488 prompt text tokens (Lean Root SI)         |
|  Premature Tool Call  :  switch_phase(SOP_02_DISCOVERY) fired on T0    |
|  JIT Card Injected    : +535 prompt text tokens                        |
|  Turn 1 Spoken Prompt : 1,023 text tokens                              |
|  Turn 1 Model Output  :  231 response tokens (40 text, 191 audio)      |
|  --------------------------------------------------------------------  |
|  TURN 1 TOTAL BILLED  : 1,254 tokens (2.5x the expected ~500 tokens)   |
+------------------------------------------------------------------------+
```

#### The Architectural Rule: Cardless & Tool-Free Opening Boundaries
1. **Phase 1 (`SOP_01_OPENING`) Must Be Strictly Cardless**: The opening greeting must never inject a JIT prompt card. Callers who immediately hang up or ask for a callback incur only the `~490`-token base cost.
2. **Explicit Turn-0 Tool Prohibition in System Instructions**:
   Instruct the model in the root System Instruction:
   ```text
   CURRENT PHASE: OPENING. Start: नमस्ते, मैं Cymbal Auto से Pragya बोल रही हूँ। आपने हमारी गाड़ियों में interest दिखाया था। क्या अभी दो मिनट बात कर सकते हैं?
   Speak the opening line first without calling any tools.
   Call switch_phase only after the caller replies (never on the opening greeting):
   - Consent to talk or vehicle questions: SOP_02_DISCOVERY.
   ```
3. **Impact**: Turn 1 prompt tokens dropped from `1,023` back down to **`494` tokens**, eliminating the `1,254`-token cold-start spike.

### R. The 7 Counter-Intuitive Truths of Real-Time Voice Models

1. **The `$12/1M` Output Audio Myth**: Generated bot speech (`$12.00/1M`) is billed only once on the turn it is emitted (~23% of total session cost), whereas carried `Prompt AUDIO` (`$3.00/1M`) is re-billed on every subsequent turn (~65% of uncompressed session cost).
2. **Bidirectional Audio Accumulation (`Prompt AUDIO`)**: Both user speech and played bot output audio persist in `Prompt AUDIO` across turns until evicted by `SlidingWindow(5000/3500)` or truncated by barge-in.
3. **The Interruption Tax Paradox**: Decisive barge-ins save money by truncating unplayed bot audio from both current output and future `Prompt AUDIO` history; fragmented false barge-ins (coughs, *"uh-huh"*) burn money by triggering a second full-window prompt evaluation (`+$0.00775`).
4. **Zero Implicit Cache Discount (`cached_content_token_count = 0`)**: Neither Vertex AI nor AI Studio applies an implicit cache discount on Live sessions today. Keep root prompts compact (`~500` tok) and prune tool declarations on 3.1 Live.
5. **The Turn-0 Tool Hijack**: Autonomous models will call routing tools before speaking their greeting unless explicitly instructed to speak the opening line first without calling tools.
6. **Funnel Telemetry Must Never Rely on Model Tool Choices**: Track funnel progression on the server using regex + async Flash-Lite classification over user transcripts (`0ms` latency, `$0` Live tool tokens).
7. **Always Pair `SlidingWindow(5000/3500)` with a `<60-Token` `FactStore`**: Server-side sliding-window compression caps context size on long calls while `FactStore` + 10-turn transcript restoration prevents context amnesia across compaction boundaries.

### S. Enterprise Live Audit & Cost Reconciliation Invariants

1. **Always Include `other_input_token` in Cost Calculators**:
   - On AI Studio endpoints, `prompt_token_count` exceeds the sum of `prompt_tokens_details` by `93 to 221` tokens per turn.
   - Always compute `other_input_token = max(0, prompt_token_count - sum(modality_details))` and bill it at the text input rate so unlabelled prompt tokens are never omitted from cost reconciliations.
2. **The "Step 0 Before/After Raw Trace" Audit Rule**:
   - Rolled-up session CSVs cannot isolate per-turn tool-call rounds, open-mic greeting audio, or model scaffolding deltas.
   - Before deploying any prompt or pipeline change (`live_tool_names=None`, `ThinkingLevel.MINIMAL`, `CallSlots`), **Step 0 must always be exporting one raw turn-by-turn `usage_metadata` JSON trace** (`prompt_token_count`, `prompt_tokens_details`, `candidates_token_count`, `thoughts_token_count`) before and after the change.

---

## 14. Production Deployment & Cloud Run Infrastructure

### A. Multi-Stage Dockerfile Pattern
```dockerfile
# Stage 1: Build client
FROM node:18-slim as client
WORKDIR /app/client
COPY client/package*.json ./
RUN npm install
COPY client/ ./
RUN npm run build

# Stage 2: Build server
FROM python:3.12 as server
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential libjpeg-dev zlib1g-dev libsndfile1-dev && rm -rf /var/lib/apt/lists/*
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m spacy download en_core_web_sm
COPY server/ .
COPY --from=client /app/client/dist ./client/dist
EXPOSE 7860
ENV GOOGLE_ENTRYPOINT="python server.py"
CMD ["python", "server.py"]
```

### B. Production Cloud Run Deployment Command
Gemini Live sessions rely on stateful bidirectional WebSockets. Always deploy Cloud Run with `--timeout=3600`, `--session-affinity`, and `--no-cpu-throttling`:
```bash
gcloud run deploy gemini-live-agent \
  --source . \
  --platform managed \
  --region us-central1 \
  --project "${PROJECT_ID}" \
  --ingress all \
  --allow-unauthenticated \
  --session-affinity \
  --memory 2Gi \
  --cpu 2 \
  --no-cpu-throttling \
  --cpu-boost \
  --min-instances 1 \
  --max-instances 100 \
  --concurrency 80 \
  --timeout 3600 \
  --service-account "gemini-live-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCP_LOCATION=us-central1,USE_VERTEXAI=true" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest"
```

### C. Rollout Verification & Health Check Invariant
Always verify the local test suite before triggering a Cloud Run build, and verify revision readiness after deployment:
```bash
./server/venv/bin/python server/test_routes.py
gcloud run services describe gemini-live-agent --region us-central1 --format="value(status.url,status.latestReadyRevisionName)"
```

---

## 15. Branch-First Release Discipline

1. **Canonical Repository Structure**: Keep all voice pipelines, server handlers, and frontend AudioWorklet clients in a single unified repository (`gemini_live_pipecat/`).
2. **Branch-First Rule**: Develop all new customer POCs and features on a dedicated branch off `main`:
   ```bash
   git checkout main && git pull origin main
   git checkout -b feat/<project-or-feature-name>
   ```
3. **Pre-Merge Test Gate**: Run `./server/venv/bin/python server/test_routes.py` (must pass 100%).
4. **Clean Merge & Remote Cleanup**:
   ```bash
   git checkout main && git pull origin main
   git merge <branch-name> --no-edit && git push origin main
   git branch -d <branch-name> && git push origin --delete <branch-name>
   ```

---

## 16. Frontend Audio Engineering, Constraints & Resilience

### A. Source-Level Hardware DSP & Web Audio Constraints
Clean microphone audio at the source (browser Web Audio API) before sending frames over WebSocket or WebRTC:
```javascript
const stream = await navigator.mediaDevices.getUserMedia({
  audio: {
    sampleRate: 16000,
    echoCancellation: true,    // Prevents the agent from hearing its own speaker output
    noiseSuppression: true,    // Improves speech SNR in noisy environments
    autoGainControl: true,     // Normalizes mic levels across user devices
    channelCount: 1,           // Mono audio stream
  },
});
```
* **Noisy Kiosk / Speakerphone Half-Duplex Option**: When deploying on open speakers without headphones, provide a client-side half-duplex gate (`isBotSpeaking`) that zeroes outgoing mic PCM frames while the `AudioWorklet` playback buffer is active, unmuting `250ms` after playback drains.

### B. `AudioWorklet` Thread Isolation & 60ms Initial Pre-Buffer
* Never schedule individual 20ms WebSocket packets via `AudioContext.createBufferSource()` on the main UI thread. Offload all raw PCM capture, resampling, and ring-buffer playback (`240,000` float32 samples = 10s at 24kHz) to a dedicated **`AudioWorkletProcessor`** with a **60ms initial pre-buffer (`1,440` samples)** before starting playback to eliminate DOM-render jitter clicks.
* Use separate `AudioContext` instances for input capture (`16000 Hz`) and output playback (`24000 Hz`).

### C. Dynamic Buffering & Network Backpressure
* **Adaptive Ring & Jitter Buffers**: Dynamically scale input/output audio buffers based on network throughput and frame arrival jitter.
* **WebSocket Backpressure Management**: Monitor `websocket.bufferedAmount`. When exceeding high-water marks, queue audio client-side to prevent TCP socket stalls.
* **Circuit Breaker Pattern**: Pause transmission after repeated socket errors and probe recovery with exponential backoff.
* **Client-Side VAD for Instant Barge-In**: Analyze mic energy on the client to cut off local speaker playback immediately upon user speech without waiting for the server round-trip.

### D. Deferred Audio Playback Queue for Async Tool Speech
* When an asynchronous background tool completes and triggers proactive model speech while an earlier conversational turn's audio is still playing out on the client speaker, buffer the incoming tool-response audio in a separate **deferred playback queue**.
* Drain the deferred queue only after the active playback buffer finishes or is flushed by a user barge-in event. This prevents overlapping audio tracks and premature cutoff of ongoing explanations.

---

## 17. Turn Completion Truth (`onTurnComplete`) & Audio Debounce

There are three distinct "model finished" signals in a duplex WebSocket session. Conflating them causes cut-off sentences, premature timers, and race conditions:

| Signal | Definition | Firing Timing & Hazard |
|---|---|---|
| **Server `turnComplete`** | Server finished transmitting response chunks over the socket. | Fires **early** while several seconds of PCM audio are still buffered and playing through the user's speakers. Injecting `turnComplete: true` text here immediately cuts off audible speech. |
| **Client `isAiSpeaking = false`** | Zero active audio sources playing in the browser. | Unreliable on its own because brief network jitter between audio chunks causes momentary zero-source gaps. |
| **Composite `onTurnComplete`** | Both `serverTurnDone === true` AND `activeSources.size === 0` after a 300ms drain debounce. | The **authoritative signal** that the model has completely finished speaking. |

### AI Speaking Debounce & Turn-Completion Implementation
* **Immediate Start (0ms debounce)**: Fire `onAiSpeakingChange(true)` immediately when the first audio chunk arrives so UI visualizers react right away.
* **Debounced Stop (300ms debounce)**: When the last audio buffer finishes playing, start a `300ms` timer before firing `onAiSpeakingChange(false)`. Cancel the timer if a new audio chunk arrives within `300ms`.
* **Strict Separation of Concerns**: Bind waveform visualizers to `isAiSpeaking`. Bind application state machines, response timers, and buffered context flushes strictly to **`onTurnComplete`**.

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

## 18. Prompt Optimization, Positional Prompt Anatomy & System Instruction Playbook

### A. Positional Prompt Anatomy (How the Model Prompt Is Constructed)
In a Gemini Live session, `systemInstruction`, `tools`, conversation history, and dynamic context updates are not independent settings: they occupy **fixed positions** inside the model prompt on every inference pass. Understanding those positions explains both how strongly an update steers the current turn and whether it invalidates the prefix cache:

```text
ROLE_SYSTEM:
  1. <base spoken-dialog preamble>             <- Server-internal spoken dialog mode instructions
  2. <voice reference embedding>               <- ~224-239 audio hard tokens resolved from speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName

ROLE_DEVELOPER:
  3. <function declarations>                   <- setup.tools (serialized FIRST inside ROLE_DEVELOPER)
  4. <developer instruction>                   <- setup.systemInstruction (maps to ROLE_DEVELOPER, after tools)
------------------------------------------------- [Prefix Cache Boundary]
ROLE_USER / ROLE_ASSISTANT:
  5. <conversation history>                    <- Prior clientContent & realtimeInput turns (audio + transcripts;
                                                  barge-in turns are truncated to only the audio the caller actually heard)

ROLE_CONTEXT:
  6. <time and location>                       <- Server-injected runtime metadata (from session timezone / location)

ROLE_USER:
  7. <current user turn>                       <- Active endpointed caller utterance (<audio> + transcript)

ROLE_CONTEXT:
  8. <client / session context>                <- Tail context (phase state, FactStore, WHEN_IDLE updates)
```

#### Four Architectural Consequences of This Layout
1. **Why Public `systemInstruction` Lives in `ROLE_DEVELOPER` (After `tools`)**:
   True `ROLE_SYSTEM` is reserved for the server's spoken-dialog preamble and the ~`224–239` audio hard tokens that encode your selected `voiceName`. Your `setup.systemInstruction` is placed in `ROLE_DEVELOPER` immediately **after** `<function declarations>` (`setup.tools`). If you declare 15–20 heavy tool schemas, they sit ahead of your `systemInstruction` in `ROLE_DEVELOPER`, which is another reason to keep declared tools pruned to 1–5 active schemas (`CallSlots`).
2. **Tail Context Is the Last Thing the Model Sees (Recency Steering)**:
   Because `ROLE_DEVELOPER` (`tools` + `systemInstruction`) sits at the very top of the prompt, accumulated multi-turn audio and transcript history (`ROLE_USER / ROLE_ASSISTANT`) gradually separates your opening instructions from the caller's latest utterance. By contrast, tail context sits immediately after `<current user turn>`, making it the last thing the model reads before generating speech and the strongest lever for state that changes during a session (active conversation phase, verified caller facts, or live cart state).
3. **`systemInstruction` and `tools` Form the Prefix-Cached Preamble**:
   Inside `ROLE_DEVELOPER`, `<function declarations>` (`tools`) are placed first, followed by `<developer instruction>` (`systemInstruction`). Because both sit in the preamble at the start of the token sequence, mutating either `systemInstruction` or `tools` mid-session invalidates the prefix cache for the rest of the session, whereas updating tail context after the conversation history preserves the cached prefix.
4. **Barge-In Truncates History to What the Caller Actually Heard & Session Resumption Uses Pre-Tokenized History**:
   Only the Live server knows which streamed audio frames were endpointed into a turn and the exact playback timestamp where a user barged in (slicing unplayed bot audio chunks out of `ROLE_ASSISTANT` history and appending `"—"` to the partial transcript so the model never assumes the caller heard the rest of an interrupted sentence). When using `SessionResumptionConfig`, the server resumes from pre-tokenized history chunks rather than re-tokenizing raw audio bytes.

| Information Type | Where to Place It | Update Cadence | Prefix Cache Impact |
| :--- | :--- | :--- | :--- |
| **Persona, vocal tone, speaking pace, and language/gender rules** | `setup.systemInstruction` (`ROLE_DEVELOPER`) | Set once at session start | Cached in preamble |
| **Core tool schemas (`functionDeclarations`)** | `setup.tools` (`ROLE_DEVELOPER`) | Set once at session start (or updated sparingly on major phase shifts) | Cached in preamble (updating invalidates cache) |
| **Active conversation phase rules (`Phase 2: KYC Verification`)** | Tail context (`FunctionResponse` with `scheduling=WHEN_IDLE` or between-turn context update) | On phase transition (`3 to 5 times` per call) | Preserves preamble prefix cache |
| **Verified caller facts (`FactStore`: name, postal code, ticket ID)** | Tail context (`<60 tokens` compact JSON/text summary) | Updated after key facts are captured | Preserves preamble prefix cache |
| **Large reference catalogs or policy docs (`>1,000 tokens`)** | Behind a non-blocking lookup tool (`CallSlots` returning `~25-token` speakable summaries) | Fetched on demand | Zero static prompt tax |

### B. Pre-Connect Complete SI vs. Mid-Session Interruptions
* Any `sendClientContent` call during an active generation turn interrupts model speech (even when `turn_complete=False` is set).
* **Rule**: Never stream or append large instructional blocks mid-session while the bot is speaking. Await any asynchronous user profile lookups *before* opening the WebSocket, assemble the initial System Instruction (`Persona + Rules + Grounding Context`), and connect once.

### C. Numbered Sequential Phases & Prescriptive Tool Flows
* Organize multi-step interactions into numbered phases (`STEP 1: VERIFICATION`, `STEP 2: DISCOVERY`, `STEP 3: RESOLUTION`).
* Spell out explicit, step-by-step tool execution sequences (`a, b, c, d`) so the model never guesses turn boundaries:
  ```text
  CRITICAL FLOW (ONE QUESTION AT A TIME):
  a) Ask the caller ONE clarifying question.
  b) Call record_customer_intent immediately after they answer.
  c) Stop speaking and wait for the tool result or next user utterance.
  d) Listen to their complete response before advancing to Step 3.
  ```

### D. Positive Behavioral Framing over Negative Prohibitions
* Negative instructions (*"Do NOT narrate tool calls"*, *"Do NOT repeat yourself"*) frequently fail under audio streaming pressure due to token attention priming.
* Use **positive behavioral framing** that defines the model's exact role after an action:
  - **Instead of**: `"Never narrate or announce when you call a function."`
  - **Use**: `"When you invoke a tool, stop speaking immediately and remain silent. Your sole job after emitting a tool call is to listen."`

### E. Language Pinning & Acoustic Noise Guardrails
* Native audio models can code-switch when exposed to regional caller accents, coughs, or background office chatter.
* Include explicit language-pinning and acoustic-filtering directives in every production System Instruction:
  ```text
  LANGUAGE PINNING: Speak exclusively in the target language (for example English or Hindi). Every word you output must remain in the target language regardless of background noise or caller accent.
  ACOUSTIC FILTERING: The caller is in a noisy environment. Ignore background conversations, side chatter, and non-directed sounds.
  ```

### F. Single Source of Truth (Anti-Duplicate Delivery)
* If a follow-up action or prompt card is injected dynamically via tail context or tool responses, **remove that instruction from the base System Instruction**. Duplicating instructions in both the root SI and runtime context causes the model to deliver the same message twice.

### G. The `"Stay Silent"` Transcription Trap
* **Never instruct the Gemini Live model to `"stay silent"` or `"produce no audio"` for a full turn.**
* When the model generates zero audio output for a turn, the Gemini Live backend suppresses `inputAudioTranscription` events as well, breaking server-side transcript loggers, phase trackers, and Conductor parsers.

### H. Natural Language Prefixes over Bracket Tags
* Avoid bracketed metadata tags like `[SCRIPT]`, `[SYSTEM_NOTE]`, or `[CONTEXT]` in injected text. Native audio models frequently vocalize bracketed words aloud. Use natural-language prefixes such as `"System update for agent: ..."`.

---

## 19. Gemini Live API Turn Management & VAD Tuning (`RealtimeInputConfig`)

Configure server-side turn detection and voice activity parameters within `LiveConnectConfig`:

### A. `AutomaticActivityDetection` (Server-Side VAD)
| Parameter | Recommended Production Setting | Rationale |
|---|---|---|
| `start_of_speech_sensitivity` | `START_SENSITIVITY_LOW` | Eliminates false barge-in triggers from background room noise, typing, or breathing. |
| `end_of_speech_sensitivity` | `END_SENSITIVITY_LOW` | Allows natural mid-sentence pauses without prematurely cutting the caller off. |
| `prefix_padding_ms` | `200` | Captures the leading consonant of user speech before VAD onset confirmation. |
| `silence_duration_ms` | `400` to `800` | Balances responsive turn-taking (`400ms` to `600ms`) with breathing room for thoughtful answers (`800ms`). |
| `disabled` | `False` | Keep `False` unless implementing custom client-side activity framing (`activity_start` / `activity_end`). |

```python
realtime_input_config = types.RealtimeInputConfig(
    automatic_activity_detection=types.AutomaticActivityDetection(
        disabled=False,
        start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
        end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
        prefix_padding_ms=200,
        silence_duration_ms=400,
    ),
    activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
)
```

### B. `TurnCoverage` & `activityHandling`
* **`TURN_INCLUDES_ALL_INPUT` (Recommended for Barge-In)**: Includes all audio (including periods when the model is speaking) as part of the conversational turn so the model receives full context when interrupted.
* **`TURN_INCLUDES_ONLY_ACTIVITY`**: Includes only active speech segments. Yields cleaner transcripts in noisy rooms but can clip abrupt barge-in phrases.
* **`activityHandling: "START_OF_ACTIVITY_INTERRUPTS"`**: Standard duplex setting where detected speech interrupts model output. Pair with `START_SENSITIVITY_LOW` to prevent ambient noise from triggering interruptions.

---

## 20. Interruption, Greeting Recovery & Cached TTS Protocol

### A. The Opening Greeting Interruption Bug & Workaround
When a caller interrupts the model during its opening introduction on the Live API, the model retains context of its partially generated transcript and can skip the rest of the mandatory disclosure rather than restarting cleanly.

Track introduction state and inject a single-shot recovery turn upon interruption:

```python
# State Tracking Variables
introduction_complete = False          # True when full intro has been spoken
introduction_restart_injected = False  # Single-shot latch (prevents infinite loop)
cumulative_output_text = ""            # Buffer accumulating model output text
```

#### Logic Flow:
1. **Track Output**: Append every `output_transcription` chunk to `cumulative_output_text`. When the closing phrase of the intro is detected (such as `"how can I assist you today"` or `"क्या अभी दो मिनट बात कर सकते हैं"`), set `introduction_complete = True`.
2. **Handle Interruption**: When `interrupted: true` arrives:
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
                           text="System update for agent: The caller did not hear your introduction due to an audio interruption. "
                                "Please start again with your complete introduction: '<FULL_INTRO_TEXT>'"
                       )]
                   )
               ],
               turn_complete=True
           )
           introduction_restart_injected = True
   ```
3. **Idempotency Guard**: Injecting at most once (`introduction_restart_injected = True`) prevents greeting loops when callers speak repeatedly during the opening turn.

### B. Barge-In Hardware & Buffer Purge Invariant (`interrupted: true`)
When `ServerMessage.server_content.interrupted: true` arrives during user barge-in:
* **Audio Queue Purge**: Immediately stop model audio playback and flush the unplayed PCM ring buffer so stale audio frames never bleed into the next conversational turn.
* **Transcription Pruning**: Stop appending to the active model transcription bubble and discard unrendered partial text deltas.
* **Late `inputTranscription` Flush**: When the model produces minimal audio, `inputTranscription` chunks can arrive *after* server `turnComplete`. Track a `turnHasCompleted` flag and flush late-arriving user transcription chunks before applying audio-gating filters.

### C. Cached TTS for Lines That Never Change (Greetings, Tool Fillers & Cascaded Pipelines)
Lines that are identical on every call (the opening greeting, `"One moment while I check that"`, or the goodbye) do not need to be generated by Gemini Live each time. Generating an 8-second greeting with Gemini Live costs about 200 output audio tokens (`$12.00/1M` = `$0.0024`) on Turn 1, adds model response latency, and leaves about 200 audio tokens in history that are billed again at `$3.00/1M` (`$0.0054` across turns 2 to 10, or about `$0.0078` per 10-turn call and `$780` per 100,000 calls).

Because Gemini Live and Gemini TTS share the same prebuilt voice names (`Aoede`, `Puck`, `Kore`, `Charon`, etc.) and the same audio format (`24kHz`, 16-bit, mono PCM), and Cloud Text-to-Speech Chirp 3 HD exposes the same voices (`en-US-Chirp3-HD-Aoede`) when you request `LINEAR16` at `24000` Hz, you can synthesize fixed lines once and play the saved clip from memory or Redis. Compare the two clips by ear before shipping, since the two models generate speech separately.

1. **Seed-First Cached Greeting (`role="model"` History Seed + `caller_audio_ok` Gate)**:
   * When the call connects, **first** add the greeting text to Gemini Live's history as a `role="model"` turn with `send_client_content(turn_complete=False)`.
   * Set a `caller_audio_ok: asyncio.Event` gate immediately after the seed so your caller-audio loop waits until the greeting is in history before sending its first `send_realtime_input` chunk. That way the greeting is recorded before the model can hear anything, and the caller can still talk over the clip.
   * Play the saved clip in 20ms (`960`-byte) chunks and stop playback if the caller interrupts. Skip any kick-off `"Hello"` text message that you would normally send to make the model speak first.
   ```python
   import asyncio
   from google.genai import types

   GREETING_TEXT = (
       "Hi, thanks for calling Cymbal Fiber. This is Maya, your virtual assistant. "
       "This call may be recorded for quality. How can I help you today?"
   )
   SAMPLE_RATE = 24_000
   CHUNK_BYTES = SAMPLE_RATE * 2 // 50  # 16-bit mono: 960 bytes = 20ms

   async def play_cached_greeting(session, play_chunk, greeting_pcm: bytes,
                                  caller_interrupted: asyncio.Event,
                                  caller_audio_ok: asyncio.Event):
       """Tell Gemini Live it already greeted the caller, then play the saved clip."""
       await session.send_client_content(
           turns=types.Content(role="model", parts=[types.Part(text=GREETING_TEXT)]),
           turn_complete=False,  # add to history without asking for a reply
       )
       caller_audio_ok.set()  # safe to forward caller audio from here on
       for start in range(0, len(greeting_pcm), CHUNK_BYTES):
           if caller_interrupted.is_set():
               break  # the caller started talking, so stop the clip
           await play_chunk(greeting_pcm[start:start + CHUNK_BYTES])
   ```
2. **Wait Lines During Tool Calls**: Play a short saved clip (`"Let me check that for you."`) from your media server while a tool runs, and stop the clip as soon as model audio arrives. When you use this pattern, remove the *"say a short acknowledgment before calling a tool"* rule from `systemInstruction` so the caller does not hear two acknowledgments.
3. **Repeated Replies in a Cascaded Pipeline (`STT -> LLM -> TTS`)**: Cache TTS audio under a key built from the normalized text, voice, TTS model, and settings like language, speed, and pitch, and skip saving audio when an `InterruptionFrame` arrives. The community package `pipecat-tts-cache` (`TTSCacheMixin`, `MemoryCacheBackend`, `RedisCacheBackend`) wraps any Pipecat TTS service (check its README for supported Pipecat versions before upgrading, and point `RedisCacheBackend` at a private Redis instance since it serializes audio with Python `pickle`):
   ```python
   # pip install "pipecat-tts-cache[redis]"
   from pipecat.services.google.tts import GoogleHttpTTSService
   from pipecat_tts_cache import TTSCacheMixin
   from pipecat_tts_cache.backends import RedisCacheBackend

   class CachedGoogleTTS(TTSCacheMixin, GoogleHttpTTSService):
       pass

   tts = CachedGoogleTTS(
       settings=CachedGoogleTTS.Settings(voice="en-US-Chirp3-HD-Aoede"),
       cache_backend=RedisCacheBackend(
           redis_url="redis://localhost:6379/0",
           key_prefix="pipecat:tts:",
       ),
       cache_ttl=604800,  # keep clips for one week
   )
   ```

---

## 21. Tool-Calling Architecture: `SILENT` Scheduling, Fire-and-Forget & Defensive Guards

### A. Why Unscheduled Tool Responses Cause Double Speech
When a `FunctionResponse` is sent back to Gemini Live after the model has already finished speaking a turn, the model treats an unscheduled or `WHEN_IDLE` response as a prompt to speak about the result. Choose `WHEN_IDLE` vs. `SILENT` deliberately based on whether the model just spoke a filler phrase or already completed its answer:
* **After a Filler Phrase (*"Let me look that up..."*)**: Use `scheduling="WHEN_IDLE"` so the model speaks the lookup result as soon as the filler audio finishes.
* **Silent Background State Capture (Model Already Answered or Moved On)**: Use `scheduling="SILENT"` so the model records the state update without narrating *"I have recorded your preference."*

### B. Pattern 1: `FunctionResponseScheduling.SILENT` (For Silent State-Capture Tools)
* **Vertex AI Support**: Vertex AI Bidi WebSockets natively support `scheduling: "SILENT"` on tool responses.
* **Critical Proxy Rule**: Ensure your WebSocket proxy or Python/TypeScript SDK wrapper **does not strip the `scheduling` field** when serializing `sendToolResponse`.
* **Reinforcement Hint**: Append `"SILENT EXECUTION."` to the end of state-capture tool descriptions in `functionDeclarations`.
```javascript
const functionResponses = responses.map(r => ({
  id: r.id,
  name: r.name,
  response: r.response,
  scheduling: "SILENT" // Updates model context without triggering narration speech
}));
this.session.sendToolResponse({ functionResponses });
```

### C. Pattern 2: Fire-and-Forget (For Stateless UI-Only Tools)
* For purely visual client actions (highlighting a card, scrolling a panel, switching tabs) where the model needs zero state feedback, execute the callback client-side and return a minimal `{"status": "OK"}` response with `scheduling: "SILENT"`.
* **Anti-Pattern (Fire-and-Forget + Audio Gating Loop)**: Never combine fire-and-forget tools with client-side output audio muting (`muteUntilTurnComplete`). Muting post-tool audio drops the model's continuation speech (such as asking the next question), which triggers a premature `onTurnComplete` and stalls the conversation.

### D. Defensive Client Engineering against Model Tool Quirks
Even with well-crafted prompts, native audio models exhibit non-deterministic tool behavior that requires client-side guards:
1. **Two-Tier Tool Deduplication (Same-Batch & Cross-Batch)**:
   - Models invoke the same tool twice for a single event in 15% to 20% of sessions.
   - Implement **per-batch deduplication** (boolean latch inside the `functionCalls` loop) and **cross-batch deduplication** (tracking the last processed idempotency key in a state ref).
   - Always return `{"status": "OK"}` for skipped duplicate calls so the session state remains valid.
2. **`MALFORMED_FUNCTION_CALL` JSON Recovery**:
   - Catch JSON parse or schema validation failures on tool arguments and return a brief structured error message so the model self-corrects on the next turn without crashing the WebSocket.
3. **React Stale Closure Defense (`useRef` Mirroring)**:
   - Tool execution handlers registered when the WebSocket opens capture stale React `useState` closures from the initial render. Mirror live state into a `useRef` synchronized via `useEffect` and read `stateRef.current` inside tool callbacks.

---

## 22. Session Architecture: Grounding, Memory & Managed Session Cycling

### A. The Sliding Window Grounding Dilemma
* Injecting large catalog or page data via chat messages (`sendClientContent`) places that data inside the sliding context window. Once `SlidingWindow(5000/3500)` evicts older turns, mid-call injected grounding data can slide out of context.
* Conversely, naive WebSocket reconnects place fresh grounding data into the persistent `system_instruction`, but cause 500ms to 1s of dead air and repeated browser microphone prompts if the audio hardware is torn down.

### B. The Managed Session Cycling Pattern
When the user navigates to a new context (new product category, new document, or at 12-minute session rotation boundaries):
1. **Maintain Persistent Microphone Capture**: Keep the browser `AudioContext` and `MediaStream` (`getUserMedia`) alive across WebSocket disconnects. Tear down only the WebSocket connection, never the audio hardware pipeline.
2. **Synthesize a Rolling Session Log**: Maintain a compact summary of the session (`FactStore` + last 10 transcript turns).
3. **Parallel Pre-Summarization for Large Data**: If new structured grounding data exceeds `~7,500` tokens, split by section headings and summarize chunks in parallel via non-live `generateContent()` (`~1s` total latency) before building the new System Instruction.
4. **Zero-Drop Reconnect and State Restoration**: Open a new WebSocket with `SI = Persona + Rolling Session Log + Fresh Grounding Data + Tools`. The model naturally references earlier turns (*"As we discussed earlier..."*) while remaining grounded in the new structured data.
5. **Full Teardown on Tab Hidden/Background**: When a browser tab is hidden, perform a clean socket close and re-initialize via the Rolling Session Log when the tab regains focus so background tabs never burn idle audio tokens.

---

### C. Mid-Session Instruction & Tool Updates: What Is Supported vs. What Is Merely Reachable

Long voice calls change shape. The caller gets verified, moves from browsing to checkout, or switches language. You then want a different persona and a different tool set without dropping the WebSocket. There are three ways to do that and they are not equally safe.

**1. Supported and documented: change the system instruction mid-session.**
Send a `clientContent` turn with `role="system"` and `turn_complete=False`. The model picks up the new instructions on its next turn. No reconnect, no dead air, no microphone re-prompt.

```python
await session.send_client_content(
    turns=types.Content(role="system", parts=[types.Part(text="Phase: Checkout. Confirm totals before charging.")]),
    turn_complete=False)
```

Verified working on `gemini-3.8-live` and `gemini-3.5-live-preview`. See [Update system instructions during a session](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/start-manage-session). This is the mechanism to build on.

**2. Supported: reconnect to change tools.** The documented way to swap the active tool set is a new session with new `setup.tools`, using the Managed Session Cycling Pattern above so the microphone stays alive and the rolling session log carries the conversation across.

**3. Reachable on the wire, but unsupported: `contextUpdate`.**
A `contextUpdate` client message exists on the Vertex AI Live WebSocket and does accept a `tools` field, which swaps or clears the active tool declarations in place. On `gemini-3.8-live` and `gemini-3.5-live-preview` it works in our tests. It is still the wrong thing to ship on:

> [!WARNING]
> `contextUpdate` appears in **no public documentation** and in **no released version of the `google-genai` SDK**. Using it means hand-constructing raw JSON frames and reaching into the SDK's private WebSocket object. There is no published support commitment, no compatibility guarantee, and no deprecation policy attached to it. Field numbers and behaviour already differ between Vertex AI and Google AI Studio, and behaviour differs between model builds: in our tests one Gemini 3.5 Live preview build accepted a `tools` update and then **silently ignored** it, with no error to tell you it did nothing, and `gemini-live-2.5-flash-native-audio` closes the connection outright. Even where it works, the model occasionally called a tool that had just been removed, copying an earlier call from the conversation history, so you would still have to check every tool call against the current list. Treat it as unsupported. If a customer needs in-place tool swapping as a product requirement, raise it with your Google account team rather than shipping on an undocumented frame.

**Rule of thumb for customer architectures:** use `role="system"` client content for persona, phase, and policy changes, and Managed Session Cycling when the tool set itself has to change. Both are documented, both survive SDK upgrades.

---

## 23. Voice-Driven UI Navigation: Silent Conductor Split Architecture

When building hands-free voice navigation across complex UI trees or multi-filter catalogs:

### A. Why Direct UI Tool Calling Fails
Giving the Live voice model direct UI selection tools (`select_option(id)`) causes retry latency because audio models frequently paraphrase or alter enum IDs (`"science-and-nature"` instead of `"science"`, `"three_players"` instead of `"3"`).

### B. The Silent Conductor Pattern (Recommended)
Decouple conversational voice rendering from deterministic UI decision-making:
1. **Live Voice Session (Zero UI Navigation Tools)**: Handles natural duplex conversation, empathy, and voice playout. Emits `inputAudioTranscription` of user speech.
2. **Silent Conductor (Non-Live `generateContent` Call with `gemini-2.5-flash-lite`)**: Receives the user's transcribed utterance plus the JSON tree of valid UI option IDs. Returns exact, schema-validated option IDs (`response_mime_type="application/json"`, handling compound requests like *"filter by SUV, under $35,000, automatic transmission"* in one pass).
3. **Background State Sync (`turnComplete: false`)**: The client applies the Conductor's UI state changes and informs the Live voice session via `sendClientContent({ turns: [...], turnComplete: false })`. The voice model sees the updated screen state and naturally acknowledges the selection without double-speaking.

---

## 24. Framework Evaluation Matrix & Decision Guide

| Evaluation Factor | Native Vertex AI / GenAI SDK (Direct WebSocket) | Pipecat (Daily.co / Open Source) | LiveKit Agents |
|---|---|---|---|
| **Architecture** | Direct WebSocket proxy (`asyncio.gather`) | Linear DAG pipeline frame processing (`AudioFrame`) | Room / WebRTC SFU distributed mesh |
| **Latency** | **Lowest (Zero Abstraction Tax)** | Low (`~10 to 20ms` Python frame queue) | Low (WebRTC SFU network hop) |
| **API Release Velocity** | **Immediate (Day-0 access to new `google-genai` flags)** | 2 to 8 week OSS wrapper lag unless subclassed | 1 to 4 week OSS plugin lag |
| **High-Scale Overhead (`>1,000` CCU)** | Lowest memory and CPU footprint | Python `AudioFrame` object allocation pressure | Additional SFU media routing hop |
| **Observability** | Custom OpenTelemetry, LangSmith & Cloud Logging | **Whisker** (local visual debugger) & **Tail** CLI | **LiveKit Cloud Insights** (unified timeline audio/log replay) |
| **Scaling Model** | Cloud Run / GKE HPA on active WebSocket concurrency | Explicit worker pools or Cloud Run concurrency scaling | Automatic warm pool provisioning |
| **Best Suited For** | High-scale (`>1,000` CCU), latency-critical custom voice pipelines | Rapid multi-provider pipelines (Live + Cascaded STT/LLM/TTS fallback) | Turnkey WebRTC rooms, SIP telephony trunks, and multi-participant calls |

---

## 25. Multi-Tier Voice QA & Cascade vs. Native Duplex Unit Economics

### A. Multi-Tier Voice QA Discipline
1. **Tier 1: Automated Text Injection Harness (`~5 min/run`)**: Expose a test hook (`window.__testService.sendText()`) to drive multi-turn state transitions, tool calls, and deduplication guards without audio timing overhead. Remember to pace turn completion waits (`>= generated_audio_duration`) when measuring `Prompt AUDIO` accumulation so you do not trigger synthetic barge-in truncation (§13.C).
2. **Tier 2: Virtual Audio Loopback (`~10 min/run`)**: Route synthesized TTS audio through a virtual audio loopback device (`BlackHole 2ch` on macOS or PulseAudio `module-null-sink` on Linux) into Chrome's `getUserMedia` input to test VAD sensitivity, barge-in recovery, and audio gating end to end.
3. **Statistical Reporting Rule (`N >= 3`)**: Because native audio models are stochastic, never validate a prompt or tool change from a single test run. Run at least `N = 3` trials (`N = 5` for tool-routing edge cases) and verify 100% pass consistency.

### B. Cascade (`STT -> LLM -> TTS`) vs. Native Duplex (`Gemini Live`) Unit Economics

| Architecture | Typical Turn Latency (TTFB) | Optimized Per-Minute Cost (`6 turns/min`) | Strengths & Trade-Offs |
|---|---:|---:|---|
| **Cascaded Pipeline (`Chirp 3 STT -> Gemini 2.5 Flash-Lite -> Cloud TTS`)** | `850ms to 1,400ms` | `$0.018 to $0.026 / min` (`1.8¢ to 2.6¢/min`) | Predictable linear text context growth; explicit transcript inspection before LLM execution; higher turn-taking latency and no native acoustic emotion recognition. |
| **Gemini Live Native Duplex (Optimized: JIT Cards + Audio-to-Text Pruning + `SlidingWindow 5000/3500`)** | **`280ms to 450ms`** | **`$0.025 to $0.031 / min` (`2.5¢ to 3.1¢/min`)** | Sub-500ms human-like turn-taking, native barge-in truncation, affective prosody, and 97+ language fluency at comparable per-minute cost to a cascaded stack. |
| **Gemini Live Native Duplex (Unmanaged: `4,500`-tok static prompt, no `SlidingWindow`)** | `350ms to 600ms` | `$0.082 / min` at 3 min (`$0.246` total), growing quadratically on longer calls | Unbounded `Prompt AUDIO` + static prompt re-billing; always apply the 3-step optimization playbook (§13.B to §13.D) before production launch. |
