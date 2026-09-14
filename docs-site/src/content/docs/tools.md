---
title: Tools & function calling
description: Non-blocking tools, the five failure modes that freeze a voice agent, and cancellation on barge-in.
---

Tools let the model take actions — look up an order, book a slot, query a
balance. In a **voice** agent, how you run tools decides whether the conversation
feels alive or frozen.

Text agents can afford a two-second pause. Voice agents cannot: silence on a
phone call reads as a dropped connection.

## The basic loop

1. Declare functions in the `setup` frame's `tools`.
2. The model emits a **`toolCall`** with a function name, arguments, and an `id`.
3. You execute the function.
4. You return a **`toolResponse`** whose `id` matches the originating call.

## Blocking vs. non-blocking

- **Blocking:** the agent goes silent until the tool returns. For anything slower
  than a few hundred milliseconds, this feels broken.
- **Non-blocking:** the agent keeps talking ("let me check that for you…") while
  the tool runs in the background, then folds the result in when it arrives.

:::danger[The schema flag is what counts]
Non-blocking behavior must be declared **in the function schema**:

```python
types.FunctionDeclaration(
    name="fetch_customer_record",
    description="Retrieve merchant account and settlement data.",
    parameters=...,
    behavior=types.Behavior.NON_BLOCKING,   # REQUIRED
)
```

Application-level decorators like `@tool(blocking=False)` only affect **your**
local dispatch. Without the schema flag, the model still treats the call as
blocking and halts speech generation until you respond.
:::

## Make the model cover the gap

Do not synthesize filler by injecting client text. Tell the model to do it, in
the system instruction:

> When calling `fetch_customer_record`, **UNMISTAKABLY** give a short natural
> acknowledgement such as "Let me look that up for you…", then wait for the data.

:::tip[The `UNMISTAKABLY` keyword]
Emphatic, unambiguous trigger language in system instructions measurably reduces
missed and duplicated tool invocations. Vague phrasing ("you may want to call…")
produces models that call tools twice, or not at all.
:::

## Five ways this freezes in production

Each of these presents as "the agent stopped responding," and each has a
different cause.

### 1. The orchestrator batching trap

Multi-tool batching queues typically flush on server `TURN_COMPLETE`. If you
track non-blocking calls in that same turn-level buffer, their results are
trapped waiting for a flush **that never comes** — the turn already ended. The
response sits in memory forever.

```python
async def on_tool_call(self, data):
    config = self.tool_handler.get_config(data.name)
    if config and config.blocking:
        self._current_turn_tool_ids.append(data.id)   # batch ONLY blocking calls
    # Non-blocking calls bypass the turn batch entirely:
    asyncio.create_task(self._run_async_tool(data))
```

### 2. Prompt hijacking / turn collision

Injecting client text with `turn_complete=True` **during** an in-flight tool call
forces the server to abort the active turn. The pending `tool_call.id` is
orphaned, and every later response for it is discarded.

Never do this:

```python
# ❌ aborts the active turn and orphans the tool call
await session.send_client_content(
    turns=[...("Looking it up...")], turn_complete=True
)
```

Let the model speak its own filler instead.

### 3. The `status: "PROCESSING"` anti-pattern

Returning a placeholder response to "keep things moving" **resolves the turn
early**. The model then verbalizes hallucinated progress updates, and treats your
real data — when it finally arrives — as an unrelated user interjection.

Return a `FunctionResponse` exactly once, with the real result.

### 4. Missing schema behavior

Covered above: an undeclared schema defaults to `BLOCKING`. Audit every
declaration.

### 5. Unsupported scheduling policies

`FunctionResponseScheduling` values (`WHEN_IDLE`, `SILENT`, `INTERRUPT`) depend on
backend rollout. Verify support on your surface before depending on them, and
degrade gracefully when unavailable.

## Canonical async dispatch

```python
async def _run_async_tool(self, data) -> None:
    result = await self.tool_handler.execute(data)
    await self.gemini_session.send_tool_response(
        function_responses=[
            types.FunctionResponse(id=data.id, name=data.name, response=result)
        ]
    )
```

One call, one response, dispatched off the turn batch. That is the whole pattern.

## Keep tool surfaces small

Large tool menus cause redundant and incorrect calls. Three rules:

1. **Put deterministic routing in your application**, not in the model. State
   machines belong in Python, not in prose.
2. **Keep system instructions lean** — persona, tone, and safety. Strip
   line-of-business decision trees out of them.
3. **Expose a dynamic allow-list** — only the tools valid for the current
   conversation state.

## Cancellation on barge-in

If the user interrupts while a tool is running, the server sends
**`toolCallCancellation`** with the affected ids.

- **Stop** the in-flight work for those ids.
- **Do not** send a `toolResponse` for a cancelled id. A late response corrupts
  server-side state and breaks the next turn.

## Session identity for tool traces

The Live API mints a **new resumption handle after every turn**, but all of them
map to one immutable **session ID** returned in `setupComplete`.

Index logs, CRM writes, and traces by the **session ID**. Indexing by resumption
handle produces one orphaned trace fragment per turn.

## Common failure modes, condensed

- **Mismatched ids** — always echo the exact `id` from the `toolCall`.
- **Responding to cancelled calls** — drop them silently.
- **Serial execution** — run independent tools concurrently.
- **Silent gaps** — always cover tool latency with speech.
