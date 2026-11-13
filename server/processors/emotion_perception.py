"""Non-blocking user vocal emotion perception powered by Pipecat 1.16 Decisions.

Streams short slices of caller microphone audio to Google's ``gemini-decision-1``
classifier (`GoogleDecisionsClassifier`) out-of-band so neither Gemini Live nor
Cascade incurs any Time-To-First-Byte (TTFB) penalty. Emits ``user_emotion``
RTVI server messages both while the caller is speaking (interim prosody reads)
and when an utterance finishes (final turn badge).
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

from loguru import logger
import numpy as np

from pipecat.classifiers.base_classifier import (
    BaseClassifier,
    ChoiceQuestion,
    ChoiceResult,
    ClassifierAudio,
    ClassifierError,
)
from pipecat.classifiers.google.decisions.classifier import GoogleDecisionsClassifier
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserMuteStartedFrame,
    UserMuteStoppedFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import (
    FrameDirection,
    FrameProcessor,
    FrameProcessorSetup,
)


DEFAULT_DECISION_MODEL = "gemini-decision-1"
DEFAULT_TIMEOUT_SECS = 4.0
MIN_INTERIM_SECS = 1.2
INTERIM_INTERVAL_SECS = 1.6
INTERIM_WINDOW_SECS = 2.5
MIN_FINAL_SECS = 0.45
FINAL_WINDOW_SECS = 4.5
MAX_BUFFER_SECS = 6.0
MIN_CONFIDENCE_FOR_NON_CALM = 0.35

# Fallback energy-gate thresholds when local Silero VAD is disabled (e.g. Gemini Live native VAD).
RMS_SPEECH_ONSET = 0.016
RMS_BARGE_IN_ONSET = 0.036
RMS_SILENCE_FLOOR = 0.010
ONSET_HOLD_SECS = 0.16
SILENCE_STOP_SECS = 0.48


@dataclass(frozen=True)
class EmotionDescriptor:
    """Display metadata for a classified caller vocal emotion."""

    key: str
    emoji: str
    title: str
    description: str


EMOTION_TAXONOMY: tuple[EmotionDescriptor, ...] = (
    EmotionDescriptor(
        key="calm",
        emoji="\U0001f60c",
        title="Calm",
        description="Neutral, composed, steady, or matter-of-fact delivery.",
    ),
    EmotionDescriptor(
        key="happy",
        emoji="\U0001f60a",
        title="Warm",
        description="Warm, friendly, cheerful, pleased, or smiling tone.",
    ),
    EmotionDescriptor(
        key="excited",
        emoji="\U0001f929",
        title="Excited",
        description="Energetic, enthusiastic, upbeat, or eager delivery.",
    ),
    EmotionDescriptor(
        key="curious",
        emoji="\U0001f914",
        title="Curious",
        description="Inquisitive, thoughtful, engaged, or questioning tone.",
    ),
    EmotionDescriptor(
        key="hesitant",
        emoji="\U0001f61f",
        title="Hesitant",
        description="Unsure, nervous, tentative, stalling, or doubtful tone.",
    ),
    EmotionDescriptor(
        key="frustrated",
        emoji="\U0001f624",
        title="Frustrated",
        description="Annoyed, impatient, exasperated, stressed, or irritated.",
    ),
    EmotionDescriptor(
        key="angry",
        emoji="\U0001f620",
        title="Angry",
        description="Hostile, sharp, raised voice, or confrontational.",
    ),
    EmotionDescriptor(
        key="sad",
        emoji="\U0001f614",
        title="Sad",
        description="Downcast, disappointed, tired, heavy, or dejected.",
    ),
    EmotionDescriptor(
        key="sarcastic",
        emoji="\U0001f643",
        title="Sarcastic",
        description="Dry, ironic, mocking, or skeptical prosody.",
    ),
)

EMOTION_BY_KEY: dict[str, EmotionDescriptor] = {
    item.key: item for item in EMOTION_TAXONOMY
}

EMOTION_QUESTION = ChoiceQuestion(
    instructions=(
        "Listen to the speaker's vocal tone, pitch, pace, sighs, laughter, "
        "and prosody in the audio clip (not just the literal words) and "
        "choose the single best label for how they sound right now."
    ),
    options={item.key: item.description for item in EMOTION_TAXONOMY},
)


def compute_pcm16_rms(pcm_bytes: bytes) -> float:
    """Return normalized [0.0, 1.0] RMS amplitude for 16-bit signed PCM bytes."""
    sample_count = len(pcm_bytes) // 2
    if sample_count == 0:
        return 0.0
    samples = np.frombuffer(pcm_bytes[: sample_count * 2], dtype=np.int16).astype(
        np.float32
    )
    mean_square = float(np.mean(samples * samples))
    return min(1.0, (mean_square**0.5) / 32768.0)


class AudioEmotionObserver(FrameProcessor):
    """Out-of-band pipeline tap that classifies caller vocal emotion from PCM audio.

    Forwards every frame immediately with zero buffering delay, while sampling
    active caller speech segments in background tasks via ``GoogleDecisionsClassifier``.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        session_id: str | None = None,
        api_key: str | None = None,
        model: str = DEFAULT_DECISION_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECS,
        classifier: BaseClassifier | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._session_id = session_id or ""
        self._sample_rate = 16000
        self._owns_classifier = False
        self._classifier: BaseClassifier | None = None

        resolved_key = (
            api_key
            if api_key is not None
            else (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "")
        ).strip()

        if enabled:
            if classifier is not None:
                self._classifier = classifier
            elif resolved_key:
                self._classifier = GoogleDecisionsClassifier(
                    api_key=resolved_key,
                    model=model,
                    timeout=timeout,
                )
                self._owns_classifier = True

        self._usable = self._classifier is not None
        self._muted = False
        self._bot_speaking = False
        self._has_external_vad = False
        self._speaking = False
        self._onset_secs = 0.0
        self._silence_secs = 0.0
        self._pre_roll = bytearray()
        self._speech_buffer = bytearray()
        self._last_interim_at = 0.0
        self._interim_in_flight = False
        self._utterance_id = 0
        self._request_seq = 0
        self._latest_emitted_seq = 0
        self._prev_input_tokens = 0
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def is_usable(self) -> bool:
        """Whether an active Decisions classifier is configured for this session."""
        return self._usable

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Initialize sample rate and warm the Decisions HTTP/2 client."""
        await super().setup(setup)
        if getattr(setup, "audio_in_sample_rate", 0):
            self._sample_rate = int(setup.audio_in_sample_rate)
        if self._classifier is not None:
            try:
                await self._classifier.setup(self.task_manager)
            except Exception as exc:
                logger.warning("[EmotionPerception] Classifier setup warning: {}", exc)

    async def cleanup(self) -> None:
        """Cancel pending background reads and close owned classifier client."""
        await self._cancel_pending_tasks()
        if self._owns_classifier and self._classifier is not None:
            try:
                await self._classifier.cleanup()
            except Exception as exc:
                logger.debug("[EmotionPerception] Classifier cleanup note: {}", exc)
        await super().cleanup()

    async def _cancel_pending_tasks(self) -> None:
        pending = list(self._tasks)
        self._tasks.clear()
        self._interim_in_flight = False
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Observe audio and VAD frames without delaying downstream frame flow."""
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (EndFrame, CancelFrame)):
            await self._cancel_pending_tasks()
            await self.push_frame(frame, direction)
            return

        if not self._usable:
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserMuteStartedFrame):
            self._muted = True
            self._reset_speech_state()
            await self._cancel_pending_tasks()
        elif isinstance(frame, UserMuteStoppedFrame):
            self._muted = False
        elif isinstance(frame, (BotStartedSpeakingFrame, TTSStartedFrame)):
            self._bot_speaking = True
        elif isinstance(frame, (BotStoppedSpeakingFrame, TTSStoppedFrame)):
            self._bot_speaking = False
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            self._has_external_vad = True
            self._begin_utterance()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._has_external_vad = True
            self._finish_utterance(trim_tail_secs=getattr(frame, "stop_secs", 0.0))
        elif isinstance(frame, InputAudioRawFrame) and not self._muted:
            self._observe_audio_chunk(frame)

        await self.push_frame(frame, direction)

    def _bytes_for_secs(self, secs: float, sample_rate: int | None = None) -> int:
        rate = sample_rate or self._sample_rate or 16000
        even_bytes = int(round(secs * rate * 2))
        return even_bytes - (even_bytes % 2)

    def _reset_speech_state(self) -> None:
        self._speaking = False
        self._onset_secs = 0.0
        self._silence_secs = 0.0
        self._speech_buffer.clear()
        self._pre_roll.clear()

    def _begin_utterance(self) -> None:
        self._utterance_id += 1
        self._speaking = True
        self._onset_secs = 0.0
        self._silence_secs = 0.0
        self._speech_buffer = bytearray(self._pre_roll)
        self._pre_roll.clear()
        self._last_interim_at = time.monotonic()

    def _finish_utterance(self, trim_tail_secs: float = 0.0) -> None:
        if not self._speaking:
            return
        self._speaking = False
        self._onset_secs = 0.0
        self._silence_secs = 0.0
        raw = bytes(self._speech_buffer)
        self._speech_buffer.clear()

        trim_bytes = self._bytes_for_secs(max(0.0, trim_tail_secs))
        if 0 < trim_bytes < len(raw):
            raw = raw[:-trim_bytes]

        min_bytes = self._bytes_for_secs(MIN_FINAL_SECS)
        if len(raw) < min_bytes:
            return

        window_bytes = self._bytes_for_secs(FINAL_WINDOW_SECS)
        clip = raw[-window_bytes:] if len(raw) > window_bytes else raw
        self._spawn_classification(
            clip,
            sample_rate=self._sample_rate,
            interim=False,
            utterance_id=self._utterance_id,
        )

    def _append_bounded_speech(self, pcm: bytes) -> None:
        self._speech_buffer.extend(pcm)
        max_bytes = self._bytes_for_secs(MAX_BUFFER_SECS)
        if len(self._speech_buffer) > max_bytes:
            del self._speech_buffer[: len(self._speech_buffer) - max_bytes]

    def _observe_audio_chunk(self, frame: InputAudioRawFrame) -> None:
        pcm = frame.audio
        if not pcm:
            return
        frame_rate = int(getattr(frame, "sample_rate", 0) or self._sample_rate or 16000)
        channels = int(getattr(frame, "num_channels", 1) or 1)
        if channels > 1:
            samples = np.frombuffer(pcm[: len(pcm) - (len(pcm) % (2 * channels))], dtype=np.int16)
            pcm = samples[::channels].tobytes()
        self._sample_rate = frame_rate
        chunk_secs = len(pcm) / float(2 * frame_rate)

        if not self._speaking:
            self._pre_roll.extend(pcm)
            pre_roll_max = self._bytes_for_secs(0.30, frame_rate)
            if len(self._pre_roll) > pre_roll_max:
                del self._pre_roll[: len(self._pre_roll) - pre_roll_max]

        if not self._has_external_vad:
            rms = compute_pcm16_rms(pcm)
            onset_threshold = (
                RMS_BARGE_IN_ONSET if self._bot_speaking else RMS_SPEECH_ONSET
            )
            if not self._speaking:
                if rms >= onset_threshold:
                    self._onset_secs += chunk_secs
                    if self._onset_secs >= ONSET_HOLD_SECS:
                        self._begin_utterance()
                        self._append_bounded_speech(pcm)
                else:
                    self._onset_secs = 0.0
                return

            self._append_bounded_speech(pcm)
            if rms < RMS_SILENCE_FLOOR:
                self._silence_secs += chunk_secs
                if self._silence_secs >= SILENCE_STOP_SECS:
                    self._finish_utterance(trim_tail_secs=self._silence_secs * 0.7)
                    return
            else:
                self._silence_secs = 0.0
        elif self._speaking:
            self._append_bounded_speech(pcm)
        else:
            return

        now = time.monotonic()
        buffered_secs = len(self._speech_buffer) / float(2 * frame_rate)
        if (
            not self._interim_in_flight
            and buffered_secs >= MIN_INTERIM_SECS
            and (now - self._last_interim_at) >= INTERIM_INTERVAL_SECS
        ):
            self._last_interim_at = now
            window_bytes = self._bytes_for_secs(INTERIM_WINDOW_SECS, frame_rate)
            clip = bytes(self._speech_buffer[-window_bytes:])
            self._interim_in_flight = True
            self._spawn_classification(
                clip,
                sample_rate=frame_rate,
                interim=True,
                utterance_id=self._utterance_id,
            )

    def _spawn_classification(
        self,
        pcm_bytes: bytes,
        *,
        sample_rate: int,
        interim: bool,
        utterance_id: int,
    ) -> None:
        if self._classifier is None:
            self._interim_in_flight = False
            return
        self._request_seq += 1
        seq = self._request_seq
        task = asyncio.create_task(
            self._run_classification(
                pcm_bytes=pcm_bytes,
                sample_rate=sample_rate,
                interim=interim,
                utterance_id=utterance_id,
                seq=seq,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _read_delta_input_tokens(self) -> int:
        client = getattr(self._classifier, "client", None)
        usage = getattr(client, "usage", None)
        total_in = int(getattr(usage, "input_tokens", 0) or 0)
        delta = max(0, total_in - self._prev_input_tokens)
        self._prev_input_tokens = total_in
        return delta

    async def _run_classification(
        self,
        *,
        pcm_bytes: bytes,
        sample_rate: int,
        interim: bool,
        utterance_id: int,
        seq: int,
    ) -> None:
        started = time.perf_counter()
        try:
            if self._classifier is None:
                return
            audio_input = ClassifierAudio(audio=pcm_bytes, sample_rate=sample_rate)
            answers = await self._classifier.choice(
                state={"speaker": "caller"},
                questions={"emotion": EMOTION_QUESTION},
                inputs=[audio_input],
            )
            emotion_answer: ChoiceResult | None = answers.get("emotion")
            if emotion_answer is None:
                return

            if seq < self._latest_emitted_seq:
                return
            if interim and utterance_id != self._utterance_id:
                return

            raw_choice = str(emotion_answer.choice or "calm").strip().lower()
            confidence = float(emotion_answer.confidence or 0.0)
            if raw_choice not in EMOTION_BY_KEY or (
                raw_choice != "calm" and confidence < MIN_CONFIDENCE_FOR_NON_CALM
            ):
                raw_choice = "calm"

            descriptor = EMOTION_BY_KEY[raw_choice]
            latency_ms = int(round((time.perf_counter() - started) * 1000))
            input_tokens = self._read_delta_input_tokens()
            self._latest_emitted_seq = seq

            logger.debug(
                "[EmotionPerception] session={} emotion={} ({:.0%}) interim={} latency={}ms in_tok={}",
                self._session_id or "-",
                descriptor.key,
                confidence,
                interim,
                latency_ms,
                input_tokens,
            )
            payload = {
                "type": "user_emotion",
                "session_id": self._session_id,
                "utterance_id": utterance_id,
                "seq": seq,
                "emotion": descriptor.key,
                "emoji": descriptor.emoji,
                "title": descriptor.title,
                "confidence": round(max(0.0, min(1.0, confidence)), 3),
                "interim": interim,
                "latency_ms": latency_ms,
                "input_tokens": input_tokens,
                "model": self._classifier.model or DEFAULT_DECISION_MODEL,
            }
            await self.push_frame(
                OutputTransportMessageUrgentFrame(
                    message={
                        "label": "rtvi-ai",
                        "type": "server-message",
                        "data": payload,
                    }
                )
            )
        except asyncio.CancelledError:
            raise
        except ClassifierError as exc:
            logger.debug("[EmotionPerception] Classifier skipped clip: {}", exc)
        except Exception as exc:
            logger.warning("[EmotionPerception] Unexpected error: {}", exc)
        finally:
            if interim:
                self._interim_in_flight = False
