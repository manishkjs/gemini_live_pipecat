"""A cascade turn must close its TTS audio context as soon as the LLM finishes.

Pipecat 1.2 closes an HTTP TTS turn at LLMFullResponseEndFrame only when the
*last* run_tts call yielded audio. A Gemini 3.8 reply that ends in a markup-only
fragment (a trailing `<laugh>` or a lone [[direction]]) yields none, so the turn
used to wait out the 3 s stop-frame timeout before it could end.
"""
import unittest
from unittest.mock import AsyncMock, patch

from pipecat.frames.frames import TTSAudioRawFrame


def _service():
    # The pipecat base builds a client in __init__; this test is about turn
    # bookkeeping, so it must not depend on local credentials.
    from agent import CustomVertexGeminiTTSService
    from pipecat.services.google.tts import GeminiTTSService

    with patch.object(GeminiTTSService, "_create_client", return_value=None), \
         patch("agent.genai.Client", return_value=None):
        return CustomVertexGeminiTTSService(project_id="p", location="us-central1", model="gemini-3.8-flash-lite-tts")


async def _one_audio_chunk():
    yield TTSAudioRawFrame(b"\x00\x00" * 240, 24000, 1)


class TestTurnClosesAfterMarkupOnlyFragment(unittest.IsolatedAsyncioTestCase):
    async def _finish_turn(self, *fragments):
        svc = _service()
        svc.append_to_audio_context = AsyncMock()
        svc.remove_audio_context = AsyncMock()
        svc.flush_audio = AsyncMock()
        await svc.tts_process_generator("ctx", _one_audio_chunk())
        for text in fragments:
            await svc.tts_process_generator("ctx", svc.run_tts(text, "ctx"))
        svc._turn_context_id = "ctx"
        with patch.object(svc, "audio_context_available", return_value=True):
            await svc.on_turn_context_completed()
        return svc

    async def test_trailing_vocal_tag_still_closes_the_turn(self):
        svc = await self._finish_turn("<laugh>")
        svc.remove_audio_context.assert_awaited_once_with("ctx")

    async def test_trailing_direction_block_still_closes_the_turn(self):
        svc = await self._finish_turn("[[warm, low pitch, slow]]")
        svc.remove_audio_context.assert_awaited_once_with("ctx")


if __name__ == "__main__":
    unittest.main()
