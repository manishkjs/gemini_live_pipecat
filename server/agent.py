import os
import time
import asyncio
from typing import Optional, List
import re
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.google.vertex.llm import GoogleVertexLLMService

from pipecat.services.stt_service import STTService
from pipecat.services.google.stt import GoogleSTTService, language_to_google_stt_language
from pipecat.services.google.tts import GoogleTTSService, GeminiTTSService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.frames.frames import (Frame, TranscriptionFrame, InterimTranscriptionFrame, TextFrame, InterruptionFrame, CancelFrame,
                                   StartFrame, TTSAudioRawFrame, TTSStoppedFrame, ErrorFrame, OutputTransportMessageFrame, LLMRunFrame,
                                   InputTransportMessageFrame, LLMContextFrame, AudioRawFrame, UserAudioRawFrame,
                                   UserStartedSpeakingFrame, UserStoppedSpeakingFrame,
                                   VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.text.markdown_text_filter import MarkdownTextFilter
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from fastapi import WebSocket
from google import genai
from google.genai import types

from system_prompt import SYSTEM_PROMPT, tts_prompt, GEMINI_LLM_TTS_PROMPT

VALID_STT_MODELS = {
    "gemini-3.5-transcribe-live",
    "gemini-3.5-transcribe-live-aistudio",
    "chirp_3",
    "chirp_2",
    "latest_long",
    "latest_short",
    "telephony",
}

VALID_LLM_MODELS = {
    "gemini-3.7-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
}


def validate_stt_model(stt_model: Optional[str]) -> str:
    """Validates and sanitizes STT model choice, defaulting to gemini-3.5-transcribe-live."""
    if stt_model in VALID_STT_MODELS:
        return stt_model
    return "gemini-3.5-transcribe-live"


def validate_llm_model(llm_model: Optional[str]) -> str:
    """Validates and sanitizes LLM model choice, defaulting to gemini-3.7-flash."""
    if llm_model in VALID_LLM_MODELS:
        return llm_model
    return "gemini-3.7-flash"


class CustomProtobufSerializer(ProtobufFrameSerializer):
    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, (InterruptionFrame, CancelFrame)):
            return None  # Don't serialize these frames
        return await super().serialize(frame)


class CustomGeminiTranscribeLiveService(STTService):
    """Speech-to-Text streaming service using Gemini 3.5 Transcribe Live.
    
    Supports both Vertex AI (Enterprise ADC) and Google AI Studio endpoints over WebSockets.
    """
    def __init__(
        self,
        *,
        project_id: Optional[str] = None,
        location: str = "us-central1",
        api_key: Optional[str] = None,
        model: str = "gemini-3.5-transcribe-live",
        languages: Optional[List[Language]] = None,
        is_ai_studio: bool = False,
        sample_rate: int = 16000,
        **kwargs
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self.is_ai_studio = is_ai_studio
        self.project_id = project_id
        self.location = location
        self.languages = languages or [Language("en-US"), Language("hi-IN")]
        
        # Clean model naming
        clean_model = model.replace("-aistudio", "").strip()
        if is_ai_studio:
            self.model_name = clean_model
            self._client = genai.Client(api_key=api_key)
        else:
            self.model_name = clean_model
            self._client = genai.Client(vertexai=True, project=project_id, location=location)

        self._audio_queue = asyncio.Queue()
        self._streaming_task = None
        self._stream_start_wall_time = None
        self._user_started_speaking_time = None
        self._user_stopped_speaking_time = None

    def can_generate_metrics(self) -> bool:
        return True

    async def run_stt(self, audio: bytes):
        """Streaming STT processing handled in bidirectional _streaming_worker task."""
        if False:
            yield None

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._stream_start_wall_time = time.time()
        self._streaming_task = self.create_task(self._streaming_worker())

    async def stop(self, frame: Frame):
        await super().stop(frame)
        if self._streaming_task:
            await self.cancel_task(self._streaming_task)
            self._streaming_task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            self._user_started_speaking_time = time.time()
            self._user_stopped_speaking_time = None
        elif isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            self._user_stopped_speaking_time = time.time()
        elif isinstance(frame, AudioRawFrame):
            await self._audio_queue.put(frame)
            if self._audio_passthrough:
                await self.push_frame(frame, direction)
            return

        await super().process_frame(frame, direction)

    async def _streaming_worker(self):
        if self.is_ai_studio:
            tx_config = types.AudioTranscriptionConfig()
        else:
            lang_codes = [language_to_google_stt_language(lang) for lang in self.languages] if self.languages else []
            tx_config = types.AudioTranscriptionConfig(
                language_codes=lang_codes if lang_codes else None
            )

        config = types.LiveConnectConfig(
            response_modalities=["TEXT"],
            input_audio_transcription=tx_config
        )
        
        while True:
            try:
                async with self._client.aio.live.connect(model=self.model_name, config=config) as session:
                    logger.info(f"Gemini 3.5 Transcribe Live session connected ({'AI Studio' if self.is_ai_studio else 'Vertex AI'} - {self.model_name})")

                    async def send_audio():
                        while True:
                            audio_frame = await self._audio_queue.get()
                            if audio_frame and audio_frame.audio:
                                await session.send(
                                    input={"data": audio_frame.audio, "mime_type": f"audio/pcm;rate={audio_frame.sample_rate}"},
                                    end_of_turn=False
                                )
                            self._audio_queue.task_done()

                    async def receive_transcripts():
                        async for response in session.receive():
                            server_content = getattr(response, "server_content", None)
                            if not server_content:
                                continue
                            
                            input_transcription = getattr(server_content, "input_transcription", None)
                            if input_transcription and input_transcription.text:
                                transcript_text = input_transcription.text.strip()
                                if transcript_text:
                                    now = time.time()
                                    stt_latency = None
                                    if self._user_stopped_speaking_time:
                                        elapsed = now - self._user_stopped_speaking_time
                                        if 0.05 <= elapsed <= 15.0:
                                            stt_latency = elapsed
                                    elif self._user_started_speaking_time:
                                        elapsed = now - self._user_started_speaking_time
                                        if 0.05 <= elapsed <= 15.0:
                                            stt_latency = elapsed

                                    if stt_latency is not None:
                                        logger.info(f"STT Latency (Gemini 3.5 Transcribe Live): {stt_latency:.3f}s ({int(stt_latency*1000)}ms)")
                                        await self.push_frame(OutputTransportMessageFrame(message={
                                            "label": "rtvi-ai",
                                            "type": "server-message",
                                            "data": {
                                                'type': 'metrics',
                                                'payload': {'type': 'stt_latency', 'value': stt_latency}
                                            }
                                        }))

                                    is_turn_complete = getattr(server_content, "turn_complete", False)
                                    primary_lang = self.languages[0].value if self.languages else "en-US"
                                    if is_turn_complete:
                                        await self.push_frame(TranscriptionFrame(
                                            text=transcript_text,
                                            user_id=self._user_id,
                                            timestamp=time_now_iso8601(),
                                            language=primary_lang
                                        ))
                                    else:
                                        await self.push_frame(InterimTranscriptionFrame(
                                            text=transcript_text,
                                            user_id=self._user_id,
                                            timestamp=time_now_iso8601(),
                                            language=primary_lang
                                        ))

                    send_task = asyncio.create_task(send_audio())
                    receive_task = asyncio.create_task(receive_transcripts())
                    
                    done, pending = await asyncio.wait(
                        [send_task, receive_task],
                        return_when=asyncio.FIRST_EXCEPTION
                    )
                    for task in pending:
                        task.cancel()
                    for task in done:
                        if task.exception():
                            raise task.exception()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Gemini 3.5 Transcribe Live connection exception: {e}")
                await asyncio.sleep(1.0)



class CustomGoogleSTTService(GoogleSTTService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stream_start_wall_time = None
        self._user_started_speaking_time = None
        self._user_stopped_speaking_time = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            self._user_started_speaking_time = time.time()
            self._user_stopped_speaking_time = None
        elif isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            self._user_stopped_speaking_time = time.time()
        await super().process_frame(frame, direction)

    async def _request_generator(self):
        self._stream_start_wall_time = time.time()
        async for req in super()._request_generator():
            yield req

    async def _process_responses(self, streaming_recognize):
        try:
            async for response in streaming_recognize:
                if (int(time.time() * 1000) - self._stream_start_time) > self.STREAMING_LIMIT:
                    logger.debug("Stream timeout reached in response processing")
                    break

                if not response.results:
                    continue

                for result in response.results:
                    if not result.alternatives:
                        continue

                    transcript = result.alternatives[0].transcript
                    if not transcript:
                        continue

                    primary_language = self._get_language_codes()[0]

                    if result.is_final:
                        now = time.time()
                        stt_latency = None

                        try:
                            if getattr(result, "result_end_offset", None) and self._stream_start_wall_time:
                                dur = result.result_end_offset
                                if hasattr(dur, "total_seconds"):
                                    offset_secs = dur.total_seconds()
                                elif hasattr(dur, "seconds") and hasattr(dur, "nanos"):
                                    offset_secs = float(dur.seconds) + float(dur.nanos) / 1e9
                                else:
                                    offset_secs = float(dur)

                                speech_ended_wall = self._stream_start_wall_time + offset_secs
                                elapsed = now - speech_ended_wall
                                if 0.05 <= elapsed <= 15.0:
                                    stt_latency = elapsed

                            if stt_latency is None:
                                if self._user_stopped_speaking_time:
                                    elapsed = now - self._user_stopped_speaking_time
                                    if 0.05 <= elapsed <= 15.0:
                                        stt_latency = elapsed
                                elif self._user_started_speaking_time:
                                    elapsed = now - self._user_started_speaking_time
                                    if 0.05 <= elapsed <= 15.0:
                                        stt_latency = elapsed
                        except Exception as calc_err:
                            logger.warning(f"STT Latency calculation warning: {calc_err}")

                        if stt_latency is not None:
                            logger.info(f"STT Latency (Cloud Speech v2): {stt_latency:.3f}s ({int(stt_latency*1000)}ms)")
                            await self.push_frame(OutputTransportMessageFrame(message={
                                "label": "rtvi-ai",
                                "type": "server-message",
                                "data": {
                                    'type': 'metrics',
                                    'payload': {'type': 'stt_latency', 'value': stt_latency}
                                }
                            }))

                        self._last_transcript_was_final = True
                        await self.push_frame(
                            TranscriptionFrame(
                                transcript,
                                self._user_id,
                                time_now_iso8601(),
                                primary_language,
                                result=result,
                            )
                        )
                        await self.stop_processing_metrics()
                        await self._handle_transcription(
                            transcript,
                            is_final=True,
                            language=primary_language,
                        )
                    else:
                        self._last_transcript_was_final = False
                        await self.push_frame(
                            InterimTranscriptionFrame(
                                transcript,
                                self._user_id,
                                time_now_iso8601(),
                                primary_language,
                                result=result,
                            )
                        )
        except Exception as e:
            logger.debug(f"CustomGoogleSTTService response note: {e}")
            raise


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
        if not getattr(self, '_my_ttfb_start', None):
            self._my_ttfb_start = time.time()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if getattr(self, '_my_ttfb_start', None):
            latency = time.time() - self._my_ttfb_start
            self._my_ttfb_start = None
            if latency < 15.0:
                logger.info(f"TTS Latency: {latency:.3f}s")
                await self.push_frame(OutputTransportMessageFrame(message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        'type': 'metrics',
                        'payload': {'type': 'tts_latency', 'value': latency}
                    }
                }))

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
        if not getattr(self, '_my_ttfb_start', None):
            self._my_ttfb_start = time.time()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if getattr(self, '_my_ttfb_start', None):
            latency = time.time() - self._my_ttfb_start
            self._my_ttfb_start = None
            if latency < 15.0:
                logger.info(f"TTS Latency: {latency:.3f}s")
                await self.push_frame(OutputTransportMessageFrame(message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        'type': 'metrics',
                        'payload': {'type': 'tts_latency', 'value': latency}
                    }
                }))

class CustomGoogleVertexLLMService(GoogleVertexLLMService):
    def _maybe_unset_thinking_budget(self, generation_params: dict):
        try:
            model = self._settings.model or ""
            if "thinking_config" in generation_params:
                return
            if "gemini-3.7" in model or "gemini-2.5" in model:
                generation_params["thinking_config"] = {"thinking_budget": 0}
            elif "gemini-3.5-flash-lite" in model or "gemini-3.1" in model or "gemini-3-flash" in model:
                generation_params["thinking_config"] = {"thinking_level": "minimal"}
        except Exception as e:
            logger.error(f"Failed to unset thinking budget: {e}")

    async def start_ttfb_metrics(self):
        if not getattr(self, '_my_ttfb_start', None):
            self._my_ttfb_start = time.time()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if getattr(self, '_my_ttfb_start', None):
            latency = time.time() - self._my_ttfb_start
            self._my_ttfb_start = None
            if latency < 15.0:
                logger.info(f"LLM Latency: {latency:.3f}s")
                await self.push_frame(OutputTransportMessageFrame(message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        'type': 'metrics',
                        'payload': {'type': 'llm_latency', 'value': latency}
                    }
                }))

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


class TranscriptionBroadcaster(FrameProcessor):
    def __init__(self, participant: str):
        super().__init__()
        self.participant = participant

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            text = ""
            if isinstance(frame, (TranscriptionFrame, TextFrame)):
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

        await self.push_frame(frame, direction)


class StartTriggerProcessor(FrameProcessor):
    def __init__(self, context, context_aggregator, skip_stt: bool):
        super().__init__()
        self.context = context
        self.context_aggregator = context_aggregator
        self.skip_stt = skip_stt
        self.triggered = False

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        await super().process_frame(frame, direction)
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
                    await self.push_frame(LLMRunFrame())
                return
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

    clean_stt_model = validate_stt_model(stt_model)
    clean_llm_model = validate_llm_model(llm_model)

    stt = None
    if not skip_stt:
        stt_languages = [Language(lang.strip()) for lang in stt_language.split(',')] if stt_language else [Language("en-US"), Language("hi-IN")]
        if clean_stt_model.startswith("gemini-3.5-transcribe"):
            is_ai_studio = clean_stt_model.endswith("-aistudio")
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
                except Exception as sm_err:
                    logger.debug(f"[SecretManager] Dynamic GEMINI_API_KEY retrieval note: {sm_err}")

            stt_loc = "global" if not is_ai_studio else location
            stt = CustomGeminiTranscribeLiveService(
                project_id=project_id,
                location=stt_loc,
                api_key=gemini_api_key,
                model=clean_stt_model,
                languages=stt_languages,
                is_ai_studio=is_ai_studio,
            )
        else:
            # chirp_3 is hosted in US multi-region ("us"), while chirp_2 is in us-central1
            stt_loc = "us-central1" if ("chirp_2" in clean_stt_model) else "us"
            stt = CustomGoogleSTTService(
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
        final_system_instruction += "\n\nIMPORTANT: The user's input is raw audio. Listen to it and respond naturally. Strictly answer ONLY the current current user query. Do not bring up previous topics or simulate future turns."

    llm_location = "global" if any(k in clean_llm_model for k in ["gemini-3", "3.7", "3.5"]) else location
    
    thinking_config = None
    if "gemini-3.7" in clean_llm_model:
        thinking_config = GoogleLLMService.ThinkingConfig(thinking_budget=0)
    elif any(k in clean_llm_model for k in ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash"]):
        thinking_config = GoogleLLMService.ThinkingConfig(thinking_level="minimal")
    elif any(k in clean_llm_model for k in ["gemini-2.5-flash", "gemini-2.5-flash-lite"]):
        thinking_config = GoogleLLMService.ThinkingConfig(thinking_budget=0)

    llm = CustomGoogleVertexLLMService(
        project_id=project_id,
        location=llm_location,
        settings=GoogleVertexLLMService.Settings(
            model=clean_llm_model,
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
