import os
import websockets
from typing import Optional
from loguru import logger
from fastapi import WebSocket
from datetime import datetime
import time

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.google.gemini_live.llm_vertex import GeminiLiveVertexLLMService
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, InputParams, GeminiModalities
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.services.google.tts import GoogleTTSService
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.frames.frames import EndTaskFrame, Frame, StartInterruptionFrame, CancelFrame, LLMMessagesAppendFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.transcriptions.language import Language
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import AdapterType, ToolsSchema
from pipecat.services.llm_service import FunctionCallParams
from pipecat.processors.user_idle_processor import UserIdleProcessor
from system_prompt import SYSTEM_PROMPT, DEBT_COLLECTION_PROMPT, RESTAURANT_RESERVATION_PROMPT, AI_GIRLFRIEND_PROMPT, ROUTER_PROMPT

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

SYSTEM_INSTRUCTION = ROUTER_PROMPT

class CustomProtobufSerializer(ProtobufFrameSerializer):
    async def serialize(self, frame: Frame) -> bytes | None:
        if isinstance(frame, (StartInterruptionFrame, CancelFrame)):
            return None
        data = await super().serialize(frame)
        return data.encode("utf-8") if isinstance(data, str) else data

async def get_current_time(params: FunctionCallParams):
    await params.result_callback(
        {"time": datetime.now().strftime("%A, %B %d, %Y %I:%M %p")}
    )

class GeminiSessionLoggerMixin:
    """Mixin to add session ID logging and token usage tracking."""

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

        # Standard Processing
        self._check_and_reset_failure_counter()
        
        if message.server_content:
            if message.server_content.model_turn:
                await self._handle_msg_model_turn(message)
            
            if message.server_content.turn_complete:
                await self._handle_msg_turn_complete(message)
                # usage_metadata is often attached to turn_complete message
                if message.usage_metadata:
                    await self._handle_msg_usage_metadata(message)
            
            if message.server_content.input_transcription:
                await self._handle_msg_input_transcription(message)
            
            if message.server_content.output_transcription:
                await self._handle_msg_output_transcription(message)
            
            if message.server_content.grounding_metadata:
                await self._handle_msg_grounding_metadata(message)
                
        elif message.tool_call:
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
        
        # DEBUG: Log raw system instruction and tools
        logger.info(f"Checking system instruction: {getattr(self, '_system_instruction', 'Not Set')}")
        logger.info(f"Checking tools: {getattr(self, '_tools', 'Not Set')}")

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
                session_resumption=SessionResumptionConfig(handle=session_resumption_handle),
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


class CustomGeminiLiveVertexLLMService(GeminiSessionLoggerMixin, GeminiLiveVertexLLMService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure _tools and _system_instruction are available for the mixin's _connect method
        # The base class might assume different storage or we might be overriding it
        self._tools = kwargs.get("tools")
        self._system_instruction = kwargs.get("system_instruction")

    async def process_frame(self, frame, direction):
        """
        Override process_frame to handle LLMMessagesAppendFrame explicitly.
        Gemini Live SDK expects direct session.send() calls for content, not just frame passing
        if the base class implementation doesn't support LLM frames.
        """
        try:
            from pipecat.frames.frames import LLMMessagesAppendFrame, LLMMessagesFrame
            from google.genai import types

            if isinstance(frame, (LLMMessagesAppendFrame, LLMMessagesFrame)):
                logger.info(f"Processing LLM Frame in Gemini Live: {type(frame)}")
                
                # Extract content from the frame
                # LLMMessagesAppendFrame usually has a list of messages in frame.messages
                # We need to find the last user message to send to the model if it's an append
                messages = getattr(frame, 'messages', [])
                if not messages:
                    return

                logger.info(f"LLM Frame messages: {messages}")

                # Find the text content to send
                text_content = ""
                for msg in messages:
                    if msg.get('role') == 'user':
                        text_content += msg.get('content', "") + "\n"
                
                if text_content.strip() and self._session:
                    logger.info(f"Sending LLM Frame text to Gemini: {text_content[:50]}...")
                    # Send as client_content (User Message)
                    await self._session.send(
                        input=types.LiveClientContent(
                            turns=[
                                types.Content(
                                    role="user",
                                    parts=[types.Part(text=text_content)]
                                )
                            ],
                            turn_complete=True
                        )
                    )
                
                # We handled the frame, so we stop propagation to base class/downstream
                return
        except Exception as e:
            logger.error(f"Error processing frame in CustomGeminiLiveVertexLLMService: {e}")
            
        await super().process_frame(frame, direction)
    async def update_system_instruction(self, instruction: str):
        if not self._session:
            logger.error("Session not started, cannot update system instruction")
            return
        try:
            from google.genai import types
            
            logger.info("Updating system instruction via context injection")
            
            # Create a context message that instructs the model to adopt new persona
            # This follows the "Context Injection" pattern since mid-session setup updates are not supported.
            context_text = f"""[SYSTEM PERSONA UPDATE]
You must now completely adopt the following new identity and instructions. 
Forget your previous persona and follow these new instructions exactly:

---
{instruction}
---

Seamlessly transition to new persona and ask user how can you help them.
"""
            
            await self._session.send(
                input=types.LiveClientContent(
                    turns=[
                        types.Content(
                            role="user",
                            parts=[types.Part(text=context_text)]
                        )
                    ],
                    turn_complete=True
                )
            )
            logger.info("System instruction updated via context injection")

        except Exception as e:
            logger.error(f"Failed to update system instruction: {e}")
            import traceback
            logger.error(traceback.format_exc())

async def run_agent_live(websocket: WebSocket, model: str, voice: Optional[str], language: str, system_instruction: Optional[str] = None, tts: bool = True, tts_pace: float = 0.80):
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
    location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"

    gender = "male" if voice == "Custom-Male" else "female"
    logger.info(f"Starting agent with language: {language}")
    
    logger.info(f"Starting agent with language: {language}")
    
    # Use the ROUTER_PROMPT as the initial system instruction if none provided
    initial_instruction = system_instruction or ROUTER_PROMPT
    prompt_text = initial_instruction + f"\n\nIMPORTANT: You must converse in {language} language."
    
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
        )
    )

    tools = ToolsSchema(standard_tools=[
        FunctionSchema(
            name="get_current_time",
            description="Get the current time.",
            properties={},
            required=[]
        ),
        FunctionSchema(
            name="switch_agent",
            description="Switch the AI agent persona based on user intent.",
            properties={
                "agent_name": {
                    "type": "string",
                    "description": "The name of the agent to switch to. Options: 'debt_collection', 'restaurant_reservation', 'ai_girlfriend'",
                    "enum": ["debt_collection", "restaurant_reservation", "ai_girlfriend"]
                }
            },
            required=["agent_name"]
        )
    ])

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
        "system_instruction": prompt_text, "tools": tools, "transcribe_model_audio": True,
        "params": InputParams(language=pipecat_language, modalities=llm_modalities)
    }

    if model == "gemini-2.5-flash-native-audio-eap-11-2025":
        common_params["http_options"] = HttpOptions(api_version="v1beta")

    vertex_params = {**common_params, "project_id": project_id, "location": location, "model": f"google/{model}"}
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        vertex_params["credentials_path"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not use_external_tts and voice:
        vertex_params["voice_id"] = voice
        
    llm = CustomGeminiLiveVertexLLMService(**vertex_params)

    async def switch_agent_handler(function_call_params: FunctionCallParams):
        agent_name = function_call_params.arguments.get("agent_name")
        logger.info(f"Switching agent to: {agent_name}")
        
        new_prompt = None
        if agent_name == "debt_collection":
            new_prompt = DEBT_COLLECTION_PROMPT
        elif agent_name == "restaurant_reservation":
            new_prompt = RESTAURANT_RESERVATION_PROMPT
        elif agent_name == "ai_girlfriend":
            new_prompt = AI_GIRLFRIEND_PROMPT
            
        if new_prompt:
            # Append language instruction
            final_prompt = new_prompt + f"\n\nIMPORTANT: You must converse in {language} language."
            await llm.update_system_instruction(final_prompt)
            return {"status": "success", "message": f"Switched to {agent_name} agent"}
        else:
            return {"status": "error", "message": f"Unknown agent: {agent_name}"}

    llm.register_function("get_current_time", get_current_time)
    llm.register_function("switch_agent", switch_agent_handler)
    context_aggregator = llm.create_context_aggregator(OpenAILLMContext())

    async def handle_user_idle(processor: UserIdleProcessor, retry_count: int) -> bool:
        """Handle user idle with escalating prompts"""
        logger.info(f"User idle detected, retry count: {retry_count}")

        if retry_count == 1:
            user_instruction = "ask me if I am able to hear you"
            await processor.push_frame(LLMMessagesAppendFrame([{"role": "user", "content": user_instruction}], run_llm=True))
            return True  # Continue monitoring
        elif retry_count == 2:
            user_instruction = "ask me if I am still here"
            await processor.push_frame(LLMMessagesAppendFrame([{"role": "user", "content": user_instruction}], run_llm=True))
            return True  # Continue monitoring
        elif retry_count == 3:
            # Final attempt: speak the message.
            user_instruction = "Tell me that you are not able to hear me, and you are disconnecting the call and will call back again"
            await processor.push_frame(LLMMessagesAppendFrame([{"role": "user", "content": user_instruction}], run_llm=True))
            return True # Continue monitoring to allow message to be spoken
        elif retry_count == 4:
            # Terminate the call after the final message has been spoken.
            await processor.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
            return False # Stop monitoring
        else:
            logger.info(f"User idle after {retry_count} retries, stopping idle monitoring")
            return False

    pipeline = Pipeline([
        transport.input(),
        context_aggregator.user(),
        UserIdleProcessor(callback=handle_user_idle, timeout=5.0),
        llm,
        *([tts_service] if tts_service else []),
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=True, enable_usage_metrics=True))

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Pipecat Client connected")
        await task.queue_frames([context_aggregator.user()._get_context_frame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Pipecat Client disconnected")
        await task.cancel()

    await PipelineRunner(handle_sigint=False).run(task)
