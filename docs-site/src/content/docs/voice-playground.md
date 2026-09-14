---
title: Voice Studio
description: Talk to a live Gemini agent in your browser and compare native vs cascade — before you write any code.
---

**Voice Studio** is the companion demo in this repo. Talk to a live agent in the
browser and hear the two speech architectures side by side, so you can make the
native-vs-cascade decision with your ears before you commit to code.

## Two engines, one UI

| Engine | Pipeline | When to use |
| --- | --- | --- |
| **Gemini Live** | Native speech-to-speech (one model) | Lowest latency, most natural prosody and interruptions |
| **Cascade** | Speech-to-Text → LLM → Text-to-Speech | Maximum control over each stage; mix and match models |

For the full tradeoff, see
[Choosing a framework → Cascade or native?](/gemini_live_pipecat/frameworks/#cascade-or-native).

## Run it locally

```bash
cd demos/voice-studio
npm ci
npm run dev
```

Open the URL Vite prints. Persona previews run immediately with browser speech
synthesis — no credentials needed. For real Gemini audio, point **Settings** at a
running backend (see [Deployment](/gemini_live_pipecat/deployment/)).

## Personas

Voice Studio ships with ready-made agent personas so you can hear how system
instructions shape behavior, tone, and language. Pick one, press start, and talk —
or choose **Custom Agent** and paste your own system instructions.

## Model choices

- **Native audio / Live:** the model handles speech directly.
- **Cascade STT:** streaming transcription models.
- **Cascade LLM:** the reasoning model that fits your latency/quality budget.
- **Cascade TTS:** native Gemini TTS voices or high-definition neural voices.

:::note
Previews that use browser speech synthesis are clearly labeled and do **not**
represent Gemini's real audio quality or latency. Use a connected backend for an
accurate impression.
:::

## Then build your own

Voice Studio is a reference, not a black box. When you are ready,
[Getting started](/gemini_live_pipecat/getting-started/) takes you from zero to a
working voice turn, and [Architecture](/gemini_live_pipecat/architecture/) explains
the model it is built on.
