"""Existing media SDK compatibility patches, installed only when a call starts."""
import threading

_lock = threading.Lock()
_installed = False


def install_runtime_patches():
    global _installed
    with _lock:
        if _installed:
            return
        # Monkey-patch for google-genai BaseApiClient to fix AttributeError in aclose
        from google.genai._api_client import BaseApiClient

        async def patched_aclose(self):
            if hasattr(self, '_async_httpx_client') and self._async_httpx_client:
                try:
                    await self._async_httpx_client.aclose()
                except Exception:
                    pass
            if hasattr(self, '_aiohttp_session') and self._aiohttp_session:
                try:
                    await self._aiohttp_session.close()
                except Exception:
                    pass

        BaseApiClient.aclose = patched_aclose

        # Monkey-patch for Pipecat FrameProcessor to fix bug when frames arrive before StartFrame
        from pipecat.processors.frame_processor import FrameProcessor
        from pipecat.frames.frames import SystemFrame

        # Fix for missing attribute fallback
        FrameProcessor._FrameProcessor__process_queue = None

        async def patched_input_frame_task_handler(self):
            while True:
                (frame, direction, callback) = await self._FrameProcessor__input_queue.get()

                if self._FrameProcessor__should_block_system_frames and self._FrameProcessor__input_event:
                    await self._FrameProcessor__input_event.wait()
                    self._FrameProcessor__input_event.clear()
                    self._FrameProcessor__should_block_system_frames = False

                if isinstance(frame, SystemFrame):
                    await self._FrameProcessor__process_frame(frame, direction, callback)
                elif hasattr(self, '_FrameProcessor__process_queue') and self._FrameProcessor__process_queue:
                    await self._FrameProcessor__process_queue.put((frame, direction, callback))
                else:
                    # Ignore frames before start instead of crashing
                    pass

                self._FrameProcessor__input_queue.task_done()

        FrameProcessor._FrameProcessor__input_frame_task_handler = patched_input_frame_task_handler

        _ensure_valid_adc()
        _installed = True


_cached_adc_creds = None
_cached_adc_mtime = None


def _ensure_valid_adc():
    """Ensure Application Default Credentials can refresh a token for Vertex AI.

    On dual-account developer machines (e.g. corp @google.com + Argolis altostrat.com),
    `~/.config/gcloud/application_default_credentials.json` may hold a restricted corp
    credential (`access_denied: Account restricted`). When default ADC refresh fails,
    fall back to a working `adc.json` under `~/.config/gcloud/legacy_credentials/`.
    Caches the validated credential in-process so individual WebSocket calls do not
    pay a redundant OAuth HTTP roundtrip before opening the Vertex stream.
    """
    global _cached_adc_creds, _cached_adc_mtime
    import glob
    import os
    import google.auth
    import google.auth.transport.requests

    adc_default_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.path.expanduser(
        "~/.config/gcloud/application_default_credentials.json"
    )
    try:
        mtime = os.path.getmtime(adc_default_path)
    except OSError:
        mtime = None

    if _cached_adc_creds is not None and mtime == _cached_adc_mtime:
        if getattr(_cached_adc_creds, "valid", False) and not getattr(_cached_adc_creds, "expired", False):
            return _cached_adc_creds
        try:
            _cached_adc_creds.refresh(google.auth.transport.requests.Request())
            return _cached_adc_creds
        except Exception:
            _cached_adc_creds = None

    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        _cached_adc_creds = creds
        _cached_adc_mtime = mtime
        return creds
    except Exception:
        pass

    pattern = os.path.expanduser("~/.config/gcloud/legacy_credentials/*/adc.json")
    candidates = sorted(
        glob.glob(pattern),
        key=lambda p: (0 if "altostrat.com" in p else (2 if "@google.com" in p else 1), p),
    )
    for path in candidates:
        try:
            creds, _ = google.auth.load_credentials_from_file(
                path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(google.auth.transport.requests.Request())
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
            _cached_adc_creds = creds
            try:
                _cached_adc_mtime = os.path.getmtime(path)
            except OSError:
                _cached_adc_mtime = None
            return creds
        except Exception:
            continue
    return None


