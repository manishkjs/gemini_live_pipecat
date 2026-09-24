import asyncio
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*vertexai.preview.rag.*")
import os
import argparse
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from urllib.parse import quote
from uuid import uuid4

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, Query, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv(override=True)
import diagnostic_buffer
import voice_profiles
import session_access


def load_pipeline(bot_type):
    """Load only the requested media pipeline after a connection is accepted."""
    from runtime_compat import install_runtime_patches
    install_runtime_patches()
    if bot_type == "gemini-live":
        from agent_live import run_agent_live
        return run_agent_live
    from agent import run_agent
    return run_agent


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
    model: str = "gemini-3.8-live-preview",
    voice: Optional[str] = "Puck",
    language: str = "en-US",
    system_instruction: Optional[str] = None,
    tts: bool = False,
    tts_voice: str = "en-US-Chirp3-HD-Aoede",
    tts_model: str = "gemini-3.8-flash-lite-tts",
    tts_pace: float = 0.80,
    tts_style: Optional[str] = None,
    tts_accent: Optional[str] = None,
    tts_pitch: Optional[str] = None,
    tts_pace_label: Optional[str] = None,
    tts_voice_prompt: Optional[str] = None,
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
    connection_id: Optional[str] = None,
    # Selects the persona's execution architecture server-side. This is the only
    # signal that decides which persona tooling loads; the system instruction is
    # never inspected for routing. See server/persona_registry.py.
    persona_id: Optional[str] = None,
):
    await websocket.accept()
    print("WebSocket connection accepted")
    if connection_id:
        if not session_access.consume_join(session_id, connection_id):
            await websocket.close(code=1008, reason="Invalid or expired connection")
            return
    else:
        # Raw websocket clients get an isolated anonymous scope; a supplied ID
        # cannot impersonate a session created through /connect.
        session_id = str(uuid4())
    if bot_type not in diagnostic_buffer.BOT_TYPES:
        await websocket.close(code=1008, reason="Unknown bot_type")
        return
    diagnostic_buffer.bind_session(session_id, bot_type)
    stored_instruction = session_access.take_instructions(session_id)
    system_instruction = stored_instruction or system_instruction
    custom_voice_key = voice_profiles.consume(voice_profile_id)
    try:
        if bot_type == "gemini-live":
            run_agent_live = await asyncio.to_thread(load_pipeline, bot_type)
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
                persona_id=persona_id,
            )
        elif bot_type == "tts-llm-stt":
            run_agent = await asyncio.to_thread(load_pipeline, bot_type)
            await run_agent(
                websocket,
                tts_voice=tts_voice,
                tts_pace=tts_pace,
                llm_model=llm_model,
                stt_model=stt_model,
                stt_language=stt_language,
                tts_model=tts_model,
                tts_voice_prompt=tts_voice_prompt,
                tts_style=tts_style,
                tts_accent=tts_accent,
                tts_pitch=tts_pitch,
                tts_pace_label=tts_pace_label,
                system_instruction=system_instruction,
                skip_stt=skip_stt,
                vad=vad,
                custom_voice_key=custom_voice_key,
                persona_id=persona_id,
            )
    except Exception as e:
        diagnostic_buffer.append_raw_log_entry(f"Session failed: {type(e).__name__}: {e}", "ERROR")
        print(f"Exception in run_bot: {e}")


@app.get("/persona-prompt/{persona_id}")
async def persona_prompt(
    persona_id: str,
    phase: Optional[str] = None,
    engine: Optional[str] = "live",
    tone: str = "professional",
    language: str = "en-US",
) -> Dict[str, Any]:
    """Return the system prompt the backend will actually run for a persona.

    Personas whose architecture owns their prompt discard whatever the client
    sends. Without this endpoint the studio could only preview its own local
    copy, which would silently disagree with the running session.

    If `phase` is specified (e.g. SOP_02_DISCOVERY), returns the JIT
    card formatted prompt for live phase inspection (for live engine).
    In cascade engine, the monolithic prompt is always returned.
    """
    from persona_registry import (
        ArchitecturePattern,
        get_persona_architecture,
        is_persona_ui_editable,
        resolve_persona_architecture,
    )

    editable = is_persona_ui_editable(persona_id)
    architecture = resolve_persona_architecture(persona_id)
    from persona_prompt_cards import get_session_preset, get_persona_card, format_persona_prompt_card
    try:
        composed = get_session_preset(persona_id, engine=engine or "live", tone=tone, language=language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not editable and phase and engine != "cascade":
        card = get_persona_card(persona_id, phase)
        if card:
            composed = format_persona_prompt_card(persona_id, card)

    persona_arch_obj = get_persona_architecture(persona_id)
    effective_engine = engine or "live"
    try:
        if getattr(persona_arch_obj, "has_exclusive_tools", lambda eng="live": False)(effective_engine):
            raw_tools = list(persona_arch_obj.get_tool_schemas(effective_engine))
        else:
            from pipecat.adapters.schemas.function_schema import FunctionSchema
            from rag_function import search_knowledge_base_schema
            raw_tools = [
                FunctionSchema(
                    name="get_current_time",
                    description="Get the current time.",
                    properties={
                        "is_explicit_request": {
                            "type": "boolean",
                            "description": (
                                "Return `true` ONLY if the user explicitly asks for the current time or date.\n\n"
                                "- Explaining schedules or timelines.\n"
                                "- Mentioning time casually in conversation."
                            ),
                        }
                    },
                    required=["is_explicit_request"],
                ),
                search_knowledge_base_schema,
            ]
            raw_tools.extend(persona_arch_obj.get_tool_schemas(effective_engine))
    except Exception:
        raw_tools = []

    serialized_tools = []
    for t in raw_tools:
        if hasattr(t, "name"):
            serialized_tools.append({
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", ""),
                "properties": getattr(t, "properties", {}),
                "required": list(getattr(t, "required", []) or []),
            })
        elif isinstance(t, dict) and "name" in t:
            serialized_tools.append(t)

    import json as _json
    tools_json_str = _json.dumps(serialized_tools, ensure_ascii=False)
    tools_token_count = max(1, int(round(len(tools_json_str) / 3.8))) if serialized_tools else 0

    return {
        "persona_id": persona_id,
        "architecture": architecture.value,
        "editable": editable,
        "prompt": composed or "",
        "phase": phase if engine != "cascade" else None,
        "engine": engine,
        "tools": serialized_tools,
        "tools_token_count": tools_token_count,
    }


@app.post("/connect")
async def bot_connect(request: Request) -> Dict[Any, Any]:
    import json
    from urllib.parse import parse_qs, urlencode
    # Get the original query string from the incoming request (e.g., "model=...&voice=...")
    query_params_raw = request.url.query
    params_dict: Dict[str, str] = {
        k: v[-1] for k, v in parse_qs(query_params_raw, keep_blank_values=True).items()
    }

    # Finish reading and validating the request before allocating any handles.
    # Invalid requests must not occupy a session slot for the four-hour TTL.
    instructions = params_dict.pop("system_instruction", None)
    try:
        body = await request.json() if await request.body() else {}
        if not isinstance(body, dict):
            raise ValueError("Expected a configuration object")
        for field in (
            "system_instruction",
            "prompt_source",
            "persona_tone",
            "thinking_level",
            "tts_style",
            "tts_accent",
            "tts_pitch",
            "tts_pace_label",
            "tts_voice_prompt",
        ):
            if field in body and body[field] is not None and not isinstance(body[field], str):
                raise ValueError(f"Invalid {field}")
        for field in ("context_compression", "thinking", "vad"):
            if field in body and not isinstance(body[field], bool):
                raise ValueError(f"Invalid {field}")
        clone_key = body.get("custom_voice_key")
        if clone_key is not None and not isinstance(clone_key, str):
            raise ValueError("Invalid custom_voice_key")
        bot_type = params_dict.get("bot_type", "tts-llm-stt")
        if bot_type not in diagnostic_buffer.BOT_TYPES:
            raise ValueError("Unknown bot_type")

        if body.get("prompt_source") == "preset" and params_dict.get("persona_id") != "custom":
            from persona_prompt_cards import get_session_preset
            preset = get_session_preset(params_dict.get("persona_id", ""),
                engine="cascade" if bot_type == "tts-llm-stt" else "live",
                tone=body.get("persona_tone", "professional"),
                language=params_dict.get("language") or params_dict.get("stt_language", "en-US"))
            if preset:
                body["system_instruction"] = preset
        if body.get("system_instruction", "").strip():
            instructions = body["system_instruction"].strip()

        if "tools" in body:
            tools_data = body["tools"]
            params_dict["tools"] = json.dumps(tools_data) if isinstance(tools_data, (dict, list)) else str(tools_data)
        for field in ("context_compression", "thinking", "vad"):
            if field in body:
                params_dict[field] = "true" if body[field] else "false"
        if "context_compression_trigger_tokens" in body:
            try:
                raw_val = int(body["context_compression_trigger_tokens"])
                # Preserve the existing minimum and invalid-value fallback.
                params_dict["context_compression_trigger_tokens"] = str(max(5000, raw_val))
            except (ValueError, TypeError, OverflowError):
                params_dict["context_compression_trigger_tokens"] = "5000"
        if "thinking_level" in body:
            params_dict["thinking_level"] = body["thinking_level"]
        for field in ("tts_style", "tts_accent", "tts_pitch", "tts_pace_label", "tts_voice_prompt"):
            if field in body and body[field]:
                params_dict[field] = body[field]
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid session configuration")

    # Dynamically determine WebSocket scheme (ws vs wss) and host
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    ws_scheme = "wss" if scheme == "https" else "ws"
    host = request.headers.get("x-forwarded-host", request.url.netloc)

    try:
        session_id, viewer_token, connection_id = session_access.issue(
            params_dict.get("session_id"), request.headers.get("x-session-token"),
            instructions=instructions)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    profile_id = None
    try:
        params_dict.update(session_id=session_id, connection_id=connection_id)
        # Exchange credentials for a one-use handle only after validation.
        if clone_key:
            profile_id = voice_profiles.register(clone_key)
            if profile_id:
                params_dict["voice_profile_id"] = profile_id
        ws_url = f"{ws_scheme}://{host}/ws?{urlencode(params_dict)}"
        return {"ws_url": ws_url, "session_id": session_id, "diagnostic_token": viewer_token}
    except Exception:
        # These handles have not reached the caller. Release both on failure.
        voice_profiles.consume(profile_id)
        session_access.discard(session_id)
        raise HTTPException(status_code=500, detail="Unable to prepare session")


@app.get("/connect/system-prompt")
async def get_system_prompt():
    return {"system_prompt": SYSTEM_PROMPT}

def diagnostic_session(request: Request, session_id: str = Query(min_length=1, max_length=128)):
    if not session_access.authorized(session_id, request.headers.get("x-session-token")):
        raise HTTPException(status_code=403, detail="Session access denied")
    return session_id


@app.get("/api/logs")
async def get_diagnostic_logs(session_id: str = Depends(diagnostic_session), limit: int = Query(default=500, ge=1, le=1500)):
    """Recent logs and latency percentiles.

    A session identifier is mandatory; unscoped process logs are excluded.
    """
    from diagnostic_buffer import get_recent_diagnostic_logs, get_latency_summary
    return {
        "logs": get_recent_diagnostic_logs(limit, session_id=session_id),
        "latency_summary": get_latency_summary(session_id=session_id),
        "session_id": session_id,
    }

@app.get("/api/metrics/latency")
async def get_latency_metrics_endpoint(session_id: str = Depends(diagnostic_session)):
    from diagnostic_buffer import get_latency_summary
    return get_latency_summary(session_id=session_id)

@app.post("/api/logs/clear")
async def clear_diagnostic_logs_endpoint(session_id: str = Depends(diagnostic_session)):
    """Clear this session only."""
    from diagnostic_buffer import clear_diagnostic_logs
    clear_diagnostic_logs(session_id=session_id)
    return {"status": "cleared", "session_id": session_id}

@app.get("/api/trace/current")
async def get_current_trace_endpoint(session_id: str = Depends(diagnostic_session)):
    from tracing import GLOBAL_LANGSMITH_TRACER
    return {"trace_url": GLOBAL_LANGSMITH_TRACER.get_current_trace_url(session_id)}

# Mount the static files directory
possible_dist_dirs = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../demos/voice-studio/dist")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "demos/voice-studio/dist")),
    os.path.abspath("/app/demos/voice-studio/dist"),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../client/dist")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "client/dist")),
    os.path.abspath("/app/client/dist"),
]

client_dist_dir = next((d for d in possible_dist_dirs if os.path.exists(d)), None)

if client_dist_dir:
    app.mount("/assets", StaticFiles(directory=os.path.join(client_dist_dir, "assets")), name="assets")
    
    personas_dir = os.path.join(client_dist_dir, "personas")
    if os.path.exists(personas_dir):
        app.mount("/personas", StaticFiles(directory=personas_dir), name="personas")

    @app.get("/favicon.svg")
    async def read_favicon():
        fav_path = os.path.join(client_dist_dir, "favicon.svg")
        if os.path.exists(fav_path):
            return FileResponse(fav_path)
        return Response(status_code=404)

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
