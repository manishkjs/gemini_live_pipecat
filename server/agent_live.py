import os
import websockets
from typing import Optional
from loguru import logger
from fastapi import WebSocket
from datetime import datetime

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
from system_prompt import SYSTEM_PROMPT

SYSTEM_INSTRUCTION = SYSTEM_PROMPT

class CustomProtobufSerializer(ProtobufFrameSerializer):
    async def serialize(self, frame: Frame) -> bytes | None:
        if isinstance(frame, (StartInterruptionFrame, CancelFrame)):
            return None  # Don't serialize these frames
        data = await super().serialize(frame)
        if isinstance(data, str):
            return data.encode("utf-8")
        return data

async def get_current_time(params: FunctionCallParams):
    await params.result_callback(
        {"time": datetime.now().strftime("%A, %B %d, %Y %I:%M %p")}
    )

async def run_agent_live(
    websocket: WebSocket,
    api_key: str,
    model: str,
    voice: Optional[str],
    language: str,
    system_instruction: Optional[str] = None,
    tts: bool = True,
    tts_pace: float = 0.80,
):
    # When using external TTS (custom voice cloning), we use AI Studio
    # When using native Gemini voices, we use Vertex AI
    use_vertex = not tts
    
    if use_vertex:
        # Validate Vertex AI credentials
        # On Cloud Run, GOOGLE_APPLICATION_CREDENTIALS is not set (uses ADC)
        # so we don't strictly check for it.
        
        project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION")
        
        if not project_id:
            raise ValueError("GCP_PROJECT_ID or GOOGLE_CLOUD_PROJECT environment variable is required for Vertex AI")
        if not location:
            raise ValueError("GCP_LOCATION or GOOGLE_CLOUD_LOCATION environment variable is required for Vertex AI")
    else:
        # Validate AI Studio API key
        if not api_key:
            raise ValueError("Google API key is required for AI Studio (when using external TTS)")

    gender = "female"
    if voice == "Custom-Male":
        gender = "male"

    logger.info(f"Starting agent with language: {language}")
    
    if system_instruction:
        prompt_text = system_instruction
    else:
        prompt_text = SYSTEM_PROMPT.replace("female", gender)
    
    # Append language instruction to system prompt to ensure model respects the selection
    prompt_text += f"\n\nIMPORTANT: You must converse in {language} language."

    language_map = {
        "ar-XA": Language.AR,
        "bn-IN": Language.BN_IN,
        "cmn-CN": Language.CMN_CN,
        "de-DE": Language.DE_DE,
        "en-US": Language.EN_US,
        "en-GB": Language.EN_GB,
        "en-IN": Language.EN_IN,
        "en-AU": Language.EN_AU,
        "es-ES": Language.ES_ES,
        "es-US": Language.ES_US,
        "fr-FR": Language.FR_FR,
        "fr-CA": Language.FR_CA,
        "gu-IN": Language.GU_IN,
        "hi-IN": Language.HI_IN,
        "id-ID": Language.ID_ID,
        "it-IT": Language.IT_IT,
        "ja-JP": Language.JA_JP,
        "kn-IN": Language.KN_IN,
        "ko-KR": Language.KO_KR,
        "ml-IN": Language.ML_IN,
        "mr-IN": Language.MR_IN,
        "nl-NL": Language.NL_NL,
        "pl-PL": Language.PL_PL,
        "pt-BR": Language.PT_BR,
        "ru-RU": Language.RU_RU,
        "ta-IN": Language.TA_IN,
        "te-IN": Language.TE_IN,
        "th-TH": Language.TH_TH,
        "tr-TR": Language.TR_TR,
        "vi-VN": Language.VI_VN,
    }
    pipecat_language = language_map.get(language, Language.EN_US)
    transport = FastAPIWebsocketTransport(
        websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(),
            serializer=CustomProtobufSerializer(),
        )
    )

    time_function = FunctionSchema(
        name="get_current_time",
        description="Get the current time.",
        properties={},
        required=[],
    )

    #search_tool = {"google_search": {}}

    tools = ToolsSchema(
        standard_tools=[time_function],
        #custom_tools={AdapterType.GEMINI: [search_tool]},
    )

    # Determine if we need external TTS
    # We use external TTS if:
    # 1. The tts flag is explicitly True
    # 2. A cloned voice is requested (Custom-Male/Custom-Female)
    use_external_tts = tts or (voice in ["Custom-Male", "Custom-Female"])

    tts_service = None
    if use_external_tts:
        if voice == "Custom-Male":
            voice_key_path = os.getenv("CLONE_TTS_VOICE_KEY_MALE")
            if not voice_key_path:
                raise ValueError("CLONE_TTS_VOICE_KEY_MALE environment variable not set")
            with open(voice_key_path, "r") as f:
                key = f.read()
            tts_service = GoogleTTSService(
                voice_cloning_key=key,
                params=GoogleTTSService.InputParams(
                    language=Language.EN_US
                )
            )
        elif voice == "Custom-Female":
            voice_key_path = os.getenv("CLONE_TTS_VOICE_KEY_FEMALE")
            if not voice_key_path:
                raise ValueError("CLONE_TTS_VOICE_KEY_FEMALE environment variable not set")
            with open(voice_key_path, "r") as f:
                key = f.read()
            tts_service = GoogleTTSService(
                voice_cloning_key=key,
                params=GoogleTTSService.InputParams(
                    language=Language.EN_US
                )
            )
        else:
            # If voice is None or empty, use a default
            voice_id = voice if voice else "Aoede"
            tts_service = GoogleTTSService(
                voice_id=f"{language}-Chirp3-HD-{voice_id}",
                params=GoogleTTSService.InputParams(
                    language=pipecat_language
                )
            )

    # Determine LLM modalities based on TTS usage
    # If using external TTS, we only need TEXT from the LLM
    # If using native LLM audio, we need AUDIO from the LLM
    llm_modalities = GeminiModalities.TEXT if use_external_tts else GeminiModalities.AUDIO

    # Select LLM Service
    vertex_models = [
        "gemini-live-2.5-flash",
        "gemini-2.0-flash-live-preview-04-09",
        "gemini-live-2.5-flash-preview-native-audio-09-2025"
    ]
    
    if api_key and model not in vertex_models:
        # Use AI Studio (GeminiLiveLLMService)
        llm = GeminiLiveLLMService(
            api_key=api_key,
            model=f"models/{model}",
            system_instruction=prompt_text,
            tools=tools,
            transcribe_model_audio=True,
            params=InputParams(
                language=pipecat_language.value,
                modalities=llm_modalities,
            )
        )
    else:
        # Use Vertex AI (GeminiLiveVertexLLMService)
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"
        
        if not project_id:
            try:
                import google.auth
                _, project_id = google.auth.default()
                logger.info(f"Auto-detected GCP project: {project_id}")
            except Exception as e:
                logger.error(f"Could not auto-detect project ID: {e}")
                raise ValueError("GCP_PROJECT_ID environment variable not set and could not auto-detect")
        
        llm_params = {
            "project_id": project_id,
            "location": location,
            "model": f"google/{model}",
            "system_instruction": prompt_text,
            "tools": tools,
            "transcribe_model_audio": True,
            "params": InputParams(
                language=pipecat_language.value,
                modalities=llm_modalities,
            ),
        }
        
        if credentials_path:
            llm_params["credentials_path"] = credentials_path
        
        # Only pass voice_id if we are NOT using external TTS
        if not use_external_tts and voice:
            llm_params["voice_id"] = voice
            
        llm = GeminiLiveVertexLLMService(**llm_params)

    llm.register_function("get_current_time", get_current_time)

    context = OpenAILLMContext(
        [
            {
                "role": "user",
                "content": prompt_text,
            }
        ],
    )

    context_aggregator = llm.create_context_aggregator(context)

    # Create user idle handler with retry callback
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

    # Create idle processor with 5 second timeout
    user_idle = UserIdleProcessor(
        callback=handle_user_idle,
        timeout=5.0
    )

    pipeline_processors = [
        transport.input(),
        user_idle,  # Monitor user idle/activity
        context_aggregator.user(),
        llm,  # LLM
    ]

    if tts_service:
        pipeline_processors.append(tts_service)

    pipeline_processors.extend([
        transport.output(),
        context_aggregator.assistant(),
    ])

    pipeline = Pipeline(pipeline_processors)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Pipecat Client connected")
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Pipecat Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
