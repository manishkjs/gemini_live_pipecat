"""
LangSmith Telemetry & Tracing Engine for Gemini Live + Pipecat.
Captures full-duplex session runs, user VAD speech turns, Gemini Live LLM turns,
TTFT turnaround latencies, token consumption, tool executions, and user interruption events.
"""
import os
import time
import uuid
from typing import Optional, Dict, Any
from datetime import datetime
from loguru import logger

try:
    from langsmith import Client as LangSmithClient
    from langsmith.run_trees import RunTree
except ImportError:
    LangSmithClient = None
    RunTree = None


class LangSmithTracer:
    def __init__(self):
        self.api_key = os.getenv("LANGSMITH_API_KEY")
        self.project_name = os.getenv("LANGSMITH_PROJECT") or "gemini-live-pipecat"
        self.endpoint = os.getenv("LANGSMITH_ENDPOINT") or "https://api.smith.langchain.com"
        self.enabled = bool(self.api_key and os.getenv("LANGSMITH_TRACING", "true").lower() in ("true", "1"))
        
        self.client: Optional[LangSmithClient] = None
        if self.enabled and LangSmithClient:
            try:
                self.client = LangSmithClient(api_key=self.api_key, api_url=self.endpoint)
                logger.info(f"[LangSmith] Tracing enabled for project: '{self.project_name}'")
            except Exception as e:
                logger.warning(f"[LangSmith] Failed to initialize client: {e}")
                self.enabled = False

        self.active_session_id: Optional[str] = None
        self.root_run: Optional[RunTree] = None
        self.current_trace_url: Optional[str] = None
        self.turn_counter: int = 0

    def get_current_trace_url(self) -> Optional[str]:
        return self.current_trace_url

    def start_session(self, session_id: str, model: str, voice: Optional[str], language: str, extra_metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        self.active_session_id = session_id or str(uuid.uuid4())
        self.turn_counter = 0
        
        run_id = str(uuid.uuid4())
        self.current_trace_url = f"https://smith.langchain.com/public/{run_id}/r"

        if not self.enabled or not RunTree:
            logger.info(f"[LangSmith] Session started: {self.active_session_id} (Trace URL: {self.current_trace_url})")
            return self.current_trace_url

        try:
            metadata = {
                "session_id": self.active_session_id,
                "model": model,
                "voice": voice or "Default",
                "language": language,
                "platform": "CloudRun" if os.getenv("K_SERVICE") else "Local",
                **(extra_metadata or {})
            }
            self.root_run = RunTree(
                id=run_id,
                name="GeminiLiveDuplexSession",
                run_type="chain",
                inputs={"session_id": self.active_session_id, "model": model, "voice": voice, "language": language},
                project_name=self.project_name,
                client=self.client,
                metadata=metadata,
                tags=["gemini-live", "pipecat", "duplex-voice", model]
            )
            self.root_run.post()
            
            # Create a public share link with token baked in so sales folks can open without credentials
            if self.client:
                try:
                    public_url = self.client.share_run(run_id)
                    if public_url:
                        self.current_trace_url = public_url
                        logger.info(f"[LangSmith] Created Public Share Link: {public_url}")
                except Exception as se:
                    logger.debug(f"[LangSmith] Notice on share_run: {se}")

            logger.info(f"[LangSmith] Root Run posted: {run_id} -> {self.current_trace_url}")
        except Exception as e:
            logger.error(f"[LangSmith] Failed to start root run: {e}")

        return self.current_trace_url

    def record_user_turn(self, text: str, latency_s: Optional[float] = None):
        self.turn_counter += 1
        if not self.enabled or not self.root_run:
            return
        try:
            child = self.root_run.create_child(
                name=f"UserSpeech_Turn_{self.turn_counter}",
                run_type="tool",
                inputs={"transcription": text},
                outputs={"clean_text": text},
                tags=["user-vad-turn"]
            )
            child.post()
            child.end(outputs={"status": "completed", "transcription": text})
            child.patch()
        except Exception as e:
            logger.debug(f"[LangSmith] User turn trace error: {e}")

    def record_bot_turn(self, text: str, ttfb_ms: Optional[float] = None, token_usage: Optional[Dict[str, Any]] = None):
        if not self.enabled or not self.root_run:
            return
        try:
            outputs = {"text": text}
            if ttfb_ms is not None:
                outputs["ttfb_ms"] = ttfb_ms
            if token_usage:
                outputs["token_usage"] = token_usage

            child = self.root_run.create_child(
                name=f"GeminiLiveResponse_Turn_{self.turn_counter}",
                run_type="llm",
                inputs={"turn_index": self.turn_counter},
                outputs=outputs,
                extra={"ttfb_ms": ttfb_ms, "token_usage": token_usage},
                tags=["gemini-live-turn"]
            )
            child.post()
            child.end(outputs=outputs)
            child.patch()
        except Exception as e:
            logger.debug(f"[LangSmith] Bot turn trace error: {e}")

    def record_tool_call(self, name: str, args: Dict[str, Any], result: Any, duration_ms: Optional[float] = None):
        if not self.enabled or not self.root_run:
            return
        try:
            child = self.root_run.create_child(
                name=f"Tool_{name}",
                run_type="tool",
                inputs={"tool_name": name, "arguments": args},
                outputs={"result": str(result)},
                extra={"duration_ms": duration_ms},
                tags=["tool-call", name]
            )
            child.post()
            child.end(outputs={"result": str(result)})
            child.patch()
        except Exception as e:
            logger.debug(f"[LangSmith] Tool call trace error: {e}")

    def record_interruption(self, elapsed_ms: float):
        if not self.enabled or not self.root_run:
            return
        try:
            child = self.root_run.create_child(
                name=f"UserInterruption_Turn_{self.turn_counter}",
                run_type="event",
                inputs={"elapsed_ms": elapsed_ms},
                outputs={"action": "bot_playback_halted", "interrupted_after_ms": elapsed_ms},
                tags=["interruption"]
            )
            child.post()
            child.end()
            child.patch()
        except Exception as e:
            logger.debug(f"[LangSmith] Interruption trace error: {e}")

    def _ensure_shared_link(self, run_id: str) -> Optional[str]:
        if not self.client or not run_id:
            return None
        try:
            return self.client.share_run(run_id)
        except Exception as e:
            err_str = str(e).lower()
            if "already shared" in err_str or "409" in err_str or "conflict" in err_str:
                try:
                    return self.client.read_run_shared_link(run_id)
                except Exception:
                    pass
            logger.debug(f"[LangSmith] share_run notice: {e}")
        return None

    def end_session(self, summary: Optional[str] = None):
        if not self.enabled or not self.root_run:
            return
        try:
            self.root_run.end(outputs={"status": "completed", "total_turns": self.turn_counter, "summary": summary or "Session ended cleanly"})
            self.root_run.patch()
            
            if self.client and self.root_run.id:
                link = self._ensure_shared_link(self.root_run.id)
                if link:
                    self.current_trace_url = link
                    logger.info(f"[LangSmith] Final Public Share URL: {self.current_trace_url}")

            logger.info(f"[LangSmith] Session ended: {self.active_session_id} (Total Turns: {self.turn_counter})")
        except Exception as e:
            logger.error(f"[LangSmith] Failed to end session run: {e}")
        finally:
            self.root_run = None


GLOBAL_LANGSMITH_TRACER = LangSmithTracer()
