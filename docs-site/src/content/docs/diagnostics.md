---
title: Diagnostics
description: Measure latency, capture recent events, and observe a live voice session.
---

You cannot improve what you do not measure. Voice quality is dominated by
**latency** and **turn-taking**, so instrument those first.

## Measure latency per stage

End-to-end "response time" hides where the time goes. Break it down:

| Stage | What it measures |
| --- | --- |
| **STT** (cascade) | Speech to finalized transcript |
| **LLM** | Transcript to first generated token |
| **TTS** (cascade) | Text to first audio chunk |
| **Time to first audio** | User stops speaking to first bot audio (the number users feel) |

For native audio, the single number that matters most is **time from end of user
speech to first bot audio chunk**.

:::note
Client-observed "response time" (from finalized user transcript to first received
audio) is not the same as server time-to-first-byte. Be explicit about which one
a metric represents.
:::

## Capture a rolling event buffer

Keep the **last N events** (frames sent/received, turn signals, tool calls,
errors) in an in-memory ring buffer. When something goes wrong mid-call, you can
dump the buffer and see the exact sequence that led there — without drowning in
full-session logs.

## Track token and duration usage

The server reports `usageMetadata` per turn: token counts and audio/video
durations. Aggregate these to understand cost per conversation and to catch
runaway context growth.

## What to watch in production

- **First-audio latency** distribution (p50/p95), not just the average.
- **Interruption handling** — did queued audio actually stop on `interrupted`?
- **Reconnect frequency** — frequent `goAway`/drops point to network or config
  issues.
- **Tool latency** — slow tools are the usual cause of awkward silences.
