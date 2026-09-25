import os
import warnings
warnings.filterwarnings("ignore", message=".*grpcio < 1.83.0.*", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*vertexai.preview.rag.*")
import time
import asyncio
from typing import Optional, List
import re
from loguru import logger
from diagnostic_buffer import current_session_id
from response_identity import ResponseIdentity

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor, RTVI
import pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy as _turn_stop_mod
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.google.vertex.llm import GoogleVertexLLMService

from pipecat.services.stt_service import STTService, STTSettings

# Cascade uses VAD stop_secs=0.4 and passes a ttfs_p99_latency measured at that setting,
# which is what Pipecat's advisory warning asks for. This constant is only read by that warning.
_turn_stop_mod.VAD_STOP_SECS = 0.4
_orig_rtvi_handle_client_ready = RTVIProcessor._handle_client_ready
async def _compat_rtvi_handle_client_ready(self, request_id: str, data):
    if data is not None and getattr(data, "version", None):
        data.version = RTVI.PROTOCOL_VERSION
    return await _orig_rtvi_handle_client_ready(self, request_id, data)
RTVIProcessor._handle_client_ready = _compat_rtvi_handle_client_ready
from pipecat.services.google.stt import GoogleSTTService, language_to_google_stt_language
from pipecat.services.google.tts import GoogleTTSService, GeminiTTSService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.frames.frames import (Frame, TranscriptionFrame, InterimTranscriptionFrame, TextFrame, InterruptionFrame, CancelFrame,
                                   StartFrame, LLMFullResponseEndFrame, TTSAudioRawFrame, TTSStoppedFrame, ErrorFrame, OutputTransportMessageUrgentFrame as OutputTransportMessageFrame, LLMRunFrame,
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
import voice_profiles
from turn_telemetry import TurnTracker
from stt_latency import FirstByteAfterSpeechEnd
from processors.turn_telemetry import TurnBoundaryProcessor, TurnOriginMixin, ServerAudioTimingProcessor
from cascade_pricing import CascadeCostLedger
from cascade_metering import publish_cost, observe_tokens, billed_duration


VALID_STT_MODELS = {
    "gemini-3.5-transcribe-live-preview",
    "gemini-3.5-transcribe-live-aistudio",
    "gemini-3.5-transcribe-live",
    "chirp_3",
    "chirp_2",
    "latest_long",
    "latest_short",
    "telephony",
}

VALID_LLM_MODELS = {
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash-lite-aistudio",
    "gemini-3.8-flash",
    "gemini-3.8-flash-aistudio",
    "gemini-3.7-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
}

VALID_TTS_MODELS = {
    "gemini-3.8-flash-tts",
    "gemini-3.8-flash-lite-tts",
    "gemini-3.8-flash-tts-aistudio",
    "gemini-3.8-flash-lite-tts-aistudio",
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-lite-preview-tts",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
    "google-tts",
}

AI_STUDIO_TTS_MODELS = {
    "gemini-3.8-flash-tts",
    "gemini-3.8-flash-lite-tts",
    "gemini-3.8-flash-tts-aistudio",
    "gemini-3.8-flash-lite-tts-aistudio",
}

PERSONA_VOICE_DESIGN_DEFAULTS = {
    "pragya": {
        "voice": "Gacrux",
        "style": "Warm & Friendly",
        "pace": "Natural",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Poised, refined luxury automotive concierge. Warm, welcoming, confident Indian female voice.",
    },
    "debt-collector": {
        "voice": "Gacrux",
        "style": "Empathetic",
        "pace": "Natural",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Calm, composed, empathetic yet firm financial collections advisor.",
    },
    "storyteller": {
        "voice": "Gacrux",
        "style": "Expressive / Dramatic",
        "pace": "Conversational",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Immersive, expressive cinematic storyteller with engaging emotional range and suspenseful pauses.",
    },
    "mf-advisor": {
        "voice": "Aoede",
        "style": "Professional",
        "pace": "Natural",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Clear, trustworthy, articulate wealth and mutual-fund financial advisor.",
    },
    "glass-buddy": {
        "voice": "Aoede",
        "style": "Cheerful",
        "pace": "Conversational",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Friendly, upbeat smart-glasses AI companion.",
    },
}


def validate_stt_model(stt_model: Optional[str]) -> str:
    """Validates and sanitizes STT model choice, defaulting to gemini-3.5-transcribe-live-aistudio."""
    if stt_model in VALID_STT_MODELS:
        return stt_model
    return "gemini-3.5-transcribe-live-aistudio"


def validate_llm_model(llm_model: Optional[str]) -> str:
    """Validates and sanitizes LLM model choice, defaulting to gemini-3.5-flash-lite."""
    if llm_model in VALID_LLM_MODELS:
        return llm_model
    return "gemini-3.5-flash-lite"


def validate_tts_model(tts_model: Optional[str]) -> str:
    """Validates and sanitizes TTS model choice, defaulting to gemini-3.8-flash-lite-tts."""
    if tts_model in VALID_TTS_MODELS:
        return tts_model
    return "gemini-3.8-flash-lite-tts"


def build_cascade_thinking_config(actual_llm_model: str):
    """Build low-latency ThinkingConfig for Cascade LLMs.

    gemini-3.8-flash and gemini-3.7-flash reject THINKING_LEVEL_MINIMAL with
    400 INVALID_ARGUMENT on both Vertex AI and AI Studio, and require
    thinking_budget=0 to suppress reasoning tokens in real-time voice turns.
    """
    if any(k in actual_llm_model for k in ["gemini-3.8", "gemini-3.7", "gemini-2.5-flash", "gemini-2.5-flash-lite"]):
        return GoogleLLMService.ThinkingConfig(thinking_budget=0)
    if any(k in actual_llm_model for k in ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash"]):
        return GoogleLLMService.ThinkingConfig(thinking_level="minimal")
    return None


class CustomProtobufSerializer(ProtobufFrameSerializer):
    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, (InterruptionFrame, CancelFrame)):
            return None  # Don't serialize these frames
        return await super().serialize(frame)


class CustomGeminiTranscribeLiveService(TurnOriginMixin, STTService):
    """Speech-to-Text streaming service using Gemini 3.5 Transcribe Live.
    
    Supports both Vertex AI (Enterprise ADC) and Google AI Studio endpoints over WebSockets.
    """
    def __init__(
        self,
        *,
        project_id: Optional[str] = None,
        location: str = "global",
        api_key: Optional[str] = None,
        model: str = "gemini-3.5-transcribe-live-aistudio",
        languages: Optional[List[Language]] = None,
        is_ai_studio: bool = False,
        sample_rate: int = 16000,
        **kwargs
    ):
        self.is_ai_studio = is_ai_studio
        self.project_id = project_id
        self.location = location
        self.languages = languages or [Language("en-US"), Language("hi-IN")]
        
        # Clean model naming
        clean_model = model.replace("-aistudio", "").strip()
        if is_ai_studio:
            self.model_name = clean_model
        else:
            self.model_name = clean_model if clean_model.endswith("-preview") else f"{clean_model}-preview"

        primary_lang = self.languages[0] if self.languages else Language("en-US")
        super().__init__(
            sample_rate=sample_rate,
            # Drives TurnAnalyzerUserTurnStopStrategy's transcript wait (ttfs - VAD stop_secs = 2.0 - 0.4 = 1.6s).
            # Measured Transcribe Live speech-end -> final transcript is ~1.2-1.7s in prod logs.
            ttfs_p99_latency=2.0,
            settings=STTSettings(model=self.model_name, language=primary_lang),
            **kwargs,
        )
        if is_ai_studio:
            self._client = genai.Client(api_key=api_key)
        else:
            self._client = genai.Client(vertexai=True, project=project_id, location=location)

        self._audio_queue = asyncio.Queue()
        self._streaming_task = None
        self._stopping = False
        self._stream_start_wall_time = None
        self._latency_clock = FirstByteAfterSpeechEnd()
        self._vad_stop_secs = 0.4

    def can_generate_metrics(self) -> bool:
        return True

    async def _emit_stt_latency(self, latency: Optional[float]):
        """STT latency = true end of user speech -> first transcript byte from Transcribe Live."""
        if latency is None:
            return
        logger.info(f"STT Latency (Gemini 3.5 Transcribe Live, speech end -> first byte): {int(latency * 1000)}ms")
        msg = OutputTransportMessageFrame(message={
            "label": "rtvi-ai",
            "type": "server-message",
            "data": {"type": "metrics", "payload": {"type": "stt_latency", "value": latency}},
        })
        if getattr(self, "_last_input_turn", None) is not None:
            msg.metadata["_telemetry_turn"] = self._last_input_turn
        await self.push_frame(msg)

    async def run_stt(self, audio: bytes):
        """Streaming STT processing handled in bidirectional _streaming_worker task."""
        if False:
            yield None

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._stopping = False
        self._stream_start_wall_time = time.time()
        self._streaming_task = self.create_task(self._streaming_worker())

    async def stop(self, frame: Frame):
        self._stopping = True
        await super().stop(frame)
        if self._streaming_task:
            await self.cancel_task(self._streaming_task)
            self._streaming_task = None

    async def cancel(self, frame: CancelFrame):
        self._stopping = True
        await super().cancel(frame)
        if self._streaming_task:
            await self.cancel_task(self._streaming_task)
            self._streaming_task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, AudioRawFrame):
            await self._audio_queue.put(frame)
            if self._audio_passthrough:
                await self.push_frame(frame, direction)
            return
        # Run TurnOriginMixin first so _last_input_turn is bound before _emit_stt_latency pushes.
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._latency_clock.speech_started(time.time())
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            await self._emit_stt_latency(self._latency_clock.speech_stopped(
                decided_at=frame.timestamp or time.time(),
                stop_secs=frame.stop_secs or self._vad_stop_secs,
            ))

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
        
        consecutive_failures = 0
        while not self._stopping:
            try:
                async with self._client.aio.live.connect(model=self.model_name, config=config) as session:
                    logger.info(f"Gemini 3.5 Transcribe Live session connected ({'AI Studio' if self.is_ai_studio else 'Vertex AI'} - {self.model_name})")
                    consecutive_failures = 0
                    meter = getattr(self, "_cascade_meter", None)
                    # Transcribe Live returns no usage_metadata, so the cost is estimated from
                    # the audio actually streamed on this connection (see cascade_pricing).
                    stream_usage = {"audio_seconds": 0.0, "transcript_chars": 0}
                    cost_key = meter.begin(
                        "stt", self.model_name, "gemini" if self.is_ai_studio else "vertex", self.location,
                        complete=True, estimated=True, usage=dict(stream_usage),
                    ) if meter else None
                    await publish_cost(self)

                    def record_stt_usage():
                        if meter:
                            meter.update(cost_key, usage=dict(stream_usage))

                    async def send_audio():
                        last_recorded = 0.0
                        while not self._stopping:
                            audio_frame = await self._audio_queue.get()
                            if audio_frame and audio_frame.audio:
                                await session.send_realtime_input(
                                    audio=types.Blob(
                                        data=audio_frame.audio,
                                        mime_type=f"audio/pcm;rate={audio_frame.sample_rate}"
                                    )
                                )
                                stream_usage["audio_seconds"] += len(audio_frame.audio) / (
                                    2 * audio_frame.sample_rate * max(audio_frame.num_channels, 1))
                                if stream_usage["audio_seconds"] - last_recorded >= 1.0:
                                    last_recorded = stream_usage["audio_seconds"]
                                    record_stt_usage()
                            self._audio_queue.task_done()

                    async def receive_transcripts():
                        # `input_transcription` is one FINAL per utterance (verified live
                        # 2026-09-24), not a growing prefix, and the server never sets
                        # `finished`/`turn_complete`. Each final is therefore emitted as-is,
                        # immediately: debouncing only adds latency and overwrote back-to-back
                        # finals, and prefix de-duplication dropped repeated answers ("Yes.").
                        async def emit_final(text_to_emit: str):
                            final_latency = self._latency_clock.final_latency(time.time())
                            if final_latency is not None:
                                logger.info(f"STT final transcript (speech end -> final): {int(final_latency * 1000)}ms")
                            stream_usage["transcript_chars"] += len(text_to_emit)
                            record_stt_usage()
                            await publish_cost(self)

                            primary_lang = self.languages[0].value if self.languages else "en-US"
                            await self.push_frame(TranscriptionFrame(
                                text=text_to_emit,
                                user_id=self._user_id,
                                timestamp=time_now_iso8601(),
                                language=primary_lang
                            ))
                            await self.stop_processing_metrics()
                            if hasattr(self, "_handle_transcription"):
                                await self._handle_transcription(
                                    text_to_emit,
                                    is_final=True,
                                    language=primary_lang,
                                )

                        while not self._stopping:
                            async for response in session.receive():
                                if meter and getattr(response, "usage_metadata", None):
                                    observe_tokens(meter, cost_key, response.usage_metadata)
                                    await publish_cost(self)
                                server_content = getattr(response, "server_content", None)
                                if not server_content:
                                    continue

                                primary_lang = self.languages[0].value if self.languages else "en-US"
                                has_text = any(
                                    getattr(getattr(server_content, field, None), "text", None)
                                    for field in ("interim_input_transcription", "input_transcription")
                                )
                                if has_text:
                                    await self._emit_stt_latency(self._latency_clock.transcript_arrived(time.time()))

                                # 1. Real-time interim transcript for instantaneous UI streaming
                                interim = getattr(server_content, "interim_input_transcription", None)
                                if interim and interim.text:
                                    interim_text = interim.text.strip()
                                    if interim_text:
                                        await self.push_frame(InterimTranscriptionFrame(
                                            text=interim_text,
                                            user_id=self._user_id,
                                            timestamp=time_now_iso8601(),
                                            language=primary_lang
                                        ))

                                # 2. Final transcript of one utterance
                                input_transcription = getattr(server_content, "input_transcription", None)
                                if input_transcription and input_transcription.text:
                                    transcript_text = input_transcription.text.strip()
                                    if transcript_text:
                                        await emit_final(transcript_text)

                    send_task = asyncio.create_task(send_audio())
                    receive_task = asyncio.create_task(receive_transcripts())
                    try:
                        done, _ = await asyncio.wait(
                            [send_task, receive_task],
                            return_when=asyncio.FIRST_COMPLETED
                        )
                    finally:
                        # asyncio.wait never cancels its tasks, including when this worker
                        # itself is cancelled; without this the send loop stays parked on
                        # the audio queue forever.
                        for task in (send_task, receive_task):
                            task.cancel()
                        await asyncio.gather(send_task, receive_task, return_exceptions=True)
                    for task in done:
                        if not task.cancelled() and task.exception():
                            raise task.exception()

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._stopping:
                    break
                consecutive_failures += 1
                err_str = str(e)
                is_rotation = any(code in err_str for code in ("1008", "1000", "1001", "operation was aborted", "ConnectionClosed"))
                if is_rotation and consecutive_failures == 1:
                    logger.debug(f"Gemini 3.5 Transcribe Live stream rotated ({err_str}); reconnecting")
                elif consecutive_failures >= 5:
                    logger.error(f"Gemini 3.5 Transcribe Live failing repeatedly ({consecutive_failures}x): {e}")
                else:
                    logger.warning(f"Gemini 3.5 Transcribe Live reconnect #{consecutive_failures}: {e}")
                await asyncio.sleep(min(0.1 * (2 ** (consecutive_failures - 1)), 5.0))



class CustomGoogleSTTService(TurnOriginMixin, GoogleSTTService):
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
        meter = getattr(self, "_cascade_meter", None)
        cost_key = meter.begin("stt", self._settings.model, "cloud-speech-v2", self._location, in_flight=True) if meter else None
        drained = False
        await publish_cost(self)
        try:
            async for response in streaming_recognize:
                if meter:
                    seconds = billed_duration(getattr(response, "metadata", None))
                    if seconds is not None:
                        # Each stream has a separate key; repeated request totals replace.
                        meter.update(cost_key, usage={"billed_seconds": seconds}, complete=True)
                        await publish_cost(self)
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
                                    if 0.03 <= elapsed <= 10.0:
                                        stt_latency = elapsed
                                elif getattr(self, "_last_audio_sent_time", None):
                                    elapsed = now - self._last_audio_sent_time
                                    if 0.03 <= elapsed <= 10.0:
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
            else:
                drained = True
        except Exception as e:
            logger.debug(f"CustomGoogleSTTService response note: {e}")
            raise
        finally:
            if meter:
                meter.update(cost_key, in_flight=False, pending_reason=None if drained else "Recognition ended before final billing was confirmed")
                await publish_cost(self)


class CustomVertexGeminiTTSService(TurnOriginMixin, GeminiTTSService):
    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        voice_id: str = "Puck",
        model: str = "gemini-3.8-flash-lite-tts",
        voice_prompt: Optional[str] = None,
        language_code: Optional[str] = None,
        tts_style: Optional[str] = None,
        tts_accent: Optional[str] = None,
        tts_pitch: Optional[str] = None,
        tts_pace: Optional[float] = None,
        tts_pace_label: Optional[str] = None,
        **kwargs,
    ):
        if voice_id and voice_id.lower() == "callirhoe":
            voice_id = "Aoede"
        elif voice_id and "-Chirp3-HD-" in voice_id:
            voice_id = voice_id.split("-Chirp3-HD-")[-1]
        elif voice_id and "-" in voice_id and not voice_id.startswith("Custom"):
            voice_id = voice_id.split("-")[-1]

        self._is_aistudio = model in AI_STUDIO_TTS_MODELS or "aistudio" in (model or "").lower()
        clean_tts_model = (model or "gemini-3.8-flash-lite-tts").replace("-aistudio", "")
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "dummy"

        settings = GeminiTTSService.Settings(
            voice=voice_id,
            model=clean_tts_model,
            prompt=voice_prompt,
            language=language_code or "en-US",
        )
        super().__init__(api_key=api_key, settings=settings, **kwargs)
        if self._is_aistudio:
            self._client = genai.Client(api_key=api_key)
            self._cost_provider = "gemini"
            self._cost_region = "global"
        else:
            tts_location = "global" if "3.8" in clean_tts_model else location
            self._client = genai.Client(vertexai=True, project=project_id, location=tts_location)
            self._cost_provider = "vertex"
            self._cost_region = tts_location
        self._voice_prompt = voice_prompt
        self._language_code = language_code
        self._tts_style = tts_style
        self._tts_accent = tts_accent
        self._tts_pitch = tts_pitch
        self._tts_pace = tts_pace
        self._tts_pace_label = tts_pace_label

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        if isinstance(frame, OutputTransportMessageFrame):
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, TextFrame) and getattr(frame, "response_id", None):
            self._current_response_id = frame.response_id
        await super().process_frame(frame, direction)

    async def start_ttfb_metrics(self):
        if not getattr(self, '_my_ttfb_start', None):
            self._my_ttfb_start = time.monotonic()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if getattr(self, '_my_ttfb_start', None):
            latency = time.monotonic() - self._my_ttfb_start
            self._my_ttfb_start = None
            logger.info(f"TTS Latency: {latency:.3f}s")
            payload = {'type': 'tts_latency', 'value': latency}
            if getattr(self, '_current_response_id', None):
                payload['response_id'] = self._current_response_id
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'metrics',
                    'payload': payload,
                }
            }))

    def _build_speech_metadata_style(self, lang_code: Optional[str]) -> str:
        """Constructs the structured SpeechMetadata style string for Gemini 3.8 TTS.

        Default output:
        'Style: Empathetic. Pace: Natural. Accent: Indian. Pitch: Default.'
        """
        if self._voice_prompt and self._voice_prompt.strip().lower().startswith("style:"):
            # Allow full manual override if user typed a raw "Style: ... Pace: ..." string
            return self._voice_prompt.strip()

        parts = []
        style_val = (self._tts_style or "Empathetic").strip()
        parts.append(f"Style: {style_val}.")

        if self._tts_pace_label:
            pace_val = self._tts_pace_label.strip()
        elif self._tts_pace is not None:
            if self._tts_pace < 0.9:
                pace_val = "Slow"
            elif self._tts_pace > 1.12:
                pace_val = "Brisk"
            else:
                pace_val = "Natural"
        else:
            pace_val = "Natural"
        parts.append(f"Pace: {pace_val}.")

        if self._tts_accent and self._tts_accent.strip().lower() not in ("auto", "auto (from language)", ""):
            accent_val = self._tts_accent.strip()
        elif lang_code and "in" in lang_code.lower():
            accent_val = "Indian"
        elif lang_code and "gb" in lang_code.lower():
            accent_val = "British"
        elif lang_code and "au" in lang_code.lower():
            accent_val = "Australian"
        else:
            accent_val = "Indian"
        parts.append(f"Accent: {accent_val}.")

        pitch_val = (self._tts_pitch or "Default").strip()
        parts.append(f"Pitch: {pitch_val}.")

        if self._voice_prompt and self._voice_prompt.strip():
            parts.append(self._voice_prompt.strip())

        return " ".join(parts)

    async def run_tts(self, text: str, context_id: str):
        # Strip any residual bracketed English tags ([warmly], [thoughtfully]) and repeated punctuation
        clean_text = re.sub(r'\[.*?\]', '', text or "")
        clean_text = re.sub(r'\.{2,}', '.', clean_text).strip()
        # Skip standalone punctuation or empty fragments (e.g. ".") so TTS never hangs or speaks "dot"
        if not clean_text or not any(ch.isalnum() for ch in clean_text):
            logger.debug(f"{self}: Skipping non-spoken fragment [{text!r}]")
            return

        logger.debug(f"{self}: Generating TTS [{clean_text}] with model={self._settings.model} aistudio={self._is_aistudio}")
        meter = getattr(self, "_cascade_meter", None)
        cost_key = meter.begin("tts", self._settings.model, self._cost_provider, self._cost_region) if meter else None
        completed = False
        last_usage_metadata = None
        await publish_cost(self)
        try:
            await self.start_ttfb_metrics()

            # Ensure language_code is a single valid BCP-47 tag (e.g. "hi-IN")
            lang_code = self._language_code
            if lang_code and "," in lang_code:
                langs = [l.strip() for l in lang_code.split(",")]
                hi_lang = next((l for l in langs if "hi" in l.lower()), None)
                lang_code = hi_lang if hi_lang else langs[0]

            if self._is_aistudio:
                style_str = self._build_speech_metadata_style(lang_code)
                speech_config = types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._settings.voice)
                    )
                )
                generate_content_config = types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=speech_config,
                )
                # Pass ONLY clean_text (no "## Transcript:" header and NO system_instruction)
                if hasattr(types, "SpeechMetadata"):
                    contents = [
                        types.Content(
                            role="user",
                            parts=[
                                types.Part(
                                    text=clean_text,
                                    speech_metadata=types.SpeechMetadata(style=style_str),
                                )
                            ],
                        )
                    ]
                else:
                    contents = [
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": clean_text,
                                    "speech_metadata": {"style": style_str},
                                }
                            ],
                        }
                    ]
            else:
                speech_config = types.SpeechConfig(
                    voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._settings.voice)),
                    language_code=lang_code
                )
                generate_content_config = types.GenerateContentConfig(
                    response_modalities=["AUDIO"], 
                    speech_config=speech_config,
                    system_instruction=self._voice_prompt
                )

                contents = f"""Synthesize speech for the performance defined below. The profile, scene,
performance notes, and context are direction only. Do NOT speak them.
Speak ONLY the lines under #### TRANSCRIPT.

# AUDIO PROFILE: {self._settings.voice}
## "Empathetic Voice Assistant"

## SCENE: A warm, natural conversation in colloquial Hindi/English

### PERFORMANCE
Style: {self._tts_style or 'Warm, expressive, natural voice'}.
Pace: {self._tts_pace_label or 'Conversational'}.

#### TRANSCRIPT
{clean_text}
"""

            async for chunk in await self._client.aio.models.generate_content_stream(
                model=self._settings.model, contents=contents, config=generate_content_config,
            ):
                if getattr(chunk, "usage_metadata", None):
                    last_usage_metadata = chunk.usage_metadata
                parts_list = getattr(chunk, "parts", None)
                if not parts_list and chunk.candidates and chunk.candidates[0].content:
                    parts_list = chunk.candidates[0].content.parts
                if not parts_list:
                    continue
                part = parts_list[0]
                if part.inline_data and part.inline_data.data:
                    audio_data = part.inline_data.data
                    await self.stop_ttfb_metrics()
                    CHUNK_SIZE = self.chunk_size
                    for i in range(0, len(audio_data), CHUNK_SIZE):
                        chunk_bytes = audio_data[i : i + CHUNK_SIZE]
                        if not chunk_bytes: break
                        yield TTSAudioRawFrame(chunk_bytes, self.sample_rate or 24000, 1)

            completed = True
            yield TTSStoppedFrame(context_id=context_id)
        except Exception as e:
            logger.exception(f"{self} error generating TTS: {e}")
            yield ErrorFrame(error=f"Gemini TTS generation error: {str(e)}")
        finally:
            if context_id and self.audio_context_available(context_id):
                await self.remove_audio_context(context_id)
            if meter:
                if last_usage_metadata is not None:
                    observe_tokens(meter, cost_key, last_usage_metadata)
                meter.update(cost_key, complete=completed,
                             issue=None if completed else "TTS ended before final usage was confirmed")
                await publish_cost(self)


class CustomGoogleTTSService(TurnOriginMixin, GoogleTTSService):
    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        if isinstance(frame, OutputTransportMessageFrame):
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, TextFrame) and getattr(frame, "response_id", None):
            self._current_response_id = frame.response_id
        await super().process_frame(frame, direction)

    async def _stream_tts(self, streaming_config, text, context_id, prompt=None):
        meter = getattr(self, "_cascade_meter", None)
        voice = getattr(self._settings, "voice", "")
        model = "chirp3-instant-custom-voice" if self._voice_cloning_key else (
            "chirp3-hd" if "-Chirp3-HD-" in voice else voice or "unknown-cloud-voice"
        )
        cost_key = meter.begin("tts", model, "cloud-tts") if meter else None
        completed = False
        await publish_cost(self)
        try:
            async for frame in super()._stream_tts(streaming_config, text, context_id, prompt):
                yield frame
            completed = True
        finally:
            if meter:
                # Count the exact post-filter synthesis text, including whitespace.
                meter.update(cost_key, usage={"characters": len(text)}, complete=completed,
                             issue=None if completed else "Synthesis interrupted; billed characters unconfirmed")
                await publish_cost(self)

    async def start_ttfb_metrics(self):
        if not getattr(self, '_my_ttfb_start', None):
            self._my_ttfb_start = time.monotonic()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if getattr(self, '_my_ttfb_start', None):
            latency = time.monotonic() - self._my_ttfb_start
            self._my_ttfb_start = None
            logger.info(f"TTS Latency: {latency:.3f}s")
            payload = {'type': 'tts_latency', 'value': latency}
            if getattr(self, '_current_response_id', None):
                payload['response_id'] = self._current_response_id
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'metrics',
                    'payload': payload,
                }
            }))


class _MeteredGeminiLLMMixin:
    """Shared metering, response_id stamping, and latency telemetry for Vertex & AI Studio LLMs."""
    _cost_provider: str = "vertex"

    async def _stream_content(self, context):
        meter = getattr(self, "_cascade_meter", None)
        if meter is None:
            return await super()._stream_content(context)
        region = getattr(self, "_location", "global") if self._cost_provider == "vertex" else "global"
        key = meter.begin("llm", self._settings.model, self._cost_provider, region,
                          input_mode=getattr(self, "_cost_input_mode", "unknown"))
        await publish_cost(self)
        try:
            stream = await super()._stream_content(context)
        except BaseException:
            meter.update(key, issue="LLM request failed before final usage")
            await publish_cost(self)
            raise

        async def metered_stream():
            completed = False
            last_usage = None
            try:
                async for chunk in stream:
                    if getattr(chunk, "usage_metadata", None):
                        last_usage = chunk.usage_metadata
                    yield chunk
                completed = True
            finally:
                if last_usage is not None:
                    observe_tokens(meter, key, last_usage)
                meter.update(key, complete=completed,
                             issue=None if completed else "LLM stream interrupted; final usage unconfirmed")
                await publish_cost(self)
        return metered_stream()

    @property
    def response_identity(self):
        if not hasattr(self, "_response_identity"):
            self._response_identity = ResponseIdentity(current_session_id())
        return self._response_identity

    async def _process_context(self, context):
        self.response_identity.begin()
        try:
            await super()._process_context(context)
        finally:
            self.response_identity.finish()

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        identity = self.response_identity.current
        if isinstance(frame, TextFrame):
            frame.response_id = identity
        if isinstance(frame, OutputTransportMessageFrame) and isinstance(frame.message, dict):
            data = frame.message.get("data", {})
            if data.get("type") == "metrics":
                data = {**data, "payload": self.response_identity.stamp(data.get("payload", {}))}
                frame.message = {**frame.message, "data": data}
        await super().push_frame(frame, direction)
        if isinstance(frame, LLMFullResponseEndFrame):
            await super().push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai", "type": "server-message",
                "data": {"type": "metrics", "payload": self.response_identity.stamp({"type": "turn_complete"})},
            }), direction)

    def _maybe_unset_thinking_budget(self, generation_params: dict):
        try:
            model = self._settings.model or ""
            if "thinking_config" in generation_params:
                return
            if any(k in model for k in ["gemini-3.8", "gemini-3.7", "gemini-2.5"]):
                generation_params["thinking_config"] = {"thinking_budget": 0}
            elif any(k in model for k in ["gemini-3.5-flash-lite", "gemini-3.1", "gemini-3-flash"]):
                generation_params["thinking_config"] = {"thinking_level": "minimal"}
        except Exception as e:
            logger.error(f"Failed to unset thinking budget: {e}")

    async def start_ttfb_metrics(self):
        if not getattr(self, '_my_ttfb_start', None):
            self._my_ttfb_start = time.monotonic()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if getattr(self, '_my_ttfb_start', None):
            latency = time.monotonic() - self._my_ttfb_start
            self._my_ttfb_start = None
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
                        "response_details": {"text": completion_tokens},
                        "phase": "final", "service": "llm", "revision": 0,
                        "model": self._settings.model,
                        "cached_content_token_count": getattr(metrics, "cache_read_input_tokens", None),
                        "thoughts_token_count": getattr(metrics, "reasoning_tokens", None),
                    }
                }
            }
        }))


class CustomGoogleVertexLLMService(_MeteredGeminiLLMMixin, TurnOriginMixin, GoogleVertexLLMService):
    _cost_provider = "vertex"


class CustomGoogleAIStudioLLMService(_MeteredGeminiLLMMixin, TurnOriginMixin, GoogleLLMService):
    _cost_provider = "gemini"


class TranscriptionBroadcaster(FrameProcessor):
    def __init__(self, participant: str):
        super().__init__()
        self.participant = participant

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, InterimTranscriptionFrame):
                ui_text = re.sub(r'\[.*?\]', '', frame.text or "").strip()
                if ui_text:
                    await self.push_frame(OutputTransportMessageFrame(message={
                        "label": "rtvi-ai",
                        "type": "server-message",
                        "data": {
                            'type': 'interim_transcription',
                            'participant': self.participant,
                            'text': ui_text
                        }
                    }))
            elif isinstance(frame, (TranscriptionFrame, TextFrame)):
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
                                'response_id': getattr(frame, 'response_id', None),
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
    llm_model: str = "gemini-3.5-flash-lite",
    stt_model: str = "gemini-3.5-transcribe-live-aistudio",
    stt_language: str = "en-US",
    tts_model: str = "gemini-3.8-flash-lite-tts",
    tts_voice_prompt: Optional[str] = None,
    tts_style: Optional[str] = None,
    tts_accent: Optional[str] = None,
    tts_pitch: Optional[str] = None,
    tts_pace_label: Optional[str] = None,
    system_instruction: Optional[str] = None,
    skip_stt: bool = False,
    vad: bool = True,
    vad_mode: Optional[str] = None,
    custom_voice_key: Optional[str] = None,
    persona_id: Optional[str] = None,
):
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
    location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"

    # Automatically apply Persona Voice Design defaults if not explicitly overridden
    persona_defaults = PERSONA_VOICE_DESIGN_DEFAULTS.get(persona_id or "", {})
    if not tts_style:
        tts_style = persona_defaults.get("style", "Empathetic")
    if not tts_pace_label:
        tts_pace_label = persona_defaults.get("pace", "Natural")
    if not tts_accent:
        tts_accent = persona_defaults.get("accent", "Indian")
    if not tts_pitch:
        tts_pitch = persona_defaults.get("pitch", "Default")
    if not tts_voice_prompt and persona_defaults.get("prompt"):
        tts_voice_prompt = persona_defaults["prompt"]

    if skip_stt:
        vad = True
    elif vad_mode:
        vad = vad_mode.strip().lower() in ("both", "silero")

    # With VAD disabled the STT service's own endpointing decides turn
    # boundaries. That is a slower but sometimes steadier signal on noisy input,
    # so it is offered as a choice rather than silently forced on.
    logger.info(f"Client-side VAD: {'enabled' if vad else 'disabled (STT endpointing only)'} (vad_mode={vad_mode or 'default'}, skip_stt={skip_stt})")
    vad_analyzer = SileroVADAnalyzer(
        params=VADParams(
            confidence=0.55 if skip_stt else 0.7,
            start_secs=0.15 if skip_stt else 0.2,
            stop_secs=0.7 if skip_stt else 0.4,
            min_volume=0.45 if skip_stt else 0.6,
        )
    ) if vad else None
    vad_processor = VADProcessor(vad_analyzer=vad_analyzer) if vad_analyzer else None

    transport = FastAPIWebsocketTransport(
        websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            serializer=CustomProtobufSerializer(),
        ),
    )

    clean_stt_model = validate_stt_model(stt_model)
    clean_llm_model = validate_llm_model(llm_model)
    clean_tts_model = validate_tts_model(tts_model)

    stt = None
    if not skip_stt:
        stt_languages = [Language(lang.strip()) for lang in stt_language.split(',')] if stt_language else [Language("en-US"), Language("hi-IN")]
        if clean_stt_model.startswith("gemini-3.5-transcribe"):
            is_ai_studio = False
            if "aistudio" in clean_stt_model:
                is_ai_studio = True
            elif not clean_stt_model.endswith("-preview") and os.getenv("GEMINI_API_KEY"):
                is_ai_studio = True

            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if is_ai_studio and not gemini_api_key:
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

    persona_architecture = None
    if persona_id:
        from persona_registry import get_persona_architecture
        persona_architecture = get_persona_architecture(persona_id)
        logger.info(
            f"[Cascade] Persona architecture: {persona_architecture.pattern.value} "
            f"(persona_id={persona_id})"
        )
        arch_instruction = persona_architecture.compose_system_prompt(system_instruction, engine="cascade")
        if arch_instruction:
            system_instruction = arch_instruction

    neutrality_instruction = "\n\nRULE: Never ask for the user's name or who you are speaking with."
    if not system_instruction:
        neutrality_instruction += "\nKeep all address, pronouns, call-outs, and verb forms for the user strictly gender-neutral so the conversation fits naturally whether the user is male or female."
    final_system_instruction = (system_instruction or SYSTEM_PROMPT) + neutrality_instruction
    if tts_model.startswith("gemini"):
        final_system_instruction += "\n\n" + GEMINI_LLM_TTS_PROMPT

    if skip_stt:
        final_system_instruction += "\n\nIMPORTANT: The user's input is raw audio. Listen to it and respond naturally. Strictly answer ONLY the current current user query. Do not bring up previous topics or simulate future turns."

    is_aistudio_llm = "aistudio" in clean_llm_model
    # Always pass the exact canonical model string ("gemini-3.8-flash", "gemini-3.5-flash-lite") to the SDK
    actual_llm_model = clean_llm_model.replace("-aistudio", "")
    llm_location = "global" if any(k in actual_llm_model for k in ["gemini-3", "3.8", "3.7", "3.5"]) else location
    
    thinking_config = build_cascade_thinking_config(actual_llm_model)

    cascade_tools = None
    if persona_architecture:
        cascade_tools = persona_architecture.get_tool_schemas(engine="cascade")
        if not cascade_tools:
            cascade_tools = None

    tools_list = [{
        "function_declarations": [schema.to_default_dict() for schema in cascade_tools],
    }] if cascade_tools else None

    if is_aistudio_llm:
        gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
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
        aistudio_kwargs = {
            "api_key": gemini_api_key,
            "settings": GoogleLLMService.Settings(
                model=actual_llm_model,
                system_instruction=final_system_instruction,
                max_tokens=1024 if thinking_config else 4096,
                thinking=thinking_config,
            ),
        }
        if tools_list:
            aistudio_kwargs["tools"] = tools_list
        llm = CustomGoogleAIStudioLLMService(**aistudio_kwargs)
    else:
        llm_kwargs = {
            "project_id": project_id,
            "location": llm_location,
            "settings": GoogleVertexLLMService.Settings(
                model=actual_llm_model,
                system_instruction=final_system_instruction,
                max_tokens=1024 if thinking_config else 4096,
                thinking=thinking_config,
            ),
        }
        if tools_list:
            llm_kwargs["tools"] = tools_list
        llm = CustomGoogleVertexLLMService(**llm_kwargs)

    if persona_architecture:
        async def broadcast_persona_event(payload: dict):
            """Push a persona telemetry event to the client over RTVI."""
            await llm.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": payload,
            }))

        persona_architecture.register_handlers(
            llm, broadcast=broadcast_persona_event, engine="cascade"
        )

    is_clone = voice_profiles.is_custom_clone_voice(tts_voice)
    if is_clone and clean_tts_model != "google-tts":
        raise ValueError("Cloned voices require Google TTS (Chirp 3 HD). Select it before starting Cascade.")
    cloned_key_content = voice_profiles.resolve_clone_key(tts_voice, custom_voice_key)
    if is_clone:
        tts_language = "hi-IN" if (stt_language and any(l in stt_language.lower() for l in ["hi", "hindi"])) else "en-US"
        tts = CustomGoogleTTSService(
            voice_cloning_key=cloned_key_content,
            params=GoogleTTSService.InputParams(
                language=Language(tts_language),
                speaking_rate=tts_pace,
            ),
            text_filters=[MarkdownTextFilter()],
        )
    elif clean_tts_model.startswith("gemini"):
        tts_location = "global" if "gemini-3" in clean_tts_model else location
        langs = [lang.strip() for lang in (stt_language or "en-US").split(",") if lang.strip()]
        tts_lang = next((lang for lang in langs if lang.lower().startswith("hi")), None) or (langs or ["en-US"])[0]

        # Sanitize voice name for Gemini TTS
        effective_voice = tts_voice
        if "-Chirp3-HD-" in effective_voice:
            effective_voice = effective_voice.split("-Chirp3-HD-")[-1]
        elif "-" in effective_voice and not effective_voice.startswith("Custom"):
            effective_voice = effective_voice.split("-")[-1]

        if effective_voice.lower() == "callirhoe":
            effective_voice = "Aoede"

        tts = CustomVertexGeminiTTSService(
            project_id=project_id,
            location=tts_location,
            voice_id=effective_voice,
            model=clean_tts_model, # Use the sanitized model
            sample_rate=24000, 
            voice_prompt=tts_voice_prompt,
            language_code=tts_lang,
            tts_style=tts_style,
            tts_accent=tts_accent,
            tts_pitch=tts_pitch,
            tts_pace=tts_pace,
            tts_pace_label=tts_pace_label,
            text_filters=[MarkdownTextFilter()]
        )
    else:
        effective_voice = tts_voice
        langs = [lang.strip() for lang in (stt_language or "en-US").split(",") if lang.strip()]
        tts_language = next((lang for lang in langs if lang.lower().startswith("hi")), None) or (langs or ["en-US"])[0]
        if "-" not in effective_voice:
            effective_voice = f"{tts_language}-Chirp3-HD-{effective_voice}"
        else:
            tts_language = "-".join(effective_voice.split("-")[:2])

        tts = CustomGoogleTTSService(
            voice_id=effective_voice,
            params=GoogleTTSService.InputParams(
                language=Language(tts_language),
                speaking_rate=tts_pace
            ),
            text_filters=[MarkdownTextFilter()],
        )

    # Skip STT bypasses the LLM's transcription input, but AudioAccumulator
    # still calls Cloud Speech for the displayed transcript. It is billable.
    turn_tracker = TurnTracker(current_session_id(), "tts-llm-stt", vad_stop_padding_ms=400 if vad else None)
    for service in (llm, tts, stt):
        if service is not None:
            service._turn_tracker = turn_tracker
    cost_meter = CascadeCostLedger(current_session_id())
    llm._cascade_meter = cost_meter
    llm._cost_input_mode = "audio" if skip_stt else "text"
    tts._cascade_meter = cost_meter
    if stt is not None:
        stt._cascade_meter = cost_meter

    is_hindi = bool(stt_language and any(l in stt_language.lower() for l in ["hi", "hindi"]))
    initial_greeting = "नमस्ते!" if is_hindi else "Hello!"

    if skip_stt:
        from processors.audio_accumulator import AudioAccumulator
        if vad_processor is None:
            # AudioAccumulator requires VADUserStartedSpeakingFrame / VADUserStoppedSpeakingFrame
            # to segment raw user audio when streaming STT is bypassed.
            vad_analyzer = SileroVADAnalyzer(
                params=VADParams(confidence=0.7, start_secs=0.2, stop_secs=0.4, min_volume=0.6)
            )
            vad_processor = VADProcessor(vad_analyzer=vad_analyzer)
        context = LLMContext(messages=[
            {"role": "user", "content": initial_greeting}
        ])
        stt_languages = [lang.strip() for lang in stt_language.split(',')] if stt_language else ["en-US"]
        accumulator = AudioAccumulator(
            context,
            project_id=project_id,
            stt_languages=stt_languages,
            cost_meter=cost_meter,
        )
        context_aggregator = LLMContextAggregatorPair(context)
        start_trigger = StartTriggerProcessor(context, context_aggregator, skip_stt=True)

        pipeline_elements = [
            transport.input(),
            start_trigger,
            *([vad_processor] if vad_processor else []),
            TurnBoundaryProcessor(turn_tracker),
            accumulator,
            llm,
            TranscriptionBroadcaster(participant="Bot"),
            tts,
            context_aggregator.assistant(),
            ServerAudioTimingProcessor(),
            transport.output()
        ]
    else:
        context = LLMContext(messages=[
            {"role": "user", "content": initial_greeting}
        ])
        user_params = LLMUserAggregatorParams(
            # VADProcessor above owns audio analysis and broadcasts VAD frames.
            # Feeding the same analyzer here again would process each PCM twice.
            vad_analyzer=None,
        )
        context_aggregator = LLMContextAggregatorPair(context, user_params=user_params)
        start_trigger = StartTriggerProcessor(context, context_aggregator, skip_stt=False)

        pipeline_elements = [
            transport.input(),
            start_trigger,
            *([vad_processor] if vad_processor else []),
            TurnBoundaryProcessor(turn_tracker),
            stt,
            TranscriptionBroadcaster(participant="User"),
            context_aggregator.user(),
            llm,
            TranscriptionBroadcaster(participant="Bot"),
            tts,
            context_aggregator.assistant(),
            ServerAudioTimingProcessor(),
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
    try:
        await runner.run(task)
    finally:
        turn_tracker.close()
