---
title: Configuration reference
description: The wire envelopes, the setup frame, prompting rules for native audio, and every session option in one reference guide.
---

<aside class="one-minute" aria-label="In one minute">
  <div class="one-minute-head">
    <span class="badge badge-blue">In one minute</span>
    <span class="one-minute-audience">For product managers and solution architects</span>
  </div>
  <dl class="one-minute-grid">
    <div class="one-minute-cell"><dt>What this page covers</dt><dd>Every message type and every setting you can send when a call starts, in one reference table.</dd></div>
    <div class="one-minute-cell"><dt>Why it matters</dt><dd>Two of these settings (the instructions and the tool list) can be changed mid-call. Everything else is fixed for the life of the connection, so it has to be right at the start.</dd></div>
    <div class="one-minute-cell one-minute-number"><dt>The number to remember</dt><dd>One frame, called setup, must go first and alone. Everything else waits for the server's acknowledgment.</dd></div>
    <div class="one-minute-cell"><dt>The decision you own</dt><dd>Which settings are standard across your product and which vary per call (voice, language, speech-detection sensitivity, compression).</dd></div>
  </dl>
</aside>

This is the **reference page** for every WebSocket frame, `setup` field, and
session option in one place. For the tutorial walkthrough, see
[Getting started](/gemini-live/getting-started/); for the state machine
behind these frames, see [Architecture](/gemini-live/architecture/).

## The message envelopes

Every frame carries one typed JSON object. `setup` is the only frame sent
before the handshake completes; all other frames follow `setupComplete`.

### Client -> server

| Frame | When you send it | Enters history? |
| --- | --- | --- |
| `setup` | **First frame only**, alone, before anything else | N/A |
| `clientContent` | Explicit turn-based input or context injection; interrupts active output when `turnComplete: true` | Yes |
| `realtimeInput` | Continuous audio, video, or activity signals | Yes (user turns) |
| `toolResponse` | The result of a function the model requested via `toolCall` | Yes |
| `contextUpdate` | Mid-call replacement of `systemInstruction`, the declared `tools`, or both via `session.send_context_update()` (`google-genai >= 2.32.0`; also accepts `context_update` on the wire) | No. It overwrites the setup values in place and invalidates the prefix cache |

### Server -> client

| Frame | What it tells you | Act on it by |
| --- | --- | --- |
| `setupComplete` | Handshake acknowledged (`sessionId` assigned) | Start sending input and log `sessionId` |
| `serverContent` | Streamed output + turn signals (`generationComplete`, `turnComplete`, `interrupted`) | Play audio; on `interrupted`, flush the playout queue. Advance the turn and unmute the mic on `turnComplete`, not `generationComplete` (see below) |
| `toolCall` | The model wants to invoke one or more functions | Execute functions and reply with `toolResponse` |
| `toolCallCancellation` | Cancel in-flight tool calls after user barge-in | Abort matching tool IDs and do not send their responses |
| `usageMetadata` | Token accounting for the turn (`promptTokenCount`, `responseTokenCount`, modality details) | Record once on `turnComplete` for cost and context tracking |
| `goAway` | The connection will close soon (`timeLeft`) | Prepare to reconnect using your latest resumption handle |
| `sessionResumptionUpdate` | A fresh resumption `newHandle` + `lastConsumedClientMessageIndex` | Store the handle; drop buffered messages up to that index |

:::tip[realtimeInput vs clientContent]
Send continuous microphone audio on `realtimeInput`. Reserve `clientContent` for explicit text turns or silent context updates (`turnComplete: false`). Sending microphone audio on `clientContent` interrupts the model on every packet. See [Architecture -> Two input channels](/gemini-live/architecture/#two-input-channels).
:::

## The `setup` frame

Sent once at session start. Most fields last for the life of the socket. Two can change mid-call: `systemInstruction` and `tools`.

| Field | Sets | Notes |
| --- | --- | --- |
| `model` | The Live model identifier | Vertex requires `projects/.../locations/.../publishers/google/models/...` |
| `systemInstruction` | The agent's persona and base rules | Replaceable mid-call: `session.send_context_update(system_instruction="...")` (`google-genai >= 2.32.0`) or `clientContent` with `role="system"` (Vertex AI). Each update replaces the whole instruction and rebuilds the prefix cache, so update at stage transitions rather than on every turn. See [Pillar 2: Dynamic prompt cards](/gemini-live/optimization/prompt-cards/) |
| `generationConfig.responseModalities` | `["AUDIO"]` **or** `["TEXT"]` | Never pass both (`["AUDIO","TEXT"]` closes with code `1007`) |
| `generationConfig.speechConfig` | Prebuilt or replicated voice + BCP-47 language | Voice names are **case-sensitive** (`Aoede`, not `aoede`). Always set `languageCode` explicitly (omitting it on Vertex AI falls back to `en-US`). See [Voices and language](#voices-and-language) |
| `generationConfig.temperature` | Sampling temperature | Leave unset (`1.0`) or keep `0.7` to `1.0` for audio output. Leave `topK` and `topP` unset. See [Sampling](#sampling-for-audio-output) |
| `generationConfig.thinkingConfig` | Reasoning level | Depends on the model. See [Thinking config by model](#thinking-config-by-model) |
| `tools` | Function declarations | Set `behavior: "NON_BLOCKING"` for async tools. Replaceable mid-call with `session.send_context_update(tools=[...])` (or `tools=[]` to clear all tools) in `google-genai >= 2.32.0`. See [Tools & function calling](/gemini-live/tools/) |
| `realtimeInputConfig.automaticActivityDetection` | Server VAD thresholds | Sensitivity, `silenceDurationMs`, `prefixPaddingMs` |
| `outputAudioTranscription` | Text transcript of model speech | `{}` to enable. On Vertex AI, add `languageCodes` (see [Response modalities and transcription](#response-modalities-and-transcription)) |
| `inputAudioTranscription` | Text transcript of user speech | `{}` to enable. On Vertex AI, add `languageCodes` |
| `sessionResumption` | Transparent reconnect across 10 to 15 min rotations | `{}` to enable, or `{"handle": "..."}` when reconnecting |
| `contextWindowCompression` | Sliding-window FIFO token eviction | Set `triggerTokens: 5000`, `slidingWindow.targetTokens: 3500`; see [Optimization patterns](/gemini-live/optimization/) |

For a complete `setup` payload with production values, see [Getting started -> What the raw protocol looks like](/gemini-live/getting-started/#4-what-the-raw-protocol-looks-like).

## Voices and language

- **Prebuilt voice (`voiceName`)**: Pass a prebuilt voice name in `speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName`. Names are **case-sensitive**; an invalid casing closes the connection with `1007` during setup. On 8 kHz telephony trunks (`mulaw`), higher-pitched female voices such as `Aoede` are more prone to dropping into a deeper chest register after nasal fillers or low-energy words; steadier voices such as `Kore` or `Despina` hold their timbre better across 8 kHz downsampling.
- **How `speechConfig.languageCode` selects the studio voice sample**: On the server, the pair `(voiceName, speechConfig.languageCode)` selects a `~224 to 239`-token studio audio recording and places it in `ROLE_SYSTEM` ahead of your `systemInstruction`. Even though consumer documentation notes that native audio models can pick a language automatically, omitting `speechConfig.languageCode` on Vertex AI falls back to the `en-US` studio recording. Passing a bare language code without a region (`"en"`, `"hi"`) or a regional Indic code that has no dedicated prebuilt studio voice entry (`bn-IN`, `gu-IN`, `kn-IN`, `ml-IN`, `or-IN`, `pa-IN`, `as-IN`, `ur-IN`) also falls back to `en-US`.
- **Anchoring Indian and multilingual voices from Turn 1**: Set `speechConfig.languageCode` explicitly to `"en-IN"` (or `"hi-IN"`, `"mr-IN"`, `"ta-IN"`, `"te-IN"`). Setting `"en-IN"` loads the Indian-accented studio voice sample from the first word of Turn 1 while still allowing the model to switch fluidly into Hindi, Hinglish, or regional languages mid-call when the caller speaks them.
- **Custom voice cloning (`replicatedVoiceConfig`)**: When a prebuilt voice does not match your regional accent target, pass `speechConfig.voiceConfig.replicatedVoiceConfig` with a 10 to 20 second clean 24 kHz mono 16-bit PCM (`audio/pcm;rate=24000`) reference clip recorded in the exact target accent and speaking pace. That reference clip replaces the prebuilt voice sample in `ROLE_SYSTEM`.
- **Single-speaker**: Native audio output uses a single voice per session.

## Voice-activity detection (VAD)

Automatic server VAD is enabled by default and configurable under `realtimeInputConfig.automaticActivityDetection`:

| Knob | Effect | Production default |
| --- | --- | --- |
| `startOfSpeechSensitivity` | How eagerly speech onset triggers | `START_SENSITIVITY_HIGH` |
| `endOfSpeechSensitivity` | How eagerly a pause ends the user turn | `END_SENSITIVITY_LOW` |
| `silenceDurationMs` | Silence required before the turn is considered complete | `500` (`350` to `800` depending on workload) |
| `prefixPaddingMs` | How much detected speech the server needs before it commits to start-of-speech. Lower values catch shorter sounds | `200` (keep `200` to `300`) |

If your client manages push-to-talk or custom local endpointing, set `automaticActivityDetection.disabled: true` and send explicit `activityStart` and `activityEnd` signals inside `realtimeInput`.

:::caution[Spelled names and emails need a short `prefixPaddingMs`]
A spoken letter ("S", "A", "C") lasts roughly 250 to 450 ms. With `prefixPaddingMs: 600`, a single letter never reaches the start-of-speech threshold, so letters drop out of names and email addresses spelled one at a time. Keep `prefixPaddingMs` at `200` to `300` ms on any flow that collects spelled input.
:::

### Short backchannels after a barge-in

Callers often say a one- or two-word acknowledgment ("okay", "right", "haan", "ji") while the agent is talking. Server VAD treats that as a barge-in, and the model stops mid-sentence and waits for a real question that never comes. Watch the input transcript right after an `interrupted` event. If it holds one or two words, no digits, and no stop word ("no", "stop", "wait"), send a short user-role text turn that asks for a reply now and tells the model the caller only acknowledged it, so it should resume what it was saying. Anything longer is a real interruption and gets a normal reply.

## Prompting for native audio models

Native speech-to-speech models interpret your `systemInstruction` and `clientContent` directly in the acoustic domain:

1. **Never use square brackets**: Do not place stage directions or tags in square brackets inside `systemInstruction` or `clientContent`. Native audio models either speak bracketed words aloud or shift into exaggerated theatrical prosody. Write natural, unbracketed instructions instead.
2. **Enforce spoken brevity**: Instruct the model to keep replies to **1 to 2 short sentences per turn** (15 to 35 words) and pause to let the caller respond.
3. **Spell out digits and codes individually**: Instruct the model to read confirmation numbers, postal codes, and phone numbers one digit at a time (*"four, two, nine"* instead of *"four hundred twenty-nine"*).
4. **Never inject `clientContent` during active model speech**: Sending a `clientContent` frame while the model is speaking can cut off its current audio turn. Send phase updates inside a blocking tool handler, right before you return the `FunctionResponse`, or after `turnComplete`. See [Prompt engineering -> Steering mid-session](/gemini-live/prompt-engineering/#4-steering-mid-session-system-instruction-cards--short-tool-results).
5. **Keep sampling non-greedy**: See [Sampling for audio output](#sampling-for-audio-output).

For the full list of prompt patterns that break native audio (silence rules, XML tags around spoken lines, non-lexical fillers), see [Prompt engineering -> Acoustic traps](/gemini-live/prompt-engineering/#3-acoustic-traps-that-break-native-audio-sessions).

## Sampling for audio output

Audio tokens need sampling diversity. With greedy decoding (`temperature: 0` or `topK: 1`) or low-temperature sampling (`temperature <= 0.3`), a post-tool reply can get stuck in a ~20-second droning or buzzing loop on `gemini-3.8-live`:

1. **Text and audio finish at different times**: When a tool result contains a long formal string (for example, a person's name followed by a corporate title), the audio head finishes speaking the natural question in ~3 seconds with rising prosody, while the text stream (`outputTranscription`) keeps emitting the remaining title words.
2. **Trailing silence blocks end-of-turn**: While those remaining text tokens flush, the audio head outputs 4 to 5 seconds of near-silence. Because the model's end-of-turn token (`<eos>`) relies on joint text-and-audio token prediction, the model never emits `<eos>` when the text stream ends inside a silent audio window, so `turnComplete` never arrives.
3. **Greedy limit-cycle hum**: With no text tokens left to condition on and `temperature: 0` / `topK: 1` forcing the single highest-probability continuation token at every step, the audio head locks into a self-reinforcing nasal murmur (*"Mmmmm..."*) near the voice's fundamental pitch (~187 to 200 Hz in one measured cloned-voice session) that grows louder for ~20 seconds until the server's turn-length cap cuts it off.

Leave `temperature` unset (default `1.0`) or between `0.7` and `1.0`, and leave `topK` and `topP` unset so the model uses its native sampling distribution. Get consistent wording from your prompt and from concise, conversational `*_say` fields in tool results (without long titles or parenthetical codes), not from greedy sampling.

## Thinking config by model

| Model | What to send | Why |
| --- | --- | --- |
| `gemini-3.8-live` (base) | Omit `thinkingConfig` | The base model does not take `thinkingLevel`. Reasoning is served by the separate `-thinking` model variants |
| `gemini-3.1-flash-live-preview` and other 3.1 thinking models | `thinkingConfig: { "thinkingLevel": "minimal" }` | Lowest reasoning overhead and the fastest first audio byte |
| Gemini 2.5 native audio | `thinkingConfig: { "thinkingBudget": 0 }` to turn reasoning off | 2.5 uses a numeric budget |

Never send the 2.5-style `thinkingBudget: 0` to a Gemini 3.x model. The API rejects a request that carries both fields, and on models that accept the budget alone, multi-step tool calls copy parameters less reliably.

## Turn signals: `generationComplete` vs `turnComplete`

The server generates audio faster than real time (about 4x) and sends `generationComplete` as soon as the last audio chunk is generated, while the caller is still hearing the reply. `turnComplete` arrives when the turn is really over. Advance your state machine, end the turn in your UI, and unmute the microphone on `turnComplete`. Gating on `generationComplete` clips the end of the reply or lets the caller's echo interrupt it.

## Response modalities and transcription

A Live session returns **either audio or text** in `generationConfig.responseModalities`, never both. To receive live text transcripts alongside spoken audio, enable `inputAudioTranscription: {}` and `outputAudioTranscription: {}` in `setup`. Transcripts stream incrementally; accumulate fragments until `finished: true` or `turnComplete`.

**Pin both speech voice locale and transcript languages on Vertex AI.** Keep `speechConfig.languageCode` set to a supported studio voice locale (`"en-IN"`, `"hi-IN"`, `"mr-IN"`, `"ta-IN"`, `"te-IN"`, using `"en-IN"` or `"hi-IN"` as the voice anchor when a caller speaks a regional Indic language without its own prebuilt studio sample), and list the expected spoken languages in `AudioTranscriptionConfig(language_codes=[...])` so transcripts render in the right script instead of drifting into Urdu, Arabic, or Cyrillic script:

```python
from google.genai import types

INDIC_FALLBACK_SPEECH_CODES = {
    "bn-IN", "gu-IN", "kn-IN", "ml-IN", "or-IN", "pa-IN", "as-IN", "ur-IN",
}
target_locale = "bn-IN"  # e.g., Bengali caller on an Indian voice agent
speech_locale = "en-IN" if target_locale in INDIC_FALLBACK_SPEECH_CODES else target_locale
transcript_locales = list(dict.fromkeys(["en-IN", target_locale]))

config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    speech_config=types.SpeechConfig(
        language_code=speech_locale,
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
        ),
    ),
    input_audio_transcription=types.AudioTranscriptionConfig(language_codes=transcript_locales),
    output_audio_transcription=types.AudioTranscriptionConfig(language_codes=transcript_locales),
)
```

`language_codes` works only on Vertex AI. In Google AI Studio (API key) mode, send `AudioTranscriptionConfig()` with no arguments. Some `google-genai` releases raise `ValueError` for `language_codes` in that mode and newer ones pass it through, so do not rely on a client-side error.

:::caution[Never put single letters or digits in a custom vocabulary]
If your speech stack accepts a custom vocabulary or phrase hints, leave out single letters (`A` to `Z`) and single digits (`0` to `9`). They bias recognition toward one-character tokens, so short words get transcribed as letters (the Hindi "जी", *ji*, comes out as "G"). Add whole words and names only.
:::

## Native options for cost and latency control

| Option | Why it matters |
| --- | --- |
| **Media resolution** | Lowering resolution for video or screenshare frames reduces input token consumption. |
| **Context window compression** | Firing sliding-window eviction at `5,000` tokens (`targetTokens: 3500`) flushes stale carried audio (`$3.00/1M` tokens for caller + played model speech) before it compounds across turns. |
| **Thinking level (`minimal`)** | On Gemini 3.1 Flash Live, `thinkingConfig.thinkingLevel: "minimal"` keeps reasoning output tokens (`$4.50/1M`) low and shortens time to first audio while keeping tool calls accurate. Omit `thinkingConfig` on base `gemini-3.8-live` (see [Thinking config by model](#thinking-config-by-model)). |

:::note
Wire protocol fields use `camelCase` (`responseModalities`, `thinkingConfig`), whereas the Python `google-genai` SDK accepts `snake_case` equivalents (`response_modalities`, `thinking_config`).
:::
