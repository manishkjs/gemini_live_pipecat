---
name: gemini-live
description: Production engineering reference for building real-time bidirectional voice and multimodal agents on the Gemini Live API (Vertex AI & Google AI Studio). Covers WebSocket lifecycle, PCM audio pipelines, VAD tuning, async tool calling, Cloud Run deployment, and 3-pillar token cost optimization.
---

# Gemini Live API, Production Agent Skill Reference

Use this skill when designing, implementing, debugging, or optimizing real-time voice and multimodal applications using the **Gemini Live API** (`BidiGenerateContent` over WebSockets) with `google-genai`, Pipecat, ADK, or LiveKit.

---

## 1. Core Architectural Invariants

1. **Single Output Modality per Session**:
   - Always set `response_modalities=["AUDIO"]` (or `["TEXT"]`, never both simultaneously in the same `LiveConnectConfig`).
   - Enable text transcripts alongside audio by adding `input_audio_transcription=AudioTranscriptionConfig()` and `output_audio_transcription=AudioTranscriptionConfig()`.
2. **Audio Format Specification**:
   - **Input (`sendRealtimeInput`)**: Raw 16-bit signed little-endian PCM, **16,000 Hz** mono (`audio/pcm;rate=16000`), streamed in **20ms to 40ms chunks** (`640` to `1,280` bytes).
   - **Output (`serverContent.modelTurn`)**: Raw 16-bit signed little-endian PCM, **24,000 Hz** mono (`audio/pcm;rate=24000`).
   - **PSTN Telephony (8kHz G.711)**: Decode μ-law/A-law to 16-bit PCM, upsample 8kHz → 16kHz on input, and apply a 3.4kHz low-pass filter before downsampling 24kHz → 8kHz on output.
3. **Setup Handshake Order**:
   - The first client frame on the WebSocket MUST be `setup`. Wait for `setupComplete` from the server before streaming `realtimeInput` or `clientContent`.
4. **Unlimited Session Duration (`10m` & `15m` Limits)**:
   - Underlying WebSocket connections rotate every ~10 minutes (`goAway`). Configure `session_resumption=SessionResumptionConfig(handle=saved_handle)` to reconnect without dropping the session.
   - Uncompressed audio sessions terminate at **15 minutes**. Enable `context_window_compression=ContextWindowCompressionConfig(trigger_tokens=5000, sliding_window=SlidingWindow(target_tokens=3500))` for unlimited call duration.

---

## 2. Canonical `LiveConnectConfig` Template (Python `google-genai`)

```python
from google import genai
from google.genai import types

client = genai.Client(
    vertexai=True,
    project="your-gcp-project-id",
    location="us-central1",
)

# Replace None with the latest SessionResumptionUpdate.new_handle on reconnect
saved_handle: str | None = None

config = types.LiveConnectConfig(
    response_modalities=[types.Modality.AUDIO],
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
        )
    ),
    system_instruction=types.Content(
        parts=[
            types.Part.from_text(
                text=(
                    "You are a concise, helpful customer support specialist. "
                    "Keep spoken responses to 1 to 2 short sentences per turn. "
                    "Never use markdown formatting, bullet points, or bracketed stage directions."
                )
            )
        ]
    ),
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
    realtime_input_config=types.RealtimeInputConfig(
        automatic_activity_detection=types.AutomaticActivityDetection(
            disabled=False,
            start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
            end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
            prefix_padding_ms=200,
            silence_duration_ms=500,
        )
    ),
    session_resumption=types.SessionResumptionConfig(handle=saved_handle),
    context_window_compression=types.ContextWindowCompressionConfig(
        trigger_tokens=5000,
        sliding_window=types.SlidingWindow(target_tokens=3500),
    ),
)
```

---

## 3. Prompting Rules for Native Audio Models

- **Never use square brackets**: Do not put stage directions or system tags in square brackets inside `systemInstruction` or `clientContent`. Native audio models either vocalize bracketed tags literally or shift into unnatural theatrical prosody.
- **Enforce spoken brevity**: Instruct the model to speak in **1 to 2 sentences per turn** (15 to 35 words) and pause to check in with the caller.
- **Spell out formatting rules**: Tell the model to read confirmation codes, phone numbers, and digits individually (*"four, two, nine"* instead of *"four hundred twenty-nine"*).
- **Avoid mid-speech `clientContent` injection**: Sending `clientContent` while the model is speaking immediately interrupts generation. Inject dynamic context only after `turnComplete` or via `FunctionResponse(scheduling=WHEN_IDLE)`.

---

## 4. VAD & Barge-In Tuning Matrix

| Environment / Workload | `startOfSpeechSensitivity` | `endOfSpeechSensitivity` | `prefixPaddingMs` | `silenceDurationMs` |
| :--- | :--- | :--- | :--- | :--- |
| **Quiet Office / Headset** | `HIGH` | `HIGH` | `150 ms` | `350 ms` |
| **Mobile / PSTN Telephony** | `HIGH` | `LOW` | `200 ms` | `500 ms` |
| **Noisy Cafe / Car / Field** | `LOW` | `LOW` | `300 ms` | `700 ms` |
| **Form Filling (Reading Digits/IDs)** | `HIGH` | `LOW` | `200 ms` | `800 ms` |

- **Handling `serverContent.interrupted`**: When `interrupted: true` arrives, immediately flush your client/telephony outbound audio buffer so stale audio stops within `<50ms`.

---

## 5. Async Tool Calling & The AntiCancel Shield

1. **`FunctionResponseScheduling`**:
   - `WHEN_IDLE` (default): Speaks the result after current speech completes.
   - `INTERRUPT`: Immediately interrupts current model speech to announce urgent results.
   - `SILENT`: Adds tool data to context without triggering a spoken response.
2. **Shield Tool Tasks from Audio Barge-In**:
   - Wrap state-mutating API calls in `asyncio.shield()` so a user barge-in (`interrupted: true`) only cancels audio playback, never the in-flight `toolResponse`.
3. **Deterministic Tool Triggers (`UNMISTAKABLY`)**:
   - State in the tool `description` that the model must call the tool *"ONLY after the user has UNMISTAKABLY provided `<parameter>`. Never guess or fabricate parameters."*

---

## 6. Token Economics & The 3-Pillar Cost Optimization Architecture

### Gemini Live API Rate Card
- **Text Input**: `$0.75 / 1M tokens` (~4 chars/tok)
- **Audio Input**: `$3.00 / 1M tokens` (~27.8 tok/sec = ~1,668 tok/min ≈ `$0.005/min` single pass)
- **Video/Image Input**: `$3.00 / 1M tokens` (258 tok/frame @ 1 FPS = 15,480 tok/min ≈ `$0.0464/min`)
- **Text Output**: `$3.00 / 1M tokens`
- **Audio Output**: `$12.00 / 1M tokens` (~25 tok/sec = ~1,500 tok/min ≈ `$0.018/min` single pass)

### Why Unmanaged Multi-Turn Calls Spike in Cost ("Carried Audio Tax")
- Implicit caching does **not** discount streaming audio turns on Live WebSockets.
- Every completed turn (`turnComplete`) re-reads your static system prompt + tool schemas (`$0.75/1M`) plus all retained historical audio turns (`$3.00/1M`).

### The 3 Pillars (Reduces 10-Min Call Cost by 82%, down to ~$0.031/min)
1. **Pillar 1, Native Sliding-Window Compression**: Configure `ContextWindowCompressionConfig(trigger_tokens=5000, sliding_window=SlidingWindow(target_tokens=3500))` to cap historical audio accumulation and remove the 15-minute session limit.
2. **Pillar 2, Dynamic Prompt Cards (The Silent Conductor)**: Start with a compact **120-token opening card** (keeping active `systemInstruction` + phase cards averaging **~500 tokens** across the call) and inject phase-specific guidance via `FunctionResponse(scheduling=WHEN_IDLE)` only when the call transitions phases.
3. **Pillar 3, Lossless History Pruning (`FactStore`)**: Convert older audio turns into compact text transcripts (`$0.75/1M`) and extract key facts into a JSON `FactStore` (**under 60 text tokens**), allowing aggressive `5,000-token` sliding-window eviction without losing early-call details.

---

## 7. Cloud Run Production Checklist

```bash
gcloud run deploy gemini-live-voice-gateway \
  --source . \
  --region us-central1 \
  --no-cpu-throttling \
  --timeout 3600 \
  --session-affinity \
  --concurrency 20 \
  --cpu 2 \
  --memory 2Gi \
  --min-instances 1
```

- **Always co-locate in `us-central1`** with `--no-cpu-throttling`, `--timeout 3600`, and `--session-affinity`.
- Grant `roles/aiplatform.user` to the runtime service account.
