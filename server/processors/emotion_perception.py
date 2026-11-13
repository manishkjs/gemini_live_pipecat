"""Non-blocking user vocal emotion perception powered by Pipecat 1.16 Decisions.

Streams short slices of caller microphone audio to Google's ``gemini-decision-1``
classifier (`GoogleDecisionsClassifier`) out-of-band so neither Gemini Live nor
Cascade incurs any Time-To-First-Byte (TTFB) or session-startup penalty. Emits
``user_emotion`` RTVI server messages both while the caller is speaking (interim
prosody reads) and when an utterance finishes (final turn badge).
"""

from __future__ import annotations

import asyncio
from collections import deque
import os
import time
from dataclasses import dataclass
from typing import Any, Coroutine

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
PRE_ROLL_SECS = 0.30
MIN_CONFIDENCE_FOR_NON_CALM = 0.35
MAX_CONCURRENT_CLASSIFICATIONS = 2
MAX_CONSECUTIVE_FAILURES = 3

# Fallback energy-gate thresholds when local Silero VAD is disabled (e.g. Gemini Live native VAD).
RMS_SPEECH_ONSET = 0.016
RMS_BARGE_IN_ONSET = 0.036
RMS_SILENCE_FLOOR = 0.010
ONSET_HOLD_SECS = 0.16
SILENCE_STOP_SECS = 0.48
NEW_ONSET_TRANSCRIPT_GRACE_SECS = 0.70
SECRET_MANAGER_EMPTY_TTL_SECS = 60.0
SECRET_MANAGER_RPC_TIMEOUT_SECS = 2.0

_SECRET_MANAGER_CACHE: dict[str, tuple[str, float | None]] = {}
_IN_FLIGHT_KEY_LOOKUPS: dict[str, asyncio.Task[str]] = {}


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


def _get_cached_secret_key(target_project: str) -> str | None:
    """Return cached Secret Manager key if present and unexpired, else None."""
    cached = _SECRET_MANAGER_CACHE.get(target_project)
    if cached is not None:
        cached_val, expires_at = cached
        if expires_at is None or time.monotonic() < expires_at:
            return cached_val
    return None


def _fetch_secret_manager_key(target_project: str) -> str:
    """Bounded blocking Secret Manager RPC helper; callers on an event loop use resolve_decision_api_key_async."""
    cached_val = _get_cached_secret_key(target_project)
    if cached_val is not None:
        return cached_val

    resolved = ""
    try:
        from google.cloud import secretmanager

        sm_client = secretmanager.SecretManagerServiceClient()
        sm_name = f"projects/{target_project}/secrets/GEMINI_API_KEY/versions/latest"
        sm_res = sm_client.access_secret_version(
            request={"name": sm_name},
            timeout=SECRET_MANAGER_RPC_TIMEOUT_SECS,
            retry=None,
        )
        resolved = sm_res.payload.data.decode("UTF-8").strip()
        if resolved:
            logger.info(
                "[EmotionPerception] Retrieved GEMINI_API_KEY from Secret Manager for project {}.",
                target_project,
            )
    except Exception as sm_err:
        logger.debug(
            "[EmotionPerception] Secret Manager GEMINI_API_KEY lookup skipped: {}",
            sm_err,
        )

    expires = None if resolved else (time.monotonic() + SECRET_MANAGER_EMPTY_TTL_SECS)
    _SECRET_MANAGER_CACHE[target_project] = (resolved, expires)
    return resolved


async def _run_deduped_secret_lookup(target_project: str) -> str:
    return await asyncio.to_thread(_fetch_secret_manager_key, target_project)


async def resolve_decision_api_key_async(project_id: str | None = None) -> str:
    """Bounded, deduplicated, non-blocking Secret Manager resolver."""
    env_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if env_key:
        return env_key

    target_project = (
        project_id
        or os.getenv("GCP_PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or ""
    ).strip()
    if not target_project:
        return ""

    cached_val = _get_cached_secret_key(target_project)
    if cached_val is not None:
        return cached_val

    in_flight = _IN_FLIGHT_KEY_LOOKUPS.get(target_project)
    if in_flight is None:
        in_flight = asyncio.create_task(_run_deduped_secret_lookup(target_project))
        _IN_FLIGHT_KEY_LOOKUPS[target_project] = in_flight
        in_flight.add_done_callback(
            lambda _t, proj=target_project: _IN_FLIGHT_KEY_LOOKUPS.pop(proj, None)
        )
    return await asyncio.shield(in_flight)


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


class _BoundedPcmRing:
    """Chunk-based O(1) bounded PCM byte ring avoiding O(N) bytearray front-deletes."""

    def __init__(self) -> None:
        self._chunks: deque[bytes] = deque()
        self._byte_len = 0

    def __len__(self) -> int:
        return self._byte_len

    def clear(self) -> None:
        self._chunks.clear()
        self._byte_len = 0

    def append(self, pcm: bytes, max_bytes: int) -> None:
        if not pcm or max_bytes <= 0:
            if max_bytes <= 0:
                self.clear()
            return
        if len(pcm) >= max_bytes:
            self._chunks.clear()
            tail = pcm[-max_bytes:]
            self._chunks.append(tail)
            self._byte_len = len(tail)
            return
        self._chunks.append(pcm)
        self._byte_len += len(pcm)
        while self._byte_len > max_bytes and self._chunks:
            excess = self._byte_len - max_bytes
            head = self._chunks[0]
            if len(head) <= excess:
                self._chunks.popleft()
                self._byte_len -= len(head)
            else:
                self._chunks[0] = head[excess:]
                self._byte_len -= excess
                break

    def copy_from(self, other: _BoundedPcmRing, max_bytes: int) -> None:
        self.clear()
        for chunk in other._chunks:
            self.append(chunk, max_bytes)

    def to_bytes(self) -> bytes:
        return b"".join(self._chunks)

    def tail_bytes(self, max_bytes: int) -> bytes:
        if max_bytes <= 0 or self._byte_len == 0:
            return b""
        if max_bytes >= self._byte_len:
            return self.to_bytes()
        collected: list[bytes] = []
        remaining = max_bytes
        for chunk in reversed(self._chunks):
            if len(chunk) <= remaining:
                collected.append(chunk)
                remaining -= len(chunk)
                if remaining == 0:
                    break
            else:
                collected.append(chunk[-remaining:])
                break
        collected.reverse()
        return b"".join(collected)


class AudioEmotionObserver(FrameProcessor):
    """Out-of-band pipeline tap that classifies caller vocal emotion from PCM audio.

    Forwards every frame immediately with zero buffering or startup delay, while
    sampling active caller speech segments in background tasks via
    ``GoogleDecisionsClassifier``.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        session_id: str | None = None,
        api_key: str | None = None,
        project_id: str | None = None,
        model: str = DEFAULT_DECISION_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECS,
        classifier: BaseClassifier | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._session_id = session_id or ""
        self._sample_rate = 16000
        self._model_name = model
        self._timeout_secs = timeout
        self._owns_classifier = False
        self._classifier: BaseClassifier | None = None
        self._deferred_project_id = ""
        self._key_ready = asyncio.Event()
        self._key_ready.set()

        if enabled:
            if classifier is not None:
                self._classifier = classifier
            elif api_key is not None:
                resolved_key = api_key.strip()
                if resolved_key:
                    self._classifier = GoogleDecisionsClassifier(
                        api_key=resolved_key,
                        model=model,
                        timeout=timeout,
                    )
                    self._owns_classifier = True
                else:
                    logger.warning(
                        "[EmotionPerception] Caller emotion perception enabled (session={}), "
                        "but no GEMINI_API_KEY / GOOGLE_API_KEY was available; disabling observer.",
                        self._session_id or "-",
                    )
            else:
                env_key = (
                    os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
                ).strip()
                target_project = (
                    project_id
                    or os.getenv("GCP_PROJECT_ID")
                    or os.getenv("GOOGLE_CLOUD_PROJECT")
                    or ""
                ).strip()
                cached_key = (
                    _get_cached_secret_key(target_project) if (not env_key and target_project) else None
                )
                immediate_key = env_key or (cached_key or "")
                if immediate_key:
                    self._classifier = GoogleDecisionsClassifier(
                        api_key=immediate_key,
                        model=model,
                        timeout=timeout,
                    )
                    self._owns_classifier = True
                elif target_project and cached_key is None:
                    # Resolve Secret Manager lazily in _warm_classifier so call setup never waits.
                    self._deferred_project_id = target_project
                    self._key_ready.clear()
                else:
                    logger.warning(
                        "[EmotionPerception] Caller emotion perception enabled (session={}), "
                        "but no GEMINI_API_KEY / GOOGLE_API_KEY was available; disabling observer.",
                        self._session_id or "-",
                    )

        self._usable = self._classifier is not None or bool(self._deferred_project_id)
        self._is_setup = False
        self._muted = False
        self._bot_speaking = False
        self._has_external_vad = False
        self._speaking = False
        self._onset_secs = 0.0
        self._silence_secs = 0.0
        self._pre_roll = _BoundedPcmRing()
        self._speech_buffer = _BoundedPcmRing()
        self._last_interim_at = 0.0
        self._interim_in_flight = False
        self._utterance_id = 0
        self._utterance_started_at = 0.0
        self._utterance_has_interim = False
        self._last_completed_utterance_id = 0
        self._request_seq = 0
        self._latest_emitted_seq = 0
        self._prev_client_in_tokens = 0
        self._prev_client_out_tokens = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._consecutive_failures = 0
        self._concurrency_sem = asyncio.Semaphore(MAX_CONCURRENT_CLASSIFICATIONS)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._interim_tasks: set[asyncio.Task[Any]] = set()

    @property
    def is_usable(self) -> bool:
        """Whether an active Decisions classifier is configured for this session."""
        return self._usable

    @property
    def current_utterance_id(self) -> int:
        """Monotonic 1-based counter of caller utterances observed in this session."""
        return self._utterance_id

    @property
    def transcript_utterance_id(self) -> int:
        """Utterance ID to stamp onto an outgoing caller transcript.

        When a cough or fresh speech onset began within NEW_ONSET_TRANSCRIPT_GRACE_SECS
        and has not yet emitted an interim read, prefer the just-completed utterance ID
        so Turn N's slightly delayed STT transcript is not stamped N+1.
        """
        if (
            self._speaking
            and self._last_completed_utterance_id > 0
            and not self._utterance_has_interim
            and (time.monotonic() - self._utterance_started_at)
            < NEW_ONSET_TRANSCRIPT_GRACE_SECS
        ):
            return self._last_completed_utterance_id
        return self._utterance_id

    def _spawn_background_task(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str,
        interim: bool = False,
    ) -> asyncio.Task[Any]:
        if self._is_setup and getattr(self, "_task_manager", None) is not None:
            task = self.create_task(coro, name=name)
        else:
            task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        if interim:
            self._interim_tasks.add(task)
            task.add_done_callback(self._interim_tasks.discard)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _warm_classifier(self) -> None:
        """Resolve deferred Secret Manager key and warm HTTP/2 connection in background."""
        try:
            if self._classifier is None and self._deferred_project_id:
                try:
                    resolved_key = await resolve_decision_api_key_async(
                        self._deferred_project_id
                    )
                    if resolved_key:
                        self._classifier = GoogleDecisionsClassifier(
                            api_key=resolved_key,
                            model=self._model_name,
                            timeout=self._timeout_secs,
                        )
                        self._owns_classifier = True
                    else:
                        self._usable = False
                        logger.warning(
                            "[EmotionPerception] Caller emotion perception enabled (session={}), "
                            "but no GEMINI_API_KEY / GOOGLE_API_KEY was available; disabling observer.",
                            self._session_id or "-",
                        )
                finally:
                    self._deferred_project_id = ""
                    self._key_ready.set()

            if self._classifier is not None:
                await self._classifier.setup(self.task_manager)
        except asyncio.CancelledError:
            self._key_ready.set()
            raise
        except Exception as exc:
            logger.warning("[EmotionPerception] Classifier background warmup warning: {}", exc)

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Initialize sample rate and start non-blocking classifier warmup."""
        await super().setup(setup)
        self._is_setup = True
        if getattr(setup, "audio_in_sample_rate", 0):
            self._sample_rate = int(setup.audio_in_sample_rate)
        if self._classifier is not None or self._deferred_project_id:
            self._spawn_background_task(
                self._warm_classifier(),
                name="emotion_warm",
                interim=False,
            )

    async def cleanup(self) -> None:
        """Cancel pending background reads and close owned classifier client."""
        await self._cancel_pending_tasks()
        if self._owns_classifier and self._classifier is not None:
            try:
                await self._classifier.cleanup()
            except Exception as exc:
                logger.debug("[EmotionPerception] Classifier cleanup note: {}", exc)
        self._is_setup = False
        await super().cleanup()

    async def _cancel_interim_tasks(self) -> None:
        pending_interims = list(self._interim_tasks)
        self._interim_tasks.clear()
        self._interim_in_flight = False
        for task in pending_interims:
            self._tasks.discard(task)
            if not task.done():
                task.cancel()
        if pending_interims:
            await asyncio.gather(*pending_interims, return_exceptions=True)

    async def _cancel_pending_tasks(self) -> None:
        pending = list(self._tasks)
        self._tasks.clear()
        self._interim_tasks.clear()
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
            await self._cancel_interim_tasks()
        elif isinstance(frame, UserMuteStoppedFrame):
            self._muted = False
        elif isinstance(frame, (BotStartedSpeakingFrame, TTSStartedFrame)):
            self._bot_speaking = True
        elif isinstance(frame, (BotStoppedSpeakingFrame, TTSStoppedFrame)):
            self._bot_speaking = False
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            if not self._muted:
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
        now = time.monotonic()
        self._utterance_id += 1
        self._utterance_started_at = now
        self._utterance_has_interim = False
        self._speaking = True
        self._onset_secs = 0.0
        self._silence_secs = 0.0
        self._speech_buffer.copy_from(
            self._pre_roll, self._bytes_for_secs(MAX_BUFFER_SECS)
        )
        self._pre_roll.clear()
        self._last_interim_at = now

    def _finish_utterance(self, trim_tail_secs: float = 0.0) -> None:
        if not self._speaking:
            return
        self._speaking = False
        self._onset_secs = 0.0
        self._silence_secs = 0.0
        raw = self._speech_buffer.to_bytes()
        self._speech_buffer.clear()

        trim_bytes = self._bytes_for_secs(max(0.0, trim_tail_secs))
        if 0 < trim_bytes < len(raw):
            raw = raw[:-trim_bytes]

        min_bytes = self._bytes_for_secs(MIN_FINAL_SECS)
        if len(raw) < min_bytes:
            return

        self._last_completed_utterance_id = self._utterance_id
        window_bytes = self._bytes_for_secs(FINAL_WINDOW_SECS)
        clip = raw[-window_bytes:] if len(raw) > window_bytes else raw
        self._spawn_classification(
            clip,
            sample_rate=self._sample_rate,
            interim=False,
            utterance_id=self._utterance_id,
        )

    def _append_bounded_speech(self, pcm: bytes) -> None:
        self._speech_buffer.append(pcm, self._bytes_for_secs(MAX_BUFFER_SECS))

    def _observe_audio_chunk(self, frame: InputAudioRawFrame) -> None:
        pcm = frame.audio
        if not pcm:
            return
        frame_rate = int(getattr(frame, "sample_rate", 0) or self._sample_rate or 16000)
        channels = int(getattr(frame, "num_channels", 1) or 1)
        if channels > 1:
            samples = np.frombuffer(
                pcm[: len(pcm) - (len(pcm) % (2 * channels))], dtype=np.int16
            )
            pcm = samples[::channels].tobytes()
        if frame_rate != self._sample_rate:
            self._pre_roll.clear()
            self._speech_buffer.clear()
        self._sample_rate = frame_rate
        chunk_secs = len(pcm) / float(2 * frame_rate)

        if not self._has_external_vad:
            rms = compute_pcm16_rms(pcm)
            onset_threshold = (
                RMS_BARGE_IN_ONSET if self._bot_speaking else RMS_SPEECH_ONSET
            )
            if not self._speaking:
                if not self._bot_speaking or rms >= onset_threshold:
                    self._pre_roll.append(pcm, self._bytes_for_secs(PRE_ROLL_SECS, frame_rate))
                if rms >= onset_threshold:
                    self._onset_secs += chunk_secs
                    if self._onset_secs >= ONSET_HOLD_SECS:
                        # _pre_roll already contains `pcm` appended above; do not double-append.
                        self._begin_utterance()
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
            self._pre_roll.append(pcm, self._bytes_for_secs(PRE_ROLL_SECS, frame_rate))
            return

        now = time.monotonic()
        buffered_secs = len(self._speech_buffer) / float(2 * frame_rate)
        if (
            not self._interim_in_flight
            and buffered_secs >= MIN_INTERIM_SECS
            and (now - self._last_interim_at) >= INTERIM_INTERVAL_SECS
        ):
            self._last_interim_at = now
            self._utterance_has_interim = True
            window_bytes = self._bytes_for_secs(INTERIM_WINDOW_SECS, frame_rate)
            clip = self._speech_buffer.tail_bytes(window_bytes)
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
        if not self._usable or (self._classifier is None and not self._deferred_project_id):
            self._interim_in_flight = False
            return
        self._request_seq += 1
        seq = self._request_seq
        self._spawn_background_task(
            self._run_classification(
                pcm_bytes=pcm_bytes,
                sample_rate=sample_rate,
                interim=interim,
                utterance_id=utterance_id,
                seq=seq,
            ),
            name=f"emotion_{'interim' if interim else 'final'}_{seq}",
            interim=interim,
        )

    def _consume_call_tokens(self) -> tuple[int, int]:
        """Consume cumulative client.usage deltas and update exact session token totals."""
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
        return in_tok, out_tok

    def _record_classifier_failure(self, exc: Exception) -> None:
        self._consecutive_failures += 1
        msg = str(exc).lower()
        permanent_auth = any(
            marker in msg
            for marker in ("api_key_invalid", "api key not valid", "401", "403", "permission_denied")
        )
        if permanent_auth or self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self._usable = False
            logger.warning(
                "[EmotionPerception] Disabling caller emotion observer for session={} "
                "after {} failure(s): {}",
                self._session_id or "-",
                self._consecutive_failures,
                exc,
            )
        else:
            logger.debug("[EmotionPerception] Classifier skipped clip: {}", exc)

    async def _run_classification(
        self,
        *,
        pcm_bytes: bytes,
        sample_rate: int,
        interim: bool,
        utterance_id: int,
        seq: int,
    ) -> None:
        try:
            if not self._key_ready.is_set():
                await self._key_ready.wait()
            if self._classifier is None or not self._usable:
                return
            started = time.perf_counter()
            async with self._concurrency_sem:
                if self._classifier is None or not self._usable:
                    return
                audio_input = ClassifierAudio(audio=pcm_bytes, sample_rate=sample_rate)
                answers = await self._classifier.choice(
                    state={"speaker": "caller"},
                    questions={"emotion": EMOTION_QUESTION},
                    inputs=[audio_input],
                )
                input_tokens, output_tokens = self._consume_call_tokens()

            self._consecutive_failures = 0
            emotion_answer: ChoiceResult | None = answers.get("emotion")
            if emotion_answer is None:
                return

            # Only interim reads can become stale; final reads belong to their own
            # completed utterance_id and must never be dropped by a newer turn's interim.
            if interim and (
                utterance_id != self._utterance_id or seq < self._latest_emitted_seq
            ):
                return

            raw_choice = str(emotion_answer.choice or "calm").strip().lower()
            confidence = float(emotion_answer.confidence or 0.0)
            if raw_choice not in EMOTION_BY_KEY or (
                raw_choice != "calm" and confidence < MIN_CONFIDENCE_FOR_NON_CALM
            ):
                raw_choice = "calm"

            descriptor = EMOTION_BY_KEY[raw_choice]
            latency_ms = int(round((time.perf_counter() - started) * 1000))
            self._latest_emitted_seq = max(self._latest_emitted_seq, seq)

            logger.debug(
                "[EmotionPerception] session={} utt={} emotion={} ({:.0%}) interim={} latency={}ms tok={}/{}",
                self._session_id or "-",
                utterance_id,
                descriptor.key,
                confidence,
                interim,
                latency_ms,
                input_tokens,
                output_tokens,
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
                "output_tokens": output_tokens,
                "total_input_tokens": self._total_input_tokens,
                "total_output_tokens": self._total_output_tokens,
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
            self._record_classifier_failure(exc)
        except Exception as exc:
            logger.warning("[EmotionPerception] Unexpected error: {}", exc)
        finally:
            if interim:
                self._interim_in_flight = False
