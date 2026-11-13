"""Native macOS and optional Android/ADB "hands and eyes" for Jarvis.

Screenshots use `screencapture`, mouse clicks post CoreGraphics events, and
typing goes through System Events. All of these work in any macOS app, not
only the browser. When an Android device or emulator is connected via `adb`,
mobile_* helpers can also drive apps like Swiggy directly.

The safety checks and command builders in the top half of this module are pure
Python so they can be unit-tested on any OS.
"""

from __future__ import annotations

import dataclasses
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# Safety gate (pure Python, testable anywhere)
# ---------------------------------------------------------------------------

_RISKY_TEXT_PATTERNS = (
    r"\brm\s+-(?=[a-z]*r)(?=[a-z]*f)[a-z]+",  # rm -rf, rm -fr
    r"\bdrop\s+(table|database|schema)\b",
    r"\btruncate\s+table\b",
    r"\bdelete\s+from\b(?!.*\bwhere\b)",  # DELETE without WHERE
    r"\bterraform\s+destroy\b",
    r"\bkubectl\s+delete\b",
    r"\bgcloud\b.*\bdelete\b",
    r"\bgit\s+push\b.*(--force|-f\b)",
    r"\bgit\s+reset\s+--hard\b",
    r"\bshutdown\b|\breboot\b",
)

_RISKY_TARGET_WORDS = (
    "delete", "remove", "destroy", "drop", "pay", "purchase", "buy",
    "order", "checkout", "transfer", "wire", "refund", "send", "submit",
    "deploy", "publish", "merge", "approve", "production", "prod",
)


@dataclasses.dataclass(frozen=True)
class RiskVerdict:
    """Result of a safety check on a proposed desktop or mobile action."""

    risky: bool
    reason: str = ""


def assess_text(text: str) -> RiskVerdict:
    """Checks text that Jarvis is about to type (e.g. into a terminal)."""
    lowered = text.lower()
    for pattern in _RISKY_TEXT_PATTERNS:
        if re.search(pattern, lowered):
            return RiskVerdict(True, f"matches destructive pattern `{pattern}`")
    return RiskVerdict(False)


def assess_click(target_description: str) -> RiskVerdict:
    """Checks the description the model gave for the UI element to click."""
    words = set(re.findall(r"[a-z]+", target_description.lower()))
    hits = sorted(words.intersection(_RISKY_TARGET_WORDS))
    if hits:
        return RiskVerdict(True, f"button looks consequential ({', '.join(hits)})")
    return RiskVerdict(False)


# ---------------------------------------------------------------------------
# Pure helpers: key combos, Meet/draw.io URLs, Chrome profile, audio, ADB
# ---------------------------------------------------------------------------

_MODIFIERS = {
    "cmd": "command down", "command": "command down",
    "ctrl": "control down", "control": "control down",
    "opt": "option down", "option": "option down", "alt": "option down",
    "shift": "shift down",
}

_KEY_CODES = {
    "enter": 36, "return": 36, "tab": 48, "space": 49, "delete": 51,
    "backspace": 51, "escape": 53, "esc": 53, "left": 123, "right": 124,
    "down": 125, "up": 126,
}

# Verified macOS Google Meet shortcuts.
MEET_SHORTCUTS = {
    "toggle_mic": "cmd+d",
    "toggle_camera": "cmd+e",
    "raise_hand": "ctrl+cmd+h",
    "open_chat": "ctrl+cmd+c",
    "leave": "cmd+w",
}

_COMMON_ANDROID_PACKAGES = {
    "swiggy": "in.swiggy.android",
    "zomato": "com.application.zomato",
    "chrome": "com.android.chrome",
    "settings": "com.android.settings",
}


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def key_combo_to_applescript(combo: str) -> str:
    """Turns 'cmd+shift+t' or 'enter' into a System Events AppleScript line."""
    parts = [part.strip().lower() for part in combo.split("+") if part.strip()]
    if not parts:
        raise ValueError("empty key combo")
    *mods, key = parts
    unknown = [mod for mod in mods if mod not in _MODIFIERS]
    if unknown:
        raise ValueError(f"unknown modifier(s): {unknown}")
    using = ""
    if mods:
        using = " using {" + ", ".join(_MODIFIERS[mod] for mod in mods) + "}"
    if key in _KEY_CODES:
        action = f"key code {_KEY_CODES[key]}"
    elif len(key) == 1:
        action = f"keystroke {_applescript_string(key)}"
    else:
        raise ValueError(f"unknown key: {key!r}")
    return f'tell application "System Events" to {action}{using}'


def normalize_meet_url(meeting: str) -> str:
    """Normalizes a Meet code ('abc-defg-hij') or URL into a meet.google.com URL."""
    cleaned = meeting.strip()
    if not cleaned:
        raise ValueError("empty meeting code or URL")
    if re.match(r"^https?://", cleaned):
        return cleaned
    if cleaned.startswith("meet.google.com/"):
        return "https://" + cleaned
    return f"https://meet.google.com/{cleaned.lstrip('/')}"


def drawio_url() -> str:
    """Returns the draw.io URL that skips the startup storage dialog."""
    return "https://app.diagrams.net/?splash=0"


def chrome_profile_command(url: str, profile_dir: str) -> list[str]:
    """Builds the macOS `open -na` command for a dedicated Chrome profile."""
    return [
        "open",
        "-na",
        "Google Chrome",
        "--args",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        url,
    ]


def resolve_audio_device_index(
    spec: str | None,
    devices: Sequence[Mapping[str, Any]],
    direction: str,
) -> int | None:
    """Resolves a device index or substring (e.g. 'BlackHole 2ch') from PyAudio info."""
    if not spec or not spec.strip():
        return None
    cleaned = spec.strip()
    channel_key = "maxInputChannels" if direction == "input" else "maxOutputChannels"
    if cleaned.isdigit():
        idx = int(cleaned)
        if 0 <= idx < len(devices) and devices[idx].get(channel_key, 0) > 0:
            return idx
        raise ValueError(f"Audio {direction} device index {idx} is unavailable")
    needle = cleaned.lower()
    for idx, dev in enumerate(devices):
        if dev.get(channel_key, 0) > 0 and needle in str(dev.get("name", "")).lower():
            return idx
    raise ValueError(f"No {direction} audio device matching {cleaned!r}")


def adb_device_serial(adb_output: str) -> str | None:
    """Parses `adb devices` stdout and returns the first online serial."""
    for line in adb_output.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    return None


def resolve_android_package(app: str) -> str:
    """Maps a friendly mobile app name like 'swiggy' to its Android package."""
    cleaned = app.strip()
    return _COMMON_ANDROID_PACKAGES.get(cleaned.lower(), cleaned)


# Characters the Android shell would interpret inside `input text`.
_ADB_SHELL_SPECIAL = re.compile(r"([\\\"'()<>|;&*~$`!?#\[\]{}])")


def adb_input_text(text: str) -> str:
    """Escapes text for `adb shell input text` (spaces become %s)."""
    return _ADB_SHELL_SPECIAL.sub(r"\\\1", text).replace(" ", "%s")


def frontmost_pid_script(pid: int) -> str:
    """Returns AppleScript that brings the process with this pid to the front."""
    return (
        'tell application "System Events" to set frontmost of '
        f"(first process whose unix id is {int(pid)}) to true"
    )


# ---------------------------------------------------------------------------
# Real macOS + optional ADB actions
# ---------------------------------------------------------------------------


def _osascript(script: str) -> None:
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True)


def list_audio_devices() -> list[dict[str, Any]]:
    """Lists PyAudio devices on this machine."""
    import pyaudio

    pa = pyaudio.PyAudio()
    try:
        return [pa.get_device_info_by_index(idx) for idx in range(pa.get_device_count())]
    finally:
        pa.terminate()


@dataclasses.dataclass(frozen=True)
class DisplayInfo:
    """Geometry for a macOS display (Quartz points and 1-based screencapture index)."""

    index: int
    display_id: int
    is_main: bool
    origin_x: float
    origin_y: float
    width: float
    height: float


def map_screenshot_point(
    x: float,
    y: float,
    origin_x: float,
    origin_y: float,
    points_per_pixel: float,
) -> tuple[float, float]:
    """Maps screenshot pixel coordinates back to global Quartz screen points."""
    return origin_x + x * points_per_pixel, origin_y + y * points_per_pixel


@dataclasses.dataclass
class Screenshot:
    """A downscaled screenshot plus what is needed to map clicks back."""

    rgb_bytes: bytes
    size: tuple[int, int]
    points_per_pixel: float  # screen points per screenshot pixel
    display: int = 1
    display_count: int = 1


class MacDesktop:
    """Eyes and hands on the local macOS desktop (plus optional ADB mobile device)."""

    def __init__(self, max_width: int = 1536):
        self._max_width = max_width
        self._points_per_pixel = 1.0
        self._active_display = 1
        self._origin_x = 0.0
        self._origin_y = 0.0
        # display index -> (origin_x, origin_y, points_per_pixel) of its last screenshot.
        self._geometry: dict[int, tuple[float, float, float]] = {}

    # -- eyes ---------------------------------------------------------------

    def list_displays(self) -> list[DisplayInfo]:
        """Returns active macOS displays ordered by 1-based `screencapture -D` index."""
        import Quartz

        err, ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
        if err != 0 or not count:
            main_id = Quartz.CGMainDisplayID()
            bounds = Quartz.CGDisplayBounds(main_id)
            return [
                DisplayInfo(
                    index=1,
                    display_id=int(main_id),
                    is_main=True,
                    origin_x=float(bounds.origin.x),
                    origin_y=float(bounds.origin.y),
                    width=float(bounds.size.width),
                    height=float(bounds.size.height),
                )
            ]

        main_id = Quartz.CGMainDisplayID()
        displays: list[DisplayInfo] = []
        for idx, display_id in enumerate(ids[:count], start=1):
            bounds = Quartz.CGDisplayBounds(display_id)
            displays.append(
                DisplayInfo(
                    index=idx,
                    display_id=int(display_id),
                    is_main=(display_id == main_id),
                    origin_x=float(bounds.origin.x),
                    origin_y=float(bounds.origin.y),
                    width=float(bounds.size.width),
                    height=float(bounds.size.height),
                )
            )
        return displays

    def _resolve_display(self, display: int | None) -> tuple[DisplayInfo, int]:
        displays = self.list_displays()
        target_index = self._active_display if display is None else int(display)
        if target_index < 1 or target_index > len(displays):
            raise ValueError(
                f"Display {target_index} not found (connected displays: 1..{len(displays)})"
            )
        return displays[target_index - 1], len(displays)

    def screenshot(self, display: int | None = None) -> Screenshot:
        """Captures and downscales the requested (or currently active) display."""
        from PIL import Image  # Imported lazily so tests don't need Pillow.

        info, display_count = self._resolve_display(display)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            subprocess.run(
                ["screencapture", "-x", "-C", "-D", str(info.index), str(path)],
                check=True,
            )
            image = Image.open(path).convert("RGB")
            image.load()

        if image.width > self._max_width:
            ratio = self._max_width / image.width
            image = image.resize((self._max_width, int(image.height * ratio)))
        self._active_display = info.index
        self._origin_x = info.origin_x
        self._origin_y = info.origin_y
        self._points_per_pixel = info.width / image.width
        self._geometry[info.index] = (info.origin_x, info.origin_y, self._points_per_pixel)
        return Screenshot(
            image.tobytes(),
            image.size,
            self._points_per_pixel,
            display=info.index,
            display_count=display_count,
        )

    # -- hands --------------------------------------------------------------

    def to_global_point(
        self, x: float, y: float, display: int | None = None
    ) -> tuple[float, float]:
        """Maps screenshot pixels on `display` (default: active) to global screen points.

        Uses the geometry of that display's own last screenshot, so coordinates
        are never scaled with another monitor's origin or resolution. Switches
        the active display so the follow-up screenshot shows the same screen.
        """
        index = self._active_display if display is None else int(display)
        geometry = self._geometry.get(index)
        if geometry is None:
            raise ValueError(
                f"No screenshot of display {index} yet; call look_at_screen(display={index}) first"
            )
        self._active_display = index
        self._origin_x, self._origin_y, self._points_per_pixel = geometry
        return map_screenshot_point(x, y, *geometry)

    def _move_pointer(self, px: float, py: float) -> None:
        import Quartz

        Quartz.CGEventPost(
            Quartz.kCGHIDEventTap,
            Quartz.CGEventCreateMouseEvent(
                None,
                Quartz.kCGEventMouseMoved,
                Quartz.CGPointMake(px, py),
                Quartz.kCGMouseButtonLeft,
            ),
        )

    def click(
        self,
        x: float,
        y: float,
        double: bool = False,
        display: int | None = None,
    ) -> tuple[float, float]:
        """Clicks at (x, y) given in pixel coordinates of that display's last screenshot."""
        import Quartz

        px, py = self.to_global_point(x, y, display)
        point = Quartz.CGPointMake(px, py)
        clicks = 2 if double else 1
        self._move_pointer(px, py)
        time.sleep(0.05)
        for click_index in range(1, clicks + 1):
            for event_type in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
                event = Quartz.CGEventCreateMouseEvent(
                    None, event_type, point, Quartz.kCGMouseButtonLeft
                )
                Quartz.CGEventSetIntegerValueField(
                    event, Quartz.kCGMouseEventClickState, click_index
                )
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
                time.sleep(0.04)
            if double and click_index == 1:
                time.sleep(0.05)
        return px, py

    def copy_to_clipboard(self, text: str) -> None:
        """Copies text to the macOS clipboard via pbcopy."""
        subprocess.run(["pbcopy"], input=text, text=True, check=True)

    def _read_clipboard(self) -> str | None:
        try:
            res = subprocess.run(["pbpaste"], check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError):
            return None
        return res.stdout

    def type_text(self, text: str, press_enter: bool = False) -> None:
        """Types text. Long text is pasted, then the previous clipboard is restored."""
        if len(text) > 40 or "\n" in text:
            saved = self._read_clipboard()
            self.copy_to_clipboard(text)
            _osascript(key_combo_to_applescript("cmd+v"))
            if saved is not None:
                time.sleep(0.3)  # Let the target app read the clipboard first.
                self.copy_to_clipboard(saved)
        else:
            _osascript(f'tell application "System Events" to keystroke {_applescript_string(text)}')
        if press_enter:
            _osascript(key_combo_to_applescript("enter"))

    def press_keys(self, combo: str) -> None:
        """Presses a key or shortcut via System Events."""
        _osascript(key_combo_to_applescript(combo))

    def focus_meet_window(self, profile_dir: str | None = None) -> None:
        """Brings Jarvis's Chrome (isolated profile if running) to the front.

        Meet shortcuts go to whichever app is frontmost, so `cmd+w` ("leave")
        would otherwise close a Terminal tab or the draw.io window.
        """
        resolved_dir = profile_dir or os.getenv(
            "JARVIS_CHROME_PROFILE", str(Path.home() / ".jarvis-chrome-profile")
        )
        res = subprocess.run(
            ["pgrep", "-f", "--", f"--user-data-dir={resolved_dir}"],
            capture_output=True,
            text=True,
        )
        pids = sorted(int(p) for p in res.stdout.split() if p.isdigit())
        # Helper processes share the flag; the browser process is usually the
        # oldest (lowest pid) and is the only one System Events can raise.
        for pid in pids:
            try:
                _osascript(frontmost_pid_script(pid))
                break
            except subprocess.CalledProcessError:
                continue
        else:
            _osascript('tell application "Google Chrome" to activate')
        time.sleep(0.2)

    def open_app(self, name: str) -> None:
        """Opens or focuses a macOS app by name."""
        subprocess.run(["open", "-a", name], check=True, capture_output=True, text=True)

    def open_url(self, url: str) -> None:
        """Opens a URL in the default browser."""
        if not re.match(r"^https?://", url):
            url = "https://" + url
        subprocess.run(["open", url], check=True)

    def open_chrome_profile(self, url: str, profile_dir: str | None = None) -> str:
        """Opens a URL in an isolated Chrome profile for a separate persona."""
        resolved_dir = profile_dir or os.getenv(
            "JARVIS_CHROME_PROFILE",
            str(Path.home() / ".jarvis-chrome-profile"),
        )
        Path(resolved_dir).mkdir(parents=True, exist_ok=True)
        subprocess.run(chrome_profile_command(url, resolved_dir), check=True)
        return resolved_dir

    def open_drawio(self, mermaid_code: str = "") -> bool:
        """Opens draw.io without the splash modal and copies optional Mermaid code."""
        if mermaid_code.strip():
            self.copy_to_clipboard(mermaid_code.strip())
        self.open_url(drawio_url())
        return bool(mermaid_code.strip())

    def scroll(
        self,
        amount: int,
        x: float | None = None,
        y: float | None = None,
        display: int | None = None,
    ) -> None:
        """Scrolls; negative scrolls down.

        With x/y (screenshot pixels), the pointer moves there first so the
        right pane scrolls instead of whatever the cursor last rested on.
        """
        import Quartz

        if x is not None and y is not None:
            self._move_pointer(*self.to_global_point(x, y, display))
            time.sleep(0.05)
        event = Quartz.CGEventCreateScrollWheelEvent(
            None, Quartz.kCGScrollEventUnitLine, 1, int(amount)
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    # -- optional Android / ADB mobile device -------------------------------

    def _require_adb_serial(self) -> str:
        if not shutil.which("adb"):
            raise RuntimeError(
                "adb is not installed. Use open_app('iPhone Mirroring') or open Chrome instead."
            )
        res = subprocess.run(["adb", "devices"], check=True, capture_output=True, text=True)
        serial = adb_device_serial(res.stdout)
        if not serial:
            raise RuntimeError(
                "No Android device/emulator connected via adb. Use Mac desktop tools instead."
            )
        return serial

    def mobile_open_app(self, app: str) -> str:
        """Launches an Android app (e.g. 'swiggy' -> in.swiggy.android) via adb."""
        serial = self._require_adb_serial()
        package = resolve_android_package(app)
        subprocess.run(
            ["adb", "-s", serial, "shell", "monkey", "-p", package,
             "-c", "android.intent.category.LAUNCHER", "1"],
            check=True,
            capture_output=True,
            text=True,
        )
        return package

    def mobile_tap(self, x: int, y: int) -> None:
        """Taps pixel coordinates on the connected Android device/emulator."""
        serial = self._require_adb_serial()
        subprocess.run(["adb", "-s", serial, "shell", "input", "tap", str(x), str(y)], check=True)

    def mobile_type(self, text: str, press_enter: bool = False) -> None:
        """Types text on the connected Android device/emulator."""
        serial = self._require_adb_serial()
        escaped = adb_input_text(text)
        subprocess.run(["adb", "-s", serial, "shell", "input", "text", escaped], check=True)
        if press_enter:
            subprocess.run(["adb", "-s", serial, "shell", "input", "keyevent", "66"], check=True)

    def mobile_swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """Swipes between two points on the connected Android device/emulator."""
        serial = self._require_adb_serial()
        subprocess.run(
            ["adb", "-s", serial, "shell", "input", "swipe",
             str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            check=True,
        )


def screenshot_to_jpeg(shot: Screenshot) -> bytes:
    """Helper for debugging: encodes a Screenshot as JPEG bytes."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.frombytes("RGB", shot.size, shot.rgb_bytes).save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()
