"""Builds a native macOS `Jarvis.app` bundle in /Applications (or ~/Applications).

Run with:
    .venv/bin/python build_app.py
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

_JARVIS_DIR = Path(__file__).resolve().parent
_DEFAULT_DEST = Path("/Applications/Jarvis.app")
_FALLBACK_DEST = Path.home() / "Applications" / "Jarvis.app"


def _render_icon_png(size: int) -> Image.Image:
    """Renders a macOS squircle icon with a glowing Jarvis orb."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pad = int(size * 0.08)
    radius = int(size * 0.22)

    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)
    bg_draw.rounded_rectangle(
        (pad, pad, size - pad, size - pad),
        radius=radius,
        fill=(14, 15, 22, 255),
        outline=(255, 255, 255, 34),
        width=max(1, size // 128),
    )

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    cx, cy = size // 2, size // 2
    outer_r = int(size * 0.28)
    glow_draw.ellipse(
        (cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r),
        fill=(66, 133, 244, 175),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(2, size // 14)))

    orb = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    orb_draw = ImageDraw.Draw(orb)
    core_r = int(size * 0.20)
    orb_draw.ellipse(
        (cx - core_r, cy - core_r, cx + core_r, cy + core_r),
        fill=(66, 133, 244, 255),
        outline=(168, 199, 250, 230),
        width=max(1, size // 64),
    )
    hi_r = int(size * 0.09)
    hi_x, hi_y = cx - int(size * 0.05), cy - int(size * 0.05)
    orb_draw.ellipse(
        (hi_x - hi_r, hi_y - hi_r, hi_x + hi_r, hi_y + hi_r),
        fill=(255, 255, 255, 210),
    )

    img = Image.alpha_composite(img, bg)
    img = Image.alpha_composite(img, glow)
    img = Image.alpha_composite(img, orb)
    return img


def _build_icns(dest_icns: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for pt_size in (16, 32, 128, 256, 512):
            _render_icon_png(pt_size).save(iconset / f"icon_{pt_size}x{pt_size}.png")
            _render_icon_png(pt_size * 2).save(iconset / f"icon_{pt_size}x{pt_size}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(dest_icns)],
            check=True,
        )


def build_app(dest: Path | None = None) -> Path:
    """Builds `Jarvis.app` at `dest` and returns its path."""
    target = dest or _DEFAULT_DEST
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not os.access(target.parent, os.W_OK):
            raise PermissionError(target.parent)
    except PermissionError:
        if dest is not None:
            raise
        target = _FALLBACK_DEST
        target.parent.mkdir(parents=True, exist_ok=True)

    venv_python = _JARVIS_DIR / ".venv" / "bin" / "python"
    if not venv_python.exists():
        raise RuntimeError(
            f"Virtualenv not found at {venv_python}. Create .venv and install requirements.txt first."
        )

    if target.exists():
        shutil.rmtree(target)

    contents = target / "Contents"
    macos_dir = contents / "MacOS"
    resources_dir = contents / "Resources"
    macos_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)

    plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": "Jarvis",
        "CFBundleExecutable": "Jarvis",
        "CFBundleIconFile": "AppIcon",
        "CFBundleIdentifier": "com.jarvis.desktop",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "Jarvis",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "Jarvis needs microphone access to hear your voice commands.",
        "NSScreenCaptureUsageDescription": "Jarvis needs screen recording access to see your screen and help you.",
        "NSAppleEventsUsageDescription": "Jarvis needs automation access to open apps and send keyboard shortcuts.",
    }
    with open(contents / "Info.plist", "wb") as fp:
        plistlib.dump(plist, fp)

    _build_icns(resources_dir / "AppIcon.icns")

    launcher_bin = macos_dir / "Jarvis"
    launcher_bin.write_text(
        f"""#!/bin/zsh
set -euo pipefail
LOG_DIR="$HOME/Library/Logs/Jarvis"
mkdir -p "$LOG_DIR"
exec >> "$LOG_DIR/jarvis.log" 2>&1
cd {str(_JARVIS_DIR)!r}
exec {str(venv_python)!r} {str(_JARVIS_DIR / "jarvis_app.py")!r}
"""
    )
    launcher_bin.chmod(0o755)

    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Jarvis.app macOS desktop app")
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="Destination .app path (default: /Applications/Jarvis.app)",
    )
    args = parser.parse_args()
    app_path = build_app(args.dest)
    print(f"Built {app_path}")
    print("Logs: ~/Library/Logs/Jarvis/jarvis.log")


if __name__ == "__main__":
    main()
