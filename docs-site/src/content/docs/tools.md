---
title: Tools & function calling
description: Synchronous vs. non-blocking function calls, and cancellation on barge-in.
---

Tools let the model take actions — look up an order, book a slot, query a
balance. In a **voice** agent, how you run tools decides whether the
conversation feels alive or frozen.

## The basic loop

1. Declare functions in the `setup` frame's `tools`.
2. The model emits a **`toolCall`** with a function name, arguments, and an `id`.
3. You execute the function.
4. You return a **`toolResponse`** whose `id` matches the originating call.

## Blocking vs. non-blocking

A slow tool (a network call, a database query) is the enemy of natural
conversation.

- **Blocking:** the agent goes silent until the tool returns. For anything slower
  than a few hundred milliseconds, this feels broken.
- **Non-blocking:** the agent keeps the conversation alive ("let me check that for
  you...") while the tool runs in the background, then folds the result in when it
  is ready.

:::tip[Design for non-blocking]
Speak a natural filler acknowledgement immediately, run the tool asynchronously,
and deliver the result when it arrives. Never let the audio stream go silent
waiting on I/O.
:::

## Cancellation on barge-in

If the user interrupts while a tool is still running, the server sends
**`toolCallCancellation`** with the affected call `ids`.

- **Stop** the in-flight work for those ids.
- **Do not** send a `toolResponse` for a cancelled id. A late response for a
  cancelled call corrupts server-side state and breaks the next turn.

## Common failure modes

- **Mismatched ids** — always echo the exact `id` from the `toolCall`.
- **Responding to cancelled calls** — drop them silently.
- **Serial tool execution** — run independent tools concurrently so one slow call
  does not stall the others.
- **Silent gaps** — always cover tool latency with speech or an earcon.
