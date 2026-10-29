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
    for c in (f"/keys/{name}", os.path.join(base_dir, name), os.path.join(os.getcwd(), "server", name)):
        if os.path.isfile(c):
            return c
    return None


GEMINI_VOICE_KEY_PREFIXES = ("voicekey_", "voice_")


def is_valid_gemini_voice_key(key: Optional[str]) -> bool:
    """True when `key` is a valid stateless (`voicekey_`) or stateful (`voice_`) Gemini voice ID."""
    return bool(key and str(key).strip().startswith(GEMINI_VOICE_KEY_PREFIXES))


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
    """Return the voicekey/voice ID for a Gemini clone selection, None for any other voice."""
    if not is_gemini_clone_voice(voice):
        return None
    gender = GEMINI_CLONE_VOICES[str(voice).strip()]
    key = load_gemini_voice_key(gender)
    if not key:
        raise ValueError(f"The Gemini 3.8 cloned voice ({gender}) has no configured voice key.")
    if not is_valid_gemini_voice_key(key):
        raise ValueError("The Gemini 3.8 cloned voice key must start with voicekey_ or voice_.")
    return key


LIVE_CUSTOM_VOICE_ID = "Custom-Live-Voice"
_GEMINI_LIVE_SAMPLE_FILES = {"male": "manish_reference_24k.wav"}


def is_live_replicated_voice(voice: Optional[str]) -> bool:
    """True when a Gemini Live voice selection uses Vertex AI ReplicatedVoiceConfig."""
    if not voice:
        return False
    v = str(voice).strip()
    return is_gemini_clone_voice(v) or v == LIVE_CUSTOM_VOICE_ID


# Prebuilt Gemini voices, gendered as the studio labels them (voice-session.ts).
_FEMALE_VOICES = frozenset({
    "achernar", "aoede", "autonoe", "callirhoe", "callirrhoe", "despina", "erinome", "gacrux",
    "kore", "laomedeia", "leda", "pulcherrima", "sulafat", "vindemiatrix", "zephyr",
})
_MALE_VOICES = frozenset({
    "achird", "algenib", "algieba", "alnilam", "charon", "enceladus", "fenrir", "iapetus",
    "orus", "puck", "rasalgethi", "sadachbia", "sadaltager", "schedar", "umbriel", "zubenelgenubi",
})


def voice_gender(voice: Optional[str]) -> Optional[str]:
    """'male' or 'female' when the voice's gender is known; None otherwise (e.g. a recorded voice)."""
    if not voice:
        return None
    v = str(voice).strip()
    if is_gemini_clone_voice(v):
        return GEMINI_CLONE_VOICES[v]
    if is_female_clone_voice(v):
        return "female"
    if is_male_clone_voice(v):
        return "male"
    name = v.rsplit("-", 1)[-1].lower()  # "hi-IN-Chirp3-HD-Charon" -> "charon"
    if name in _FEMALE_VOICES:
        return "female"
    if name in _MALE_VOICES:
        return "male"
    return None


def get_gemini_live_voice_sample_file(gender: str = "male") -> Optional[str]:
    env_path = os.getenv("GEMINI_LIVE_VOICE_SAMPLE_MALE" if gender == "male" else "GEMINI_LIVE_VOICE_SAMPLE_FEMALE")
    if env_path and os.path.isfile(env_path):
        return env_path
    name = _GEMINI_LIVE_SAMPLE_FILES.get(gender)
    if not name:
        return None
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for c in (
        f"/keys/{name}",
        os.path.join(base_dir, name),
        os.path.join(os.getcwd(), "server", name),
        os.path.join(os.getcwd(), name),
        f"/app/{name}",
    ):
        if os.path.isfile(c):
            return c
    return None


def load_gemini_live_voice_sample(voice: Optional[str]) -> Optional[bytes]:
    """Load the pre-bundled 24 kHz 16-bit mono WAV sample for a server-managed Gemini 3.8 clone."""
    if not is_gemini_clone_voice(voice):
        return None
    gender = GEMINI_CLONE_VOICES[str(voice).strip()]
    path = get_gemini_live_voice_sample_file(gender)
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
            return data if data else None
    except OSError:
        return None



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


class VoiceProfileStore:
    """Single-use credential store with optional cross-instance shared backend."""

    def __init__(self, shared_store=None):
        self._profiles: Dict[str, _Profile] = {}
        self._lock = threading.Lock()
        self._shared = shared_store

    def _purge_expired(self, now: float) -> None:
        for profile_id in [pid for pid, p in self._profiles.items() if p.expires_at <= now]:
            del self._profiles[profile_id]

    def register(self, voice_cloning_key: Optional[str], ttl_seconds: int = PROFILE_TTL_SECONDS) -> Optional[str]:
        if not voice_cloning_key or not voice_cloning_key.strip():
            return None
        now = time.time()
        clean = voice_cloning_key.strip()
        profile_id = f"{_PREFIX}{secrets.token_urlsafe(24)}"
        with self._lock:
            self._purge_expired(now)
            while len(self._profiles) >= MAX_PROFILES:
                oldest_id = next(iter(self._profiles))
                del self._profiles[oldest_id]
            self._profiles[profile_id] = _Profile(clean, now + ttl_seconds)
        shared = self._shared
        if shared is not None:
            try:
                shared.register_voice_profile(profile_id, clean, ttl_seconds, now_wall=now)
            except BaseException:
                with self._lock:
                    self._profiles.pop(profile_id, None)
                raise
        return profile_id

    def consume(self, profile_id: Optional[str]) -> Optional[str]:
        if not profile_id:
            return None
        now = time.time()
        if self._shared is not None:
            with self._lock:
                self._purge_expired(now)
                self._profiles.pop(profile_id, None)
            return self._shared.consume_voice_profile(profile_id, now_wall=now)
        with self._lock:
            self._purge_expired(now)
            profile = self._profiles.pop(profile_id, None)
        if profile is None:
            return None
        return profile.key

    def active_count(self) -> int:
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            return len(self._profiles)

    def clear(self) -> None:
        with self._lock:
            self._profiles.clear()
        if self._shared is not None:
            self._shared.clear_voice_profiles()


from shared_session_store import build_default_shared_store as _build_default_shared_store

_default_profile_store = VoiceProfileStore(shared_store=_build_default_shared_store())
_profiles = _default_profile_store._profiles
_lock = _default_profile_store._lock


def configure_shared_store(shared_store=None) -> None:
    _default_profile_store._shared = shared_store


def register(voice_cloning_key: Optional[str], ttl_seconds: int = PROFILE_TTL_SECONDS) -> Optional[str]:
    """Store a cloning key and return an opaque id, or None for empty input."""
    return _default_profile_store.register(voice_cloning_key, ttl_seconds=ttl_seconds)


def consume(profile_id: Optional[str]) -> Optional[str]:
    """Redeem an id for its key. Single use: a second call returns None."""
    return _default_profile_store.consume(profile_id)


def is_profile_id(value: Optional[str]) -> bool:
    """True when a value looks like an opaque profile id rather than a raw key."""
    return bool(value) and str(value).startswith(_PREFIX)


def active_count() -> int:
    """Number of unredeemed, unexpired profiles. For tests and diagnostics."""
    return _default_profile_store.active_count()


def clear() -> None:
    """Drop every profile. For tests."""
    _default_profile_store.clear()

