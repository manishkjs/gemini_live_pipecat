---
title: Gemini Live configuration
description: The setup frame, message envelopes, voices, VAD, modalities, and native options.
---

Everything about a session is declared in the first message — the **`setup`**
frame — and every frame after it is one of a small set of typed envelopes.

## The message envelopes

Each WebSocket frame carries exactly one thing.

**Client to server:**

| Frame | Purpose |
| --- | --- |
| `setup` | First frame only: model, system instruction, tools, voice, config |
| `clientContent` | Turn-based input that builds history and interrupts output |
| `realtimeInput` | Continuous audio/video/text stream (not stored in history) |
| `toolResponse` | The result of a function the model asked you to run |

**Server to client:**

| Frame | Purpose |
| --- | --- |
| `setupComplete` | Handshake acknowledged — you may now send input |
| `serverContent` | Streamed audio/text output plus turn-lifecycle signals |
| `toolCall` | The model requests a function call |
| `toolCallCancellation` | Cancel a pending tool call (e.g., after barge-in) |
| `usageMetadata` | Token and duration accounting for the turn |
| `goAway` | The connection will close soon — reconnect |
| `sessionResumptionUpdate` | A fresh resumption handle and confirmed message index |

## The `setup` frame

Key fields you set once at session start:

- **`model`** — the Live model to use.
- **`systemInstruction`** — the agent's behavior. **Immutable for the session**;
  to change it, tear down and reopen the connection.
- **`generationConfig`** — response modalities, temperature, voice, and more.
- **`tools`** — function declarations the model may call.
- **`realtimeInputConfig`** — voice-activity detection behavior.
- **`sessionResumption`** — enable transparent resumption.
- **`contextWindowCompression`** — automatic context trimming for long sessions.

## Voices and language

- Choose a **prebuilt voice** by name. Voice names are **case-sensitive** — an
  invalid name closes the connection during setup.
- Set the **output language** with a BCP-47 code (for example `en-US`, `hi-IN`).
- Native audio is single-speaker.

## Voice-activity detection (VAD)

By default the server detects when the user starts and stops speaking
(**automatic VAD**). You can tune sensitivity, silence duration, and prefix
padding, or switch to **manual** activity signaling if your client already knows
when the user is talking.

## Response modalities

A session returns **either audio or text**, not both as audio. Request the
modality you need in `generationConfig`. If you need a live transcript alongside
audio, enable **input/output transcription** (see below).

## Transcription

Enable input and/or output transcription in `setup` to receive text alongside
audio. Transcripts stream in fragments with a `finished` flag — append fragments
until `finished` is true, then close that transcript line.

## Native options worth knowing

- **Media resolution** — lower resolution for video/screenshare frames reduces
  input token cost.
- **Context window compression** — automatically compresses older context so long
  sessions do not overflow the window.
- **Thinking budget** — set to zero to disable "thinking" tokens when you want the
  lowest latency and cost.
