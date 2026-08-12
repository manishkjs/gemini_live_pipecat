import os
import time
import asyncio
from typing import Optional
import re
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
# Obsolete context aggregator imports removed
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.google.vertex.llm import GoogleVertexLLMService

from pipecat.services.stt_service import STTService
from pipecat.services.google.stt import GoogleSTTService
from pipecat.services.google.tts import GoogleTTSService, GeminiTTSService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.frames.frames import (Frame, TranscriptionFrame, InterimTranscriptionFrame, TextFrame, InterruptionFrame, CancelFrame,
                                   TTSAudioRawFrame, TTSStoppedFrame, ErrorFrame, OutputTransportMessageFrame, LLMRunFrame,
                                   InputTransportMessageFrame, LLMContextFrame, AudioRawFrame, UserAudioRawFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.text.markdown_text_filter import MarkdownTextFilter
from pipecat.transcriptions.language import Language
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from fastapi import WebSocket
from google import genai
from google.genai import types

from system_prompt import SYSTEM_PROMPT, tts_prompt, GEMINI_LLM_TTS_PROMPT

class CustomProtobufSerializer(ProtobufFrameSerializer):
    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, (InterruptionFrame, CancelFrame)):
            return None  # Don't serialize these frames
        return await super().serialize(frame)


class CustomVertexGeminiTTSService(GeminiTTSService):
    def __init__(self, *, project_id: str, location: str, voice_id: str = "Puck", model: str = "gemini-2.5-flash-lite-preview-tts", voice_prompt: Optional[str] = None, language_code: Optional[str] = None, **kwargs):
        # Pass a dummy API key since we're using Vertex.
        settings = GeminiTTSService.Settings(
            voice=voice_id,
            model=model,
            prompt=voice_prompt,
            language=language_code or "en-US"
        )
        super().__init__(api_key="dummy", settings=settings, **kwargs)
        self._client = genai.Client(vertexai=True, project=project_id, location=location)
        self._voice_prompt = voice_prompt
        self._language_code = language_code

    async def start_ttfb_metrics(self):
        self._my_ttfb_start = time.time()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if hasattr(self, '_my_ttfb_start') and self._my_ttfb_start:
            latency = time.time() - self._my_ttfb_start
            logger.info(f"TTS Latency: {latency}s")
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'metrics',
                    'payload': {'type': 'tts_latency', 'value': latency}
                }
            }))
            self._my_ttfb_start = None

    async def run_tts(self, text: str, context_id: str):
        logger.debug(f"{self}: Generating TTS [{text}]")
        try:
            await self.start_ttfb_metrics()

            # Ensure language_code is a single valid BCP-47 tag (e.g. "hi-IN")
            lang_code = self._language_code
            if lang_code and "," in lang_code:
                langs = [l.strip() for l in lang_code.split(",")]
                hi_lang = next((l for l in langs if "hi" in l.lower()), None)
                lang_code = hi_lang if hi_lang else langs[0]

            speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._settings.voice)),
                language_code=lang_code
            )
            generate_content_config = types.GenerateContentConfig(
                response_modalities=["AUDIO"], 
                speech_config=speech_config,
                system_instruction=self._voice_prompt
            )

            structured_prompt = f"""Synthesize speech for the performance defined below. The profile, scene,
performance notes, and context are direction only. Do NOT speak them.
Speak ONLY the lines under #### TRANSCRIPT.

# AUDIO PROFILE: {self._settings.voice}
## "Empathetic Voice Assistant"

## SCENE: A warm, natural conversation in colloquial Hindi/English

### PERFORMANCE
Style: Warm, expressive, natural voice.
Pace: Conversational.

#### TRANSCRIPT
{text}
"""

            async for chunk in await self._client.aio.models.generate_content_stream(
                model=self._settings.model, contents=structured_prompt, config=generate_content_config,
            ):
                if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
                    continue
                part = chunk.candidates[0].content.parts[0]
                if part.inline_data and part.inline_data.data:
                    audio_data = part.inline_data.data
                    await self.stop_ttfb_metrics()
                    CHUNK_SIZE = self.chunk_size
                    for i in range(0, len(audio_data), CHUNK_SIZE):
                        chunk_bytes = audio_data[i : i + CHUNK_SIZE]
                        if not chunk_bytes: break
                        yield TTSAudioRawFrame(chunk_bytes, self.sample_rate or 24000, 1)

            yield TTSStoppedFrame()
        except Exception as e:
            logger.exception(f"{self} error generating TTS: {e}")
            yield ErrorFrame(error=f"Gemini TTS generation error: {str(e)}")


class CustomGoogleTTSService(GoogleTTSService):
    async def start_ttfb_metrics(self):
        self._my_ttfb_start = time.time()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if hasattr(self, '_my_ttfb_start') and self._my_ttfb_start:
            latency = time.time() - self._my_ttfb_start
            logger.info(f"TTS Latency: {latency}s")
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'metrics',
                    'payload': {'type': 'tts_latency', 'value': latency}
                }
            }))
            self._my_ttfb_start = None

class CustomGoogleVertexLLMService(GoogleVertexLLMService):
    async def start_ttfb_metrics(self):
        self._my_ttfb_start = time.time()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if hasattr(self, '_my_ttfb_start') and self._my_ttfb_start:
            latency = time.time() - self._my_ttfb_start
            logger.info(f"LLM Latency: {latency}s")
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'metrics',
                    'payload': {'type': 'llm_latency', 'value': latency}
                }
            }))
            self._my_ttfb_start = None

    async def start_llm_usage_metrics(self, metrics):
        await super().start_llm_usage_metrics(metrics)
        
        prompt_tokens = getattr(metrics, "prompt_tokens", 0) or 0
        completion_tokens = getattr(metrics, "completion_tokens", 0) or 0
        total_tokens = getattr(metrics, "total_tokens", 0) or (prompt_tokens + completion_tokens)
        
        logger.info(f"LLM Token Usage: Prompt: {prompt_tokens}, Response: {completion_tokens}, Total: {total_tokens}")
        
        await self.push_frame(OutputTransportMessageFrame(message={
            "label": "rtvi-ai",
            "type": "server-message",
            "data": {
                'type': 'metrics',
                'payload': {
                    'type': 'usage',
                    'usage': {
                        "prompt_token_count": prompt_tokens,
                        "response_token_count": completion_tokens,
                        "total_token_count": total_tokens,
                        "prompt_details": {"text": prompt_tokens},
                        "response_details": {"text": completion_tokens}
                    }
                }
            }
        }))


class GeminiLiveSTTService(STTService):
    def __init__(
        self,
        *,
        model: str = "gemini-3.5-transcribe-live-preview",
        project_id: Optional[str] = None,
        location: str = "us-central1",
        api_key: Optional[str] = None,
        **kwargs
    ):
        super().__init__(sample_rate=16000, **kwargs)
        self._model = model
        self._project_id = project_id or "deep-clock-339817"
        self._location = location
        self._api_key = api_key
        self._client = None
        self._session = None
        self._audio_queue = asyncio.Queue(maxsize=200)
        self._sender_task = None
        self._receiver_task = None
        self._running = False

    async def start(self, frame_processor):
        await super().start(frame_processor)
        self._running = True
        self._sender_task = self.create_task(self._session_loop())

    async def _session_loop(self):
        try:
            if self._api_key:
                self._client = genai.Client(api_key=self._api_key, http_options={"api_version": "v1alpha"})
            else:
                self._client = genai.Client(vertexai=True, project=self._project_id, location=self._location)

            config = types.LiveConnectConfig(
                response_modalities=["TEXT"],
            )
            model_target = self._model
            if not model_target.startswith("models/") and not model_target.startswith("projects/") and not model_target.startswith("publishers/"):
                model_target = f"models/{model_target}" if self._api_key else f"publishers/google/models/{model_target}"

            logger.info(f"GeminiLiveSTTService connecting to {model_target}...")
            async with self._client.aio.live.connect(model=model_target, config=config) as session:
                self._session = session
                logger.info(f"GeminiLiveSTTService connected successfully to {model_target}")
                self._receiver_task = self.create_task(self._receive_loop())

                while self._running:
                    chunk = await self._audio_queue.get()
                    if chunk is None:
                        break
                    await session.send_realtime_input(media_chunks=[{"data": chunk, "mime_type": "audio/pcm"}])
        except Exception as e:
            logger.warning(f"GeminiLiveSTTService session note: {e}")
        finally:
            if self._receiver_task:
                await self.cancel_task(self._receiver_task)

    async def _receive_loop(self):
        try:
            if not self._session:
                return
            async for response in self._session.receive():
                sc = getattr(response, "server_content", None)
                if not sc:
                    continue
                # Interim transcription
                if getattr(sc, "interim_input_transcription", None) and sc.interim_input_transcription.text:
                    txt = sc.interim_input_transcription.text
                    await self.push_frame(InterimTranscriptionFrame(text=txt, user_id="user", timestamp=time.strftime("%H:%M:%S")))
                # Final transcription
                elif getattr(sc, "input_transcription", None) and sc.input_transcription.text:
                    txt = sc.input_transcription.text
                    await self.push_frame(TranscriptionFrame(text=txt, user_id="user", timestamp=time.strftime("%H:%M:%S")))
                elif getattr(sc, "model_turn", None):
                    for part in sc.model_turn.parts:
                        if getattr(part, "text", None):
                            await self.push_frame(TranscriptionFrame(text=part.text, user_id="user", timestamp=time.strftime("%H:%M:%S")))
        except Exception as e:
            logger.debug(f"GeminiLiveSTTService receive loop note: {e}")

    async def run_stt(self, audio: bytes):
        if self._running:
            if self._audio_queue.full():
                try:
                    self._audio_queue.get_nowait()
                except Exception:
                    pass
            await self._audio_queue.put(audio)
        yield None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, (AudioRawFrame, UserAudioRawFrame)):
            if self._audio_queue.full():
                try:
                    self._audio_queue.get_nowait()
                except Exception: pass
            await self._audio_queue.put(frame.audio)
        await self.push_frame(frame, direction)

    async def stop(self, frame_processor):
        self._running = False
        if self._audio_queue:
            await self._audio_queue.put(None)
        if self._sender_task:
            await self.cancel_task(self._sender_task)
        await super().stop(frame_processor)


class TranscriptionBroadcaster(FrameProcessor):
    def __init__(self, participant: str):
        super().__init__()
        self.participant = participant

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if direction == FrameDirection.DOWNSTREAM:
            text = ""
            if isinstance(frame, TranscriptionFrame):
                text = frame.text
            elif isinstance(frame, TextFrame):
                text = frame.text

            if text:
                ui_text = re.sub(r'\[.*?\]', '', text).strip()
                if ui_text:
                    logger.info(f"TranscriptionBroadcaster [{self.participant}]: {ui_text}")
                    await self.push_frame(OutputTransportMessageFrame(message={
                        "label": "rtvi-ai",
                        "type": "server-message",
                        "data": {
                            'type': 'transcription',
                            'participant': self.participant,
                            'text': ui_text
                        }
                    }))

        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class ContextLogger(FrameProcessor):
    def __init__(self, logger_name: str):
        super().__init__()
        self.logger_name = logger_name

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        from pipecat.frames.frames import LLMContextFrame
        if isinstance(frame, LLMContextFrame):
            logger.info(f"ContextLogger [{self.logger_name}]: Received LLMContextFrame")
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class StartTriggerProcessor(FrameProcessor):
    def __init__(self, context, context_aggregator, skip_stt: bool):
        super().__init__()
        self.context = context
        self.context_aggregator = context_aggregator
        self.skip_stt = skip_stt
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
                    logger.info("[StartTriggerProcessor] start_trigger received. Queueing initial greeting turn.")
                    if self.skip_stt:
                        await self.push_frame(LLMContextFrame(self.context))
                        await self.push_frame(LLMRunFrame())
                    else:
                        await self.push_frame(self.context_aggregator.user()._get_context_frame())
                        await self.push_frame(LLMRunFrame())
                return
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


async def run_agent(
    websocket: WebSocket,
    tts_voice: str,
    tts_pace: float,
    llm_model: str,
    stt_model: str,
    stt_language: str,
    tts_model: str = "google-tts",
    tts_voice_prompt: Optional[str] = None,
    system_instruction: Optional[str] = None,
    skip_stt: bool = False,
):
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
    location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"

    transport = FastAPIWebsocketTransport(
        websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.4)),
            serializer=CustomProtobufSerializer(),
        ),
    )

    stt = None
    if not skip_stt:
        valid_stt_models = {"chirp_3", "chirp_2", "latest_long", "latest_short", "telephony"}
        clean_stt_model = stt_model if stt_model in valid_stt_models else "chirp_3"
        # chirp_3 is hosted in US multi-region ("us"), while chirp_2 is in us-central1
        stt_loc = "us-central1" if ("chirp_2" in clean_stt_model) else "us"
        
        stt_languages = [Language(lang.strip()) for lang in stt_language.split(',')] if stt_language else [Language("en-US"), Language("hi-IN")]
        
        stt = GoogleSTTService(
            vertexai_project=project_id,
            location=stt_loc,
            settings=GoogleSTTService.Settings(
                languages=stt_languages,
                model=clean_stt_model,
                enable_interim_results=True,
            )
        )

    final_system_instruction = system_instruction or SYSTEM_PROMPT
    if tts_model.startswith("gemini"):
        final_system_instruction += "\n\n" + GEMINI_LLM_TTS_PROMPT

    if skip_stt:
        final_system_instruction += "\n\nIMPORTANT: The user's input is raw audio. Listen to it and respond naturally. Strictly answer ONLY the current user query. Do not bring up previous topics or simulate future turns."

    llm_location = "global" if any(k in llm_model for k in ["gemini-3", "3.6", "3.5"]) else location
    
    thinking_config = None
    if any(k in llm_model for k in ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite-preview", "gemini-3-flash-preview", "gemini-3.5-flash-preview", "gemini-3.5-flash"]):
        thinking_config = GoogleLLMService.ThinkingConfig(thinking_level="minimal")

    llm = CustomGoogleVertexLLMService(
        project_id=project_id,
        location=llm_location,
        settings=GoogleVertexLLMService.Settings(
            model=llm_model,
            system_instruction=final_system_instruction,
            max_tokens=1024 if thinking_config else 4096,
            thinking=thinking_config
        )
    )

    if tts_model.startswith("gemini"):
        # Use Gemini TTS (Vertex AI) requires 24kHz
        tts_location = "global" if "gemini-3" in tts_model else location
        
        tts_lang = "hi-IN"
        if stt_language:
            langs = [l.strip() for l in stt_language.split(",")]
            hi_lang = next((l for l in langs if "hi" in l.lower()), None)
            tts_lang = hi_lang if hi_lang else langs[0]

        tts = CustomVertexGeminiTTSService(
            project_id=project_id,
            location=tts_location,
            voice_id=tts_voice,
            model=tts_model, # Use the conditionally passed model
            sample_rate=24000, 
            voice_prompt=tts_voice_prompt,
            language_code=tts_lang,
            text_filters=[MarkdownTextFilter()]
        )
    elif tts_voice in ["Custom-Male", "Custom-Female"]:
        # For cloned voices, use en-US as the base language code
        # The voice cloning will handle the accent/style
        tts_language = "en-US"
        if tts_voice == "Custom-Male":
            voice_key_path = os.getenv("CLONE_TTS_VOICE_KEY_MALE")
            if not voice_key_path:
                raise ValueError("CLONE_TTS_VOICE_KEY_MALE environment variable not set")
            with open(voice_key_path, "r") as f:
                key = f.read()
            tts = CustomGoogleTTSService(
                voice_cloning_key=key,
                params=GoogleTTSService.InputParams(
                    language=Language(tts_language),
                    speaking_rate=tts_pace
                ),
                text_filters=[MarkdownTextFilter()],
            )
        else:  # Custom-Female
            voice_key_path = os.getenv("CLONE_TTS_VOICE_KEY_FEMALE")
            if not voice_key_path:
                raise ValueError("CLONE_TTS_VOICE_KEY_FEMALE environment variable not set")
            with open(voice_key_path, "r") as f:
                key = f.read()
            tts = CustomGoogleTTSService(
                voice_cloning_key=key,
                params=GoogleTTSService.InputParams(
                    language=Language(tts_language),
                    speaking_rate=tts_pace
                ),
                text_filters=[MarkdownTextFilter()],
            )
    else:
        tts_language = "-".join(tts_voice.split("-")[:2])
        tts = CustomGoogleTTSService(
            voice_id=tts_voice,
            params=GoogleTTSService.InputParams(
                language=Language(tts_language),
                speaking_rate=tts_pace
            ),
            text_filters=[MarkdownTextFilter()],
        )

    is_hindi = bool(stt_language and any(l in stt_language.lower() for l in ["hi", "hindi"]))
    initial_greeting = "नमस्ते!" if is_hindi else "Hello!"

    if skip_stt:
        from pipecat.services.google.llm import GoogleLLMContext
        from processors.audio_accumulator import AudioAccumulator
        context = GoogleLLMContext()
        context.set_messages([
            {"role": "system", "content": final_system_instruction},
            {"role": "user", "content": initial_greeting}
        ])
        stt_languages = [lang.strip() for lang in stt_language.split(',')] if stt_language else ["en-US"]
        accumulator = AudioAccumulator(
            context,
            project_id=project_id,
            stt_languages=stt_languages,
        )
        context_aggregator = LLMContextAggregatorPair(context)
        start_trigger = StartTriggerProcessor(context, context_aggregator, skip_stt=True)

        pipeline_elements = [
            transport.input(),
            start_trigger,
            accumulator,
            llm,
            TranscriptionBroadcaster(participant="Bot"),
            tts,
            context_aggregator.assistant(),
            transport.output()
        ]
    else:
        context = LLMContext(messages=[
            {"role": "system", "content": final_system_instruction},
            {"role": "user", "content": initial_greeting}
        ])
        context_aggregator = LLMContextAggregatorPair(context)
        start_trigger = StartTriggerProcessor(context, context_aggregator, skip_stt=False)

        pipeline_elements = [
            transport.input(),
            start_trigger,
            stt,
            TranscriptionBroadcaster(participant="User"),
            context_aggregator.user(),
            ContextLogger(logger_name="UserToLLM"),
            llm,
            TranscriptionBroadcaster(participant="Bot"),
            tts,
            context_aggregator.assistant(),
            transport.output()
        ]

    pipeline = Pipeline(pipeline_elements)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            report_only_initial_ttfb=False,
            audio_in_sample_rate=16000,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Pipecat Client connected to STT-LLM-TTS pipeline")
        # Defer greeting until start_trigger message is received when user clicks Start Listening

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
