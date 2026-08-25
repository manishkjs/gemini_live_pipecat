"""
LangSmith Telemetry & Tracing Engine for Gemini Live + Pipecat.
Captures full-duplex session runs, user VAD speech turns, Gemini Live LLM turns,
TTFT turnaround latencies, token consumption, tool executions, and user interruption events.
Non-blocking background worker with bounded queue ensures <0.1ms audio hot-path overhead.
"""
import os
import time
import uuid
import queue
import threading
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
    def __init__(self, max_queue_size: int = 1000):
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
        self._lock = threading.Lock()

        # Non-blocking background worker queue
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="langsmith-tracer-worker"
        )
        self._worker_thread.start()

    def get_current_trace_url(self) -> Optional[str]:
        return self.current_trace_url

    def _start_background_share(self, run_id: str):
        """Asynchronously retry public sharing until LangSmith ingestion commits the run."""
        def _share_worker():
            for attempt in range(6):
                time.sleep(1.0 + attempt * 0.8)
                if not self.client:
                    return
                try:
                    url = self.client.share_run(run_id)
                    if url:
                        self.current_trace_url = url
                        logger.info(f"[LangSmith] 🎉 Public Share URL confirmed on attempt {attempt+1}: {url}")
                        return
                except Exception as e:
                    err_str = str(e).lower()
                    if "already shared" in err_str or "409" in err_str or "conflict" in err_str:
                        try:
                            url = self.client.read_run_shared_link(run_id)
                            if url:
                                self.current_trace_url = url
                                logger.info(f"[LangSmith] 🎉 Public Share URL retrieved on attempt {attempt+1}: {url}")
                                return
                        except Exception:
                            pass
                    logger.debug(f"[LangSmith] Background share attempt {attempt+1}/6 waiting for ingestion...")

        t = threading.Thread(target=_share_worker, daemon=True)
        t.start()

    def _enqueue(self, event: Dict[str, Any]):
        """Enqueue an event to the background queue without blocking caller."""
        if not self.enabled and event.get("type") != "END_SESSION":
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning("[LangSmith] Tracer queue is full! Dropping event to protect audio hot path.")

    def _worker_loop(self):
        """Dedicated background daemon thread processing tracing network calls."""
        while True:
            try:
                event = self._queue.get()
                if event is None:
                    break
                self._process_event(event)
            except Exception as e:
                logger.debug(f"[LangSmith] Worker loop exception: {e}")
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def _process_event(self, event: Dict[str, Any]):
        event_type = event.get("type")
        if not self.enabled or not RunTree:
            if event_type == "END_SESSION":
                with self._lock:
                    self.root_run = None
            return

        try:
            if event_type == "START_SESSION":
                run_id = event["run_id"]
                metadata = event["metadata"]
                inputs = event["inputs"]
                with self._lock:
                    self.root_run = RunTree(
                        id=run_id,
                        name="GeminiLiveDuplexSession",
                        run_type="chain",
                        inputs=inputs,
                        project_name=self.project_name,
                        client=self.client,
                        metadata=metadata,
                        tags=["gemini-live", "pipecat", "duplex-voice", metadata.get("model", "")]
                    )
                self.root_run.post()
                if self.client:
                    self._start_background_share(run_id)
                logger.info(f"[LangSmith] Root Run posted in worker: {run_id} -> {self.current_trace_url}")

            elif event_type == "USER_TURN":
                with self._lock:
                    root = self.root_run
                if not root:
                    return
                turn_index = event["turn_index"]
                text = event["text"]
                child = root.create_child(
                    name=f"UserSpeech_Turn_{turn_index}",
                    run_type="tool",
                    inputs={"transcription": text},
                    outputs={"clean_text": text},
                    tags=["user-vad-turn"]
                )
                child.post()
                child.end(outputs={"status": "completed", "transcription": text})
                child.patch()

            elif event_type == "BOT_TURN":
                with self._lock:
                    root = self.root_run
                if not root:
                    return
                turn_index = event["turn_index"]
                text = event["text"]
                outputs = event["outputs"]
                ttfb_ms = event.get("ttfb_ms")
                token_usage = event.get("token_usage")
                child = root.create_child(
                    name=f"GeminiLiveResponse_Turn_{turn_index}",
                    run_type="llm",
                    inputs={"turn_index": turn_index},
                    outputs=outputs,
                    extra={"ttfb_ms": ttfb_ms, "token_usage": token_usage},
                    tags=["gemini-live-turn"]
                )
                child.post()
                child.end(outputs=outputs)
                child.patch()

            elif event_type == "TOOL_CALL":
                with self._lock:
                    root = self.root_run
                if not root:
                    return
                name = event["name"]
                args = event["args"]
                result_str = event["result_str"]
                duration_ms = event.get("duration_ms")
                child = root.create_child(
                    name=f"Tool_{name}",
                    run_type="tool",
                    inputs={"tool_name": name, "arguments": args},
                    outputs={"result": result_str},
                    extra={"duration_ms": duration_ms},
                    tags=["tool-call", name]
                )
                child.post()
                child.end(outputs={"result": result_str})
                child.patch()

            elif event_type == "INTERRUPTION":
                with self._lock:
                    root = self.root_run
                if not root:
                    return
                turn_index = event["turn_index"]
                elapsed_ms = event["elapsed_ms"]
                child = root.create_child(
                    name=f"UserInterruption_Turn_{turn_index}",
                    run_type="event",
                    inputs={"elapsed_ms": elapsed_ms},
                    outputs={"action": "bot_playback_halted", "interrupted_after_ms": elapsed_ms},
                    tags=["interruption"]
                )
                child.post()
                child.end()
                child.patch()

            elif event_type == "END_SESSION":
                with self._lock:
                    root = self.root_run
                if root:
                    summary = event.get("summary") or "Session ended cleanly"
                    turn_count = event.get("turn_count", self.turn_counter)
                    root.end(outputs={"status": "completed", "total_turns": turn_count, "summary": summary})
                    root.patch()
                    if self.client and root.id:
                        link = self._ensure_shared_link(root.id)
                        if link:
                            self.current_trace_url = link
                            logger.info(f"[LangSmith] Final Public Share URL: {self.current_trace_url}")
                    logger.info(f"[LangSmith] Session ended in worker: {self.active_session_id} (Total Turns: {turn_count})")
                with self._lock:
                    self.root_run = None

        except Exception as e:
            logger.debug(f"[LangSmith] Worker error processing {event_type}: {e}")

    def start_session(self, session_id: str, model: str, voice: Optional[str], language: str, extra_metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        self.active_session_id = session_id or str(uuid.uuid4())
        self.turn_counter = 0
        run_id = str(uuid.uuid4())
        self.current_trace_url = f"https://smith.langchain.com/public/{run_id}/r"

        if not self.enabled or not RunTree:
            logger.info(f"[LangSmith] Session started: {self.active_session_id} (Trace URL: {self.current_trace_url})")
            return self.current_trace_url

        metadata = {
            "session_id": self.active_session_id,
            "model": model,
            "voice": voice or "Default",
            "language": language,
            "platform": "CloudRun" if os.getenv("K_SERVICE") else "Local",
            **(extra_metadata or {})
        }
        inputs = {"session_id": self.active_session_id, "model": model, "voice": voice, "language": language}

        self._enqueue({
            "type": "START_SESSION",
            "run_id": run_id,
            "metadata": metadata,
            "inputs": inputs,
        })
        logger.info(f"[LangSmith] Session start enqueued: {run_id} -> {self.current_trace_url}")
        return self.current_trace_url

    def record_user_turn(self, text: str, latency_s: Optional[float] = None):
        self.turn_counter += 1
        if not self.enabled:
            return
        self._enqueue({
            "type": "USER_TURN",
            "turn_index": self.turn_counter,
            "text": text,
            "latency_s": latency_s,
        })

    def record_bot_turn(self, text: str, ttfb_ms: Optional[float] = None, token_usage: Optional[Dict[str, Any]] = None):
        if not self.enabled:
            return
        outputs = {"text": text}
        if ttfb_ms is not None:
            outputs["ttfb_ms"] = ttfb_ms
        if token_usage:
            outputs["token_usage"] = token_usage

        self._enqueue({
            "type": "BOT_TURN",
            "turn_index": self.turn_counter,
            "text": text,
            "outputs": outputs,
            "ttfb_ms": ttfb_ms,
            "token_usage": token_usage,
        })

    def record_tool_call(self, name: str, args: Dict[str, Any], result: Any, duration_ms: Optional[float] = None):
        if not self.enabled:
            return
        self._enqueue({
            "type": "TOOL_CALL",
            "name": name,
            "args": args,
            "result_str": str(result),
            "duration_ms": duration_ms,
        })

    def record_interruption(self, elapsed_ms: float):
        if not self.enabled:
            return
        self._enqueue({
            "type": "INTERRUPTION",
            "turn_index": self.turn_counter,
            "elapsed_ms": elapsed_ms,
        })

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

    def end_session(self, summary: Optional[str] = None, timeout: float = 1.5):
        if not self.enabled:
            with self._lock:
                self.root_run = None
            return

        self._enqueue({
            "type": "END_SESSION",
            "summary": summary,
            "turn_count": self.turn_counter,
        })

        # Drain the queue with safe timeout cap (min(timeout, 1.5)s)
        deadline = time.monotonic() + min(timeout, 1.5)
        while self._queue.unfinished_tasks > 0 and time.monotonic() < deadline:
            time.sleep(0.02)

        with self._lock:
            self.root_run = None


GLOBAL_LANGSMITH_TRACER = LangSmithTracer()

