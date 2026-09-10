---
title: Voice playground
description: Try Gemini Live and the cascade pipeline interactively before writing code.
---

The companion **Voice Studio** demo lets you talk to a live agent in the browser
and compare the two speech architectures side by side.

## Two engines, one UI

| Engine | Pipeline | When to use |
| --- | --- | --- |
| **Gemini Live** | Native speech-to-speech (one model) | Lowest latency, most natural prosody and interruptions |
| **Cascade** | Speech-to-Text -> LLM -> Text-to-Speech | Maximum control over each stage, mix-and-match models |

## Run it locally

```bash
cd demos/voice-studio
npm ci
npm run dev
```

Open the URL printed by Vite. Persona previews run immediately with browser
speech synthesis — no credentials needed. For real audio, point **Settings** at
a running backend.

## Personas

The playground ships with several ready-made agent personas so you can hear how
system instructions shape behavior, tone, and language. Pick one, press start,
and talk — or choose **Custom Agent** and paste your own system instructions.

## Model choices

- **Native audio / Live:** the model handles speech directly.
- **Cascade STT:** streaming transcription models.
- **Cascade LLM:** choose the reasoning model that fits your latency/quality
  budget.
- **Cascade TTS:** native Gemini TTS voices or high-definition neural voices.

:::note
Previews that use browser speech synthesis are clearly labeled and do **not**
represent Gemini's real audio quality or latency. Use a connected backend for an
accurate impression.
:::
