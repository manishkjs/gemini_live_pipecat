"""Jarvis: a floating voice agent for the Mac desktop.

Run with `python jarvis_app.py` (or `python jarvis_app.py --list-audio` to
inspect input/output devices such as BlackHole). A glass "Dynamic Island"
window sits at the top of the screen and shows what Jarvis hears, says and
does. On first run (when no Gemini API key is configured), the same window
opens a setup screen to verify and save an AI Studio key and check macOS
permissions. The voice pipeline runs in a background thread; the window must
own the main thread on macOS.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Any
import webbrowser

from loguru import logger

import bot
import jarvis_config
import mac_actions
import mac_permissions

_UI_FILE = Path(__file__).parent / "ui" / "index.html"
_WIDTH, _HEIGHT = 600, 190
# Collapsed pill (364x44 plus 6px top padding) with a little slack, so the
# transparent window doesn't swallow clicks on browser tabs around it.
_COMPACT_WIDTH, _COMPACT_HEIGHT = 380, 56
_SETUP_WIDTH, _SETUP_HEIGHT = 548, 600


def _pill_state_path() -> Path:
    return jarvis_config.get_config_dir() / "pill.json"


def _saved_pill_position() -> tuple[float, float] | None:
    """Saved (centre x, top y) of the pill in global screen points, if on a display."""
    try:
        data = json.loads(_pill_state_path().read_text(encoding="utf-8"))
        cx, top = float(data["gcx"]), float(data["gtop"])
    except Exception:
        return None
    try:
        for d in mac_actions.MacDesktop().list_displays():
            if d.origin_x <= cx < d.origin_x + d.width and d.origin_y <= top < d.origin_y + d.height:
                return cx, top
    except Exception:
        return None
    return None


def _saved_pinned() -> bool:
    try:
        return bool(json.loads(_pill_state_path().read_text(encoding="utf-8")).get("pinned", False))
    except Exception:
        return False


def _jarvis_nswindow():
    import AppKit

    for w in AppKit.NSApp.windows():
        if str(w.title()) == "Jarvis":
            return w
    return None


def _set_pill_frame(
    width: float,
    height: float,
    gcx: float | None = None,
    gtop: float | None = None,
    *,
    clamp_to_screen: bool = False,
    focus: bool = False,
) -> None:
    """Resizes/moves the pill on the main thread using global screen points.

    Global points have their origin at the top-left of the main display (like
    Quartz); Cocoa's origin is the bottom-left, so y is flipped here. Without
    gcx/gtop the pill keeps its current centre and top edge, so a pill the user
    dragged (even to another monitor) stays put.
    """
    import AppKit
    from PyObjCTools import AppHelper

    def _apply() -> None:
        w = _jarvis_nswindow()
        if w is None:
            return
        screens = AppKit.NSScreen.screens()
        if not screens:
            return
        main_h = screens[0].frame().size.height
        f = w.frame()
        cx = gcx if gcx is not None else f.origin.x + f.size.width / 2
        top = gtop if gtop is not None else main_h - (f.origin.y + f.size.height)

        target_w, target_h = float(width), float(height)
        x = cx - target_w / 2
        y_cocoa = main_h - top - target_h

        if clamp_to_screen:
            probe_y = main_h - top - 4
            target_screen = None
            for s in screens:
                sf = s.frame()
                if (
                    sf.origin.x <= cx < sf.origin.x + sf.size.width
                    and sf.origin.y <= probe_y < sf.origin.y + sf.size.height
                ):
                    target_screen = s
                    break
            if target_screen is None:
                target_screen = w.screen() or screens[0]
            vf = target_screen.visibleFrame()
            pad = 12.0
            target_w = min(target_w, max(360.0, vf.size.width - 2 * pad))
            target_h = min(target_h, max(360.0, vf.size.height - 2 * pad))
            x = max(vf.origin.x + pad, min(x, vf.origin.x + vf.size.width - target_w - pad))
            y_cocoa = max(
                vf.origin.y + pad, min(y_cocoa, vf.origin.y + vf.size.height - target_h - pad)
            )

        w.setFrame_display_(AppKit.NSMakeRect(x, y_cocoa, target_w, target_h), True)
        if focus:
            AppKit.NSApp.activateIgnoringOtherApps_(True)
            w.makeKeyAndOrderFront_(None)

    AppHelper.callAfter(_apply)


class WebviewBridge:
    """Connects the pipeline (asyncio thread) and setup logic to the window (main thread)."""

    def __init__(self, *, initial_setup: bool = False, initial_reason: str = "") -> None:
        self.window: Any = None
        self.screen_width = 0
        self.placed = False
        self.pinned = _saved_pinned()
        self.setup_open = initial_setup
        self.setup_reason = initial_reason
        self.pill_pos: tuple[float, float] | None = None
        self._setup_height = _SETUP_HEIGHT
        self._paused_before_setup: bool | None = None
        self._needs_pipeline_restart = False
        self._dragging = False
        self.control = bot.JarvisControl()
        self._pipeline_lock = threading.Lock()
        self._pipeline_thread: threading.Thread | None = None
        self._pipeline_gen = 0
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

    def set_compact(self, compact: bool) -> None:
        """Shrinks the window to the collapsed pill, or grows it to fit the panel."""
        window = self.window
        if not window or self.setup_open:
            return
        width, height = (_COMPACT_WIDTH, _COMPACT_HEIGHT) if compact else (_WIDTH, _HEIGHT)
        try:
            # Grow/shrink around the pill's current centre and top edge, so a
            # pill the user dragged (even to another screen) stays where it is.
            _set_pill_frame(width, height)
        except Exception:
            logger.opt(exception=True).debug("Failed to resize Jarvis window")

    def begin_drag(self, grab_x: float = 0.0, grab_y: float = 0.0) -> None:
        """Moves the pill with the mouse until the button is released.

        grab_x/grab_y is where inside the pill the user pressed (CSS px =
        points), so the pill stays under the pointer exactly at that spot.
        """
        if self.pinned or self._dragging:
            return
        self._dragging = True
        threading.Thread(
            target=self._drag_loop,
            args=(float(grab_x), float(grab_y)),
            name="jarvis-pill-drag",
            daemon=True,
        ).start()

    def _drag_loop(self, grab_x: float, grab_y: float) -> None:
        import AppKit
        import Quartz
        from PyObjCTools import AppHelper

        try:
            w = _jarvis_nswindow()
            if w is None:
                return
            state = Quartz.kCGEventSourceStateCombinedSessionState
            last = None
            while Quartz.CGEventSourceButtonState(state, Quartz.kCGMouseButtonLeft):
                m = AppKit.NSEvent.mouseLocation()  # Cocoa: y grows upwards
                height = w.frame().size.height
                origin = (m.x - grab_x, m.y + grab_y - height)
                if origin != last:
                    AppHelper.callAfter(w.setFrameOrigin_, AppKit.NSMakePoint(*origin))
                    last = origin
                time.sleep(0.008)
            time.sleep(0.15)  # Let the last move land before saving.
            if not self.setup_open:
                self.placed = True
                self.remember_position()
        except Exception:
            logger.opt(exception=True).debug("Pill drag failed")
        finally:
            self._dragging = False

    def toggle_pin(self) -> bool:
        """Locks/unlocks the pill's position; saved across launches."""
        self.pinned = not self.pinned
        self._write_pill_state()
        self.emit({"type": "pinned", "pinned": self.pinned})
        logger.info("Jarvis pill {}", "pinned" if self.pinned else "unpinned")
        return self.pinned

    def _current_window_pill_coords(self) -> tuple[float, float] | None:
        try:
            import Quartz

            own = os.getpid()
            for w in (
                Quartz.CGWindowListCopyWindowInfo(
                    Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
                )
                or []
            ):
                b = w.get("kCGWindowBounds") or {}
                if w.get("kCGWindowOwnerPID") == own and b.get("Width", 0) >= 50:
                    return float(b["X"] + b["Width"] / 2), float(b["Y"])
        except Exception:
            logger.opt(exception=True).debug("Failed to inspect Jarvis window position")
        return None

    def _write_pill_state(self) -> None:
        pos = self.pill_pos
        if pos is None:
            return
        try:
            pill_file = _pill_state_path()
            pill_file.parent.mkdir(parents=True, exist_ok=True)
            pill_file.write_text(
                json.dumps({"gcx": pos[0], "gtop": pos[1], "pinned": self.pinned}),
                encoding="utf-8",
            )
        except Exception:
            logger.opt(exception=True).debug("Failed to save Jarvis pill position")

    def remember_position(self, *_args) -> None:
        """Saves the pill's position so Jarvis reopens where the user left it."""
        if not self.window or not self.placed or self.setup_open:
            return  # Ignore pywebview's own startup placement and setup-screen resizing.
        coords = self._current_window_pill_coords()
        if coords is not None:
            self.pill_pos = coords
            self._write_pill_state()

    # -- setup & permissions controls -------------------------------------

    def is_pipeline_running(self) -> bool:
        thread = self._pipeline_thread
        return bool(thread and thread.is_alive())

    def get_setup_state(self) -> dict[str, Any]:
        """Returns setup UI state without ever exposing raw API key values."""
        reason = self.setup_reason
        try:
            lookup = jarvis_config.lookup_api_key()
        except RuntimeError as exc:
            lookup = jarvis_config.KeyLookup(key=None, source=None)
            if not reason:
                reason = str(exc)

        has_saved = jarvis_config.load_saved_api_key() is not None
        running = self.is_pipeline_running()
        return {
            "setup_open": self.setup_open,
            "has_key": bool(lookup.key),
            "source": lookup.source,
            "has_saved_config_key": has_saved,
            "reason": reason,
            "can_cancel": (
                running
                and not self._needs_pipeline_restart
                and bool(lookup.key)
                and not bool(reason)
            ),
            "pipeline_running": running,
            "permissions": mac_permissions.check_all_permissions(),
            "api_key_url": jarvis_config.GEMINI_API_KEY_URL,
        }

    def validate_and_save_key(self, key: str) -> dict[str, Any]:
        """Validates a Gemini API key against AI Studio and saves it with mode 0600."""
        result = jarvis_config.validate_gemini_api_key(key)
        if not result.ok:
            return {
                "ok": False,
                "message": result.message,
                "error_kind": result.error_kind,
            }

        try:
            jarvis_config.save_api_key(key)
        except Exception as exc:
            safe_err = jarvis_config.redact_secrets(str(exc), key)
            logger.error("Failed to save Jarvis config: {}", safe_err)
            return {
                "ok": False,
                "message": f"Verified key, but couldn't write ~/.jarvis/config.json: {safe_err}",
                "error_kind": "io",
            }

        self.setup_reason = ""
        self._needs_pipeline_restart = True
        logger.info("Gemini API key validated and saved to config.json (0600)")

        try:
            lookup = jarvis_config.lookup_api_key()
            source = lookup.source
        except RuntimeError:
            source = "config"

        if source == "env":
            msg = (
                "Key verified and saved to ~/.jarvis/config.json. "
                "Note: GEMINI_API_KEY in your environment takes precedence until unset."
            )
        elif source == "dotenv":
            msg = (
                "Key verified and saved to ~/.jarvis/config.json. "
                "Note: demos/jarvis/.env takes precedence when present."
            )
        else:
            msg = "Key verified with Gemini and saved to ~/.jarvis/config.json."

        return {
            "ok": True,
            "message": msg,
            "has_key": True,
            "source": source,
            "has_saved_config_key": True,
        }

    def check_permissions(self) -> list[dict[str, Any]]:
        """Re-checks all four macOS permissions."""
        return mac_permissions.check_all_permissions()

    def open_permission_settings(self, permission_id: str) -> bool:
        """Opens the matching macOS System Settings Privacy pane."""
        return mac_permissions.open_privacy_pane(permission_id)

    def open_external(self, url: str) -> bool:
        """Opens an external HTTPS link in the user's default browser (not pywebview)."""
        target = (url or "").strip()
        if not target.startswith("https://"):
            return False
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                webbrowser.open(target, new=2)
            return True
        except Exception:
            logger.opt(exception=True).debug("Failed to open external browser link")
            return False

    def resize_setup(self, height: int) -> None:
        """Fits the native window height to the setup card while in setup mode."""
        if not self.window or not self.setup_open:
            return
        clamped = max(480, min(720, int(height)))
        self._setup_height = clamped
        try:
            _set_pill_frame(_SETUP_WIDTH, clamped, clamp_to_screen=True)
        except Exception:
            logger.opt(exception=True).debug("Failed to resize Jarvis setup window")

    def open_setup(self, reason: str = "") -> dict[str, Any]:
        """Switches the floating pill into the setup screen."""
        if not self.setup_open:
            if self.placed and self.window:
                coords = self._current_window_pill_coords()
                if coords is not None:
                    self.pill_pos = coords
            if self.is_pipeline_running():
                self._paused_before_setup = self.control.paused
                self.control.set_paused(True)

        self.setup_open = True
        self.setup_reason = reason

        if self.window:
            gcx, gtop = self.pill_pos if self.pill_pos else (None, None)
            try:
                _set_pill_frame(
                    _SETUP_WIDTH,
                    self._setup_height,
                    gcx,
                    gtop,
                    clamp_to_screen=True,
                    focus=True,
                )
            except Exception:
                logger.opt(exception=True).debug("Failed to expand window for setup")

        state = self.get_setup_state()
        self.emit({"type": "setup_open", "setup": state})
        return state

    def close_setup(self) -> dict[str, Any]:
        """Returns from setup to the running pill when no restart is needed."""
        try:
            lookup = jarvis_config.lookup_api_key()
        except RuntimeError as exc:
            return {"ok": False, "message": str(exc)}
        if not lookup.key:
            return {"ok": False, "message": "Save a valid Gemini API key before closing setup."}

        self.setup_open = False
        self.setup_reason = ""

        if self._paused_before_setup is not None:
            restore_paused = self._paused_before_setup
            self._paused_before_setup = None
            self.control.set_paused(restore_paused)
            self.emit({"type": "paused", "paused": restore_paused})

        if self.window:
            gcx, gtop = self.pill_pos if self.pill_pos else (None, None)
            try:
                _set_pill_frame(_COMPACT_WIDTH, _COMPACT_HEIGHT, gcx, gtop)
            except Exception:
                logger.opt(exception=True).debug("Failed to shrink window back to pill")
            self.placed = True

        self.emit({"type": "setup_closed"})
        return {"ok": True}

    def start_jarvis(self) -> dict[str, Any]:
        """Transitions from setup to the floating pill and starts (or restarts) voice."""
        try:
            lookup = jarvis_config.lookup_api_key()
        except RuntimeError as exc:
            return {"ok": False, "message": str(exc)}
        if not lookup.key:
            return {"ok": False, "message": "Paste and verify your Gemini API key first."}

        self.setup_open = False
        self.setup_reason = ""
        self._paused_before_setup = None

        if self.window:
            gcx, gtop = self.pill_pos if self.pill_pos else (None, None)
            try:
                _set_pill_frame(_COMPACT_WIDTH, _COMPACT_HEIGHT, gcx, gtop)
            except Exception:
                logger.opt(exception=True).debug("Failed to switch window to pill frame")
            self.placed = True

        self.emit({"type": "setup_closed"})
        self.emit({"type": "paused", "paused": False})

        should_restart = self._needs_pipeline_restart or not self.is_pipeline_running()
        self._needs_pipeline_restart = False
        if should_restart:
            self.emit({"type": "status_text", "text": "Connecting…"})
            threading.Thread(
                target=self.start_pipeline, name="jarvis-pipeline-starter", daemon=True
            ).start()
        else:
            self.control.set_paused(False)
            self.emit({"type": "state", "state": "idle"})
        return {"ok": True}

    def start_pipeline(self) -> None:
        """Starts a fresh voice pipeline thread, cleanly stopping any prior run first."""
        with self._pipeline_lock:
            self._pipeline_gen += 1
            gen = self._pipeline_gen
            prev_control = self.control
            prev_thread = self._pipeline_thread

        if prev_thread and prev_thread.is_alive():
            self.decide(False)
            prev_control.stop()
            prev_thread.join(timeout=4.0)

        with self._pipeline_lock:
            if gen != self._pipeline_gen:
                return
            control = bot.JarvisControl()
            self.control = control
            thread = threading.Thread(
                target=self._pipeline_entry,
                args=(control, gen),
                name=f"jarvis-pipeline-{gen}",
                daemon=True,
            )
            self._pipeline_thread = thread
            thread.start()

    def _pipeline_entry(self, control: bot.JarvisControl, gen: int) -> None:
        self._ready.wait(timeout=10)
        try:
            asyncio.run(bot.run_jarvis(self, control))
        except jarvis_config.NoApiKeyError as exc:
            if gen != self._pipeline_gen:
                return
            logger.warning("No Gemini API key found; showing setup")
            self.open_setup(reason=str(exc))
        except jarvis_config.ApiKeyRejectedError as exc:
            if gen != self._pipeline_gen:
                return
            safe_reason = jarvis_config.redact_secrets(str(exc))
            logger.warning("Gemini API key rejected on connect: {}", safe_reason)
            self.open_setup(reason=safe_reason)
        except Exception as exc:
            if gen != self._pipeline_gen:
                return
            auth_reason = jarvis_config.classify_gemini_auth_error(exc, str(exc))
            if auth_reason:
                logger.warning("Gemini API key rejected: {}", auth_reason)
                self.open_setup(reason=auth_reason)
                return
            safe_err = jarvis_config.redact_secrets(str(exc))
            logger.error("Jarvis pipeline stopped: {}", safe_err)
            self.emit({"type": "error", "text": f"Stopped: {safe_err}"})

    def stop(self) -> None:
        """Stops the pipeline and closes the floating Jarvis window."""
        logger.info("Stopping Jarvis from UI")
        with self._pipeline_lock:
            self._pipeline_gen += 1
        # Deny any open approval so the waiting tool call returns before cancel.
        self.decide(False)
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

    def set_compact(self, compact: bool) -> None:
        self._bridge.set_compact(compact)

    def begin_drag(self, grab_x: float = 0.0, grab_y: float = 0.0) -> None:
        self._bridge.begin_drag(grab_x, grab_y)

    def toggle_pin(self) -> bool:
        return self._bridge.toggle_pin()

    def stop(self) -> None:
        self._bridge.stop()

    def get_setup_state(self) -> dict[str, Any]:
        return self._bridge.get_setup_state()

    def validate_and_save_key(self, key: str) -> dict[str, Any]:
        return self._bridge.validate_and_save_key(key)

    def check_permissions(self) -> list[dict[str, Any]]:
        return self._bridge.check_permissions()

    def open_permission_settings(self, permission_id: str) -> bool:
        return self._bridge.open_permission_settings(permission_id)

    def open_external(self, url: str) -> bool:
        return self._bridge.open_external(url)

    def resize_setup(self, height: int) -> None:
        self._bridge.resize_setup(height)

    def open_setup(self) -> dict[str, Any]:
        return self._bridge.open_setup()

    def close_setup(self) -> dict[str, Any]:
        return self._bridge.close_setup()

    def start_jarvis(self) -> dict[str, Any]:
        return self._bridge.start_jarvis()


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
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Directory for config.json and pill.json (default: ~/.jarvis).",
    )
    parser.add_argument(
        "--no-dotenv",
        action="store_true",
        help="Ignore demos/jarvis/.env when resolving settings and API keys.",
    )
    args = parser.parse_args()
    if args.list_audio:
        _print_audio_devices()
        return

    if args.config_dir is not None:
        os.environ["JARVIS_CONFIG_DIR"] = str(args.config_dir.expanduser().resolve())
    if args.no_dotenv:
        os.environ["JARVIS_NO_DOTENV"] = "1"

    import webview

    jarvis_config.load_non_secret_dotenv_into_environ(Path(__file__).parent / ".env")

    initial_reason = ""
    try:
        initial_lookup = jarvis_config.lookup_api_key()
        needs_setup = initial_lookup.key is None
    except RuntimeError as exc:
        needs_setup = True
        initial_reason = str(exc)

    bridge = WebviewBridge(initial_setup=needs_setup, initial_reason=initial_reason)

    screen = webview.screens[0]
    bridge.screen_width = int(screen.width)
    init_w = _SETUP_WIDTH if needs_setup else _COMPACT_WIDTH
    init_h = _SETUP_HEIGHT if needs_setup else _COMPACT_HEIGHT
    ui_url = _UI_FILE.as_uri() + ("?mode=setup" if needs_setup else "")

    window = webview.create_window(
        "Jarvis",
        url=ui_url,
        js_api=_JsApi(bridge),
        width=init_w,
        height=init_h,
        x=int((screen.width - init_w) / 2),
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
    window.events.moved += bridge.remember_position

    # Place the pill ourselves once the window exists (pywebview's own x/y is
    # relative to whichever screen it picks and can't target other monitors):
    # the saved spot, else the top centre of the main display.
    saved = _saved_pill_position()
    if saved is None:
        main_disp = mac_actions.MacDesktop().list_displays()[0]
        saved = (main_disp.origin_x + main_disp.width / 2, main_disp.origin_y + 34)
    bridge.pill_pos = saved

    def _place() -> None:
        time.sleep(0.4)  # Let pywebview finish its own initial placement first.
        if bridge.setup_open:
            _set_pill_frame(
                _SETUP_WIDTH,
                bridge._setup_height,
                saved[0],
                max(saved[1], 48.0),
                clamp_to_screen=True,
                focus=True,
            )
            time.sleep(0.25)
            bridge.emit({"type": "pinned", "pinned": bridge.pinned})
            bridge.emit({"type": "setup_open", "setup": bridge.get_setup_state()})
        else:
            _set_pill_frame(_COMPACT_WIDTH, _COMPACT_HEIGHT, saved[0], saved[1])
            time.sleep(0.3)
            bridge.placed = True  # From now on, moves are the user dragging the pill.
            bridge.emit({"type": "pinned", "pinned": bridge.pinned})

    window.events.shown += lambda: threading.Thread(target=_place, daemon=True).start()

    if not needs_setup:
        bridge.start_pipeline()

    try:
        webview.start()
    except BaseException:
        # os._exit below skips normal traceback printing, so log it first.
        logger.exception("Jarvis window crashed")
        raise
    finally:
        bridge.control.stop()
        sys.stdout.flush()
        sys.stderr.flush()
        # Non-daemon worker threads in audio/SDK libraries can hang Python's
        # interpreter shutdown (wait_for_thread_shutdown) after the window closes.
        os._exit(0)


if __name__ == "__main__":
    main()
