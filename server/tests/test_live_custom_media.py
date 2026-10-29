"""Custom Live media (recorded voice, uploaded avatar) must degrade, never break.

Vertex AI rejects an unusable custom voice or avatar at setup with a websocket
close code 1007/1008 ("Failed to parse WAV audio", "Current project is not
allowlisted for customized avatar feature"). The session then continues with
the prebuilt voice or avatar and tells the user why. Anything else (quota,
overload, a timeout) is a real outage and must surface, never be papered over
by a silent swap.
"""
import asyncio
import base64
import io
import math
import struct
import unittest
import wave
from unittest.mock import AsyncMock

from google.genai import errors
from google.genai.types import (
    GenerationConfig,
    LiveConnectConfig,
    Modality,
    SpeechConfig,
    VoiceConfig,
)
from pipecat.frames.frames import OutputTransportMessageFrame

import agent_live
from agent_live import classify_custom_media_rejection


def _close(code, reason):
    """What google-genai raises when Live closes the socket during setup."""
    return errors.APIError(code, reason, None)


AVATAR_NOT_ALLOWLISTED = _close(1007, "Current project is not allowlisted for customized avatar feature.")
WAV_UNPARSEABLE = _close(1007, "Failed to parse WAV audio: unexpected end of data.")
GENERIC_INVALID = _close(1007, "Request contains an invalid argument.")


def _wav(seconds=3.0, rate=24000):
    frames = b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * 220 * i / rate)))
        for i in range(int(seconds * rate))
    )
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)
    return out.getvalue()


def _png_data_url():
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (90, 160), (200, 150, 120)).save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def _pipecat_config():
    """The config Pipecat's _connect builds: prebuilt voice under generation_config."""
    return LiveConnectConfig(
        generation_config=GenerationConfig(
            response_modalities=[Modality.AUDIO],
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(prebuilt_voice_config={"voice_name": "Puck"}),
                language_code="en-US",
            ),
        ),
    )


class _FakeLive:
    """Stands in for Pipecat's GeminiLiveLLMService (the AI Studio gateway)."""

    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.attempts = []
        self.base_errors = []

    async def _connection_task_handler(self, config):
        self.attempts.append(config)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, BaseException):
            raise outcome

    async def _handle_connection_error(self, error):
        self.base_errors.append(error)
        return True

    async def _handle_session_ready(self, session):
        pass


class _Live(agent_live.GeminiSessionLoggerMixin, _FakeLive):
    pass


def _service(outcomes=(), *, voice_sample=None, avatar_image=None, avatar=False):
    llm = _Live(outcomes)
    llm._language_code = "en-US"
    llm._avatar_enabled = avatar or bool(avatar_image)
    llm._avatar_name = "Ben"
    llm._avatar_custom_image = avatar_image
    llm._replicated_voice_sample = voice_sample
    llm._fallback_voice_name = "Puck"
    return llm


def _connect(llm):
    asyncio.run(llm._connection_task_handler(config=_pipecat_config()))


def _voice(config):
    return config.generation_config.speech_config.voice_config


class TestClassifyCustomMediaRejection(unittest.TestCase):
    def test_avatar_allowlist_rejection_blames_only_the_avatar(self):
        self.assertEqual(
            classify_custom_media_rejection(AVATAR_NOT_ALLOWLISTED, avatar=True, voice=True), {"avatar"})

    def test_wav_parse_failure_blames_only_the_voice(self):
        self.assertEqual(classify_custom_media_rejection(WAV_UNPARSEABLE, avatar=True, voice=True), {"voice"})

    def test_an_unnamed_rejection_blames_everything_custom(self):
        self.assertEqual(
            classify_custom_media_rejection(GENERIC_INVALID, avatar=True, voice=True), {"avatar", "voice"})
        self.assertEqual(classify_custom_media_rejection(GENERIC_INVALID, avatar=False, voice=True), {"voice"})

    def test_blame_on_media_the_session_does_not_have_is_not_ours(self):
        self.assertEqual(classify_custom_media_rejection(AVATAR_NOT_ALLOWLISTED, avatar=False, voice=True), set())
        self.assertEqual(classify_custom_media_rejection(GENERIC_INVALID, avatar=False, voice=False), set())

    def test_quota_and_overload_are_outages_not_bad_media(self):
        for error in (
            _close(1008, "Resource exhausted: quota exceeded for customized avatar."),
            _close(1007, "Rate limit reached for replicated voice, try again later."),
            _close(1008, "Service unavailable."),
            _close(429, "Resource exhausted"),
            _close(1011, "Internal error while loading the voice sample."),
            TimeoutError("voice setup timed out"),
        ):
            with self.subTest(error=str(error)):
                self.assertEqual(classify_custom_media_rejection(error, avatar=True, voice=True), set())

    def test_close_code_in_the_message_is_enough(self):
        self.assertEqual(
            classify_custom_media_rejection(
                RuntimeError("1007 None. Failed to parse WAV audio."), avatar=False, voice=True),
            {"voice"})


class TestRejectionRetry(unittest.TestCase):
    def test_rejected_voice_retries_once_with_the_prebuilt_voice(self):
        llm = _service([WAV_UNPARSEABLE], voice_sample=_wav())
        _connect(llm)

        first, retry = llm.attempts
        self.assertIsNotNone(_voice(first).replicated_voice_config)
        self.assertIsNotNone(first.speech_config.voice_config.replicated_voice_config)
        self.assertEqual(_voice(retry).prebuilt_voice_config.voice_name, "Puck")
        self.assertIsNone(_voice(retry).replicated_voice_config)
        self.assertIsNone(retry.speech_config)
        self.assertIsNone(llm._replicated_voice_sample)
        self.assertEqual(llm._voice_fallback_notice["code"], "rejected")
        self.assertEqual(llm._voice_fallback_notice["fallback_voice"], "Puck")

    def test_ai_studio_gateway_configures_a_voice_clone_without_crashing(self):
        llm = _service(voice_sample=_wav())
        _connect(llm)

        (config,) = llm.attempts
        self.assertEqual(config.speech_config.language_code, "en-US")
        self.assertEqual(config.speech_config.voice_config.replicated_voice_config.mime_type, "audio/pcm;rate=24000")

    def test_avatar_rejection_keeps_the_custom_voice(self):
        llm = _service([AVATAR_NOT_ALLOWLISTED], voice_sample=_wav(), avatar_image=_png_data_url())
        _connect(llm)

        first, retry = llm.attempts
        self.assertIsNotNone(first.avatar_config.customized_avatar)
        self.assertEqual(retry.avatar_config.avatar_name, "Ben")
        self.assertIsNone(retry.avatar_config.customized_avatar)
        self.assertEqual(retry.response_modalities, [Modality.VIDEO])
        self.assertIsNotNone(_voice(retry).replicated_voice_config)
        self.assertEqual(llm._avatar_fallback_notice["code"], "project_not_allowlisted")
        self.assertIsNone(getattr(llm, "_voice_fallback_notice", None))

    def test_each_rejection_drops_one_more_part_then_the_error_surfaces(self):
        llm = _service(
            [AVATAR_NOT_ALLOWLISTED, WAV_UNPARSEABLE, GENERIC_INVALID],
            voice_sample=_wav(),
            avatar_image=_png_data_url(),
        )
        with self.assertRaises(errors.APIError) as raised:
            _connect(llm)

        self.assertIs(raised.exception, GENERIC_INVALID)
        self.assertEqual(len(llm.attempts), 3)
        self.assertEqual(llm.attempts[2].avatar_config.avatar_name, "Ben")
        self.assertEqual(_voice(llm.attempts[2]).prebuilt_voice_config.voice_name, "Puck")

    def test_quota_error_surfaces_without_touching_the_custom_media(self):
        quota = _close(1008, "Resource exhausted. Quota exceeded.")
        sample, image = _wav(), _png_data_url()
        llm = _service([quota], voice_sample=sample, avatar_image=image)
        with self.assertRaises(errors.APIError) as raised:
            _connect(llm)

        self.assertIs(raised.exception, quota)
        self.assertEqual(len(llm.attempts), 1)
        self.assertEqual(llm._replicated_voice_sample, sample)
        self.assertEqual(llm._avatar_custom_image, image)
        self.assertIsNone(getattr(llm, "_voice_fallback_notice", None))
        self.assertIsNone(getattr(llm, "_avatar_fallback_notice", None))

    def test_unreadable_sample_falls_back_before_connecting(self):
        llm = _service(voice_sample=b"definitely not a wav file, just some bytes")
        _connect(llm)

        (config,) = llm.attempts
        self.assertEqual(_voice(config).prebuilt_voice_config.voice_name, "Puck")
        self.assertIsNone(config.speech_config)
        self.assertEqual(llm._voice_fallback_notice["code"], "invalid_sample")

    def test_unreadable_image_falls_back_before_connecting(self):
        llm = _service(avatar_image="data:image/png;base64," + base64.b64encode(b"not an image").decode())
        _connect(llm)

        (config,) = llm.attempts
        self.assertEqual(config.avatar_config.avatar_name, "Ben")
        self.assertEqual(llm._avatar_fallback_notice["code"], "invalid_image")

    def test_plain_session_config_is_untouched(self):
        llm = _service()
        _connect(llm)

        (config,) = llm.attempts
        self.assertEqual(_voice(config).prebuilt_voice_config.voice_name, "Puck")
        self.assertIsNone(config.speech_config)
        self.assertIsNone(config.avatar_config)
        self.assertEqual(config.generation_config.response_modalities, [Modality.AUDIO])


class TestMidSessionRejection(unittest.TestCase):
    def test_rejection_after_setup_clears_the_media_for_the_reconnect(self):
        llm = _service(voice_sample=_wav())

        should_reconnect = asyncio.run(llm._handle_connection_error(WAV_UNPARSEABLE))

        self.assertTrue(should_reconnect)
        self.assertEqual(llm.base_errors, [WAV_UNPARSEABLE])
        self.assertIsNone(llm._replicated_voice_sample)
        self.assertEqual(llm._voice_fallback_notice["code"], "rejected")
        _connect(llm)
        self.assertIsNone(_voice(llm.attempts[0]).replicated_voice_config)

    def test_outage_after_setup_keeps_the_media(self):
        sample = _wav()
        llm = _service(voice_sample=sample)

        asyncio.run(llm._handle_connection_error(_close(1011, "Internal error.")))

        self.assertEqual(llm._replicated_voice_sample, sample)
        self.assertIsNone(getattr(llm, "_voice_fallback_notice", None))


class TestFallbackNotices(unittest.TestCase):
    def test_session_ready_tells_the_client_once_about_each_fallback(self):
        llm = _service()
        llm.push_frame = AsyncMock()
        llm._avatar_fallback_notice = {"fallback_avatar": "Ben", "reason": "r1", "code": "rejected"}
        llm._voice_fallback_notice = {"fallback_voice": "Puck", "reason": "r2", "code": "missing_sample"}

        asyncio.run(llm._handle_session_ready(object()))
        asyncio.run(llm._handle_session_ready(object()))

        pushed = [call.args[0] for call in llm.push_frame.await_args_list]
        self.assertTrue(all(isinstance(frame, OutputTransportMessageFrame) for frame in pushed))
        self.assertEqual(
            [frame.message["data"] for frame in pushed],
            [
                {"type": "avatar_fallback", "fallback_avatar": "Ben", "reason": "r1", "code": "rejected"},
                {"type": "voice_fallback", "fallback_voice": "Puck", "reason": "r2", "code": "missing_sample"},
            ],
        )


class TestLiveVoiceSampleSelection(unittest.TestCase):
    def test_recorded_audio_is_the_sample(self):
        sample = _wav()
        data_url = "data:audio/wav;base64," + base64.b64encode(sample).decode()
        self.assertEqual(agent_live.load_live_voice_sample("Custom-Live-Voice", data_url), (sample, True))

    def test_a_clone_without_a_sample_is_requested_but_empty(self):
        self.assertEqual(agent_live.load_live_voice_sample("Custom-Live-Voice", None), (None, True))
        self.assertEqual(agent_live.load_live_voice_sample("Custom-Live-Voice", "data:audio/wav;base64,@@@"), (None, True))

    def test_prebuilt_voice_requests_no_clone(self):
        self.assertEqual(agent_live.load_live_voice_sample("Puck", None), (None, False))


if __name__ == "__main__":
    unittest.main()
