---
title: Configuration reference
description: The wire envelopes, the setup frame, prompting rules for native audio, and every session option in one reference guide.
---

This is the **reference page** for every WebSocket frame, `setup` field, and
session option in one place. For the tutorial walkthrough, see
[Getting started](/gemini_live_pipecat/getting-started/); for the state machine
behind these frames, see [Architecture](/gemini_live_pipecat/architecture/).

## The message envelopes

Every frame carries one typed JSON object. `setup` is the only frame sent
before the handshake completes; all other frames follow `setupComplete`.

### Client -> server

| Frame | When you send it | Enters history? |
| --- | --- | --- |
| `setup` | **First frame only**, alone, before anything else | N/A |
| `clientContent` | Explicit turn-based input or context injection; unconditionally interrupts active output | Yes |
| `realtimeInput` | Continuous audio, video, or activity signals | Yes (user turns) |
| `toolResponse` | The result of a function the model requested via `toolCall` | Yes |

### Server -> client

| Frame | What it tells you | Act on it by |
| --- | --- | --- |
| `setupComplete` | Handshake acknowledged (`sessionId` assigned) | Start sending input and log `sessionId` |
| `serverContent` | Streamed output + turn signals (`generationComplete`, `turnComplete`, `interrupted`) | Play audio; on `interrupted`, flush the playout queue |
| `toolCall` | The model wants to invoke one or more functions | Execute functions and reply with `toolResponse` |
| `toolCallCancellation` | Cancel in-flight tool calls after user barge-in | Abort matching tool IDs and do not send their responses |
| `usageMetadata` | Token accounting for the turn (`promptTokenCount`, `responseTokenCount`, modality details) | Record once on `turnComplete` for cost and context tracking |
| `goAway` | The connection will close soon (`timeLeft`) | Prepare to reconnect using your latest resumption handle |
| `sessionResumptionUpdate` | A fresh resumption `newHandle` + `lastConsumedClientMessageIndex` | Store the handle; drop buffered messages up to that index |

:::tip[realtimeInput vs clientContent]
Send continuous microphone audio on `realtimeInput`. Reserve `clientContent` for explicit text turns or silent context updates (`turnComplete: false`). Sending microphone audio on `clientContent` interrupts the model on every packet. See [Architecture -> Two input channels](/gemini_live_pipecat/architecture/#two-input-channels).
:::

## The `setup` frame

Declared once at session start. Most fields are **immutable for the life of the socket connection**.

| Field | Sets | Notes |
| --- | --- | --- |
| `model` | The Live model identifier | Vertex requires `projects/.../locations/.../publishers/google/models/...` |
| `systemInstruction` | The agent's persona and base rules | Immutable on the socket; use [Dynamic prompt cards & phase gates](/gemini_live_pipecat/optimization/#pillar-2-dynamic-prompt-cards--phase-gates-the-silent-conductor) for mid-call phase updates |
| `generationConfig.responseModalities` | `["AUDIO"]` **or** `["TEXT"]` | Never pass both (`["AUDIO","TEXT"]` closes with code `1007`) |
| `generationConfig.speechConfig` | Prebuilt voice + BCP-47 language | Voice names are **case-sensitive** (`Aoede`, not `aoede`) |
| `generationConfig.thinkingConfig` | Reasoning level (`thinkingLevel: "minimal"`) | Minimizes reasoning token overhead and cuts Time-to-First-Audio-Byte |
| `tools` | Function declarations | Set `behavior: "NON_BLOCKING"` for async tools; see [Tools & function calling](/gemini_live_pipecat/tools/) |
| `realtimeInputConfig.automaticActivityDetection` | Server VAD thresholds | Sensitivity, `silenceDurationMs`, `prefixPaddingMs` |
| `outputAudioTranscription` | Text transcript of model speech | `{}` to enable |
| `inputAudioTranscription` | Text transcript of user speech | `{}` to enable |
| `sessionResumption` | Transparent reconnect across 10 to 15 min rotations | `{}` to enable, or `{"handle": "..."}` when reconnecting |
| `contextWindowCompression` | Sliding-window FIFO token eviction | Set `triggerTokens: 5000`, `slidingWindow.targetTokens: 3500`; see [Optimization patterns](/gemini_live_pipecat/optimization/) |

For a complete `setup` payload with production values, see [Getting started -> What the raw protocol looks like](/gemini_live_pipecat/getting-started/#4-what-the-raw-protocol-looks-like).

## Voices and language

- **Voice**: Pass a prebuilt voice name in `speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName`. Names are **case-sensitive**; an invalid casing closes the connection with `1007` during setup.
- **Language**: Configure output language with a BCP-47 code (`en-US`, `en-IN`, `hi-IN`, etc.).
- **Single-speaker**: Native audio output uses a single voice per session.

## Voice-activity detection (VAD)

Automatic server VAD is enabled by default and configurable under `realtimeInputConfig.automaticActivityDetection`:

| Knob | Effect | Production default |
| --- | --- | --- |
| `startOfSpeechSensitivity` | How eagerly speech onset triggers | `START_SENSITIVITY_HIGH` |
| `endOfSpeechSensitivity` | How eagerly a pause ends the user turn | `END_SENSITIVITY_LOW` |
| `silenceDurationMs` | Silence required before the turn is considered complete | `500` (`350` to `800` depending on workload) |
| `prefixPaddingMs` | Audio retained prior to detected speech onset | `200` |

If your client manages push-to-talk or custom local endpointing, set `automaticActivityDetection.disabled: true` and send explicit `activityStart` and `activityEnd` signals inside `realtimeInput`.

## Prompting for native audio models

Native speech-to-speech models interpret your `systemInstruction` and `clientContent` directly in the acoustic domain:

1. **Never use square brackets**: Do not place stage directions or tags in square brackets inside `systemInstruction` or `clientContent`. Native audio models either speak bracketed words aloud or shift into exaggerated theatrical prosody. Write natural, unbracketed instructions instead.
2. **Enforce spoken brevity**: Instruct the model to keep replies to **1 to 2 short sentences per turn** (15 to 35 words) and pause to let the caller respond.
3. **Spell out digits and codes individually**: Instruct the model to read confirmation numbers, postal codes, and phone numbers one digit at a time (*"four, two, nine"* instead of *"four hundred twenty-nine"*).
4. **Never inject `clientContent` during active model speech**: Sending a `clientContent` frame while the model is speaking immediately cuts off its current audio turn. Inject phase updates only after `turnComplete` or inside a `FunctionResponse` with `scheduling=WHEN_IDLE`.

## Response modalities and transcription

A Live session returns **either audio or text** in `generationConfig.responseModalities`, never both. To receive live text transcripts alongside spoken audio, enable `inputAudioTranscription: {}` and `outputAudioTranscription: {}` in `setup`. Transcripts stream incrementally; accumulate fragments until `finished: true` or `turnComplete`.

## Native options for cost and latency control

| Option | Why it matters |
| --- | --- |
| **Media resolution** | Lowering resolution for video or screenshare frames reduces input token consumption. |
| **Context window compression** | Firing sliding-window eviction at `5,000` tokens (`targetTokens: 3500`) flushes stale caller audio (`$3.00/1M` tokens) before it compounds across turns. |
| **Thinking level (`minimal`)** | Setting `thinkingConfig.thinkingLevel: "minimal"` minimizes reasoning token overhead (`$4.50/1M` output tokens) and reduces initial audio latency while preserving tool-calling accuracy. |

:::note
Wire protocol fields use `camelCase` (`responseModalities`, `thinkingConfig`), whereas the Python `google-genai` SDK accepts `snake_case` equivalents (`response_modalities`, `thinking_config`).
:::
