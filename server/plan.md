# Implementation Plan: Observability UI & Dynamic Tools

This plan details the steps to implement an observability dashboard and dynamic tool registration for the Gemini Live Pipecat agent.

## 1. Backend Implementation

### 1.1 Dynamic Tool Registration (`server/server.py`, `server/agent_live.py`)
- **Goal**: Allow the client to define tools via JSON configuration instead of hardcoding them.
- **`server/server.py`**:
  - Update `/connect` endpoint to accept `tools` in the JSON body.
  - Encode the `tools` JSON string into the WebSocket URL query parameters.
  - Update `websocket_endpoint` to accept `tools` argument.
- **`server/agent_live.py`**:
  - Update `run_agent_live` to accept `tools` (JSON string).
  - Parse the JSON string into `ToolsSchema` and `FunctionSchema` objects.
  - Update the `tools` passed to `GeminiLiveVertexLLMService`.
  - Dynamically register the functions (mocking execution for now, or supporting a generic "echo" for testing). *Self-correction: The user wants to "register tools dynamically instead of using the hardcoded get_current_time". I will interpret this as allowing the definition of the *interface*. Since the actual backend logic for new tools won't exist dynamically, I will implement a generic handler or keep `get_current_time` as a default if no tools are provided, but allow overriding.*
  - *Refinement*: For true dynamic tools, we need a way to execute them. For this task, the primary goal is *declaration*. I will likely bind all dynamic tools to a generic handler that returns "Tool [name] called with args [args]" to verify the loop.

### 1.2 Metrics Streaming (`server/agent_live.py`)
- **Goal**: Stream real-time metrics (token usage, interruptions, tool calls) to the client.
- **`GeminiSessionLoggerMixin`**:
  - **Interruption Tracking**:
    - In `process_frame`, increment an interruption counter when `InterruptionFrame` is detected.
    - Emit a metrics update.
  - **Tool Call Tracking**:
    - In `_handle_msg_tool_call`, increment tool call counter.
    - Emit a metrics update.
  - **Token Usage**:
    - In `_handle_msg_usage_metadata`, extract prompt/response/total tokens.
    - Emit a metrics update.
  - **Streaming Mechanism**:
    - Create a helper `_emit_metrics(self)`:
      - Constructs a JSON object: `{ type: "metrics", ... }`.
      - Creates a `TextFrame` with content `JSON:<json_string>`.
      - Pushes the frame downstream.

## 2. Frontend Implementation

### 2.1 UI Updates (`client/index.html`, `client/src/style.css`)
- **Goal**: Add the Observability dashboard.
- **HTML**:
  - Add a new tab button "Observability" in the "Bot Configuration" tile.
  - Add a corresponding panel `#observability-panel`.
  - **Tool Editor**: Add a `<textarea>` for JSON input (defaulting to `get_current_time` schema).
  - **Dashboard**:
    - **Summary Cards**: Total Turns, Total Interrupts, Total Tool Calls, Total Tokens.
    - **History Table**: Turn ID, Prompt Tokens, Response Tokens, Total Tokens.
- **CSS**:
  - Style the dashboard cards (grid layout).
  - Style the table.
  - Style the JSON editor (monospaced font).

### 2.2 Client Logic (`client/src/app.ts`)
- **Goal**: Handle metrics messages and send tool configuration.
- **Tool Config**:
  - In `connect()`, read the JSON from the Tool Editor.
  - Validate it (basic JSON parse).
  - Include it in the POST body to `/connect`.
- **Metrics Handling**:
  - In `onGenericMessage` (or where text messages arrive):
    - Check for `JSON:` prefix.
    - If found, parse and update the dashboard state.
    - **Crucial**: Prevent this message from being displayed as a transcript or caption.
- **Dashboard Logic**:
  - Maintain state: `turns`, `totalInterrupts`, `totalToolCalls`.
  - Update DOM elements on receipt of metrics.

## 3. Execution Steps

1.  **Modify Server (Connection & Tools)**: Update `server.py` and `agent_live.py` to thread the tools config through.
2.  **Modify Server (Metrics)**: Implement the metrics tracking and streaming in `GeminiSessionLoggerMixin`.
3.  **Update Client UI**: Add the HTML and CSS for the dashboard.
4.  **Update Client Logic**: Implement the connection logic and message handling.
5.  **Verification**: Test connection with custom tools and verify metrics appear in the dashboard.
