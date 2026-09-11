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
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv(override=True)
import diagnostic_buffer
import voice_profiles

_session_instructions: Dict[str, str] = {}

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
from system_prompt import SYSTEM_PROMPT, tts_prompt

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

@app.middleware("http")
async def check_sni_mismatch_middleware(request: Request, call_next):
    gfe_info = request.headers.get("x-google-gfe-frontline-info")
    if gfe_info:
        host = (request.headers.get("host") or "").split(":")[0].lower()
        sni = None
        for pair in gfe_info.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                if k.strip().lower() == "sni":
                    sni = v.strip().lower()
                    break
        if sni and host and sni != host:
            return Response(status_code=421, content="Misdirected Request")
    return await call_next(request)

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    bot_type: str = "tts-llm-stt",
    model: str = "gemini-3.5-flash-live-preview",
    voice: Optional[str] = "Puck",
    language: str = "en-US",
    system_instruction: Optional[str] = None,
    tts: bool = False,
    tts_voice: str = "en-US-Chirp3-HD-Aoede",
    tts_model: str = "gemini-3.1-flash-tts-preview",
    tts_pace: float = 0.80,
    llm_model: str = "gemini-3.5-flash-lite",
    stt_model: str = "gemini-3.5-transcribe-live-aistudio",
    stt_language: str = "en-US",
    tools: Optional[str] = None,
    skip_stt: bool = False,
    vad: bool = True,
    context_compression: bool = True,
    context_compression_trigger_tokens: Optional[int] = 5000,
    thinking: bool = False,
    thinking_level: Optional[str] = None,
    # Opaque, single-use handle minted by /connect. Raw cloning keys are
    # deliberately not accepted here: this URL is logged in several places.
    voice_profile_id: Optional[str] = None,
    # Stamps every log line and latency sample this session produces, so
    # concurrent demoers do not blend their metrics together.
    session_id: Optional[str] = None,
):
    await websocket.accept()
    print("WebSocket connection accepted")
    diagnostic_buffer.bind_session(session_id)
    if not system_instruction and session_id and session_id in _session_instructions:
        system_instruction = _session_instructions.pop(session_id)
    custom_voice_key = voice_profiles.consume(voice_profile_id)
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
                vad=vad,
                context_compression=context_compression,
                context_compression_trigger_tokens=max(5000, context_compression_trigger_tokens) if context_compression_trigger_tokens is not None else 5000,
                thinking=thinking,
                thinking_level=thinking_level,
                custom_voice_key=custom_voice_key,
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
                vad=vad,
            )
    except Exception as e:
        print(f"Exception in run_bot: {e}")


@app.post("/connect")
async def bot_connect(request: Request) -> Dict[Any, Any]:
    from urllib.parse import parse_qs, urlencode
    # Get the original query string from the incoming request (e.g., "model=...&voice=...")
    query_params_raw = request.url.query
    params_dict: Dict[str, str] = {
        k: v[-1] for k, v in parse_qs(query_params_raw, keep_blank_values=True).items()
    }

    # Try to get parameters from the JSON body
    try:
        body = await request.json()
        if isinstance(body, dict):
            # Store system_instruction and URL-encode if within URL limits
            if "system_instruction" in body:
                custom_prompt = body["system_instruction"].strip()
                if custom_prompt and custom_prompt != SYSTEM_PROMPT.strip():
                    session_id = params_dict.get("session_id")
                    if session_id:
                        _session_instructions[session_id] = custom_prompt
                    if len(custom_prompt) < 4500:
                        params_dict["system_instruction"] = custom_prompt
            
            # URL-encode the tools from the body
            if "tools" in body:
                import json
                tools_data = body["tools"]
                if isinstance(tools_data, (dict, list)):
                    tools_str = json.dumps(tools_data)
                else:
                    tools_str = str(tools_data)
                params_dict["tools"] = tools_str

            if "context_compression" in body:
                params_dict["context_compression"] = "true" if body["context_compression"] else "false"

            if "context_compression_trigger_tokens" in body:
                try:
                    raw_val = int(body["context_compression_trigger_tokens"])
                    # Strictly enforce minimum 5,000 tokens - do not accept anything less
                    params_dict["context_compression_trigger_tokens"] = str(max(5000, raw_val))
                except (ValueError, TypeError):
                    params_dict["context_compression_trigger_tokens"] = "5000"

            if "thinking" in body:
                params_dict["thinking"] = "true" if body["thinking"] else "false"

            if "thinking_level" in body:
                params_dict["thinking_level"] = str(body["thinking_level"])

            if "vad" in body:
                params_dict["vad"] = "false" if body["vad"] is False else "true"

            # A cloning key is a credential and must never reach the ws_url,
            # which is written to browser history, access logs and the in-app
            # diagnostics buffer. Exchange it for a single-use, expiring handle.
            if "custom_voice_key" in body and body["custom_voice_key"]:
                profile_id = voice_profiles.register(str(body["custom_voice_key"]))
                if profile_id:
                    params_dict["voice_profile_id"] = profile_id

    except Exception:
        # Body is not JSON or is empty, so we just ignore it
        pass
    
    query_params = urlencode(params_dict)
    
    # Dynamically determine WebSocket scheme (ws vs wss) and host
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    ws_scheme = "wss" if scheme == "https" else "ws"
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    
    ws_url = f"{ws_scheme}://{host}/ws?{query_params}"
    print(f"Generated WS URL for client: {ws_url}") # Helpful for debugging
    
    return {"ws_url": ws_url}


@app.get("/connect/system-prompt")
async def get_system_prompt():
    return {"system_prompt": SYSTEM_PROMPT}

@app.get("/api/logs")
async def get_diagnostic_logs(limit: int = 500, session_id: Optional[str] = None):
    """Recent logs and latency percentiles.

    Pass `session_id` to see only your own session. Omitting it returns
    everything in the process, which is only meaningful on a single-user box.
    """
    from diagnostic_buffer import get_recent_diagnostic_logs, get_latency_summary
    return {
        "logs": get_recent_diagnostic_logs(limit, session_id=session_id),
        "latency_summary": get_latency_summary(session_id=session_id),
        "session_id": session_id,
    }

@app.get("/api/metrics/latency")
async def get_latency_metrics_endpoint(session_id: Optional[str] = None):
    from diagnostic_buffer import get_latency_summary
    return get_latency_summary(session_id=session_id)

@app.post("/api/logs/clear")
async def clear_diagnostic_logs_endpoint(session_id: Optional[str] = None):
    """Clear diagnostics. Scoped to one session unless asked otherwise, so one
    demoer clicking Clear cannot wipe another's history."""
    from diagnostic_buffer import clear_diagnostic_logs
    clear_diagnostic_logs(session_id=session_id)
    return {"status": "cleared", "session_id": session_id}

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
        headers = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
        if os.path.exists(diag_path):
            return FileResponse(diag_path, headers=headers)
        return FileResponse(os.path.join(client_dist_dir, "index.html"), headers=headers)

    @app.get("/{catch_all:path}")
    async def read_index(catch_all: str):
        headers = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
        return FileResponse(os.path.join(client_dist_dir, "index.html"), headers=headers)

async def main():
    port = int(os.environ.get("PORT", 7860))
    config = uvicorn.Config(app, host="0.0.0.0", port=port)
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
