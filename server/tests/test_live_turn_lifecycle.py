"""Gemini Live turn lifecycle, exercised through the real Pipecat service.

Regressions from Critique 1-5 (2026-09-27), each verified against Pipecat 1.2.1:

1. A spoken turn must close: TTSStoppedFrame + LLMFullResponseEndFrame reach the
   pipeline, or turn telemetry marks every turn "abandoned".
2. A barge-in detected by Gemini's own VAD (``server_content.interrupted``) is an
   interruption: the client hears about it, the half-sentence is recorded as
   interrupted (even if trailing output_transcription chunks arrive before
   turn_complete), and turn_complete does NOT emit LLMFullResponseEndFrame for
   the aborted turn.
3. A barge-in detected by local Silero VAD (``process_frame(InterruptionFrame)``)
   flushes the avatar MSE buffer (``avatar_interrupted``), marks the active turn
   ``"interrupted"``, and releases ``_live_output_turn`` so the next turn binds.
4. Downstream ``UserStoppedSpeakingFrame`` from ``context_aggregator.user()``
   (which bypasses ``TurnBoundaryProcessor`` and has no ``ORIGIN_KEY``) must
   never wipe ``_last_input_turn = None`` in Silero modes, and must advance
   ``TurnTracker`` in ``"gemini"`` (server-VAD-only) mode.
5. In ``vad_mode="silero"`` (``_vad_disabled=True``), ``VADUserStoppedSpeakingFrame``
   sends ``ActivityEnd`` immediately without waiting 600-5000 ms for the text
   aggregator, and without sending a duplicate on ``UserStoppedSpeakingFrame``.
6. Live Avatar turns carry only video/mp4, yet still report TTFT and speaking frames.
7. TTFT handles late aggregator timeouts, mid-utterance pauses, fast server-VAD
   replies (<400 ms before local VAD stop), and idle re-prompts.
8. ``UserIdleProcessor`` resets on local VAD frames and pauses while the bot is
   speaking on audio turns as well as avatar turns.
"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

import agent_live
from processors.turn_telemetry import ServerAudioTimingProcessor, TurnBoundaryProcessor
from turn_telemetry import TurnTracker


def _msg(*, text=None, audio=None, video=None, transcript=None, user_transcript=None, turn_complete=False):
    parts = []
    if audio is not None:
        parts.append(SimpleNamespace(text=None, thought=None,
                                     inline_data=SimpleNamespace(mime_type="audio/pcm;rate=24000", data=audio)))
    if video is not None:
        parts.append(SimpleNamespace(text=None, thought=None,
                                     inline_data=SimpleNamespace(mime_type="video/mp4", data=video)))
    if text is not None:
        parts.append(SimpleNamespace(text=text, thought=None, inline_data=None))
    sc = SimpleNamespace(
        model_turn=SimpleNamespace(parts=parts) if parts else None,
        output_transcription=SimpleNamespace(text=transcript) if transcript else None,
        input_transcription=SimpleNamespace(text=user_transcript) if user_transcript else None,
        grounding_metadata=None,
        turn_complete=turn_complete,
        interrupted=False,
    )
    return SimpleNamespace(server_content=sc, usage_metadata=None)


class _Harness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pushed = []

        async def capture(proc, frame, direction=FrameDirection.DOWNSTREAM):
            self.pushed.append((frame, direction))

        patches = [
            patch.object(FrameProcessor, "push_frame", new=capture),
            patch.object(FrameProcessor, "broadcast_interruption", new=AsyncMock()),
            patch.object(FrameProcessor, "stop_all_metrics", new=AsyncMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.llm = agent_live.CustomGeminiLiveLLMService(api_key="dummy")

    def frames(self, cls, direction=None):
        return [f for f, d in self.pushed if isinstance(f, cls) and (direction is None or d == direction)]

    def metrics(self, kind):
        out = []
        for f, _ in self.pushed:
            if isinstance(f, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)) and isinstance(f.message, dict):
                data = f.message.get("data", {})
                if data.get("type") == "metrics" and data.get("payload", {}).get("type") == kind:
                    out.append(data["payload"])
        return out

    def server_messages(self, msg_type):
        out = []
        for f, _ in self.pushed:
            if isinstance(f, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)) and isinstance(f.message, dict):
                data = f.message.get("data", {})
                if data.get("type") == msg_type:
                    out.append(data)
        return out


class TestSpokenTurnCloses(_Harness):
    async def test_completed_audio_turn_emits_response_end_frames(self):
        await self.llm._handle_msg_output_transcription(_msg(transcript="Namaste bhai"))
        await self.llm._handle_msg_model_turn(_msg(audio=b"\x01\x00" * 240))
        await self.llm._handle_msg_turn_complete(_msg(turn_complete=True))

        self.assertEqual(len(self.frames(TTSStoppedFrame)), 1)
        self.assertEqual(len(self.frames(LLMFullResponseEndFrame)), 1)

    async def test_audio_before_transcript_still_closes(self):
        await self.llm._handle_msg_model_turn(_msg(audio=b"\x01\x00" * 240))
        await self.llm._handle_msg_output_transcription(_msg(transcript="Namaste"))
        await self.llm._handle_msg_turn_complete(_msg(turn_complete=True))

        self.assertEqual(len(self.frames(LLMFullResponseEndFrame)), 1)


class TestServerVadBargeIn(_Harness):
    async def test_gemini_vad_interruption_is_reported_and_does_not_emit_response_end(self):
        await self.llm._handle_msg_output_transcription(_msg(transcript="Bilkul saaf aa rahi hai bhai! Bataiye, AeroNxt"))
        await self.llm._handle_msg_model_turn(_msg(audio=b"\x01\x00" * 240))

        # What Pipecat does on server_content.interrupted, followed by a trailing
        # output_transcription chunk and Gemini's turn_complete 3 ms later.
        await self.llm.broadcast_interruption()
        await self.llm._handle_msg_output_transcription(_msg(transcript=" mein aapki"))
        await self.llm._handle_msg_turn_complete(_msg(turn_complete=True))

        self.assertEqual(len(self.metrics("interruption")), 1)
        self.assertEqual(
            len(self.frames(LLMFullResponseEndFrame)), 0,
            "an interrupted turn must not emit LLMFullResponseEndFrame on turn_complete",
        )
        history = [t["text"] for t in self.llm._dialogue_history if t["role"] == "Assistant"]
        self.assertEqual(history, ["Bilkul saaf aa rahi hai bhai! Bataiye, AeroNxt [interrupted]"])

    async def test_interruption_with_nothing_playing_is_not_reported(self):
        await self.llm.broadcast_interruption()
        self.assertEqual(self.metrics("interruption"), [])


class TestLocalVadBargeIn(_Harness):
    async def test_local_vad_interruption_flushes_avatar_and_releases_turn_slot(self):
        self.llm._avatar_enabled = True
        tracker = TurnTracker("sess-local-barge", "gemini-live", vad_stop_padding_ms=400)
        boundary = TurnBoundaryProcessor(tracker)
        self.llm._turn_tracker = tracker

        with patch.object(FrameProcessor, "process_frame", new=AsyncMock()):
            start1 = VADUserStartedSpeakingFrame()
            stop1 = VADUserStoppedSpeakingFrame()
            await boundary.process_frame(start1, FrameDirection.DOWNSTREAM)
            await boundary.process_frame(stop1, FrameDirection.DOWNSTREAM)

        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(stop1, FrameDirection.DOWNSTREAM)

        turn1 = tracker.current
        await self.llm._handle_msg_output_transcription(_msg(transcript="Main abhi"))
        await self.llm._handle_msg_model_turn(_msg(video=b"\x00" * 16))

        # User barges in via local Silero VAD -> context_aggregator pushes InterruptionFrame
        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)

        self.assertEqual(len(self.server_messages("avatar_interrupted")), 1)
        self.assertEqual(turn1.status, "interrupted")
        self.assertIsNone(self.llm._live_output_turn)

        # User finishes second utterance -> Turn 2 must bind cleanly
        with patch.object(FrameProcessor, "process_frame", new=AsyncMock()):
            start2 = VADUserStartedSpeakingFrame()
            stop2 = VADUserStoppedSpeakingFrame()
            await boundary.process_frame(start2, FrameDirection.DOWNSTREAM)
            await boundary.process_frame(stop2, FrameDirection.DOWNSTREAM)

        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(stop2, FrameDirection.DOWNSTREAM)

        self.assertEqual(self.llm._live_output_turn.turn_id, 2)


class TestPipelineTurnAttribution(_Harness):
    async def test_downstream_aggregator_user_stop_does_not_wipe_silero_turn(self):
        tracker = TurnTracker("sess-silero-attr", "gemini-live", vad_stop_padding_ms=400)
        boundary = TurnBoundaryProcessor(tracker)
        timing = ServerAudioTimingProcessor()
        self.llm._turn_tracker = tracker
        self.llm._last_input_turn = tracker.current
        self.llm._live_output_turn = None

        with patch.object(FrameProcessor, "process_frame", new=AsyncMock()):
            vad_start = VADUserStartedSpeakingFrame()
            vad_stop = VADUserStoppedSpeakingFrame()
            await boundary.process_frame(vad_start, FrameDirection.DOWNSTREAM)
            await boundary.process_frame(vad_stop, FrameDirection.DOWNSTREAM)

        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(vad_stop, FrameDirection.DOWNSTREAM)
            # 600ms later, context_aggregator.user() broadcasts UserStoppedSpeakingFrame
            # downstream directly to llm (bypassing TurnBoundaryProcessor -> empty metadata).
            await self.llm.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

        self.assertIsNotNone(self.llm._last_input_turn)
        self.assertEqual(self.llm._last_input_turn.turn_id, 1)

        await self.llm._handle_msg_model_turn(_msg(audio=b"\x01\x00" * 240))
        await self.llm._handle_msg_turn_complete(_msg(turn_complete=True))

        with patch.object(FrameProcessor, "process_frame", new=AsyncMock()):
            for frame, direction in list(self.pushed):
                if isinstance(frame, (TTSAudioRawFrame, LLMFullResponseEndFrame)):
                    await timing.process_frame(frame, direction)

        self.assertEqual(tracker.current.status, "ok")

    async def test_gemini_vad_only_mode_attributes_and_closes_turns(self):
        tracker = TurnTracker("sess-gemini-attr", "gemini-live", vad_stop_padding_ms=None)
        timing = ServerAudioTimingProcessor()
        self.llm._turn_tracker = tracker
        self.llm._last_input_turn = tracker.current
        self.llm._live_output_turn = None

        # In vad_mode="gemini", context_aggregator.user() broadcasts UserStarted/StoppedSpeakingFrame
        # directly to llm without passing through TurnBoundaryProcessor first.
        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await self.llm.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

        self.assertIsNotNone(self.llm._last_input_turn)
        self.assertEqual(self.llm._last_input_turn.turn_id, 1)
        self.assertEqual(self.llm._live_output_turn.turn_id, 1)

        await self.llm._handle_msg_model_turn(_msg(audio=b"\x01\x00" * 240))
        await self.llm._handle_msg_turn_complete(_msg(turn_complete=True))

        with patch.object(FrameProcessor, "process_frame", new=AsyncMock()):
            for frame, direction in list(self.pushed):
                if isinstance(frame, (TTSAudioRawFrame, LLMFullResponseEndFrame)):
                    await timing.process_frame(frame, direction)

        self.assertEqual(tracker.current.status, "ok")


class TestSileroOnlyActivityEnd(_Harness):
    async def test_vad_stop_sends_activity_end_immediately_once(self):
        self.llm._vad_disabled = True
        self.llm._ready_for_realtime_input = True
        self.llm._session = SimpleNamespace(
            send_realtime_input=AsyncMock(),
            send_client_content=AsyncMock(),
        )

        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            self.assertEqual(self.llm._session.send_realtime_input.await_count, 1)

            await self.llm.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            self.assertEqual(self.llm._session.send_realtime_input.await_count, 2)
            self.assertFalse(self.llm._user_is_speaking)

            # Delayed UserStoppedSpeakingFrame from SpeechTimeoutUserTurnStopStrategy must not double-send
            await self.llm.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            self.assertEqual(self.llm._session.send_realtime_input.await_count, 2)
        await self.llm._handle_user_stopped_speaking(UserStoppedSpeakingFrame())
        self.assertEqual(self.llm._session.send_realtime_input.await_count, 2)


def _mp4_box(box_type: bytes, payload: bytes) -> bytes:
    import struct
    return struct.pack(">I4s", 8 + len(payload), box_type) + payload


def _build_iso_avatar_segment(frame_idx: int, *, active_audio: bool) -> bytes:
    """Build a valid ISO-BMFF moof+mdat pair for track 1 (video) and track 2 (CBR AAC audio)."""
    import struct
    v_tfdt = frame_idx * 512
    a_tfdt = frame_idx * 1024
    v_tfhd = _mp4_box(b"tfhd", struct.pack(">II", 0x020000, 1))
    v_tfdt_box = _mp4_box(b"tfdt", struct.pack(">IQ", 0x01000000, v_tfdt))
    v_moof = _mp4_box(b"moof", _mp4_box(b"traf", v_tfhd + v_tfdt_box))
    v_mdat = _mp4_box(b"mdat", b"\x11" * 256)

    a_tfhd = _mp4_box(b"tfhd", struct.pack(">II", 0x020000, 2))
    a_tfdt_box = _mp4_box(b"tfdt", struct.pack(">IQ", 0x01000000, a_tfdt))
    a_moof = _mp4_box(b"moof", _mp4_box(b"traf", a_tfhd + a_tfdt_box))
    if active_audio:
        # High-entropy speech AAC frame (>120 bytes after zlib level-1 compression)
        a_payload = bytes(((i * 73 + frame_idx * 19) ^ (i * i)) & 0xFF for i in range(683))
    else:
        # Vertex AI 3.8 Live Avatar CBR AAC digital-silence filler frame (<=100 bytes after zlib)
        a_payload = bytes.fromhex("01402280a37ff885") + (b"\x2d" * 665) + (b"\xb4" * 10)
    a_mdat = _mp4_box(b"mdat", a_payload)
    return v_moof + v_mdat + a_moof + a_mdat


class TestAvatarTurns(_Harness):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.llm._avatar_enabled = True

    async def test_video_only_turn_reports_ttft_and_speaking_state(self):
        await self.llm.start_ttfb_metrics()
        await asyncio.sleep(0.05)
        await self.llm._handle_msg_model_turn(_msg(video=b"\x00" * 16))
        await self.llm._handle_msg_model_turn(_msg(video=b"\x00" * 16))

        latencies = self.metrics("llm_latency")
        self.assertEqual(len(latencies), 1)
        self.assertGreaterEqual(latencies[0]["value"], 0.04)
        self.assertEqual(len(self.frames(BotStartedSpeakingFrame, FrameDirection.UPSTREAM)), 1)

        await self.llm._handle_msg_turn_complete(_msg(turn_complete=True))
        self.assertEqual(len(self.frames(BotStoppedSpeakingFrame, FrameDirection.UPSTREAM)), 1)

    async def test_idle_silent_avatar_segments_do_not_trigger_bot_output_or_ttft(self):
        idle = agent_live.UserIdleProcessor(callback=AsyncMock(return_value=True), timeout=30.0)
        self.llm.user_idle_processor = idle
        await self.llm.start_ttfb_metrics()
        await asyncio.sleep(0.04)

        # Pre-speech idle fMP4 segments carry CBR AAC silence filler frames: must not start bot output or report TTFT
        await self.llm._handle_msg_model_turn(_msg(video=_build_iso_avatar_segment(0, active_audio=False)))
        await self.llm._handle_msg_model_turn(_msg(video=_build_iso_avatar_segment(1, active_audio=False)))
        self.assertFalse(getattr(self.llm, "_mixin_bot_responding", False))
        self.assertFalse(getattr(self.llm, "_avatar_speaking", False))
        self.assertFalse(idle._bot_speaking)
        self.assertEqual(len(self.metrics("llm_latency")), 0)
        self.assertEqual(len(self.frames(BotStartedSpeakingFrame, FrameDirection.UPSTREAM)), 0)

        # Active speech fMP4 segment starts bot output and reports true TTFT
        await self.llm._handle_msg_model_turn(_msg(video=_build_iso_avatar_segment(2, active_audio=True)))
        self.assertTrue(self.llm._mixin_bot_responding)
        self.assertTrue(self.llm._avatar_speaking)
        self.assertTrue(idle._bot_speaking)
        self.assertEqual(len(self.metrics("llm_latency")), 1)
        self.assertEqual(len(self.frames(BotStartedSpeakingFrame, FrameDirection.UPSTREAM)), 1)

        # Post-turn_complete idle fMP4 segments must not re-open bot output
        await self.llm._handle_msg_turn_complete(_msg(turn_complete=True))
        await self.llm._handle_msg_model_turn(_msg(video=_build_iso_avatar_segment(3, active_audio=False)))
        self.assertFalse(self.llm._mixin_bot_responding)
        self.assertFalse(self.llm._avatar_speaking)
        self.assertFalse(idle._bot_speaking)
        self.assertEqual(len(self.frames(BotStartedSpeakingFrame, FrameDirection.UPSTREAM)), 1)

    async def test_post_speech_silent_avatar_segments_end_avatar_speaking_before_delayed_turn_complete(self):
        idle = agent_live.UserIdleProcessor(callback=AsyncMock(return_value=True), timeout=30.0)
        self.llm.user_idle_processor = idle

        await self.llm._handle_msg_model_turn(_msg(video=_build_iso_avatar_segment(10, active_audio=True)))
        await self.llm._handle_msg_model_turn(_msg(video=_build_iso_avatar_segment(11, active_audio=True)))
        self.assertTrue(self.llm._avatar_speaking)
        self.assertTrue(idle._bot_speaking)

        # Vertex AI finishes TTS audio and streams ~2s of silent AAC + phantom lip movement before turn_complete
        await self.llm._handle_msg_model_turn(_msg(video=_build_iso_avatar_segment(12, active_audio=False)))
        await self.llm._handle_msg_model_turn(_msg(video=_build_iso_avatar_segment(13, active_audio=False)))
        self.assertFalse(self.llm._avatar_speaking)
        self.assertFalse(idle._bot_speaking)
        self.assertEqual(len(self.frames(BotStoppedSpeakingFrame, FrameDirection.UPSTREAM)), 1)

        # Delayed turn_complete must not emit a duplicate BotStoppedSpeakingFrame
        await self.llm._handle_msg_turn_complete(_msg(turn_complete=True))
        self.assertEqual(len(self.frames(BotStoppedSpeakingFrame, FrameDirection.UPSTREAM)), 1)



class TestTtftFromSpeechEnd(_Harness):
    async def test_ttft_counts_from_vad_stop_even_when_turn_timeout_fires_late(self):
        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.2)
        await self.llm._handle_msg_output_transcription(_msg(transcript="Haan"))
        # SpeechTimeoutUserTurnStopStrategy fires 600 ms after the transcript, mid-reply.
        await self.llm.start_ttfb_metrics()
        await self.llm._handle_msg_model_turn(_msg(audio=b"\x01\x00" * 240))

        latencies = self.metrics("llm_latency")
        self.assertEqual(len(latencies), 1, "a late turn-timeout must not mint a second, fake TTFT")
        self.assertGreaterEqual(latencies[0]["value"], 0.18)

    async def test_mid_utterance_pause_is_cleared_when_user_resumes_speaking(self):
        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.20)
            # User resumes speaking after a 400ms pause
            await self.llm.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.05)
            await self.llm.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)
        await self.llm._handle_msg_output_transcription(_msg(transcript="Achha"))

        latencies = self.metrics("llm_latency")
        self.assertEqual(len(latencies), 1)
        self.assertLess(latencies[0]["value"], 0.15)

    async def test_fast_server_vad_reply_before_local_vad_stop_still_emits_ttft(self):
        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await self.llm._handle_msg_input_transcription(_msg(user_transcript="Hello."))
        await asyncio.sleep(0.05)
        # Server VAD responds before local Silero's 400ms VADUserStoppedSpeakingFrame arrives
        await self.llm._handle_msg_output_transcription(_msg(transcript="Hi there"))
        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

        latencies = self.metrics("llm_latency")
        self.assertEqual(len(latencies), 1)
        self.assertGreaterEqual(latencies[0]["value"], 0.04)

    async def test_create_single_response_overrides_stale_vad_anchor(self):
        self.llm._session = SimpleNamespace(
            send_client_content=AsyncMock(),
            send_realtime_input=AsyncMock(),
        )
        with patch.object(GeminiLiveLLMService, "process_frame", new=AsyncMock()):
            await self.llm.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.20)
        await self.llm._create_single_response([{"role": "user", "content": "ask me if I am still here"}])
        await asyncio.sleep(0.05)
        await self.llm._handle_msg_output_transcription(_msg(transcript="Are you still there?"))

        latencies = self.metrics("llm_latency")
        self.assertEqual(len(latencies), 1)
        self.assertLess(latencies[0]["value"], 0.15)


class TestUserIdleProcessorWithLocalVad(_Harness):
    async def test_vad_frames_reset_idle_and_audio_turn_suspends_timer(self):
        idle = agent_live.UserIdleProcessor(callback=AsyncMock(return_value=True), timeout=30.0)
        idle.retry_count = 2
        self.llm.user_idle_processor = idle

        with patch.object(FrameProcessor, "process_frame", new=AsyncMock()):
            await idle.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(idle.retry_count, 0)

        await self.llm._handle_msg_output_transcription(_msg(transcript="Speaking now"))
        self.assertTrue(idle._bot_speaking)

        await self.llm._handle_msg_turn_complete(_msg(turn_complete=True))
        self.assertFalse(idle._bot_speaking)


class TestLiveVadRuns(unittest.TestCase):
    def test_silero_modes_get_a_vad_processor(self):
        from pipecat.processors.audio.vad_processor import VADProcessor
        self.assertIsInstance(agent_live.build_live_vad_processor(True, "both"), VADProcessor)
        self.assertIsInstance(agent_live.build_live_vad_processor(True, "silero"), VADProcessor)
        self.assertIsNone(agent_live.build_live_vad_processor(True, "gemini"))


if __name__ == "__main__":
    unittest.main()
