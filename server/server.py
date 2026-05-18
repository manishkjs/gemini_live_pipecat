import asyncio
import os
import argparse
import websockets
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from urllib.parse import quote

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv(override=True)

# Monkey-patch pipecat-ai to fix a bug in the library
# The GeminiMultimodalLiveLLMService uses the 'websockets' library but doesn't import it.
# This patch injects the websockets module into the library's namespace.
import pipecat.services.gemini_multimodal_live.gemini
pipecat.services.gemini_multimodal_live.gemini.websockets = websockets

# Monkey-patch for google-genai BaseApiClient to fix AttributeError in aclose
from google.genai._api_client import BaseApiClient

async def patched_aclose(self):
    if hasattr(self, '_async_httpx_client') and self._async_httpx_client:
        try:
            await self._async_httpx_client.aclose()
        except Exception:
            pass
    if hasattr(self, '_aiohttp_session') and self._aiohttp_session:
        try:
            await self._aiohttp_session.close()
        except Exception:
            pass

BaseApiClient.aclose = patched_aclose

# Monkey-patch for Pipecat FrameProcessor to fix bug when frames arrive before StartFrame
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import SystemFrame

# Fix for missing attribute fallback
FrameProcessor._FrameProcessor__process_queue = None

async def patched_input_frame_task_handler(self):
    while True:
        (frame, direction, callback) = await self._FrameProcessor__input_queue.get()

        if self._FrameProcessor__should_block_system_frames and self._FrameProcessor__input_event:
            await self._FrameProcessor__input_event.wait()
            self._FrameProcessor__input_event.clear()
            self._FrameProcessor__should_block_system_frames = False

        if isinstance(frame, SystemFrame):
            await self._FrameProcessor__process_frame(frame, direction, callback)
        elif hasattr(self, '_FrameProcessor__process_queue') and self._FrameProcessor__process_queue:
            await self._FrameProcessor__process_queue.put((frame, direction, callback))
        else:
            # Ignore frames before start instead of crashing
            pass

        self._FrameProcessor__input_queue.task_done()

FrameProcessor._FrameProcessor__input_frame_task_handler = patched_input_frame_task_handler

from agent_live import run_agent_live
from agent import run_agent
from system_prompt import SYSTEM_PROMPT

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles FastAPI startup and shutdown."""
    yield  # Run app

# Initialize FastAPI app with lifespan manager
app = FastAPI(lifespan=lifespan)

# Configure CORS to allow requests from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    bot_type: str = "tts-llm-stt",
    model: str = "gemini-live-2.5-flash-native-audio",
    #gemini-2.5-flash-native-audio-preview-09-2025
    voice: Optional[str] = "Puck",
    language: str = "en-US",
    system_instruction: Optional[str] = None,
    tts: bool = True,
    tts_voice: str = "en-US-Chirp3-HD-Aoede",
    tts_model: str = "google-tts",
    tts_pace: float = 0.80,
    llm_model: str = "gemini-2.5-flash",
    stt_model: str = "latest_long",
    stt_language: str = "en-US",
    tools: Optional[str] = None,
    skip_stt: bool = False,
):
    await websocket.accept()
    print("WebSocket connection accepted")
    try:
        if bot_type == "gemini-live":
            await run_agent_live(
                websocket,
                model=model,
                voice=voice,
                language=language,
                system_instruction=system_instruction,
                tts=tts,
                tts_pace=tts_pace,
                tools=tools,
            )
        elif bot_type == "tts-llm-stt":
            await run_agent(
                websocket,
                tts_voice=tts_voice,
                tts_pace=tts_pace,
                llm_model=llm_model,
                stt_model=stt_model,
                stt_language=stt_language,
                tts_model=tts_model,
                system_instruction=system_instruction,
                skip_stt=skip_stt,
            )
    except Exception as e:
        print(f"Exception in run_bot: {e}")


@app.post("/connect")
async def bot_connect(request: Request) -> Dict[Any, Any]:
    # Get the original query string from the incoming request (e.g., "model=...&voice=...")
    query_params = request.url.query

    # Try to get parameters from the JSON body
    try:
        body = await request.json()
        if isinstance(body, dict):
            # URL-encode the system_instruction from the body
            if "system_instruction" in body:
                encoded_instruction = quote(body["system_instruction"])
                # Append to existing query params or start a new query string
                if query_params:
                    query_params += f"&system_instruction={encoded_instruction}"
                else:
                    query_params = f"system_instruction={encoded_instruction}"
            
            # URL-encode the tools from the body
            if "tools" in body:
                import json
                # Ensure tools is a valid JSON string or object converted to string
                tools_data = body["tools"]
                if isinstance(tools_data, (dict, list)):
                    tools_str = json.dumps(tools_data)
                else:
                    tools_str = str(tools_data)
                
                encoded_tools = quote(tools_str)
                if query_params:
                    query_params += f"&tools={encoded_tools}"
                else:
                    query_params = f"tools={encoded_tools}"

    except Exception:
        # Body is not JSON or is empty, so we just ignore it
        pass
    
    # Check if running in production (e.g., on Cloud Run)
    is_production = "K_SERVICE" in os.environ

    if is_production:
        # Construct the full WebSocket URL for production
        ws_url = f"wss://{request.url.hostname}/ws?{query_params}"
    else:
        # Construct the full WebSocket URL for local development
        ws_url = f"ws://{request.url.hostname}:7860/ws?{query_params}"

    print(f"Generated WS URL for client: {ws_url}") # Helpful for debugging
    
    return {"ws_url": ws_url}


@app.get("/connect/system-prompt")
async def get_system_prompt():
    return {"system_prompt": SYSTEM_PROMPT}


from fastapi.responses import Response

@app.post("/twilio/voice")
async def twilio_voice(request: Request):
    """Webhook endpoint for Twilio to fetch TwiML."""
    # Use netloc to preserve the incoming port (e.g. :7860 or standard 80/443)
    scheme = "wss" if request.url.scheme == "https" or "K_SERVICE" in os.environ else "ws"
    ws_url = f"{scheme}://{request.url.netloc}/ws/twilio"
        
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}" />
    </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


from agent_live import run_agent_twilio

import json

@app.websocket("/ws/twilio")
async def websocket_twilio(websocket: WebSocket):
    """WebSocket endpoint for Twilio Media Streams."""
    await websocket.accept()
    print("Twilio WebSocket connection accepted")
    try:
        # Read messages until we find 'start' event
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            print(f"Received Twilio event: {data.get('event')}")
            if data.get("event") == "start":
                stream_sid = data.get("streamSid")
                print(f"Received streamSid: {stream_sid}")
                await run_agent_twilio(websocket, stream_sid=stream_sid)
                break
    except Exception as e:
        print(f"Exception in websocket_twilio: {e}")

# Mount the static files directory
if os.path.exists("client/dist"):
    app.mount("/assets", StaticFiles(directory="client/dist/assets"), name="assets")
    
    @app.get("/{catch_all:path}")
    async def read_index(catch_all: str):
        return FileResponse('client/dist/index.html')

async def main():
    port = int(os.environ.get("PORT", 7860))
    config = uvicorn.Config(app, host="0.0.0.0", port=port)
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
