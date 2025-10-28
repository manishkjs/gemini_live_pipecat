"""
Telephony integration for Gemini Live using Twilio/Telnyx
Based on pipecat-quickstart-phone-bot example
"""
import os
from typing import Optional
from loguru import logger
from fastapi import WebSocket

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.gemini_multimodal_live.gemini import (
    GeminiMultimodalLiveLLMService,
    InputParams,
    GeminiMultimodalModalities,
)
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.services.google.tts import GoogleTTSService
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.frames.frames import LLMRunFrame
from pipecat.transcriptions.language import Language
from pipecat.runner.utils import parse_telephony_websocket
from system_prompt import SYSTEM_PROMPT


async def run_phone_bot(
    websocket: WebSocket,
    api_key: str,
    model: str = "gemini-2.0-flash-exp",
    voice: Optional[str] = "Puck",
    language: str = "en-US",
    system_instruction: Optional[str] = None,
):
    """
    Run a Gemini Live bot for telephony (Twilio/Telnyx)
    
    Args:
        websocket: FastAPI WebSocket connection
        api_key: Google/Gemini API key
        model: Gemini model to use
        voice: Voice ID for Gemini
        language: Language code (e.g., 'en-US')
        system_instruction: Custom system prompt (optional)
    """
    logger.info("run_phone_bot called - starting telephony bot")
    
    # If no API key passed through URL, try environment variable
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY", "")
        logger.info("API key not in URL, using environment variable")
    
    if not api_key:
        logger.error("No API key provided in URL or environment!")
        raise ValueError("Google API key is required - set GEMINI_API_KEY environment variable")

    # Parse telephony websocket to get provider and call metadata
    try:
        logger.info("About to parse telephony websocket...")
        transport_type, call_data = await parse_telephony_websocket(websocket)
        logger.info(f"Telephony provider detected: {transport_type}")
        logger.info(f"Call data: {call_data}")
    except Exception as e:
        logger.error(f"Failed to parse telephony websocket: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise

    # Create Twilio-specific serializer
    serializer = TwilioFrameSerializer(
        stream_sid=call_data.get("stream_id", ""),
        call_sid=call_data.get("call_id", ""),
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
    )

    # Map language codes
    language_map = {
        "en-US": Language.EN_US,
        "en-GB": Language.EN_GB,
        "en-IN": Language.EN_IN,
        "es-ES": Language.ES_ES,
        "fr-FR": Language.FR_FR,
        "hi-IN": Language.HI_IN,
    }
    pipecat_language = language_map.get(language, Language.EN_US)

    # Create transport with telephony settings
    # Telephony uses 8kHz audio (not 24kHz like browser)
    transport = FastAPIWebsocketTransport(
        websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,  # Telephony doesn't use WAV headers
            vad_analyzer=SileroVADAnalyzer(),
            serializer=serializer,
            audio_out_sample_rate=8000,  # Telephony standard
            audio_in_sample_rate=8000,   # Telephony standard
        ),
    )

    # Create Gemini Live LLM service
    # Note: Gemini outputs 24kHz, will need resampling for 8kHz telephony
    llm = GeminiMultimodalLiveLLMService(
        api_key=api_key,
        model=f"models/{model}",
        system_instruction=system_instruction or SYSTEM_PROMPT,
        transcribe_model_audio=True,
        params=InputParams(
            language=pipecat_language,
            modalities=GeminiMultimodalModalities.AUDIO,  # Audio mode for voice
        ),
    )

    # Create context aggregator
    context = OpenAILLMContext(
        [
            {
                "role": "system",
                "content": system_instruction or SYSTEM_PROMPT,
            }
        ],
    )
    context_aggregator = llm.create_context_aggregator(context)

    # Build pipeline
    # Note: For production, you'd add audio resampling processor here
    # to convert Gemini's 24kHz output to 8kHz for telephony
    pipeline = Pipeline(
        [
            transport.input(),           # Telephony audio input (8kHz)
            context_aggregator.user(),   # User transcription
            llm,                         # Gemini Live LLM
            # TODO: Add resampler here if Gemini outputs 24kHz
            transport.output(),          # Telephony audio output (8kHz)
            context_aggregator.assistant(),  # Bot transcription
        ]
    )

    # Create task
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,   # Match telephony
            audio_out_sample_rate=8000,  # Match telephony
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    # Event handlers
    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Phone call connected")
        # Start the conversation
        await task.queue_frames([
            context_aggregator.user().get_context_frame()
        ])
        # Optional: Have bot greet first
        # context.messages.append({
        #     "role": "system",
        #     "content": "Say hello and introduce yourself briefly."
        # })
        # await task.queue_frame(LLMRunFrame())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Phone call disconnected")
        await task.cancel()

    # Run the pipeline
    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)


async def run_phone_bot_with_tts(
    websocket: WebSocket,
    api_key: str,
    tts_voice: str = "en-US-Chirp3-HD-Puck",
    llm_model: str = "gemini-2.0-flash",
    language: str = "en-US",
    system_instruction: Optional[str] = None,
):
    """
    Run a traditional STT->LLM->TTS pipeline for telephony
    This uses separate services instead of Gemini Live
    
    Args:
        websocket: FastAPI WebSocket connection
        api_key: Google API key
        tts_voice: Google TTS voice ID
        llm_model: Gemini model for LLM
        language: Language code
        system_instruction: Custom system prompt
    """
    # Parse telephony websocket
    try:
        transport_type, call_data = await parse_telephony_websocket(websocket)
        logger.info(f"Telephony provider detected: {transport_type}")
    except Exception as e:
        logger.error(f"Failed to parse telephony websocket: {e}")
        raise

    # Create serializer
    serializer = TwilioFrameSerializer(
        stream_sid=call_data.get("stream_id", ""),
        call_sid=call_data.get("call_id", ""),
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
    )

    # Language mapping
    language_map = {
        "en-US": Language.EN_US,
        "en-GB": Language.EN_GB,
        "en-IN": Language.EN_IN,
        "es-ES": Language.ES_ES,
        "fr-FR": Language.FR_FR,
        "hi-IN": Language.HI_IN,
    }
    pipecat_language = language_map.get(language, Language.EN_US)

    # Create transport
    transport = FastAPIWebsocketTransport(
        websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(),
            serializer=serializer,
            audio_out_sample_rate=8000,
            audio_in_sample_rate=8000,
        ),
    )

    # Note: This is a placeholder - you'd need to add STT and LLM services
    # from pipecat.services.deepgram.stt import DeepgramSTTService
    # from pipecat.services.openai.llm import OpenAILLMService (or Gemini equivalent)
    
    logger.warning("run_phone_bot_with_tts is not fully implemented yet")
    logger.warning("Use run_phone_bot (Gemini Live) for now")
    
    # For now, just close the connection
    await websocket.close()
