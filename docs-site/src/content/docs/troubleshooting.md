---
title: Troubleshooting & Common Pitfalls
description: Quick diagnosis and fixes for common audio, connection, VAD, tool calling, and billing issues in Gemini Live.
---

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
| **Model ignores short caller replies like *"Yes"* or *"No"*** | `startOfSpeechSensitivity` is set to `LOW` or `prefixPaddingMs` is too high. | Set `startOfSpeechSensitivity="START_SENSITIVITY_HIGH"` and `prefixPaddingMs=100`. |

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
| **Injecting a `clientContent` message cuts off the model mid-sentence** | A `clientContent` with `turnComplete: true` is a new user turn and interrupts active generation. | Only send `clientContent` after `turnComplete`, or return dynamic guidance inside a `toolResponse` with `scheduling=WHEN_IDLE` or `SILENT`. |
| **Per-minute cost climbs from `$0.031/min` in Minute 1 to `$0.178/min` in Minute 10** | Quadratic Carried Audio Tax: every turn re-reads all prior audio turns and a large static system prompt. | Implement the [3-Pillar Optimization Architecture](/gemini_live_pipecat/optimization/) (SlidingWindow + Dynamic Prompt Cards + FactStore Pruning). |
