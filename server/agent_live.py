import os
import websockets
import json
import asyncio
from typing import Optional, List, Dict, Any
from loguru import logger
from fastapi import WebSocket
from datetime import datetime
import time

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.google.gemini_live.vertex.llm import GeminiLiveVertexLLMService
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, InputParams, GeminiModalities
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.services.google.tts import GoogleTTSService
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.filters.krisp_viva_filter import KrispVivaFilter
from pipecat.audio.turn.krisp_viva_turn import KrispVivaTurn
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams

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
    is_explicit = params.arguments.get('is_explicit_request')
    if not is_explicit:
        await params.result_callback({"error": "Explicit time request required."})
        return

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
            self._my_ttfb_start = None


    async def process_frame(self, frame, direction):
        """Intercept InterruptionFrame to set filler-pending flag.

        We override process_frame instead of _handle_interruption because
        _bot_is_responding gets set to False when the API turn_complete arrives,
        but audio may still be playing from the transport buffer. The
        InterruptionFrame is only generated when the user actually interrupts
        ongoing audio playback, so it's a reliable signal.
        """
        if isinstance(frame, InterruptionFrame):
            if not hasattr(self, '_repeat_on_filler_pending'):
                self._repeat_on_filler_pending = False
            self._repeat_on_filler_pending = True
            logger.info("[RepeatOnFiller] Interruption detected. Watching for filler.")
            
            # Metric Streaming: Interruption
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'metrics',
                    'payload': {'type': 'interruption', 'count': 1}
                }
            }))

        await super().process_frame(frame, direction)

    async def _handle_msg_input_transcription(self, message):
        """Override to detect ≤2-word fillers after an interruption and auto-repeat.

        The API sends transcription in chunks (fragments). We accumulate text
        in our own buffer and check once a complete sentence is formed (sentence-
        ending punctuation detected). This avoids false positives from partial
        chunks like "अच्छा," arriving before the rest of a longer sentence.

        We ALWAYS let the parent handle sentence buffering and TranscriptionFrame
        emission first, then evaluate the filler logic.
        """
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

        # ALWAYS let parent handle normally (sentence buffering, TranscriptionFrame)
        await super()._handle_msg_input_transcription(message)

        # Send transcription to UI
        logger.debug(f"[Transcription] User: {text}")
        await self.push_frame(OutputTransportMessageFrame(message={
            "label": "rtvi-ai",
            "type": "server-message",
            "data": {
                'type': 'transcription',
                'participant': 'User',
                'text': text
            }
        }))

        # After parent processes, check if our buffer forms a complete sentence
        if getattr(self, '_repeat_on_filler_pending', False):
            buffer = getattr(self, '_post_interruption_buffer', '').strip()
            if not buffer:
                return

            import re
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
                    await self.push_frame(OutputTransportMessageFrame(message={
                        "label": "rtvi-ai",
                        "type": "server-message",
                        "data": {
                            'type': 'transcription',
                            'participant': 'Bot',
                            'text': text
                        }
                    }))
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
            logger.debug(f"[Transcription] Bot: {text}")
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

    async def _tool_result(self, *args, **kwargs):
        if len(args) == 1 and hasattr(args[0], "result"):
            frame = args[0]
            result_dict = frame.result if isinstance(frame.result, dict) else {}
            tool_call_id = getattr(frame, "tool_call_id", "")
        elif len(args) >= 3:
            tool_call_id = args[0]
            tool_name = args[1]
            result_dict = args[2] if isinstance(args[2], dict) else {}
        else:
            result_dict = kwargs.get("tool_result_message", {})
            tool_call_id = kwargs.get("tool_call_id", "")

        scheduling = result_dict.get("scheduling", "SILENT") if isinstance(result_dict, dict) else "SILENT"
        
        if hasattr(super(), "_tool_result"):
            await super()._tool_result(*args, **kwargs)
        elif getattr(self, "_session", None) and hasattr(self._session, "send"):
            payload = {"tool_response": {"function_responses": [{"response": result_dict, "id": tool_call_id}]}, "scheduling": scheduling}
            await self._session.send(payload)

    async def _handle_server_message(self, message):
        if getattr(message, "go_away", False) or getattr(message, "goAway", False):
            logger.info("[GeminiSessionLoggerMixin] go_away message received! Triggering _reconnect().")
            if hasattr(self, "_reconnect"):
                await self._reconnect()
        elif hasattr(super(), "_handle_server_message"):
            await super()._handle_server_message(message)

    async def _buffer_or_send_audio(self, frame):
        if not hasattr(self, "_audio_buffer"):
            self._audio_buffer = []
        if getattr(self, "_session", None) is None:
            self._audio_buffer.append(frame)
            logger.debug("[GeminiSessionLoggerMixin] Session is None (reconnecting), buffering audio frame.")
        else:
            if hasattr(super(), "_buffer_or_send_audio"):
                await super()._buffer_or_send_audio(frame)
            elif hasattr(self, "_send_user_audio"):
                await self._send_user_audio(frame)

    async def _handle_session_ready(self, session):
        if hasattr(super(), "_handle_session_ready"):
            await super()._handle_session_ready(session)
        self._session = session
        if hasattr(self, "_audio_buffer") and self._audio_buffer:
            logger.info(f"[GeminiSessionLoggerMixin] Flushing {len(self._audio_buffer)} buffered audio frames...")
            for frame in list(self._audio_buffer):
                if hasattr(self, "_send_user_audio"):
                    await self._send_user_audio(frame)
            self._audio_buffer.clear()

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






_PROCESSED_TOOL_CALLS = set()

def get_default_settings():
    from google.genai.types import SessionResumptionConfig
    return GeminiLiveVertexLLMService.Settings(
        model="google/gemini-3.1-flash-live-preview",
        system_instruction="",
        extra={"session_resumption": SessionResumptionConfig()},
        context_window_compression={"enabled": True, "sliding_window": {"trigger_tokens": 20000, "target_tokens": 10000}}
    )

async def dynamic_tool_handler(params: FunctionCallParams = None, *args, **kwargs):
    if params is not None and not isinstance(params, str):
        func_name = params.function_name
        args_dict = params.arguments
        callback = params.result_callback
    else:
        func_name = params if isinstance(params, str) else (args[0] if args else "unknown")
        args_dict = args[0] if (isinstance(params, str) and args) else (args[1] if len(args) > 1 else kwargs)
        callback = None

    dedup_key = (func_name, str(sorted(args_dict.items()) if isinstance(args_dict, dict) else args_dict), kwargs.get("round_id"))
    if dedup_key in _PROCESSED_TOOL_CALLS:
        logger.info(f"Duplicate tool call detected and ignored: {dedup_key}")
        if callback:
            await callback("OK")
        return "OK"
    _PROCESSED_TOOL_CALLS.add(dedup_key)

    res = {"status": "success", "message": f"Tool {func_name} called successfully", "scheduling": "SILENT"}
    if callback:
        await callback(res)
    return res

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
    def __init__(self):
        super().__init__()
        self.triggered = False

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        if isinstance(frame, InputTransportMessageFrame):
            message = frame.message
            if isinstance(message, dict) and message.get("type") == "start_trigger":
                if not self.triggered:
                    self.triggered = True
                    logger.info("[StartTriggerProcessor] start_trigger received. Queueing greeting turn.")
                    await self.push_frame(LLMMessagesAppendFrame(messages=[{"role": "user", "content": "Hello!"}]))
                    await self.push_frame(LLMRunFrame())
                return
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


async def run_agent_live(websocket: WebSocket, model: str, voice: Optional[str], language: str, system_instruction: Optional[str] = None, tts: bool = True, tts_pace: float = 0.80, tools: Optional[str] = None, context_compression: bool = True, context_compression_trigger_tokens: Optional[int] = None):
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
    location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"

    gender = "male" if voice == "Custom-Male" else "female"
    logger.info(f"Starting agent with language: {language}")
    
    prompt_text = (system_instruction or SYSTEM_PROMPT.replace("female", gender)) + f"\n\nIMPORTANT: You must converse in {language} language."
    
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
            vad_analyzer=SileroVADAnalyzer(), serializer=CustomProtobufSerializer(),
            audio_filter=KrispVivaFilter(),
        )
    )

    # Dynamic Tool Registration
    standard_tools = [FunctionSchema(
        name="get_current_time",
        description="Get the current time.",
        properties={
            "is_explicit_request": {
                "type": "boolean",
                "description": (
                    "Return `true` ONLY if the user explicitly asks for the current time or date.\n\n"
                    "Return `false` for anything else, including:\n"
                    "- Explaining schedules or timelines.\n"
                    "- Mentioning time casually in conversation."
                )
            }
        },
        required=["is_explicit_request"]
    )]

    
    if tools:
        try:
            tools_data = json.loads(tools)
            if isinstance(tools_data, list):
                for tool in tools_data:
                    # Basic validation
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
    
    voice_name = "Zephyr" if (model == "gemini-3.1-flash-live-preview" and not use_external_tts) else (voice if not use_external_tts else None)

    cwc = {}
    if context_compression:
        cwc["enabled"] = True
        cwc["sliding_window"] = {
            "trigger_tokens": context_compression_trigger_tokens if context_compression_trigger_tokens is not None else 20000,
            "target_tokens": 10000
        }

    if model == "gemini-3.1-flash-live-preview":
        settings = GeminiLiveLLMService.Settings(
            model=f"models/{model}",
            system_instruction=prompt_text,
            voice=voice_name,
            language=pipecat_language,
            modalities=llm_modalities,
            context_window_compression=cwc,
            extra={"session_resumption": SessionResumptionConfig()}
        )
        ai_studio_params = {
            "api_key": os.getenv("GEMINI_API_KEY"),
            "tools": tools_schema,
            "transcribe_model_audio": True,
            "settings": settings,
            "http_options": HttpOptions(api_version="v1beta")
        }
        llm = CustomGeminiLiveLLMService(**ai_studio_params)
    else:
        settings = GeminiLiveVertexLLMService.Settings(
            model=f"google/{model}",
            system_instruction=prompt_text,
            voice=voice_name,
            language=pipecat_language,
            modalities=llm_modalities,
            context_window_compression=cwc,
            extra={"session_resumption": SessionResumptionConfig()}
        )
        vertex_params = {
            "project_id": project_id,
            "location": location,
            "tools": tools_schema,
            "transcribe_model_audio": True,
            "settings": settings
        }
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            vertex_params["credentials_path"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if model == "gemini-2.5-flash-native-audio-eap-11-2025":
            vertex_params["http_options"] = HttpOptions(api_version="v1beta")
        llm = CustomGeminiLiveVertexLLMService(**vertex_params)

    llm.register_function("get_current_time", get_current_time)
    
    # Register generic handler for dynamic tools
    for tool in standard_tools:
        if tool.name != "get_current_time":
            llm.register_function(tool.name, dynamic_tool_handler)

    initial_greeting = "नमस्ते!" if language == "hi-IN" else "Hello!"
    context = LLMContext(messages=[{"role": "user", "content": initial_greeting}])
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                stop=[TurnAnalyzerUserTurnStopStrategy(
                    turn_analyzer=KrispVivaTurn()
                )]
            ),
            vad_analyzer=SileroVADAnalyzer()
        )
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
        StartTriggerProcessor(),
        UserIdleProcessor(callback=handle_user_idle, timeout=10.0),
        context_aggregator.user(),
        llm,
        *([tts_service] if tts_service else []),
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(pipeline, params=PipelineParams(
        enable_metrics=True,
        enable_usage_metrics=True,
    ))
    
    task.add_observer(WhiskerObserver(pipeline))

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Pipecat Client connected")
        # Defer greeting until start_trigger message is received

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Pipecat Client disconnected")
        await task.cancel()

    await PipelineRunner(handle_sigint=False).run(task)
