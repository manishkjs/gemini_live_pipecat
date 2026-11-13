"""Jarvis voice pipeline: local mic/speaker -> Gemini Live -> macOS tools.

Runs entirely on the Mac with Pipecat's LocalAudioTransport. Gemini Live hears
the user, sees screenshots we push into the stream, and calls the desktop tools
below. Risky actions pause until the user approves them in the Jarvis UI.

Only the Gemini Developer API (AI Studio, `GEMINI_API_KEY`) is used. Vertex AI
is deliberately not supported.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, Protocol

from google.genai.types import HttpOptions
from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
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
You are Jarvis, a calm, witty voice assistant that operates the user's Mac.
You can see the screen through screenshots and act with the tools provided.

How you work:
- Keep spoken replies short: one or two sentences. Narrate what you are doing
  as you do it ("Opening Terminal... checking the logs now").
- Before clicking, call look_at_screen unless you just received a fresh
  screenshot. Coordinates are pixels in the latest screenshot.
- Prefer open_app, open_url and press_keys over clicking when they do the job.
- After each action you get a fresh screenshot. Check that it worked.
- If the user interrupts you, stop and follow the new instruction.
- Some actions need the user's approval. If a tool says the action is waiting
  for approval or was denied, tell the user plainly and do not try to work
  around it.
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
    """Desktop tools exposed to Gemini, with the approval gate built in."""

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
        await params.result_callback({"status": "done", "action": label, **screen})

    # -- handlers -----------------------------------------------------------

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
        ]


def _resolve_api_key() -> str:
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true"):
        raise RuntimeError("Jarvis does not use Vertex AI. Unset GOOGLE_GENAI_USE_VERTEXAI.")
    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY (AI Studio key) in demos/jarvis/.env")
    return key


async def run_jarvis(ui: UiBridge) -> None:
    """Builds and runs the pipeline until cancelled."""
    model = os.getenv("JARVIS_MODEL", DEFAULT_MODEL)
    logger.info("Starting Jarvis on {} (AI Studio)", model)

    transport = LocalAudioTransport(
        LocalAudioTransportParams(audio_in_enabled=True, audio_out_enabled=True)
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

