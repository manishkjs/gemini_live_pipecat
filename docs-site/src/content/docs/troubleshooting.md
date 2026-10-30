---
title: Troubleshooting & Common Pitfalls
description: Quick diagnosis and fixes for common audio, connection, VAD, accent drift, tool calling, and billing issues in Gemini Live.
---

<aside class="one-minute" aria-label="In one minute">
  <div class="one-minute-head">
    <span class="badge badge-blue">In one minute</span>
    <span class="one-minute-audience">For product managers and solution architects</span>
  </div>
  <dl class="one-minute-grid">
    <div class="one-minute-cell"><dt>What this page covers</dt><dd>A symptom-to-fix table for the problems that come up most: wrong-pitch audio, accent drift, self-interruption, dropped connections, silent tool calls, and surprising bills.</dd></div>
    <div class="one-minute-cell"><dt>Why it matters</dt><dd>Most incidents in the first weeks match one of these rows. Checking here first saves an investigation.</dd></div>
    <div class="one-minute-cell one-minute-number"><dt>The number to remember</dt><dd>The model speaks at 24 kHz and listens at 16 kHz. A mismatch is the most common cause of a voice that sounds slow and deep, or fast and squeaky.</dd></div>
    <div class="one-minute-cell"><dt>The decision you own</dt><dd>Which of these checks go into your launch runbook.</dd></div>
  </dl>
</aside>

Use this symptom-to-fix reference to diagnose common issues during Gemini Live development and production rollout.

---

## 1. Audio & playback issues

| Symptom | Root Cause | Fix |
| :--- | :--- | :--- |
| **Model voice sounds slow, deep, or demon-pitched** | Playing **24kHz** PCM model output through an `AudioContext` or telephony stream configured for **16kHz** or **8kHz**. | Initialize your playback `AudioContext({ sampleRate: 24000 })`, or downsample 24kHz → 8kHz (with an anti-aliasing filter) before sending to PSTN telephony. |
| **Model voice sounds fast or "chipmunk"-pitched** | Playing **24kHz** PCM model output at **44.1kHz** or **48kHz** without resampling. | Explicitly pass `24000` when creating the `AudioBuffer`: `ctx.createBuffer(1, samples.length, 24000)`. |
| **Loud static / white noise instead of speech** | Byte-order (endianness) mismatch or float32 vs. int16 buffer confusion. | Gemini Live sends and receives **16-bit signed little-endian PCM (`int16`)**. Convert `Int16Array` samples to `Float32Array` by dividing by `32768.0` before Web Audio playback. |
| **Model never responds to caller audio** | Sending `audio/webm`, `audio/mp3`, or 8kHz G.711 `mulaw` directly to Gemini Live without transcoding. | Transcode inbound audio to raw `audio/pcm;rate=16000` (16-bit, mono, little-endian) and stream via `sendRealtimeInput`. |

---

## 2. Interruption (barge-in) & VAD issues

| Symptom | Root Cause | Fix |
| :--- | :--- | :--- |
| **Model interrupts itself as soon as it starts speaking** | Acoustic echo: speaker audio is bleeding back into the user's microphone without Echo Cancellation (AEC). | Enable browser AEC (`echoCancellation: true`, `noiseSuppression: true`, `autoGainControl: true`) or test with headphones. |
| **Old audio keeps playing for 2–3 seconds after user barges in** | Client audio queue isn't flushed on `serverContent.interrupted == True`. | Listen for `serverContent.interrupted` and immediately stop/disconnect all scheduled `AudioBufferSourceNode` instances in your playback queue. |
| **Model cuts off the caller mid-sentence when they pause to think** | `endOfSpeechSensitivity` is too high or `silenceDurationMs` is too short. | Increase `silenceDurationMs` to `600`–`800` ms and set `endOfSpeechSensitivity="END_SENSITIVITY_LOW"`. |
| **Model ignores short caller replies like *"Yes"* or *"No"*** | `startOfSpeechSensitivity` is set to `LOW` or `prefixPaddingMs` is too high. | Set `startOfSpeechSensitivity="START_SENSITIVITY_HIGH"` and keep `prefixPaddingMs` at `200` to `300` (higher values drop short words and spelled letters). |

---

## 3. Connection & WebSocket lifecycle errors

| Symptom | Root Cause | Fix |
| :--- | :--- | :--- |
| **WebSocket closes immediately after connecting (`1007` / `1008`)** | Sending `realtimeInput` audio chunks before sending `setup` (or sending `setup` twice), or specifying both `AUDIO` and `TEXT` in `responseModalities`. | Wait for `setupComplete` before streaming audio, and set `responseModalities: ["AUDIO"]` (enable transcripts via `inputAudioTranscription` / `outputAudioTranscription`). |
| **Call drops at ~10 minutes (`goAway` / `1001`)** | Underlying Vertex AI / AI Studio WebSocket connection lifetime limit (~10 minutes). | Enable `sessionResumption` in `LiveConnectConfig`, store the latest `sessionResumptionUpdate.newHandle`, and reconnect automatically when `goAway` arrives. |
| **Call terminates at 15 minutes even with `sessionResumption`** | Uncompressed audio sessions have a hard 15-minute context ceiling. | Enable `contextWindowCompression` (`SlidingWindow`) in `LiveConnectConfig` to allow unlimited session duration. |

---

## 4. Prompting, tool calling & cost anomalies

| Symptom | Root Cause | Fix |
| :--- | :--- | :--- |
| **Model reads stage directions aloud (e.g., *"laughs"*, *"pause"*)** | Using square brackets like `[laugh]` or `[SYSTEM UPDATE]` in the prompt or `clientContent`. | Remove all square brackets from prompts and dynamic phase cards; write natural unbracketed guidance instead. |
| **Injecting a `clientContent` message cuts off the model mid-sentence** | A `clientContent` with `turnComplete: true` is a new user turn and interrupts active generation. | Only send `clientContent` after `turnComplete`, or send the update inside a blocking tool handler right before you return the `toolResponse`. |
| **Agent makes 2 to 5 back-to-back tool calls in one turn when a search returns empty** | On `gemini-3.8-live`, returning a bare empty payload (`{"results": []}`) or a contentless stub (`{"status": "OK"}`) causes the model to sweep multiple query variations before speaking. | When a lookup finds no matches, return the structured empty-lookup payload (`{"status": "no_results", "retryable": false, "matches": [], "ask_say": "I couldn't find a match for that name.", "instruction": "No matching records exist. Do not call this tool again with alternate spellings; ask the caller once to clarify."}`) and cap consecutive tool calls in your prompt (see [Tools -> Stop redundant tool sweeps](/gemini-live/tools/#stop-redundant-tool-sweeps-on-empty-lookups-retryable-false)). Keep argument-validation errors (`error` field) retryable once so the model can fix a bad parameter. |
| **Agent enters a ~20-second droning or humming loop right after a tool call** | With greedy decoding (`temperature: 0` or `topK: 1`) or low-temperature sampling (`temperature <= 0.3`), if the spoken question ends early while the text stream keeps flushing a long formal string from a tool result, the audio head emits 4 to 5 seconds of trailing silence. Inside that silent window, the model never emits its end-of-turn token (so `turnComplete` never arrives) and locks into a self-amplifying nasal hum near the voice's fundamental pitch (~187 to 200 Hz in one measured cloned-voice session) until the ~28-second turn limit (see [Sampling for audio output](/gemini-live/gemini-live-configuration/#sampling-for-audio-output)). | Leave `temperature`, `topK`, and `topP` unset (so the model default `temperature: 1.0` applies) or keep `temperature` at `0.7` to `1.0`, and keep `*_say` strings concise so spoken prosody and transcript tokens finish together. |
| **Per-minute cost climbs from `$0.031/min` in Minute 1 to `$0.178/min` in Minute 10** | Quadratic Carried Audio Tax: every turn re-reads all prior audio turns and a large static system prompt. | Implement the [4-Pillar Optimization Architecture](/gemini-live/optimization/) (SlidingWindow + Dynamic Prompt Cards + FactStore Pruning + Cached TTS). |

---

## 5. Voice, accent drift & multilingual stability

Unlike a traditional cascaded pipeline (`STT -> Text LLM -> TTS`) where a separate TTS engine enforces a fixed voice locale on every sentence, Gemini Live generates speech directly as discrete audio tokens (~25 tokens/sec) conditioned on the entire context window. Accent and voice stability therefore depend on both the ~224 to 239-token prebuilt voice sample (or custom reference clip) loaded into `ROLE_SYSTEM` at session start and the text-to-audio balance at the bottom of the prompt on every turn.

| Symptom | Root Cause | Fix |
| :--- | :--- | :--- |
| **Agent starts in an American (`en-US`) accent or drifts to `en-US` on English words** | Each prebuilt voice is backed by locale-specific studio recordings. On Vertex AI (`gemini-3.8-live`), omitting `speechConfig.languageCode`, passing a bare two-letter code (`"en"`, `"hi"`), or passing a regional Indic code without a dedicated studio voice entry (`bn-IN`, `gu-IN`, `kn-IN`, `ml-IN`, `or-IN`, `pa-IN`, `as-IN`, `ur-IN`) causes the server's voice matcher to fall back to the `en-US` studio recording. That `en-US` sample pulls against your text prompt, especially when Turn 0 opens with a text-only greeting trigger and no caller audio. | Set `speechConfig.languageCode` to a supported speech locale (`"en-IN"`, `"hi-IN"`, `"mr-IN"`, `"ta-IN"`, or `"te-IN"`). Setting `"en-IN"` selects the Indian studio voice in `ROLE_SYSTEM` and does not block mid-call switching into Hindi (`hi-IN`), Hinglish, or regional languages. For callers speaking `bn-IN`, `gu-IN`, `kn-IN`, `ml-IN`, `or-IN`, `pa-IN`, `as-IN`, or `ur-IN`, set `speechConfig.languageCode` to `"en-IN"` (or `"hi-IN"`) as the closest Indian acoustic anchor and pass the specific regional locale list in `inputAudioTranscription.languageCodes` and `outputAudioTranscription.languageCodes` (see [Voices and language](/gemini-live/gemini-live-configuration/#voices-and-language)). |
| **Agent speaks with the right accent on Turn 1, then shifts toward a US accent right after a `toolResponse` or RAG lookup** | The ~224 to 239-token prebuilt voice sample sits at the very top of `ROLE_SYSTEM`, while a `FunctionResponse` returned in the current turn lands at the very bottom of `ROLE_USER` right before audio decoding begins. A 300-to-800-word dump of raw English JSON keys and values creates a large text-to-audio token imbalance right at the decode boundary, pulling prosody toward the model's US English text prior. | Keep tool payloads compact (`<60` tokens for `call_state` plus ready-to-say `*_say` / `*_spell` strings), move step instructions into `systemInstruction` via `session.send_context_update()`, and append a one-line `vocal_tone` reminder as the last key of every `FunctionResponse` (listed in your base prompt's never-speak whitelist; see [Tools -> Keep the accent after tool calls](/gemini-live/tools/#keep-the-accent-after-tool-calls-vocal_tone)). |
| **Custom cloned voice (`ReplicatedVoiceConfig`) still drifts in accent mid-call after tool calls** | `ReplicatedVoiceConfig` (`10 to 20 seconds` of 24 kHz mono `s16le` PCM at `audio/pcm;rate=24000`, recorded with `-3 dB to -6 dB` headroom) replaces the prebuilt studio recording in the exact same top-of-preamble `ROLE_SYSTEM` slot. It eliminates the Turn-1 `en-US` catalog fallback, but its reference audio tokens still sit at the top of the context window and are diluted mid-call by heavy English tool dumps at the bottom of the turn. | Pair `ReplicatedVoiceConfig` with the same compact `FunctionResponse` contract and in-band `vocal_tone` anchor used for prebuilt voices, and resample uploaded reference clips to 24 kHz with an anti-aliased polyphase filter (`soxr` or `scipy.signal.resample_poly`). |
| **Agent voice drops into a deep, gravelly chest register mid-call on 8 kHz phone lines** | Certain prebuilt voices (especially `Aoede`, *"Breezy"*) can shift into a lower chest register during long telephony calls when triggered by breathy non-lexical fillers (`"Hmm..."`, `"Umm..."`, `"Uh..."`) or aggressive client-side volume normalization (`30x to 40x` gain) that amplifies quiet breath frames before `24 kHz -> 8 kHz` `mulaw` conversion. | Prefer `Kore` (*Firm*) or `Despina` (*Smooth*) for female regional agents on 8 kHz telephony (`Puck` or `Orus` for male), replace non-lexical fillers with lexical acknowledgments (`"Sure"`, `"Right"`, `"जी"`), cap client-side RMS auto-gain at `4x to 5x`, and use a polyphase anti-aliased resampler (`soxr`) when converting between `8 kHz` and `16 kHz / 24 kHz`. |
| **Speaking pace speeds up noticeably or drops audio output on brand acronyms** | Long uninterrupted replies (over 60 words / 3+ sentences) cause the native-audio decoder to accelerate its speaking rate, and large inline `"Pronounce X as Y"` lookup tables or mid-word mixed-script hyphenation (`"B-E-six-स्पोर्टेक"`) can destabilize or drop audio output. | Keep each spoken turn under 2 to 3 sentences (`<60 words`), remove inline pronunciation lookup tables, and write phonetic spellings for English acronyms directly in place in clean Latin script (`"B-E six Sporteq"`; see [Prompt engineering -> Short turns and phonetic spellings](/gemini-live/prompt-engineering/#b-pair-speechconfiglanguagecode-with-short-turns-60-words-and-in-place-phonetic-spellings)). |
