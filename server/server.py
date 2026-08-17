import asyncio
import os
import sys
import argparse
import websockets
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from urllib.parse import quote

# Ensure server dir is in sys.path
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv(override=True)
import diagnostic_buffer

# Obsolete in pipecat-ai 1.x (which natively uses google-genai)
# import pipecat.services.gemini_multimodal_live.gemini
# pipecat.services.gemini_multimodal_live.gemini.websockets = websockets

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
from system_prompt import SYSTEM_PROMPT, get_chained_system_prompt, tts_prompt
from redis_cache import rag_cache
from rag_function import CANONICAL_DOMAIN_KNOWLEDGE

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles FastAPI startup and shutdown."""
    await rag_cache.initialize()
    await rag_cache.prewarm(CANONICAL_DOMAIN_KNOWLEDGE)
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
    bot_type: str = "gemini-live",
    model: str = "gemini-3.5-flash-live-preview",
    voice: Optional[str] = "Aoede",
    language: str = "hi-IN",
    system_instruction: Optional[str] = None,
    tts: bool = False,
    tts_voice: str = "en-US-Chirp3-HD-Aoede",
    tts_model: str = "gemini-3.1-flash-tts-preview",
    tts_pace: float = 0.80,
    llm_model: str = "gemini-3.5-flash-lite",
    stt_model: str = "chirp_3",
    stt_language: str = "en-US",
    tools: Optional[str] = None,
    skip_stt: bool = False,
    context_compression: bool = True,
    context_compression_trigger_tokens: Optional[int] = 10000,
    user_id: Optional[str] = None,
):
    await websocket.accept()
    print("WebSocket connection accepted")
    try:
        if bot_type == "tts-llm-stt":
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
        else:
            await run_agent_live(
                websocket,
                model=model,
                voice=voice,
                language=language,
                system_instruction=system_instruction,
                tts=tts,
                tts_pace=tts_pace,
                tools=tools,
                context_compression=context_compression,
                context_compression_trigger_tokens=context_compression_trigger_tokens,
                initial_user_id=user_id,
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
            # URL-encode system_instruction ONLY if customized and compact to prevent HTTP 400 (Query URL too long)
            if "system_instruction" in body:
                custom_prompt = body["system_instruction"].strip()
                if custom_prompt and custom_prompt != SYSTEM_PROMPT.strip() and len(custom_prompt) < 1500:
                    encoded_instruction = quote(custom_prompt)
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

            if "context_compression" in body:
                val = "true" if body["context_compression"] else "false"
                if query_params:
                    query_params += f"&context_compression={val}"
                else:
                    query_params = f"context_compression={val}"

            if "context_compression_trigger_tokens" in body:
                val = str(body["context_compression_trigger_tokens"])
                if query_params:
                    query_params += f"&context_compression_trigger_tokens={val}"
                else:
                    query_params = f"context_compression_trigger_tokens={val}"

    except Exception:
        # Body is not JSON or is empty, so we just ignore it
        pass
    
    # Dynamically determine WebSocket scheme (ws vs wss) and host
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    ws_scheme = "wss" if scheme == "https" else "ws"
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    
    ws_url = f"{ws_scheme}://{host}/ws?{query_params}"
    print(f"Generated WS URL for client: {ws_url}") # Helpful for debugging
    
    return {"ws_url": ws_url}


@app.get("/connect/system-prompt")
async def get_system_prompt():
    return {"system_prompt": get_chained_system_prompt(phase=1)}

@app.get("/api/logs")
async def get_diagnostic_logs(limit: int = 500):
    from diagnostic_buffer import get_recent_diagnostic_logs
    return {"logs": get_recent_diagnostic_logs(limit)}

@app.post("/api/logs/clear")
async def clear_diagnostic_logs_endpoint():
    from diagnostic_buffer import clear_diagnostic_logs
    clear_diagnostic_logs()
    return {"status": "cleared"}

@app.get("/api/trace/current")
async def get_current_trace_endpoint():
    from tracing import GLOBAL_LANGSMITH_TRACER
    return {"trace_url": GLOBAL_LANGSMITH_TRACER.get_current_trace_url()}

# Mount the static files directory
possible_dist_dirs = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../client/dist")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "client/dist")),
    os.path.abspath("/app/client/dist"),
]

client_dist_dir = next((d for d in possible_dist_dirs if os.path.exists(d)), None)

if client_dist_dir:
    app.mount("/assets", StaticFiles(directory=os.path.join(client_dist_dir, "assets")), name="assets")
    
    @app.get("/diagnostics")
    async def read_diagnostics():
        diag_path = os.path.join(client_dist_dir, "diagnostics.html")
        if os.path.exists(diag_path):
            return FileResponse(diag_path)
        return FileResponse(os.path.join(client_dist_dir, "index.html"))

    @app.get("/{catch_all:path}")
    async def read_index(catch_all: str):
        return FileResponse(os.path.join(client_dist_dir, "index.html"))

async def main():
    port = int(os.environ.get("PORT", 7860))
    config = uvicorn.Config(app, host="0.0.0.0", port=port)
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
