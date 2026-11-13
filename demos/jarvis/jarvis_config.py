"""API key storage, lookup precedence, and Gemini key validation for Jarvis.

Pure-Python module (standard library only, with optional certifi CA bundle if
installed) so unit tests run anywhere without audio or GUI dependencies.

Lookup order for the Gemini Developer API (AI Studio) key:
1. Environment variables: ``GEMINI_API_KEY``, then ``GOOGLE_API_KEY``
2. ``demos/jarvis/.env`` (unless ``ignore_dotenv=True`` or ``JARVIS_NO_DOTENV=1``)
3. ``~/.jarvis/config.json`` (saved with file mode ``0600``)
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import socket
import ssl
import tempfile
from typing import Any, Callable, Mapping, MutableMapping
import urllib.error
import urllib.request

GEMINI_API_KEY_URL = "https://aistudio.google.com/apikey"
GEMINI_MODELS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"
DEFAULT_DOTENV_PATH = Path(__file__).resolve().parent / ".env"

_KEY_ENV_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
_TRUTHY = ("1", "true", "yes", "on")
_AIZA_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{8,}")


class NoApiKeyError(RuntimeError):
    """Raised when no Gemini API key is found in env, .env, or config.json."""


class ApiKeyRejectedError(RuntimeError):
    """Raised when Gemini rejects the configured API key while connecting."""


@dataclass(frozen=True)
class KeyLookup:
    """Resolved API key and where it came from ('env', 'dotenv', 'config', or None)."""

    key: str | None
    source: str | None


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a candidate Gemini API key against AI Studio."""

    ok: bool
    message: str
    error_kind: str | None = None


def redact_secrets(text: str, *secrets: str | None) -> str:
    """Removes candidate API keys and AIza-prefixed tokens from logs/error messages."""
    if not text:
        return ""
    cleaned = str(text)
    for secret in secrets:
        if secret:
            trimmed = secret.strip()
            if len(trimmed) >= 4:
                cleaned = cleaned.replace(trimmed, "[REDACTED]")
    cleaned = _AIZA_PATTERN.sub("[REDACTED]", cleaned)
    return cleaned


def get_config_dir(
    config_dir: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Returns the Jarvis state directory (defaults to ``~/.jarvis``)."""
    if config_dir is not None:
        return Path(config_dir).expanduser()
    env = environ if environ is not None else os.environ
    override = (env.get("JARVIS_CONFIG_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".jarvis"


def get_config_path(
    config_dir: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Returns ``<config_dir>/config.json``."""
    return get_config_dir(config_dir=config_dir, environ=environ) / "config.json"


def parse_dotenv(content: str) -> dict[str, str]:
    """Minimal pure-Python ``.env`` parser for ``KEY=VALUE`` files."""
    values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") and "=" in line[7:]:
            line = line[7:].strip()
        if "=" not in line:
            continue
        name, raw_val = line.split("=", 1)
        name = name.strip()
        if not name:
            continue
        val = raw_val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        values[name] = val
    return values


def load_dotenv_file(dotenv_path: Path | None = None) -> dict[str, str]:
    """Reads ``demos/jarvis/.env`` if it exists; returns ``{}`` otherwise."""
    path = dotenv_path if dotenv_path is not None else DEFAULT_DOTENV_PATH
    try:
        if not path.is_file():
            return {}
        return parse_dotenv(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def is_dotenv_disabled(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return (env.get("JARVIS_NO_DOTENV") or "").strip().lower() in _TRUTHY


def load_non_secret_dotenv_into_environ(
    dotenv_path: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Loads optional non-key settings from ``.env`` without masking key source."""
    env = environ if environ is not None else os.environ
    if is_dotenv_disabled(env):
        return
    for name, value in load_dotenv_file(dotenv_path).items():
        if name in _KEY_ENV_NAMES:
            continue
        env.setdefault(name, value)


def load_saved_api_key(
    config_path: Path | None = None,
    *,
    config_dir: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Loads ``gemini_api_key`` from ``~/.jarvis/config.json`` if present."""
    path = config_path or get_config_path(config_dir=config_dir, environ=environ)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("gemini_api_key")
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    return cleaned or None


def save_api_key(
    key: str,
    config_path: Path | None = None,
    *,
    config_dir: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Atomically writes ``gemini_api_key`` to ``~/.jarvis/config.json`` with mode 0600."""
    cleaned = _normalize_candidate_key(key)
    if not cleaned or any(ch.isspace() for ch in cleaned):
        raise ValueError("API key must be a non-empty string without spaces.")

    path = config_path or get_config_path(config_dir=config_dir, environ=environ)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = loaded
    except (OSError, ValueError, TypeError):
        existing = {}

    existing["gemini_api_key"] = cleaned
    payload = (json.dumps(existing, indent=2) + "\n").encode("utf-8")

    fd, tmp_name = tempfile.mkstemp(prefix=".config.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fp:
            fp.write(payload)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_path, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return path


def lookup_api_key(
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = DEFAULT_DOTENV_PATH,
    config_path: Path | None = None,
    config_dir: Path | str | None = None,
    ignore_dotenv: bool | None = None,
) -> KeyLookup:
    """Finds the Gemini API key following ``env -> demos/jarvis/.env -> config.json``."""
    env = environ if environ is not None else os.environ
    skip_dotenv = is_dotenv_disabled(env) if ignore_dotenv is None else bool(ignore_dotenv)
    dotenv_vals = {} if skip_dotenv or dotenv_path is None else load_dotenv_file(dotenv_path)

    vertex_flag = (
        env.get("GOOGLE_GENAI_USE_VERTEXAI")
        or dotenv_vals.get("GOOGLE_GENAI_USE_VERTEXAI")
        or ""
    ).strip().lower()
    if vertex_flag in ("1", "true"):
        raise RuntimeError("Jarvis does not use Vertex AI. Unset GOOGLE_GENAI_USE_VERTEXAI.")

    for var in _KEY_ENV_NAMES:
        val = (env.get(var) or "").strip()
        if val:
            return KeyLookup(key=val, source="env")

    for var in _KEY_ENV_NAMES:
        val = (dotenv_vals.get(var) or "").strip()
        if val:
            return KeyLookup(key=val, source="dotenv")

    saved = load_saved_api_key(config_path, config_dir=config_dir, environ=env)
    if saved:
        return KeyLookup(key=saved, source="config")

    return KeyLookup(key=None, source=None)


def resolve_api_key(
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = DEFAULT_DOTENV_PATH,
    config_path: Path | None = None,
    config_dir: Path | str | None = None,
    ignore_dotenv: bool | None = None,
) -> str:
    """Returns the active Gemini API key or raises :class:`NoApiKeyError`."""
    found = lookup_api_key(
        environ=environ,
        dotenv_path=dotenv_path,
        config_path=config_path,
        config_dir=config_dir,
        ignore_dotenv=ignore_dotenv,
    )
    if not found.key:
        raise NoApiKeyError(
            "No Gemini API key configured. Paste an AI Studio key in Jarvis Setup "
            "or set GEMINI_API_KEY."
        )
    return found.key


def _normalize_candidate_key(raw_key: str) -> str:
    cleaned = (raw_key or "").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _default_urlopen(req: urllib.request.Request, timeout: float):
    ctx = ssl.create_default_context()
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            try:
                import certifi  # type: ignore[import-not-found]

                cert_ctx = ssl.create_default_context(cafile=certifi.where())
                return urllib.request.urlopen(req, timeout=timeout, context=cert_ctx)
            except ImportError:
                pass
        raise


def validate_gemini_api_key(
    key: str,
    *,
    opener: Callable[[urllib.request.Request, float], Any] | None = None,
    timeout: float = 8.0,
) -> ValidationResult:
    """Validates a Gemini API key with a zero-token ``models?pageSize=1`` call."""
    cleaned = _normalize_candidate_key(key)
    if not cleaned:
        return ValidationResult(
            ok=False,
            message="Paste your Gemini API key first.",
            error_kind="empty",
        )
    if any(ch.isspace() for ch in cleaned) or not cleaned.isascii():
        return ValidationResult(
            ok=False,
            message="That doesn't look like a valid API key — check for extra spaces or line breaks.",
            error_kind="format",
        )

    req = urllib.request.Request(
        GEMINI_MODELS_ENDPOINT,
        headers={
            "x-goog-api-key": cleaned,
            "Accept": "application/json",
        },
        method="GET",
    )
    open_fn = opener or _default_urlopen

    try:
        with open_fn(req, timeout) as resp:
            status = getattr(resp, "status", 200)
            body = resp.read().decode("utf-8", "replace")
        if 200 <= status < 300:
            data = json.loads(body) if body else {}
            if isinstance(data, dict) and "models" in data:
                return ValidationResult(ok=True, message="API key verified.")
            return ValidationResult(ok=True, message="API key verified.")
        return ValidationResult(
            ok=False,
            message="Unexpected response from Gemini. Please try again.",
            error_kind="server",
        )
    except urllib.error.HTTPError as exc:
        raw_body = ""
        try:
            raw_body = exc.read().decode("utf-8", "replace")
        except Exception:
            raw_body = ""
        return _classify_http_validation_error(exc.code, raw_body, cleaned)
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError):
        return ValidationResult(
            ok=False,
            message="Couldn't reach Google's Gemini servers. Check your internet connection and try again.",
            error_kind="network",
        )


def _classify_http_validation_error(code: int, body: str, key: str) -> ValidationResult:
    lowered = redact_secrets(body, key).lower()
    if code in (400, 401):
        if "expired" in lowered:
            return ValidationResult(
                ok=False,
                message="This API key has expired. Create a new key in Google AI Studio.",
                error_kind="rejected",
            )
        return ValidationResult(
            ok=False,
            message="Gemini rejected this API key. Make sure you copied the full key from Google AI Studio.",
            error_kind="rejected",
        )
    if code == 403:
        return ValidationResult(
            ok=False,
            message="Gemini denied access for this key. Check that the Gemini API is enabled and the key isn't restricted.",
            error_kind="rejected",
        )
    if code == 429:
        return ValidationResult(
            ok=False,
            message="Gemini rate-limited the check. Wait a few seconds and try again.",
            error_kind="rate_limit",
        )
    if code >= 500:
        return ValidationResult(
            ok=False,
            message="Google's Gemini service is temporarily unavailable. Please try again shortly.",
            error_kind="server",
        )
    return ValidationResult(
        ok=False,
        message=f"Gemini rejected the request (HTTP {code}). Check your key and try again.",
        error_kind="rejected",
    )


def classify_gemini_auth_error(
    exc: BaseException | None,
    error_text: str = "",
    *secrets: str | None,
) -> str | None:
    """Returns a plain-language reason if an error means Gemini rejected the API key."""
    if isinstance(exc, ApiKeyRejectedError):
        return redact_secrets(str(exc), *secrets) or (
            "Gemini rejected the saved API key. Please enter a new key."
        )

    parts = []
    if exc is not None:
        parts.append(str(exc))
    if error_text:
        parts.append(error_text)
    combined = redact_secrets(" ".join(parts), *secrets).lower()
    if not combined:
        return None

    code = getattr(exc, "code", None)
    if "api key expired" in combined or "api_key_expired" in combined:
        return "Gemini rejected the saved API key because it has expired. Paste a new key below."

    if any(
        phrase in combined
        for phrase in (
            "api key not valid",
            "api_key_invalid",
            "invalid api key",
            "api key not found",
            "pass a valid api key",
            "unauthenticated",
            "invalid authentication credentials",
        )
    ) or code == 401:
        return "Gemini rejected the saved API key. Paste a valid key from Google AI Studio."

    if code == 403 or "permission_denied" in combined:
        return (
            "Gemini denied access for the saved API key. Check its restrictions in "
            "Google AI Studio or paste a new key."
        )

    if any(ws_code in combined for ws_code in ("1007", "1008")) and "api key" in combined:
        return "Gemini rejected the saved API key. Paste a valid key from Google AI Studio."

    return None
