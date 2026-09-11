---
title: Optimization patterns
description: Keep long voice sessions cheap and alive — without silently losing the conversation.
---

Long sessions have one enemy: the context window fills up. Audio accrues at
roughly **25 tokens/second**, so an audio-only session reaches the window in about
**15 minutes** and then drops — unless you manage context deliberately.

## The one thing to understand

Gemini Live has exactly one built-in control, **`contextWindowCompression`**, and
it is **not** summarization. It is a **sliding window** that *discards the oldest
turns* once context crosses a threshold:

| Field | What it does | Default |
| --- | --- | --- |
| `triggerTokens` | Compaction fires when context crosses this | ~80% of the window |
| `slidingWindow.targetTokens` | How far it shrinks to when it fires | `triggerTokens / 2` — **drops ~half the conversation** |

System instructions and pinned prefix turns are always kept; everything older is
**FIFO-evicted and gone**. Compaction also causes a brief latency spike — so you
want it to fire *rarely*.

:::danger[The default is maximally lossy]
Enabling compression without setting `targetTokens` means every trigger throws
away half your history. Always set it explicitly.
:::

## Tune the safety net

Keep compression **on** so a session can never hard-overflow — but make it fire
rarely and drop the least when it does (Python SDK; wire names are camelCase):

```python
context_window_compression = {
    "enabled": True,
    "trigger_tokens": 32000,   # fire rarely, not at every small growth
    "target_tokens": 24000,    # when it fires, drop the least — not trigger/2
}
```

## Do the real work client-side (lossless)

The built-in window is a net, not a strategy. These layers *reduce* tokens without
*losing* meaning:

| Lever | Move | Why it works |
| --- | --- | --- |
| **Transcribe, then prune audio** | Drop raw user-audio parts older than ~6 turns; keep their transcript text | Text is several times cheaper than audio and semantically identical — you already have it if input transcription is on |
| **Rolling summary** | Keep a small (<60-token) running digest of salient facts; re-inject each turn with `send_client_content(turn_complete=False)` | The gist survives even after the window evicts turn 1 |
| **Pin what must not vanish** | Put persona and critical facts in `systemInstruction` or prefix turns | The sliding window never evicts these |

:::tip[The mental model]
Leave the sliding window **on** as a safety net, tuned to almost never fire. Let
**transcript-pruning + a rolling summary** do the real, lossless work. That is how
a session stays cheap *and* keeps its memory.
:::
