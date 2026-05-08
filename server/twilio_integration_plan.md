# Plan: Twilio Telephony Integration for Gemini Live

This plan outlines the steps to integrate Twilio Voice with the Gemini Live Pipecat agent, allowing users to interact with the agent via phone calls.

## 1. Architecture

We will use **Twilio Media Streams** to connect the phone call to our Pipecat server. This avoids complex SIP setups and uses WebSockets for low latency.

**Flow:**
1.  **User calls** the Twilio phone number.
2.  Twilio makes a POST request to our webhook endpoint (e.g., `/twilio/voice`).
3.  Our server responds with **TwiML** containing a `<Connect>` verb and a `<Stream>` noun, pointing to our WebSocket endpoint (e.g., `wss://<domain>/ws/twilio`).
4.  Twilio establishes a WebSocket connection.
5.  Our server upgrades the connection and runs a Pipecat pipeline specifically configured for Twilio.

## 2. Pipecat Configuration for Twilio

- **Transport**: `FastAPIWebsocketTransport` (already used for web, but we will configure it for Twilio).
- **Serializer**: `TwilioFrameSerializer` (handles Twilio's specific payload format and μ-law audio encoding).
- **Audio Format**: Twilio uses 8kHz μ-law. Pipecat/Gemini handles the conversion if configured correctly.
- **VAD**: We can use `SileroVADAnalyzer` as an option, or rely on Gemini's native VAD.

## 3. Implementation Steps

### 3.1 Backend Updates (`server/server.py`)
- Add a new route `/twilio/voice` (POST) to handle the initial call and return TwiML.
- Add a new WebSocket route `/ws/twilio` to handle the media stream.
- Ensure the server can distinguish between web clients and Twilio clients.

### 3.2 Agent Updates (`server/agent_live.py` or new file)
- Implement a function `run_agent_twilio` or update `run_agent_live` to accept a `TwilioFrameSerializer`.
- Configure the pipeline with the correct audio sample rate (Twilio defaults to 8000Hz, while Gemini Live prefers 16000Hz or higher). Pipecat usually handles resampling if configured properly.

### 3.3 Infrastructure
- We will need a public URL (e.g., via `ngrok`) for Twilio to reach our local server during development.

## 4. Next Steps

1.  Verify that `TwilioFrameSerializer` is available in the installed Pipecat version.
2.  Implement the TwiML webhook in `server/server.py`.
3.  Implement the Twilio WebSocket handler and pipeline.
