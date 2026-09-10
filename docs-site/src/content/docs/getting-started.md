---
title: Getting started
description: Prerequisites, endpoints, and your first end-to-end Gemini Live voice turn.
---

This guide takes you from zero to a working voice turn: open a session, send
audio, and receive spoken audio back.

## Prerequisites

- A **Google Cloud project** with the Vertex AI API enabled, **or** a
  **Google AI Studio** API key for prototyping.
- Ability to open a **WebSocket** connection from your backend (Gemini Live is a
  streaming API, not request/response).
- An audio path that can capture **16 kHz PCM** input and play **24 kHz PCM**
  output.

## Choose an access surface

| Surface | Auth | Best for |
| --- | --- | --- |
| **Vertex AI** | OAuth bearer token (ADC / service account) | Production, enterprise controls |
| **AI Studio** | API key | Prototyping, quick starts |

## The connection lifecycle

Every Gemini Live session follows the same shape:

1. **Open** a WebSocket to the Live endpoint.
2. **Send `setup`** as the very first message (model, system instruction, voice,
   modalities). Send nothing else until the server acknowledges.
3. **Wait for `setupComplete`.** This is your green light.
4. **Stream input** — microphone audio as continuous `realtimeInput`.
5. **Receive output** — audio chunks, transcripts, and turn signals in
   `serverContent`.
6. **Handle turn end and interruptions**, then repeat.
7. **Reconnect** gracefully when the server signals `goAway` or the socket drops.

```text
client ──setup──────────────▶ server
client ◀──setupComplete────── server
client ──realtimeInput(audio)▶ server   (continuous)
client ◀──serverContent(audio)─ server  (continuous)
```

:::caution[Gate every send on `setupComplete`]
Sending audio or content before `setupComplete` arrives is a protocol violation
and will close the connection. Always wait for the acknowledgement first.
:::

## Audio formats that just work

- **Input:** 16 kHz, 16-bit, mono PCM.
- **Output:** 24 kHz, 16-bit, mono PCM.

Resample on the client if your capture device uses a different rate. Mismatched
sample rates are the most common cause of "it sounds like chipmunks / slow
motion."

## Next steps

- [Architecture](/gemini_live_pipecat/architecture/) — understand turns,
  interruptions, and resumption before you build.
- [Gemini Live configuration](/gemini_live_pipecat/gemini-live-configuration/) —
  the full `setup` frame and every option.
- [Voice playground](/gemini_live_pipecat/voice-playground/) — try it without
  writing code.
