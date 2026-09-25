"""Turn origins travel with frames and async work, never with a latest-ID lookup."""
from contextvars import ContextVar
from diagnostic_buffer import record_provider_usage, record_metric
from pipecat.frames.frames import (
    CancelFrame, EndFrame, InterruptionFrame, LLMContextFrame,
    LLMFullResponseEndFrame, OutputTransportMessageFrame, OutputTransportMessageUrgentFrame, TTSAudioRawFrame,
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
                if getattr(self.tracker, "bot_type", None) == "tts-llm-stt":
                    await self.push_frame(OutputTransportMessageUrgentFrame(message={
                        "label": "rtvi-ai",
                        "type": "server-message",
                        "data": {
                            "type": "metrics",
                            "payload": {"type": "interruption", "count": 1},
                        },
                    }))
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
        if isinstance(frame, LLMContextFrame) and ORIGIN_KEY not in frame.metadata:
            # Aggregators can create context after delayed STT/tool callbacks.
            # Capturing tracker.current here would relabel late A as turn B.
            frame.metadata[ORIGIN_KEY] = None
        if isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
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
    """Boundary immediately before the output transport; not client playback."""
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        origin = frame.metadata.get(ORIGIN_KEY)
        if direction == FrameDirection.DOWNSTREAM and origin is not None:
            if isinstance(frame, TTSAudioRawFrame) and frame.audio:
                origin.audio()
            elif isinstance(frame, LLMFullResponseEndFrame):
                # A tool-only generation is not the end of the spoken response.
                if origin.first_audio is not None:
                    origin.finish("ok")
        await self.push_frame(frame, direction)
