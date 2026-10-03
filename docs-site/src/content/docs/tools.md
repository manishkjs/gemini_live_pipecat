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

---

## 7. Changing tools and instructions during a call

A call often moves through stages. First you verify the caller, then you fix their problem, then you wrap up. Each stage needs different instructions and often different tools. Here is what you can change without hanging up, and how.

| What you want to change | How | Supported? |
| :-- | :-- | :-- |
| The instructions | Send `clientContent` with `role="system"` and `turn_complete=False` | **Yes**, documented |
| The tool list | Open a new session with the new `setup.tools` | **Yes**, documented |
| The tool list, without reconnecting | Raw `contextUpdate` frame | **No.** Reachable, but not documented or supported |

### Change the instructions: send a system turn

```python
await session.send_client_content(
    turns=types.Content(
        role="system",
        parts=[types.Part(text="Stage: checkout. Read the total back before you charge the card.")],
    ),
    turn_complete=False,
)
```

The model follows the new instructions from its next reply. The socket stays open, so the caller hears no gap and the browser doesn't ask for the microphone again. We tested this on `gemini-3.8-live` and `gemini-3.5-live-preview`. Google documents it in [Update system instructions during a session](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/start-manage-session).

Send it after `turnComplete`, not while the model is talking. A `clientContent` message sent mid-reply cuts the model off.

### Change the tools: reconnect without dropping the caller

The supported way to swap tools is a new session with a new `setup.tools`. Done carelessly, that means half a second of silence and a fresh microphone prompt. Done well, the caller doesn't notice:

1. Keep the browser `AudioContext` and microphone stream alive. Close only the WebSocket.
2. Keep a short running summary of the call (key facts plus the last few turns).
3. Open the new session with the persona, that summary, and the new tools.

[Session Architecture: Managed Session Cycling](/gemini_live_pipecat/gemini-live-skill/#b-the-managed-session-cycling-pattern) walks through each step.

### What about `contextUpdate`?

The Vertex AI Live WebSocket accepts a `contextUpdate` message with a `tools` field. On `gemini-3.8-live` and `gemini-3.5-live-preview` it does swap or clear the tool list in place, with no reconnect. It's tempting. Don't build a product on it yet.

:::caution[`contextUpdate` is exposed, but not documented or supported]
- **No documentation.** No public Google page describes it.
- **No SDK support.** No released version of `google-genai` has a method for it. You have to write raw JSON to the SDK's private WebSocket object, which can break on any SDK upgrade.
- **No support commitment.** It comes with no compatibility promise and no deprecation notice period.
- **It can fail silently.** In our tests one Gemini 3.5 Live preview build accepted the frame and then ignored it. No error came back, and the old tools kept firing. `gemini-live-2.5-flash-native-audio` closes the connection instead.
- **Removed tools can still be called.** Even where it works, the model sometimes called a tool it had just lost, copying an earlier call from the conversation. You would have to check every tool call against the current list before running it.

If changing tools without reconnecting is a hard requirement for your product, ask your Google account team. Until then, use a system turn for instructions and session cycling for tools.
:::
