"""Native macOS "hands and eyes" for Jarvis.

Screenshots use the built-in `screencapture` tool, mouse clicks post real
CoreGraphics events, and typing goes through System Events. All of these work
in any app, not only the browser. They need Screen Recording and Accessibility
permission for the process that runs Jarvis.

The safety checks at the top of this module are pure Python so they can be
unit-tested on any OS.
"""

from __future__ import annotations

import dataclasses
import io
import re
import subprocess
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Safety gate (pure Python, testable anywhere)
# ---------------------------------------------------------------------------

# Commands or text that must never run without a human saying yes.
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

# Words in a click target that mean "this button changes something real".
_RISKY_TARGET_WORDS = (
    "delete", "remove", "destroy", "drop", "pay", "purchase", "buy",
    "transfer", "wire", "refund", "send", "submit", "deploy", "publish",
    "merge", "approve", "production", "prod",
)


@dataclasses.dataclass(frozen=True)
class RiskVerdict:
    """Result of a safety check on a proposed desktop action."""

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
    """Checks the description the model gave for the thing it wants to click."""
    words = set(re.findall(r"[a-z]+", target_description.lower()))
    hits = sorted(words.intersection(_RISKY_TARGET_WORDS))
    if hits:
        return RiskVerdict(True, f"button looks consequential ({', '.join(hits)})")
    return RiskVerdict(False)


# ---------------------------------------------------------------------------
# Key combos -> AppleScript (pure Python, testable anywhere)
# ---------------------------------------------------------------------------

_MODIFIERS = {
    "cmd": "command down", "command": "command down",
    "ctrl": "control down", "control": "control down",
    "opt": "option down", "option": "option down", "alt": "option down",
    "shift": "shift down",
}

# macOS virtual key codes for keys that have no printable character.
_KEY_CODES = {
    "enter": 36, "return": 36, "tab": 48, "space": 49, "delete": 51,
    "backspace": 51, "escape": 53, "esc": 53, "left": 123, "right": 124,
    "down": 125, "up": 126,
}


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def key_combo_to_applescript(combo: str) -> str:
    """Turns 'cmd+shift+t' or 'enter' into a System Events AppleScript line."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty key combo")
    *mods, key = parts
    unknown = [m for m in mods if m not in _MODIFIERS]
    if unknown:
        raise ValueError(f"unknown modifier(s): {unknown}")
    using = ""
    if mods:
        using = " using {" + ", ".join(_MODIFIERS[m] for m in mods) + "}"
    if key in _KEY_CODES:
        action = f"key code {_KEY_CODES[key]}"
    elif len(key) == 1:
        action = f"keystroke {_applescript_string(key)}"
    else:
        raise ValueError(f"unknown key: {key!r}")
    return f'tell application "System Events" to {action}{using}'


# ---------------------------------------------------------------------------
# Real macOS actions
# ---------------------------------------------------------------------------


def _osascript(script: str) -> None:
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True)


@dataclasses.dataclass
class Screenshot:
    """A downscaled screenshot plus what is needed to map clicks back."""

    rgb_bytes: bytes
    size: tuple[int, int]
    points_per_pixel: float  # screen points per screenshot pixel


class MacDesktop:
    """Eyes and hands on the local macOS desktop."""

    def __init__(self, max_width: int = 1280):
        self._max_width = max_width
        self._points_per_pixel = 1.0

    # -- eyes ---------------------------------------------------------------

    def screenshot(self) -> Screenshot:
        """Captures and downscales the main display."""
        from PIL import Image  # Imported lazily so tests don't need Pillow.
        import Quartz

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            subprocess.run(["screencapture", "-x", "-C", str(path)], check=True)
            image = Image.open(path).convert("RGB")
            image.load()

        screen_points_w = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()).size.width
        if image.width > self._max_width:
            ratio = self._max_width / image.width
            image = image.resize((self._max_width, int(image.height * ratio)))
        self._points_per_pixel = screen_points_w / image.width
        return Screenshot(image.tobytes(), image.size, self._points_per_pixel)

    # -- hands --------------------------------------------------------------

    def click(self, x: float, y: float, double: bool = False) -> tuple[float, float]:
        """Clicks at (x, y) given in the last screenshot's pixel coordinates."""
        import Quartz

        px, py = x * self._points_per_pixel, y * self._points_per_pixel
        point = Quartz.CGPointMake(px, py)
        clicks = 2 if double else 1
        Quartz.CGEventPost(
            Quartz.kCGHIDEventTap,
            Quartz.CGEventCreateMouseEvent(
                None, Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft
            ),
        )
        for click_index in range(1, clicks + 1):
            for event_type in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
                event = Quartz.CGEventCreateMouseEvent(
                    None, event_type, point, Quartz.kCGMouseButtonLeft
                )
                Quartz.CGEventSetIntegerValueField(
                    event, Quartz.kCGMouseEventClickState, click_index
                )
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
                time.sleep(0.03)
        return px, py

    def type_text(self, text: str, press_enter: bool = False) -> None:
        """Types text. Long text is pasted, which is faster and more reliable."""
        if len(text) > 40:
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
            _osascript(key_combo_to_applescript("cmd+v"))
        else:
            _osascript(f'tell application "System Events" to keystroke {_applescript_string(text)}')
        if press_enter:
            _osascript(key_combo_to_applescript("enter"))

    def press_keys(self, combo: str) -> None:
        """Presses a key or shortcut via System Events."""
        _osascript(key_combo_to_applescript(combo))

    def open_app(self, name: str) -> None:
        """Opens or focuses a macOS app by name."""
        subprocess.run(["open", "-a", name], check=True, capture_output=True, text=True)

    def open_url(self, url: str) -> None:
        """Opens a URL in the default browser."""
        if not re.match(r"^https?://", url):
            url = "https://" + url
        subprocess.run(["open", url], check=True)

    def scroll(self, amount: int) -> None:
        """Scrolls the window under the pointer; negative scrolls down."""
        import Quartz

        event = Quartz.CGEventCreateScrollWheelEvent(
            None, Quartz.kCGScrollEventUnitLine, 1, int(amount)
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def screenshot_to_jpeg(shot: Screenshot) -> bytes:
    """Helper for debugging: encodes a Screenshot as JPEG bytes."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.frombytes("RGB", shot.size, shot.rgb_bytes).save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()
