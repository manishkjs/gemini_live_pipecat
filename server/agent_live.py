import os
import websockets
import json
import asyncio
import re
import google.auth
from typing import Optional, List, Dict, Any
from loguru import logger
from fastapi import WebSocket
from datetime import datetime
import time

from rag_function import search_knowledge_base_schema, search_knowledge_base_handler
from diagnostic_buffer import append_diagnostic_log
from tracing import GLOBAL_LANGSMITH_TRACER

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_start import VADUserTurnStartStrategy, TranscriptionUserTurnStartStrategy
try:
    from pipecat.services.google.gemini_live.vertex.llm import GeminiLiveVertexLLMService
except ImportError:
    from pipecat.services.google.gemini_live.llm_vertex import GeminiLiveVertexLLMService
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, InputParams, GeminiModalities
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.services.google.tts import GoogleTTSService
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

from pipecat_whisker import WhiskerObserver
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.frames.frames import (
    EndTaskFrame,
    Frame,
    InterruptionFrame,
    CancelFrame,
    LLMMessagesAppendFrame,
    TextFrame,
    OutputTransportMessageFrame,
    InputTransportMessageFrame,
    StartFrame,
    EndFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    TranscriptionFrame,
    LLMRunFrame
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transcriptions.language import Language
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import AdapterType, ToolsSchema
from pipecat.services.llm_service import FunctionCallParams
# from pipecat.processors.user_idle_processor import UserIdleProcessor
from system_prompt import SYSTEM_PROMPT

from google.genai.types import (
    AudioTranscriptionConfig,
    AutomaticActivityDetection,
    ContextWindowCompressionConfig,
    GenerationConfig,
    LiveConnectConfig,
    MediaResolution,
    Modality,
    RealtimeInputConfig,
    SessionResumptionConfig,
    SlidingWindow,
    SpeechConfig,
    VoiceConfig,
    HttpOptions,
    Content,
    Part
)

SYSTEM_INSTRUCTION = SYSTEM_PROMPT

class CustomProtobufSerializer(ProtobufFrameSerializer):
    async def serialize(self, frame: Frame) -> bytes | None:
        if isinstance(frame, (InterruptionFrame, CancelFrame)):
            return None
        data = await super().serialize(frame)
        return data.encode("utf-8") if isinstance(data, str) else data

async def get_current_time(params: FunctionCallParams):
    await params.result_callback(
        {"time": datetime.now().strftime("%A, %B %d, %Y %I:%M %p")}
    )


class GeminiSessionLoggerMixin:
    """Mixin to add session ID logging, token usage tracking, and repeat-on-filler."""

    # ── Repeat-on-filler: intercept at API level ──────────────────────

    async def start_ttfb_metrics(self):
        self._my_ttfb_start = time.time()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if hasattr(self, '_my_ttfb_start') and self._my_ttfb_start:
            self._current_turn_ttft = time.time() - self._my_ttfb_start
            logger.info(f"Custom TTFT calculation: {self._current_turn_ttft}s")
            ttfb_ms = self._current_turn_ttft * 1000.0
            append_diagnostic_log("⚡ TTFB Latency", f"Bot audio turnaround inside {round(ttfb_ms, 1)} ms", ttfb_ms=ttfb_ms)
            
            # Stream llm_latency metric frame to UI client
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'metrics',
                    'payload': {'type': 'llm_latency', 'value': self._current_turn_ttft}
                }
            }))
            self._my_ttfb_start = None

    # Max wall-clock time a tool lock may suppress interruptions before self-healing.
    # Guards against a handler that raises before emitting FunctionCallResultFrame,
    # which would otherwise leave the bot permanently uninterruptible.
    TOOL_LOCK_MAX_HOLD_SECS = 8.0

    def _lock_tools(self, reason: str):
        self._active_tools_in_flight = getattr(self, '_active_tools_in_flight', 0) + 1
        self._frame_locked_tools = True
        self._tool_lock_started_at = time.monotonic()
        logger.info(f"[AntiCancel] Locked _active_tools_in_flight={self._active_tools_in_flight} at T=0ms on {reason}")

    def _release_tools(self, reason: str):
        self._active_tools_in_flight = max(0, getattr(self, '_active_tools_in_flight', 1) - 1)
        self._frame_locked_tools = False
        self._tool_lock_started_at = None
        logger.info(f"[AntiCancel] Released _active_tools_in_flight={self._active_tools_in_flight} on {reason}")

    def _tools_in_flight(self) -> bool:
        """True while a tool call is genuinely executing. Self-heals a stuck lock."""
        if getattr(self, '_active_tools_in_flight', 0) <= 0:
            return False
        started = getattr(self, '_tool_lock_started_at', None)
        if started and (time.monotonic() - started) > self.TOOL_LOCK_MAX_HOLD_SECS:
            logger.warning(
                f"[AntiCancel] Tool lock held >{self.TOOL_LOCK_MAX_HOLD_SECS}s without a result frame. "
                "Force-releasing so the user can interrupt again."
            )
            self._active_tools_in_flight = 0
            self._frame_locked_tools = False
            self._tool_lock_started_at = None
            return False
        return True

    async def _run_function_call(self, tool_call):
        locked_by_method = False
        if not getattr(self, '_frame_locked_tools', False):
            self._active_tools_in_flight = getattr(self, '_active_tools_in_flight', 0) + 1
            self._tool_lock_started_at = time.monotonic()
            locked_by_method = True
        try:
            return await super()._run_function_call(tool_call)
        finally:
            if locked_by_method:
                self._active_tools_in_flight = max(0, getattr(self, '_active_tools_in_flight', 1) - 1)
                if self._active_tools_in_flight == 0:
                    self._tool_lock_started_at = None

    async def _cancel_function_call(self, function_name: str | None):
        """Block Pipecat from cancelling an in-flight tool on user interruption."""
        if getattr(self, '_active_tools_in_flight', 0) > 0:
            logger.info(
                f"[AntiCancel] Refusing to cancel in-flight function call '{function_name}' "
                "on user audio interruption. Tool will run to completion."
            )
        return

    async def process_frame(self, frame, direction):
        """Guarantee memory tool calls complete despite user audio interruptions."""
        frame_type_name = type(frame).__name__
        if frame_type_name in ("FunctionCallInProgressFrame", "FunctionCallsStartedFrame", "FunctionCallFromLLM"):
            if not getattr(self, '_frame_locked_tools', False):
                self._lock_tools(f"frame {frame_type_name}")
        elif frame_type_name == "FunctionCallResultFrame":
            res_str = str(getattr(frame, 'result', getattr(frame, 'content', '')))
            if len(res_str) > 150:
                append_diagnostic_log("Tool Output", f"Result -> Model: {res_str[:150]}...")
            else:
                append_diagnostic_log("Tool Output", f"Result -> Model:\n{res_str}")
            if getattr(self, '_frame_locked_tools', False):
                self._release_tools(f"frame {frame_type_name}")
        elif frame_type_name == "FunctionCallCancelFrame":
            # A cancel slipped through (e.g. LLM-driven async tool cancellation).
            # Drop the frame so downstream never sees the tool as dead, but always
            # release the lock so interruptions work again on the next turn.
            in_flight = self._tools_in_flight()
            if getattr(self, '_frame_locked_tools', False):
                self._release_tools(f"frame {frame_type_name}")
            if in_flight:
                logger.info("[AntiCancel] Suppressed FunctionCallCancelFrame for an in-flight tool call.")
                return

        # NOTE: CancelFrame is deliberately NOT suppressed. It is the pipeline
        # shutdown signal (client disconnect / task cancel); swallowing it leaks
        # the Cloud Run session forever.
        if isinstance(frame, (InterruptionFrame, UserStartedSpeakingFrame)):
            if self._tools_in_flight():
                logger.info(
                    f"[AntiCancel] Suppressing interruption ({frame_type_name}) during active tool call "
                    f"({self._active_tools_in_flight} in flight)."
                )
                return

        if isinstance(frame, InterruptionFrame):
            if not hasattr(self, '_repeat_on_filler_pending'):
                self._repeat_on_filler_pending = False
            self._repeat_on_filler_pending = True
            logger.info("[RepeatOnFiller] Interruption detected. Watching for filler.")
            
            if getattr(self, '_bot_turn_text_buffer', '').strip():
                interrupted_text = self._bot_turn_text_buffer.strip()
                append_diagnostic_log("🤖 Bot Response (Interrupted)", f'"{interrupted_text}..."')
                self._bot_turn_text_buffer = ""

            elapsed_ms = None
            if hasattr(self, '_my_ttfb_start') and self._my_ttfb_start:
                elapsed_ms = round((time.time() - self._my_ttfb_start) * 1000.0, 1)
                append_diagnostic_log("⚡ Interruption", f"Turn interrupted by user after {elapsed_ms} ms")
                self._my_ttfb_start = None

            # Metric Streaming: Interruption
            metric_payload: Dict[str, Any] = {'type': 'interruption', 'count': 1}
            if elapsed_ms is not None:
                metric_payload['elapsed_ms'] = elapsed_ms

            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'metrics',
                    'payload': metric_payload
                }
            }))

        await super().process_frame(frame, direction)

    async def _push_user_transcription(self, sentence: str, result=None):
        """Emit consolidated complete sentences for user speech."""
        await super()._push_user_transcription(sentence, result=result)
        clean_sentence = sentence.strip()
        if clean_sentence:
            append_diagnostic_log("💬 User Speech", f'"{clean_sentence}"')
            GLOBAL_LANGSMITH_TRACER.record_user_turn(clean_sentence)
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'transcription',
                    'participant': 'User',
                    'text': clean_sentence
                }
            }))

    async def _handle_msg_input_transcription(self, message):
        """Override to detect ≤2-word fillers after an interruption and auto-repeat."""
        if not message.server_content.input_transcription:
            return await super()._handle_msg_input_transcription(message)

        text = message.server_content.input_transcription.text
        if not text:
            return await super()._handle_msg_input_transcription(message)

        # Accumulate post-interruption text in our own buffer
        if getattr(self, '_repeat_on_filler_pending', False):
            if not hasattr(self, '_post_interruption_buffer'):
                self._post_interruption_buffer = ""
            self._post_interruption_buffer += text
            logger.debug(
                f"[RepeatOnFiller] Accumulating chunk: '{text.strip()}' "
                f"(buffer: '{self._post_interruption_buffer.strip()}')"
            )

        # Let parent handle sentence buffering and trigger _push_user_transcription on full sentence
        await super()._handle_msg_input_transcription(message)

        # After parent processes, check if our buffer forms a complete sentence
        if getattr(self, '_repeat_on_filler_pending', False):
            buffer = getattr(self, '_post_interruption_buffer', '').strip()
            if not buffer:
                return

            has_sentence_end = bool(re.search(r'[.।!?\n]', buffer))
            user_stopped = not getattr(self, '_user_is_speaking', True)

            if has_sentence_end or user_stopped:
                filler_max_words = getattr(self, '_filler_max_words', 2)
                clean = buffer.rstrip('।.!?\n').strip()
                word_count = len(clean.split()) if clean else 0

                if word_count <= filler_max_words:
                    logger.info(
                        f"[RepeatOnFiller] Filler detected: '{buffer}' "
                        f"({word_count} word(s)). Sending repeat instruction."
                    )
                    self._repeat_on_filler_pending = False
                    self._post_interruption_buffer = ""
                    await self._send_repeat_instruction(buffer)
                else:
                    logger.info(
                        f"[RepeatOnFiller] Genuine interruption: '{buffer}' "
                        f"({word_count} words). No repeat needed."
                    )
                    self._repeat_on_filler_pending = False
                    self._post_interruption_buffer = ""

    async def _handle_msg_output_transcription(self, message):
        await super()._handle_msg_output_transcription(message)
        if message.server_content.output_transcription and message.server_content.output_transcription.text:
            text = message.server_content.output_transcription.text
            
            # Accumulate text for the complete bot turn
            if not hasattr(self, '_bot_turn_text_buffer'):
                self._bot_turn_text_buffer = ""
            self._bot_turn_text_buffer += text
            
            # If text chunk arrived before audio stop_ttfb_metrics, calculate TTFT immediately
            if getattr(self, '_current_turn_ttft', None) is None and getattr(self, '_my_ttfb_start', None) is not None:
                self._current_turn_ttft = time.time() - self._my_ttfb_start
                ttfb_ms = self._current_turn_ttft * 1000.0
                append_diagnostic_log("⚡ TTFB Latency", f"Bot text turnaround inside {round(ttfb_ms, 1)} ms", ttfb_ms=ttfb_ms)
                self._my_ttfb_start = None
                
                # Also push metric frame immediately
                await self.push_frame(OutputTransportMessageFrame(message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        'type': 'metrics',
                        'payload': {'type': 'llm_latency', 'value': self._current_turn_ttft}
                    }
                }))

            ttft = getattr(self, '_current_turn_ttft', None)
            message_data = {
                'type': 'transcription',
                'participant': 'Bot',
                'text': text
            }
            if ttft is not None:
                message_data['ttft'] = ttft
                self._current_turn_ttft = None
                
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": message_data
            }))

    async def _handle_msg_turn_complete(self, message):
        await super()._handle_msg_turn_complete(message)
        if getattr(self, '_bot_turn_text_buffer', '').strip():
            full_bot_text = self._bot_turn_text_buffer.strip()
            append_diagnostic_log("🤖 Bot Response", f'"{full_bot_text}"')
            GLOBAL_LANGSMITH_TRACER.record_bot_turn(
                full_bot_text,
                ttfb_ms=getattr(self, '_current_turn_ttft', 0.0) * 1000.0 if getattr(self, '_current_turn_ttft', None) else None,
                token_usage=getattr(self, '_last_turn_usage', None)
            )
            self._bot_turn_text_buffer = ""

    async def _send_repeat_instruction(self, filler_text: str):
        """Send a user-role prompt telling the model to repeat itself."""
        if self._disconnecting or not self._session:
            return
        try:
            await self._create_single_response([{
                "role": "user",
                "content": (
                    f"The user just said '{filler_text}' which is a short "
                    f"filler/acknowledgment while you were speaking. They did NOT "
                    f"ask a new question. Please REPEAT your previous response "
                    f"from the beginning — resume exactly what you were saying "
                    f"before the interruption."
                ),
            }])
            logger.info("[RepeatOnFiller] Repeat instruction sent to model.")
        except Exception as e:
            logger.error(f"[RepeatOnFiller] Error sending repeat instruction: {e}")

    # ── Session ID & token usage logging ──────────────────────────────

    async def _handle_session_ready(self, session):
        await super()._handle_session_ready(session)
        session_id = getattr(session, 'session_id', None) or getattr(session, 'id', None)
        if session_id:
            logger.info(f"Session ID Established: {session_id}")

    async def _handle_msg_usage_metadata(self, message):
        await super()._handle_msg_usage_metadata(message)
        
        if not message.usage_metadata:
            return
            
        usage = message.usage_metadata
        
        # Log token usage in logs
        def format_details(details):
            if not details: return ""
            return " (" + ", ".join([f"{d.modality}: {d.token_count}" for d in details]) + ")"

        logger.info(
            f"Turn Token Usage:\n"
            f"  - Prompt: {getattr(usage, 'prompt_token_count', 0)}{format_details(getattr(usage, 'prompt_tokens_details', []))}\n"
            f"  - Cached Content: {getattr(usage, 'cached_content_token_count', 0)}{format_details(getattr(usage, 'cache_tokens_details', []))}\n"
            f"  - Response: {getattr(usage, 'response_token_count', 0)}{format_details(getattr(usage, 'response_tokens_details', []))}\n"
            f"  - Tool Use Prompt: {getattr(usage, 'tool_use_prompt_token_count', 0)}{format_details(getattr(usage, 'tool_use_prompt_tokens_details', []))}\n"
            f"  - Thoughts: {getattr(usage, 'thoughts_token_count', 0)}\n"
            f"  - Total: {getattr(usage, 'total_token_count', 0)}"
        )

        # Stream token usage downstream to client
        prompt_details = {}
        if hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
            for d in usage.prompt_tokens_details:
                prompt_details[d.modality.lower()] = d.token_count

        response_details = {}
        if hasattr(usage, 'response_tokens_details') and usage.response_tokens_details:
            for d in usage.response_tokens_details:
                response_details[d.modality.lower()] = d.token_count

        usage_dict = {
            "prompt_token_count": getattr(usage, 'prompt_token_count', 0),
            "response_token_count": getattr(usage, 'response_token_count', 0),
            "total_token_count": getattr(usage, 'total_token_count', 0),
            "prompt_details": prompt_details,
            "response_details": response_details
        }
        
        await self.push_frame(OutputTransportMessageFrame(message={
            "label": "rtvi-ai",
            "type": "server-message",
            "data": {
                'type': 'metrics',
                'payload': {
                    'type': 'usage',
                    'usage': usage_dict
                }
            }
        }))

    async def _handle_msg_turn_complete(self, message):
        await super()._handle_msg_turn_complete(message)
        
        # Metric Streaming: Turn Complete
        await self.push_frame(OutputTransportMessageFrame(message={
            "label": "rtvi-ai",
            "type": "server-message",
            "data": {
                'type': 'metrics',
                'payload': {'type': 'turn_complete'}
            }
        }))

    async def _handle_msg_tool_call(self, message):
        # Metric Streaming: Tool Call
        tool_calls = []
        if hasattr(message.tool_call, 'function_calls'):
            for fc in message.tool_call.function_calls:
                 tool_calls.append({"name": fc.name, "args": fc.args})
        await self.push_frame(OutputTransportMessageFrame(message={
            "label": "rtvi-ai",
            "type": "server-message",
            "data": {
                'type': 'metrics',
                'payload': {'type': 'tool_call', 'tool': tool_calls}
            }
        }))
        
        await super()._handle_msg_tool_call(message)

    async def _connection_task_handler(self, config):
        from pipecat.services.google.gemini_live.vertex.llm import GeminiLiveVertexLLMService
        if isinstance(self, GeminiLiveVertexLLMService):
            # Set transcription language to match the session's configured language (Vertex AI Enterprise only)
            from google.genai.types import AudioTranscriptionConfig
            lang_code = getattr(self, "_language_code", "en-US")
            config.input_audio_transcription = AudioTranscriptionConfig(language_codes=[lang_code])
            config.output_audio_transcription = AudioTranscriptionConfig(language_codes=[lang_code])
        
        await super()._connection_task_handler(config)

class CustomGeminiLiveVertexLLMService(GeminiSessionLoggerMixin, GeminiLiveVertexLLMService): pass
class CustomGeminiLiveLLMService(GeminiSessionLoggerMixin, GeminiLiveLLMService):
    def create_client(self):
        """Create the Gemini API client instance forcing AI Studio mode."""
        import os
        from google.genai import Client
        
        # Temporarily unset Vertex env vars to force AI Studio mode
        project = os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
        creds = os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        
        logger.info("Creating Client forcing AI Studio mode (unsetting project/creds temporarily)...")
        try:
            self._client = Client(api_key=self._api_key, vertexai=False, http_options=self._http_options)
        finally:
            # Restore them
            if project: os.environ["GOOGLE_CLOUD_PROJECT"] = project
            if creds: os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds






async def dynamic_tool_handler(params: FunctionCallParams):
    logger.info(f"Dynamic tool called: {params.function_name} with args: {params.arguments}")
    await params.result_callback({"status": "success", "message": f"Tool {params.function_name} called successfully"})

class UserIdleProcessor(FrameProcessor):
    def __init__(self, callback, timeout: float = 10.0):
        super().__init__()
        self.callback = callback
        self.timeout = timeout
        self.retry_count = 0
        self.timer_task = None
        self.last_activity = time.monotonic()
        self._bot_speaking = False

    async def _idle_timer(self):
        try:
            while True:
                await asyncio.sleep(0.2) # tick faster for sub-second precision
                if self._bot_speaking:
                    self.last_activity = time.monotonic()
                    continue
                if time.monotonic() - self.last_activity >= self.timeout:
                    self.retry_count += 1
                    logger.info(f"[UserIdleProcessor] Idle timeout fired, retry_count={self.retry_count}")
                    should_continue = await self.callback(self, self.retry_count)
                    if not should_continue:
                        break
                    self.last_activity = time.monotonic()
        except asyncio.CancelledError:
            pass

    async def start_timer(self):
        self.cancel_timer()
        self.last_activity = time.monotonic()
        self.timer_task = asyncio.create_task(self._idle_timer())

    def cancel_timer(self):
        if self.timer_task:
            self.timer_task.cancel()
            self.timer_task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        if isinstance(frame, StartFrame):
            await self.start_timer()
        elif isinstance(frame, (EndFrame, CancelFrame)):
            self.cancel_timer()

        # Handle bot speaking status boundaries to suspend/resume silence timer
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self.last_activity = time.monotonic()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self.last_activity = time.monotonic()
            logger.info(f"[UserIdleProcessor] Bot finished speaking. Starting silence countdown.")

        # Reset timer ONLY on active speech activity (VAD or transcription/text frames)
        if isinstance(frame, (UserStartedSpeakingFrame, UserStoppedSpeakingFrame, TextFrame, TranscriptionFrame)):
            self.last_activity = time.monotonic()
            # Reset the idle retry counter back to 0 if the user confirms they are active
            if isinstance(frame, (UserStartedSpeakingFrame, TranscriptionFrame)):
                if self.retry_count > 0:
                    logger.info(f"[UserIdleProcessor] User speech activity detected ({frame.name}). Resetting idle retry counter from {self.retry_count} to 0.")
                self.retry_count = 0

        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class StartTriggerProcessor(FrameProcessor):
    def __init__(self, language: str = "en-US"):
        super().__init__()
        self.language = language
        self.triggered = False

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        if isinstance(frame, InputTransportMessageFrame):
            message = frame.message
            if isinstance(message, dict) and message.get("type") == "start_trigger":
                msg_id = message.get("id")
                if msg_id:
                    await self.push_frame(OutputTransportMessageFrame(message={
                        "label": "rtvi-ai",
                        "type": "response",
                        "id": msg_id,
                        "data": {"status": "ok"}
                    }))
                if not self.triggered:
                    self.triggered = True
                    greeting_text = "नमस्ते!" if self.language == "hi-IN" else "Hello!"
                    logger.info(f"[StartTriggerProcessor] start_trigger received. Queueing single greeting turn: {greeting_text}")
                    await self.push_frame(LLMMessagesAppendFrame(messages=[{"role": "user", "content": greeting_text}]))
                    await self.push_frame(LLMRunFrame())
                return
        await super().process_frame(frame, direction)


async def run_agent_live(websocket: WebSocket, model: str, voice: Optional[str], language: str, system_instruction: Optional[str] = None, tts: bool = True, tts_pace: float = 0.80, tools: Optional[str] = None, context_compression: bool = True, context_compression_trigger_tokens: Optional[int] = None):
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
    location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"

    gender = "male" if voice == "Custom-Male" else "female"
    logger.info(f"Starting agent with language: {language}")
    
    identity_instruction = (
        "\n\nIDENTITY RULE:\n"
        "1. When greeting the user initially, ask who you are speaking with today.\n"
        "2. As soon as the user states their name, call `identify_user(name=...)` immediately.\n"
    )
    prompt_text = (system_instruction or SYSTEM_PROMPT.replace("female", gender)) + identity_instruction + f"\n\nIMPORTANT: You must converse in {language} language."
    initial_user_id = os.getenv("ACTIVE_USER_ID", "default_user")
    # Option B: Path 1 pre-loading disabled - force live deep recall tool execution for every memory query
    preloaded_facts = []
    
    language_map = {
        "ar-XA": Language.AR, "bn-IN": Language.BN_IN, "cmn-CN": Language.CMN_CN, "de-DE": Language.DE_DE,
        "en-US": Language.EN_US, "en-GB": Language.EN_GB, "en-IN": Language.EN_IN, "en-AU": Language.EN_AU,
        "es-ES": Language.ES_ES, "es-US": Language.ES_US, "fr-FR": Language.FR_FR, "fr-CA": Language.FR_CA,
        "gu-IN": Language.GU_IN, "hi-IN": Language.HI_IN, "id-ID": Language.ID_ID, "it-IT": Language.IT_IT,
        "ja-JP": Language.JA_JP, "kn-IN": Language.KN_IN, "ko-KR": Language.KO_KR, "ml-IN": Language.ML_IN,
        "mr-IN": Language.MR_IN, "nl-NL": Language.NL_NL, "pl-PL": Language.PL_PL, "pt-BR": Language.PT_BR,
        "ru-RU": Language.RU_RU, "ta-IN": Language.TA_IN, "te-IN": Language.TE_IN, "th-TH": Language.TH_TH,
        "tr-TR": Language.TR_TR, "vi-VN": Language.VI_VN,
    }
    pipecat_language = language_map.get(language, Language.EN_US)
    
    transport = FastAPIWebsocketTransport(
        websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True, audio_out_enabled=True, add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.4)), serializer=CustomProtobufSerializer(),
            audio_filter=None,
        )
    )

    # Dynamic Tool & RAG / Memory Registration
    standard_tools = [
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
                    )
                }
            },
            required=["is_explicit_request"]
        ),
        search_knowledge_base_schema,
    ]

    if tools:
        try:
            tools_data = json.loads(tools)
            if isinstance(tools_data, list):
                for tool in tools_data:
                    if "name" in tool:
                        standard_tools.append(FunctionSchema(
                            name=tool.get("name"),
                            description=tool.get("description", ""),
                            properties=tool.get("properties", {}),
                            required=tool.get("required", [])
                        ))
        except Exception as e:
            logger.error(f"Failed to parse dynamic tools: {e}")

    tools_schema = ToolsSchema(standard_tools=standard_tools)

    use_external_tts = tts or (voice in ["Custom-Male", "Custom-Female"])
    tts_service = None
    
    if use_external_tts:
        voice_env = "CLONE_TTS_VOICE_KEY_MALE" if voice == "Custom-Male" else "CLONE_TTS_VOICE_KEY_FEMALE"
        voice_key_path = os.getenv(voice_env) if voice in ["Custom-Male", "Custom-Female"] else None
        
        if voice_key_path:
            with open(voice_key_path, "r") as f: key = f.read()
            tts_service = GoogleTTSService(voice_cloning_key=key, params=GoogleTTSService.InputParams(language=Language.EN_US))
        else:
            voice_id = voice if voice else "Aoede"
            tts_service = GoogleTTSService(voice_id=f"{language}-Chirp3-HD-{voice_id}", params=GoogleTTSService.InputParams(language=pipecat_language))

    llm_modalities = GeminiModalities.TEXT if use_external_tts else GeminiModalities.AUDIO
    
    voice_name = voice if not use_external_tts else None
    if not voice_name and not use_external_tts:
        voice_name = "Aoede"

    cwc = {}
    if context_compression:
        cwc["enabled"] = True
        if context_compression_trigger_tokens is not None:
            cwc["trigger_tokens"] = context_compression_trigger_tokens

    AI_STUDIO_MODELS = {
        "gemini-3.1-flash-live-preview",
        "gemini-3.5-live-translate-preview",
        "gemini-2.5-flash-native-audio-latest",
        "gemini-2.5-flash-native-audio-preview-09-2025",
        "gemini-2.5-flash-native-audio-preview-12-2025",
    }
    VERTEX_LIVE_MODELS = {
        "gemini-3.5-flash-live-preview",
        "gemini-3.5-flash-lite-live-preview",
        "gemini-3.5-live-preview",
        "gemini-3.5-live-extended-thinking-preview",
        "gemini-live-2.5-flash-native-audio",
        "gemini-live-2.5-flash",
    }

    clean_model = model[:-9] if model.endswith("-aistudio") else model
    if clean_model in AI_STUDIO_MODELS or (model.endswith("-aistudio") and clean_model not in VERTEX_LIVE_MODELS):
        is_ai_studio = True
    else:
        is_ai_studio = False

    if is_ai_studio:
        # Resolve API key from environment (Cloud Run --set-secrets) or Secret Manager
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            try:
                from google.cloud import secretmanager
                sm_client = secretmanager.SecretManagerServiceClient()
                sm_name = f"projects/{project_id}/secrets/GEMINI_API_KEY/versions/latest"
                sm_res = sm_client.access_secret_version(request={"name": sm_name})
                gemini_api_key = sm_res.payload.data.decode("UTF-8").strip()
                if gemini_api_key:
                    os.environ["GEMINI_API_KEY"] = gemini_api_key
                    logger.info("[SecretManager] Successfully retrieved GEMINI_API_KEY from Google Cloud Secret Manager.")
            except Exception as sm_err:
                logger.debug(f"[SecretManager] Dynamic GEMINI_API_KEY retrieval note: {sm_err}")

        settings = GeminiLiveLLMService.Settings(
            model=f"models/{clean_model}",
            system_instruction=prompt_text,
            voice=voice_name,
            language=pipecat_language,
            modalities=llm_modalities,
            context_window_compression=cwc
        )
        ai_studio_params = {
            "api_key": gemini_api_key,
            "tools": tools_schema,
            "transcribe_model_audio": True,
            "settings": settings,
            "http_options": HttpOptions(api_version="v1alpha")
        }
        llm = CustomGeminiLiveLLMService(**ai_studio_params)
    else:
        live_location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or location or "us-central1"
        vertex_model_name = clean_model
        if clean_model in ["gemini-3.5-live-preview", "gemini-3.5-live-extended-thinking-preview"]:
            vertex_model_name = "gemini-3.5-flash-live-preview"

        settings = GeminiLiveVertexLLMService.Settings(
            model=f"google/{vertex_model_name}",
            system_instruction=prompt_text,
            voice=voice_name,
            language=pipecat_language,
            modalities=llm_modalities,
            context_window_compression=cwc
        )
        vertex_params = {
            "project_id": project_id,
            "location": live_location,
            "tools": tools_schema,
            "transcribe_model_audio": True,
            "settings": settings,
        }
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            vertex_params["credentials_path"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        llm = CustomGeminiLiveVertexLLMService(**vertex_params)

    llm.register_function("get_current_time", get_current_time)
    llm.register_function("search_knowledge_base", search_knowledge_base_handler)
    
    # Register generic handler for dynamic tools (skip built-in tools)
    built_in_tools = {"get_current_time", "search_knowledge_base"}
    for tool in standard_tools:
        if tool.name not in built_in_tools:
            llm.register_function(tool.name, dynamic_tool_handler)

    user_params = LLMUserAggregatorParams(
        user_turn_strategies=UserTurnStrategies(
            start=[VADUserTurnStartStrategy(), TranscriptionUserTurnStartStrategy()],
            stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)]
        )
    )
    context_aggregator = LLMContextAggregatorPair(
        LLMContext(messages=[]),
        user_params=user_params
    )

    async def handle_user_idle(processor: UserIdleProcessor, retry_count: int) -> bool:
        logger.info(f"User idle detected, retry count: {retry_count}")
        if retry_count < 4:
            prompts = {
                1: "ask me if I am able to hear you",
                2: "ask me if I am still here",
                3: "Tell me that you are not able to hear me, and you are disconnecting the call and will call back again"
            }
            # Call Gemini Live session directly to trigger a response
            await llm._create_single_response([{"role": "user", "content": prompts[retry_count]}])
            return True
        await processor.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
        return False

    pipeline = Pipeline([
        transport.input(),
        StartTriggerProcessor(language=language),
        UserIdleProcessor(callback=handle_user_idle, timeout=30.0),
        context_aggregator.user(),
        llm,
        *([tts_service] if tts_service else []),
        transport.output(),
        context_aggregator.assistant(),
    ])

    session_id = f"session_{int(time.time()*1000)}"
    trace_url = GLOBAL_LANGSMITH_TRACER.start_session(session_id, model=model, voice=voice, language=language)

    task = PipelineTask(pipeline, params=PipelineParams(
        enable_metrics=True,
        enable_usage_metrics=True,
    ))
    
    task.add_observer(WhiskerObserver(pipeline))

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Pipecat Client connected. Trace URL: {trace_url}")
        if trace_url:
            await transport.output().push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {"type": "trace_url", "url": trace_url}
            }))

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Pipecat Client disconnected")
        GLOBAL_LANGSMITH_TRACER.end_session()
        await task.cancel()

    await PipelineRunner(handle_sigint=False).run(task)
