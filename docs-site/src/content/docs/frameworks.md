---
title: Orchestration Frameworks
description: Choosing between the Google GenAI SDK, ADK, Pipecat, and LiveKit for Gemini Live applications.
---

<aside class="one-minute" aria-label="In one minute">
  <div class="one-minute-head">
    <span class="badge badge-blue">In one minute</span>
    <span class="one-minute-audience">For product managers and solution architects</span>
  </div>
  <dl class="one-minute-grid">
    <div class="one-minute-cell"><dt>What this page covers</dt><dd>The four ways to connect callers to Gemini Live (raw SDK, Google ADK, Pipecat, LiveKit) and why a native speech model beats a three-service chain.</dd></div>
    <div class="one-minute-cell"><dt>Why it matters</dt><dd>This is the first architecture decision and the hardest to reverse. It also decides whether you get sub-second replies or a 1 to 2 second pause on every turn.</dd></div>
    <div class="one-minute-cell one-minute-number"><dt>The number to remember</dt><dd>A three-stage cascade takes 1,200 to 2,500 ms per turn. The native path stays under a second.</dd></div>
    <div class="one-minute-cell"><dt>The decision you own</dt><dd>Phone lines and carrier trunks (Pipecat), browser and mobile apps (LiveKit or raw SDK), or multi-agent systems on Google Cloud (Agent Development Kit, ADK).</dd></div>
  </dl>
</aside>

When building a Gemini Live application, your first architectural decision is how to connect user devices and telephony trunks to the Gemini Live WebSocket.

---

## 1. Framework comparison matrix

| Framework | Primary Strength | Transport Layer | Best Use Case |
| :--- | :--- | :--- | :--- |
| **Raw `google-genai` SDK** | Zero framework overhead, direct access to every Bidi API field (`send_context_update`, `sessionResumption`, `contextWindowCompression`) | Custom WebSocket / WebRTC | Latency-critical custom gateways, mid-call dynamic prompt cards, and high-concurrency backend services. |
| **Google Agent Development Kit (ADK)** | Built-in `SessionService`, Cloud Trace, evaluation, and multi-agent tool delegation (`mode="single_turn"` / `AgentTool`) | FastAPI WebSocket / `LiveKitRunner` WebRTC | Multi-agent Google Cloud systems where one Live voice root agent delegates inline tasks to specialist text or reasoning agents. |
| **Pipecat (`pipecat-ai`)** | Frame-based audio pipeline, 40+ telephony & SIP connectors (Twilio, Daily, Plivo, Telnyx) | WebRTC (Daily / LiveKit) & SIP WebSockets | Contact center telephony, SIP trunking, custom DSP filters, and hybrid voice/video pipelines. |
| **LiveKit Agents** | Production-grade WebRTC SFU, global edge routing, native browser/mobile SDKs | LiveKit WebRTC | Consumer mobile/web apps requiring low-latency WebRTC, room management, and multi-participant audio/video. |

---

## 2. Native S2S vs. cascaded STT → LLM → TTS inside frameworks

Both Pipecat and LiveKit support two fundamentally different pipeline modes. Make sure you configure the **Native Multimodal / Realtime** node rather than chaining separate STT, LLM, and TTS services:

### Anti-pattern: The 3-stage cascade
```text
[User Audio] → [Deepgram/Chirp STT] → (Text) → [Gemini Flash Text API] → (Text) → [ElevenLabs/Cloud TTS] → [Speaker]
```
- **Latency**: 1,200ms to 2,500ms (sums STT endpointing + LLM TTFT + TTS synthesis).
- **Blind to paralinguistics**: Strips tone, hesitation, and emotion before the LLM sees the input.
- **Triple vendor billing**: Pays separately for ASR per minute, LLM tokens, and TTS characters.

### Recommended: Native Speech-to-Speech (`GeminiMultimodalLiveLLMService`)
```text
[User Audio (16kHz PCM)] ──► [Gemini Live Bidi WebSocket] ──► [Speaker Audio (24kHz PCM)]
                                         │
                              (Async Tool & Transcript Events)
```
- **Latency**: 400ms to 700ms end-to-end.
- **Acoustic understanding**: Hears frustration, sarcasm, background noise, and language switches natively.
- **Single unified stream**: Emits 24kHz audio (`inlineData`), input/output transcriptions, and `toolCall` events over one connection.

### If you keep a cascade: hold the TTS voice steady
A cascade sends one TTS request per sentence, so each sentence is a fresh generation. With Gemini 3.8 TTS:
- Put the accent and character in the voice itself: an Extended Voice Library voice (for example the Indian English `en-in-*` voices from `client.voices.list`) or a Voice design voice. Asking for an accent inside `speech_metadata.style` on every sentence makes the voice wander.
- Keep `style` to short situational delivery: emotion, pitch and pace.
- Do not send one-word sentences ("Namaste.") as their own request; merge them into the next sentence.
- Send as few requests per reply as you can: the model cannot take earlier audio as context, so every request re-derives the voice. Release the first sentence quickly, then send the rest of the reply as one request. Measured: seven requests 0.65 to 0.67 speaker similarity, first sentence then the rest 0.69 to 0.76, one request 0.75 to 0.80.
- When identity matters more than expressiveness, send the plain transcript with no `speech_metadata.style` at all (0.69 to 0.71 against 0.61 to 0.66 with any style string).
- Check results with a speaker-verification model across the sentences of one reply, not only by ear or pitch.

See [Agent Skill §2.C](/gemini-live/gemini-live-skill/) for the full rules and the A/B numbers.

---

## 3. Google ADK (`Runner.run_live`) & LiveKit guardrails

ADK's `Runner.run_live()` wraps `google-genai` `AsyncSession` with session persistence, tracing, and multi-agent orchestration. Before choosing an ADK topology for live voice, account for four architectural constraints:

1. **Prefer inline tool delegation (`mode="single_turn"` or `AgentTool`) over conversational `transfer_to_agent`**:
   - Attaching default conversational `LlmAgent` instances (`mode="chat"`) to `sub_agents=[...]` registers `transfer_to_agent`. In `run_live()`, `transfer_to_agent` cancels any running background or streaming tools, sleeps `1.0 s` (`DEFAULT_TRANSFER_AGENT_DELAY`), closes the active Gemini Live WebSocket, clears `sessionResumption`, opens a fresh WebSocket for the target agent, strips raw audio from history, replays transcripts via `send_client_content`, and may send a `"."` realtime text trigger on Gemini 3.x Live when the last replayed turn is from the user.
   - That socket teardown carries four side effects: (a) `1.5 to 2.0 s` of voice silence (`~4.6 s` of frozen video on avatar streams); (b) server stream-queue overflow (`1011`) when caller mic frames buffered during the `1.0 s` sleep flush in a burst; (c) lost voice context if `input_audio_transcription` or `output_audio_transcription` is set to `None`; and (d) `1011` setup failure if any `mode="chat"` sub-agent uses a non-Live text model (`gemini-3.8-flash`, `gemini-2.5-pro`).
   - Instead, keep one Live root `LlmAgent` holding the WebSocket open and delegate to specialist text or reasoning `LlmAgent` instances via `mode="single_turn"` in `sub_agents=[...]` (which runs inline in the parent session via non-live `run_async` / `generateContent`) or via `AgentTool(sub_agent)` (which runs in an isolated nested runner/session in unary `StreamingMode.NONE`). Neither closes the Live socket. Use `mode="single_turn"`, not `mode="task"`, for text specialists: a `mode="task"` sub-agent under a Live parent still executes in live mode (`run_live`) and requires a Live model.
   - `SequentialAgent` also reconnects per stage (`1.0 s` delay), while `ParallelAgent` and `LoopAgent` raise `NotImplementedError` in `run_live()` and do not accept `mode=`; wrap them in `AgentTool(parallel_agent)` instead.
2. **Mid-call `send_context_update` is not yet wrapped in `run_live()`**:
   - `Runner.run_live()` does not yet expose `AsyncSession.send_context_update(system_instruction=..., tools=...)` (see [Dynamic Prompt Cards](/gemini-live/optimization/prompt-cards/)). If your call flow swaps phase instructions and tool declarations mid-call with zero audio gap, drive `google-genai >= 2.32.0` `AsyncSession` directly or keep one ADK Live root agent with compact state-gated tools.
3. **Use `LiveKitRunner` (or anti-aliased `16 kHz` WebRTC tracks) instead of naive PCM stride slicing**:
   - Browser and mobile apps over raw WebSockets lack WebRTC jitter buffers and packet-loss concealment. ADK includes an experimental `LiveKitRunner` and `LiveKitToolset` (`pip install "google-adk[livekit]"`, `from google.adk.integrations.livekit import LiveKitRunner`), where LiveKit resamples inbound audio on subscribe (`rtc.AudioStream(track, sample_rate=16000, num_channels=1)`).
   - Avoid older sample bridges that step through `48 kHz` WebRTC frames every 3rd sample (`6`-byte stride) without a `<8 kHz` low-pass filter (which folds `8 to 24 kHz` speech harmonics into metallic aliasing) or hardcode `thinking_budget=0` on Gemini 3.x Live. Keep `RunConfig(save_live_blob=False)` on long calls unless backed by Cloud Storage (enabling `save_live_blob=True` against `InMemoryArtifactService` retains every turn's audio in process memory, despite a stale note in ADK's LiveKit README suggesting `save_live_blob` drains inbound audio).
4. **Vertex AI Agent Engine (`AdkApp`) requires the experimental preview wrapper for `bidi_stream_query`**:
   - Standard `vertexai.agent_engines.templates.adk.AdkApp` registers unary/SSE methods only (`bidi_stream_query not found`). Bidirectional streaming on Agent Engine requires `vertexai.preview.reasoning_engines.AdkApp` with `AgentServerMode.EXPERIMENTAL`. For production WebRTC rooms or SIP trunks, host `LiveKitRunner`, Pipecat, or FastAPI + `Runner.run_live()` directly on Cloud Run (`--timeout=3600 --session-affinity`) or GKE.

See [Troubleshooting -> Framework & multi-agent orchestration issues](/gemini-live/troubleshooting/#6-framework--multi-agent-orchestration-issues-adk--livekit) for quick symptom-to-fix lookups.

---

## 4. When a hybrid pipeline still makes sense

While native Speech-to-Speech is the default for 90% of conversational voice agents, two specialized scenarios justify a hybrid or sidecar architecture:

1. **Strict pre-speech compliance filtering**: If a regulated financial or healthcare environment requires inspecting and redacting the exact text transcript *before* the first millisecond of audio is played to the user, you can either use [Pre-speech compliance guardrails (200ms jitter buffer)](/gemini-live/optimization/#pre-speech-compliance-guardrails-200ms-jitter-buffer) on the native stream, or run Gemini Live in `TEXT` output modality paired with an ultra-low-latency streaming TTS.
2. **Custom cloned brand voices**: If your application mandates a bespoke voice clone not available in the 30+ prebuilt Gemini HD voices, configure `responseModalities: ["TEXT"]` on Gemini Live (preserving native audio input understanding and VAD) and pipe the text output stream into your custom TTS synthesizer.
