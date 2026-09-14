---
title: Configuration reference
description: The wire envelopes, the setup frame, and every session option — one page to bookmark.
---

This is the **lookup page** — every WebSocket frame, every `setup` field, and every
session option in one place. For the tutorial framing, see
[Getting started](/gemini_live_pipecat/getting-started/); for the concurrency model
behind these frames, see [Architecture](/gemini_live_pipecat/architecture/).

## The message envelopes

Every frame carries exactly one typed object. `setup` is the only frame you send
before the handshake completes; everything else follows `setupComplete`.

### Client → server

| Frame | When you send it | Enters history? |
| --- | --- | --- |
| `setup` | **First frame only**, alone, before anything else | — |
| `clientContent` | Turn-based input you want remembered; also interrupts output | Yes |
| `realtimeInput` | Continuous audio/video/text stream | No |
| `toolResponse` | The result of a function the model asked you to run | — |

### Server → client

| Frame | What it tells you | Act on it by |
| --- | --- | --- |
| `setupComplete` | Handshake acknowledged | Start sending input |
| `serverContent` | Streamed output + turn signals (`generationComplete`, `turnComplete`, `interrupted`) | Play audio; on `interrupted`, flush the queue |
| `toolCall` | The model wants a function run | Execute it, reply with `toolResponse` |
| `toolCallCancellation` | Cancel a pending tool call (e.g. after barge-in) | Abort that call if you can |
| `usageMetadata` | Token + duration accounting for the turn | Record it for cost and context tracking |
| `goAway` | The connection will close soon | Reconnect with your resumption handle |
| `sessionResumptionUpdate` | A fresh handle + last confirmed message index | Store the handle; drop buffered messages up to that index |

:::tip[realtimeInput vs clientContent]
The distinction people get wrong most. Mic audio goes on `realtimeInput`
(continuous, not stored). Deliberate turns you want remembered go on
`clientContent` (and they interrupt the model). Sending mic audio as
`clientContent` interrupts constantly and bloats context. See
[Architecture](/gemini_live_pipecat/architecture/#two-input-channels-do-not-confuse-them).
:::

## The `setup` frame

Declared once, at session start. Most fields are **immutable for the life of the
session** — to change them, tear down the socket and open a new one.

| Field | Sets | Notes |
| --- | --- | --- |
| `model` | The Live model | Vertex needs the full `projects/…/locations/…/publishers/google/models/…` path |
| `systemInstruction` | The agent's behavior | **Immutable.** No update frame exists |
| `generationConfig.responseModalities` | `["AUDIO"]` **or** `["TEXT"]` | Never both — `["AUDIO","TEXT"]` closes with `1007` |
| `generationConfig.speechConfig` | Voice + language | Voice names are **case-sensitive** |
| `tools` | Function declarations | See [Tools & function calling](/gemini_live_pipecat/tools/) |
| `realtimeInputConfig.automaticActivityDetection` | VAD behavior | Sensitivity, silence window, prefix padding |
| `outputAudioTranscription` | Text alongside audio | `{}` to enable |
| `inputAudioTranscription` | Transcript of user speech | `{}` to enable |
| `sessionResumption` | Transparent reconnects | `{}` to enable; see [Architecture](/gemini_live_pipecat/architecture/#session-resumption) |
| `contextWindowCompression` | Auto-trim long sessions | Lossy by default — see [Optimization patterns](/gemini_live_pipecat/optimization/) |

For a complete minimal `setup` payload with real values, see
[Getting started → the raw protocol](/gemini_live_pipecat/getting-started/#4-what-the-raw-protocol-looks-like).

## Voices and language

- **Voice** — a prebuilt voice name in `speechConfig`. Names are **case-sensitive**; an invalid one closes the connection during setup.
- **Language** — set the output language with a BCP-47 code (`en-US`, `hi-IN`, …).
- Native audio is **single-speaker**.

## Voice-activity detection (VAD)

Automatic VAD is on by default — the server decides when the user starts and stops
speaking. Tunable under `realtimeInputConfig.automaticActivityDetection`:

| Knob | Effect | Field-tested default |
| --- | --- | --- |
| `startOfSpeechSensitivity` | How eagerly speech onset triggers | `START_SENSITIVITY_LOW` |
| `endOfSpeechSensitivity` | How eagerly a pause ends the turn | `END_SENSITIVITY_LOW` |
| `silenceDurationMs` | Silence before the turn is considered done | `1200` |
| `prefixPaddingMs` | Audio retained before detected onset | Tune to taste |

Or switch to **manual** activity signaling if your client already knows when the
user is talking.

## Response modalities

A session returns **either audio or text**, not both as audio. Request the one you
need in `generationConfig.responseModalities`. For a live transcript alongside
audio, enable transcription — do **not** add `TEXT` as a second modality.

## Transcription

Enable `inputAudioTranscription` and/or `outputAudioTranscription` in `setup`.
Transcripts stream in fragments with a `finished` flag — append fragments until
`finished` is true, then close that line.

## Native options worth knowing

| Option | Why it matters |
| --- | --- |
| **Media resolution** | Lower resolution for video/screenshare frames cuts input token cost |
| **Context window compression** | Compresses older context so long sessions do not overflow — [tune it carefully](/gemini_live_pipecat/optimization/) |
| **Thinking budget** | Set to zero to disable "thinking" tokens for the lowest latency and cost |

:::note
Field names on the wire are camelCase (`responseModalities`); the Python SDK
exposes snake_case equivalents (`response_modalities`). This page uses the wire
names — see [Getting started](/gemini_live_pipecat/getting-started/) for the SDK forms.
:::
