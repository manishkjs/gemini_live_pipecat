---
title: Tool Calling & Async Orchestration
description: Asynchronous tool calling, non-blocking execution, and state orchestration in Gemini Live.
---

<aside class="one-minute" aria-label="In one minute">
  <div class="one-minute-head">
    <span class="badge badge-blue">In one minute</span>
    <span class="one-minute-audience">For product managers and solution architects</span>
  </div>
  <dl class="one-minute-grid">
    <div class="one-minute-cell"><dt>What this page covers</dt><dd>How the agent asks your backend to do things (look up an order, book a seat) while the conversation keeps going. Also how to change its instructions and tools mid-call, and what to put in a tool result.</dd></div>
    <div class="one-minute-cell"><dt>Why it matters</dt><dd>Tool calls are where voice agents freeze, go silent, or drift in accent. The result you return is the last thing the model reads before it speaks.</dd></div>
    <div class="one-minute-cell one-minute-number"><dt>The number to remember</dt><dd>A one-line pointer instead of a repeated step card in each tool result saves about 550 to 680 history tokens (billing units) per step change.</dd></div>
    <div class="one-minute-cell"><dt>The decision you own</dt><dd>Which tools are available at each step of the call, and what a tool result is allowed to say out loud.</dd></div>
  </dl>
</aside>

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

See [Optimization Patterns: Dynamic Prompt Cards & Phase Gates](/gemini-live/optimization/#pillar-2-dynamic-prompt-cards--phase-gates-the-silent-conductor) for the full state-machine implementation that keeps active prompt tokens averaging ~500 tokens per turn without dropping the WebSocket connection.

---

## 7. Changing tools and instructions during a call

A call often moves through stages. First you verify the caller, then you fix their problem, then you wrap up. Each stage needs different instructions and often different tools. Here is what you can change without hanging up, and how.

| What you want to change | How | Supported? |
| :-- | :-- | :-- |
| Both the tool list and `systemInstruction` in place, without reconnecting | `await session.send_context_update(system_instruction=..., tools=...)` (`google-genai >= 2.32.0`) | Yes on Vertex AI (`gemini-3.8-live`); SDK also sends the frame on the Gemini Developer API (confirm your API key has server-side `contextUpdate` access) |
| The instructions only | `await session.send_context_update(system_instruction="...")` (`gemini-3.8-live`), or `clientContent` with `role="system"` and `turn_complete=False` (Vertex AI, including Gemini 2.5 native audio) | Yes, documented |
| The tool list on models that do not support `contextUpdate` (such as Gemini 2.5 native audio) | Open a new session with the new `setup.tools` | Yes, documented |

### Change the instructions: send a system turn (Vertex AI)

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

[Session Architecture: Managed Session Cycling](/gemini-live/gemini-live-skill/#b-the-managed-session-cycling-pattern) walks through each step.

### Swap per-card tools and `systemInstruction` in place with `send_context_update` (`google-genai >= 2.32.0`)

Starting in `google-genai 2.32.0` (`pip install -U "google-genai>=2.32.0"`), `session.send_context_update()` lets you replace `system_instruction`, `tools`, or both in place during a live call on `gemini-3.8-live` without closing the WebSocket:

```python
# 1. Replace the system prompt only (existing tools stay untouched):
await session.send_context_update(
    system_instruction="Base rules...\n\nCURRENT PROMPT CARD\nStep: Payment..."
)

# 2. Replace the active tool list (pass Python functions or types.Tool objects):
await session.send_context_update(tools=[set_call_language, dispatch_checkout_link])

# 3. Remove all tools on a talk-only closing card (0 tool schema tokens/turn):
await session.send_context_update(tools=[])

# 4. Replace both in one atomic frame inside a blocking tool handler:
await session.send_context_update(
    system_instruction=updated_system_instruction,
    tools=card_tools,
)
```

Sending `send_context_update` inside a blocking tool handler (right before returning the `FunctionResponse`) replaces the active tool list with only the tools the next prompt card needs and refreshes `systemInstruction` with the active card and session state, so sliding-window compression never drops the card.

:::caution[Operational rules for `send_context_update`]
- **Update at major stage transitions, not on every turn**: `system_instruction` and `tools` sit in the model preamble, so every update invalidates the prefix cache. Swap them when the conversation moves to a new phase card (for example, `3 to 8 times` in a multi-step call), not on turns where nothing changed.
- **Set at least one field**: Calling `await session.send_context_update()` with both `system_instruction=None` and `tools=None` raises ``ValueError("At least one of `system_instruction` or `tools` must be set.")``.
- **Full replacement (no merge)**: Every field you set replaces the previous value. Include global tools (such as `set_call_language`) in each card's `tools` list, and pass `base_rules + current_card + session_state` in `system_instruction`.
- **Check active tools before running**: Removing a tool declaration does not remove earlier `function_call` turns from conversation history, so the model can occasionally imitate an old call. Check incoming tool calls against the current card's active tool list before running them.
- **Model & SDK compatibility**: `session.send_context_update()` is in `google-genai >= 2.32.0` and serializes `contextUpdate` for both Vertex AI and the Gemini Developer API. On Vertex AI (`gemini-3.8-live`) it is ungated; on the Gemini Developer API, confirm your API key has server-side `contextUpdate` access before relying on it in production. Legacy `gemini-live-2.5-flash-native-audio` rejects `contextUpdate` with `1007` (use `send_client_content` with `role="system"` on Vertex AI 2.5 instead). If your non-Python SDK release has no context-update helper yet, send the raw `contextUpdate` JSON frame below.
:::

#### Python tool-handler pattern (`google-genai >= 2.32.0`)

```python
from typing import Any, Dict, List
from google.genai import types


async def advance_card_and_tools(
    session,
    function_call,
    card_tools: List[Any],
    updated_system_instruction: str,
    tool_result: Dict[str, Any],
):
    # 1. Send context_update while the model is blocked waiting on this tool response.
    #    Pass card_tools=[] on a talk-only closing card to clear all tools.
    await session.send_context_update(
        system_instruction=updated_system_instruction,
        tools=card_tools,
    )

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

#### Raw WebSocket JSON payloads (for non-Python runtimes or `google-genai < 2.32.0`)

On the wire, `send_context_update` sends a `contextUpdate` (or `context_update`) message. Every field you include replaces the previous value. Because Protobuf cannot distinguish an unset repeated field from an empty list, `tools` wraps the `tools` array inside an outer object (`{"tools": {"tools": [...]}}`), and sending an empty list (`{"tools": {"tools": []}}`) or empty wrapper object (`{"tools": {}}`) clears all tools:

```jsonc
// 1. Replace both systemInstruction and the active tool list for the next card:
{
  "contextUpdate": {
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
  "contextUpdate": {
    "tools": { "tools": [] }
  }
}
```

:::danger[An empty `"tools": {}` or `"tools": {"tools": []}` clears every tool]
The `tools` wrapper exists so the server can tell "no tools update" apart from "clear all tools". If the `tools` key is absent (`tools=None` in `send_context_update`), the current tools stay. If it is present with an empty list (`tools=[]` in `send_context_update`, which sends `{"tools": {"tools": []}}` on the wire; `{"tools": {}}` is an equivalent raw form), the server clears all tools. A custom serializer that always writes a default `"tools": {}` when you only meant to update `systemInstruction` removes every tool for the rest of the call, and the server sends no error. Omit the `tools` key unless you mean to change the tools.
:::

For the animated walkthrough of how Gemini Live stores instructions versus history, the 8-step flight-booking breakdown, and the complete tool-handler code, see [Pillar 2: Dynamic Prompt Cards & Per-Card Tools](/gemini-live/optimization/prompt-cards/).

---

## 8. What to put in a FunctionResponse

Every tool result is added to the conversation history and billed again on every later turn. It also sits right before the point where the model starts generating audio, so its wording steers the next reply more than anything else in the prompt. Keep it short, and split it into fields the model speaks and fields it only reads.

### The compact response contract

When a tool call moves the call to a new phase, put the full card in `systemInstruction` (see [section 7](#7-changing-tools-and-instructions-during-a-call)) and return only:

| Field | What it holds | Size |
| :--- | :--- | :--- |
| `call_state` | Confirmed facts so far: `"Language: Hindi \| Trip: one-way BLR to DEL, 18 Oct \| Adults: 2"` | Under 60 tokens |
| `instruction` | What to say or ask next | One sentence |
| `prompt_card` | A pointer, not the card: `"Prompt card 4 of 8 (Return Flight Selection) is now in your system instruction. Follow it."` | One line |
| `vocal_tone` | The voice and accent reminder (see below) | One line |
| spoken fields | `facts`, `ask_say`, `note_say`, any `*_say` or `*_spell` field | As short as the reply allows |

Do not repeat a multi-hundred-token phase card in every tool result. Fourteen tool calls that each carried a ~495-token card added about 6,900 tokens of history in one call. A one-line pointer instead of the full card saves about 550 to 680 history tokens per card change.

### Format numbers in code, not in the model's speech

The audio model is weakest at formatting while it speaks. Do the formatting in your handler and return ready-to-say strings:

| Raw value | Spoken field | What the handler returns |
| :--- | :--- | :--- |
| `fare: 4500` | `fare_say` | `"₹4,500 (four thousand five hundred rupees)"`, or the same amount in the caller's script for Hindi or Tamil |
| `depart: "06:20"` | `depart_say` | `"6:20 AM"` |
| `flight: "XY 2134"` | `flight_say` | `"X Y two one three four"` |
| `name: "SACHIN"` | `first_spell` | `"S as in Sierra, A as in Alpha, C as in Charlie, H as in Hotel, I as in India, N as in November"` |

```python
def rupees(amount: int) -> str:
    """Indian digit grouping plus words: 150000 -> '₹1,50,000 (one lakh fifty thousand rupees)'."""
    digits = str(amount)
    head, tail = digits[:-3], digits[-3:]
    while len(head) > 2:
        tail = f"{head[-2:]},{tail}"
        head = head[:-2]
    grouped = f"{head},{tail}" if head else tail
    words = number_to_words(amount)  # your own helper, or num2words(amount, lang="en_IN")
    return f"₹{grouped} ({words} rupees)"


def clock(hhmm: str) -> str:
    hour, minute = map(int, hhmm.split(":"))
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12}:{minute:02d} {suffix}"
```

### Tell the model which fields to speak

Add one rule to the base system instruction that lists the spoken fields and the private ones:

```text
Tool results are private guidance. Speak only their spoken fields, in the caller's language:
facts, ask_say, heads_up, note_say, change, any field ending in _say or _spell (exactly as given),
and any field the current step or the instruction tells you to read.
Never speak instruction, prompt_card, call_state, or vocal_tone.
If a result has an error field, do not read it. Fix the argument it names and call the tool once more,
unless its instruction says otherwise.
```

### Keep the accent after tool calls: `vocal_tone`

The system instruction sits at the top of the prompt. After three or four audio turns, it is thousands of tokens away from the decode point, while the newest tool result is right next to it. A result full of English JSON keys and values can then pull the voice toward the model's default US English accent. Repeat a one-line tone reminder inside every tool result:

```python
VOCAL_TONE = "Warm Indian English or everyday Hinglish female voice, Indian accent on every word"


def respond(payload: dict, call_state: str) -> dict:
    return {**payload, "call_state": call_state, "vocal_tone": VOCAL_TONE}
```

Keep the same wording as the accent line in your system instruction, and list `vocal_tone` among the fields the model never speaks. In field testing on Indian-English agents, this removed most post-tool accent drift.

### Stop redundant tool sweeps on empty lookups (`retryable: False`)

When a search or directory lookup returns an empty list (`[]`) or `{}` without a terminal status, `gemini-3.8-live` often treats the miss as a query-formatting mistake and fires 2 to 5 follow-up calls with shortened names or alternative filters before replying to the caller. Distinguish between **argument validation errors** (where you want the model to fix the argument and retry once) and **valid lookups that found zero records** (where the model must stop searching and ask the caller):

```python
if not matches:
    return respond(
        {
            "status": "no_results",
            "retryable": False,
            "matches": [],
            "ask_say": f"I couldn't find a match for {query}. Could you check the spelling or try another date?",
            "instruction": "No matching records exist. Tell the caller and ask for an alternative without calling this tool again.",
        },
        call_state=state.summary(),
    )
```

Keep the `instruction` field to a single concise sentence and `call_state` under 60 tokens. Never dump full state dictionaries or multi-paragraph instructions into every `FunctionResponse`, because every tool result stays in `ROLE_USER` history and is re-billed on every later turn until `SlidingWindow` trims it.


