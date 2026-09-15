---
title: Choosing a framework
description: Raw WebSocket, Pipecat, or LiveKit, and when to put a WebRTC media server in front of any of them.
---

There are three credible ways to build a Gemini Live backend. The right answer
depends far more on your team and scale than on the technology.

## The decision matrix

| | Raw WebSocket | Pipecat | LiveKit Agents |
| --- | --- | --- | --- |
| Architecture | Direct socket proxy | Linear frame-processing pipeline | Room / WebRTC SFU mesh |
| Latency | Lowest (zero abstraction tax) | Low (~10–20 ms frame queue) | Low (SFU overhead) |
| Observability | Bring your own (OpenTelemetry, Cloud Logging) | Visual local debugger + CLI tail | Hosted insights, audio/log replay |
| Scaling | GKE HPA on active-socket metrics | Explicit min/max agents + idle buffer | Automatic warm pools |
| You own | Everything | Pipeline stages | Almost nothing |
| Best for | >1,000 concurrent calls, latency-critical, strong infra team | Startups, custom frame transforms, lean teams | Enterprise turnkey, multi-party rooms, zero-ops |

## How to choose

Raw WebSocket is the choice when latency is the product and you have infrastructure
engineers. You get zero abstraction tax and total control, and you personally own
session resumption, reconnection, buffering, and backpressure. That state machine
is real work.

Pipecat fits when you want the pipeline handled but still need to reach in.
Frame processors compose cleanly, the local debugger is very good, and
swapping a cascade stage is a one-line change. This is the sweet spot for most
teams building a custom voice product.

LiveKit Agents fits when you need multi-party rooms, want scaling and compliance
handled, or simply do not want to operate this. You trade some control for a lot
of operational burden disappearing.

:::tip[The honest default]
If you are one team shipping one voice product, start with a framework. Move to
raw WebSocket only when you can name the specific milliseconds you are buying.
:::

## When you need a WebRTC media server

Plain WebSockets carry audio fine. They do not give you adaptive bitrate,
jitter buffering, packet-loss concealment, or simulcast, all of which matter the
moment video or screen sharing enters the picture, or when users are on mobile
networks.

Put an SFU in front:

```text
Client (WebRTC) ⟷ SFU media proxy ⟷ Your backend (WebSocket) ⟷ Gemini Live
                  (LiveKit / Daily / aiortc)
```

The SFU absorbs network hostility; your backend keeps a clean, steady PCM stream
to the model.

Reach for this when you have video or screenshare, mobile users on
cellular, multi-party calls, or measurable packet loss. For a desktop-only,
audio-only agent on decent networks, a plain WebSocket plus a good jitter buffer
is enough. See [Audio engineering](/gemini_live_pipecat/audio-engineering/).
## Cascade or native?

Orthogonal to your choice of framework, you must choose between native duplex streaming and a traditional three-stage cascade (Speech-to-Text into an LLM, then into Text-to-Speech).

| Dimension | Native Duplex (Gemini Live) | Cascade (STT -> LLM -> TTS) |
| --- | --- | --- |
| Latency | Low (~550ms to 700ms). Single hop. | Higher (~750ms to 1,100ms). Three serialized services. |
| Scaling & Ops | Simple. 1 model endpoint, 1 quota pool, 1 socket per call. | Complex. 3 distributed services, 3 quota pools, stacked tail latency. |
| Prosody | Natural. Model hears caller tone, hesitation, and emotion. | Flattened through an intermediate text bottleneck. |
| Interruptions | Native server-side cancellation (`interrupted`). | Manual client orchestration required. |
| Unit Economics | Out of the box, persistent audio tokens compound. Matches cascade cost with 5k compression and JIT cards. | Out of the box, audio is discarded after STT and LLMs cache text prompts at 50% to 75% discounts. |
| Compliance Filtering | Requires a 200ms playout jitter buffer checking concurrent text streams before audio plays. | Text is inspected between LLM generation and TTS synthesis. |
| Custom Voices | Built-in HD voice library. | Any external TTS provider or custom voice clone. |

Native audio is the right default for interactive conversational agents. Managing autoscaling, rate limits, and tail latency across three separate services in a cascade creates significant operational overhead during traffic spikes.

### Porting Cascade Advantages into Gemini Live

Enterprise architects often gravitate toward cascades because STT discards audio immediately and LLMs cache static system instructions. You do not need to sacrifice native prosody or manage three models to get those economics:

1. Ephemeral audio via 5k compression: Configure `trigger_tokens: 5000` in Gemini Live to aggressively flush older caller audio turns from the context window. This mimics the ephemeral audio behavior of an STT pipeline while keeping sub-second turn-taking.
2. Zero-cache overhead via JIT Prompt Cards: Instead of loading a monolithic 4,000-token system prompt on Turn 1, start with a 120-token opening card and inject phase-specific instructions only when the caller progresses.
3. Pre-speech compliance guardrails: Gemini Live streams text tokens slightly ahead of audio chunks. Buffer playout by 200ms on the client to run regex or policy checks against the text stream and flush the audio queue before a policy violation ever reaches the speaker.
4. Hybrid dual-engine routing: Use Gemini Live for open conversation, discovery, and objection handling, while routing deterministic steps (DTMF keypad entry, credit card capture, or long regulatory disclaimers) to non-blocking background tools or lightweight workers. See [Optimization patterns](/gemini_live_pipecat/optimization/) for implementation details.

:::note
Native audio models cannot return text-only output so you can feed your own TTS.
Requesting `["AUDIO", "TEXT"]` as response modalities closes the connection with
`1007`. If you require a custom third-party TTS voice, run a cascade pipeline.
:::
