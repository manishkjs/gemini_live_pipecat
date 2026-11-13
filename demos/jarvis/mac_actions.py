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


MEET_NEW_URL = "https://meet.google.com/new"
_MEET_NEW_WORDS = {
    "",
    "new",
    "instant",
    "start",
    "create",
    "new meeting",
    "instant meeting",
    "start meeting",
    "start a new meeting",
    "new meet",
}
_MEET_CODE_RE = re.compile(r"^[a-z]{3}-?[a-z]{4}-?[a-z]{3}$")
_MEET_LOOKUP_RE = re.compile(r"^lookup/[\w-]+$")


def normalize_meet_url(meeting: str | None) -> str:
    """Normalizes a Meet request into a meet.google.com URL.

    - "new", "instant", "start" (or empty) -> https://meet.google.com/new, which
      creates and opens a fresh instant meeting.
    - A code "abc-defg-hij" (dashes optional), "meet.google.com/<code>" or a full
      https://meet.google.com/... URL -> that meeting.
    Anything else raises ValueError rather than opening a bogus
    meet.google.com/<word> page.
    """
    cleaned = (meeting or "").strip()
    lowered = cleaned.lower().rstrip("/")
    if lowered in _MEET_NEW_WORDS:
        return MEET_NEW_URL
    path = re.sub(r"^(https?://)?(www\.)?meet\.google\.com/?", "", lowered)
    if path != lowered or re.match(r"^https?://", lowered):
        if re.match(r"^https?://", path):
            raise ValueError(f"not a Google Meet URL: {cleaned!r}")
        path = path.split("?", 1)[0].split("#", 1)[0].strip("/")
        if path in ("", "new"):
            return MEET_NEW_URL
        if _MEET_CODE_RE.match(path) or _MEET_LOOKUP_RE.match(path):
            return f"https://meet.google.com/{_format_meet_code(path)}"
        raise ValueError(f"not a Google Meet meeting URL: {cleaned!r}")
    if _MEET_CODE_RE.match(lowered):
        return f"https://meet.google.com/{_format_meet_code(lowered)}"
    raise ValueError(
        f"{cleaned!r} is not a Meet code (xxx-yyyy-zzz) or URL; use 'new' to start a meeting"
    )


def _format_meet_code(path: str) -> str:
    if _MEET_LOOKUP_RE.match(path):
        return path
    letters = path.replace("-", "")
    return f"{letters[:3]}-{letters[3:7]}-{letters[7:]}"


GMAIL_URL = "https://mail.google.com/mail/u/0/#inbox"


def gmail_compose_url(base_url: str, to: str = "", subject: str = "", body: str = "") -> str:
    """Builds a compose URL for the same Gmail account as `base_url`.

    Keeps the /mail/u/<n>/ account index from an existing tab so a work or
    personal mailbox stays in its own account. Without fields it opens the
    compose pop-up over the inbox; with fields it opens a pre-filled draft.
    """
    import urllib.parse

    m = re.search(r"https://mail\.google\.com/mail/u/(\d+)", base_url or "")
    prefix = f"https://mail.google.com/mail/u/{m.group(1) if m else 0}/"
    if not (to or subject or body):
        return prefix + "#inbox?compose=new"
    query = {"view": "cm", "fs": "1"}
    if to:
        query["to"] = to
    if subject:
        query["su"] = subject
    if body:
        query["body"] = body
    return prefix + "?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)


@dataclasses.dataclass
class ChromeTab:
    url: str
    title: str


_CHROME_BIN = "Google Chrome.app/Contents/MacOS/Google Chrome"


def pick_user_chrome_pid(ps_lines: Sequence[str], jarvis_profile: str) -> int | None:
    """From `ps -axo pid=,args=` lines, picks the user's own Chrome browser pid.

    Skips helper processes and Jarvis's isolated instance (its
    --user-data-dir), which would otherwise swallow `open -a` and AppleScript.
    """
    for line in ps_lines:
        pid_text, _, args = line.strip().partition(" ")
        if not pid_text.isdigit() or not args.strip().endswith(_CHROME_BIN) and (
            _CHROME_BIN + " " not in args
        ):
            continue
        if "--type=" in args or f"--user-data-dir={jarvis_profile}" in args:
            continue
        return int(pid_text)
    return None


def chrome_jxa(pid: int, op: str, arg: str) -> str:
    """JXA for the Chrome process `pid`.

    op="find": focus the first tab whose URL/title contains arg (case-
    insensitive); prints "<url>\\t<title>" or "". op="open": new tab with URL arg
    in the front window. op="set": navigate the front window's active tab.
    """
    import json

    return f"""
var c = Application({int(pid)}); var op = {json.dumps(op)}; var arg = {json.dumps(arg)};
function front() {{ c.activate(); delay(0.2); }}
(function() {{
  if (op === "find") {{
    var q = arg.toLowerCase(); var ws = c.windows();
    for (var i = 0; i < ws.length; i++) {{
      var ts = ws[i].tabs();
      for (var j = 0; j < ts.length; j++) {{
        var u = ts[j].url() || "", t = ts[j].title() || "";
        if (u.toLowerCase().indexOf(q) >= 0 || t.toLowerCase().indexOf(q) >= 0) {{
          ws[i].activeTabIndex = j + 1; ws[i].index = 1; front();
          return u + "\\t" + t;
        }}
      }}
    }}
    return "";
  }}
  if (op === "open") {{
    if (c.windows().length === 0) {{ c.Window().make(); delay(0.3); }}
    var w = c.windows[0]; var tab = c.Tab({{url: arg}}); w.tabs.push(tab);
    w.activeTabIndex = w.tabs().length; front(); return arg;
  }}
  if (op === "set") {{ c.windows[0].activeTab.url = arg; front(); return arg; }}
  return "";
}})();
"""


def chrome_open_command(url: str) -> list[str]:
    """Builds the command that opens a URL in the user's normal Google Chrome."""
    return ["open", "-a", "Google Chrome", url]


def drawio_url() -> str:
    """Returns the draw.io URL that skips the startup storage dialog."""
    return "https://app.diagrams.net/?splash=0"


# -- Mermaid flowchart -> native draw.io diagram -------------------------------

_MERMAID_HEADER_RE = re.compile(r"^\s*(?:graph|flowchart)\s+(TD|TB|BT|LR|RL)\b", re.I)
_MERMAID_NODE_RE = re.compile(
    r"""^\s*([A-Za-z0-9_]+)\s*
        (?:\[\((?P<l1>[^\]]*)\)\]      # [(db)]
          |\(\((?P<l2>[^)]*)\)\)       # ((circle))
          |\[\[(?P<l3>[^\]]*)\]\]      # [[subroutine]]
          |\[(?P<l4>[^\]]*)\]          # [box]
          |\((?P<l5>[^)]*)\)           # (rounded)
          |\{(?P<l6>[^}]*)\}           # {decision}
          |>(?P<l7>[^\]]*)\]           # >flag]
        )?""",
    re.X,
)
_MERMAID_ARROW_RE = re.compile(
    r"""\s*(?:
        --\s*(?P<t1>[^-|>][^>]*?)\s*-->     # A -- text --> B
      | -\.\s*(?P<t2>[^.]+?)\s*\.->         # A -. text .-> B
      | ==\s*(?P<t3>[^=>]+?)\s*==>          # A == text ==> B
      | (?:-->|==>|-\.->|---|-.-|--o|--x|<-->)
        (?:\s*\|(?P<t4>[^|]*)\|)?           # A -->|text| B
    )\s*""",
    re.X,
)
_SHAPE_STYLES = {
    "l1": "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=12;fillColor=#fff2cc;strokeColor=#d6b656;",
    "l2": "ellipse;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;",
    "l3": "shape=process;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;",
    "l4": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;",
    "l5": "rounded=1;arcSize=40;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;",
    "l6": "rhombus;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;",
    "l7": "shape=step;perimeter=stepPerimeter;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;",
}
_DB_WORDS = re.compile(r"\b(db|database|sql|postgres|mysql|storage|spanner|bigquery|cache|redis)\b", re.I)


@dataclasses.dataclass
class FlowNode:
    id: str
    label: str
    style: str


@dataclasses.dataclass
class Flowchart:
    direction: str
    nodes: dict[str, FlowNode]
    edges: list[tuple[str, str, str]]


def _parse_mermaid_node(text: str, chart: Flowchart) -> tuple[str | None, str]:
    """Parses one node reference at the start of text; returns (id, rest)."""
    m = _MERMAID_NODE_RE.match(text)
    if not m or not m.group(1):
        return None, text
    node_id = m.group(1)
    label, style = None, None
    for key in _SHAPE_STYLES:
        if m.group(key) is not None:
            label = m.group(key).strip().strip('"')
            style = _SHAPE_STYLES[key]
            break
    node = chart.nodes.get(node_id)
    if node is None:
        text_label = label if label else node_id
        if style is None:
            style = _SHAPE_STYLES["l1"] if _DB_WORDS.search(text_label) else _SHAPE_STYLES["l4"]
        chart.nodes[node_id] = FlowNode(node_id, text_label, style)
    elif label:
        node.label = label
        node.style = style or node.style
    return node_id, text[m.end():]


def parse_mermaid_flowchart(code: str) -> Flowchart:
    """Parses a simple Mermaid `graph`/`flowchart` into nodes and edges.

    Supports node shapes [], (), {}, [()], (()), [[ ]], chained arrows
    (A --> B --> C), `&` fan-out (A --> B & C) and edge labels (-->|x|,
    -- x -->). Raises ValueError for other diagram types or empty charts.
    """
    lines = [ln.strip() for ln in code.replace(";", "\n").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("%%")]
    if not lines:
        raise ValueError("empty Mermaid code")
    header = _MERMAID_HEADER_RE.match(lines[0])
    if not header:
        raise ValueError("only Mermaid 'graph'/'flowchart' diagrams can be drawn natively")
    direction = header.group(1).upper().replace("TB", "TD")
    chart = Flowchart(direction, {}, [])
    pending_label = ""
    for line in lines[1:]:
        if re.match(r"^(subgraph|end|classDef|class|style|linkStyle|click|direction)\b", line):
            continue
        rest = line
        sources: list[str] = []
        while rest:
            group: list[str] = []
            while True:
                node_id, rest = _parse_mermaid_node(rest, chart)
                if node_id is None:
                    break
                group.append(node_id)
                amp = re.match(r"\s*&\s*", rest)
                if not amp:
                    break
                rest = rest[amp.end():]
            if not group:
                break
            for src in sources:
                for dst in group:
                    chart.edges.append((src, dst, pending_label))
            arrow = _MERMAID_ARROW_RE.match(rest)
            if not arrow or arrow.end() == 0:
                break
            pending_label = next(
                (arrow.group(k).strip() for k in ("t1", "t2", "t3", "t4") if arrow.group(k)), ""
            )
            rest = rest[arrow.end():]
            sources = group
    if not chart.nodes:
        raise ValueError("no nodes found in Mermaid code")
    return chart


def _layer_nodes(chart: Flowchart) -> dict[str, int]:
    """Assigns each node a layer: longest path from a root (cycle-safe)."""
    layer = {nid: 0 for nid in chart.nodes}
    for _ in range(len(chart.nodes)):
        changed = False
        for src, dst, _label in chart.edges:
            if src != dst and layer[dst] < layer[src] + 1 and layer[src] + 1 < len(chart.nodes):
                layer[dst] = layer[src] + 1
                changed = True
        if not changed:
            break
    return layer


def _xml_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        .replace("\n", "&#xa;")
    )


def flowchart_to_drawio_xml(chart: Flowchart, title: str = "Jarvis diagram") -> str:
    """Lays out a Flowchart and returns a draw.io `mxfile` XML document."""
    layers = _layer_nodes(chart)
    by_layer: dict[int, list[str]] = {}
    for nid in chart.nodes:  # keep declaration order inside a layer
        by_layer.setdefault(layers[nid], []).append(nid)
    width, height, gap_main, gap_cross = 160, 70, 90, 50
    horizontal = chart.direction in ("LR", "RL")
    widest = max(len(v) for v in by_layer.values())
    pos: dict[str, tuple[int, int]] = {}
    for depth, ids in by_layer.items():
        if chart.direction in ("BT", "RL"):
            depth = max(by_layer) - depth
        offset = (widest - len(ids)) * (width + gap_cross if not horizontal else height + gap_cross) // 2
        for i, nid in enumerate(ids):
            if horizontal:
                pos[nid] = (40 + depth * (width + gap_main), 40 + offset + i * (height + gap_cross))
            else:
                pos[nid] = (40 + offset + i * (width + gap_cross), 40 + depth * (height + gap_main))
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    ids = {nid: f"n{i}" for i, nid in enumerate(chart.nodes)}
    for nid, node in chart.nodes.items():
        x, y = pos[nid]
        cells.append(
            f'<mxCell id="{ids[nid]}" value="{_xml_attr(node.label)}" style="{node.style}" '
            f'vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{width}" '
            f'height="{height}" as="geometry"/></mxCell>'
        )
    edge_style = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=classic;strokeWidth=2;"
    for i, (src, dst, label) in enumerate(chart.edges):
        cells.append(
            f'<mxCell id="e{i}" value="{_xml_attr(label)}" style="{edge_style}" edge="1" '
            f'parent="1" source="{ids[src]}" target="{ids[dst]}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
    return (
        f'<mxfile><diagram name="{_xml_attr(title)}" id="jarvis">'
        '<mxGraphModel grid="1" gridSize="10" guides="1" connect="1" arrows="1" page="1">'
        f'<root>{"".join(cells)}</root></mxGraphModel></diagram></mxfile>'
    )


def drawio_url_for_xml(xml: str) -> str:
    """Encodes draw.io XML into an app.diagrams.net `#R` URL that opens it.

    Same scheme as draw.io's File > Export as > URL: raw-deflate of the
    URI-encoded XML, base64, then URI-encoded into the hash.
    """
    import base64
    import urllib.parse
    import zlib

    encoded = urllib.parse.quote(xml, safe="-_.!~*'()")
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = compressor.compress(encoded.encode("utf-8")) + compressor.flush()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"https://app.diagrams.net/?splash=0#R{urllib.parse.quote(b64, safe='')}"


def mermaid_to_drawio_url(code: str, title: str = "Jarvis diagram") -> str:
    """Mermaid flowchart -> URL that opens app.diagrams.net with it drawn."""
    return drawio_url_for_xml(flowchart_to_drawio_xml(parse_mermaid_flowchart(code), title))


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


@dataclasses.dataclass
class UiMatch:
    """An on-screen UI element found by its accessible text."""

    role: str
    text: str
    x: float  # global Quartz points, element centre
    y: float
    width: float
    height: float
    score: float = 0.0


_CLICKABLE_ROLES = {
    "AXLink": 1.5, "AXButton": 1.5, "AXMenuItem": 1.2, "AXMenuButton": 1.2,
    "AXPopUpButton": 1.0, "AXCheckBox": 1.0, "AXRadioButton": 1.0, "AXTab": 1.0,
    "AXCell": 0.6, "AXRow": 0.4, "AXImage": 0.5, "AXHeading": 0.6,
    "AXStaticText": 0.3, "AXTextField": 0.8, "AXComboBox": 0.8,
}


def score_ui_match(query: str, text: str, role: str) -> float:
    """How well an element's accessible text matches the query (0 = no match)."""
    q = " ".join(query.lower().split())
    t = " ".join((text or "").lower().split())
    if not q or not t:
        return 0.0
    if t == q:
        base = 10.0
    elif t.startswith(q):
        base = 7.0
    elif q in t:
        base = 5.0
    else:
        words = [w for w in q.split() if len(w) > 1]
        hits = sum(1 for w in words if re.search(rf"\b{re.escape(w)}", t))
        needed = len(words) if len(words) <= 2 else -(-2 * len(words) // 3)
        if not words or hits < needed:
            return 0.0
        base = 3.0 * hits / len(words)
    # Prefer tight labels over long blobs that merely contain the words.
    base -= min(len(t) / max(len(q), 1), 20) * 0.05
    return base + _CLICKABLE_ROLES.get(role, 0.0)


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
        px, py = self.to_global_point(x, y, display)
        return self.click_global(px, py, double)

    # -- accessibility (click by text) ---------------------------------------

    def find_ui_elements(
        self, query: str, limit: int = 5, max_nodes: int = 8000, budget_s: float = 3.0
    ) -> list[UiMatch]:
        """Finds on-screen elements of the frontmost app whose accessible text matches.

        Uses the macOS Accessibility tree, so it reads real labels (link and
        button names, YouTube video titles, menu items) instead of guessing
        pixels. Chrome/Electron expose web content once AXManualAccessibility
        is set on the app.
        """
        import AppKit
        import ApplicationServices as AS

        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return []
        root = AS.AXUIElementCreateApplication(app.processIdentifier())
        AS.AXUIElementSetAttributeValue(root, "AXManualAccessibility", True)
        AS.AXUIElementSetAttributeValue(root, "AXEnhancedUserInterface", True)

        def attr(el, name):
            err, value = AS.AXUIElementCopyAttributeValue(el, name, None)
            return value if err == 0 else None

        window = attr(root, "AXFocusedWindow") or attr(root, "AXMainWindow") or root
        displays = self.list_displays()

        def on_screen(x: float, y: float) -> bool:
            return any(
                d.origin_x <= x < d.origin_x + d.width and d.origin_y <= y < d.origin_y + d.height
                for d in displays
            )

        win_frame = None
        wpos, wsize = attr(window, "AXPosition"), attr(window, "AXSize")
        if wpos is not None and wsize is not None:
            _, wp = AS.AXValueGetValue(wpos, AS.kAXValueCGPointType, None)
            _, ws = AS.AXValueGetValue(wsize, AS.kAXValueCGSizeType, None)
            win_frame = (wp.x, wp.y, wp.x + ws.width, wp.y + ws.height)

        found: list[UiMatch] = []
        queue = [window]
        seen = 0
        deadline = time.monotonic() + budget_s
        while queue and seen < max_nodes and time.monotonic() < deadline:
            el = queue.pop(0)
            seen += 1
            role = attr(el, "AXRole") or ""
            texts = []
            for name in ("AXTitle", "AXDescription", "AXValue", "AXHelp"):
                value = attr(el, name)
                if isinstance(value, str) and value.strip():
                    texts.append(value.strip())
            best_text, best = "", 0.0
            for text in texts:
                sc = score_ui_match(query, text, role)
                if sc > best:
                    best_text, best = text, sc
            if best > 0:
                pos, size = attr(el, "AXPosition"), attr(el, "AXSize")
                if pos is not None and size is not None:
                    _, pt = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
                    _, sz = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
                    cx, cy = pt.x + sz.width / 2, pt.y + sz.height / 2
                    inside = win_frame is None or (
                        win_frame[0] <= cx <= win_frame[2] and win_frame[1] <= cy <= win_frame[3]
                    )
                    if sz.width >= 4 and sz.height >= 4 and on_screen(cx, cy) and inside:
                        found.append(
                            UiMatch(role, best_text[:120], cx, cy, sz.width, sz.height, best)
                        )
            children = attr(el, "AXChildren")
            if children:
                queue.extend(children)
        found.sort(key=lambda m: (-m.score, m.y, m.x))
        # Drop near-duplicates (a link and its own text label at the same spot).
        unique: list[UiMatch] = []
        for m in found:
            if all(abs(m.x - u.x) > 6 or abs(m.y - u.y) > 6 for u in unique):
                unique.append(m)
        return unique[:limit]

    def click_text(self, query: str, nth: int = 1, double: bool = False) -> UiMatch:
        """Clicks the nth best on-screen element whose accessible text matches query."""
        matches = self.find_ui_elements(query, limit=max(5, nth))
        if len(matches) < nth:
            time.sleep(0.8)  # Chrome builds its web AX tree lazily on first query.
            matches = self.find_ui_elements(query, limit=max(5, nth))
        if len(matches) < nth:
            raise LookupError(
                f"No on-screen element in the front app matches {query!r}"
                + (f" (only {len(matches)} found)" if matches else "")
            )
        target = matches[nth - 1]
        self.click_global(target.x, target.y, double)
        self.focus_display_at(target.x, target.y)
        return target

    def focus_display_at(self, gx: float, gy: float) -> None:
        """Makes the display containing a global point the active one for screenshots."""
        for d in self.list_displays():
            if d.origin_x <= gx < d.origin_x + d.width and d.origin_y <= gy < d.origin_y + d.height:
                self._active_display = d.index
                return

    def front_window_display(self) -> int | None:
        """1-based display index showing the frontmost app's top window, if any."""
        import AppKit
        import Quartz

        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        pid = app.processIdentifier()
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        ) or []
        for w in windows:
            if w.get("kCGWindowOwnerPID") != pid or w.get("kCGWindowLayer", 0) != 0:
                continue
            b = w.get("kCGWindowBounds") or {}
            if b.get("Width", 0) < 100 or b.get("Height", 0) < 100:
                continue
            cx, cy = b["X"] + b["Width"] / 2, b["Y"] + b["Height"] / 2
            for d in self.list_displays():
                if d.origin_x <= cx < d.origin_x + d.width and d.origin_y <= cy < d.origin_y + d.height:
                    return d.index
        return None

    def click_global(self, px: float, py: float, double: bool = False) -> tuple[float, float]:
        """Clicks at global Quartz screen points."""
        import Quartz

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

    def focus_meet_window(self, profile_dir: str | None = None, isolated: bool = True) -> None:
        """Brings the Chrome running the Meet call to the front.

        With isolated=True, prefers Jarvis's own Chrome profile if it runs;
        with isolated=False, activates the user's normal Google Chrome.
        Meet shortcuts go to whichever app is frontmost, so `cmd+w` ("leave")
        would otherwise close a Terminal tab or the draw.io window.
        """
        if not isolated:
            pid = self.user_chrome_pid()
            if pid is not None:
                _osascript(frontmost_pid_script(pid))
            else:
                _osascript('tell application "Google Chrome" to activate')
            time.sleep(0.2)
            return
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
        # The user's Chrome by pid: plain `open url` can land in Jarvis's
        # isolated Chrome when that instance is running.
        self.open_in_chrome(url)

    def _jarvis_profile_dir(self) -> str:
        return os.getenv("JARVIS_CHROME_PROFILE", str(Path.home() / ".jarvis-chrome-profile"))

    def user_chrome_pid(self) -> int | None:
        """Pid of the user's own Chrome (not Jarvis's isolated instance), if running."""
        res = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True, text=True)
        return pick_user_chrome_pid(res.stdout.splitlines(), self._jarvis_profile_dir())

    def _chrome_jxa(self, op: str, arg: str) -> str | None:
        pid = self.user_chrome_pid()
        if pid is None:
            return None
        res = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", chrome_jxa(pid, op, arg)],
            check=True, capture_output=True, text=True,
        )
        return res.stdout.strip()

    def focus_chrome_tab(self, query: str) -> ChromeTab | None:
        """Brings the first tab in the user's Chrome matching query to the front."""
        out = self._chrome_jxa("find", query)
        if not out:
            return None
        url, _, title = out.partition("\t")
        time.sleep(0.3)
        return ChromeTab(url=url, title=title)

    def set_front_tab_url(self, url: str) -> None:
        """Navigates the active tab of the user's Chrome front window to url."""
        if self._chrome_jxa("set", url) is None:
            self.open_in_chrome(url)

    def open_in_chrome(self, url: str) -> None:
        """Opens a URL in a new tab of the user's normal Google Chrome.

        Talks to that Chrome process by pid: plain `open -a "Google Chrome"`
        would hand the URL to Jarvis's isolated Chrome when that one is running.
        """
        if self._chrome_jxa("open", url) is not None:
            return
        cmd = chrome_open_command(url)
        if self._jarvis_chrome_running():
            # Force a fresh default-profile instance instead of Jarvis's.
            cmd = ["open", "-na", "Google Chrome", "--args", url]
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    def _jarvis_chrome_running(self) -> bool:
        res = subprocess.run(
            ["pgrep", "-f", "--", f"--user-data-dir={self._jarvis_profile_dir()}"],
            capture_output=True, text=True,
        )
        return bool(res.stdout.strip())

    def open_chrome_profile(self, url: str, profile_dir: str | None = None) -> str:
        """Opens a URL in an isolated Chrome profile for a separate persona."""
        resolved_dir = profile_dir or os.getenv(
            "JARVIS_CHROME_PROFILE",
            str(Path.home() / ".jarvis-chrome-profile"),
        )
        Path(resolved_dir).mkdir(parents=True, exist_ok=True)
        subprocess.run(chrome_profile_command(url, resolved_dir), check=True)
        return resolved_dir

    def open_drawio(self, mermaid_code: str = "", title: str = "Jarvis diagram") -> str:
        """Opens draw.io in Chrome, with a Mermaid flowchart already drawn.

        Returns "drawn" when the flowchart was converted to a native draw.io
        diagram and opened, "clipboard" when the Mermaid is some other kind
        (sequence, class, ...) and was only copied, or "empty".
        """
        code = mermaid_code.strip()
        if code:
            try:
                url = mermaid_to_drawio_url(code, title)
            except ValueError:
                self.copy_to_clipboard(code)
                self.open_in_chrome(drawio_url())
                return "clipboard"
            self.open_in_chrome(url)
            return "drawn"
        self.open_in_chrome(drawio_url())
        return "empty"

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
