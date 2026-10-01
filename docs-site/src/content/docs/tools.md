---
title: Tool Calling & Async Orchestration
description: Asynchronous tool calling, non-blocking execution, and state orchestration in Gemini Live.
---

In standard HTTP request-response models, the model stops generating when it calls a tool, waits for the API response, and then continues. 

In **Gemini Live**, the session is a continuous, real-time audio stream. When the model decides to call a tool, **the audio stream does not pause**. The user can keep speaking while your backend executes the function.

---

## 1. The async tool lifecycle

1. **Tool declaration**: You pass function schemas (`functionDeclarations`) in the initial `setup` message.
2. **Tool call (`serverContent` / `toolCall`)**: The model emits a `toolCall` message containing one or more `functionCalls`, each with a unique `id`, `name`, and `args`.
3. **Speech overlap**: Often, the model will say *"Let me check that for you"* right before or while emitting the `toolCall`, and the user might immediately add *"Oh, and make sure it's for tomorrow."*
4. **Tool response (`toolResponse`)**: Your backend executes the API/database query and sends back a `toolResponse` matching the `id`.

```python
from google.genai import types

# Sending the tool result back over the active session
await session.send(
    input=types.LiveClientToolResponse(
        function_responses=[
            types.FunctionResponse(
                id=tool_call.id,
                name=tool_call.name,
                response={"result": {"status": "confirmed", "order_id": "ORD-9921"}}
            )
        ]
    )
)
```

---

## 2. Controlling response scheduling (`SILENT`, `INTERRUPT`, `WHEN_IDLE`)

When a background tool finishes and returns data to the model, you can control how and when the model speaks the result using `FunctionResponseScheduling` inside `FunctionResponse`:

| Scheduling Mode | Behavior | Best Use Case |
| :--- | :--- | :--- |
| **`WHEN_IDLE`** *(Default)* | Waits until the model finishes its current utterance (and the user is not speaking) before speaking the tool result. | Standard customer lookups (order status, account balance, flight search). |
| **`INTERRUPT`** | Immediately interrupts whatever the model is currently saying to announce the tool result. | Urgent alerts, safety guardrails, or payment failures that invalidate the current speech. |
| **`SILENT`** | Appends the tool output to the conversation context silently without triggering a spoken response. | Background CRM prefetching, state updates, or logging where the model only needs the data for future turns. |

```python
from google.genai import types

await session.send(
    input=types.LiveClientToolResponse(
        function_responses=[
            types.FunctionResponse(
                id=tool_call.id,
                name="prefetch_customer_profile",
                response={"tier": "Platinum", "open_tickets": 1},
                scheduling=types.FunctionResponseScheduling.SILENT,
            )
        ]
    )
)
```

---

## 3. Preventing silent tool hangs (the filler pattern)

If a backend tool takes 2 to 4 seconds to execute (such as querying a legacy ERP or running a credit check), dead air on a phone call makes the user think the line dropped.

Instruct the model in your system prompt to always emit a brief conversational filler **before** or **during** slow tool calls:

```markdown
# Tool Execution Behavior
Whenever you invoke `lookup_order_status` or `verify_identity`, always say a brief, natural acknowledgment first (for example, "One moment while I pull up your order.") so the caller is not left in silence.
```

---

## 4. Handling user barge-in during tool execution (the AntiCancel shield)

A common production failure occurs when:
1. The model calls `create_support_ticket(issue="broken screen")` and says *"I'm creating that ticket for you now."*
2. While the HTTP POST to Zendesk is in flight, the user coughs or says *"Thanks."*
3. VAD triggers an `interrupted: true` event.
4. Naive orchestration frameworks cancel the entire turn task on `interrupted: true`, killing the in-flight HTTP request or dropping the `toolResponse` so the model never learns whether the ticket was created.

### The decoupling rule
Never bind the lifecycle of state-mutating tool executions to the audio playback task.
- **Audio playback task**: Cancel immediately on `interrupted: true`.
- **Tool execution task**: Shield from cancellation (`asyncio.shield()` in Python) so the `toolResponse` is always delivered to the Gemini Live session even if the user barges in mid-sentence.

```python
import asyncio

async def handle_tool_call(session, tool_call):
    # Shield the database/API execution from audio barge-in cancellation
    result = await asyncio.shield(execute_backend_api(tool_call.name, tool_call.args))
    
    # Always deliver the toolResponse so the model's context stays consistent
    await session.send(
        input=types.LiveClientToolResponse(
            function_responses=[
                types.FunctionResponse(
                    id=tool_call.id,
                    name=tool_call.name,
                    response={"result": result}
                )
            ]
        )
    )
```

---

## 5. Grounding tool invocation (`UNMISTAKABLY` pattern)

Audio models occasionally hallucinate tool calls when background noise sounds vaguely like a request, or skip calling a required tool and guess the answer instead.

To make tool triggers deterministic:
1. **Explicit trigger conditions**: In the `description` of your `FunctionDeclaration`, state the exact precondition required before calling the tool.
2. **Required parameter verification**: Instruct the model never to guess IDs, dates, or email addresses.

```python
lookup_order_decl = types.FunctionDeclaration(
    name="lookup_order",
    description=(
        "Fetches real-time order status and tracking details. "
        "Call this tool ONLY after the user has UNMISTAKABLY provided their "
        "6-digit order number. Never guess or fabricate an order number."
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "order_id": types.Schema(
                type="STRING",
                description="The exact 6-digit order number spoken by the user."
            )
        },
        required=["order_id"]
    )
)
```

---

## 6. Multi-agent handoffs (Supervisor pattern)

Rather than stuffing 25 tools and 5,000 tokens of instructions into a single monolithic prompt, use a lightweight **Router / Triage configuration** and swap active instructions when the conversation transitions to a specialized workflow (such as Billing, Technical Support, or Cancellations).

See [Optimization Patterns: Dynamic Prompt Cards & Phase Gates](/gemini_live_pipecat/optimization/#pillar-2-dynamic-prompt-cards--phase-gates-the-silent-conductor) for the full state-machine implementation that keeps active prompt tokens averaging ~500 tokens per turn without dropping the WebSocket connection.
