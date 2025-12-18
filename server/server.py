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
load_dotenv()

# Monkey-patch pipecat-ai to fix a bug in the library
# The GeminiMultimodalLiveLLMService uses the 'websockets' library but doesn't import it.
# This patch injects the websockets module into the library's namespace.
import pipecat.services.gemini_multimodal_live.gemini
pipecat.services.gemini_multimodal_live.gemini.websockets = websockets

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
    api_key: str = "",
    model: str = "gemini-2.5-flash-native-audio-preview-09-2025",
    #gemini-2.5-flash-native-audio-preview-09-2025
    voice: Optional[str] = "Puck",
    language: str = "en-US",
    system_instruction: Optional[str] = None,
    tts: bool = True,
    tts_voice: str = "en-US-Chirp3-HD-Aoede",
    tts_pace: float = 0.80,
    llm_model: str = "gemini-2.0-flash",
    stt_model: str = "latest_long",
    stt_language: str = "en-US",
):
    await websocket.accept()
    print("WebSocket connection accepted")
    try:
        if bot_type == "gemini-live":
            await run_agent_live(
                websocket,
                api_key=api_key,
                model=model,
                voice=voice,
                language=language,
                system_instruction=system_instruction,
                tts=tts,
                tts_pace=tts_pace,
            )
        elif bot_type == "tts-llm-stt":
            await run_agent(
                websocket,
                api_key=api_key,
                tts_voice=tts_voice,
                tts_pace=tts_pace,
                llm_model=llm_model,
                stt_model=stt_model,
                stt_language=stt_language,
                system_instruction=system_instruction,
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


# Mount the static files directory
if os.path.exists("client/dist"):
    app.mount("/assets", StaticFiles(directory="client/dist/assets"), name="assets")
    
    @app.get("/system-prompt")
    async def get_system_prompt():
        return {"system_prompt": SYSTEM_PROMPT}

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
