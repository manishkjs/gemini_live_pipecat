---
title: Troubleshooting
description: Close codes, audio-format mismatches, and the silent model fallback.
---

The most common production issues and how to read them.

## WebSocket close codes

| Code | Meaning | Resumable? |
| --- | --- | --- |
| `1000` | Normal closure | Yes — reconnect with your resumption handle |
| `1006` | Abnormal closure (network drop) | Yes — reconnect and replay |
| `1007` | Invalid frame payload (e.g., modality violation) | No — fix your config |
| `1008` | Policy violation (e.g., not permitted) | No — fix your request/access |

Treat `1000`/`1006` as **transient** and recover automatically. Treat
`1007`/`1008` as **bugs in your setup** — do not retry blindly.

## The connection closes right after `setup`

Almost always an invalid `setup` frame. Check:

- **Voice name** — case-sensitive; an unknown name closes the socket.
- **Model name** — a typo or an unavailable model.
- **Modalities** — requesting an unsupported combination.

## "It works, but the model seems wrong"

Some backends **silently fall back** to a default model when you request one that
is not on their allowlist. If responses do not match the model you think you
selected, log the **effective** model the server actually used, not the one you
requested.

## Audio sounds sped up or slowed down

A **sample-rate mismatch**. Input must be 16 kHz; output is 24 kHz. If you play
24 kHz audio at 16 kHz (or vice versa) it will sound wrong. Resample explicitly.

## The agent talks over the user

Your client is not honoring **`interrupted`**. On that signal, immediately flush
all buffered-but-unplayed audio.

## Nothing happens after connecting

You are probably sending audio **before `setupComplete`**. Gate all sends on the
handshake acknowledgement.

## First turn is silent or cut off

Check your **jitter buffer** and greeting logic. If you play audio the instant the
first chunk arrives, network unevenness causes choppiness; if your buffer is too
deep, the first response feels delayed.
