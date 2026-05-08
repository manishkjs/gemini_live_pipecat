import os
import time
from typing import Optional
import re
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response import LLMUserContextAggregator, LLMAssistantContextAggregator
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.google.llm_vertex import GoogleVertexLLMService
from pipecat.processors.transcript_processor import TranscriptProcessor
from pipecat.services.google.stt import GoogleSTTService
from pipecat.services.google.tts import GoogleTTSService, GeminiTTSService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.frames.frames import (Frame, TranscriptionFrame, TextFrame, StartInterruptionFrame, CancelFrame,
                                   TTSAudioRawFrame, TTSStoppedFrame, ErrorFrame, OutputTransportMessageFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.text.markdown_text_filter import MarkdownTextFilter
from pipecat.transcriptions.language import Language
from pipecat.audio.vad.silero import SileroVADAnalyzer
from fastapi import WebSocket
from google import genai
from google.genai import types

from system_prompt import SYSTEM_PROMPT

class CustomProtobufSerializer(ProtobufFrameSerializer):
    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, (StartInterruptionFrame, CancelFrame)):
            return None  # Don't serialize these frames
        return await super().serialize(frame)


class CustomVertexGeminiTTSService(GeminiTTSService):
    def __init__(self, *, project_id: str, location: str, voice_id: str = "Puck", model: str = "gemini-2.5-flash-lite-preview-tts", voice_prompt: Optional[str] = None, language_code: Optional[str] = None, **kwargs):
        # Pass a dummy API key since we're using Vertex.
        super().__init__(api_key="dummy", voice_id=voice_id, model=model, **kwargs)
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

    async def run_tts(self, text: str):
        logger.debug(f"{self}: Generating TTS [{text}]")
        try:
            await self.start_ttfb_metrics()

            speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice_id)),
                language_code=self._language_code
            )
            generate_content_config = types.GenerateContentConfig(
                response_modalities=["AUDIO"], 
                speech_config=speech_config,
                system_instruction=self._voice_prompt
            )

            structured_prompt = f"""Synthesize speech for the performance defined below. The profile, scene,
performance notes, and context are direction only. Do NOT speak them.
Speak ONLY the lines under #### TRANSCRIPT.

# AUDIO PROFILE: Aria
## "Empathetic AI Companion"

## SCENE: A warm, friendly conversation
Aria is chatting with the user, offering support and conversation with a genuine, human-like feel.

### PERFORMANCE
Style: Warm and sincere. The voice carries feeling and expressiveness.
Pace: Natural, conversational.

### CONTEXT
Aria is a professional and empathetic voice assistant designed to sound like a real human.

#### TRANSCRIPT
{text}
"""

            async for chunk in await self._client.aio.models.generate_content_stream(
                model=self._model, contents=structured_prompt, config=generate_content_config,
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
        from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContextFrame
        if isinstance(frame, OpenAILLMContextFrame):
            logger.info(f"ContextLogger [{self.logger_name}]: Received OpenAILLMContextFrame")
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
            vad_analyzer=SileroVADAnalyzer(),
            serializer=CustomProtobufSerializer(),
        ),
    )

    stt = None
    if not skip_stt:
        stt_location = location if "chirp_2" in stt_model else "us"
        stt = GoogleSTTService(
            vertexai_project=project_id,
            location=stt_location,
            params=GoogleSTTService.InputParams(
                languages=[Language(lang) for lang in stt_language.split(',')] if stt_language else [Language("en-US")],
                model=stt_model,
                enable_interim_results=True,
            )
        )

    final_system_instruction = system_instruction or SYSTEM_PROMPT


    if skip_stt:
        final_system_instruction += "\n\nIMPORTANT: The user's input is raw audio. Listen to it and respond naturally. Strictly answer ONLY the current user query. Do not bring up previous topics or simulate future turns."

    llm_location = "global" if "gemini-3" in llm_model else location
    llm_params = None
    if llm_model in ["gemini-3.1-flash-lite-preview", "gemini-3-flash-preview"]:
        llm_params = GoogleVertexLLMService.InputParams(
            max_tokens=4096,
            extra={
                "thinking_config": {
                    "thinking_level": "minimal"
                }
            }
        )

    llm = CustomGoogleVertexLLMService(
        project_id=project_id,
        location=llm_location,
        model=llm_model,
        system_instruction=final_system_instruction,
        params=llm_params
    )

    if tts_model.startswith("gemini"):
        # Use Gemini TTS (Vertex AI) requires 24kHz
        tts_location = "global" if "gemini-3" in tts_model else location
        tts = CustomVertexGeminiTTSService(
            project_id=project_id,
            location=tts_location,
            voice_id=tts_voice,
            model=tts_model, # Use the conditionally passed model
            sample_rate=24000, 
            voice_prompt=tts_voice_prompt,
            language_code=stt_language.lower() if stt_language else None
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

    if skip_stt:
        from pipecat.services.google.llm import GoogleLLMContext
        from processors.audio_accumulator import AudioAccumulator
        from pipecat.frames.frames import LLMContextFrame
        context = GoogleLLMContext()
        context.set_messages([{"role": "system", "content": final_system_instruction}])
        stt_languages = [lang.strip() for lang in stt_language.split(',')] if stt_language else ["en-US"]
        accumulator = AudioAccumulator(
            context,
            project_id=project_id,
            stt_languages=stt_languages,
        )
        context_aggregator = llm.create_context_aggregator(context)

        pipeline_elements = [
            transport.input(),
            accumulator,
            llm,
            TranscriptionBroadcaster(participant="Bot"),
            tts,
            context_aggregator.assistant(),
            transport.output()
        ]
    else:
        context = OpenAILLMContext(messages=[{"role": "system", "content": final_system_instruction}])
        context_aggregator = llm.create_context_aggregator(context)
        transcript = TranscriptProcessor()
        
        pipeline_elements = [
            transport.input(),
            stt,
            TranscriptionBroadcaster(participant="User"),
            transcript.user(),
            context_aggregator.user(),
            ContextLogger(logger_name="UserToLLM"),
            llm,
            TranscriptionBroadcaster(participant="Bot"),
            tts,
            transcript.assistant(),
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
        if skip_stt:
            await task.queue_frames([LLMContextFrame(context)])
        else:
            await task.queue_frames([context_aggregator.user()._get_context_frame()])

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
