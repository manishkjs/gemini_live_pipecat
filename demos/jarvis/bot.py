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
    InputImageRawFrame,
    LLMRunFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

import mac_actions

DEFAULT_MODEL = "gemini-3.8-live"
DEFAULT_VOICE = "Charon"
_TOOL_TIMEOUT_SECONDS = 120

SYSTEM_INSTRUCTION = """\
You are Jarvis, a calm, witty voice assistant operating a Mac desktop.
You can see the screen through screenshots and act with the tools provided.

How you work:
- Keep spoken replies short: one or two sentences. Narrate what you are doing
  as you do it ("Opening draw.io... pasting the architecture now").
- Before clicking, call look_at_screen unless you just received a fresh
  screenshot. Coordinates are pixels in the latest screenshot.
- Prefer open_app, open_url, meet_join, meet_action, open_drawio and press_keys
  over raw coordinate clicking whenever they do the job.
- Google Meet: Use meet_join(meeting, use_jarvis_profile=True) to join in an
  isolated Chrome profile as a separate persona ("Jarvis"). On the pre-join
  screen, enter "Jarvis" if asked for a name, check mic state, and click Join.
  In a group call, stay quiet unless addressed as "Jarvis".
- Architecture diagrams: Use open_drawio(mermaid_code) with clean Mermaid
  syntax. It opens draw.io and copies your Mermaid code to the clipboard.
  Then click Arrange -> Insert -> Advanced -> Mermaid (or '+' -> Mermaid),
  press cmd+v, and click Insert.
- Mobile apps (e.g. Swiggy): If an Android device/emulator is connected, use
  mobile_open_app / mobile_tap / mobile_type / mobile_swipe. If not, open
  iPhone Mirroring or the emulator/browser window and use Mac desktop tools.
- After each action you get a fresh screenshot. Check that it worked.
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


class _UiTap(FrameProcessor):
    """Passes every frame through and mirrors the interesting ones to the UI."""

    def __init__(self, ui: UiBridge, **kwargs):
        super().__init__(**kwargs)
        self._ui = ui

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            self._ui.emit({"type": "user_text", "text": frame.text})
        elif isinstance(frame, (TTSTextFrame, LLMTextFrame)):
            self._ui.emit({"type": "bot_text", "text": frame.text})
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._ui.emit({"type": "state", "state": "listening"})
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._ui.emit({"type": "state", "state": "speaking"})
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._ui.emit({"type": "state", "state": "idle"})
        elif isinstance(frame, FunctionCallInProgressFrame):
            self._ui.emit({"type": "state", "state": "acting"})
        await self.push_frame(frame, direction)


class JarvisTools:
    """Desktop, Meet, draw.io, and mobile tools with the approval gate built in."""

    # Wait for the UI to repaint before taking the follow-up screenshot. Must
    # also exceed the 1 s video throttle in GeminiLiveLLMService.
    _SETTLE_SECONDS = 1.1

    def __init__(self, desktop: mac_actions.MacDesktop, feeder: _ScreenFeeder, ui: UiBridge):
        self._desktop = desktop
        self._feeder = feeder
        self._ui = ui

    async def _look(self) -> dict[str, Any]:
        shot = await asyncio.to_thread(self._desktop.screenshot)
        await self._feeder.send_screenshot(shot)
        return {"screenshot_size": list(shot.size)}

    async def _act(
        self,
        params: FunctionCallParams,
        label: str,
        action: Callable[[], Any],
        verdict: mac_actions.RiskVerdict,
        extra: dict[str, Any] | None = None,
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
        screen = await self._look()
        payload = {"status": "done", "action": label, **screen}
        if extra:
            payload.update(extra)
        await params.result_callback(payload)

    # -- desktop handlers ---------------------------------------------------

    async def look_at_screen(self, params: FunctionCallParams) -> None:
        """Captures a fresh screenshot and returns its dimensions."""
        self._ui.emit({"type": "action", "label": "Looking at the screen"})
        await params.result_callback({"status": "done", **(await self._look())})

    async def click(self, params: FunctionCallParams) -> None:
        """Clicks a screen coordinate with a safety check on the target."""
        args = params.arguments
        target = args.get("target_description", "")
        x_coord, y_coord = float(args["x"]), float(args["y"])
        is_double = bool(args.get("double", False))
        await self._act(
            params,
            f"Click {target}".strip(),
            lambda: self._desktop.click(x_coord, y_coord, is_double),
            mac_actions.assess_click(target),
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
        )

    async def open_url(self, params: FunctionCallParams) -> None:
        """Opens a URL in the default browser."""
        url = params.arguments["url"]
        await self._act(
            params,
            f"Open {url}",
            lambda: self._desktop.open_url(url),
            mac_actions.RiskVerdict(False),
        )

    async def scroll(self, params: FunctionCallParams) -> None:
        """Scrolls under the pointer."""
        amount = int(params.arguments.get("amount", -5))
        await self._act(
            params,
            "Scroll",
            lambda: self._desktop.scroll(amount),
            mac_actions.RiskVerdict(False),
        )

    # -- Google Meet & draw.io handlers -------------------------------------

    async def meet_join(self, params: FunctionCallParams) -> None:
        """Opens a Google Meet URL in Jarvis's isolated Chrome profile."""
        args = params.arguments
        url = mac_actions.normalize_meet_url(args["meeting"])
        use_jarvis_profile = bool(args.get("use_jarvis_profile", True))

        def _launch() -> None:
            if use_jarvis_profile:
                self._desktop.open_chrome_profile(url)
            else:
                self._desktop.open_url(url)

        await self._act(
            params,
            f"Open Meet {url}",
            _launch,
            mac_actions.RiskVerdict(False),
            extra={"url": url, "isolated_profile": use_jarvis_profile},
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
        await self._act(
            params,
            f"Meet: {action_name}",
            lambda: self._desktop.press_keys(shortcut),
            verdict,
        )

    async def open_drawio(self, params: FunctionCallParams) -> None:
        """Opens draw.io and optionally copies Mermaid diagram code to clipboard."""
        mermaid_code = params.arguments.get("mermaid_code", "")
        copied = bool(mermaid_code.strip())
        next_step = (
            "Click Arrange -> Insert -> Advanced -> Mermaid, paste (cmd+v), then Insert."
            if copied
            else "Draw.io is open."
        )
        await self._act(
            params,
            "Open draw.io",
            lambda: self._desktop.open_drawio(mermaid_code),
            mac_actions.RiskVerdict(False),
            extra={"mermaid_copied_to_clipboard": copied, "next_step": next_step},
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
                "Take a fresh screenshot of the Mac screen.",
                self.look_at_screen,
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
                "open_url",
                "Open a URL in the default browser.",
                self.open_url,
                {"url": {"type": "string"}},
                ["url"],
            ),
            make_tool(
                "scroll",
                "Scroll under the pointer. Negative scrolls down.",
                self.scroll,
                {"amount": {"type": "integer"}},
            ),
            make_tool(
                "meet_join",
                "Open a Google Meet URL or code, optionally in Jarvis's own Chrome profile.",
                self.meet_join,
                {
                    "meeting": {"type": "string", "description": "Meet URL or code xxx-yyyy-zzz."},
                    "use_jarvis_profile": {"type": "boolean"},
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
                "Open draw.io (app.diagrams.net) and copy optional Mermaid code to the clipboard.",
                self.open_drawio,
                {"mermaid_code": {"type": "string"}},
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


async def run_jarvis(ui: UiBridge) -> None:
    """Builds and runs the pipeline until cancelled."""
    model = os.getenv("JARVIS_MODEL", DEFAULT_MODEL)
    logger.info("Starting Jarvis on {} (AI Studio)", model)

    input_idx, output_idx = _resolve_transport_audio_indices()
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
        ),
        tools=ToolsSchema(standard_tools=[schema for schema, _ in definitions]),
        http_options=HttpOptions(api_version="v1alpha"),
    )
    for schema, handler in definitions:
        # Desktop actions must not be cut off halfway by a barge-in, and the
        # approval gate can wait up to two minutes for the user.
        llm.register_function(
            schema.name, handler, cancel_on_interruption=False, timeout_secs=_TOOL_TIMEOUT_SECONDS
        )

    context = LLMContext()
    user_agg, assistant_agg = LLMContextAggregatorPair(context)

    pipeline = Pipeline(
        [
            transport.input(),
            user_agg,
            _UiTap(ui),
            feeder,
            llm,
            _UiTap(ui),
            transport.output(),
            assistant_agg,
        ]
    )
    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=True))
    ui.emit({"type": "state", "state": "idle"})
    ui.emit({"type": "bot_text", "text": "Jarvis online. At your service."})
    await task.queue_frames([LLMRunFrame()])
    await PipelineRunner(handle_sigint=False).run(task)
