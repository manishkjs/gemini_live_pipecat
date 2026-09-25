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

        _installed = True
