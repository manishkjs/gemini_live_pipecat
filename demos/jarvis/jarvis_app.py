"""Jarvis: a floating voice agent for the Mac desktop.

Run with `python jarvis_app.py` (or `python jarvis_app.py --list-audio` to
inspect input/output devices such as BlackHole). A glass "Dynamic Island"
window sits at the top of the screen and shows what Jarvis hears, says and
does. The voice pipeline runs in a background thread; the window must own the
main thread on macOS.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import sys
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger

import bot
import mac_actions

_UI_FILE = Path(__file__).parent / "ui" / "index.html"
_WIDTH, _HEIGHT = 600, 190


class WebviewBridge:
    """Connects the pipeline (asyncio thread) to the window (main thread)."""

    def __init__(self) -> None:
        self.window: Any = None
        self.control = bot.JarvisControl()
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: asyncio.Future[bool] | None = None
        self._ui_queue: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        threading.Thread(target=self._ui_worker, name="jarvis-ui-bridge", daemon=True).start()

    # -- called by the window ---------------------------------------------

    def mark_ready(self) -> None:
        """Signals that the webview DOM has loaded and can receive JS calls."""
        self._ready.set()

    def decide(self, approved: bool) -> None:
        """Approve/Deny button handler, exposed to JavaScript."""
        loop, pending = self._loop, self._pending
        if loop and pending and not pending.done():
            loop.call_soon_threadsafe(pending.set_result, bool(approved))

    def toggle_pause(self) -> bool:
        """Toggles Jarvis mic/speech pause state, exposed to JavaScript."""
        paused = self.control.set_paused(not self.control.paused)
        self.emit({"type": "paused", "paused": paused})
        logger.info("Jarvis {}", "paused" if paused else "resumed")
        return paused

    def stop(self) -> None:
        """Stops the pipeline and closes the floating Jarvis window."""
        logger.info("Stopping Jarvis from UI")
        self.control.stop()
        # Fallback in case Cocoa runloop doesn't unwind promptly after window.destroy().
        timer = threading.Timer(1.5, lambda: os._exit(0))
        timer.daemon = True
        timer.start()
        window = self.window
        if window:
            try:
                window.destroy()
            except Exception:
                logger.opt(exception=True).debug("Failed to destroy Jarvis window")

    # -- called by the pipeline (UiBridge protocol) -------------------------

    def emit(self, event: dict[str, Any]) -> None:
        """Queues a JSON event payload for the floating pill UI without blocking asyncio."""
        self._ui_queue.put_nowait(event)

    def _ui_worker(self) -> None:
        """Flushes queued UI events on a dedicated thread so evaluate_js never stalls audio."""
        self._ready.wait()
        while True:
            event = self._ui_queue.get()
            window = self.window
            if not window:
                continue
            try:
                window.evaluate_js(f"window.jarvis.update({json.dumps(event)})")
            except Exception:
                logger.opt(exception=True).debug("Failed to push event to Jarvis webview")

    async def request_approval(self, action: str, reason: str) -> bool:
        """Suspends until the user approves or denies the action in the UI."""
        self._loop = asyncio.get_running_loop()
        self._pending = self._loop.create_future()
        logger.warning("Approval needed: {} ({})", action, reason)
        try:
            return await self._pending
        finally:
            self._pending = None


class _JsApi:
    """Exposes UI control methods to JavaScript so pywebview skips the window ref."""

    def __init__(self, bridge: WebviewBridge) -> None:
        self._bridge = bridge

    def decide(self, approved: bool) -> None:
        self._bridge.decide(approved)

    def toggle_pause(self) -> bool:
        return self._bridge.toggle_pause()

    def stop(self) -> None:
        self._bridge.stop()


def _run_pipeline(bridge: WebviewBridge) -> None:
    bridge._ready.wait(timeout=10)
    try:
        asyncio.run(bot.run_jarvis(bridge, bridge.control))
    except Exception as exc:
        logger.exception("Jarvis pipeline stopped")
        bridge.emit({"type": "error", "text": f"Stopped: {exc}"})


def _print_audio_devices() -> None:
    for idx, dev in enumerate(mac_actions.list_audio_devices()):
        ins = dev.get("maxInputChannels", 0)
        outs = dev.get("maxOutputChannels", 0)
        print(f"[{idx}] {dev.get('name')} (in={ins}, out={outs})")


def main() -> None:
    """Parses CLI flags and starts either audio listing or the floating UI."""
    parser = argparse.ArgumentParser(description="Jarvis Mac desktop voice agent")
    parser.add_argument(
        "--list-audio",
        action="store_true",
        help="Print available PyAudio input/output device indexes and exit.",
    )
    args = parser.parse_args()
    if args.list_audio:
        _print_audio_devices()
        return

    import webview

    load_dotenv(Path(__file__).parent / ".env")
    bridge = WebviewBridge()

    screen = webview.screens[0]
    window = webview.create_window(
        "Jarvis",
        url=_UI_FILE.as_uri(),
        js_api=_JsApi(bridge),
        width=_WIDTH,
        height=_HEIGHT,
        x=int((screen.width - _WIDTH) / 2),
        y=0,
        frameless=True,
        easy_drag=False,
        transparent=True,
        on_top=True,
        resizable=False,
        shadow=False,
        background_color="#000000",
    )
    bridge.window = window
    window.events.loaded += bridge.mark_ready

    threading.Thread(target=_run_pipeline, args=(bridge,), daemon=True).start()
    try:
        webview.start()
    finally:
        bridge.control.stop()
        sys.stdout.flush()
        sys.stderr.flush()
        # Non-daemon worker threads in audio/SDK libraries can hang Python's
        # interpreter shutdown (wait_for_thread_shutdown) after the window closes.
        os._exit(0)


if __name__ == "__main__":
    main()
