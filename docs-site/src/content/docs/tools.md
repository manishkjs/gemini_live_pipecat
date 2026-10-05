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
                id=function_call.id,
                name=function_call.name,
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
                id=function_call.id,
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

async def handle_tool_call(session, function_call):
    # Shield the database/API execution from audio barge-in cancellation
    result = await asyncio.shield(execute_backend_api(function_call.name, function_call.args))
    
    # Always deliver the toolResponse so the model's context stays consistent
    await session.send(
        input=types.LiveClientToolResponse(
            function_responses=[
                types.FunctionResponse(
                    id=function_call.id,
                    name=function_call.name,
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
| The instructions | Send `clientContent` with `role="system"` and `turn_complete=False` | Yes, documented |
| The tool list | Open a new session with the new `setup.tools` | Yes, documented |
| Both the tool list and `systemInstruction` in place, without reconnecting | Raw `context_update` frame on Vertex AI `gemini-3.8-live` | No (exposed on the wire, not yet documented or in the SDK) |

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

The model follows the new instructions from its next reply. A `role="system"` turn overwrites the previous system instruction in place (unlike a `role="user"` note, which stays in history and is billed again on every later turn), so include your base persona rules alongside the current stage instructions each time. The socket stays open, the caller hears no gap, and the browser doesn't ask for the microphone again. We tested this on `gemini-3.8-live` and `gemini-live-2.5-flash-native-audio`; see [Update system instructions during a session](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/start-manage-session).

Send the update after `turnComplete`, not while the model is talking. A `clientContent` frame with `turn_complete=True` cuts the model off mid-reply; with `turn_complete=False`, the current reply usually finishes (14 of 16 measured runs), and the new instruction takes effect on the next turn.

### Change the tools: reconnect without dropping the caller

The supported way to swap tools is a new session with a new `setup.tools`. Done carelessly, that means half a second of silence and a fresh microphone prompt. Done well, the caller doesn't notice:

1. Keep the browser `AudioContext` and microphone stream alive. Close only the WebSocket.
2. Keep a short running summary of the call (key facts plus the last few turns).
3. Open the new session with the persona, that summary, and the new tools.

[Session Architecture: Managed Session Cycling](/gemini_live_pipecat/gemini-live-skill/#b-the-managed-session-cycling-pattern) walks through each step.

### Swap per-card tools and `systemInstruction` in place with `context_update` (Vertex AI `gemini-3.8-live`)

The Vertex AI Live WebSocket accepts a `context_update` (`contextUpdate`) client message with two public fields: `tools` and `systemInstruction`. On `gemini-3.8-live`, sending it inside a blocking tool handler (right before returning the `FunctionResponse`) replaces the active tool list with only the tools the next prompt card needs and refreshes `systemInstruction` with the active card and session state, so sliding-window compression never drops the card.

:::caution[`context_update` is exposed on the wire, but not yet documented or supported]
- No public Google page describes `context_update` yet, and it comes with no compatibility promise or deprecation notice period.
- Released versions of `google-genai` do not include a helper for it. You write raw JSON to the SDK session's underlying WebSocket (`session._ws.send(...)`).
- It works on Vertex AI `gemini-3.8-live` (`v1beta1` and `v1`). Google AI Studio ignores it, and `gemini-live-2.5-flash-native-audio` rejects it and closes the connection (`1007`). The server sends no confirmation frame when an update lands.
- Removing a tool declaration does not remove earlier `function_call` turns from the conversation history, so the model can occasionally imitate an old call. Check incoming tool calls against the current card's active tool list before running them.
:::

#### WebSocket wire payloads (`context_update`)

Every field you include in `context_update` replaces (does not merge) the previous value. Because Protobuf cannot distinguish an unset repeated field from an empty list, `tools` wraps the `tools` array inside an outer object (`{"tools": {"tools": [...]}}`), and sending an empty wrapper object (`{"tools": {}}`) clears all tools:

```json
// 1. Replace both systemInstruction and the active tool list for the next card:
{
  "context_update": {
    "systemInstruction": {
      "parts": [{ "text": "Base rules...\n\nCURRENT PROMPT CARD\nStep: Payment..." }]
    },
    "tools": {
      "tools": [
        {
          "functionDeclarations": [
            {
              "name": "set_call_language",
              "description": "Records the caller's preferred spoken language for the session.",
              "parameters": {
                "type": "OBJECT",
                "properties": { "language_code": { "type": "STRING" } },
                "required": ["language_code"]
              }
            },
            {
              "name": "dispatch_checkout_link",
              "description": "Sends the checkout link once the itinerary and passenger manifest are confirmed.",
              "parameters": {
                "type": "OBJECT",
                "properties": { "delivery_channel": { "type": "STRING", "enum": ["sms", "email"] } },
                "required": ["delivery_channel"]
              }
            }
          ]
        }
      ]
    }
  }
}

// 2. Clear all tools when entering a talk-only farewell card (0 tool schema tokens/turn):
{
  "context_update": {
    "tools": {}
  }
}
```

#### Minimal Python helper (send inside a blocking tool call before returning the result)

```python
import json
from typing import Any, Dict, List, Optional
from google.genai import types


def context_update_frame(
    declarations: Optional[List[Dict[str, Any]]] = None,
    system_instruction: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the raw context_update frame.

    - declarations=[...] -> replaces active tools with the given declarations
    - declarations=[]    -> sends {"tools": {}} to clear all active tools
    - declarations=None  -> omits "tools" so existing tools stay unchanged
    """
    update: Dict[str, Any] = {}
    if declarations is not None:
        update["tools"] = (
            {"tools": [{"functionDeclarations": declarations}]}
            if declarations
            else {}
        )
    if system_instruction is not None:
        update["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    return {"context_update": update}


async def advance_card_and_tools(
    session,
    function_call,
    card_declarations: List[Dict[str, Any]],
    updated_system_instruction: str,
    tool_result: Dict[str, Any],
):
    # 1. Send context_update while the model is blocked waiting on this tool response.
    #    The generation that reads the tool response will already have the new card's tools.
    frame = context_update_frame(
        declarations=card_declarations,
        system_instruction=updated_system_instruction,
    )
    await session._ws.send(json.dumps(frame))

    # 2. Return the FunctionResponse (with a short pointer instead of repeating the full card).
    await session.send_tool_response(
        function_responses=[
            types.FunctionResponse(
                id=function_call.id,
                name=function_call.name,
                response=tool_result,
            )
        ]
    )
```

For the animated walkthrough of how Gemini Live stores instructions versus history, the 8-step flight-booking breakdown, and the complete tool-handler code, see [Pillar 2: Dynamic Prompt Cards & Per-Card Tools](/gemini_live_pipecat/optimization/prompt-cards/).

