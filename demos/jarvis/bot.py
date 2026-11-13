"""Jarvis voice pipeline: local mic/speaker -> Gemini Live -> macOS tools.

Runs on the Mac with Pipecat's LocalAudioTransport. Gemini Live hears the user
(or a virtual audio cable from Google Meet), sees screenshots we push into the
stream, and calls desktop, Meet, draw.io, or optional Android/ADB mobile tools.
Risky actions pause until the user approves them in the Jarvis UI.

Only the Gemini Developer API (AI Studio, `GEMINI_API_KEY`) is used. Vertex AI
is deliberately not supported.
"""

from __future__ import annotations

import array
import asyncio
import collections
import math
import os
import sys
import time
from typing import Any, Awaitable, Callable, Mapping, Protocol

from google.genai.types import EndSensitivity, HttpOptions, StartSensitivity, TurnCoverage
from loguru import logger

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorCategory,
    ErrorFrame,
    Frame,
    FunctionCallInProgressFrame,
    InputAudioRawFrame,
    InputImageRawFrame,
    InterruptionFrame,
    LLMRunFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSStartedFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.google.gemini_live.llm import (
    ContextWindowCompressionParams,
    GeminiLiveLLMService,
    GeminiVADParams,
)
from pipecat.services.llm_service import FunctionCallParams

import jarvis_config
import mac_actions

DEFAULT_MODEL = "gemini-3.8-live"
DEFAULT_VOICE = "Charon"
# speech_config.language_code picks the reference voice sample the Live
# backend loads for the session. Leaving it unset (or "en") falls back to the
# en-US sample; "en-IN" gives an Indian English accent from the first word.
DEFAULT_LANGUAGE = "en-IN"
# Added to every tool result while an Indian locale is active. Raw English JSON
# right before decoding pulls the voice back toward a US accent; a short tone
# line in the result itself keeps the accent steady after tool calls.
VOCAL_TONE = "Natural Indian English accent on every word; calm, warm and clear."
# Context compression: start trimming at this many tokens instead of the
# default 80% of the window, so every turn doesn't re-bill a huge audio and
# screenshot history.
_COMPRESSION_TRIGGER_TOKENS = 32_000
_TOOL_TIMEOUT_SECONDS = 120
_ECHO_PRE_ROLL_SECONDS = 0.50
_ECHO_TAIL_SECONDS = 0.60
# How long to keep dropping Jarvis's audio after a local barge-in while we wait
# for Gemini's own "interrupted" signal for the reply it was still streaming.
_BARGE_IN_SUPPRESS_SECONDS = 2.0
_ISOLATED_OUTPUT_KEYWORDS = (
    "headphone",
    "airpod",
    "earphone",
    "earbud",
    "headset",
    "beats",
    "blackhole",
    "loopback",
)

SYSTEM_INSTRUCTION = """\
You are Jarvis, a calm, witty voice assistant operating a Mac desktop.
You can see the screen through screenshots and act with the tools provided.

How you work:
- Keep spoken replies short: one or two sentences.
- All tools run asynchronously (NON_BLOCKING): keep speaking naturally while
  tools execute ("Opening draw.io right now... pasting the architecture")
  instead of going silent during actions, then briefly follow up once the tool
  result arrives.
- Prefer open_app, open_url, meet_join, meet_action, open_drawio and press_keys
  over raw coordinate clicking whenever they do the job.
- Browser tabs: the user keeps many tabs open in Chrome. Before opening a site,
  call switch_to_tab(query) to reuse an existing tab (pass url_if_missing to
  open it otherwise). "My mail/mailbox/inbox/email" means Gmail in Chrome:
  call open_mailbox (compose=true to start a new email), not the Mail app.
- Always tell the user where you are working: after switching or opening a
  tab, say its title in a few words ("I'm in your Google Maps tab"). If the
  user says they can't see it, call look_at_screen and describe what's in
  front, then switch_to_tab again rather than continuing blind.
- Multi-monitor: Your home screen is the display your floating pill is on
  (home_display in look_at_screen results). Work there by default: windows you
  open or switch to are moved onto it automatically, and screenshots show it.
  Only call look_at_screen(display=N) when the user points at another screen
  ("my second screen"); follow-ups then stay on that display until you open or
  switch to something, which brings you back home.
- Searching: "search X on YouTube/Google/Maps/Gmail/..." -> web_search(site, X).
  Distances/routes -> maps_directions(origin, destination). Never click a
  search box by x/y and type; these tools do it reliably in the user's tab.
- Typing into a box: type_text(text, field="Search") (field = its label or
  placeholder). Only omit field if you just clicked into the box with click_text.
- Clicking: Prefer click_text(text) for anything with a visible label: buttons,
  links, tabs, menu items, video/thumbnail titles (click the video's title
  text, e.g. click_text("Why AI Infrastructure Is Moving to Rust")). Use x/y
  click only for unlabeled targets; aim at the centre and, if it misses, check
  the follow-up screenshot and adjust. Never repeat the same x/y after a miss.
- Each screenshot result names what it shows (screen N, front app, window
  title, top windows on that screen). When describing the screen, say which
  screen and app you're looking at; if that isn't what the user means, ask
  or switch (switch_to_tab / look_at_screen(display=N)) instead of guessing.
- Before clicking for the first time in a turn, call look_at_screen only if you
  have not received a screenshot yet. Coordinates are pixels in the latest screenshot.
- Every action tool (click, type_text, press_keys, open_app, open_url, scroll,
  meet_join, meet_action, open_drawio, mobile_*) automatically captures and
  attaches a fresh screenshot before returning. NEVER call look_at_screen right
  after another tool—use the screenshot already attached.
- Google Meet: To start/create a new meeting, call meet_join(meeting="new")
  directly. Never click through the "New meeting" dropdown on meet.google.com.
  To join an existing one, call meet_join with its code or URL. These open in
  the user's own Chrome. Then click "Join now" on the pre-join screen in the
  attached screenshot. Only pass use_jarvis_profile=True when the user asks
  you to join as a separate participant ("Jarvis"); then enter "Jarvis" if
  asked for a name. In a group call, stay quiet unless addressed as "Jarvis".
- Diagrams: To draw anything in draw.io (architecture, flow, tiers), call
  open_drawio(mermaid_code) once with a Mermaid flowchart ("graph TD" or
  "graph LR"; use [box], [(database)], {decision}, A -->|label| B). It opens
  draw.io in Chrome with the diagram ALREADY DRAWN, boxes and arrows included.
  Do not use open_url for draw.io/excalidraw or click toolbar shapes; just
  tell the user it is ready. For ANY change ("rename box 1 to Client", "add a
  database"), call open_drawio again with the FULL updated Mermaid code: it
  redraws in the same draw.io tab, never a new one. Keep node ids stable.
- Mobile apps (e.g. Swiggy): If an Android device/emulator is connected, use
  mobile_open_app / mobile_tap / mobile_type / mobile_swipe. If not, open
  iPhone Mirroring or the emulator/browser window and use Mac desktop tools.
- If the user starts talking while you are speaking, stop at once and follow
  the new instruction. Do not finish or repeat the old sentence.
- Respond only to the user's newest words. If your own last sentence echoes
  back from the speakers, ignore it and keep listening for the user.
- Tool results are private guidance. Say what matters in your own words; never
  read field names, JSON, or the vocal_tone field aloud.
- Use short spoken acknowledgements ("Sure", "Right", "On it"), not "Hmm" or
  "Umm".
- Some actions (deleting data, force-push, Pay/Order/Checkout buttons) need
  approval. If a tool says waiting or denied, tell the user plainly and do not
  try to work around it.
- Never invent results. If you cannot see something, say so.
"""

_INDIAN_ACCENT_INSTRUCTION = """
Voice: Speak English with a natural Indian accent on every word, like an
Indian professional talking to a colleague: clear, warm and unhurried. Keep
that accent for the whole conversation, including right after tool results.
Use Indian conventions when they come up: lakh and crore, rupees, DD/MM dates.
"""


def accent_enabled(language: str) -> bool:
    """Returns True when the session locale is an Indian one (e.g. en-IN, hi-IN)."""
    return language.strip().upper().endswith("-IN")


def build_system_instruction(language: str = DEFAULT_LANGUAGE) -> str:
    """Returns the Jarvis system prompt, with the accent block for Indian locales."""
    if accent_enabled(language):
        return SYSTEM_INSTRUCTION + _INDIAN_ACCENT_INSTRUCTION
    return SYSTEM_INSTRUCTION


class UiBridge(Protocol):
    """What the pipeline needs from the floating UI."""

    def emit(self, event: dict[str, Any]) -> None: ...

    async def request_approval(self, action: str, reason: str) -> bool: ...


def is_headphone_output(device_name: str) -> bool:
    """Returns True when the output device is isolated from the mic (headphones/virtual cable)."""
    lowered = device_name.lower()
    if "speaker" in lowered:
        return False
    return any(keyword in lowered for keyword in _ISOLATED_OUTPUT_KEYWORDS)


def _detect_output_device_name(output_device_index: int | None = None) -> str:
    try:
        import pyaudio

        pa = pyaudio.PyAudio()
        try:
            if output_device_index is not None:
                info = pa.get_device_info_by_index(output_device_index)
            else:
                info = pa.get_default_output_device_info()
            return str(info.get("name", ""))
        finally:
            pa.terminate()
    except Exception:
        return ""


def resolve_echo_guard_enabled(
    env_value: str | None = None,
    output_device_name: str | None = None,
    output_device_index: int | None = None,
) -> tuple[bool, str]:
    """Determines whether to mute mic input during bot speech to prevent speaker echo."""
    setting = (
        env_value if env_value is not None else os.getenv("JARVIS_ECHO_GUARD", "auto")
    ).strip().lower()
    device = (
        output_device_name
        if output_device_name is not None
        else _detect_output_device_name(output_device_index)
    )

    if setting in ("1", "true", "on", "yes"):
        return True, device or "forced-on"
    if setting in ("0", "false", "off", "no"):
        return False, device or "forced-off"
    if setting in ("smart", "mute"):
        return True, device or f"forced-{setting}"
    if device and is_headphone_output(device):
        return False, device
    return True, device or "unknown output"


def resolve_echo_mode(
    env_value: str | None = None,
    output_device_name: str | None = None,
    output_device_index: int | None = None,
) -> tuple[str, str]:
    """Picks how the mic is handled while Jarvis speaks: "off", "smart" or "mute".

    - "off": mic always open (headphones/virtual cables); Gemini's own VAD
      handles barge-in.
    - "smart" (default on open speakers): mic is silenced while Jarvis talks,
      but loud, sustained speech well above the speaker echo counts as a
      barge-in: Jarvis stops at once and the user's words go through.
    - "mute": mic fully silenced while Jarvis talks plus a short tail (no
      barge-in). JARVIS_ECHO_GUARD=on/mute selects it.
    """
    raw = env_value if env_value is not None else os.getenv("JARVIS_ECHO_GUARD", "auto")
    setting = raw.strip().lower()
    enabled, device = resolve_echo_guard_enabled(
        setting, output_device_name, output_device_index
    )
    if not enabled:
        return "off", device
    if setting in ("1", "true", "on", "yes", "mute"):
        return "mute", device
    return "smart", device


def _pcm16_rms(audio: bytes) -> float:
    """Root-mean-square level of little/native-endian signed 16-bit PCM."""
    usable = len(audio) - (len(audio) % 2)
    if usable <= 0:
        return 0.0
    samples = array.array("h")
    samples.frombytes(audio[:usable])
    if sys.byteorder != "little":
        samples.byteswap()
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class _BargeInDetector:
    """Spots the user talking over Jarvis's own speaker output.

    While Jarvis speaks, the mic hears its echo. The detector keeps a slowly
    decaying peak of that echo level and calls it a barge-in once the mic stays
    well above it (`ratio` times, and at least `min_rms`) for `hold_seconds`.
    The first `warmup_seconds` of each utterance only learn the echo level.
    Raw frames from the last `preroll_seconds` are kept so the start of the
    user's words can be forwarded after the barge-in fires.
    """

    def __init__(
        self,
        ratio: float = 2.2,
        min_rms: float = 700.0,
        hold_seconds: float = 0.18,
        warmup_seconds: float = 0.30,
        preroll_seconds: float = 0.50,
        decay_per_second: float = 0.80,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ratio = ratio
        self._min_rms = min_rms
        self._hold = hold_seconds
        self._warmup = warmup_seconds
        self._preroll = preroll_seconds
        self._decay_per_second = decay_per_second
        self._clock = clock
        self._echo_level = 0.0
        self._loud_seconds = 0.0
        self._quiet_frames = 0
        self._started_at: float | None = None
        self._buffer: collections.deque[InputAudioRawFrame] = collections.deque()
        self._buffered_seconds = 0.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> _BargeInDetector:
        """Builds a detector, letting JARVIS_BARGE_IN_RATIO / _MIN_RMS tune it."""
        env = os.environ if env is None else env

        def _num(name: str, default: float) -> float:
            try:
                return float(env.get(name, default))
            except (TypeError, ValueError):
                return default

        return cls(
            ratio=_num("JARVIS_BARGE_IN_RATIO", 2.2),
            min_rms=_num("JARVIS_BARGE_IN_MIN_RMS", 700.0),
        )

    @property
    def echo_level(self) -> float:
        return self._echo_level

    def start_utterance(self) -> None:
        """Called when Jarvis starts a new stretch of speech."""
        self._started_at = self._clock()
        self._loud_seconds = 0.0
        self._quiet_frames = 0
        self._buffer.clear()
        self._buffered_seconds = 0.0

    def feed(self, frame: InputAudioRawFrame) -> bool:
        """Feeds one mic frame captured while Jarvis speaks; True means barge-in."""
        if self._started_at is None:
            self.start_utterance()
        channels = max(1, frame.num_channels)
        duration = len(frame.audio) / (2 * channels * max(1, frame.sample_rate))
        self._buffer.append(frame)
        self._buffered_seconds += duration
        while self._buffer and self._buffered_seconds - self._frame_seconds(self._buffer[0]) >= self._preroll:
            self._buffered_seconds -= self._frame_seconds(self._buffer.popleft())

        rms = _pcm16_rms(frame.audio)
        threshold = max(self._min_rms, self._ratio * self._echo_level)
        in_warmup = (self._clock() - self._started_at) < self._warmup
        if in_warmup or rms < threshold:
            # Learn the echo: jump up to new peaks, decay slowly otherwise.
            decay = self._decay_per_second ** duration
            self._echo_level = max(rms, self._echo_level * decay)
            self._quiet_frames += 1
            if self._quiet_frames > 1:  # allow one quiet frame inside a word
                self._loud_seconds = 0.0
            return False
        self._quiet_frames = 0
        self._loud_seconds += duration
        return self._loud_seconds >= self._hold

    def drain(self) -> list[InputAudioRawFrame]:
        """Returns and clears the buffered raw frames (oldest first)."""
        frames = list(self._buffer)
        self._buffer.clear()
        self._buffered_seconds = 0.0
        self._loud_seconds = 0.0
        return frames

    @staticmethod
    def _frame_seconds(frame: InputAudioRawFrame) -> float:
        channels = max(1, frame.num_channels)
        return len(frame.audio) / (2 * channels * max(1, frame.sample_rate))


class _EchoGuardState:
    """Tracks when Jarvis is speaking (plus acoustic tail) so speaker output isn't fed back."""

    def __init__(
        self,
        enabled: bool,
        pre_roll_seconds: float = _ECHO_PRE_ROLL_SECONDS,
        tail_seconds: float = _ECHO_TAIL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        barge_in: bool = False,
        suppress_seconds: float = _BARGE_IN_SUPPRESS_SECONDS,
    ) -> None:
        self.enabled = enabled
        self.barge_in = barge_in
        self._pre_roll_seconds = pre_roll_seconds
        self._tail_seconds = tail_seconds
        self._suppress_seconds = suppress_seconds
        self._clock = clock
        self._bot_speaking = False
        self._mute_until = 0.0
        self._suppress_output_until = 0.0
        self._own_interrupts_pending = 0

    def on_pre_speech(self) -> None:
        if not self.enabled:
            return
        self._mute_until = max(self._mute_until, self._clock() + self._pre_roll_seconds)

    def on_bot_started(self) -> None:
        if not self.enabled:
            return
        self._bot_speaking = True
        self._mute_until = max(self._mute_until, self._clock() + self._pre_roll_seconds)

    def on_bot_stopped(self) -> None:
        if not self.enabled:
            return
        self._bot_speaking = False
        self._mute_until = max(self._mute_until, self._clock() + self._tail_seconds)

    def on_interrupted(self) -> None:
        self._bot_speaking = False
        # In smart mode the user is the one talking now: muting the tail would
        # clip their first words. Plain mute mode keeps a short tail.
        if self.enabled and not self.barge_in:
            self._mute_until = max(self._mute_until, self._clock() + 0.15)
        else:
            self._mute_until = 0.0

    def on_local_barge_in(self) -> None:
        """The user talked over Jarvis: open the mic and drop the stale reply."""
        self._bot_speaking = False
        self._mute_until = 0.0
        self._suppress_output_until = self._clock() + self._suppress_seconds
        # broadcast_interruption() sends one InterruptionFrame downstream to
        # the output tap; the next one there is Gemini's own confirmation.
        self._own_interrupts_pending = 1

    def on_output_interruption(self) -> None:
        """An InterruptionFrame reached the output side of the pipeline."""
        if self._own_interrupts_pending:
            self._own_interrupts_pending -= 1
            return
        # Gemini confirmed it: the stale reply is cancelled, new audio is fresh.
        self._suppress_output_until = 0.0

    def suppress_output(self) -> bool:
        """True while Jarvis's leftover audio from an interrupted reply is dropped."""
        return self._clock() < self._suppress_output_until

    def should_mute_mic(self) -> bool:
        if not self.enabled:
            return False
        return self._bot_speaking or (self._clock() < self._mute_until)


class JarvisControl:
    """Thread-safe pause/resume and stop controls shared with the floating UI."""

    def __init__(self) -> None:
        self.paused = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: PipelineTask | None = None

    def bind(self, loop: asyncio.AbstractEventLoop, task: PipelineTask) -> None:
        self._loop = loop
        self._task = task

    def set_paused(self, paused: bool) -> bool:
        self.paused = bool(paused)
        if self.paused and self._loop and self._task:
            # Thread-safe and keeps a reference, unlike a bare create_task.
            asyncio.run_coroutine_threadsafe(
                self._task.queue_frames([InterruptionFrame()]), self._loop
            )
        return self.paused

    def stop(self) -> None:
        # PipelineTask.cancel is a coroutine: scheduling it with
        # call_soon_threadsafe would create it without ever awaiting it.
        if self._loop and self._task and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._task.cancel(), self._loop)


class _SpeakerEchoGuard(FrameProcessor):
    """Silences mic frames while Jarvis is speaking or paused, with optional barge-in.

    With a `detector` (smart mode), loud speech over Jarvis's echo triggers a
    local interruption: Jarvis's queued audio is flushed right away, the mic
    opens, and the buffered start of the user's words is forwarded to Gemini.
    """

    def __init__(
        self,
        state: _EchoGuardState,
        control: JarvisControl | None = None,
        detector: _BargeInDetector | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._state = state
        self._control = control
        self._detector = detector
        self._was_muting = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            self._state.on_bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._state.on_bot_stopped()
        elif isinstance(frame, InterruptionFrame):
            self._state.on_interrupted()
        elif isinstance(frame, InputAudioRawFrame):
            if self._control is not None and self._control.paused:
                frame = _silence_like(frame)
            elif self._state.should_mute_mic():
                if await self._maybe_barge_in(frame, direction):
                    return
                frame = _silence_like(frame)
            else:
                self._was_muting = False
        await self.push_frame(frame, direction)

    async def _maybe_barge_in(self, frame: InputAudioRawFrame, direction: FrameDirection) -> bool:
        """Returns True if this frame triggered a barge-in (frames already forwarded)."""
        if self._detector is None or not self._state.barge_in:
            return False
        if not self._was_muting:
            self._detector.start_utterance()
            self._was_muting = True
        if not self._detector.feed(frame):
            return False
        logger.info("Barge-in: user spoke over Jarvis (echo level {:.0f})", self._detector.echo_level)
        self._state.on_local_barge_in()
        self._was_muting = False
        preroll = self._detector.drain()
        await self.broadcast_interruption()
        for buffered in preroll:
            await self.push_frame(buffered, direction)
        return True


def _silence_like(frame: InputAudioRawFrame) -> InputAudioRawFrame:
    return InputAudioRawFrame(
        audio=b"\x00" * len(frame.audio),
        sample_rate=frame.sample_rate,
        num_channels=frame.num_channels,
    )


class _ScreenFeeder(FrameProcessor):
    """Sits before the LLM so screenshots can be injected as video frames."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    async def send_screenshot(self, shot: mac_actions.Screenshot) -> None:
        await self.push_frame(
            InputImageRawFrame(image=shot.rgb_bytes, size=shot.size, format="RGB"),
            FrameDirection.DOWNSTREAM,
        )


class _InputUiTap(FrameProcessor):
    """Mirrors user speech and transcription events (before the LLM) to the UI."""

    def __init__(self, ui: UiBridge, **kwargs):
        super().__init__(**kwargs)
        self._ui = ui

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            self._ui.emit({"type": "user_text", "text": frame.text})
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._ui.emit({"type": "state", "state": "listening"})
        await self.push_frame(frame, direction)


class _OutputUiTap(FrameProcessor):
    """Mirrors assistant speech/tool events (after the LLM) to the UI and echo guard."""

    def __init__(
        self,
        ui: UiBridge,
        echo_state: _EchoGuardState | None = None,
        control: JarvisControl | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._ui = ui
        self._echo_state = echo_state
        self._control = control

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        paused = self._control is not None and self._control.paused
        if paused and isinstance(frame, OutputAudioRawFrame):
            return
        if (
            isinstance(frame, OutputAudioRawFrame)
            and self._echo_state is not None
            and self._echo_state.suppress_output()
        ):
            # Leftover audio from a reply the user just talked over.
            return

        if self._echo_state is not None:
            if isinstance(frame, (TTSStartedFrame, OutputAudioRawFrame)):
                self._echo_state.on_pre_speech()
            elif isinstance(frame, BotStartedSpeakingFrame):
                self._echo_state.on_bot_started()
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._echo_state.on_bot_stopped()
            elif isinstance(frame, InterruptionFrame):
                self._echo_state.on_interrupted()
                self._echo_state.on_output_interruption()

        if not paused:
            self._mirror_to_ui(frame, direction)
        await self.push_frame(frame, direction)

    def _mirror_to_ui(self, frame: Frame, direction: FrameDirection) -> None:
        # GeminiLiveLLMService emits both LLMTextFrame and TTSTextFrame for every
        # spoken chunk; tap only TTSTextFrame so words aren't duplicated. Not
        # called while paused, so the pill keeps showing "Paused".
        if isinstance(frame, TTSTextFrame):
            self._ui.emit({"type": "bot_text", "text": frame.text})
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._ui.emit({"type": "state", "state": "speaking"})
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._ui.emit({"type": "state", "state": "idle"})
        elif isinstance(frame, FunctionCallInProgressFrame) and direction == FrameDirection.DOWNSTREAM:
            self._ui.emit({"type": "state", "state": "acting"})


class JarvisTools:
    """Desktop, Meet, draw.io, and mobile tools with the approval gate built in."""

    # Wait for the UI to repaint before taking the follow-up screenshot. Must
    # also exceed the 1 s video throttle in GeminiLiveLLMService.
    _SETTLE_SECONDS = 1.1

    def __init__(self, desktop: mac_actions.MacDesktop, feeder: _ScreenFeeder, ui: UiBridge):
        self._desktop = desktop
        self._feeder = feeder
        self._ui = ui
        # Which Chrome the last meet_join used, so meet_action focuses that one.
        self._meet_isolated = False
        self._last_frame_at = 0.0

    def _bring_to_home_display(self) -> int | None:
        """Moves the window an action just opened onto Jarvis's screen.

        Jarvis works on the display its floating pill is on; a window that
        opened on another monitor is moved over so the user sees it next to
        the pill and the screenshot shows it.
        """
        try:
            home = self._desktop.home_display()
            self._desktop.unpin_display()
            if self._desktop.move_front_window_to_display(home):
                time.sleep(0.4)  # Let the window finish moving before the screenshot.
            return home
        except Exception:  # A screenshot of the active display is a fine fallback.
            logger.opt(exception=True).debug("Moving the front window to the home display failed")
            try:
                return self._desktop.front_window_display()
            except Exception:
                return None

    # Pipecat's GeminiLiveLLMService silently drops video frames sent less than
    # 1 s after the previous one, so a screenshot taken too soon never reached
    # the model while the tool result still claimed it was "fresh". Space them.
    _MIN_FRAME_GAP = 1.15

    async def _look(self, display: int | None = None, pin: bool = False) -> dict[str, Any]:
        shot = await asyncio.to_thread(self._desktop.screenshot, display, pin)
        wait = self._MIN_FRAME_GAP - (time.monotonic() - self._last_frame_at)
        if wait > 0:
            await asyncio.sleep(wait)
        await self._feeder.send_screenshot(shot)
        self._last_frame_at = time.monotonic()
        info: dict[str, Any] = {
            "screenshot_size": list(shot.size),
            "display": shot.display,
            "display_count": shot.display_count,
        }
        front = await asyncio.to_thread(self._safe_front_info, shot.display)
        if front:
            info.update(front)
        return info

    def _safe_front_info(self, display: int) -> dict[str, str]:
        try:
            return self._desktop.front_window_info(display)
        except Exception:
            logger.opt(exception=True).debug("front_window_info failed")
            return {}

    async def _act(
        self,
        params: FunctionCallParams,
        label: str,
        action: Callable[[], Any],
        verdict: mac_actions.RiskVerdict,
        extra: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
        follow_front: bool = False,
    ) -> None:
        self._ui.emit({"type": "action", "label": label})
        if verdict.risky:
            self._ui.emit({"type": "gate", "label": label, "reason": verdict.reason})
            approved = await self._ui.request_approval(label, verdict.reason)
            self._ui.emit({"type": "gate_resolved", "approved": approved})
            if not approved:
                await params.result_callback(
                    {"status": "denied", "reason": f"User denied: {verdict.reason}"}
                )
                return
        try:
            await asyncio.to_thread(action)
        except Exception as exc:  # Report failures to the model instead of crashing.
            logger.exception("Jarvis action failed: {}", label)
            await params.result_callback({"status": "error", "error": str(exc)})
            return
        await asyncio.sleep(self._SETTLE_SECONDS)
        display = None
        if follow_front:
            display = await asyncio.to_thread(self._bring_to_home_display)
        screen = await self._look(display)
        payload = {"status": "done", "action": label, "fresh_screenshot_attached": True, **screen}
        if callable(extra):
            extra = extra()
        if extra:
            payload.update(extra)
        await params.result_callback(payload)

    # -- desktop handlers ---------------------------------------------------

    async def look_at_screen(self, params: FunctionCallParams) -> None:
        """Captures a fresh screenshot and returns its dimensions and connected displays."""
        args = params.arguments or {}
        raw_display = args.get("display")
        display = int(raw_display) if raw_display is not None else None
        label = f"Looking at screen {display}" if display is not None else "Looking at the screen"
        self._ui.emit({"type": "action", "label": label})
        try:
            screen_info = await self._look(display, pin=display is not None)
        except Exception as exc:
            await params.result_callback({"status": "error", "error": str(exc)})
            return
        displays = await asyncio.to_thread(self._desktop.list_displays)
        home = await asyncio.to_thread(self._desktop.home_display)
        screen_info["home_display"] = home
        screen_info["displays"] = [
            {
                "display": d.index,
                "main": d.is_main,
                "points": [int(d.width), int(d.height)],
            }
            for d in displays
        ]
        await params.result_callback(
            {"status": "done", "fresh_screenshot_attached": True, **screen_info}
        )

    async def click(self, params: FunctionCallParams) -> None:
        """Clicks a screen coordinate with a safety check on the target."""
        args = params.arguments
        target = args.get("target_description", "")
        x_coord, y_coord = float(args["x"]), float(args["y"])
        is_double = bool(args.get("double", False))
        raw_display = args.get("display")
        display = int(raw_display) if raw_display is not None else None
        await self._act(
            params,
            f"Click {target}".strip(),
            lambda: self._desktop.click(x_coord, y_coord, is_double, display=display),
            mac_actions.assess_click(target),
        )

    async def click_text(self, params: FunctionCallParams) -> None:
        """Clicks a UI element by its visible text via macOS Accessibility."""
        args = params.arguments
        text = (args.get("text") or "").strip()
        nth = max(1, int(args.get("nth", 1) or 1))
        is_double = bool(args.get("double", False))
        if not text:
            await params.result_callback({"status": "error", "error": "text is required"})
            return
        hit: dict[str, Any] = {}

        def _click() -> None:
            m = self._desktop.click_text(text, nth, is_double)
            hit.update(clicked_role=m.role, clicked_text=m.text)

        await self._act(
            params, f"Click “{text[:50]}”", _click, mac_actions.assess_click(text),
            extra=lambda: hit,
            follow_front=True,
        )

    async def type_text(self, params: FunctionCallParams) -> None:
        """Types text, first clicking into a named field when one is given."""
        args = params.arguments
        text = args["text"]
        press_enter = bool(args.get("press_enter", False))
        field = (args.get("field") or "").strip()
        info: dict[str, Any] = {}

        def _type() -> None:
            if field:
                m = self._desktop.focus_text_field(field)
                info["typed_into"] = m.text or m.role
            self._desktop.type_text(text, press_enter)

        await self._act(
            params,
            f"Type “{text[:60]}”" + (f" into {field}" if field else ""),
            _type,
            mac_actions.assess_text(text),
            extra=lambda: info,
        )

    async def _open_here_or_new(self, host_hint: str, url: str, label: str,
                                params: FunctionCallParams) -> None:
        """Navigates an existing tab of that site (keeps the user's place), or opens one."""
        info: dict[str, Any] = {"url": url}

        def _go() -> None:
            tab = self._desktop.focus_chrome_tab(host_hint) if host_hint else None
            if tab:
                self._desktop.set_front_tab_url(url)
                info.update(reused_tab=True, previous_tab=tab.title[:80])
            else:
                self._desktop.open_in_chrome(url)
                info["reused_tab"] = False
            time.sleep(1.5)

        await self._act(params, label, _go, mac_actions.RiskVerdict(False),
                        extra=lambda: info, follow_front=True)

    async def web_search(self, params: FunctionCallParams) -> None:
        """Runs a search on a site by URL: no search box clicking or typing."""
        args = params.arguments
        site, query = (args.get("site") or "google"), (args.get("query") or "").strip()
        if not query:
            await params.result_callback({"status": "error", "error": "query is required"})
            return
        key = site.strip().lower().replace(" ", "").removesuffix(".com")
        gmail_base = ""
        if key in ("mail", "gmail", "email", "inbox"):
            tab = await asyncio.to_thread(self._desktop.focus_chrome_tab, "mail.google.com")
            gmail_base = tab.url if tab else ""
        try:
            url = mac_actions.site_search_url(site, query, gmail_base)
        except ValueError as exc:
            await params.result_callback({"status": "error", "error": str(exc)})
            return
        hint = mac_actions.SEARCH_SITE_HOSTS.get(key, "")
        await self._open_here_or_new(hint, url, f"Search {site}: {query[:40]}", params)

    async def maps_directions(self, params: FunctionCallParams) -> None:
        """Opens Google Maps directions between two places."""
        args = params.arguments
        url = mac_actions.maps_directions_url(
            args.get("origin", ""), args.get("destination", ""), args.get("mode", "")
        )
        await self._open_here_or_new(
            "google.com/maps", url, f"Directions to {args.get('destination', '')[:40]}", params
        )

    async def press_keys(self, params: FunctionCallParams) -> None:
        """Sends a keyboard shortcut or special key."""
        combo = params.arguments["combo"]
        await self._act(
            params,
            f"Press {combo}",
            lambda: self._desktop.press_keys(combo),
            mac_actions.RiskVerdict(False),
        )

    async def open_app(self, params: FunctionCallParams) -> None:
        """Opens or focuses a macOS application by name."""
        name = params.arguments["name"]
        await self._act(
            params,
            f"Open {name}",
            lambda: self._desktop.open_app(name),
            mac_actions.RiskVerdict(False),
            follow_front=True,
        )

    async def open_url(self, params: FunctionCallParams) -> None:
        """Opens a URL in the default browser."""
        url = params.arguments["url"]
        await self._act(
            params,
            f"Open {url}",
            lambda: self._desktop.open_url(url),
            mac_actions.RiskVerdict(False),
            follow_front=True,
        )

    async def scroll(self, params: FunctionCallParams) -> None:
        """Scrolls at (x, y) if given, otherwise under the pointer."""
        args = params.arguments or {}
        amount = int(args.get("amount", -5))
        x_coord = float(args["x"]) if args.get("x") is not None else None
        y_coord = float(args["y"]) if args.get("y") is not None else None
        raw_display = args.get("display")
        display = int(raw_display) if raw_display is not None else None
        await self._act(
            params,
            "Scroll",
            lambda: self._desktop.scroll(amount, x_coord, y_coord, display),
            mac_actions.RiskVerdict(False),
        )

    # -- Google Meet & draw.io handlers -------------------------------------

    async def meet_join(self, params: FunctionCallParams) -> None:
        """Starts or joins a Google Meet, in the user's Chrome by default."""
        args = params.arguments
        try:
            url = mac_actions.normalize_meet_url(args.get("meeting", "new"))
        except ValueError as exc:
            await params.result_callback({"status": "error", "error": str(exc)})
            return
        use_jarvis_profile = bool(args.get("use_jarvis_profile", False))
        self._meet_isolated = use_jarvis_profile

        def _launch() -> None:
            if use_jarvis_profile:
                self._desktop.open_chrome_profile(url)
            else:
                self._desktop.open_in_chrome(url)
            # Meet needs a moment to create the room and render the pre-join
            # screen before the follow-up screenshot is useful.
            time.sleep(2.5)

        await self._act(
            params,
            f"Open Meet {url}",
            _launch,
            mac_actions.RiskVerdict(False),
            extra={
                "url": url,
                "isolated_profile": use_jarvis_profile,
                "next_step": "On the pre-join screen in the screenshot, click 'Join now'"
                " (or 'Switch here'); if not visible yet, call look_at_screen.",
            },
            follow_front=True,
        )

    async def meet_action(self, params: FunctionCallParams) -> None:
        """Performs an in-call Google Meet action (mic, cam, hand, chat, leave)."""
        args = params.arguments
        action_name = args["action"].strip().lower()
        message = args.get("message", "")

        if action_name == "send_chat":
            if not message.strip():
                await params.result_callback({"status": "error", "error": "message is required"})
                return

            def _send_chat() -> None:
                self._desktop.focus_meet_window(isolated=self._meet_isolated)
                self._desktop.press_keys(mac_actions.MEET_SHORTCUTS["open_chat"])
                time.sleep(0.4)
                self._desktop.type_text(message, press_enter=True)

            await self._act(
                params,
                f"Meet chat: {message[:45]}",
                _send_chat,
                mac_actions.assess_text(message),
            )
            return

        shortcut = mac_actions.MEET_SHORTCUTS.get(action_name)
        if not shortcut:
            valid = sorted([*mac_actions.MEET_SHORTCUTS, "send_chat"])
            await params.result_callback(
                {"status": "error", "error": f"Unknown meet action {action_name!r}; use {valid}"}
            )
            return

        verdict = (
            mac_actions.RiskVerdict(True, "leaves the active Google Meet call")
            if action_name == "leave"
            else mac_actions.RiskVerdict(False)
        )
        def _press_in_meet() -> None:
            self._desktop.focus_meet_window(isolated=self._meet_isolated)
            self._desktop.press_keys(shortcut)

        await self._act(
            params,
            f"Meet: {action_name}",
            _press_in_meet,
            verdict,
        )

    async def switch_to_tab(self, params: FunctionCallParams) -> None:
        """Finds an open Chrome tab by URL/title text and brings it to the front."""
        args = params.arguments
        query = (args.get("query") or "").strip()
        fallback = (args.get("url_if_missing") or "").strip()
        if not query:
            await params.result_callback({"status": "error", "error": "query is required"})
            return
        found: dict[str, Any] = {}

        def _switch() -> None:
            tab = self._desktop.focus_chrome_tab(query)
            if tab:
                found.update(found_existing_tab=True, tab_url=tab.url, tab_title=tab.title)
                self._ui.emit({"type": "action", "label": f"Chrome tab: {tab.title[:60]}"})
            elif fallback:
                self._desktop.open_in_chrome(fallback)
                found.update(found_existing_tab=False, opened=fallback)
            else:
                raise LookupError(f"No open Chrome tab matches {query!r}")

        await self._act(
            params, f"Switch to tab: {query}", _switch, mac_actions.RiskVerdict(False),
            extra=lambda: found,
            follow_front=True,
        )

    async def open_mailbox(self, params: FunctionCallParams) -> None:
        """Switches to the user's open Gmail tab (or opens Gmail) and optionally composes."""
        args = params.arguments or {}
        compose = bool(args.get("compose", False))
        to = args.get("to", "")
        subject = args.get("subject", "")
        body = args.get("body", "")
        if to or subject or body:
            compose = True
        found: dict[str, Any] = {}

        def _open() -> None:
            tab = self._desktop.focus_chrome_tab("mail.google.com")
            base = tab.url if tab else mac_actions.GMAIL_URL
            found["found_existing_tab"] = bool(tab)
            if not tab:
                self._desktop.open_in_chrome(mac_actions.GMAIL_URL)
            if compose:
                url = mac_actions.gmail_compose_url(base, to, subject, body)
                if tab:
                    self._desktop.set_front_tab_url(url)
                else:
                    time.sleep(2.0)
                    self._desktop.set_front_tab_url(url)
                found["compose_url"] = url
            time.sleep(1.5)

        label = "Gmail: new email" if compose else "Open Gmail"
        await self._act(
            params, label, _open, mac_actions.RiskVerdict(False),
            extra=lambda: {
                **found,
                "next_step": "A compose window is open; fill in anything missing. Never press"
                " Send without the user's explicit OK." if compose else "",
            },
            follow_front=True,
        )

    async def open_drawio(self, params: FunctionCallParams) -> None:
        """Opens draw.io with a Mermaid flowchart already drawn as a native diagram."""
        mermaid_code = params.arguments.get("mermaid_code", "")
        title = params.arguments.get("title") or "Jarvis diagram"
        outcome: dict[str, str] = {}

        def _open() -> None:
            outcome["mode"] = self._desktop.open_drawio(mermaid_code, title)
            # draw.io takes a moment to load and render the diagram.
            time.sleep(2.5)

        next_steps = {
            "drawn": "The diagram is already drawn on the canvas with boxes and arrows. "
            "Tell the user it is ready; only touch it if they ask for edits.",
            "clipboard": "Not a flowchart, so the Mermaid was copied to the clipboard. Click "
            "Arrange -> Insert -> Advanced -> Mermaid, press cmd+v, then click Insert.",
            "empty": "Blank draw.io is open.",
        }

        await self._act(
            params,
            "Draw in draw.io" if mermaid_code.strip() else "Open draw.io",
            _open,
            mac_actions.RiskVerdict(False),
            extra=lambda: {
                "diagram": outcome.get("mode", ""),
                "next_step": next_steps.get(outcome.get("mode", ""), ""),
            },
            follow_front=True,
        )

    # -- optional Android/ADB mobile handlers -------------------------------

    async def mobile_open_app(self, params: FunctionCallParams) -> None:
        """Launches an app on a connected Android device/emulator (e.g. 'swiggy')."""
        app = params.arguments["app"]
        await self._act(
            params,
            f"Mobile open {app}",
            lambda: self._desktop.mobile_open_app(app),
            mac_actions.RiskVerdict(False),
        )

    async def mobile_tap(self, params: FunctionCallParams) -> None:
        """Taps coordinates on a connected Android device/emulator."""
        args = params.arguments
        target = args.get("target_description", "")
        x_coord, y_coord = int(args["x"]), int(args["y"])
        await self._act(
            params,
            f"Mobile tap {target}".strip(),
            lambda: self._desktop.mobile_tap(x_coord, y_coord),
            mac_actions.assess_click(target),
        )

    async def mobile_type(self, params: FunctionCallParams) -> None:
        """Types text on a connected Android device/emulator."""
        args = params.arguments
        text = args["text"]
        press_enter = bool(args.get("press_enter", False))
        await self._act(
            params,
            f"Mobile type “{text[:50]}”",
            lambda: self._desktop.mobile_type(text, press_enter),
            mac_actions.assess_text(text),
        )

    async def mobile_swipe(self, params: FunctionCallParams) -> None:
        """Swipes on a connected Android device/emulator."""
        args = params.arguments
        await self._act(
            params,
            "Mobile swipe",
            lambda: self._desktop.mobile_swipe(
                int(args["x1"]), int(args["y1"]), int(args["x2"]), int(args["y2"])
            ),
            mac_actions.RiskVerdict(False),
        )

    def definitions(
        self,
    ) -> list[tuple[FunctionSchema, Callable[[FunctionCallParams], Awaitable[None]]]]:
        """Returns (schema, handler) pairs for every tool."""

        def make_tool(name: str, description: str, handler, properties=None, required=None):
            schema = FunctionSchema(
                name=name,
                description=description,
                properties=properties or {},
                required=required or [],
            )
            return schema, handler

        return [
            make_tool(
                "look_at_screen",
                "Take a fresh screenshot of a Mac screen (1 = main display, 2 = second display). Only call when switching displays or when no action tool was just used.",
                self.look_at_screen,
                {
                    "display": {
                        "type": "integer",
                        "description": "Optional 1-based display index (1 = main, 2 = second screen). Omit to capture the active display.",
                    }
                },
            ),
            make_tool(
                "click",
                "Click a point on screen. x,y are pixels in the latest screenshot.",
                self.click,
                {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "target_description": {
                        "type": "string",
                        "description": "Short label of what is clicked, e.g. 'Deploy button'.",
                    },
                    "double": {"type": "boolean"},
                    "display": {
                        "type": "integer",
                        "description": "Optional 1-based display index if clicking on a specific screen.",
                    },
                },
                ["x", "y", "target_description"],
            ),
            make_tool(
                "type_text",
                "Type text. Pass `field` (its visible label/placeholder, e.g. 'Search',"
                " 'To', 'Subject') to click into that box first; without it, text goes to"
                " whatever is focused.",
                self.type_text,
                {
                    "text": {"type": "string"},
                    "press_enter": {"type": "boolean"},
                    "field": {"type": "string", "description": "Label of the text box to type into."},
                },
                ["text"],
            ),
            make_tool(
                "press_keys",
                "Press a key or shortcut, e.g. 'cmd+t', 'enter', 'cmd+shift+4'.",
                self.press_keys,
                {"combo": {"type": "string"}},
                ["combo"],
            ),
            make_tool(
                "open_app",
                "Open or focus a Mac app by name.",
                self.open_app,
                {"name": {"type": "string"}},
                ["name"],
            ),
            make_tool(
                "web_search",
                "Search a site directly by URL (no clicking/typing): site = youtube, google,"
                " maps, images, news, gmail, drive, github, amazon, wikipedia, x. Reuses the"
                " user's open tab for that site, else opens one. ALWAYS use this for 'search"
                " X on Y'.",
                self.web_search,
                {"site": {"type": "string"}, "query": {"type": "string"}},
                ["site", "query"],
            ),
            make_tool(
                "maps_directions",
                "Open Google Maps directions/distance between two places (reuses a Maps tab).",
                self.maps_directions,
                {
                    "origin": {"type": "string"},
                    "destination": {"type": "string"},
                    "mode": {"type": "string", "description": "driving, walking, transit or bicycling"},
                },
                ["origin", "destination"],
            ),
            make_tool(
                "click_text",
                "Click a button, link, tab, menu item or video by its visible text (e.g. a"
                " YouTube video title, 'Join now', 'Compose'). Finds the element through macOS"
                " Accessibility and clicks its exact centre. More reliable than x/y clicks.",
                self.click_text,
                {
                    "text": {"type": "string", "description": "Visible label or title to click."},
                    "nth": {"type": "integer", "description": "Pick the nth match (default 1)."},
                    "double": {"type": "boolean"},
                },
                ["text"],
            ),
            make_tool(
                "switch_to_tab",
                "Find an already-open Chrome tab whose URL or title contains `query` (e.g."
                " 'docs.google.com', 'Jira', 'calendar') and bring it to the front. Use before"
                " opening a site the user probably already has open.",
                self.switch_to_tab,
                {
                    "query": {"type": "string"},
                    "url_if_missing": {
                        "type": "string",
                        "description": "Optional URL to open in Chrome if no tab matches.",
                    },
                },
                ["query"],
            ),
            make_tool(
                "open_mailbox",
                "Open the user's mailbox: switches to their existing Gmail tab in Chrome (keeping"
                " the right account) or opens Gmail. compose=true (or any of to/subject/body)"
                " starts a new email there. Never sends.",
                self.open_mailbox,
                {
                    "compose": {"type": "boolean"},
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
            ),
            make_tool(
                "open_url",
                "Open a URL in the default browser.",
                self.open_url,
                {"url": {"type": "string"}},
                ["url"],
            ),
            make_tool(
                "scroll",
                "Scroll the page. amount: negative = down; -5 is about half a screen (wheel notches), values above 50 are pixels. Defaults to the front window; pass x,y to scroll a specific pane.",
                self.scroll,
                {
                    "amount": {"type": "integer"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "display": {
                        "type": "integer",
                        "description": "Optional 1-based display index for x,y.",
                    },
                },
            ),
            make_tool(
                "meet_join",
                "Start a new Google Meet (meeting='new') or join one by code/URL. Opens in the"
                " user's Chrome; set use_jarvis_profile only to join as a separate 'Jarvis' persona.",
                self.meet_join,
                {
                    "meeting": {
                        "type": "string",
                        "description": "'new' to start an instant meeting, or a Meet URL / code xxx-yyyy-zzz.",
                    },
                    "use_jarvis_profile": {
                        "type": "boolean",
                        "description": "Default false (user's Chrome). True only when asked to join as Jarvis itself.",
                    },
                },
                ["meeting"],
            ),
            make_tool(
                "meet_action",
                "Meet action: toggle_mic, toggle_camera, raise_hand, open_chat, send_chat, leave.",
                self.meet_action,
                {
                    "action": {"type": "string"},
                    "message": {"type": "string", "description": "Chat text for send_chat."},
                },
                ["action"],
            ),
            make_tool(
                "open_drawio",
                "Draw a diagram in draw.io: pass a Mermaid flowchart ('graph TD' / 'graph LR')"
                " and it opens app.diagrams.net in Chrome with the boxes and arrows already drawn.",
                self.open_drawio,
                {
                    "mermaid_code": {
                        "type": "string",
                        "description": "Mermaid flowchart, e.g. 'graph TD\\n A[Web] --> B[App]\\n B --> C[(DB)]'.",
                    },
                    "title": {"type": "string", "description": "Optional diagram name."},
                },
            ),
            make_tool(
                "mobile_open_app",
                "Open an Android app via adb (e.g. 'swiggy' or 'in.swiggy.android').",
                self.mobile_open_app,
                {"app": {"type": "string"}},
                ["app"],
            ),
            make_tool(
                "mobile_tap",
                "Tap (x, y) on a connected Android device/emulator via adb.",
                self.mobile_tap,
                {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "target_description": {"type": "string"},
                },
                ["x", "y", "target_description"],
            ),
            make_tool(
                "mobile_type",
                "Type text on a connected Android device/emulator via adb.",
                self.mobile_type,
                {"text": {"type": "string"}, "press_enter": {"type": "boolean"}},
                ["text"],
            ),
            make_tool(
                "mobile_swipe",
                "Swipe from (x1,y1) to (x2,y2) on a connected Android device/emulator.",
                self.mobile_swipe,
                {
                    "x1": {"type": "integer"},
                    "y1": {"type": "integer"},
                    "x2": {"type": "integer"},
                    "y2": {"type": "integer"},
                },
                ["x1", "y1", "x2", "y2"],
            ),
        ]


def _resolve_api_key() -> str:
    return jarvis_config.resolve_api_key()


def _resolve_transport_audio_indices() -> tuple[int | None, int | None]:
    input_spec = os.getenv("JARVIS_INPUT_DEVICE")
    output_spec = os.getenv("JARVIS_OUTPUT_DEVICE")
    if not input_spec and not output_spec:
        return None, None
    devices = mac_actions.list_audio_devices()
    input_idx = mac_actions.resolve_audio_device_index(input_spec, devices, "input")
    output_idx = mac_actions.resolve_audio_device_index(output_spec, devices, "output")
    logger.info("Audio devices: input={} output={}", input_idx, output_idx)
    return input_idx, output_idx


_TURN_COVERAGE_BY_NAME = {
    "audio_and_video": TurnCoverage.TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO,
    "all_input": TurnCoverage.TURN_INCLUDES_ALL_INPUT,
    "activity": TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
    "default": None,
}


def build_live_settings(
    model: str, env: Mapping[str, str] | None = None
) -> GeminiLiveLLMService.Settings:
    """Gemini Live session settings for Jarvis.

    - language: speech_config.language_code, default en-IN (JARVIS_LANGUAGE).
    - Server VAD: LOW start sensitivity so speaker echo and room noise don't
      cut Jarvis off, LOW end sensitivity with 700 ms of silence so short
      pauses mid-command don't end the turn, 200 ms prefix padding so short
      words still register.
    - Turn coverage: audio activity plus ALL video, so screenshots sent between
      turns stay in the user's turn while silence/echo frames don't.
    - Context window compression with an explicit trigger.
    - temperature/top_k/top_p are left unset (greedy decoding on 3.8 Live has
      caused audio loops).
    """
    env = os.environ if env is None else env
    language = (env.get("JARVIS_LANGUAGE") or DEFAULT_LANGUAGE).strip()
    coverage_name = (env.get("JARVIS_TURN_COVERAGE") or "audio_and_video").strip().lower()
    turn_coverage = _TURN_COVERAGE_BY_NAME.get(
        coverage_name, TurnCoverage.TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO
    )
    return GeminiLiveLLMService.Settings(
        model=f"models/{model}",
        system_instruction=build_system_instruction(language),
        voice=env.get("JARVIS_VOICE") or DEFAULT_VOICE,
        language=language,
        vad=GeminiVADParams(
            start_sensitivity=StartSensitivity.START_SENSITIVITY_LOW,
            end_sensitivity=EndSensitivity.END_SENSITIVITY_LOW,
            prefix_padding_ms=200,
            silence_duration_ms=700,
        ),
        turn_coverage=turn_coverage,
        context_window_compression=ContextWindowCompressionParams(
            enabled=True, trigger_tokens=_COMPRESSION_TRIGGER_TOKENS
        ),
    )


def with_vocal_tone(
    handler: Callable[[FunctionCallParams], Awaitable[None]], tone: str = VOCAL_TONE
) -> Callable[[FunctionCallParams], Awaitable[None]]:
    """Wraps a tool handler so every dict result carries a `vocal_tone` line."""

    async def wrapped(params: FunctionCallParams) -> None:
        original = params.result_callback

        async def result_with_tone(result: Any, *args: Any, **kwargs: Any) -> None:
            if isinstance(result, dict):
                result = {**result, "vocal_tone": tone}
            await original(result, *args, **kwargs)

        params.result_callback = result_with_tone
        await handler(params)

    wrapped.__name__ = getattr(handler, "__name__", "tool")
    return wrapped


async def run_jarvis(ui: UiBridge, control: JarvisControl | None = None) -> None:
    """Builds and runs the pipeline until cancelled.

    Pipecat >= 1.16 declares tools registered with cancel_on_interruption=False
    as NON_BLOCKING on Gemini 3.8+ and sends WHEN_IDLE scheduling with their
    results, so no GeminiLiveLLMService subclass is needed.
    """
    api_key = _resolve_api_key()

    # Imported here so the unit tests can import this module without PyAudio.
    from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

    control = control or JarvisControl()
    model = os.getenv("JARVIS_MODEL", DEFAULT_MODEL)
    logger.info("Starting Jarvis on {} (AI Studio, non-blocking tools)", model)

    input_idx, output_idx = _resolve_transport_audio_indices()
    echo_mode, out_device = resolve_echo_mode(output_device_index=output_idx)
    if echo_mode == "smart":
        logger.info(
            "Open speakers {!r}: mic is silenced while Jarvis talks, but speaking over "
            "it interrupts (JARVIS_ECHO_GUARD=mute to disable barge-in, off for headphones)",
            out_device,
        )
    elif echo_mode == "mute":
        logger.info("Echo guard (no barge-in) for output device {!r}", out_device)
    else:
        logger.info("Isolated output {!r}; mic always open, Gemini VAD handles barge-in", out_device)
    echo_state = _EchoGuardState(enabled=echo_mode != "off", barge_in=echo_mode == "smart")
    detector = _BargeInDetector.from_env() if echo_mode == "smart" else None

    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            input_device_index=input_idx,
            output_device_index=output_idx,
        )
    )
    feeder = _ScreenFeeder()
    tools = JarvisTools(mac_actions.MacDesktop(), feeder, ui)
    definitions = tools.definitions()

    settings = build_live_settings(model)
    llm = GeminiLiveLLMService(
        api_key=api_key,
        settings=settings,
        tools=ToolsSchema(standard_tools=[schema for schema, _ in definitions]),
        http_options=HttpOptions(api_version="v1alpha"),
    )
    tone_on = accent_enabled(str(settings.language))
    logger.info("Voice {} with language {}", settings.voice, settings.language)
    for schema, handler in definitions:
        # Registered with cancel_on_interruption=False so tools are declared
        # NON_BLOCKING (Jarvis keeps speaking while acting) and approval gates
        # can wait up to two minutes without being cancelled mid-action.
        llm.register_function(
            schema.name,
            with_vocal_tone(handler) if tone_on else handler,
            cancel_on_interruption=False,
            timeout_secs=_TOOL_TIMEOUT_SECONDS,
        )

    context = LLMContext()
    user_agg, assistant_agg = LLMContextAggregatorPair(context)

    pipeline = Pipeline(
        [
            transport.input(),
            _SpeakerEchoGuard(echo_state, control, detector),
            user_agg,
            _InputUiTap(ui),
            feeder,
            llm,
            _OutputUiTap(ui, echo_state, control),
            transport.output(),
            assistant_agg,
        ]
    )
    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=True))
    rejected_reason: list[str] = []

    @task.event_handler("on_pipeline_error")
    async def _on_pipeline_error(_task: PipelineTask, frame: ErrorFrame) -> None:
        reason = jarvis_config.classify_gemini_auth_error(
            frame.exception, frame.error, api_key
        )
        if not reason and frame.category in (
            ErrorCategory.AUTHENTICATION,
            ErrorCategory.AUTHORIZATION,
        ):
            reason = "Gemini rejected the saved API key. Paste a valid key from Google AI Studio."
        if reason:
            if not rejected_reason:
                rejected_reason.append(reason)
            await task.cancel()
        elif frame.processor and not getattr(frame.processor, "is_usable", True):
            safe_err = jarvis_config.redact_secrets(
                str(frame.exception or frame.error), api_key
            )
            ui.emit({"type": "error", "text": f"Connection failed: {safe_err}"})
            await task.cancel()

    control.bind(asyncio.get_running_loop(), task)
    ui.emit({"type": "state", "state": "idle"})
    ui.emit({"type": "bot_text", "text": "Jarvis online. At your service."})
    await task.queue_frames([LLMRunFrame()])
    try:
        await PipelineRunner(handle_sigint=False).run(task)
    except Exception as exc:
        reason = jarvis_config.classify_gemini_auth_error(exc, str(exc), api_key)
        if reason:
            raise jarvis_config.ApiKeyRejectedError(reason) from None
        raise
    if rejected_reason:
        raise jarvis_config.ApiKeyRejectedError(rejected_reason[0])
