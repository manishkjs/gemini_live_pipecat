"""Background speech & side-talk gate powered by Google Decisions (`gemini-decision-1`).

Provides two Pipecat processors that prevent background voices (TV, radio,
side-talk to others in the room) from triggering unwanted assistant replies:

- `LiveBackgroundSpeechGate`: For Gemini Live in Silero VAD mode
  (`vad_mode="silero"`, where Gemini's server-side VAD is disabled and Pipecat
  owns `ActivityStart`/`ActivityEnd`). Buffers a turn's PCM audio locally
  between `VADUserStartedSpeakingFrame` and `VADUserStoppedSpeakingFrame`,
  classifies the audio clip + last bot utterance via Google Decisions, and only
  forwards the turn to Gemini Live when it is addressed to the assistant.
- `CascadeBackgroundSpeechGate`: For Cascade (`STT -> LLM -> TTS` and
  `skip_stt` audio-to-LLM) pipelines. Sits right before the LLM, inspects each
  completed user turn (`LLMContextFrame`) with transcript + optional audio +
  last assistant utterance, and suppresses the LLM turn (removing the ignored
  user message from context to prevent poisoning subsequent turns) only when
  background speech confidence exceeds a high threshold.

Both gates are strictly fail-open: API errors, timeouts, missing API keys, or
ambiguous probabilities always let the caller's turn through so real customer
speech (e.g. "yes", "haan", OTP digits) is never silently dropped.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import os
import time
from typing import Any, Callable

from loguru import logger

from pipecat.classifiers.base_classifier import (
    BaseClassifier,
    ClassifierAudio,
    ClassifierError,
    YesNoQuestion,
    YesNoResult,
)
from pipecat.classifiers.google.decisions.classifier import GoogleDecisionsClassifier
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    LLMContextFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
    UserMuteStartedFrame,
    UserMuteStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import (
    FrameDirection,
    FrameProcessor,
    FrameProcessorSetup,
)

from processors.emotion_perception import resolve_decision_api_key_async

DEFAULT_DECISION_MODEL = "gemini-decision-1"
DEFAULT_TIMEOUT_SECS = 2.5
LIVE_DEFAULT_TIMEOUT_SECS = 1.5
DEFAULT_IGNORE_THRESHOLD = 0.85
MIN_AUDIO_SECS = 0.18
PRE_ROLL_SECS = 0.50
MAX_BUFFER_SECS = 8.0
MAX_CLASSIFY_AUDIO_SECS = 5.0
FLUSH_CHUNK_MS = 100
MAX_CONSECUTIVE_FAILURES = 3
CIRCUIT_OPEN_COOLDOWN_SECS = 30.0

ADDRESSED_TO_ASSISTANT_QUESTION = YesNoQuestion(
    instructions=(
        "Decide whether the caller's latest utterance is directed to the voice "
        "assistant on this call, or whether it is background audio / side-talk "
        "not meant for the assistant. When uncertain or for short replies "
        "(yes, no, okay, haan, numbers, OTPs), prefer 'yes'."
    ),
    yes=(
        "The caller is speaking to the voice assistant: answering the "
        "assistant's question, asking a question, making a request, providing "
        "details (names, numbers, OTPs, dates, amounts), confirming or "
        "acknowledging ('yes', 'okay', 'haan', 'theek hai', 'sure', 'hello'), "
        "or interrupting to redirect the call."
    ),
    no=(
        "The speech is clearly NOT meant for the assistant: background TV, "
        "radio, or video dialogue, public announcements, or the caller talking "
        "to another person in the room ('mummy ek minute', 'hold on I am on a "
        "call', 'pass the water') unrelated to the call."
    ),
)


@dataclass(frozen=True)
class BackgroundSpeechDecision:
    """Result of evaluating whether a user turn is addressed to the assistant."""

    should_respond: bool
    addressed_probability: float
    background_probability: float
    latency_ms: int
    reason: str
    transcript: str = ""
    audio_duration_secs: float = 0.0

    def to_rtvi_payload(self, mode: str) -> dict[str, Any]:
        """Serialize the decision for RTVI server-message telemetry."""
        return {
            "type": "background_gate",
            "decision": "respond" if self.should_respond else "ignore",
            "addressed_probability": round(self.addressed_probability, 3),
            "background_probability": round(self.background_probability, 3),
            "latency_ms": self.latency_ms,
            "mode": mode,
            "reason": self.reason,
            "transcript": self.transcript[:160] if self.transcript else "",
            "audio_duration_secs": round(self.audio_duration_secs, 1),
        }


class BackgroundSpeechEvaluator:
    """Shared fail-open evaluator backed by `GoogleDecisionsClassifier`."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        ignore_threshold: float = DEFAULT_IGNORE_THRESHOLD,
        timeout_secs: float = DEFAULT_TIMEOUT_SECS,
        model: str = DEFAULT_DECISION_MODEL,
        api_key: str | None = None,
        project_id: str | None = None,
        classifier: BaseClassifier | None = None,
        shared_client: Any = None,
        persona_hint: str = "",
    ) -> None:
        self.enabled = bool(enabled)
        self._ignore_threshold = max(0.5, min(0.99, float(ignore_threshold)))
        self._timeout_secs = max(0.2, float(timeout_secs))
        self._model = model
        self._project_id = project_id
        self._persona_hint = (persona_hint or "").strip()
        self._classifier: BaseClassifier | None = classifier
        self._classifier_setup_done = False
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._disabled_reason: str | None = None

        if not self.enabled:
            self._disabled_reason = "disabled"
            return

        if self._classifier is None:
            if shared_client is not None:
                self._classifier = GoogleDecisionsClassifier(client=shared_client)
            else:
                if api_key is not None:
                    resolved_key = api_key.strip()
                else:
                    resolved_key = (
                        os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
                    ).strip()
                if resolved_key:
                    self._classifier = GoogleDecisionsClassifier(
                        api_key=resolved_key,
                        model=model,
                        timeout=self._timeout_secs,
                    )
                elif api_key is None and project_id:
                    # Resolve Secret Manager lazily in setup() so call setup never blocks.
                    self._deferred_project_id: str | None = project_id
                else:
                    self._deferred_project_id = None
                    self._disabled_reason = "missing_api_key"
                    logger.warning(
                        "[BackgroundGate] No Gemini API key available; gate will fail-open."
                    )
        else:
            self._deferred_project_id = None

    @property
    def classifier(self) -> BaseClassifier | None:
        return self._classifier

    @property
    def ignore_threshold(self) -> float:
        return self._ignore_threshold

    async def setup(self, task_manager: Any) -> None:
        if self._classifier is None and getattr(self, "_deferred_project_id", None):
            resolved = await resolve_decision_api_key_async(self._deferred_project_id)
            if resolved:
                self._classifier = GoogleDecisionsClassifier(
                    api_key=resolved,
                    model=self._model,
                    timeout=self._timeout_secs,
                )
            else:
                self._disabled_reason = "missing_api_key"
        if self._classifier is not None and not self._classifier_setup_done:
            await self._classifier.setup(task_manager)
            self._classifier_setup_done = True

    async def cleanup(self) -> None:
        if self._classifier is not None and self._classifier_setup_done:
            await self._classifier.cleanup()
            self._classifier_setup_done = False

    def _build_state_text(
        self,
        *,
        transcript: str = "",
        last_bot_utterance: str = "",
        has_audio: bool = False,
    ) -> str:
        lines = ["Voice call turn classification."]
        if self._persona_hint:
            lines.append(f"Assistant role: {self._persona_hint[:200]}")
        if last_bot_utterance.strip():
            lines.append(f"Assistant's last message: {last_bot_utterance.strip()[:300]}")
        if transcript.strip():
            lines.append(f"Latest captured speech transcript: {transcript.strip()[:400]}")
        elif has_audio:
            lines.append("Latest captured speech is provided in the attached audio clip.")
        return "\n".join(lines)

    async def evaluate(
        self,
        *,
        transcript: str = "",
        audio_pcm: bytes | None = None,
        sample_rate: int = 16000,
        last_bot_utterance: str = "",
    ) -> BackgroundSpeechDecision:
        """Classify a turn, always failing open on errors, timeouts, or missing inputs."""
        clean_tx = (transcript or "").strip()
        if not self.enabled:
            return BackgroundSpeechDecision(
                should_respond=True,
                addressed_probability=1.0,
                background_probability=0.0,
                latency_ms=0,
                reason="disabled",
                transcript=clean_tx,
            )

        if self._classifier is None:
            return BackgroundSpeechDecision(
                should_respond=True,
                addressed_probability=1.0,
                background_probability=0.0,
                latency_ms=0,
                reason=f"fail_open_{self._disabled_reason or 'no_classifier'}",
                transcript=clean_tx,
            )

        now = time.monotonic()
        if now < self._circuit_open_until:
            return BackgroundSpeechDecision(
                should_respond=True,
                addressed_probability=1.0,
                background_probability=0.0,
                latency_ms=0,
                reason="fail_open_circuit_open",
                transcript=clean_tx,
            )

        has_usable_audio = False
        audio_dur_secs = 0.0
        classify_audio: bytes | None = None
        if audio_pcm and sample_rate > 0:
            audio_dur_secs = len(audio_pcm) / (sample_rate * 2.0)
            if audio_dur_secs >= MIN_AUDIO_SECS:
                has_usable_audio = True
                max_bytes = int(MAX_CLASSIFY_AUDIO_SECS * sample_rate * 2)
                max_bytes -= max_bytes % 2
                classify_audio = audio_pcm[-max_bytes:] if len(audio_pcm) > max_bytes else audio_pcm

        if not clean_tx and not has_usable_audio:
            return BackgroundSpeechDecision(
                should_respond=True,
                addressed_probability=1.0,
                background_probability=0.0,
                latency_ms=0,
                reason="short_audio_bypass",
                transcript=clean_tx,
                audio_duration_secs=audio_dur_secs,
            )

        inputs = (
            [ClassifierAudio(audio=classify_audio, sample_rate=sample_rate)]
            if has_usable_audio and classify_audio is not None
            else []
        )
        state = self._build_state_text(
            transcript=clean_tx,
            last_bot_utterance=last_bot_utterance,
            has_audio=has_usable_audio,
        )

        t0 = time.monotonic()
        try:
            results = await asyncio.wait_for(
                self._classifier.ask(
                    state=state,
                    questions={"addressed": ADDRESSED_TO_ASSISTANT_QUESTION},
                    inputs=inputs,
                ),
                timeout=self._timeout_secs,
            )
            elapsed_ms = int(round((time.monotonic() - t0) * 1000))
            res = results.get("addressed")
            if not isinstance(res, YesNoResult):
                raise ClassifierError(f"Unexpected Decisions result type: {type(res).__name__}")

            addressed_p = max(0.0, min(1.0, float(res.probability)))
            background_p = max(0.0, min(1.0, 1.0 - addressed_p))
            should_respond = background_p < self._ignore_threshold
            self._consecutive_failures = 0
            return BackgroundSpeechDecision(
                should_respond=should_respond,
                addressed_probability=addressed_p,
                background_probability=background_p,
                latency_ms=elapsed_ms,
                reason="addressed" if should_respond else "background_speech",
                transcript=clean_tx,
                audio_duration_secs=audio_dur_secs,
            )
        except asyncio.TimeoutError:
            elapsed_ms = int(round((time.monotonic() - t0) * 1000))
            self._record_failure("timeout")
            return BackgroundSpeechDecision(
                should_respond=True,
                addressed_probability=1.0,
                background_probability=0.0,
                latency_ms=elapsed_ms,
                reason="fail_open_timeout",
                transcript=clean_tx,
                audio_duration_secs=audio_dur_secs,
            )
        except Exception as exc:
            elapsed_ms = int(round((time.monotonic() - t0) * 1000))
            self._record_failure(f"{type(exc).__name__}: {exc}")
            return BackgroundSpeechDecision(
                should_respond=True,
                addressed_probability=1.0,
                background_probability=0.0,
                latency_ms=elapsed_ms,
                reason="fail_open_error",
                transcript=clean_tx,
                audio_duration_secs=audio_dur_secs,
            )

    def _record_failure(self, detail: str) -> None:
        self._consecutive_failures += 1
        logger.warning(
            "[BackgroundGate] Classification failed ({}); failing open (streak={}).",
            detail,
            self._consecutive_failures,
        )
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self._circuit_open_until = time.monotonic() + CIRCUIT_OPEN_COOLDOWN_SECS
            logger.warning(
                "[BackgroundGate] Circuit open for {:.0f}s after {} consecutive failures.",
                CIRCUIT_OPEN_COOLDOWN_SECS,
                self._consecutive_failures,
            )


def _coalesce_audio_frames(
    frames: list[InputAudioRawFrame],
    chunk_ms: int = FLUSH_CHUNK_MS,
) -> list[InputAudioRawFrame]:
    """Merge small 20ms PCM frames into uniform chunks while preserving sample rate."""
    if not frames:
        return []
    coalesced: list[InputAudioRawFrame] = []
    cur_rate = frames[0].sample_rate
    cur_channels = frames[0].num_channels
    cur_metadata: dict[str, Any] = dict(getattr(frames[0], "metadata", None) or {})
    buf = bytearray()
    chunk_bytes = max(2, int(round((chunk_ms / 1000.0) * cur_rate * cur_channels * 2)))
    chunk_bytes -= chunk_bytes % 2

    def _flush_buf() -> None:
        nonlocal buf
        offset = 0
        while offset < len(buf):
            end = min(len(buf), offset + chunk_bytes)
            chunk = InputAudioRawFrame(
                audio=bytes(buf[offset:end]),
                sample_rate=cur_rate,
                num_channels=cur_channels,
            )
            if cur_metadata:
                chunk.metadata.update(cur_metadata)
            coalesced.append(chunk)
            offset = end
        buf = bytearray()

    for frame in frames:
        if frame.sample_rate != cur_rate or frame.num_channels != cur_channels:
            _flush_buf()
            cur_rate = frame.sample_rate
            cur_channels = frame.num_channels
            cur_metadata = dict(getattr(frame, "metadata", None) or {})
            chunk_bytes = max(2, int(round((chunk_ms / 1000.0) * cur_rate * cur_channels * 2)))
            chunk_bytes -= chunk_bytes % 2
        if frame.audio:
            buf.extend(frame.audio)
    _flush_buf()
    return coalesced


def _extract_message_text(message: Any) -> str:
    """Extract plain caller text from a Pipecat/OpenAI-style context message.

    In `skip_stt=True` mode, `AudioAccumulator` constructs a multimodal user
    message containing both an `input_audio` part and a synthetic instruction
    prompt ("Listen carefully to the user's spoken audio..."). We return `""`
    whenever an audio part is present so the synthetic prompt is never fed to
    the classifier as if it were the caller's spoken transcript.
    """
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        has_audio_part = any(
            isinstance(item, dict) and item.get("type") in ("input_audio", "audio")
            for item in content
        )
        if has_audio_part:
            return ""
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
            elif isinstance(item, str) and item.strip():
                parts.append(item.strip())
        return " ".join(parts).strip()
    return ""


class LiveBackgroundSpeechGate(FrameProcessor):
    """Silero-VAD turn gate for Gemini Live (`vad_mode='silero'`).

    Buffers microphone PCM locally while the caller speaks, evaluates the turn
    via `BackgroundSpeechEvaluator` at `VADUserStoppedSpeakingFrame`, and only
    forwards `VADUserStartedSpeakingFrame` + audio + `VADUserStoppedSpeakingFrame`
    downstream when the speech is addressed to the assistant.
    """

    def __init__(
        self,
        evaluator: BackgroundSpeechEvaluator,
        *,
        get_last_bot_utterance: Callable[[], str] | None = None,
        max_buffer_secs: float = MAX_BUFFER_SECS,
        pre_roll_secs: float = PRE_ROLL_SECS,
        on_decision: Callable[[BackgroundSpeechDecision], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._evaluator = evaluator
        self._get_last_bot_utterance = get_last_bot_utterance
        self._max_buffer_secs = max(1.0, float(max_buffer_secs))
        self._pre_roll_secs = max(0.0, float(pre_roll_secs))
        self._on_decision = on_decision

        self._muted = False
        self._bot_speaking = False
        self._in_speech = False
        self._pass_through_turn = False
        self._drop_turn = False
        self._held_start_frame: VADUserStartedSpeakingFrame | None = None
        self._pre_roll: deque[InputAudioRawFrame] = deque()
        self._pre_roll_bytes = 0
        self._turn_frames: list[InputAudioRawFrame] = []
        self._turn_bytes = 0
        self._sample_rate = 16000

    async def setup(self, setup: FrameProcessorSetup) -> None:
        await super().setup(setup)
        await self._evaluator.setup(setup.task_manager)

    async def cleanup(self) -> None:
        await self._evaluator.cleanup()
        await super().cleanup()

    def _reset_turn_state(self) -> None:
        self._in_speech = False
        self._pass_through_turn = False
        self._drop_turn = False
        self._held_start_frame = None
        self._turn_frames.clear()
        self._turn_bytes = 0

    def _append_pre_roll(self, frame: InputAudioRawFrame) -> None:
        if not frame.audio or self._pre_roll_secs <= 0:
            return
        self._sample_rate = frame.sample_rate or self._sample_rate
        max_bytes = int(round(self._pre_roll_secs * self._sample_rate * frame.num_channels * 2))
        self._pre_roll.append(frame)
        self._pre_roll_bytes += len(frame.audio)
        while self._pre_roll and self._pre_roll_bytes > max_bytes:
            old = self._pre_roll.popleft()
            self._pre_roll_bytes -= len(old.audio)

    async def _emit_decision(self, decision: BackgroundSpeechDecision) -> None:
        if self._on_decision is not None:
            try:
                self._on_decision(decision)
            except Exception:
                logger.exception("[LiveBackgroundGate] on_decision callback failed")
        await self.push_frame(
            OutputTransportMessageUrgentFrame(
                message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": decision.to_rtvi_payload("live"),
                }
            )
        )

    async def _evaluate_buffered_audio(self, trim_tail_secs: float = 0.0) -> BackgroundSpeechDecision:
        raw_pcm = b"".join(f.audio for f in self._turn_frames if f.audio)
        rate = self._turn_frames[0].sample_rate if self._turn_frames else self._sample_rate
        classify_pcm = raw_pcm
        if trim_tail_secs > 0 and rate > 0:
            trim_bytes = int(round(trim_tail_secs * rate * 2))
            trim_bytes -= trim_bytes % 2
            min_keep = int(round(MIN_AUDIO_SECS * rate * 2))
            if len(classify_pcm) - trim_bytes >= min_keep:
                classify_pcm = classify_pcm[:-trim_bytes]
        last_bot = self._get_last_bot_utterance() if self._get_last_bot_utterance else ""
        return await self._evaluator.evaluate(
            audio_pcm=classify_pcm,
            sample_rate=rate,
            last_bot_utterance=last_bot,
        )

    async def _flush_held_turn(
        self,
        direction: FrameDirection,
        stop_frame: VADUserStoppedSpeakingFrame | None = None,
    ) -> None:
        if self._held_start_frame is not None:
            await self.push_frame(self._held_start_frame, direction)
            self._held_start_frame = None
        for chunk in _coalesce_audio_frames(self._turn_frames):
            await self.push_frame(chunk, direction)
        self._turn_frames.clear()
        self._turn_bytes = 0
        if stop_frame is not None:
            await self.push_frame(stop_frame, direction)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False

        if not self._evaluator.enabled or direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (StartFrame, EndFrame, CancelFrame)):
            if isinstance(frame, (EndFrame, CancelFrame)):
                self._reset_turn_state()
                self._pre_roll.clear()
                self._pre_roll_bytes = 0
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserMuteStartedFrame):
            self._muted = True
            self._reset_turn_state()
            self._pre_roll.clear()
            self._pre_roll_bytes = 0
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserMuteStoppedFrame):
            self._muted = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, VADUserStartedSpeakingFrame):
            if self._muted:
                return
            self._reset_turn_state()
            self._in_speech = True
            self._held_start_frame = frame
            self._turn_frames = list(self._pre_roll)
            self._turn_bytes = self._pre_roll_bytes
            self._pre_roll.clear()
            self._pre_roll_bytes = 0
            # Interrupt bot audio playback immediately (<50ms) when speech starts
            # while keeping the turn's audio buffered locally until Decisions runs.
            if self._bot_speaking:
                self._bot_speaking = False
                await self.broadcast_interruption()
                await self.push_frame(
                    OutputTransportMessageUrgentFrame(
                        message={
                            "label": "rtvi-ai",
                            "type": "server-message",
                            "data": {
                                "type": "metrics",
                                "payload": {"type": "interruption", "count": 1},
                            },
                        }
                    )
                )
            return

        if isinstance(frame, InputAudioRawFrame):
            if self._muted:
                return
            self._sample_rate = frame.sample_rate or self._sample_rate
            if not self._in_speech:
                self._append_pre_roll(frame)
                return
            if self._pass_through_turn:
                await self.push_frame(frame, direction)
                return
            if self._drop_turn:
                return

            self._turn_frames.append(frame)
            self._turn_bytes += len(frame.audio)
            max_bytes = int(round(self._max_buffer_secs * self._sample_rate * frame.num_channels * 2))
            if self._turn_bytes >= max_bytes:
                decision = await self._evaluate_buffered_audio(trim_tail_secs=0.0)
                await self._emit_decision(decision)
                if decision.should_respond:
                    self._pass_through_turn = True
                    await self._flush_held_turn(direction, stop_frame=None)
                else:
                    self._drop_turn = True
                    self._held_start_frame = None
                    self._turn_frames.clear()
                    self._turn_bytes = 0
            return

        if isinstance(frame, VADUserStoppedSpeakingFrame):
            if not self._in_speech:
                return
            if self._pass_through_turn:
                self._reset_turn_state()
                await self.push_frame(frame, direction)
                return
            if self._drop_turn:
                self._reset_turn_state()
                return

            stop_ts = time.monotonic()
            frame.metadata["_vad_stop_monotonic"] = stop_ts
            trim_tail = float(getattr(frame, "stop_secs", 0.0) or 0.0)
            decision = await self._evaluate_buffered_audio(trim_tail_secs=trim_tail)
            await self._emit_decision(decision)
            if decision.should_respond:
                await self._flush_held_turn(direction, stop_frame=frame)
            else:
                logger.info(
                    "[LiveBackgroundGate] Ignored background turn (p_bg={:.2f}, latency={}ms).",
                    decision.background_probability,
                    decision.latency_ms,
                )
            self._reset_turn_state()
            return

        await self.push_frame(frame, direction)


class CascadeBackgroundSpeechGate(FrameProcessor):
    """Turn-level background speech gate for Cascade (`STT -> LLM -> TTS` and `skip_stt`).

    Sits directly before the LLM. Evaluates each new user `LLMContextFrame` using
    the user's transcript (if present), optional turn audio clip, and the
    assistant's last message. Opening greetings and tool-call follow-up turns
    pass straight through without classification.
    """

    def __init__(
        self,
        evaluator: BackgroundSpeechEvaluator,
        *,
        get_recent_audio: Callable[[], tuple[bytes | None, int]] | None = None,
        on_decision: Callable[[BackgroundSpeechDecision], None] | None = None,
        interrupt_on_respond: bool = False,
        defer_turn_boundaries: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._evaluator = evaluator
        self._get_recent_audio = get_recent_audio
        self._on_decision = on_decision
        self._interrupt_on_respond = bool(interrupt_on_respond)
        self._defer_turn_boundaries = bool(defer_turn_boundaries)
        self._seen_user_speech = False
        self._held_vad_start: VADUserStartedSpeakingFrame | None = None
        self._held_vad_stop: VADUserStoppedSpeakingFrame | None = None
        self._last_vad_stop_monotonic: float | None = None
        # Tracks whether the assistant aggregator has an active turn in progress so
        # barge-in interruptions only fire when needed and never interleave a
        # partial assistant message after the newly appended user message.
        self._assistant_idle_event = asyncio.Event()
        self._assistant_idle_event.set()
        self._tracks_assistant_lifecycle = False
        self._bot_speaking = False

    def mark_assistant_turn_started(self) -> None:
        """Record that the assistant aggregator started a response turn."""
        self._tracks_assistant_lifecycle = True
        self._assistant_idle_event.clear()

    def mark_assistant_turn_stopped(self) -> None:
        """Record that the assistant aggregator committed/stopped its turn."""
        self._tracks_assistant_lifecycle = True
        self._assistant_idle_event.set()

    def attach_assistant_aggregator(self, assistant_aggregator: Any) -> None:
        """Subscribe to Pipecat `LLMAssistantAggregator` turn lifecycle events."""
        if assistant_aggregator is None or not hasattr(assistant_aggregator, "event_handler"):
            return
        self._tracks_assistant_lifecycle = True

        @assistant_aggregator.event_handler("on_assistant_turn_started")
        async def _on_assistant_started(_aggregator: Any, *_args: Any) -> None:
            self.mark_assistant_turn_started()

        @assistant_aggregator.event_handler("on_assistant_turn_stopped")
        async def _on_assistant_stopped(_aggregator: Any, *_args: Any) -> None:
            self.mark_assistant_turn_stopped()

    async def setup(self, setup: FrameProcessorSetup) -> None:
        await super().setup(setup)
        await self._evaluator.setup(setup.task_manager)

    async def cleanup(self) -> None:
        await self._evaluator.cleanup()
        await super().cleanup()

    def _clear_held_boundaries(self) -> None:
        self._held_vad_start = None
        self._held_vad_stop = None
        self._last_vad_stop_monotonic = None

    async def _emit_decision(self, decision: BackgroundSpeechDecision) -> None:
        if self._on_decision is not None:
            try:
                self._on_decision(decision)
            except Exception:
                logger.exception("[CascadeBackgroundGate] on_decision callback failed")
        await self.push_frame(
            OutputTransportMessageUrgentFrame(
                message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": decision.to_rtvi_payload("cascade"),
                }
            )
        )

    @staticmethod
    def _last_assistant_text(messages: list[Any]) -> str:
        for msg in reversed(messages[:-1]):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                text = _extract_message_text(msg)
                if text:
                    return text
        return ""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Track bot playback state from upstream/downstream Bot*SpeakingFrames
        # so barge-in still interrupts queued TTS audio after LLMFullResponseEndFrame.
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False

        if not self._evaluator.enabled or direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            if self._defer_turn_boundaries:
                # Downstream Cascade processors (TurnBoundaryProcessor, LLM, TTS)
                # only consume the VAD boundary pair and LLMContextFrame, so we
                # hold VAD start/stop and absorb semantic User*SpeakingFrames.
                if isinstance(frame, VADUserStartedSpeakingFrame):
                    self._held_vad_start = frame
                return
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            self._seen_user_speech = True
            if self._defer_turn_boundaries:
                if isinstance(frame, VADUserStoppedSpeakingFrame):
                    self._held_vad_stop = frame
                    self._last_vad_stop_monotonic = time.monotonic()
                elif self._last_vad_stop_monotonic is None:
                    self._last_vad_stop_monotonic = time.monotonic()
                return
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMContextFrame):
            context = getattr(frame, "context", None)
            messages = getattr(context, "messages", None)
            if not isinstance(messages, list) or not messages:
                await self.push_frame(frame, direction)
                return

            last_msg = messages[-1]
            if not isinstance(last_msg, dict) or last_msg.get("role") != "user":
                # Tool results, system updates, or assistant messages pass through untouched.
                await self.push_frame(frame, direction)
                return

            has_assistant_history = any(
                isinstance(m, dict) and m.get("role") == "assistant" for m in messages[:-1]
            )
            if not self._seen_user_speech and not has_assistant_history:
                # Opening greeting trigger from StartTriggerProcessor always passes through.
                await self.push_frame(frame, direction)
                return

            user_text = _extract_message_text(last_msg)
            last_bot = self._last_assistant_text(messages)
            audio_pcm: bytes | None = None
            sample_rate = 16000
            if self._get_recent_audio is not None:
                try:
                    audio_pcm, sample_rate = self._get_recent_audio()
                except Exception:
                    audio_pcm = None

            decision = await self._evaluator.evaluate(
                transcript=user_text,
                audio_pcm=audio_pcm,
                sample_rate=sample_rate,
                last_bot_utterance=last_bot,
            )
            await self._emit_decision(decision)

            if decision.should_respond:
                if self._interrupt_on_respond:
                    assistant_turn_active = not self._assistant_idle_event.is_set()
                    needs_interrupt = (
                        assistant_turn_active
                        or self._bot_speaking
                        or not self._tracks_assistant_lifecycle
                    )
                    if needs_interrupt:
                        # Only pop/wait/re-append when the assistant aggregator
                        # has an open turn whose partial reply will be committed
                        # by the interruption; if the LLM already finished and
                        # only TTS playback is still draining, interrupt directly.
                        popped_msg = (
                            messages.pop()
                            if assistant_turn_active and messages and messages[-1] is last_msg
                            else None
                        )
                        try:
                            await self.broadcast_interruption()
                            if (
                                assistant_turn_active
                                and self._tracks_assistant_lifecycle
                                and not self._assistant_idle_event.is_set()
                            ):
                                try:
                                    await asyncio.wait_for(
                                        self._assistant_idle_event.wait(),
                                        timeout=0.5,
                                    )
                                except asyncio.TimeoutError:
                                    logger.warning(
                                        "[CascadeBackgroundGate] Timed out waiting for assistant turn commit after interruption."
                                    )
                        finally:
                            if popped_msg is not None:
                                messages.append(popped_msg)
                if self._defer_turn_boundaries:
                    if self._held_vad_start is not None:
                        await self.push_frame(self._held_vad_start, direction)
                    stop_frame = self._held_vad_stop or VADUserStoppedSpeakingFrame()
                    if self._last_vad_stop_monotonic is not None:
                        stop_frame.metadata["_vad_stop_monotonic"] = self._last_vad_stop_monotonic
                    await self.push_frame(stop_frame, direction)
                    self._clear_held_boundaries()
                await self.push_frame(frame, direction)
            else:
                self._clear_held_boundaries()
                # Remove the ignored background message so it cannot poison the next turn.
                if messages and messages[-1] is last_msg:
                    messages.pop()
                logger.info(
                    "[CascadeBackgroundGate] Ignored background turn (p_bg={:.2f}, latency={}ms, text={!r}).",
                    decision.background_probability,
                    decision.latency_ms,
                    user_text[:80],
                )
            return

        await self.push_frame(frame, direction)
