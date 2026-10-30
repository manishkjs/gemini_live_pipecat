"""Turn origins travel with frames and async work, never with a latest-ID lookup."""
from contextvars import ContextVar
from diagnostic_buffer import record_provider_usage, record_metric
from pipecat.frames.frames import (
    CancelFrame, EndFrame, InterruptionFrame, LLMContextFrame,
    LLMFullResponseEndFrame, OutputTransportMessageFrame, OutputTransportMessageUrgentFrame,
    TTSAudioRawFrame, TTSStoppedFrame,
    UserStartedSpeakingFrame, UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

ORIGIN = ContextVar("provider_turn_origin", default=None)
ORIGIN_KEY = "_telemetry_turn"


class TurnBoundaryProcessor(FrameProcessor):
    def __init__(self, tracker):
        super().__init__()
        self.tracker = tracker

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if not frame.metadata.get("_turn_boundary_seen"):
            # With local VAD, semantic user-turn events may arrive much later
            # (after STT). They must not mint a second turn or interrupt this one.
            local_vad = self.tracker.padding is not None
            if isinstance(frame, VADUserStartedSpeakingFrame) or (
                not local_vad and isinstance(frame, UserStartedSpeakingFrame)
            ):
                self.tracker.start()
            elif isinstance(frame, VADUserStoppedSpeakingFrame) or (
                not local_vad and isinstance(frame, UserStoppedSpeakingFrame)
            ):
                self.tracker.stop(vad=isinstance(frame, VADUserStoppedSpeakingFrame))
            elif isinstance(frame, InterruptionFrame):
                origin = frame.metadata.get(ORIGIN_KEY)
                if origin is not None:
                    origin.finish("interrupted")
                if getattr(self.tracker, "bot_type", None) == "tts-llm-stt":
                    await self.push_frame(OutputTransportMessageUrgentFrame(message={
                        "label": "rtvi-ai",
                        "type": "server-message",
                        "data": {
                            "type": "metrics",
                            "payload": {"type": "interruption", "count": 1},
                        },
                    }))
            elif isinstance(frame, (EndFrame, CancelFrame)):
                self.tracker.close()
            frame.metadata["_turn_boundary_seen"] = True
        frame.metadata.setdefault(ORIGIN_KEY, self.tracker.current)
        frame.metadata.setdefault("turn_id", self.tracker.current.turn_id)
        await self.push_frame(frame, direction)


class TurnOriginMixin:
    """Bind a frame's origin for the duration of provider processing.

    Unattributed aggregator/tool callbacks stay unattributed. Spawned tasks
    inherit the ContextVar; delayed audio carries the captured object in metadata.
    Provider request TTFB can still be reported without claiming a turn interval.
    """
    async def process_frame(self, frame, direction):
        origin = frame.metadata.get(ORIGIN_KEY)
        tracker = getattr(self, "_turn_tracker", None)
        if tracker is not None and tracker.padding is None and not frame.metadata.get("_turn_boundary_seen"):
            # In server-VAD-only mode (padding=None), LLMUserAggregator sits downstream
            # of TurnBoundaryProcessor and broadcasts UserStarted/StoppedSpeakingFrame
            # directly to the LLM without passing through TurnBoundaryProcessor first.
            if isinstance(frame, UserStartedSpeakingFrame):
                tracker.start()
                frame.metadata["_turn_boundary_seen"] = True
            elif isinstance(frame, UserStoppedSpeakingFrame):
                origin = tracker.stop(vad=False)
                frame.metadata[ORIGIN_KEY] = origin
                frame.metadata["turn_id"] = origin.turn_id
                frame.metadata["_turn_boundary_seen"] = True
        if isinstance(frame, LLMContextFrame) and ORIGIN_KEY not in frame.metadata:
            # Aggregators can create context after delayed STT/tool callbacks.
            # Capturing tracker.current here would relabel late A as turn B.
            frame.metadata[ORIGIN_KEY] = None
        if isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            if (
                isinstance(frame, UserStoppedSpeakingFrame)
                and origin is None
                and tracker is not None
                and tracker.padding is not None
            ):
                # In local-VAD modes, LLMUserAggregator broadcasts a synthetic
                # UserStoppedSpeakingFrame downstream ~600ms after VADUserStoppedSpeakingFrame
                # without TurnBoundaryProcessor metadata. Never let it wipe _last_input_turn.
                origin = getattr(self, "_last_input_turn", None)
            else:
                self._last_input_turn = origin
            if getattr(self, "_live_telemetry", False) and getattr(self, "_live_output_turn", None) is None:
                # Reserve A at its input boundary, before its first output.
                # Keep that reservation until the ordered Live completion or
                # interruption acknowledgement; B must not steal delayed A.
                self._live_output_turn = origin
        token = ORIGIN.set(origin)
        try:
            await super().process_frame(frame, direction)
        finally:
            ORIGIN.reset(token)

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        origin = frame.metadata.get(ORIGIN_KEY, ORIGIN.get())
        if origin is None and ORIGIN_KEY not in frame.metadata:
            origin = getattr(self, "_live_output_turn", None)
        if ORIGIN_KEY not in frame.metadata:
            frame.metadata[ORIGIN_KEY] = origin
        if origin is not None:
            frame.metadata["turn_id"] = origin.turn_id
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)) and isinstance(frame.message, dict):
            data = frame.message.get("data", {})
            payload = data.get("payload", {}) if data.get("type") == "metrics" else {}
            if payload.get("type") == "usage" and not frame.metadata.get("_usage_recorded"):
                record_provider_usage(payload)
                frame.metadata["_usage_recorded"] = True
            stages = {"stt_latency": "stt", "llm_latency": "llm", "tts_latency": "tts"}
            stage = stages.get(payload.get("type"))
            if stage and not frame.metadata.get("_stage_recorded"):
                tracker = getattr(self, "_turn_tracker", None)
                bot_type = origin.bot_type if origin else getattr(tracker, "bot_type", None)
                if stage == "llm" and bot_type == "gemini-live":
                    stage = "live_ttfb"
                if origin:
                    origin.metric(stage, payload.get("value"))
                    payload = {**payload, "session_id": origin.session_id, "turn_id": origin.turn_id,
                               "bot_type": origin.bot_type}
                elif tracker:
                    # Request timings need no fabricated conversational identity.
                    # STT's continuous receive loop has no verified utterance
                    # correlation, so its wall-clock heuristic is unavailable.
                    value = payload.get("value")
                    if stage == "stt":
                        value = None
                        payload = {**payload, "type": "stt_latency_unavailable", "value": None}
                    record_metric(tracker.session_id, None, bot_type, stage,
                                  value * 1000 if value is not None else None,
                                  attribution="unavailable")
                    payload = {**payload, "session_id": tracker.session_id, "turn_id": None,
                               "bot_type": bot_type, "attribution": "unavailable"}
                frame.metadata["_stage_recorded"] = True
                frame.message = {**frame.message, "data": {**data, "payload": payload}}
        await super().push_frame(frame, direction)

    async def append_to_audio_context(self, context_id, frame):
        # Audio will be drained by another long-lived task; ContextVars alone
        # cannot preserve origin across this queue boundary.
        if frame is not None and hasattr(frame, "metadata"):
            frame.metadata.setdefault(ORIGIN_KEY, ORIGIN.get())
        await super().append_to_audio_context(context_id, frame)


class ServerAudioTimingProcessor(FrameProcessor):
    """Boundary immediately before the output transport; enforces 2-byte s16le alignment and flushes MediaSender tail."""

    def __init__(self):
        super().__init__()
        self._pcm_carry = b""
        self._utterance_pcm_bytes = 0
        self._utterance_sample_rate = 24000
        self._utterance_channels = 1

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, (InterruptionFrame, CancelFrame, EndFrame)):
            self._pcm_carry = b""
            self._utterance_pcm_bytes = 0
            await self.push_frame(frame, direction)
            return

        origin = frame.metadata.get(ORIGIN_KEY)
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, TTSAudioRawFrame) and frame.audio:
                raw = (self._pcm_carry + bytes(frame.audio)) if self._pcm_carry else bytes(frame.audio)
                even_len = len(raw) & ~1
                self._pcm_carry = raw[even_len:]
                if even_len == 0:
                    return
                if even_len != len(frame.audio) or isinstance(frame.audio, bytearray):
                    frame.audio = raw[:even_len]
                self._utterance_pcm_bytes += even_len
                self._utterance_sample_rate = frame.sample_rate or 24000
                self._utterance_channels = frame.num_channels or 1
                if origin is not None:
                    origin.audio()
            elif isinstance(frame, TTSStoppedFrame):
                self._pcm_carry = b""
                if self._utterance_pcm_bytes > 0:
                    # Pipecat 1.2.1 MediaSender buffers output in 40ms (4 x 10ms) chunks
                    # (1920 bytes @ 24kHz mono) and discards any sub-chunk tail inside
                    # _bot_stopped_speaking() when TTSStoppedFrame arrives. Pad to chunk
                    # boundary so the final spoken syllable flushes completely.
                    chunk_bytes = max(2, int(self._utterance_sample_rate / 100) * self._utterance_channels * 2 * 4)
                    rem = self._utterance_pcm_bytes % chunk_bytes
                    self._utterance_pcm_bytes = 0
                    if rem:
                        tail = TTSAudioRawFrame(
                            b"\x00" * (chunk_bytes - rem),
                            self._utterance_sample_rate,
                            self._utterance_channels,
                        )
                        if origin is not None:
                            tail.metadata[ORIGIN_KEY] = origin
                        await self.push_frame(tail, direction)
            elif isinstance(frame, LLMFullResponseEndFrame) and origin is not None:
                # A tool-only generation is not the end of the spoken response.
                if origin.first_audio is not None:
                    origin.finish("ok")
        await self.push_frame(frame, direction)
