"""macOS Privacy & Security permission checks and System Settings shortcuts.

Jarvis needs four macOS permissions:
- Microphone (voice input)
- Screen Recording (screenshots pushed to Gemini Live)
- Accessibility (UI clicks, typing, window inspection)
- Automation (AppleScript control of Google Chrome and System Events)

Every check here uses read-only preflight APIs so viewing Setup never triggers
macOS TCC popups or blocks the Cocoa main runloop. When macOS cannot report a
permission's status (for example Automation when target apps are not running,
or on non-macOS systems), the returned status says so plainly.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
from ctypes import Structure, byref, c_bool, c_char_p, c_int32, c_size_t, c_uint32, c_void_p
from dataclasses import asdict, dataclass
import subprocess
import sys
import threading
from typing import Any, Callable

PRIVACY_URLS: dict[str, str] = {
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "screen_recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "automation": "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
}

AUTOMATION_TARGETS: tuple[tuple[str, str], ...] = (
    ("com.google.Chrome", "Chrome"),
    ("com.apple.systemevents", "System Events"),
)

# Carbon MacErrors.h constants for AEDeterminePermissionToAutomateTarget:
AE_NO_ERR = 0
AE_PROC_NOT_FOUND = -600
AE_NOT_PERMITTED = -1743
AE_WOULD_REQUIRE_CONSENT = -1744


@dataclass(frozen=True)
class PermissionStatus:
    """UI-ready status record for one macOS permission."""

    id: str
    name: str
    purpose: str
    status: str  # 'granted' | 'denied' | 'prompt' | 'unknown'
    label: str
    detail: str
    detectable: bool
    settings_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _probe_microphone_macos() -> int | None:
    """Returns AVAuthorizationStatus int (0..3) for audio, or None if unavailable."""
    if sys.platform != "darwin":
        return None
    try:
        import objc  # type: ignore[import-not-found]

        objc.loadBundle(
            "AVFoundation",
            {},
            bundle_path="/System/Library/Frameworks/AVFoundation.framework",
        )
        av_device = objc.lookUpClass("AVCaptureDevice")
        return int(av_device.authorizationStatusForMediaType_("soun"))
    except Exception:
        return None


def _probe_screen_recording_macos() -> bool | None:
    if sys.platform != "darwin":
        return None
    try:
        import Quartz  # type: ignore[import-not-found]

        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        return None


def _probe_accessibility_macos() -> bool | None:
    if sys.platform != "darwin":
        return None
    try:
        import ApplicationServices  # type: ignore[import-not-found]

        return bool(ApplicationServices.AXIsProcessTrusted())
    except Exception:
        return None


class _AEDesc(Structure):
    _fields_ = [("descriptorType", c_uint32), ("dataHandle", c_void_p)]


def _fourcc(code: bytes) -> int:
    return int.from_bytes(code, "big")


def _query_automation_codes_worker() -> dict[str, int] | None:
    if sys.platform != "darwin":
        return None
    try:
        cs = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")
        cs.AECreateDesc.argtypes = [c_uint32, c_char_p, c_size_t, ctypes.POINTER(_AEDesc)]
        cs.AECreateDesc.restype = c_int32
        cs.AEDisposeDesc.argtypes = [ctypes.POINTER(_AEDesc)]
        cs.AEDisposeDesc.restype = c_int32
        cs.AEDeterminePermissionToAutomateTarget.argtypes = [
            ctypes.POINTER(_AEDesc),
            c_uint32,
            c_uint32,
            c_bool,
        ]
        cs.AEDeterminePermissionToAutomateTarget.restype = c_int32

        type_bundle = _fourcc(b"bund")
        wildcard = _fourcc(b"****")
        results: dict[str, int] = {}
        for bundle_id, _label in AUTOMATION_TARGETS:
            raw = bundle_id.encode("utf-8")
            desc = _AEDesc()
            err = cs.AECreateDesc(type_bundle, raw, len(raw), byref(desc))
            if err != 0:
                continue
            try:
                rc = int(
                    cs.AEDeterminePermissionToAutomateTarget(
                        byref(desc), wildcard, wildcard, False
                    )
                )
                results[bundle_id] = rc
            finally:
                cs.AEDisposeDesc(byref(desc))
        return results or None
    except Exception:
        return None


def _probe_automation_macos() -> dict[str, int] | None:
    """Runs AEDeterminePermissionToAutomateTarget off the Cocoa main thread."""
    if sys.platform != "darwin":
        return None
    if threading.current_thread() is threading.main_thread():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_query_automation_codes_worker)
            try:
                return fut.result(timeout=1.5)
            except Exception:
                return None
    return _query_automation_codes_worker()


def check_microphone(probe: Callable[[], int | None] = _probe_microphone_macos) -> PermissionStatus:
    url = PRIVACY_URLS["microphone"]
    purpose = "Hears your voice commands"
    code = probe()
    if code == 3:
        return PermissionStatus(
            id="microphone",
            name="Microphone",
            purpose=purpose,
            status="granted",
            label="Granted",
            detail="Microphone access is enabled.",
            detectable=True,
            settings_url=url,
        )
    if code == 0:
        return PermissionStatus(
            id="microphone",
            name="Microphone",
            purpose=purpose,
            status="prompt",
            label="Will prompt",
            detail="Not requested yet — macOS will ask when Jarvis starts.",
            detectable=True,
            settings_url=url,
        )
    if code in (1, 2):
        label = "Restricted" if code == 1 else "Not granted"
        return PermissionStatus(
            id="microphone",
            name="Microphone",
            purpose=purpose,
            status="denied",
            label=label,
            detail="Turn on Microphone access in System Settings.",
            detectable=True,
            settings_url=url,
        )
    return PermissionStatus(
        id="microphone",
        name="Microphone",
        purpose=purpose,
        status="unknown",
        label="Cannot detect",
        detail="Status cannot be detected automatically — check System Settings.",
        detectable=False,
        settings_url=url,
    )


def check_screen_recording(
    probe: Callable[[], bool | None] = _probe_screen_recording_macos,
) -> PermissionStatus:
    url = PRIVACY_URLS["screen_recording"]
    purpose = "Lets Jarvis see your screen"
    allowed = probe()
    if allowed is True:
        return PermissionStatus(
            id="screen_recording",
            name="Screen Recording",
            purpose=purpose,
            status="granted",
            label="Granted",
            detail="Screen capture access is enabled.",
            detectable=True,
            settings_url=url,
        )
    if allowed is False:
        return PermissionStatus(
            id="screen_recording",
            name="Screen Recording",
            purpose=purpose,
            status="denied",
            label="Not granted",
            detail="Enable in System Settings (macOS may require restarting the app).",
            detectable=True,
            settings_url=url,
        )
    return PermissionStatus(
        id="screen_recording",
        name="Screen Recording",
        purpose=purpose,
        status="unknown",
        label="Cannot detect",
        detail="Status cannot be detected automatically — check System Settings.",
        detectable=False,
        settings_url=url,
    )


def check_accessibility(
    probe: Callable[[], bool | None] = _probe_accessibility_macos,
) -> PermissionStatus:
    url = PRIVACY_URLS["accessibility"]
    purpose = "Clicks, types, and reads UI controls"
    trusted = probe()
    if trusted is True:
        return PermissionStatus(
            id="accessibility",
            name="Accessibility",
            purpose=purpose,
            status="granted",
            label="Granted",
            detail="Accessibility control is enabled.",
            detectable=True,
            settings_url=url,
        )
    if trusted is False:
        return PermissionStatus(
            id="accessibility",
            name="Accessibility",
            purpose=purpose,
            status="denied",
            label="Not granted",
            detail="Enable in System Settings → Accessibility.",
            detectable=True,
            settings_url=url,
        )
    return PermissionStatus(
        id="accessibility",
        name="Accessibility",
        purpose=purpose,
        status="unknown",
        label="Cannot detect",
        detail="Status cannot be detected automatically — check System Settings.",
        detectable=False,
        settings_url=url,
    )


def check_automation(
    probe: Callable[[], dict[str, int] | None] = _probe_automation_macos,
) -> PermissionStatus:
    url = PRIVACY_URLS["automation"]
    purpose = "Drives Chrome & System Events via AppleScript"
    codes = probe()
    if not codes:
        return PermissionStatus(
            id="automation",
            name="Automation",
            purpose=purpose,
            status="unknown",
            label="Cannot detect",
            detail="Status cannot be detected automatically — macOS prompts on first AppleScript use.",
            detectable=False,
            settings_url=url,
        )

    denied: list[str] = []
    granted: list[str] = []
    not_asked: list[str] = []
    not_running: list[str] = []

    for bundle_id, friendly in AUTOMATION_TARGETS:
        rc = codes.get(bundle_id)
        if rc == AE_NOT_PERMITTED:
            denied.append(friendly)
        elif rc == AE_NO_ERR:
            granted.append(friendly)
        elif rc == AE_WOULD_REQUIRE_CONSENT:
            not_asked.append(friendly)
        else:
            not_running.append(friendly)

    if denied:
        return PermissionStatus(
            id="automation",
            name="Automation",
            purpose=purpose,
            status="denied",
            label="Not granted",
            detail=f"Denied for {' & '.join(denied)} — enable in System Settings → Automation.",
            detectable=True,
            settings_url=url,
        )

    if len(granted) == len(AUTOMATION_TARGETS):
        return PermissionStatus(
            id="automation",
            name="Automation",
            purpose=purpose,
            status="granted",
            label="Granted",
            detail="Granted for Chrome & System Events.",
            detectable=True,
            settings_url=url,
        )

    if not_asked and not not_running:
        return PermissionStatus(
            id="automation",
            name="Automation",
            purpose=purpose,
            status="prompt",
            label="Will prompt",
            detail=f"macOS will ask on first use for {' & '.join(not_asked)}.",
            detectable=True,
            settings_url=url,
        )

    if granted and not_running:
        return PermissionStatus(
            id="automation",
            name="Automation",
            purpose=purpose,
            status="unknown",
            label="Partial",
            detail=(
                f"{' & '.join(granted)} granted; {' & '.join(not_running)} status "
                "cannot be detected while it is not running."
            ),
            detectable=False,
            settings_url=url,
        )

    return PermissionStatus(
        id="automation",
        name="Automation",
        purpose=purpose,
        status="unknown",
        label="Cannot detect",
        detail=(
            "macOS cannot report Automation status until Chrome / System Events are running "
            "(prompts on first use)."
        ),
        detectable=False,
        settings_url=url,
    )


def check_all_permissions() -> list[dict[str, Any]]:
    """Checks all four macOS permissions and returns serializable dicts."""
    return [
        check_microphone().to_dict(),
        check_screen_recording().to_dict(),
        check_accessibility().to_dict(),
        check_automation().to_dict(),
    ]


def open_privacy_pane(
    permission_id: str,
    *,
    runner: Callable[..., Any] = subprocess.Popen,
) -> bool:
    """Opens the System Settings Privacy & Security pane for ``permission_id``."""
    url = PRIVACY_URLS.get(permission_id)
    if not url:
        return False
    runner(["open", url])
    return True
