import os
import websockets
import json
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
from pipecat.audio.filters.aic_filter import AICFilter
from pipecat_whisker import WhiskerObserver
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.frames.frames import EndTaskFrame, Frame, InterruptionFrame, CancelFrame, LLMMessagesAppendFrame, TextFrame, OutputTransportMessageFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transcriptions.language import Language
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import AdapterType, ToolsSchema
from pipecat.services.llm_service import FunctionCallParams
# from pipecat.processors.user_idle_processor import UserIdleProcessor
from system_prompt import SYSTEM_PROMPT
from tools.projects import search_projects


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
        """Intercept InterruptionFrame for metrics."""
        if isinstance(frame, InterruptionFrame):
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
        """Override to handle transcription normally."""
        if not message.server_content.input_transcription:
            return await super()._handle_msg_input_transcription(message)

        text = message.server_content.input_transcription.text
        if not text:
            return await super()._handle_msg_input_transcription(message)

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



    # ── Session ID & token usage logging ──────────────────────────────

    async def _process_message(self, message):

        # Capture Session ID
        if not getattr(self, '_session_id_logged', False):
            session_id = None
            if hasattr(message, 'session_resumption_update') and message.session_resumption_update:
                session_id = message.session_resumption_update.new_handle
            elif self._session: # Fallback to session object
                 session_id = getattr(self._session, 'session_id', None) or getattr(self._session, 'id', None)
            
            if session_id:
                self._session_id = session_id
                logger.info(f"Session ID Established: {session_id}")
                self._session_id_logged = True

        # Log Token Usage
        if hasattr(message, 'usage_metadata') and message.usage_metadata:
            usage = message.usage_metadata
            
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

            # Metric Streaming: Token Usage
            usage_dict = {
                "prompt_token_count": getattr(usage, 'prompt_token_count', 0),
                "response_token_count": getattr(usage, 'response_token_count', 0),
                "total_token_count": getattr(usage, 'total_token_count', 0),
            }
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'metrics',
                    'payload': {'type': 'usage', 'usage': usage_dict}
                }
            }))

        # Standard Processing
        self._check_and_reset_failure_counter()
        
        if message.server_content:
            if hasattr(message.server_content, "activity_end") and message.server_content.activity_end:
                logger.info("Activity End received from server (User stopped speaking)")
                
            if message.server_content.model_turn:
                logger.info("Model Turn detected")
                await self._handle_msg_model_turn(message)
            
            if message.server_content.turn_complete:
                logger.info("Turn Complete received from server")
                await self._handle_msg_turn_complete(message)
                # Metric Streaming: Turn Count
                await self.push_frame(OutputTransportMessageFrame(message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        'type': 'metrics',
                        'payload': {'type': 'turn_complete'}
                    }
                }))

                # usage_metadata is often attached to turn_complete message
                if message.usage_metadata:
                    await self._handle_msg_usage_metadata(message)
            
            if message.server_content.input_transcription:
                logger.debug(f"Input Transcription: {message.server_content.input_transcription.text}")
                await self._handle_msg_input_transcription(message)
            
            if message.server_content.output_transcription:
                await self._handle_msg_output_transcription(message)
            
            if message.server_content.grounding_metadata:
                await self._handle_msg_grounding_metadata(message)
                
        elif message.tool_call:
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
            
            await self._handle_msg_tool_call(message)
        elif message.session_resumption_update:
            self._handle_msg_resumption_update(message)

    async def _connect(self, session_resumption_handle: Optional[str] = None):
        """Establish client connection to Gemini Live API."""
        if self._session:
            return

        if session_resumption_handle:
            logger.info(
                f"Connecting to Gemini service with session_resumption_handle: {session_resumption_handle}"
            )
        else:
            logger.info("Connecting to Gemini service")
        try:
            # Assemble basic configuration
            modalities = self._settings["modalities"]
            has_audio = modalities == GeminiModalities.AUDIO

            generation_config_params = {
                "frequency_penalty": self._settings["frequency_penalty"],
                "max_output_tokens": self._settings["max_tokens"],
                "presence_penalty": self._settings["presence_penalty"],
                "temperature": self._settings["temperature"],
                "top_k": self._settings["top_k"],
                "top_p": self._settings["top_p"],
                "response_modalities": [Modality(modalities.value)],
                "media_resolution": MediaResolution(self._settings["media_resolution"].value),
            }

            if has_audio:
                generation_config_params["speech_config"] = SpeechConfig(
                    voice_config=VoiceConfig(
                        prebuilt_voice_config={"voice_name": self._voice_id}
                    ),
                    language_code=self._settings["language"],
                )

            config = LiveConnectConfig(
                generation_config=GenerationConfig(**generation_config_params),
                input_audio_transcription=AudioTranscriptionConfig(),
                # session_resumption=SessionResumptionConfig(handle=session_resumption_handle),
            )

            if has_audio:
                config.output_audio_transcription = AudioTranscriptionConfig()

            # Add context window compression to configuration, if enabled
            if self._settings.get("context_window_compression", {}).get("enabled", False):
                compression_config = ContextWindowCompressionConfig()

                # Add sliding window (always true if compression is enabled)
                compression_config.sliding_window = SlidingWindow()

                # Add trigger_tokens if specified
                trigger_tokens = self._settings.get("context_window_compression", {}).get(
                    "trigger_tokens"
                )
                if trigger_tokens is not None:
                    compression_config.trigger_tokens = trigger_tokens

                config.context_window_compression = compression_config

            # Add thinking configuration to configuration, if provided
            if self._settings.get("thinking"):
                config.thinking_config = self._settings["thinking"]

            # Add affective dialog setting, if provided
            if self._settings.get("enable_affective_dialog", False):
                config.enable_affective_dialog = self._settings["enable_affective_dialog"]

            # Add proactivity configuration to configuration, if provided
            if self._settings.get("proactivity"):
                config.proactivity = self._settings["proactivity"]

            # Add VAD configuration to configuration, if provided
            if self._settings.get("vad"):
                vad_config = AutomaticActivityDetection()
                vad_params = self._settings["vad"]
                has_vad_settings = False

                # Only add parameters that are explicitly set
                if vad_params.disabled is not None:
                    vad_config.disabled = vad_params.disabled
                    has_vad_settings = True

                if vad_params.start_sensitivity:
                    vad_config.start_of_speech_sensitivity = vad_params.start_sensitivity
                    has_vad_settings = True

                if vad_params.end_sensitivity:
                    vad_config.end_of_speech_sensitivity = vad_params.end_sensitivity
                    has_vad_settings = True

                if vad_params.prefix_padding_ms is not None:
                    vad_config.prefix_padding_ms = vad_params.prefix_padding_ms
                    has_vad_settings = True

                if vad_params.silence_duration_ms is not None:
                    vad_config.silence_duration_ms = vad_params.silence_duration_ms
                    has_vad_settings = True

                # Only add automatic_activity_detection if we have VAD settings
                if has_vad_settings:
                    config.realtime_input_config = RealtimeInputConfig(
                        automatic_activity_detection=vad_config
                    )

            # Add system instruction to configuration, if provided
            system_instruction = getattr(self, "_system_instruction", None) or ""
            if self._context and hasattr(self._context, "extract_system_instructions"):
                system_instruction += "\n" + self._context.extract_system_instructions()
            if system_instruction:
                logger.debug(f"Setting system instruction: {system_instruction}")
                config.system_instruction = system_instruction

            # Add tools to configuration, if provided
            tools = getattr(self, "_tools", None)
            if tools:
                logger.debug(f"Setting tools: {tools}")
                # Manually convert tools to Google format since ToolsSchema doesn't have to_google_tools
                # and we don't have easy access to the adapter instance here
                from pipecat.adapters.services.gemini_adapter import GeminiLLMAdapter
                adapter = GeminiLLMAdapter()
                config.tools = adapter.to_provider_tools_format(tools)

            self._connection_task = self.create_task(self._connection_task_handler(config))
        except Exception as e:
            logger.error(f"Error connecting to Gemini service: {e}")
            raise e

    async def _connection_task_handler(self, config: LiveConnectConfig):
        async with self._client.aio.live.connect(model=self._model_name, config=config) as session:
            logger.info("Connected to Gemini service")
            self._connection_start_time = time.time()
            await self._handle_session_ready(session)

            while True:
                try:
                    turn = self._session.receive()
                    async for message in turn:
                        await self._process_message(message)
                except Exception as e:
                    if not self._disconnecting and await self._handle_connection_error(e):
                        await self._reconnect()
                        return
                    break

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

    async def _create_initial_response(self):
        if self._disconnecting:
            return
        if not self._session:
            self._run_llm_when_session_ready = True
            return

        logger.info("Triggering initial response in Hindi for AI Studio model...")
        from google.genai.types import Content, Part
        messages = [Content(
            parts=[Part.from_text(text="नमस्ते! बातचीत शुरू करें।")],
            role='user'
        )]
        await self._session.send_client_content(
            turns=messages, turn_complete=True
        )




async def dynamic_tool_handler(params: FunctionCallParams):
    logger.info(f"Dynamic tool called: {params.function_name} with args: {params.arguments}")
    await params.result_callback({"status": "success", "message": f"Tool {params.function_name} called successfully"})

async def run_agent_live(websocket: WebSocket, model: str, voice: Optional[str], language: str, system_instruction: Optional[str] = None, tts: bool = True, tts_pace: float = 0.80, tools: Optional[str] = None):
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
            audio_filter=AICFilter(),
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
    
    common_params = {
        "system_instruction": prompt_text, "tools": tools_schema, "transcribe_model_audio": True,
        "params": InputParams(language=pipecat_language, modalities=llm_modalities)
    }

    if model == "gemini-2.5-flash-native-audio-eap-11-2025":
        common_params["http_options"] = HttpOptions(api_version="v1beta")

    if model == "gemini-3.1-flash-live-preview":
        ai_studio_params = {
            **common_params, 
            "api_key": os.getenv("GEMINI_API_KEY"), 
            "model": f"models/{model}",
            "http_options": HttpOptions(api_version="v1beta")
        }
        if not use_external_tts:
            # Use Zephyr as requested by user for this model
            ai_studio_params["voice_id"] = "Zephyr"
        llm = CustomGeminiLiveLLMService(**ai_studio_params)
    else:
        vertex_params = {**common_params, "project_id": project_id, "location": location, "model": f"google/{model}"}
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            vertex_params["credentials_path"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not use_external_tts and voice:
            vertex_params["voice_id"] = voice
        llm = CustomGeminiLiveVertexLLMService(**vertex_params)

    llm.register_function("get_current_time", get_current_time)
    
    # Register generic handler for dynamic tools
    for tool in standard_tools:
        if tool.name != "get_current_time":
            llm.register_function(tool.name, dynamic_tool_handler)

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(context)

    pipeline = Pipeline([
        transport.input(),
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
        await task.queue_frames([context_aggregator.user()._get_context_frame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Pipecat Client disconnected")
        await task.cancel()

    await PipelineRunner(handle_sigint=False).run(task)


async def run_agent_twilio(websocket: WebSocket, stream_sid: str, system_instruction: Optional[str] = None, use_silero_vad: Optional[bool] = None):
    """Runs the Gemini Live agent with Twilio integration."""
    if use_silero_vad is None:
        use_silero_vad = os.getenv("GEMINI_VAD_MODE", "silero").lower() == "silero"

    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
    location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"

    logger.info(f"Starting Twilio agent for stream {stream_sid} (VAD: {'Silero' if use_silero_vad else 'Native'})")
    
    prompt_text = system_instruction or SYSTEM_PROMPT
    
    transport = FastAPIWebsocketTransport(
        websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True, 
            audio_out_enabled=True, 
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer() if use_silero_vad else None,
            serializer=TwilioFrameSerializer(
                stream_sid=stream_sid,
                params=TwilioFrameSerializer.InputParams(auto_hang_up=False)
            ),
            audio_filter=None, # Disabled for Twilio (8kHz) to prevent sample rate distortion
        )
    )

    # Register standard and domain-specific tools
    standard_tools = [
        FunctionSchema(
            name="get_current_time",
            description="Get the current time.",
            properties={
                "is_explicit_request": {
                    "type": "boolean",
                    "description": "Return `true` ONLY if the user explicitly asks for the current time."
                }
            },
            required=["is_explicit_request"]
        ),
        FunctionSchema(
            name="project_search",
            description="Search Noida/Greater Noida projects by query keywords (e.g. Noida, budget, 4 BHK).",
            properties={
                "query": {
                    "type": "string",
                    "description": "Search keywords (e.g. location, budget, configuration)"
                }
            },
            required=["query"]
        ),
        FunctionSchema(
            name="handle_other_client_queries",
            description="Handle miscellaneous user queries outside of project pitches.",
            properties={
                "query": {
                    "type": "string",
                    "description": "The user's query"
                }
            },
            required=["query"]
        )
    ]
    tools_schema = ToolsSchema(standard_tools=standard_tools)

    common_params = {
        "system_instruction": prompt_text, 
        "tools": tools_schema, 
        "transcribe_model_audio": True,
        "params": InputParams(language=Language.HI_IN, modalities=GeminiModalities.AUDIO)
    }

    vertex_params = {
        **common_params, 
        "project_id": project_id, 
        "location": location, 
        "model": "google/gemini-live-2.5-flash-native-audio",
        "http_options": HttpOptions(api_version="v1alpha")
    }
    
    # Subclass to inject Native VAD config and Proactivity
    class TwilioGeminiService(CustomGeminiLiveVertexLLMService):
        async def _connection_task_handler(self, config):
            if not use_silero_vad:
                from google.genai.types import RealtimeInputConfig, AutomaticActivityDetection
                logger.info("Enabling Native VAD for Twilio")
                vad_config = AutomaticActivityDetection(
                    start_of_speech_sensitivity="START_SENSITIVITY_LOW",
                    end_of_speech_sensitivity="END_SENSITIVITY_LOW",
                    prefix_padding_ms=200,
                    silence_duration_ms=500
                )
                config.realtime_input_config = RealtimeInputConfig(
                    automatic_activity_detection=vad_config
                )
            
            # Enable Proactivity
            logger.info("Enabling Proactivity for Twilio")
            config.proactivity = {"proactive_audio": True}
            
            await super()._connection_task_handler(config)

    # Tool Handlers
    async def project_search_handler(params: FunctionCallParams):
        query = params.arguments.get("query", "")
        logger.info(f"project_search called with query: {query}")
        result = search_projects(query)
        await params.result_callback({"status": "success", "result": result})

    async def other_queries_handler(params: FunctionCallParams):
        query = params.arguments.get("query", "")
        logger.info(f"handle_other_client_queries called with query: {query}")
        # Fallback mock response to prevent crash
        await params.result_callback({
            "status": "success", 
            "result": "I have noted your query. I am mainly focused on Noida project assistance, but I will pass this to our team."
        })

    # Use the custom service
    llm = TwilioGeminiService(**vertex_params)
    llm.register_function("get_current_time", get_current_time)
    llm.register_function("project_search", project_search_handler)
    llm.register_function("handle_other_client_queries", other_queries_handler)

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(context)

    pipeline = Pipeline([
        transport.input(),
        context_aggregator.user(),
        llm,
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
        logger.info("Twilio Client connected")
        await task.queue_frames([context_aggregator.user()._get_context_frame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Twilio Client disconnected")
        await task.cancel()

    await PipelineRunner(handle_sigint=False).run(task)
