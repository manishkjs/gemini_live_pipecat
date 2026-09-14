---
title: Choosing a framework
description: Raw WebSocket, Pipecat, or LiveKit — and when to put a WebRTC media server in front of any of them.
---

There are three credible ways to build a Gemini Live backend. The right answer
depends far more on your team and scale than on the technology.

## The decision matrix

| | **Raw WebSocket** | **Pipecat** | **LiveKit Agents** |
| --- | --- | --- | --- |
| **Architecture** | Direct socket proxy | Linear frame-processing pipeline | Room / WebRTC SFU mesh |
| **Latency** | **Lowest** — zero abstraction tax | Low (~10–20 ms frame queue) | Low (SFU overhead) |
| **Observability** | Bring your own (OpenTelemetry, Cloud Logging) | Visual local debugger + CLI tail | Hosted insights, audio/log replay |
| **Scaling** | GKE HPA on active-socket metrics | Explicit min/max agents + idle buffer | Automatic warm pools |
| **You own** | Everything | Pipeline stages | Almost nothing |
| **Best for** | >1,000 concurrent calls, latency-critical, strong infra team | Startups, custom frame transforms, lean teams | Enterprise turnkey, multi-party rooms, zero-ops |

## How to choose

**Raw WebSocket** when latency is the product and you have infrastructure
engineers. You get no abstraction tax and total control — and you personally own
session resumption, reconnection, buffering, and backpressure. That state machine
is real work.

**Pipecat** when you want the pipeline handled but still need to reach in.
Frame processors compose cleanly, the local debugger is genuinely good, and
swapping a cascade stage is a one-line change. This is the sweet spot for most
teams building a custom voice product.

**LiveKit Agents** when you need multi-party rooms, want scaling and compliance
handled, or simply do not want to operate this. You trade some control for a lot
of operational burden disappearing.

:::tip[The honest default]
If you are one team shipping one voice product, start with a framework. Move to
raw WebSocket only when you can name the specific milliseconds you are buying.
:::

## When you need a WebRTC media server

Plain WebSockets carry audio fine. They do **not** give you adaptive bitrate,
jitter buffering, packet-loss concealment, or simulcast — all of which matter the
moment video or screen sharing enters the picture, or when users are on mobile
networks.

Put an SFU in front:

```text
Client (WebRTC) ⟷ SFU media proxy ⟷ Your backend (WebSocket) ⟷ Gemini Live
                  (LiveKit / Daily / aiortc)
```

The SFU absorbs network hostility; your backend keeps a clean, steady PCM stream
to the model.

Reach for this when you have **video or screenshare**, **mobile users on
cellular**, **multi-party calls**, or measurable packet loss. For a desktop-only,
audio-only agent on decent networks, a plain WebSocket plus a good jitter buffer
is genuinely enough — see
[Audio engineering](/gemini_live_pipecat/audio-engineering/).

## Cascade or native?

Orthogonal to the framework choice, and worth being deliberate about.

| | **Native audio** | **Cascade (STT → LLM → TTS)** |
| --- | --- | --- |
| **Latency** | Lower — one model, one hop | Higher — three services in series |
| **Prosody** | Natural; hears tone and emotion | Flattened through a text bottleneck |
| **Interruptions** | Handled natively | You orchestrate them |
| **Control** | Voice and persona via config | Swap any stage independently |
| **Custom voices** | Prebuilt voice set | Any TTS voice you can call |
| **Text logging** | Requires transcription config | Transcripts are free — they are the pipeline |

Native audio is the better default for conversational agents. Choose a cascade
when you need a specific TTS voice, a specific reasoning model, or per-stage
control that native cannot give you.

:::note
Native audio models cannot return text-only output so you can feed your own TTS.
Requesting `["AUDIO", "TEXT"]` as response modalities closes the connection with
`1007`. If you need your own TTS, you need a real cascade.
:::
