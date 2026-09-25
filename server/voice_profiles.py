"""Short-lived, in-process registry for voice cloning credentials.

A voice cloning key is a credential. Before this registry existed the studio
sent it as a `custom_voice_key` query parameter, which meant the raw key was
written into browser history, HTTP access logs, and — because the WebSocket URL
is logged — the `DIAGNOSTIC_LOG_BUFFER` that the in-app Observability drawer
renders back to whoever has the page open.

The exchange now works like this:

    POST /connect  { "custom_voice_key": "<secret>" }
        -> registry.register(secret) -> "vp_<opaque>"
        -> ws_url carries ?voice_profile_id=vp_<opaque>
    WS   /ws?voice_profile_id=vp_<opaque>
        -> registry.consume(id) -> "<secret>"

Profiles are single-use and expire, so a leaked id is worth nothing after the
session starts or the TTL lapses.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from typing import Dict, NamedTuple, Optional

# Long enough for a user to click Connect, short enough that a stray id in a log
# is inert by the time anyone reads it.
PROFILE_TTL_SECONDS = 300

_PREFIX = "vp_"


def get_voice_cloning_key_file(gender: str) -> Optional[str]:
    """Resolve the voice cloning key file path with automatic fallbacks."""
    env_var = "CLONE_TTS_VOICE_KEY_MALE" if gender == "male" else "CLONE_TTS_VOICE_KEY_FEMALE"
    env_path = os.getenv(env_var)
    if env_path and os.path.isfile(env_path):
        return env_path

    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, f"voice_cloning_key_{'m' if gender == 'male' else 'f'}.txt"),
        os.path.join(os.getcwd(), "server", f"voice_cloning_key_{'m' if gender == 'male' else 'f'}.txt"),
        os.path.join(os.getcwd(), f"voice_cloning_key_{'m' if gender == 'male' else 'f'}.txt"),
        f"/app/voice_cloning_key_{'m' if gender == 'male' else 'f'}.txt",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def load_voice_cloning_key(gender: str) -> Optional[str]:
    """Read the voice cloning key for male or female from env or local file."""
    path = get_voice_cloning_key_file(gender)
    if path and os.path.isfile(path):
        try:
            with open(path, "r") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass
    return None


def is_male_clone_voice(voice: Optional[str]) -> bool:
    if not voice or is_gemini_clone_voice(voice):
        return False
    v = str(voice).strip()
    v_lower = v.lower()
    return v in ["Custom-Male", "Chirp3-HD-Clone-Male", "hi-IN-Chirp3-HD-Custom-Male"] or (
        "clone" in v_lower and "male" in v_lower and "female" not in v_lower
    )


def is_female_clone_voice(voice: Optional[str]) -> bool:
    if not voice or is_gemini_clone_voice(voice):
        return False
    v = str(voice).strip()
    v_lower = v.lower()
    return v in ["Custom-Female", "Chirp3-HD-Clone-Female", "hi-IN-Chirp3-HD-Custom-Female"] or (
        "clone" in v_lower and "female" in v_lower
    )


def is_custom_clone_voice(voice: Optional[str]) -> bool:
    """Chirp 3 HD clones only. Gemini 3.8 voicekey clones are a separate product."""
    if not voice:
        return False
    return is_male_clone_voice(voice) or is_female_clone_voice(voice) or (str(voice).strip() == "Custom-Key")


# ---------------------------------------------------------------------------
# Gemini 3.8 TTS cloned voices (voicekey_...)
#
# A different credential from the Chirp clones above: it is passed as
# `types.VoiceConfig(voice=<voicekey>)` to gemini-3.8-flash(-lite)-tts and is
# bound to the AI Studio GEMINI_API_KEY project. It is server-managed: the
# browser selects it by name and never sees or sends the key.
# ---------------------------------------------------------------------------
GEMINI_CLONE_VOICES: Dict[str, str] = {"Gemini-Clone-Male": "male"}
GEMINI_CLONE_TTS_MODELS = frozenset({"gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"})
_GEMINI_KEY_FILES = {"male": "gemini_3_8_voicekey_m.txt", "female": "gemini_3_8_voicekey_f.txt"}


def is_gemini_clone_voice(voice: Optional[str]) -> bool:
    return bool(voice) and str(voice).strip() in GEMINI_CLONE_VOICES


def supports_gemini_clone(tts_model: Optional[str]) -> bool:
    return (tts_model or "").replace("-aistudio", "") in GEMINI_CLONE_TTS_MODELS


def get_gemini_voice_key_file(gender: str) -> Optional[str]:
    env_path = os.getenv("GEMINI_TTS_VOICE_KEY_MALE" if gender == "male" else "GEMINI_TTS_VOICE_KEY_FEMALE")
    if env_path and os.path.isfile(env_path):
        return env_path
    name = _GEMINI_KEY_FILES[gender]
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(base_dir, name), os.path.join(os.getcwd(), "server", name), f"/keys/{name}"):
        if os.path.isfile(c):
            return c
    return None


def load_gemini_voice_key(gender: str) -> Optional[str]:
    path = get_gemini_voice_key_file(gender)
    if not path:
        return None
    try:
        with open(path, "r") as f:
            return f.read().strip() or None
    except OSError:
        return None


def resolve_gemini_voice_key(voice: Optional[str]) -> Optional[str]:
    """Return the voicekey for a Gemini clone selection, None for any other voice."""
    if not is_gemini_clone_voice(voice):
        return None
    gender = GEMINI_CLONE_VOICES[str(voice).strip()]
    key = load_gemini_voice_key(gender)
    if not key:
        raise ValueError(f"The Gemini 3.8 cloned voice ({gender}) has no configured voice key.")
    if not key.startswith("voicekey_"):
        raise ValueError("The Gemini 3.8 cloned voice key must start with voicekey_.")
    return key



def resolve_clone_key(voice: Optional[str], supplied_key: Optional[str] = None) -> Optional[str]:
    """Only an explicitly selected clone can use a credential.

    Browser input is credential text, never a server filesystem path. Named
    voices ignore stale keys. Server-managed clones use the configured files.
    """
    if not is_custom_clone_voice(voice):
        return None
    if voice == "Custom-Key":
        key = (supplied_key or "").strip()
        if not key:
            raise ValueError("Custom-Key requires a voice cloning key. Enter it or select a named voice.")
    else:
        gender = "female" if is_female_clone_voice(voice) else "male"
        key = load_voice_cloning_key(gender)
        if not key:
            raise ValueError(f"The selected {gender} clone has no configured voice cloning key.")
    return key


class _Profile(NamedTuple):
    key: str
    expires_at: float


MAX_PROFILES = 1000
_profiles: Dict[str, _Profile] = {}
_lock = threading.Lock()


def _purge_expired(now: float) -> None:
    """Callers must hold the lock."""
    for profile_id in [pid for pid, p in _profiles.items() if p.expires_at <= now]:
        del _profiles[profile_id]


def register(voice_cloning_key: Optional[str], ttl_seconds: int = PROFILE_TTL_SECONDS) -> Optional[str]:
    """Store a cloning key and return an opaque id, or None for empty input."""
    if not voice_cloning_key or not voice_cloning_key.strip():
        return None
    now = time.time()
    profile_id = f"{_PREFIX}{secrets.token_urlsafe(24)}"
    with _lock:
        _purge_expired(now)
        while len(_profiles) >= MAX_PROFILES:
            oldest_id = next(iter(_profiles))
            del _profiles[oldest_id]
        _profiles[profile_id] = _Profile(voice_cloning_key.strip(), now + ttl_seconds)
    return profile_id


def consume(profile_id: Optional[str]) -> Optional[str]:
    """Redeem an id for its key. Single use: a second call returns None."""
    if not profile_id:
        return None
    now = time.time()
    with _lock:
        _purge_expired(now)
        profile = _profiles.pop(profile_id, None)
    if profile is None:
        return None
    return profile.key


def is_profile_id(value: Optional[str]) -> bool:
    """True when a value looks like an opaque profile id rather than a raw key."""
    return bool(value) and str(value).startswith(_PREFIX)


def active_count() -> int:
    """Number of unredeemed, unexpired profiles. For tests and diagnostics."""
    now = time.time()
    with _lock:
        _purge_expired(now)
        return len(_profiles)


def clear() -> None:
    """Drop every profile. For tests."""
    with _lock:
        _profiles.clear()
