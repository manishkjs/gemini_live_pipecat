import os
import struct
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
from diagnostic_buffer import append_diagnostic_log, current_session_id
from turn_telemetry import TurnTracker
from processors.turn_telemetry import TurnBoundaryProcessor, TurnOriginMixin, ServerAudioTimingProcessor
from response_identity import ResponseIdentity
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
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, GeminiVADParams, InputParams, GeminiModalities
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.services.google.tts import GoogleTTSService
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
import tts_script
import voice_profiles


from collections import deque
import numpy as np

import base64
from pipecat_whisker import WhiskerObserver
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.frames.frames import (
    EndTaskFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    CancelFrame,
    LLMMessagesAppendFrame,
    TextFrame,
    TTSStoppedFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
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


def estimate_tokens(text: str) -> int:
    """Approximate the token cost of a string.

    Everything this system reports about prompt size is in tokens, because
    tokens are what gets billed and what fills the context window. Characters
    are an implementation detail of the encoding and mean nothing to the model.

    The estimate is script-aware on purpose. Latin text runs about 3.8
    characters per token, but Devanagari runs closer to 1.8 — a single divisor
    would understate Pragya's Hindi cards by roughly half and make the injected
    payloads look free when they are not.
    """
    if not text:
        return 0
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    return round(non_ascii / 1.8 + (len(text) - non_ascii) / 3.8)


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


# Live closes the socket with 1007 (invalid payload) or 1008 (policy) when it
# refuses what we sent at setup; those are the only closes custom media can cause.
_MEDIA_REJECTION_CLOSE_CODES = (1007, 1008)
_OUTAGE_HINTS = (
    "quota", "exhausted", "rate limit", "429", "unavailable", "deadline",
    "timeout", "timed out", "overloaded", "try again",
)
_MEDIA_HINTS = {
    "avatar": ("avatar", "image"),
    "voice": ("voice", "wav", "audio", "replicated", "speech"),
}


def classify_custom_media_rejection(error: BaseException, *, avatar: bool, voice: bool) -> set:
    """Name the custom media ("avatar", "voice") a Live connection error blames.

    Only a 1007/1008 close can blame media, and never one that reads like an
    outage (quota, overload, timeout): those must surface, not be hidden by a
    silent swap to prebuilt media. A rejection that names a part blames just
    that part, if the session has it; one that names nothing blames every
    custom part the session sent.
    """
    configured = {part for part, sent in (("avatar", avatar), ("voice", voice)) if sent}
    text = str(error)
    if not configured:
        return set()
    if getattr(error, "code", None) not in _MEDIA_REJECTION_CLOSE_CODES and not re.match(r"\s*100[78]\b", text):
        return set()
    lowered = text.lower()
    if any(hint in lowered for hint in _OUTAGE_HINTS):
        return set()
    named = {part for part, hints in _MEDIA_HINTS.items() if any(hint in lowered for hint in hints)}
    return named & configured if named else configured


def _rejection_detail(error: BaseException) -> str:
    """The server's own words: "Failed to parse WAV audio", not "1007 None. Failed…"."""
    details = getattr(error, "details", None)
    return details if isinstance(details, str) and details.strip() else str(error)


def extract_complete_mp4_segments(buf: bytearray) -> list[tuple[bytes, bool]]:
    """Reassemble arbitrary transport slices into complete ISO-BMFF segments.

    Vertex AI Gemini Live Avatar slices its continuous fMP4 byte stream into
    16 KiB chunks that split `moof` and `mdat` boxes mid-payload. Emitting
    only complete `ftyp + moov` (is_init=True) and `moof + mdat` (is_init=False)
    segments guarantees Chrome's MSE SourceBuffer never ingests a truncated box.
    """
    pos = 0
    n = len(buf)
    boxes: list[tuple[bytes, int, int]] = []
    while pos + 8 <= n:
        sz, btype = struct.unpack(">I4s", buf[pos : pos + 8])
        if sz == 1:
            if pos + 16 > n:
                break
            sz = struct.unpack(">Q", buf[pos + 8 : pos + 16])[0]
        elif sz < 8:
            # Malformed or non-box stream: flush buffer as-is to avoid stalling
            raw = bytes(buf)
            buf.clear()
            return [(raw, b"ftyp" in raw[:32] or b"moov" in raw[:64])]
        if pos + sz > n:
            break
        boxes.append((btype, pos, pos + sz))
        pos += sz

    if not boxes:
        return []

    emitted: list[tuple[bytes, bool]] = []
    start_idx = 0

    if boxes[0][0] == b"ftyp":
        moov_idx = next((i for i, b in enumerate(boxes) if b[0] == b"moov"), None)
        if moov_idx is None:
            return []
        init_end = boxes[moov_idx][2]
        emitted.append((bytes(buf[:init_end]), True))
        start_idx = moov_idx + 1
        last_mdat_end = max(
            (b[2] for b in boxes[start_idx:] if b[0] == b"mdat"),
            default=0,
        )
        if last_mdat_end > init_end:
            emitted.append((bytes(buf[init_end:last_mdat_end]), False))
            del buf[:last_mdat_end]
        else:
            del buf[:init_end]
        return emitted

    last_mdat_end = max((b[2] for b in boxes if b[0] == b"mdat"), default=0)
    if last_mdat_end > 0:
        emitted.append((bytes(buf[:last_mdat_end]), False))
        del buf[:last_mdat_end]
    return emitted


class GeminiSessionLoggerMixin(TurnOriginMixin):
    """Mixin to add session ID logging, token usage tracking, and repeat-on-filler."""

    _live_telemetry = True

    @property
    def response_identity(self):
        if not hasattr(self, "_response_identity"):
            self._response_identity = ResponseIdentity(current_session_id())
        return self._response_identity

    async def broadcast_interruption(self, *args, **kwargs):
        self._bot_is_responding = False
        origin = getattr(self, "_live_output_turn", None)
        if origin is not None:
            origin.finish("interrupted")
        if getattr(self, "_avatar_enabled", False):
            try:
                await self.push_frame(OutputTransportMessageUrgentFrame(message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {"type": "avatar_interrupted"}
                }))
            except Exception:
                pass
        try:
            await super().broadcast_interruption(*args, **kwargs)
        finally:
            self._live_output_turn = None

    async def _handle_msg_model_turn(self, message):
        if getattr(self, "_avatar_enabled", False):
            sc = getattr(message, "server_content", None)
            mt = getattr(sc, "model_turn", None) if sc else None
            parts = getattr(mt, "parts", None) or []
            has_non_video = False
            if not hasattr(self, "_avatar_mp4_buffer"):
                self._avatar_mp4_buffer = bytearray()
            for part in parts:
                inl = getattr(part, "inline_data", None)
                mime = getattr(inl, "mime_type", "") if inl else ""
                if inl and mime.startswith("video/mp4") and getattr(inl, "data", None):
                    self._avatar_mp4_buffer.extend(inl.data)
                    for seg_bytes, is_init in extract_complete_mp4_segments(self._avatar_mp4_buffer):
                        b64_str = base64.b64encode(seg_bytes).decode("ascii")
                        if is_init:
                            self._avatar_init_segment = b64_str
                        seq = getattr(self, "_avatar_seq", 0) + 1
                        self._avatar_seq = seq
                        await self.push_frame(OutputTransportMessageUrgentFrame(message={
                            "label": "rtvi-ai",
                            "type": "server-message",
                            "data": {
                                "type": "avatar_video",
                                "data": b64_str,
                                "is_init": is_init,
                                "seq": seq,
                            }
                        }))
                    # Clear video/mp4 inline_data so stock Pipecat doesn't log 'Unrecognized server_content format video/mp4'
                    part.inline_data = None
                elif getattr(part, "text", None) or (inl and mime.startswith("audio/pcm")):
                    has_non_video = True
            if not has_non_video:
                return

        self._bot_is_responding = True
        if getattr(self, "_live_output_turn", None) is None:
            self._live_output_turn = getattr(self, "_last_input_turn", None)
        self.response_identity.begin()
        await super()._handle_msg_model_turn(message)

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frame, OutputTransportMessageFrame) and isinstance(frame.message, dict):
            data = frame.message.get("data", {})
            if data.get("type") == "transcription" and data.get("participant", "").lower() != "user":
                data = {**data, "response_id": self.response_identity.begin()}
            elif data.get("type") == "metrics":
                payload = data.get("payload", {})
                response_id = self.response_identity.current
                if payload.get("type") == "usage":
                    response_id = self.response_identity.completed or response_id
                data = {**data, "payload": self.response_identity.stamp(payload, response_id=response_id)}
            frame.message = {**frame.message, "data": data}
        await super().push_frame(frame, direction)

    # ── Repeat-on-filler: intercept at API level ──────────────────────

    async def start_ttfb_metrics(self):
        self._my_ttfb_start = time.monotonic()
        await super().start_ttfb_metrics()
        
    async def stop_ttfb_metrics(self):
        await super().stop_ttfb_metrics()
        if hasattr(self, '_my_ttfb_start') and self._my_ttfb_start:
            self._current_turn_ttft = time.monotonic() - self._my_ttfb_start
            logger.info(f"Custom TTFT calculation: {self._current_turn_ttft}s")
            ttfb_ms = self._current_turn_ttft * 1000.0
            append_diagnostic_log("⚡ Gemini Live TTFB", f"Bot audio turnaround inside {round(ttfb_ms, 1)} ms", ttfb_ms=ttfb_ms)
            
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
            was_responding = bool(
                getattr(self, '_bot_is_responding', False)
                or getattr(self, '_bot_turn_text_buffer', '').strip()
                or getattr(self, '_my_ttfb_start', None)
            )
            self._bot_is_responding = False
            if was_responding:
                if not hasattr(self, '_repeat_on_filler_pending'):
                    self._repeat_on_filler_pending = False
                self._repeat_on_filler_pending = True
                logger.info("[RepeatOnFiller] Interruption detected. Watching for filler.")

                if getattr(self, '_bot_turn_text_buffer', '').strip():
                    interrupted_text = self._bot_turn_text_buffer.strip()
                    append_diagnostic_log("🤖 Bot Response (Interrupted)", f'"{interrupted_text}..."')
                    if not hasattr(self, '_dialogue_history'):
                        self._dialogue_history = []
                    self._dialogue_history.append({
                        "role": "Assistant",
                        "text": f"{interrupted_text} [interrupted]",
                        "timestamp": time.time()
                    })
                    logger.info(f"🤖 [Transcript Assistant (Interrupted Turn {len(self._dialogue_history)})]: {interrupted_text}")
                    self._bot_turn_text_buffer = ""

                elapsed_ms = None
                if hasattr(self, '_my_ttfb_start') and self._my_ttfb_start:
                    elapsed_ms = round((time.monotonic() - self._my_ttfb_start) * 1000.0, 1)
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
            if not hasattr(self, '_dialogue_history'):
                self._dialogue_history = []
            if not self._dialogue_history or self._dialogue_history[-1].get("text") != clean_sentence or self._dialogue_history[-1].get("role") != "User":
                self._dialogue_history.append({
                    "role": "User",
                    "text": clean_sentence,
                    "timestamp": time.time()
                })
                logger.info(f"💬 [Transcript User (Turn {len(self._dialogue_history)})]: {clean_sentence}")
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    'type': 'transcription',
                    'participant': 'User',
                    'text': clean_sentence
                }
            }))

            # Optional transcript telemetry. Pragya inherits the no-op hook;
            # Gemini's switch_phase tool owns her phase and collected fields.
            architecture = getattr(self, "persona_architecture", None)
            if architecture is not None:
                try:
                    await architecture.on_user_transcript(
                        clean_sentence, getattr(self, "persona_broadcast", None)
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(f"[Persona] on_user_transcript failed: {exc}")

    async def _handle_msg_input_transcription(self, message):
        """Override to detect ≤2-word fillers after an interruption and auto-repeat."""
        if getattr(getattr(self, "persona_architecture", None), "model_controls_conversation", False):
            # Short speech can be consent or a real answer ("आप बताइए").
            # Let Gemini interpret it, without a regex/word-count repeat rule.
            self._repeat_on_filler_pending = False
            self._post_interruption_buffer = ""
            return await super()._handle_msg_input_transcription(message)
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
                from processors.repeat_on_interruption import is_conversational_filler
                filler_max_words = getattr(self, '_filler_max_words', 2)
                clean = buffer.rstrip('।.!?\n').strip()
                word_count = len(clean.split()) if clean else 0

                if is_conversational_filler(clean, filler_max_words):
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
        if getattr(self, "_live_output_turn", None) is None:
            self._live_output_turn = getattr(self, "_last_input_turn", None)
        self.response_identity.begin()
        await super()._handle_msg_output_transcription(message)
        if message.server_content.output_transcription and message.server_content.output_transcription.text:
            self._bot_is_responding = True
            text = message.server_content.output_transcription.text
            
            # Accumulate text for the complete bot turn
            if not hasattr(self, '_bot_turn_text_buffer'):
                self._bot_turn_text_buffer = ""
            self._bot_turn_text_buffer += text
            
            # If text chunk arrived before audio stop_ttfb_metrics, calculate TTFT immediately
            if getattr(self, '_current_turn_ttft', None) is None and getattr(self, '_my_ttfb_start', None) is not None:
                self._current_turn_ttft = time.monotonic() - self._my_ttfb_start
                ttfb_ms = self._current_turn_ttft * 1000.0
                append_diagnostic_log("⚡ Gemini Live TTFB", f"Bot text turnaround inside {round(ttfb_ms, 1)} ms", ttfb_ms=ttfb_ms)
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
        self._bot_is_responding = False
        self.response_identity.begin()
        await super()._handle_msg_turn_complete(message)
        if getattr(self, '_bot_turn_text_buffer', '').strip():
            full_bot_text = self._bot_turn_text_buffer.strip()
            append_diagnostic_log("🤖 Bot Response", f'"{full_bot_text}"')
            GLOBAL_LANGSMITH_TRACER.record_bot_turn(
                full_bot_text,
                ttfb_ms=getattr(self, '_current_turn_ttft', 0.0) * 1000.0 if getattr(self, '_current_turn_ttft', None) else None,
                # Usage arrives after turn_complete; never attach the previous response's usage.
                token_usage=None
            )
            if not hasattr(self, '_dialogue_history'):
                self._dialogue_history = []
            self._dialogue_history.append({
                "role": "Assistant",
                "text": full_bot_text,
                "timestamp": time.time()
            })
            logger.info(f"🤖 [Transcript Assistant (Turn {len(self._dialogue_history)})]: {full_bot_text}")
            self._bot_turn_text_buffer = ""

        # Metric Streaming: Turn Complete
        await self.push_frame(OutputTransportMessageFrame(message={
            "label": "rtvi-ai",
            "type": "server-message",
            "data": {
                'type': 'metrics',
                'payload': {'type': 'turn_complete'}
            }
        }))
        self.response_identity.finish()
        self._live_output_turn = None
        pending = getattr(self, "_pending_directives", None)
        if pending:
            while pending:
                deferred_text, deferred_tag = pending.pop(0)
                try:
                    await self.inject_directive(
                        deferred_text, tag=deferred_tag, speak_now=False, at_tool_boundary=True
                    )
                except Exception as exc:
                    logger.warning(f"[{deferred_tag}] Deferred directive flush failed: {exc}")
        architecture = getattr(self, "persona_architecture", None)
        flush = getattr(architecture, "flush_pending_card", None)
        if flush is not None:
            try:
                await flush()
            except Exception as exc:
                logger.warning(f"[Persona] Deferred card failed: {exc}")
        st = getattr(self, "start_trigger", None)
        if st is not None:
            st.open_gate("bot turn complete")

    async def inject_directive(
        self, text: str, tag: str = "Directive", speak_now: bool = True,
        at_tool_boundary: bool = False,
    ) -> bool:
        """Send a directive using the selected Live model's text protocol.

        A successful SDK write is reported as sent, not as proof of application
        to a particular response. Quiet cards wait while generation is active:
        client content can interrupt even with turn_complete=False. A blocking
        tool boundary is different: the model is waiting for its function result,
        so its requested card must be sent before that result. Gemini 3 uses
        realtime text for mid-call updates, as in the pinned provider.
        """
        self._last_directive_status = "failed"
        if self._disconnecting or not self._session:
            logger.warning(f"[{tag}] Not delivered — session is not live.")
            return False
        if not speak_now and not at_tool_boundary and getattr(self, "_bot_is_responding", False):
            self._last_directive_status = "pending"
            if not hasattr(self, "_pending_directives"):
                self._pending_directives = []
            self._pending_directives.append((text, tag))
            return False
        try:
            if speak_now:
                await self._create_single_response([{"role": "user", "content": text}])
            elif getattr(self, "_is_gemini_3", False):
                await self._session.send_realtime_input(text=text)
            else:
                await self._session.send_client_content(
                    turns=[Content(role="user", parts=[Part(text=text)])],
                    turn_complete=False,
                )
            self._last_directive_status = "sent"
            mode = "respond now" if speak_now else "briefing"
            logger.info(f"[{tag}] Sent (~{estimate_tokens(text)} estimated tokens, {mode}).")
            return True
        except Exception as e:
            logger.error(f"[{tag}] Injection failed: {e}")
            return False

    async def _send_repeat_instruction(self, filler_text: str):
        """Send a user-role prompt telling the model to repeat itself."""
        await self.inject_directive(
            (
                f"The user just said '{filler_text}' which is a short "
                f"filler/acknowledgment while you were speaking. They did NOT "
                f"ask a new question. Please REPEAT your previous response "
                f"from the beginning — resume exactly what you were saying "
                f"before the interruption."
            ),
            tag="RepeatOnFiller",
        )

    # ── Session ID & token usage logging ──────────────────────────────

    async def _handle_session_ready(self, session):
        self._avatar_mp4_buffer = bytearray()
        await super()._handle_session_ready(session)
        session_id = getattr(session, 'session_id', None) or getattr(session, 'id', None)
        if session_id:
            logger.info(f"Session ID Established: {session_id}")
        for kind in ("avatar", "voice"):
            notice = getattr(self, f"_{kind}_fallback_notice", None)
            if not notice:
                continue
            setattr(self, f"_{kind}_fallback_notice", None)
            await self.push_frame(OutputTransportMessageFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {"type": f"{kind}_fallback", **notice},
            }))

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
        def clean_modality(mod):
            s = str(mod).lower()
            if "audio" in s: return "audio"
            if "text" in s: return "text"
            if "image" in s: return "image"
            if "video" in s: return "video"
            return s

        prompt_details = {}
        if hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
            for d in usage.prompt_tokens_details:
                prompt_details[clean_modality(d.modality)] = d.token_count

        response_details = {}
        if hasattr(usage, 'response_tokens_details') and usage.response_tokens_details:
            for d in usage.response_tokens_details:
                response_details[clean_modality(d.modality)] = d.token_count

        prompt_tokens = int(getattr(usage, 'prompt_token_count', 0) or 0)
        response_tokens = int(getattr(usage, 'response_token_count', 0) or 0)
        total_tokens = int(getattr(usage, 'total_token_count', 0) or 0)

        usage_dict = {
            "prompt_token_count": prompt_tokens,
            "response_token_count": response_tokens,
            "total_token_count": total_tokens,
            "prompt_details": prompt_details,
            "response_details": response_details,
            "cached_content_token_count": getattr(usage, "cached_content_token_count", None),
            "thoughts_token_count": getattr(usage, "thoughts_token_count", None),
            "tool_use_prompt_token_count": getattr(usage, "tool_use_prompt_token_count", None),
            "phase": "final",
            "service": "live",
            "revision": 0,
        }
        self._last_turn_usage = usage_dict
        
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

        # Check for context compression trigger
        if getattr(self, '_context_compression_enabled', False):
            raw_threshold = getattr(self, '_context_compression_trigger_tokens', 5000) or 5000
            threshold = max(5000, raw_threshold)
            current_tot = total_tokens
            current_prompt = prompt_tokens
            last_prompt = int(getattr(self, '_last_prompt_tokens', 0) or 0)
            # Exclude streamed output video tokens (e.g. ~16.5k/turn in Live Avatar mode) from context window threshold check
            video_out_tokens = int(response_details.get("video", 0) or 0)
            effective_context_tot = max(current_prompt, current_tot - video_out_tokens)

            # Detect compression:
            # 1. Effective context tokens reached or exceeded the configured threshold
            # 2. OR prompt tokens dropped significantly (>150 tokens) while turn count > 1 (signature of FIFO eviction compaction)
            compression_detected = False
            if effective_context_tot >= threshold and not getattr(self, '_context_compression_triggered', False):
                compression_detected = True
            elif current_prompt > 0 and last_prompt > 1000 and current_prompt < (last_prompt - 150):
                compression_detected = True
                logger.info(f"🗜️ [Context Compression] Compaction detected! Prompt tokens contracted from {last_prompt} to {current_prompt}")

            if compression_detected:
                self._context_compression_triggered = True
                logger.info(f"🗜️ [Context Compression] Triggered! Context token count {effective_context_tot} (threshold: {threshold}, prompt: {current_prompt})")
                append_diagnostic_log(
                    "🗜️ Context Compression",
                    f"Triggered at {effective_context_tot} tokens (threshold: {threshold}, prompt: {current_prompt}) · Sliding window active"
                )
                await self.push_frame(OutputTransportMessageFrame(message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        "type": "context_compression",
                        "payload": {
                            "status": "triggered",
                            "tokens": effective_context_tot,
                            "threshold": threshold,
                            "message": f"Context window compressed at {effective_context_tot} tokens",
                            "timestamp": time.time(),
                        }
                    }
                }))

                # FactStore: Immediately inject verbatim dialogue transcription logs back into model context
                await self._inject_transcription_logs()

            if current_prompt > 0:
                self._last_prompt_tokens = current_prompt

    async def _inject_transcription_logs(self):
        """Inject verbatim dialogue transcription logs into Gemini Live context on compression."""
        if not getattr(self, '_session', None) or self._disconnecting:
            logger.warning("🗜️ [FactStore Injection] Cannot inject transcript logs: session not available or disconnecting.")
            return

        history = getattr(self, '_dialogue_history', [])
        if not history:
            logger.info("🗜️ [FactStore Injection] No dialogue history in FactStore to inject.")
            return

        # Cap injection to the last 5 turns to keep token overhead minimal
        capped_history = history[-5:] if len(history) > 5 else history

        # Format verbatim dialogue transcription logs for model injection (last 5 turns)
        injected_lines = [f"{turn['role']}: {turn['text']}" for turn in capped_history]
        injected_transcript = "\n".join(injected_lines)

        # Full dialogue history across the entire session for backend logs
        total_lines = [f"[{i+1}] {turn['role']}: {turn['text']}" for i, turn in enumerate(history)]
        total_transcript = "\n".join(total_lines)

        turn_notice = f"last {len(capped_history)}" if len(history) > 5 else "all"
        prompt_card = (
            f"[CONVERSATION_TRANSCRIPT_LOG]\n"
            f"The following is the verbatim transcript log of the {turn_notice} dialogue turns in this session:\n"
            f"{injected_transcript}\n\n"
            f"CRITICAL INSTRUCTIONS:\n"
            f"• Seamlessly continue the conversation with the user from the latest turn.\n"
            f"• Retain full awareness of all customer details, numbers, preferences, and agreements stated in this transcript.\n"
            f"• DO NOT repeat greetings, do NOT re-introduce yourself, and do NOT verbally acknowledge this transcript update."
        )

        injected_tokens = estimate_tokens(injected_transcript)

        logger.info(
            f"🗜️ [FactStore Injection] Compression compaction triggered! Session turns: {len(history)}, Injecting: last {len(capped_history)} turns (~{injected_tokens} tok).\n"
            f"==================== TOTAL SESSION TRANSCRIPTION HISTORY ({len(history)} turns) ====================\n"
            f"{total_transcript}\n"
            f"============================================================================================\n"
            f"==================== INJECTED TRANSCRIPT PAYLOAD (Last {len(capped_history)} turns) ====================\n"
            f"{injected_transcript}\n"
            f"============================================================================================"
        )

        try:
            content = Content(
                role="user",
                parts=[Part(text=prompt_card)]
            )
            await self._session.send_client_content(
                turns=[content],
                turn_complete=False
            )
            logger.info(
                f"🗜️ [FactStore Injection] Successfully injected last {len(capped_history)} dialogue turns "
                f"(~{injected_tokens} tok) into model context via send_client_content(turn_complete=False)."
            )
            append_diagnostic_log(
                "🗜️ FactStore Injected",
                f"Restored last {len(capped_history)} turns (~{injected_tokens} tok) of verbatim transcript into context."
            )
        except Exception as e:
            logger.error(f"❌ [FactStore Injection] Error sending client_content: {e}")

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

    # ── Custom Live media: recorded voice clone and uploaded avatar ─────

    async def _connection_task_handler(self, config):
        from pipecat.services.google.gemini_live.vertex.llm import GeminiLiveVertexLLMService

        lang_code = getattr(self, "_language_code", None) or "en-US"
        if isinstance(self, GeminiLiveVertexLLMService):
            # Transcription language pinning is Vertex AI Enterprise only.
            from google.genai.types import AudioTranscriptionConfig
            config.input_audio_transcription = AudioTranscriptionConfig(language_codes=[lang_code])
            config.output_audio_transcription = AudioTranscriptionConfig(language_codes=[lang_code])

        # Enforce sliding_window.target_tokens on context compression (80% of trigger_tokens)
        if getattr(config, "context_window_compression", None):
            trigger = getattr(config.context_window_compression, "trigger_tokens", None) or 5000
            target = int(trigger * 0.8)  # 4000 for 5000 trigger
            config.context_window_compression.sliding_window = SlidingWindow(target_tokens=target)
            logger.info(f"🗜️ [Context Compression Config] Initialized with trigger_tokens={trigger}, target_tokens={target}")

        # Every attempt starts from Pipecat's config (prebuilt voice, no avatar) and
        # adds whatever custom media is still in play. A rejection drops the part it
        # blames, so each retry carries strictly less custom media: at most three
        # attempts, and anything that is not a media rejection surfaces at once.
        while True:
            attempt = config.model_copy(deep=True)
            self._apply_custom_media(attempt, lang_code)
            try:
                return await super()._connection_task_handler(attempt)
            except Exception as error:
                if not self._reject_custom_media(error):
                    raise

    async def _handle_connection_error(self, error):
        # A rejection after setup: drop the blamed media so the reconnect Pipecat
        # is about to make comes back with the prebuilt voice or avatar.
        self._reject_custom_media(error)
        return await super()._handle_connection_error(error)

    def _apply_custom_media(self, config, lang_code):
        self._apply_custom_voice(config, lang_code)
        if getattr(self, "_avatar_enabled", False):
            self._apply_avatar(config)

    def _apply_custom_voice(self, config, lang_code):
        sample = getattr(self, "_replicated_voice_sample", None)
        if not sample:
            return  # Pipecat's config already speaks with the prebuilt voice.
        from google.genai.types import ReplicatedVoiceConfig
        try:
            wav, meta = normalize_custom_voice_audio(sample)
        except Exception as wav_err:
            self._fall_back_voice(f"The voice sample could not be read ({wav_err})", "invalid_sample")
            return
        speech = SpeechConfig(
            voice_config=VoiceConfig(
                replicated_voice_config=ReplicatedVoiceConfig(
                    voice_sample_audio=wav,
                    mime_type="audio/pcm;rate=24000",
                )
            ),
            language_code=lang_code,
        )
        if getattr(config, "generation_config", None) is not None:
            config.generation_config.speech_config = speech
        config.speech_config = speech
        logger.info(
            f"🎙️ [Live Voice Clone] Configured replicated_voice_config "
            f"({meta['duration_s']}s, 24kHz 16-bit mono WAV, {meta['bytes']} bytes) "
            f"with fallback '{self._fallback_voice()}'"
        )

    def _apply_avatar(self, config):
        from google.genai.types import AvatarConfig, CustomizedAvatar, Modality
        if getattr(config, "generation_config", None) is not None:
            config.generation_config.response_modalities = None
        config.response_modalities = [Modality.VIDEO]
        name = self._fallback_avatar()
        image_b64 = getattr(self, "_avatar_custom_image", None)
        if image_b64:
            try:
                image, meta = normalize_custom_avatar_image(base64.b64decode(image_b64.split(",")[-1]))
            except Exception as img_err:
                self._fall_back_avatar(f"The image could not be used ({img_err})", "invalid_image")
            else:
                config.avatar_config = AvatarConfig(
                    customized_avatar=CustomizedAvatar(image_data=image, image_mime_type="image/png")
                )
                logger.info(
                    f"🎭 [Live Avatar] Configured customized_avatar "
                    f"({meta['orig_size']} -> {meta['norm_size']} RGB PNG, {len(image)} bytes) "
                    f"with fallback '{name}'"
                )
                return
        config.avatar_config = AvatarConfig(avatar_name=name)
        logger.info(f"🎭 [Live Avatar] Configured prebuilt avatar_name='{name}' with response_modalities=[VIDEO]")

    def _reject_custom_media(self, error) -> set:
        """Drop whichever custom media `error` blames and return what was dropped."""
        rejected = classify_custom_media_rejection(
            error,
            avatar=bool(getattr(self, "_avatar_custom_image", None)),
            voice=bool(getattr(self, "_replicated_voice_sample", None)),
        )
        detail = _rejection_detail(error)
        not_allowlisted = "not allowlisted" in detail.lower()
        code = "project_not_allowlisted" if not_allowlisted else "rejected"
        if "avatar" in rejected:
            self._fall_back_avatar(
                "This Google Cloud project is not allowlisted for custom avatars" if not_allowlisted
                else f"Vertex AI rejected the custom avatar ({detail})",
                code,
            )
        if "voice" in rejected:
            self._fall_back_voice(
                "This Google Cloud project is not allowlisted for custom Live voices" if not_allowlisted
                else f"Vertex AI rejected the voice sample ({detail})",
                code,
            )
        return rejected

    def _fallback_avatar(self) -> str:
        return getattr(self, "_avatar_name", None) or "Ben"

    def _fallback_voice(self) -> str:
        return getattr(self, "_fallback_voice_name", None) or "Puck"

    def _fall_back_avatar(self, cause: str, code: str):
        name = self._fallback_avatar()
        logger.warning(f"🎭 [Live Avatar] {cause}; using the prebuilt avatar '{name}'")
        self._avatar_custom_image = None
        self._avatar_fallback_notice = {
            "fallback_avatar": name,
            "reason": f"{cause}, so the prebuilt avatar {name} is standing in.",
            "code": code,
        }

    def _fall_back_voice(self, cause: str, code: str):
        name = self._fallback_voice()
        logger.warning(f"🎙️ [Live Voice Clone] {cause}; using the prebuilt voice '{name}'")
        self._replicated_voice_sample = None
        self._voice_fallback_notice = {
            "fallback_voice": name,
            "reason": f"{cause}, so the prebuilt voice {name} is speaking instead.",
            "code": code,
        }

class CustomGeminiLiveVertexLLMService(GeminiSessionLoggerMixin, GeminiLiveVertexLLMService):
    @property
    def _supports_non_blocking_tools(self) -> bool:
        return True

    @staticmethod
    def _get_credentials(credentials, credentials_path):
        from runtime_compat import _ensure_valid_adc
        cached = _ensure_valid_adc()
        if not credentials and not credentials_path and cached is not None:
            return cached
        return GeminiLiveVertexLLMService._get_credentials(credentials, credentials_path)


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
    """Handles client start_trigger and gates microphone audio during initial greeting.

    For Gemini 3.1 Live Preview, open duplex microphone streaming before the user
    speaks causes server-side audio metering to leak ~201 prompt tokens on Turn 1.
    When `gate_mic_on_greeting` is active:
      - Raw audio chunks during silence/ambient noise are dropped from downstream.
      - If the user speaks (voice barge-in, RMS > 650 for >=2 frames), an interruption
        is immediately broadcast to halt the bot greeting and the mic gate opens.
      - If the bot finishes the greeting uninterrupted, BotStoppedSpeakingFrame or
        TTSStoppedFrame opens the gate cleanly.
      - A 12s safety watchdog auto-opens the gate if no signal arrives.
    """

    def __init__(
        self,
        language: str = "en-US",
        gate_mic_on_greeting: bool = False,
    ):
        super().__init__()
        self.language = language
        self.triggered = False
        self.gate_mic_on_greeting = gate_mic_on_greeting
        self._mic_gated = gate_mic_on_greeting
        self._pre_buffer = deque(maxlen=10)  # ~200ms pre-speech buffer to prevent onset clipping
        self._consecutive_speech_frames = 0
        self._gate_start_time = time.monotonic()
        self._max_gate_duration = 12.0  # Safety timeout
        if self._mic_gated:
            logger.info("[StartTriggerProcessor] Client mic gating enabled for initial greeting turn.")

    def open_gate(self, reason: str = "manual"):
        if self._mic_gated:
            logger.info(f"[GreetingAudioGate] Opening client microphone gate (reason: {reason}).")
            self._mic_gated = False
            self._pre_buffer.clear()

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        await super().process_frame(frame, direction)

        # 1. Gate release on bot completion signals (travels upstream from output transport or downstream from LLM)
        if isinstance(frame, (BotStoppedSpeakingFrame, TTSStoppedFrame)):
            self.open_gate(f"{type(frame).__name__} received")
            await self.push_frame(frame, direction)
            return

        # 2. Handle start_trigger message from client
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
                    self._gate_start_time = time.monotonic()
                    greeting_text = "Hey!" if self.language == "hi-IN" else "Hello!"
                    logger.info(f"[StartTriggerProcessor] start_trigger received. Queueing single greeting turn: {greeting_text}")
                    await self.push_frame(LLMMessagesAppendFrame(messages=[{"role": "user", "content": greeting_text}]))
                    await self.push_frame(LLMRunFrame())
                return

        # 3. Audio input gating & user barge-in detection during initial greeting
        if isinstance(frame, InputAudioRawFrame):
            if not self._mic_gated:
                await self.push_frame(frame, direction)
                return

            # Safety watchdog: auto-open if greeting exceeds max duration
            if (time.monotonic() - self._gate_start_time) > self._max_gate_duration:
                self.open_gate("watchdog timeout 12s expired")
                await self.push_frame(frame, direction)
                return

            # Voice activity check on incoming PCM chunk (RMS energy)
            audio_bytes = getattr(frame, "audio", None)
            if not audio_bytes:
                return

            samples = np.frombuffer(audio_bytes, dtype=np.int16)
            rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if len(samples) > 0 else 0.0

            # Barge-in speech threshold:
            # Silence/background room noise with open mic is RMS ~40 to 250.
            # Human speech speaking into mic is typically RMS 1,200 to 10,000+.
            # Requiring 2 consecutive frames (>40ms) with RMS > 650 prevents single click/breath false triggers.
            if rms > 650.0:
                self._consecutive_speech_frames += 1
                if self._consecutive_speech_frames >= 2:
                    logger.info(
                        f"[GreetingAudioGate] User voice barge-in detected during initial greeting! "
                        f"(RMS={rms:.1f}, frames={self._consecutive_speech_frames}). "
                        "Broadcasting interruption and opening microphone gate."
                    )
                    self._mic_gated = False
                    # Abort bot greeting playback immediately
                    await self.broadcast_interruption()
                    # Flush onset frames from pre_buffer so first syllable is preserved
                    while self._pre_buffer:
                        buffered_frame = self._pre_buffer.popleft()
                        await self.push_frame(buffered_frame, direction)
                    # Forward active speech frame downstream to model
                    await self.push_frame(frame, direction)
                    return
            else:
                self._consecutive_speech_frames = 0

            # Ambient noise / silence during greeting: store in rolling pre_buffer and drop from downstream!
            self._pre_buffer.append(frame)
            return

        await self.push_frame(frame, direction)


VALID_THINKING_LEVELS = ("minimal", "low", "medium", "high")

AI_STUDIO_LIVE_MODELS = {
    "gemini-3.8-live-extended-thinking",
    "gemini-3.5-live-preview",
    "gemini-3.5-live-extended-thinking-preview",
    "gemini-3.1-flash-live-preview",
    "gemini-3.5-live-translate-preview",
    "gemini-2.5-flash-native-audio-latest",
    "gemini-2.5-flash-native-audio-preview-09-2025",
    "gemini-2.5-flash-native-audio-preview-12-2025",
}
VERTEX_LIVE_MODELS = {
    "gemini-3.8-live",
    "gemini-3.8-live-preview",
    "gemini-3.8-live-extended-thinking-preview",
    "gemini-3.5-flash-live-preview",
    "gemini-3.5-flash-lite-live-preview",
    "gemini-3.8-flash-live-preview",
    "gemini-live-2.5-flash-native-audio",
    "gemini-live-2.5-flash",
}
AI_STUDIO_RENAME_MAP = {
    "gemini-3.5-live-preview": "gemini-3.8-live",
    "gemini-3.5-live-extended-thinking-preview": "gemini-3.8-live-extended-thinking",
    "gemini-3.8-live-preview": "gemini-3.8-live",
    "gemini-3.8-live-extended-thinking-preview": "gemini-3.8-live-extended-thinking",
}
VERTEX_RENAME_MAP = {
    "gemini-3.8-flash-live-preview": "gemini-3.8-live",
    "gemini-3.8-live-preview": "gemini-3.8-live",
    "gemini-3.8-live-extended-thinking": "gemini-3.8-live-extended-thinking-preview",
}


def resolve_live_model_gateway(model: str) -> tuple[bool, str]:
    """Resolve whether a Live model string targets AI Studio or Vertex AI, and its normalized model ID.

    - On Vertex AI (`us-central1`), `gemini-3.8-live` is GA (default), while
      `gemini-3.8-live-extended-thinking-preview` remains in preview.
    - Legacy `gemini-3.8-live-preview` and `gemini-3.8-flash-live-preview` normalize
      to `gemini-3.8-live` on Vertex AI.
    - On AI Studio, `gemini-3.8-live-aistudio` strips `-aistudio` and sends `gemini-3.8-live`.
    """
    clean_model = model[:-9] if model.endswith("-aistudio") else model
    if model.endswith("-aistudio") or clean_model in AI_STUDIO_LIVE_MODELS:
        clean_model = AI_STUDIO_RENAME_MAP.get(clean_model, clean_model)
        return True, clean_model
    clean_model = VERTEX_RENAME_MAP.get(clean_model, clean_model)
    return False, clean_model


def build_thinking_config(model: str, thinking: bool, thinking_level: Optional[str]) -> dict:
    """Build the Gemini reasoning config for a Live session.

    Gemini 3 replaced the numeric `thinking_budget` with discrete `thinking_level`
    tiers, and the API rejects any request carrying both. We therefore only ever
    emit `thinking_level`. An empty dict means "no explicit config", letting the
    model apply its own default tier.
    See https://ai.google.dev/gemini-api/docs/thinking
    """
    # Base Gemini 3.8 Live (`gemini-3.8-live` / `gemini-3.8-live-preview`) does not
    # support `thinking_level` (reasoning is served by the dedicated
    # `gemini-3.8-live-extended-thinking*` models). Never emit `thinking_level`
    # for the non-thinking 3.8 Live endpoint even if the UI toggle remained set.
    if "3.8" in model and "thinking" not in model.lower():
        return {}

    # Models with "thinking" in the name reason by default; honour that even if
    # the client did not explicitly opt in.
    if not thinking and "thinking" not in model.lower():
        return {}

    level = (thinking_level or "").strip().lower()
    if level not in VALID_THINKING_LEVELS:
        # Lite and 3.1-class models are latency sensitive, so bias them low.
        level = "minimal" if ("3.1" in model or "flash-lite" in model) else "medium"
    return {"thinking_level": level}


def compose_live_system_prompt(
    system_instruction: Optional[str],
    gender: str,
    language: str,
    voice: Optional[str] = None,
) -> str:
    """Build the system prompt for a Live session.

    A caller-supplied ``system_instruction`` is authoritative and passes through
    untouched apart from the language directive. Earlier revisions appended a
    global "never ask for the user's name" rule here unconditionally, which
    silently contradicted custom instructions that legitimately needed to ask.
    That rule now lives where it belongs: in the shared default prompt
    (``system_prompt.SYSTEM_PROMPT``) and in each persona's own prompt, both of
    which a caller can override.

    A cloned ``voice`` also gets its self-reference grammar rule: its gender is
    fixed by the recording, whatever the persona says.
    """
    base = system_instruction if system_instruction else SYSTEM_PROMPT.replace("female", gender)
    gender_rule = tts_script.voice_gender_rule(voice)
    if gender_rule:
        base = f"{base}\n\n{gender_rule}"
    return f"{base}\n\nIMPORTANT: You must converse in {language} language."


def resolve_live_vad_mode(vad: bool = True, vad_mode: Optional[str] = None) -> tuple[str, bool, bool]:
    """Resolve VAD mode into (mode_name, use_silero_vad, disable_gemini_internal_vad).

    Supported modes:
    - "both": Local Silero VAD on WebSocket transport + Gemini Live internal server-side VAD enabled.
    - "gemini": Local Silero VAD disabled; Gemini Live internal server-side VAD enabled.
    - "silero": Local Silero VAD on WebSocket transport; Gemini Live internal server-side VAD disabled
      (AutomaticActivityDetection(disabled=True) so Pipecat sends explicit ActivityStart/ActivityEnd).
    """
    normalized = (vad_mode or "").strip().lower()
    if normalized == "silero":
        return ("silero", True, True)
    if normalized == "gemini" or (not normalized and not vad):
        return ("gemini", False, False)
    return ("both", True, False)


def build_live_vad_analyzer(vad: bool = True, vad_mode: Optional[str] = None) -> Optional[SileroVADAnalyzer]:
    """Client-side turn detection for the Live pipeline.

    Returning ``None`` hands endpointing to Gemini's own server-side turn
    detection. That is a legitimate configuration for native audio, not a
    degraded one, but it changes interruption behaviour — so it stays opt-in.
    """
    _, use_silero, _ = resolve_live_vad_mode(vad, vad_mode)
    if not use_silero:
        return None
    return SileroVADAnalyzer(params=VADParams(stop_secs=0.4))


def build_gemini_live_vad_params(vad: bool = True, vad_mode: Optional[str] = None) -> Optional[GeminiVADParams]:
    """Server-side AutomaticActivityDetection configuration for Gemini Live."""
    _, _, disable_gemini_internal = resolve_live_vad_mode(vad, vad_mode)
    if disable_gemini_internal:
        return GeminiVADParams(disabled=True)
    return None


from persona_registry import get_persona_architecture


PREBUILT_AVATAR_NAMES = {"Ben", "Kira", "Leo", "Vera", "Sam", "Kai", "Jay", "Paul"}


def normalize_custom_avatar_image(raw_bytes: bytes) -> tuple[bytes, dict]:
    """Normalize any user-uploaded portrait into Vertex AI's required 9:16 RGB PNG (>=704x1280, <5 MB).

    Requirements per Vertex AI Gemini 3.8 Live Avatar documentation:
      - Format: PNG (lossless RGB)
      - Minimum size: 704 x 1280 pixels (9:16 portrait)
      - File size: < 5 MB
      - Framing: Head & shoulders bust shot (upper-center bias when cropping square/landscape uploads)
    """
    import io
    from PIL import Image, ImageOps

    target_w, target_h = 704, 1280
    with Image.open(io.BytesIO(raw_bytes)) as img:
        orig_format = img.format
        exif = img.getexif()
        orientation = exif.get(0x0112, 1) if exif else 1
        if (
            orig_format == "PNG"
            and img.size == (target_w, target_h)
            and img.mode == "RGB"
            and orientation == 1
            and len(raw_bytes) <= 4_800_000
        ):
            return raw_bytes, {
                "orig_size": f"{target_w}x{target_h}",
                "norm_size": f"{target_w}x{target_h}",
                "bytes": len(raw_bytes),
            }

        img = ImageOps.exif_transpose(img)
        orig_w, orig_h = img.size
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            bg = Image.new("RGB", img.size, (18, 24, 38))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[3])
            rgb_img = bg
        else:
            rgb_img = img.convert("RGB")

        # Bias vertical crop slightly toward top (0.22) to preserve head & shoulders bust framing
        if rgb_img.size == (target_w, target_h):
            fitted = rgb_img
        else:
            fitted = ImageOps.fit(
                rgb_img,
                (target_w, target_h),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.22),
            )
        out = io.BytesIO()
        fitted.save(out, format="PNG", compress_level=6)
        norm_bytes = out.getvalue()

        # If PNG exceeds 4.8 MB, downscale slightly while keeping >= 704x1280
        if len(norm_bytes) > 4_800_000:
            out = io.BytesIO()
            fitted.quantize(colors=256).convert("RGB").save(out, format="PNG", compress_level=6)
            norm_bytes = out.getvalue()

        return norm_bytes, {
            "orig_size": f"{orig_w}x{orig_h}",
            "norm_size": f"{target_w}x{target_h}",
            "bytes": len(norm_bytes),
        }


def normalize_custom_voice_audio(raw_bytes: bytes) -> tuple[bytes, dict]:
    """Normalize any uploaded/recorded WAV sample into Vertex AI's required 24 kHz 16-bit mono WAV (`s16le`).

    Requirements per Vertex AI Gemini 3.8 Live ReplicatedVoiceConfig documentation:
      - Container: WAV (`RIFF...WAVE`) with `mime_type="audio/pcm;rate=24000"`
      - Sample rate: 24,000 Hz
      - Bit depth: 16-bit signed integer PCM (`s16le`)
      - Channels: 1 (mono)
      - Duration: 10–20 seconds recommended (clamped to <= 20s)
    """
    import io
    import wave
    import numpy as np

    if not raw_bytes or len(raw_bytes) < 44:
        raise ValueError("Voice sample audio is empty or too short")

    try:
        with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
            orig_ch = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            orig_sr = wf.getframerate()
            nframes = wf.getnframes()
            frames = wf.readframes(nframes)
    except Exception as exc:
        raise ValueError(f"Invalid WAV audio file: {exc}") from exc

    if orig_sr <= 0 or orig_ch <= 0 or nframes <= 0:
        raise ValueError("WAV audio has invalid header parameters")

    #Fast-path if already 24kHz 16-bit mono WAV within 1..20s
    if orig_sr == 24000 and orig_ch == 1 and sampwidth == 2 and (24000 <= nframes <= 24000 * 20):
        return raw_bytes, {
            "orig_rate": orig_sr,
            "orig_channels": orig_ch,
            "duration_s": round(nframes / 24000.0, 2),
            "bytes": len(raw_bytes),
        }

    if sampwidth == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sampwidth == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sampwidth == 4:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif sampwidth == 3:
        raw_u8 = np.frombuffer(frames, dtype=np.uint8)
        n_samp = len(raw_u8) // 3
        b = raw_u8[: n_samp * 3].reshape(-1, 3)
        signed = (
            b[:, 0].astype(np.int32)
            | (b[:, 1].astype(np.int32) << 8)
            | (b[:, 2].astype(np.int8).astype(np.int32) << 16)
        )
        samples = signed.astype(np.float32) / 8388608.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sampwidth} bytes")

    if orig_ch > 1:
        usable = (len(samples) // orig_ch) * orig_ch
        samples = samples[:usable].reshape(-1, orig_ch).mean(axis=1)

    target_sr = 24000
    if orig_sr != target_sr and len(samples) > 1:
        new_len = int(round(len(samples) * target_sr / orig_sr))
        old_x = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
        new_x = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
        samples = np.interp(new_x, old_x, samples).astype(np.float32)

    if len(samples) < target_sr:
        raise ValueError("Voice sample must be at least 1 second long")

    max_samples = target_sr * 20
    if len(samples) > max_samples:
        samples = samples[:max_samples]

    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if 0.01 < peak < 0.35:
        samples = samples * (0.85 / peak)

    pcm_i16 = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as out_wf:
        out_wf.setnchannels(1)
        out_wf.setsampwidth(2)
        out_wf.setframerate(target_sr)
        out_wf.writeframes(pcm_i16.tobytes())
    norm_wav = out.getvalue()
    return norm_wav, {
        "orig_rate": orig_sr,
        "orig_channels": orig_ch,
        "duration_s": round(len(pcm_i16) / float(target_sr), 2),
        "bytes": len(norm_wav),
    }


def load_live_voice_sample(voice: Optional[str], custom_voice_audio: Optional[str]) -> tuple[Optional[bytes], bool]:
    """The ReplicatedVoiceConfig sample for a session, and whether a clone was asked for.

    A recorded or uploaded sample (base64 or data URL) wins; a server-managed
    Gemini clone loads its bundled sample. A clone that was asked for but has
    no usable sample comes back as (None, True): the session runs as plain
    Live and says so, instead of pretending to clone.
    """
    if custom_voice_audio:
        try:
            return base64.b64decode(custom_voice_audio.split(",")[-1]) or None, True
        except ValueError as b64_err:
            logger.warning(f"🎙️ [Live Voice Clone] Could not decode the recorded voice sample: {b64_err}")
            return None, True
    if voice_profiles.is_gemini_clone_voice(voice):
        return voice_profiles.load_gemini_live_voice_sample(voice), True
    return None, voice_profiles.is_live_replicated_voice(voice)


def resolve_prebuilt_avatar_name(
    avatar_name: Optional[str],
    persona_id: Optional[str],
    voice: Optional[str],
    gender: str,
) -> str:
    """Resolve an avatar selection ('auto', 'custom', or explicit prebuilt name) to a valid Vertex AI prebuilt avatar_name."""
    raw = (avatar_name or "").strip()
    for valid in PREBUILT_AVATAR_NAMES:
        if raw.lower() == valid.lower():
            return valid

    pid = (persona_id or "").strip().lower()
    if pid == "hindi-assistant":
        return "Vera"
    if pid == "banking-advisor":
        return "Kira"
    if pid == "tech-architect":
        return "Leo"
    if pid == "store-assistant":
        return "Ben"
    return "Kira" if (voice_profiles.voice_gender(voice) or gender) == "female" else "Ben"


async def run_agent_live(
    websocket: WebSocket,
    model: str,
    voice: Optional[str],
    language: str,
    system_instruction: Optional[str] = None,
    tts: bool = True,
    tts_pace: float = 0.80,
    tools: Optional[str] = None,
    context_compression: bool = True,
    context_compression_trigger_tokens: Optional[int] = None,
    thinking: bool = False,
    thinking_level: Optional[str] = None,
    custom_voice_key: Optional[str] = None,
    vad: bool = True,
    vad_mode: Optional[str] = None,
    # Selects the persona's execution architecture. This is the ONLY input that
    # decides which persona tooling loads -- the system instruction is never
    # inspected for that purpose. See server/persona_registry.py.
    persona_id: Optional[str] = None,
    avatar_enabled: bool = False,
    avatar_name: str = "auto",
    avatar_custom_image: Optional[str] = None,
    custom_voice_audio: Optional[str] = None,
):
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
    location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"

    gender = voice_profiles.voice_gender(voice) or "female"
    logger.info(f"Starting agent with language: {language}")

    # Resolved before the prompt is composed: an architecture may own its system
    # instruction outright. Routing is on persona_id alone -- the instruction text
    # is never inspected to decide behaviour. See server/persona_registry.py.
    persona_architecture = get_persona_architecture(persona_id)
    logger.info(
        f"Persona architecture: {persona_architecture.pattern.value} "
        f"(persona_id={persona_id or 'unspecified'})"
    )
    effective_instruction = persona_architecture.compose_system_prompt(system_instruction)
    if effective_instruction is not system_instruction:
        logger.info(
            "System instruction supplied by architecture "
            f"{persona_architecture.pattern.value}; client-provided text ignored."
        )

    prompt_text = compose_live_system_prompt(effective_instruction, gender, language, voice)

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

    effective_vad_mode, use_silero, disable_gemini_vad = resolve_live_vad_mode(vad, vad_mode)
    logger.info(
        f"Live VAD mode: {effective_vad_mode} "
        f"(Silero={'enabled' if use_silero else 'disabled'}, "
        f"GeminiInternalVAD={'disabled' if disable_gemini_vad else 'enabled'})"
    )
    transport = FastAPIWebsocketTransport(
        websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True, audio_out_enabled=True, add_wav_header=False,
            vad_analyzer=build_live_vad_analyzer(vad, vad_mode), serializer=CustomProtobufSerializer(),
            audio_filter=None,
        )
    )

    # Dynamic Tool & RAG / Memory Registration
    # Persona tooling is resolved from the persona_id supplied at connect time.
    # The system instruction is NEVER inspected to decide this: prompt text
    # describes behaviour, it must not select infrastructure. Editing a prompt
    # can no longer silently disable an engine, and a persona that happens to
    # mention a car no longer inherits car tooling.
    persona_architecture = get_persona_architecture(persona_id)
    logger.info(
        f"Persona architecture: {persona_architecture.pattern.value} "
        f"(persona_id={persona_id or 'unspecified'})"
    )

    if getattr(persona_architecture, "has_exclusive_tools", lambda: False)():
        standard_tools = list(persona_architecture.get_tool_schemas())
    else:
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
        standard_tools.extend(persona_architecture.get_tool_schemas())


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

    resolved_avatar_name = resolve_prebuilt_avatar_name(avatar_name, persona_id, voice, gender)
    is_custom_voice = voice_profiles.is_custom_clone_voice(voice)
    replicated_voice_bytes, voice_clone_requested = load_live_voice_sample(voice, custom_voice_audio)
    # Only a real sample takes the clone path; a clone with no sample runs as plain Live and says so.
    is_live_voice_clone = bool(replicated_voice_bytes)
    # When Live Avatar or Gemini 3.8 Live Voice Cloning (ReplicatedVoiceConfig) is enabled,
    # Gemini 3.8 Live synthesizes audio natively on Vertex AI (`google/gemini-3.8-live`),
    # so external Chirp TTS must be disabled.
    use_external_tts = False if (avatar_enabled or is_live_voice_clone) else (tts or is_custom_voice)
    tts_service = None
    if use_external_tts:
        from agent import CustomGoogleTTSService
        cloned_key_content = voice_profiles.resolve_clone_key(voice, custom_voice_key)
        if cloned_key_content:
            clone_lang = Language.HI_IN if ("hi" in (language or "").lower()) else Language.EN_US
            tts_service = CustomGoogleTTSService(
                voice_cloning_key=cloned_key_content,
                params=GoogleTTSService.InputParams(language=clone_lang, speaking_rate=tts_pace),
            )
        else:
            voice_id = voice if voice and not voice.startswith("Custom") and "clone" not in voice.lower() else "Aoede"
            tts_service = CustomGoogleTTSService(
                voice_id=voice_id if "-Chirp3-HD-" in voice_id else f"{language}-Chirp3-HD-{voice_id}",
                params=GoogleTTSService.InputParams(language=pipecat_language, speaking_rate=tts_pace),
            )

    llm_modalities = GeminiModalities.TEXT if use_external_tts else GeminiModalities.AUDIO
    
    voice_name = voice if not use_external_tts else None
    if not voice_name and not use_external_tts:
        voice_name = "Aoede"
    if voice_name and (voice_name.startswith("Custom") or "clone" in voice_name.lower()):
        voice_name = "Puck" if gender == "male" else "Aoede"

    # Voice compatibility guard:
    # Most Gemini Live models (including 2.5 and 3.5) support the full voice library (Aoede, Despina, Puck, etc.).
    # If a voice like 'Callirhoe' is unmapped on the Vertex Live gateway, fallback gracefully to Aoede.
    if voice_name and voice_name.lower() == "callirhoe":
        logger.warning(f"⚠️ Voice '{voice_name}' is currently unmapped on the Vertex Live endpoint. Falling back to 'Aoede'.")
        voice_name = "Aoede"

    cwc = {}
    if context_compression:
        cwc["enabled"] = True
        trigger = 5000
        if context_compression_trigger_tokens is not None:
            # Google GenAI / Vertex Live API strictly validates trigger_tokens in [5000, 128000]
            # (throws "1007 None. Context window trigger tokens must be within [5000, 128000]").
            trigger = max(5000, min(128000, int(context_compression_trigger_tokens)))
        cwc["trigger_tokens"] = trigger
        cwc["sliding_window"] = {"target_tokens": int(trigger * 0.8)}

    is_ai_studio, clean_model = resolve_live_model_gateway(model)
    if avatar_enabled or is_live_voice_clone:
        # Gemini 3.8 Live Avatar (AvatarConfig) and Live Voice Cloning (ReplicatedVoiceConfig)
        # are served on the Vertex AI Enterprise gateway via `google/gemini-3.8-live`.
        is_ai_studio = False
        clean_model = "gemini-3.8-live"
        if avatar_enabled:
            logger.info(
                f"🎭 [Live Avatar] Enabled for session: forcing Vertex AI google/gemini-3.8-live "
                f"(avatar_name='{resolved_avatar_name}', custom_image={'yes' if avatar_custom_image else 'no'})"
            )
        if is_live_voice_clone:
            logger.info(
                f"🎙️ [Live Voice Clone] Enabled for session: forcing Vertex AI google/gemini-3.8-live "
                f"(voice='{voice}', sample_bytes={len(replicated_voice_bytes) if replicated_voice_bytes else 0})"
            )
    model = clean_model

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

        thinking_config = build_thinking_config(clean_model, thinking, thinking_level)
        gemini_vad_params = build_gemini_live_vad_params(vad, vad_mode)

        settings = GeminiLiveLLMService.Settings(
            model=f"models/{clean_model}",
            system_instruction=prompt_text,
            voice=voice_name,
            language=pipecat_language,
            modalities=llm_modalities,
            context_window_compression=cwc,
            thinking=thinking_config,
            vad=gemini_vad_params,
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

        thinking_config = build_thinking_config(clean_model, thinking, thinking_level)
        gemini_vad_params = build_gemini_live_vad_params(vad, vad_mode)

        settings = GeminiLiveVertexLLMService.Settings(
            model=f"google/{vertex_model_name}",
            system_instruction=prompt_text,
            voice=voice_name,
            language=pipecat_language,
            modalities=llm_modalities,
            context_window_compression=cwc,
            thinking=thinking_config,
            vad=gemini_vad_params,
        )
        vertex_params = {
            "project_id": project_id,
            "location": live_location,
            "tools": tools_schema,
            "transcribe_model_audio": True,
            "settings": settings,
        }
        creds_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if creds_file and os.path.isfile(creds_file):
            try:
                with open(creds_file, "r", encoding="utf-8") as cf:
                    if json.load(cf).get("type") == "service_account":
                        vertex_params["credentials_path"] = creds_file
            except Exception:
                pass
        llm = CustomGeminiLiveVertexLLMService(**vertex_params)

    # Avatar & Voice Clone flags for CustomGeminiLiveVertexLLMService._connection_task_handler & _handle_msg_model_turn
    llm._avatar_enabled = bool(avatar_enabled)
    llm._avatar_name = resolved_avatar_name
    llm._avatar_custom_image = avatar_custom_image
    llm._avatar_seq = 0
    llm._replicated_voice_sample = replicated_voice_bytes
    llm._fallback_voice_name = voice_name or ("Puck" if gender == "male" else "Aoede")
    if voice_clone_requested and not replicated_voice_bytes:
        llm._fall_back_voice("No voice sample was recorded or configured for this voice", "missing_sample")

    # Context compression tracking and notification flags
    effective_trigger = (max(5000, min(128000, int(context_compression_trigger_tokens))) if context_compression_trigger_tokens is not None else 5000) if context_compression else None
    llm._context_compression_enabled = context_compression
    llm._context_compression_trigger_tokens = effective_trigger
    llm._context_compression_triggered = False
    llm._last_prompt_tokens = 0

    llm.register_function("get_current_time", get_current_time)
    llm.register_function("search_knowledge_base", search_knowledge_base_handler)
    built_in_tools = {"get_current_time", "search_knowledge_base"}

    # Persona-specific tools are owned by the architecture strategy resolved from
    # persona_id. Adding a new persona architecture therefore never requires an
    # edit here -- see server/persona_registry.py.
    async def broadcast_persona_event(payload: dict):
        """Push a persona telemetry event to the client over RTVI."""
        await llm.push_frame(OutputTransportMessageFrame(message={
            "label": "rtvi-ai",
            "type": "server-message",
            "data": payload,
        }))

    built_in_tools.update(
        persona_architecture.register_handlers(llm, broadcast=broadcast_persona_event)
    )

    # Give the service the architecture and a channel to the client, so a
    # completed user transcript can update persona telemetry without a tool.
    llm.persona_architecture = persona_architecture
    llm.persona_broadcast = broadcast_persona_event

    
    # Register generic handler for dynamic tools (skip built-in tools)
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

    gate_mic_on_greeting = "3.1" in (model or "")
    start_trigger = StartTriggerProcessor(
        language=language,
        gate_mic_on_greeting=gate_mic_on_greeting,
    )
    llm.start_trigger = start_trigger

    turn_tracker = TurnTracker(current_session_id(), "gemini-live", vad_stop_padding_ms=400 if vad else None)
    llm._turn_tracker = turn_tracker
    llm._last_input_turn = turn_tracker.current
    llm._live_output_turn = turn_tracker.current
    if tts_service is not None:
        tts_service._turn_tracker = turn_tracker

    pipeline = Pipeline([
        transport.input(),
        start_trigger,
        TurnBoundaryProcessor(turn_tracker),
        UserIdleProcessor(callback=handle_user_idle, timeout=30.0),
        context_aggregator.user(),
        llm,
        *([tts_service] if tts_service else []),
        ServerAudioTimingProcessor(),
        transport.output(),
        context_aggregator.assistant(),
    ])

    session_id = current_session_id()
    trace_url = GLOBAL_LANGSMITH_TRACER.start_session(session_id, model=model, voice=voice, language=language)

    task = PipelineTask(pipeline, params=PipelineParams(
        enable_metrics=True,
        enable_usage_metrics=True,
    ))
    
    if os.getenv("ENABLE_WHISKER") == "1":
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
        turn_tracker.close()
        logger.info("Pipecat Client disconnected")
        history = getattr(llm, '_dialogue_history', [])
        if history:
            transcript_lines = [f"[{i+1}] {turn['role']}: {turn['text']}" for i, turn in enumerate(history)]
            full_transcript = "\n".join(transcript_lines)
            logger.info(
                f"\n==================== TOTAL SESSION TRANSCRIPTION HISTORY ({len(history)} turns) ====================\n"
                f"{full_transcript}\n"
                f"============================================================================================\n"
            )
        else:
            logger.info("Pipecat Client disconnected (no dialogue history recorded).")
        GLOBAL_LANGSMITH_TRACER.end_session()
        await task.cancel()

    try:
        await PipelineRunner(handle_sigint=False).run(task)
    finally:
        turn_tracker.close()
        GLOBAL_LANGSMITH_TRACER.end_session()
