"""Background speech & side-talk gate powered by Google Decisions (`gemini-decision-1`).

Provides two Pipecat processors that prevent background voices (TV, radio,
announcements, or side-talk to others in the room) from triggering unwanted
assistant replies, while preserving immediate `<50ms` playback barge-in when
speech begins:

- `LiveBackgroundSpeechGate`: For Gemini Live in Silero VAD mode
  (`vad_mode="silero"`, where Gemini's server-side VAD is disabled and Pipecat
  owns `ActivityStart`/`ActivityEnd`). Interrupts local playback immediately on
  `VADUserStartedSpeakingFrame`, buffers the turn's PCM audio locally (absorbing
  `UserSpeakingFrame` so ignored chatter never resets idle timers), classifies
  the mono audio clip + last bot utterance via Google Decisions at `VADUserStoppedSpeakingFrame`, and only forwards the turn to
  Gemini Live when addressed to the assistant.
- `CascadeBackgroundSpeechGate`: For Cascade (`STT -> LLM -> TTS` and
  `skip_stt` audio-to-LLM) pipelines. Sits right before the LLM, atomically
  removes each new user message from `LLMContext.messages` before running an
  un-cancelled Decisions evaluation (so mid-flight `InterruptionFrame` task
  cancellations can never strand ignored TV speech in `LLMContext`), and
  restores/forwards the turn only when addressed to the assistant.

Both gates own an isolated `GoogleDecisionsClassifier` instance (so token
accounting never collides with `AudioEmotionObserver`), warm Secret Manager /
TLS connections in a non-blocking background task, and fail open on timeouts,
errors, or missing credentials.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import inspect
import os
import time
from typing import Any, Callable

from loguru import logger
import numpy as np

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
    UserSpeakingFrame,
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
from processors.turn_telemetry import ORIGIN_KEY

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
        "call', 'pass the water', 'turn off the TV') unrelated to the call."
    ),
)


def downmix_pcm16_to_mono(pcm: bytes, num_channels: int = 1) -> bytes:
    """Convert multi-channel 16-bit PCM to 1-channel mono for `ClassifierAudio`."""
    if not pcm:
        return b""
    channels = max(1, int(num_channels or 1))
    frame_width = 2 * channels
    aligned_len = len(pcm) - (len(pcm) % frame_width)
    if aligned_len <= 0:
        return b""
    if channels == 1:
        return pcm[:aligned_len]
    samples = np.frombuffer(pcm[:aligned_len], dtype=np.int16).reshape(-1, channels)
    mono = np.round(samples.mean(axis=1)).astype(np.int16)
    return mono.tobytes()


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
    input_tokens: int = 0
    output_tokens: int = 0
    utterance_id: int | None = None

    def with_utterance_id(self, utterance_id: int | None) -> BackgroundSpeechDecision:
        if not utterance_id or utterance_id <= 0:
            return self
        return BackgroundSpeechDecision(
            should_respond=self.should_respond,
            addressed_probability=self.addressed_probability,
            background_probability=self.background_probability,
            latency_ms=self.latency_ms,
            reason=self.reason,
            transcript=self.transcript,
            audio_duration_secs=self.audio_duration_secs,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            utterance_id=int(utterance_id),
        )

    def to_rtvi_payload(self, mode: str) -> dict[str, Any]:
        """Serialize the decision for RTVI server-message telemetry."""
        payload: dict[str, Any] = {
            "type": "background_gate",
            "decision": "respond" if self.should_respond else "ignore",
            "addressed_probability": round(self.addressed_probability, 3),
            "background_probability": round(self.background_probability, 3),
            "latency_ms": self.latency_ms,
            "mode": mode,
            "reason": self.reason,
            "transcript": self.transcript[:2000] if self.transcript else "",
            "audio_duration_secs": round(self.audio_duration_secs, 1),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }
        if self.utterance_id is not None and self.utterance_id > 0:
            payload["utterance_id"] = self.utterance_id
        return payload


class BackgroundSpeechEvaluator:
    """Isolated, fail-open evaluator backed by `GoogleDecisionsClassifier`."""

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
        persona_hint: str = "",
    ) -> None:
        self.enabled = bool(enabled)
        self._ignore_threshold = max(0.5, min(0.99, float(ignore_threshold)))
        self._timeout_secs = max(0.2, float(timeout_secs))
        self._model = model
        self._project_id = project_id
        self._persona_hint = (persona_hint or "").strip()
        self._classifier: BaseClassifier | None = classifier
        self._owns_classifier = False
        self._classifier_setup_done = False
        self._deferred_project_id: str | None = None
        self._warm_task: asyncio.Task[None] | None = None
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._disabled_reason: str | None = None
        self._prev_client_in_tokens = 0
        self._prev_client_out_tokens = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0

        if not self.enabled:
            self._disabled_reason = "disabled"
            return

        if self._classifier is None:
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
                self._owns_classifier = True
            elif api_key is None and project_id:
                # Resolve Secret Manager asynchronously so pipeline startup never blocks.
                self._deferred_project_id = project_id
            else:
                self._disabled_reason = "missing_api_key"
                logger.warning(
                    "[BackgroundGate] No Gemini API key available; gate will fail-open."
                )

    @property
    def classifier(self) -> BaseClassifier | None:
        return self._classifier

    @property
    def ignore_threshold(self) -> float:
        return self._ignore_threshold

    @property
    def total_tokens(self) -> tuple[int, int]:
        return (self._total_input_tokens, self._total_output_tokens)

    async def _warm_classifier(self, task_manager: Any) -> None:
        try:
            if self._classifier is None and self._deferred_project_id:
                resolved = await resolve_decision_api_key_async(self._deferred_project_id)
                if resolved:
                    self._classifier = GoogleDecisionsClassifier(
                        api_key=resolved,
                        model=self._model,
                        timeout=self._timeout_secs,
                    )
                    self._owns_classifier = True
                else:
                    self._disabled_reason = "missing_api_key"
            if self._classifier is not None and not self._classifier_setup_done:
                await self._classifier.setup(task_manager)
                self._classifier_setup_done = True
        except Exception as exc:
            logger.warning("[BackgroundGate] Warmup failed ({}): {}", type(exc).__name__, exc)

    async def setup(self, task_manager: Any) -> None:
        """Warm API credentials and HTTP connection without blocking `StartFrame`."""
        if not self.enabled:
            return
        if self._warm_task is None:
            self._warm_task = asyncio.create_task(self._warm_classifier(task_manager))

    async def cleanup(self) -> None:
        if self._warm_task is not None:
            if not self._warm_task.done():
                self._warm_task.cancel()
            await asyncio.gather(self._warm_task, return_exceptions=True)
            self._warm_task = None
        if self._classifier is not None and (self._classifier_setup_done or self._owns_classifier):
            await self._classifier.cleanup()
            self._classifier_setup_done = False

    def _consume_call_tokens(self) -> tuple[int, int]:
        client = getattr(self._classifier, "client", None)
        usage = getattr(client, "usage", None)
        total_in = int(getattr(usage, "input_tokens", 0) or 0)
        total_out = int(getattr(usage, "output_tokens", 0) or 0)
        in_tok = max(0, total_in - self._prev_client_in_tokens)
        out_tok = max(0, total_out - self._prev_client_out_tokens)
        self._prev_client_in_tokens = total_in
        self._prev_client_out_tokens = total_out
        self._total_input_tokens += in_tok
        self._total_output_tokens += out_tok
        return (in_tok, out_tok)

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
        num_channels: int = 1,
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

        t0 = time.monotonic()
        if self._warm_task is not None and not self._warm_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._warm_task), timeout=self._timeout_secs)
            except asyncio.TimeoutError:
                elapsed_ms = int(round((time.monotonic() - t0) * 1000))
                self._record_failure("warmup_timeout")
                return BackgroundSpeechDecision(
                    should_respond=True,
                    addressed_probability=1.0,
                    background_probability=0.0,
                    latency_ms=elapsed_ms,
                    reason="fail_open_timeout",
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
            mono_pcm = downmix_pcm16_to_mono(audio_pcm, num_channels)
            audio_dur_secs = len(mono_pcm) / (sample_rate * 2.0)
            if audio_dur_secs >= MIN_AUDIO_SECS:
                has_usable_audio = True
                max_bytes = int(MAX_CLASSIFY_AUDIO_SECS * sample_rate * 2)
                max_bytes -= max_bytes % 2
                classify_audio = mono_pcm[-max_bytes:] if len(mono_pcm) > max_bytes else mono_pcm

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

        remaining_timeout = max(0.1, self._timeout_secs - (time.monotonic() - t0))
        try:
            results = await asyncio.wait_for(
                self._classifier.ask(
                    state=state,
                    questions={"addressed": ADDRESSED_TO_ASSISTANT_QUESTION},
                    inputs=inputs,
                ),
                timeout=remaining_timeout,
            )
            elapsed_ms = int(round((time.monotonic() - t0) * 1000))
            in_tok, out_tok = self._consume_call_tokens()
            addressed_result = results.get("addressed")
            if not isinstance(addressed_result, YesNoResult):
                raise ClassifierError(
                    f"Unexpected Decisions result type: {type(addressed_result).__name__}"
                )

            addressed_prob = max(0.0, min(1.0, float(addressed_result.probability)))
            background_prob = max(0.0, min(1.0, 1.0 - addressed_prob))
            should_respond = background_prob < self._ignore_threshold
            self._consecutive_failures = 0
            return BackgroundSpeechDecision(
                should_respond=should_respond,
                addressed_probability=addressed_prob,
                background_probability=background_prob,
                latency_ms=elapsed_ms,
                reason="addressed" if should_respond else "background_speech",
                transcript=clean_tx,
                audio_duration_secs=audio_dur_secs,
                input_tokens=in_tok,
                output_tokens=out_tok,
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
    """Merge small 20ms PCM frames into uniform chunks while preserving metadata."""
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

    Interrupts local bot playback immediately (`<50ms`) when speech begins so
    the bot never talks over the caller, buffers microphone PCM locally until
    `VADUserStoppedSpeakingFrame`, evaluates the mono audio clip + last bot
    utterance via `BackgroundSpeechEvaluator`, and only forwards
    `VADUserStartedSpeakingFrame` + audio + `VADUserStoppedSpeakingFrame`
    downstream when addressed to the assistant. If an interrupting sound is
    classified as background noise (`STAYED QUIET`), notifies
    `on_ignored_barge_in` so `RepeatOnFiller` is disarmed and Gemini stays quiet.
    """

    def __init__(
        self,
        evaluator: BackgroundSpeechEvaluator,
        *,
        get_last_bot_utterance: Callable[[], str] | None = None,
        on_ignored_barge_in: Callable[[], Any] | None = None,
        max_buffer_secs: float = MAX_BUFFER_SECS,
        pre_roll_secs: float = PRE_ROLL_SECS,
        on_decision: Callable[[BackgroundSpeechDecision], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._evaluator = evaluator
        self._get_last_bot_utterance = get_last_bot_utterance
        self._on_ignored_barge_in = on_ignored_barge_in
        self._max_buffer_secs = max(1.0, float(max_buffer_secs))
        self._pre_roll_secs = max(0.0, float(pre_roll_secs))
        self._on_decision = on_decision

        self._muted = False
        self._bot_speaking = False
        self._in_speech = False
        self._turn_interrupted_bot = False
        self._pass_through_turn = False
        self._drop_turn = False
        self._held_start_frame: VADUserStartedSpeakingFrame | None = None
        self._pre_roll: deque[InputAudioRawFrame] = deque()
        self._pre_roll_mono_bytes = 0
        self._turn_frames: list[InputAudioRawFrame] = []
        self._turn_mono_chunks: list[bytes] = []
        self._turn_mono_bytes = 0
        self._sample_rate = 16000

    async def setup(self, setup: FrameProcessorSetup) -> None:
        await super().setup(setup)
        await self._evaluator.setup(setup.task_manager)

    async def cleanup(self) -> None:
        await self._evaluator.cleanup()
        await super().cleanup()

    def _reset_turn_state(self) -> None:
        self._in_speech = False
        self._turn_interrupted_bot = False
        self._pass_through_turn = False
        self._drop_turn = False
        self._held_start_frame = None
        self._turn_frames.clear()
        self._turn_mono_chunks.clear()
        self._turn_mono_bytes = 0

    def _append_pre_roll(self, frame: InputAudioRawFrame) -> None:
        if not frame.audio or self._pre_roll_secs <= 0:
            return
        self._sample_rate = frame.sample_rate or self._sample_rate
        mono = downmix_pcm16_to_mono(frame.audio, frame.num_channels)
        if not mono:
            return
        max_bytes = int(round(self._pre_roll_secs * self._sample_rate * 2))
        self._pre_roll.append(frame)
        self._pre_roll_mono_bytes += len(mono)
        while self._pre_roll and self._pre_roll_mono_bytes > max_bytes:
            old = self._pre_roll.popleft()
            old_mono_len = len(downmix_pcm16_to_mono(old.audio, old.num_channels))
            self._pre_roll_mono_bytes = max(0, self._pre_roll_mono_bytes - old_mono_len)

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

    async def _notify_ignored_barge_in(self) -> None:
        if not self._turn_interrupted_bot or self._on_ignored_barge_in is None:
            return
        try:
            maybe_coro = self._on_ignored_barge_in()
            if inspect.iscoroutine(maybe_coro):
                await maybe_coro
        except Exception:
            logger.exception("[LiveBackgroundGate] on_ignored_barge_in callback failed")

    async def _evaluate_buffered_audio(self, trim_tail_secs: float = 0.0) -> BackgroundSpeechDecision:
        mono_pcm = b"".join(self._turn_mono_chunks)
        rate = self._turn_frames[0].sample_rate if self._turn_frames else self._sample_rate
        classify_pcm = mono_pcm
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
            num_channels=1,
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
        self._turn_mono_chunks.clear()
        self._turn_mono_bytes = 0
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
                self._pre_roll_mono_bytes = 0
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserMuteStartedFrame):
            self._muted = True
            self._reset_turn_state()
            self._pre_roll.clear()
            self._pre_roll_mono_bytes = 0
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserMuteStoppedFrame):
            self._muted = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserSpeakingFrame):
            # Absorb ongoing speaking heartbeats while buffering so ignored
            # background chatter never resets downstream UserIdleProcessor timers.
            if self._pass_through_turn and not self._muted:
                await self.push_frame(frame, direction)
            return

        if isinstance(frame, VADUserStartedSpeakingFrame):
            if self._muted:
                return
            self._reset_turn_state()
            self._in_speech = True
            self._held_start_frame = frame
            self._turn_frames = list(self._pre_roll)
            self._turn_mono_chunks = [
                downmix_pcm16_to_mono(f.audio, f.num_channels)
                for f in self._turn_frames
                if f.audio
            ]
            self._turn_mono_bytes = sum(len(c) for c in self._turn_mono_chunks)
            self._pre_roll.clear()
            self._pre_roll_mono_bytes = 0
            # Interrupt local bot playback immediately (<50ms) when speech begins
            # while keeping the turn's audio buffered locally until Decisions runs.
            if self._bot_speaking:
                self._bot_speaking = False
                self._turn_interrupted_bot = True
                await self.broadcast_interruption()
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

            mono = downmix_pcm16_to_mono(frame.audio, frame.num_channels)
            self._turn_frames.append(frame)
            if mono:
                self._turn_mono_chunks.append(mono)
                self._turn_mono_bytes += len(mono)
            max_bytes = int(round(self._max_buffer_secs * self._sample_rate * 2))
            if self._turn_mono_bytes >= max_bytes:
                decision = await self._evaluate_buffered_audio(trim_tail_secs=0.0)
                await self._emit_decision(decision)
                if decision.should_respond:
                    self._pass_through_turn = True
                    await self._flush_held_turn(direction, stop_frame=None)
                else:
                    await self._notify_ignored_barge_in()
                    self._drop_turn = True
                    self._held_start_frame = None
                    self._turn_frames.clear()
                    self._turn_mono_chunks.clear()
                    self._turn_mono_bytes = 0
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
                await self._notify_ignored_barge_in()
                logger.info(
                    "[LiveBackgroundGate] Ignored background turn (p_bg={:.2f}, latency={}ms).",
                    decision.background_probability,
                    decision.latency_ms,
                )
            self._reset_turn_state()
            return

        await self.push_frame(frame, direction)


@dataclass
class _InflightCascadeTurn:
    """Single queued Cascade user utterance awaiting FIFO commit."""

    context: Any
    message: dict[str, Any]
    user_text: str
    utterance_id: int | None
    turn_origin: Any
    eval_task: asyncio.Task[BackgroundSpeechDecision]
    committed: bool = False
    should_respond: bool = True


TurnSnapshot = tuple[Any, int | None, bytes | None, int]


class CascadeBackgroundSpeechGate(FrameProcessor):
    """Turn-level background speech gate for Cascade (`STT -> LLM -> TTS` and `skip_stt`).

    Sits directly before the LLM. Evaluates each new user `LLMContextFrame` using
    the user's transcript (if present), optional turn audio clip, and the
    assistant's last message. Opening greetings and tool-call follow-up turns
    pass straight through without classification.

    Concurrency & cancellation invariants:
    1. Each new uncommitted user message is popped from `LLMContext.messages`
       before any `await`, so Pipecat 1.16's `InterruptionFrame` task cancellation
       can never strand ignored background speech in `messages`.
    2. All evaluations commit strictly in FIFO arrival order via `_inflight_entries`,
       inserting approved messages *before* any newly appended uncommitted user
       messages (`_committed_msgs`) so history never reorders or re-classifies.
    3. Recovery of an interrupted addressed turn waits until the interrupting
       aggregator turn closes (`UserStoppedSpeakingFrame`, or `AGGREGATOR_SAFETY_SECS`
       if STT produced zero tokens and timed out), preventing double LLM replies.
    """

    POST_STOP_RECOVERY_SECS = 0.05
    AGGREGATOR_SAFETY_SECS = 5.2

    def __init__(
        self,
        evaluator: BackgroundSpeechEvaluator,
        *,
        get_recent_audio: Callable[[], tuple[bytes | None, int]] | None = None,
        get_current_utterance_id: Callable[[], int] | None = None,
        on_decision: Callable[[BackgroundSpeechDecision], None] | None = None,
        on_ignored_turn: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._evaluator = evaluator
        self._get_recent_audio = get_recent_audio
        self._get_current_utterance_id = get_current_utterance_id
        self._on_decision = on_decision
        self._on_ignored_turn = on_ignored_turn
        self._seen_user_speech = False
        self._turn_open_in_aggregator = False
        self._open_vad_snapshot: TurnSnapshot | None = None
        self._closed_turn_snapshots: deque[TurnSnapshot] = deque(maxlen=16)
        self._committed_msgs: deque[dict[str, Any]] = deque(maxlen=128)
        self._inflight_entries: list[_InflightCascadeTurn] = []
        self._commit_lock = asyncio.Lock()
        self._unanswered_addressed_turn = False
        self._last_addressed_context: Any = None
        self._recovery_task: asyncio.Task[None] | None = None
        self._bg_tasks: set[asyncio.Task[Any]] = set()

    async def setup(self, setup: FrameProcessorSetup) -> None:
        await super().setup(setup)
        await self._evaluator.setup(setup.task_manager)

    def _track_bg_task(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def _cancel_recovery_task(self) -> None:
        if self._recovery_task is not None and not self._recovery_task.done():
            self._recovery_task.cancel()
        self._recovery_task = None

    def _schedule_recovery(self, delay_secs: float, *, force_close_open_turn: bool = False) -> None:
        self._cancel_recovery_task()

        async def _runner() -> None:
            try:
                await asyncio.sleep(delay_secs)
                if force_close_open_turn:
                    self._turn_open_in_aggregator = False
                if (
                    self._unanswered_addressed_turn
                    and not self._inflight_entries
                    and not self._turn_open_in_aggregator
                    and self._last_addressed_context is not None
                ):
                    ctx = self._last_addressed_context
                    self._unanswered_addressed_turn = False
                    await self.push_frame(LLMContextFrame(context=ctx), FrameDirection.DOWNSTREAM)
            except asyncio.CancelledError:
                pass

        self._recovery_task = self._track_bg_task(asyncio.create_task(_runner()))

    async def cleanup(self) -> None:
        self._cancel_recovery_task()
        for task in list(self._bg_tasks):
            if not task.done():
                task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
            self._bg_tasks.clear()
        self._inflight_entries.clear()
        self._closed_turn_snapshots.clear()
        self._open_vad_snapshot = None
        await self._evaluator.cleanup()
        await super().cleanup()

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

    def _finish_ignored_turn(self, turn_origin: Any) -> None:
        if turn_origin is not None and hasattr(turn_origin, "finish"):
            try:
                turn_origin.finish("ignored")
                return
            except Exception:
                logger.exception("[CascadeBackgroundGate] turn_origin.finish('ignored') failed")
        if self._on_ignored_turn is not None:
            try:
                self._on_ignored_turn()
            except Exception:
                logger.exception("[CascadeBackgroundGate] on_ignored_turn callback failed")

    @staticmethod
    def _last_assistant_text(messages: list[Any]) -> str:
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                text = _extract_message_text(msg)
                if text:
                    return text
        return ""

    def _is_committed(self, msg: Any) -> bool:
        return isinstance(msg, dict) and any(existing is msg for existing in self._committed_msgs)

    def _mark_committed(self, msg: dict[str, Any]) -> None:
        if not self._is_committed(msg):
            self._committed_msgs.append(msg)

    def _insert_committed_message(self, messages: list[Any], msg: dict[str, Any]) -> None:
        """Insert `msg` before any trailing user message that has not been evaluated yet."""
        self._mark_committed(msg)
        insert_at = len(messages)
        while (
            insert_at > 0
            and isinstance(messages[insert_at - 1], dict)
            and messages[insert_at - 1].get("role") == "user"
            and not self._is_committed(messages[insert_at - 1])
        ):
            insert_at -= 1
        messages.insert(insert_at, msg)

    def _pop_earliest_uncommitted_user_msg(
        self, messages: list[Any]
    ) -> tuple[dict[str, Any], int]:
        """Pop the oldest uncommitted trailing user message and return `(msg, remaining_count)`."""
        first_uncommitted = len(messages) - 1
        while (
            first_uncommitted > 0
            and isinstance(messages[first_uncommitted - 1], dict)
            and messages[first_uncommitted - 1].get("role") == "user"
            and not self._is_committed(messages[first_uncommitted - 1])
        ):
            first_uncommitted -= 1
        candidate = messages.pop(first_uncommitted)
        remaining = len(messages) - first_uncommitted
        return candidate, max(0, remaining)

    def _sample_live_utterance_context(self) -> tuple[int | None, bytes | None, int]:
        utt_id: int | None = None
        if self._get_current_utterance_id is not None:
            try:
                raw_utt = int(self._get_current_utterance_id() or 0)
                if raw_utt > 0:
                    utt_id = raw_utt
            except Exception:
                utt_id = None
        audio_pcm: bytes | None = None
        sample_rate = 16000
        if self._get_recent_audio is not None:
            try:
                audio_pcm, sample_rate = self._get_recent_audio()
            except Exception:
                audio_pcm = None
        return (utt_id, audio_pcm, sample_rate)

    def _capture_vad_stop_snapshot(self, frame: Frame) -> None:
        origin = frame.metadata.get(ORIGIN_KEY)
        utt_id, audio_pcm, sample_rate = self._sample_live_utterance_context()
        if self._open_vad_snapshot is not None:
            prev_origin, prev_utt, prev_pcm, _ = self._open_vad_snapshot
            # Prefer the newest VAD segment's utterance_id & PCM so an earlier
            # empty-STT cough never stamps a subsequent spoken utterance with stale metadata.
            self._open_vad_snapshot = (
                origin or prev_origin,
                utt_id or prev_utt,
                audio_pcm if audio_pcm is not None else prev_pcm,
                sample_rate,
            )
        else:
            self._open_vad_snapshot = (origin, utt_id, audio_pcm, sample_rate)

    def _pop_turn_snapshot(self, frame: Frame, uncommitted_remaining: int = 0) -> TurnSnapshot:
        # Discard any orphan snapshots left behind by earlier empty-STT cough turns
        # that emitted `UserStoppedSpeakingFrame` without appending a user message.
        while len(self._closed_turn_snapshots) > uncommitted_remaining + 1:
            orphan_origin, _, _, _ = self._closed_turn_snapshots.popleft()
            self._finish_ignored_turn(orphan_origin)
        if self._closed_turn_snapshots:
            origin, utt_id, audio_pcm, sample_rate = self._closed_turn_snapshots.popleft()
            return (frame.metadata.get(ORIGIN_KEY) or origin, utt_id, audio_pcm, sample_rate)
        if self._open_vad_snapshot is not None:
            origin, utt_id, audio_pcm, sample_rate = self._open_vad_snapshot
            self._open_vad_snapshot = None
            return (frame.metadata.get(ORIGIN_KEY) or origin, utt_id, audio_pcm, sample_rate)
        utt_id, audio_pcm, sample_rate = self._sample_live_utterance_context()
        return (frame.metadata.get(ORIGIN_KEY), utt_id, audio_pcm, sample_rate)

    async def _drain_commits(self) -> None:
        """Commit completed evaluations strictly in FIFO arrival order."""
        async with self._commit_lock:
            while self._inflight_entries and self._inflight_entries[0].eval_task.done():
                head = self._inflight_entries.pop(0)
                try:
                    raw_decision = await head.eval_task
                    decision = raw_decision.with_utterance_id(head.utterance_id)
                except asyncio.CancelledError:
                    head.committed = True
                    head.should_respond = False
                    continue
                except Exception as exc:
                    logger.warning(
                        "[CascadeBackgroundGate] Unexpected evaluation error ({}); failing open.",
                        exc,
                    )
                    decision = BackgroundSpeechDecision(
                        should_respond=True,
                        addressed_probability=1.0,
                        background_probability=0.0,
                        latency_ms=0,
                        reason="fail_open_error",
                        transcript=head.user_text,
                        utterance_id=head.utterance_id,
                    )

                await self._emit_decision(decision)
                head.should_respond = decision.should_respond
                head.committed = True
                if decision.should_respond:
                    self._insert_committed_message(head.context.messages, head.message)
                    self._unanswered_addressed_turn = True
                    self._last_addressed_context = head.context
                else:
                    self._finish_ignored_turn(head.turn_origin)
                    logger.info(
                        "[CascadeBackgroundGate] Ignored background turn (p_bg={:.2f}, latency={}ms, text={!r}).",
                        decision.background_probability,
                        decision.latency_ms,
                        head.user_text[:80],
                    )

    async def _await_through(self, target: _InflightCascadeTurn) -> None:
        """Wait until `target` and all earlier queued turns have committed in order."""
        while not target.committed and target in self._inflight_entries:
            oldest = self._inflight_entries[0]
            if not oldest.eval_task.done():
                await asyncio.shield(oldest.eval_task)
            await self._drain_commits()

    async def _settle_cancelled_turn(self, entry: _InflightCascadeTurn) -> None:
        """Ensure an interrupted `process_frame` still commits in FIFO order."""
        try:
            await self._await_through(entry)
            if self._unanswered_addressed_turn and not self._inflight_entries:
                if self._turn_open_in_aggregator:
                    self._schedule_recovery(
                        self.AGGREGATOR_SAFETY_SECS, force_close_open_turn=True
                    )
                else:
                    self._schedule_recovery(self.POST_STOP_RECOVERY_SECS)
        except asyncio.CancelledError:
            pass

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if not self._evaluator.enabled or direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (EndFrame, CancelFrame)):
            self._cancel_recovery_task()
            for task in list(self._bg_tasks):
                if not task.done():
                    task.cancel()
            self._inflight_entries.clear()
            self._unanswered_addressed_turn = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, BotStartedSpeakingFrame):
            self._unanswered_addressed_turn = False
            self._cancel_recovery_task()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            self._turn_open_in_aggregator = True
            self._cancel_recovery_task()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, VADUserStoppedSpeakingFrame):
            self._seen_user_speech = True
            self._capture_vad_stop_snapshot(frame)
            await self.push_frame(frame, direction)
            if self._unanswered_addressed_turn and self._turn_open_in_aggregator:
                # Safety ceiling > Pipecat's 5.0s user_turn_stop_timeout in case an
                # empty-STT cough never triggers UserStoppedSpeakingFrame.
                self._schedule_recovery(self.AGGREGATOR_SAFETY_SECS, force_close_open_turn=True)
            return

        if isinstance(frame, UserStoppedSpeakingFrame):
            self._seen_user_speech = True
            self._turn_open_in_aggregator = False
            if self._open_vad_snapshot is not None:
                self._closed_turn_snapshots.append(self._open_vad_snapshot)
                self._open_vad_snapshot = None
            elif frame.metadata.get(ORIGIN_KEY) is not None:
                self._capture_vad_stop_snapshot(frame)
                if self._open_vad_snapshot is not None:
                    self._closed_turn_snapshots.append(self._open_vad_snapshot)
                    self._open_vad_snapshot = None
            await self.push_frame(frame, direction)
            if self._unanswered_addressed_turn and not self._inflight_entries:
                self._schedule_recovery(self.POST_STOP_RECOVERY_SECS)
            return

        if isinstance(frame, LLMContextFrame):
            self._cancel_recovery_task()
            context = getattr(frame, "context", None)
            messages = getattr(context, "messages", None)
            if not isinstance(messages, list) or not messages:
                await self.push_frame(frame, direction)
                return

            last_msg = messages[-1]
            if isinstance(last_msg, dict) and last_msg.get("role") == "developer":
                dev_text = _extract_message_text(last_msg)
                if "may have said something" in dev_text or "did not speak" in dev_text:
                    # Pipecat 1.16 empty-user-turn prompt after unrecognized noise/cough:
                    # drop the synthetic developer prompt, consume its cough snapshot so
                    # subsequent turns stay aligned, and only forward if a prior addressed
                    # user turn is still awaiting an answer.
                    messages.pop()
                    cough_origin, _, _, _ = self._pop_turn_snapshot(frame, uncommitted_remaining=0)
                    self._finish_ignored_turn(cough_origin)
                    if self._unanswered_addressed_turn and not self._inflight_entries:
                        self._unanswered_addressed_turn = False
                        await self.push_frame(frame, direction)
                    return

            if not isinstance(last_msg, dict) or last_msg.get("role") != "user":
                # Tool results, system updates, or assistant messages pass through untouched.
                await self.push_frame(frame, direction)
                return

            has_assistant_history = any(
                isinstance(m, dict) and m.get("role") == "assistant" for m in messages[:-1]
            )
            if not self._seen_user_speech and not has_assistant_history:
                # Opening greeting trigger from StartTriggerProcessor always passes through.
                self._mark_committed(last_msg)
                await self.push_frame(frame, direction)
                return

            if self._is_committed(last_msg):
                # Already evaluated and approved (e.g. recovery frame); forward directly.
                self._unanswered_addressed_turn = False
                await self.push_frame(frame, direction)
                return

            # Synchronously pop the earliest uncommitted user message BEFORE any await.
            candidate_msg, uncommitted_remaining = self._pop_earliest_uncommitted_user_msg(
                messages
            )
            self._turn_open_in_aggregator = False
            user_text = _extract_message_text(candidate_msg)
            last_bot = self._last_assistant_text(messages)
            turn_origin, utt_id, audio_pcm, sample_rate = self._pop_turn_snapshot(
                frame, uncommitted_remaining=uncommitted_remaining
            )

            eval_task = self._track_bg_task(
                asyncio.create_task(
                    self._evaluator.evaluate(
                        transcript=user_text,
                        audio_pcm=audio_pcm,
                        sample_rate=sample_rate,
                        last_bot_utterance=last_bot,
                    )
                )
            )
            entry = _InflightCascadeTurn(
                context=context,
                message=candidate_msg,
                user_text=user_text,
                utterance_id=utt_id,
                turn_origin=turn_origin,
                eval_task=eval_task,
            )
            self._inflight_entries.append(entry)

            try:
                await self._await_through(entry)
            except asyncio.CancelledError:
                self._track_bg_task(asyncio.create_task(self._settle_cancelled_turn(entry)))
                raise

            if entry.should_respond or (
                self._unanswered_addressed_turn and not self._inflight_entries
            ):
                self._unanswered_addressed_turn = False
                await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)
