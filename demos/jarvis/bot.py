"""Jarvis voice pipeline: local mic/speaker -> Gemini Live -> macOS tools.

Runs on the Mac with Pipecat's LocalAudioTransport. Gemini Live hears the user
(or a virtual audio cable from Google Meet), sees screenshots we push into the
stream, and calls desktop, Meet, draw.io, or optional Android/ADB mobile tools.
Risky actions pause until the user approves them in the Jarvis UI.

Only the Gemini Developer API (AI Studio, `GEMINI_API_KEY`) is used. Vertex AI
is deliberately not supported.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Awaitable, Callable, Protocol

from google.genai.types import HttpOptions
from loguru import logger

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
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
)
from pipecat.services.llm_service import FunctionCallParams

import mac_actions

DEFAULT_MODEL = "gemini-3.8-live"
DEFAULT_VOICE = "Charon"
_TOOL_TIMEOUT_SECONDS = 120
_ECHO_PRE_ROLL_SECONDS = 0.50
_ECHO_TAIL_SECONDS = 0.60
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
- Multi-monitor: You can see all connected displays. Call look_at_screen(display=2)
  to inspect a second screen (or display=1 for the main screen). Once you switch
  displays, follow-up screenshots and clicks stay on that display until switched.
- Clicking: Prefer click_text(text) for anything with a visible label: buttons,
  links, tabs, menu items, video/thumbnail titles (click the video's title
  text, e.g. click_text("Why AI Infrastructure Is Moving to Rust")). Use x/y
  click only for unlabeled targets; aim at the centre and, if it misses, check
  the follow-up screenshot and adjust. Never repeat the same x/y after a miss.
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
  Do not open draw.io again or click toolbar shapes to redraw it; just tell
  the user it is ready. For edits, call open_drawio again with updated code.
- Mobile apps (e.g. Swiggy): If an Android device/emulator is connected, use
  mobile_open_app / mobile_tap / mobile_type / mobile_swipe. If not, open
  iPhone Mirroring or the emulator/browser window and use Mac desktop tools.
- If the user interrupts you, stop and follow the new instruction.
- Some actions (deleting data, force-push, Pay/Order/Checkout buttons) need
  approval. If a tool says waiting or denied, tell the user plainly and do not
  try to work around it.
- Never invent results. If you cannot see something, say so.
"""


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
    if device and is_headphone_output(device):
        return False, device
    return True, device or "unknown output"


class _EchoGuardState:
    """Tracks when Jarvis is speaking (plus acoustic tail) so speaker output isn't fed back."""

    def __init__(
        self,
        enabled: bool,
        pre_roll_seconds: float = _ECHO_PRE_ROLL_SECONDS,
        tail_seconds: float = _ECHO_TAIL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = enabled
        self._pre_roll_seconds = pre_roll_seconds
        self._tail_seconds = tail_seconds
        self._clock = clock
        self._bot_speaking = False
        self._mute_until = 0.0

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
        if self.enabled:
            self._mute_until = max(self._mute_until, self._clock() + 0.15)

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
    """Replaces mic frames with silence while Jarvis is speaking or paused."""

    def __init__(
        self,
        state: _EchoGuardState,
        control: JarvisControl | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._state = state
        self._control = control

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            self._state.on_bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._state.on_bot_stopped()
        elif isinstance(frame, InterruptionFrame):
            self._state.on_interrupted()
        elif isinstance(frame, InputAudioRawFrame) and (
            (self._control is not None and self._control.paused)
            or self._state.should_mute_mic()
        ):
            frame = InputAudioRawFrame(
                audio=b"\x00" * len(frame.audio),
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
            )
        await self.push_frame(frame, direction)


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

        if self._echo_state is not None:
            if isinstance(frame, (TTSStartedFrame, OutputAudioRawFrame)):
                self._echo_state.on_pre_speech()
            elif isinstance(frame, BotStartedSpeakingFrame):
                self._echo_state.on_bot_started()
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._echo_state.on_bot_stopped()
            elif isinstance(frame, InterruptionFrame):
                self._echo_state.on_interrupted()

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

    def _safe_front_display(self) -> int | None:
        try:
            return self._desktop.front_window_display()
        except Exception:  # Screenshot of the active display is a fine fallback.
            logger.opt(exception=True).debug("front_window_display failed")
            return None

    async def _look(self, display: int | None = None) -> dict[str, Any]:
        shot = await asyncio.to_thread(self._desktop.screenshot, display)
        await self._feeder.send_screenshot(shot)
        return {
            "screenshot_size": list(shot.size),
            "display": shot.display,
            "display_count": shot.display_count,
        }

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
            display = await asyncio.to_thread(self._safe_front_display)
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
            screen_info = await self._look(display)
        except Exception as exc:
            await params.result_callback({"status": "error", "error": str(exc)})
            return
        displays = await asyncio.to_thread(self._desktop.list_displays)
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
        """Types text after checking for destructive commands."""
        args = params.arguments
        text = args["text"]
        press_enter = bool(args.get("press_enter", False))
        await self._act(
            params,
            f"Type “{text[:60]}”",
            lambda: self._desktop.type_text(text, press_enter),
            mac_actions.assess_text(text),
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
                "Type text into the focused field or terminal.",
                self.type_text,
                {"text": {"type": "string"}, "press_enter": {"type": "boolean"}},
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
                "Scroll. Negative scrolls down. Pass x,y (screenshot pixels) to scroll a specific pane.",
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
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true"):
        raise RuntimeError("Jarvis does not use Vertex AI. Unset GOOGLE_GENAI_USE_VERTEXAI.")
    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY (AI Studio key) in demos/jarvis/.env")
    return key


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


async def run_jarvis(ui: UiBridge, control: JarvisControl | None = None) -> None:
    """Builds and runs the pipeline until cancelled.

    Pipecat >= 1.16 declares tools registered with cancel_on_interruption=False
    as NON_BLOCKING on Gemini 3.8+ and sends WHEN_IDLE scheduling with their
    results, so no GeminiLiveLLMService subclass is needed.
    """
    # Imported here so the unit tests can import this module without PyAudio.
    from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

    control = control or JarvisControl()
    model = os.getenv("JARVIS_MODEL", DEFAULT_MODEL)
    logger.info("Starting Jarvis on {} (AI Studio, non-blocking tools)", model)

    input_idx, output_idx = _resolve_transport_audio_indices()
    echo_guard_on, out_device = resolve_echo_guard_enabled(output_device_index=output_idx)
    if echo_guard_on:
        logger.info(
            "Speaker echo guard enabled for output device {!r} (set JARVIS_ECHO_GUARD=off to allow barge-in)",
            out_device,
        )
    else:
        logger.info("Isolated output {!r} detected; full barge-in enabled", out_device)
    echo_state = _EchoGuardState(enabled=echo_guard_on)

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

    llm = GeminiLiveLLMService(
        api_key=_resolve_api_key(),
        settings=GeminiLiveLLMService.Settings(
            model=f"models/{model}",
            system_instruction=SYSTEM_INSTRUCTION,
            voice=os.getenv("JARVIS_VOICE", DEFAULT_VOICE),
            # Screenshots + audio hit the ~2 min audio/video session cap without
            # a sliding window; Pipecat already reconnects with resumption handles.
            context_window_compression=ContextWindowCompressionParams(enabled=True),
        ),
        tools=ToolsSchema(standard_tools=[schema for schema, _ in definitions]),
        http_options=HttpOptions(api_version="v1alpha"),
    )
    for schema, handler in definitions:
        # Registered with cancel_on_interruption=False so tools are declared
        # NON_BLOCKING (Jarvis keeps speaking while acting) and approval gates
        # can wait up to two minutes without being cancelled mid-action.
        llm.register_function(
            schema.name, handler, cancel_on_interruption=False, timeout_secs=_TOOL_TIMEOUT_SECONDS
        )

    context = LLMContext()
    user_agg, assistant_agg = LLMContextAggregatorPair(context)

    pipeline = Pipeline(
        [
            transport.input(),
            _SpeakerEchoGuard(echo_state, control),
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
    control.bind(asyncio.get_running_loop(), task)
    ui.emit({"type": "state", "state": "idle"})
    ui.emit({"type": "bot_text", "text": "Jarvis online. At your service."})
    await task.queue_frames([LLMRunFrame()])
    await PipelineRunner(handle_sigint=False).run(task)
