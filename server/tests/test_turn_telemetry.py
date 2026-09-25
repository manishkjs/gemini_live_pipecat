"""Correlation, lifecycle and retention tests without provider connections."""
import unittest
import asyncio
from diagnostic_buffer import (
    DIAGNOSTIC_LOG_BUFFER, TURN_LATENCY_RECORDS, append_raw_log_entry,
    bind_session, clear_diagnostic_logs, get_latency_summary,
    get_recent_diagnostic_logs, record_metric,
)
from turn_telemetry import TurnTracker


class TestTurnTelemetry(unittest.TestCase):
    def setUp(self):
        DIAGNOSTIC_LOG_BUFFER.clear()
        TURN_LATENCY_RECORDS.clear()

    def test_provider_usage_snapshots_replace_and_remain_scoped(self):
        from diagnostic_buffer import record_provider_usage
        for session, response, n in (("A", "r1", 10), ("A", "r1", 20), ("A", "r2", 5), ("B", "r1", 90)):
            record_provider_usage({"session_id": session, "response_id": response,
                "usage": {"prompt_token_count": n, "response_token_count": 2, "total_token_count": n + 2}})
        usage = get_latency_summary("A")["provider_usage"]
        self.assertEqual(usage["count"], 2)
        self.assertEqual(usage["total_token_count"], 29)
        clear_diagnostic_logs("A")
        self.assertEqual(get_latency_summary("A")["provider_usage"]["count"], 0)
        self.assertEqual(get_latency_summary("B")["provider_usage"]["count"], 1)

    def test_missing_stages_never_create_an_end_to_end_total(self):
        record_metric("A", 1, "tts-llm-stt", "llm", 15)
        record_metric("A", 2, "tts-llm-stt", "tts", 200)
        summary = get_latency_summary("A")
        self.assertEqual(summary["llm"]["p50"], 15)
        self.assertEqual(summary["total_turnaround"]["count"], 0)
        self.assertEqual(summary["vad_stop_to_first_server_audio"]["count"], 0)

    def test_logs_never_manufacture_metrics_or_badge_values(self):
        bind_session("A", "gemini-live")
        for message in ("TTSService TTFB: 15 ms", "TTSService TTFB: 15ms", "worker 7 TTFB: 0.25 s"):
            append_raw_log_entry(message)
        self.assertFalse(TURN_LATENCY_RECORDS)
        self.assertTrue(all("ttfb_ms" not in x for x in get_recent_diagnostic_logs(session_id="A")))

    def test_rapid_turns_and_repeated_tts_requests_survive(self):
        for turn_id, value in ((1, 12), (1, 18), (2, 15)):
            record_metric("A", turn_id, "tts-llm-stt", "tts", value)
        self.assertEqual(get_latency_summary("A")["tts"]["count"], 3)

    def test_scope_required_for_reads_and_clears_and_unscoped_is_private(self):
        for call in (get_latency_summary, clear_diagnostic_logs):
            with self.assertRaises(ValueError):
                call()
        with self.assertRaises(ValueError):
            get_recent_diagnostic_logs()
        for session in (None, "A", "B"):
            bind_session(session)
            append_raw_log_entry(str(session))
        self.assertEqual(len(get_recent_diagnostic_logs(session_id="A")), 1)
        clear_diagnostic_logs("A")
        self.assertEqual(len(get_recent_diagnostic_logs(session_id="B")), 1)

    def test_process_wide_capacity_and_engine_validation(self):
        for i in range(5000):
            record_metric(str(i % 50), i, "gemini-live", "live_ttfb", 15)
        self.assertEqual(len(TURN_LATENCY_RECORDS), 2000)
        self.assertEqual(TURN_LATENCY_RECORDS[0]["turn_id"], 3000)
        for bot_type in (None, "unknown"):
            with self.assertRaises(ValueError):
                record_metric("A", 1, bot_type, "llm", 15)
        for value in (-1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                record_metric("A", 1, "gemini-live", "live_ttfb", value)

    def test_measured_and_estimated_server_intervals_are_distinct(self):
        tracker = TurnTracker("A", "tts-llm-stt", vad_stop_padding_ms=400)
        tracker.start()
        turn = tracker.stop(vad=True, now=10)
        self.assertIs(tracker.stop(), turn)  # VAD + user stop do not mint two turns.
        turn.audio(now=10.25)
        turn.audio(now=11)
        turn.finish("ok")
        record = TURN_LATENCY_RECORDS[-1]
        self.assertEqual(record["vad_stop_to_first_server_audio_ms"], 250)
        self.assertEqual(record["estimated_speech_end_to_first_server_audio_ms"], 650)
        self.assertNotIn("turnaround_ms", record)
        self.assertNotIn("perceived_turnaround_ms", record)

    def test_late_audio_from_interrupted_turn_cannot_populate_next_turn(self):
        tracker = TurnTracker("A", "gemini-live")
        tracker.start()
        first = tracker.stop(vad=True, now=10)
        tracker.start()
        second = tracker.stop(vad=True, now=11)
        first.audio(now=11.1)
        first.finish("ok")
        self.assertEqual(first.status, "interrupted")
        self.assertIsNone(first.first_audio)
        self.assertIsNone(second.first_audio)
        second.audio(now=11.2)
        second.finish("ok")
        old = [r for r in TURN_LATENCY_RECORDS if r["turn_id"] == first.turn_id]
        self.assertEqual(len(old), 1)
        self.assertNotIn("vad_stop_to_first_server_audio_ms", old[0])

    def test_disconnect_closes_once_and_missing_vad_stays_unavailable(self):
        tracker = TurnTracker("A", "tts-llm-stt")
        tracker.start()
        turn = tracker.stop(now=10)
        turn.audio(now=11)
        tracker.close()
        tracker.close()
        turn.finish("ok")
        records = [r for r in TURN_LATENCY_RECORDS if r["turn_id"] == turn.turn_id]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "abandoned")
        self.assertNotIn("vad_stop_to_first_server_audio_ms", records[0])


class TestFrameOrigins(unittest.IsolatedAsyncioTestCase):
    async def test_delayed_semantic_events_do_not_duplicate_local_vad_turn(self):
        from unittest.mock import AsyncMock, patch
        from pipecat.frames.frames import (
            VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
            UserStartedSpeakingFrame, UserStoppedSpeakingFrame,
        )
        from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
        from processors.turn_telemetry import TurnBoundaryProcessor
        tracker = TurnTracker("boundary", "tts-llm-stt", vad_stop_padding_ms=400)
        boundary = TurnBoundaryProcessor(tracker)
        boundary.push_frame = AsyncMock()
        with patch.object(FrameProcessor, "process_frame", new=AsyncMock()):
            for frame in (VADUserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(),
                          UserStartedSpeakingFrame(), UserStoppedSpeakingFrame()):
                await boundary.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(tracker.counter, 1)
        self.assertIsNone(tracker.current.status)
        self.assertIsNotNone(tracker.current.vad_stop)

    async def test_actual_mixin_preserves_origin_across_async_task_and_audio_queue(self):
        from pipecat.frames.frames import LLMContextFrame, TTSAudioRawFrame
        from pipecat.processors.frame_processor import FrameDirection
        from processors.turn_telemetry import TurnOriginMixin, ORIGIN_KEY

        released = asyncio.Event()
        class Base:
            async def process_frame(self, frame, direction):
                async def delayed():
                    await released.wait()
                    audio = TTSAudioRawFrame(b"\0\0", 24000, 1)
                    await self.append_to_audio_context("old-response", audio)
                self.task = asyncio.create_task(delayed())
            async def append_to_audio_context(self, context_id, frame):
                self.queued = frame
            async def push_frame(self, frame, direction):
                self.emitted = frame
        class Service(TurnOriginMixin, Base):
            pass

        tracker = TurnTracker("frames", "tts-llm-stt")
        tracker.start()
        first = tracker.stop(vad=True, now=10)
        service = Service()
        service._turn_tracker = tracker
        request = LLMContextFrame(object())
        request.metadata[ORIGIN_KEY] = first
        await service.process_frame(request, FrameDirection.DOWNSTREAM)
        tracker.start()
        second = tracker.stop(vad=True, now=11)
        released.set()
        await service.task
        self.assertIs(service.queued.metadata[ORIGIN_KEY], first)
        await service.push_frame(service.queued, FrameDirection.DOWNSTREAM)
        self.assertIs(service.emitted.metadata[ORIGIN_KEY], first)
        first.audio(now=11.1)
        self.assertIsNone(second.first_audio)
        self.assertIsNone(first.first_audio)

    async def test_unattributed_upstream_context_cannot_capture_current_turn(self):
        from pipecat.frames.frames import LLMContextFrame, LLMTextFrame
        from pipecat.processors.frame_processor import FrameDirection
        from processors.turn_telemetry import TurnOriginMixin, ORIGIN_KEY
        class Base:
            async def process_frame(self, frame, direction):
                await self.push_frame(LLMTextFrame("tool follow-up"), direction)
            async def push_frame(self, frame, direction):
                self.emitted = frame
        class Service(TurnOriginMixin, Base):
            pass
        service = Service()
        service._turn_tracker = TurnTracker("frames", "tts-llm-stt")
        for direction in (FrameDirection.UPSTREAM, FrameDirection.DOWNSTREAM):
            await service.process_frame(LLMContextFrame(object()), direction)
            self.assertIsNone(service.emitted.metadata[ORIGIN_KEY])

    async def test_live_reserves_old_input_until_provider_acknowledges_interruption(self):
        from pipecat.frames.frames import VADUserStoppedSpeakingFrame, TTSAudioRawFrame
        from pipecat.processors.frame_processor import FrameDirection
        from processors.turn_telemetry import TurnOriginMixin, ORIGIN_KEY
        class Base:
            async def process_frame(self, frame, direction): pass
            async def push_frame(self, frame, direction): self.emitted = frame
        class Service(TurnOriginMixin, Base):
            _live_telemetry = True
        tracker = TurnTracker("native", "gemini-live", vad_stop_padding_ms=400)
        service = Service()
        tracker.start()
        first = tracker.stop(vad=True)
        first_stop = VADUserStoppedSpeakingFrame()
        first_stop.metadata[ORIGIN_KEY] = first
        await service.process_frame(first_stop, FrameDirection.DOWNSTREAM)
        tracker.start()
        second = tracker.stop(vad=True)
        second_stop = VADUserStoppedSpeakingFrame()
        second_stop.metadata[ORIGIN_KEY] = second
        await service.process_frame(second_stop, FrameDirection.DOWNSTREAM)
        await service.push_frame(TTSAudioRawFrame(b"00", 24000, 1))
        self.assertIs(service.emitted.metadata[ORIGIN_KEY], first)
        self.assertEqual(first.status, "interrupted")
        self.assertIsNone(second.first_audio)

    async def test_real_output_boundary_records_first_audio_and_closes_once(self):
        from unittest.mock import AsyncMock, patch
        from pipecat.frames.frames import LLMFullResponseEndFrame, TTSAudioRawFrame
        from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
        from processors.turn_telemetry import ServerAudioTimingProcessor, ORIGIN_KEY
        tracker = TurnTracker("output", "tts-llm-stt", vad_stop_padding_ms=400)
        tracker.start()
        turn = tracker.stop(vad=True)
        processor = ServerAudioTimingProcessor()
        processor.push_frame = AsyncMock()
        with patch.object(FrameProcessor, "process_frame", new=AsyncMock()):
            for frame in (LLMFullResponseEndFrame(), TTSAudioRawFrame(b"00", 24000, 1), LLMFullResponseEndFrame(), LLMFullResponseEndFrame()):
                frame.metadata[ORIGIN_KEY] = turn
                await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        records = [r for r in TURN_LATENCY_RECORDS if r["session_id"] == "output" and r["turn_id"] == turn.turn_id]
        self.assertEqual(len(records), 1)
        self.assertIn("vad_stop_to_first_server_audio_ms", records[0])
