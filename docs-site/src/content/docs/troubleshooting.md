---
title: Troubleshooting
description: Close codes, self-interruption loops, duplicate greetings, and the interrupted-introduction recovery protocol.
---

The most common production issues and how to read them.

## WebSocket close codes

| Code | Meaning | Resumable? |
| --- | --- | --- |
| `1000` | Normal closure | Yes — reconnect with your resumption handle |
| `1006` | Abnormal closure — no clean handshake | Yes — reconnect and replay |
| `1007` | Invalid frame payload (modality violation, bad voice name) | No — fix your config |
| `1008` | Policy violation **or routine session rotation** | **It depends — read below** |
| `1011` | Server-side error | Yes — retry with backoff |

:::caution[`1008` means two completely different things]
- **Routine rotation.** The server ends sessions roughly every **10–15 minutes**.
  It emits a `sessionResumptionUpdate` first, *then* closes with `1008`. This is
  expected. Reconnect with the handle and replay unconfirmed messages.
- **Genuine policy violation.** The model is gated on your surface, or your
  project lacks access. No amount of retrying will help.

**How to tell them apart:** if you received a resumption update shortly before
the close, it was rotation. If the socket died on the very first turn, it is
access. Treating rotation as fatal makes every long call look broken; treating
gating as transient produces an infinite reconnect loop.
:::

## The connection closes right after `setup`

Almost always an invalid `setup` frame. Check, in this order:

- **Voice name** — case-sensitive. `Aoede` works; `aoede` closes the socket.
- **Response modalities** — `["AUDIO", "TEXT"]` is invalid and returns `1007`.
  Use `["AUDIO"]` plus output transcription.
- **Model name** — a typo, or a model not available in your project or region.
- **Model path form** — Vertex requires the full
  `projects/…/locations/…/publishers/google/models/…` path, not a bare name.

## `1006` immediately, with no server response

The WebSocket **upgrade** never completed. The model never saw you.

- **Proxies and web-preview URLs** frequently drop WS upgrades. If you are
  developing on a remote VM, forward the port over SSH and hit `localhost`
  instead of the proxy hostname:

  ```bash
  ssh -L 7860:localhost:7860 user@your-dev-vm
  ```

- **Mixed content** — an HTTPS page cannot open a `ws://` socket. It must be
  `wss://`.
- **Missing auth header** — a bearer token in a query string where the server
  expects a header fails at upgrade time.

## The agent interrupts itself in a loop

Speaker output is bleeding into the microphone, so server VAD "hears the user"
the moment the agent speaks.

1. Enable **`echoCancellation: true`** in `getUserMedia`. This fixes it the vast
   majority of the time.
2. Test with headphones — if the loop disappears, it is confirmed acoustic echo.
3. Lower VAD sensitivity to `LOW` on both start and end of speech.

See [Audio engineering](/gemini_live_pipecat/audio-engineering/).

## The agent greets you twice, or talks over itself at the start

You are emitting the opening turn twice. In frameworks with a context aggregator,
pushing **both** a context frame and a run frame produces two parallel
generations — the aggregator already emits context when the run frame arrives.

Push **only** the run frame to trigger the greeting.

## The user interrupts the introduction and never hears it

By default the model resumes from where it was cut off, so a user who barges in
during the opening greeting never learns who they are talking to. Fix it in your
application, with a one-shot latch:

```python
introduction_complete = False
introduction_restart_injected = False   # single-shot: prevents a greeting loop
cumulative_output_text = ""
```

1. Append every output-transcription fragment to `cumulative_output_text`. When
   the intro's closing phrase appears (for example *"how can I assist you
   today"*), set `introduction_complete = True`.
2. On `interrupted`, if the introduction never completed and you have not already
   injected a restart, send a hidden context turn asking the model to deliver the
   full introduction again — then set the latch.
3. Never inject more than once. Without the latch, a user who interrupts twice
   traps the agent in a greeting loop.

## "It works, but the model seems wrong"

Some backends **silently fall back** to a default model when you request one that
is not on their allowlist. Log the **effective** model the server used, not the
one you asked for.

Related: if you are on public AI Studio and the newest Live models close with
`1008`, they are experiment-gated there. Move to Vertex AI.

## Audio sounds sped up or slowed down

A **sample-rate mismatch**. Input must be 16 kHz; output is 24 kHz. Playing one
at the other's rate produces chipmunks or a slow drawl. Resample explicitly, and
verify each direction independently.

## The agent talks over the user

Your client is not honoring **`interrupted`**. On that signal, immediately flush
all buffered-but-unplayed audio. Note that `generationComplete` is *not* the same
signal — the model has stopped generating, but your queue may still hold seconds
of audio.

## Nothing happens after connecting

You are probably sending audio **before `setupComplete`**. Gate all sends on the
handshake acknowledgement.

## First turn is silent or choppy

Check your **jitter buffer**. Playing the first chunk instantly gives the lowest
latency and the worst smoothness; too deep a buffer makes the first response feel
sluggish. Queue a few chunks, then play at a steady cadence.

## Your latency numbers look impossibly good

If STT latency reads around **2 ms**, you are measuring the audio frame interval,
not speech latency. See [the 2 ms
trap](/gemini_live_pipecat/latency-and-telemetry/#the-2-ms-trap).

## Long sessions crash or degrade

Enable **context window compression**. Without it, a long call eventually
overflows the context window. Also confirm session resumption is actually
implemented — not just enabled in `setup`.
