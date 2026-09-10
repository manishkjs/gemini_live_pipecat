---
title: Architecture
description: The duplex streaming model, turn lifecycle, interruptions, and session resumption.
---

Gemini Live is **stateful and bidirectional**. Understanding four ideas — the two
input channels, the turn lifecycle, interruptions, and session resumption — is
enough to reason about almost any behavior you will see in production.

## Two input channels (do not confuse them)

| Channel | Purpose | Enters history? | Interrupts model? |
| --- | --- | --- | --- |
| **`realtimeInput`** | Continuous mic/camera stream | No | No |
| **`clientContent`** | Deliberate, turn-based messages | Yes | Yes |

Send live microphone audio as `realtimeInput`. Use `clientContent` only for
explicit turns you want remembered (e.g., injecting a text message). Sending mic
audio as `clientContent` will interrupt the model constantly and bloat context;
sending a real user turn as `realtimeInput` means it is never remembered.

## The turn lifecycle

The server streams output with three distinct signals. They are **not**
interchangeable:

- **`generationComplete`** — the model has finished generating, but buffered
  audio may still be playing on the client.
- **`turnComplete`** — the logical end of the turn.
- **`interrupted`** — the user barged in. Immediately stop and discard any queued
  audio playback.

```text
user speaks ─▶ model generates audio ─▶ generationComplete ─▶ turnComplete
                          │
                 user barges in ─▶ interrupted ─▶ drop queued audio
```

## Interruptions (barge-in)

Natural conversation requires the user to be able to talk over the agent. When
the server detects speech during playback, it sends `interrupted`. Your client
**must** flush the audio it has buffered but not yet played, or the agent will
keep talking over the user. Treat this as a hard, immediate stop.

## Session resumption and message replay

The server may end a session proactively (a `goAway` signal) or the network may
drop. To survive this transparently:

1. **Enable transparent resumption** in `setup`.
2. **Number and buffer** every message you send.
3. The server periodically tells you the **last message index it safely
   received**; discard buffered messages up to that index.
4. On reconnect, open a new socket **with the stored resumption handle**, then
   **replay the remaining buffered messages before sending anything new**.
5. If the handle has expired, start a fresh session.

```text
… ─▶ [msg 7] [msg 8] [msg 9]        (buffered, unconfirmed)
server: "received through 7"        (drop 1–7)
socket drops ─▶ reconnect(handle) ─▶ replay [8][9] ─▶ resume
```

:::tip
If you use a higher-level voice framework, session resumption is usually managed
for you. If you talk to the raw WebSocket, you own this state machine.
:::

## Jitter buffering

Networks deliver audio chunks unevenly. A small **playout buffer** (queue a few
chunks before playing, then play at a steady cadence) smooths this out and
prevents choppy audio — at the cost of a little added latency. Tune the buffer
depth to trade smoothness against responsiveness.
