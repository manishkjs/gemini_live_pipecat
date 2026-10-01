---
title: Orchestration Frameworks
description: Choosing between the Google GenAI SDK, ADK, Pipecat, and LiveKit for Gemini Live applications.
---

When building a Gemini Live application, your first architectural decision is how to connect user devices and telephony trunks to the Gemini Live WebSocket.

---

## 1. Framework comparison matrix

| Framework | Primary Strength | Transport Layer | Best Use Case |
| :--- | :--- | :--- | :--- |
| **Raw `google-genai` SDK** | Zero framework overhead, direct access to every Bidi API field | Custom WebSocket / WebRTC | Custom backend microservices, lightweight integrations, or full control over `sessionResumption` and `contextWindowCompression`. |
| **Google Agent Development Kit (ADK)** | Native multi-agent routing, built-in evaluation & Vertex AI Agent Engine integration | FastAPI WebSocket / WebRTC | Enterprise multi-agent systems deployed on Google Cloud with structured sub-agent handoffs. |
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

---

## 3. When a hybrid pipeline still makes sense

While native Speech-to-Speech is the default for 90% of conversational voice agents, two specialized scenarios justify a hybrid or sidecar architecture:

1. **Strict pre-speech compliance filtering**: If a regulated financial or healthcare environment requires inspecting and redacting the exact text transcript *before* the first millisecond of audio is played to the user, you can either use [Pre-speech compliance guardrails (200ms jitter buffer)](/gemini_live_pipecat/optimization/#pre-speech-compliance-guardrails-200ms-jitter-buffer) on the native stream, or run Gemini Live in `TEXT` output modality paired with an ultra-low-latency streaming TTS.
2. **Custom cloned brand voices**: If your application mandates a bespoke voice clone not available in the 30+ prebuilt Gemini HD voices, configure `responseModalities: ["TEXT"]` on Gemini Live (preserving native audio input understanding and VAD) and pipe the text output stream into your custom TTS synthesizer.
