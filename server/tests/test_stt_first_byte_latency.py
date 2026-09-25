"""STT latency = end of user speech -> first transcript byte from Transcribe Live.

The VAD only *decides* speech ended after `stop_secs` of silence, so the true end of
speech is `decided_at - stop_secs`. Transcribe Live streams while the user talks, so
the first byte may even arrive inside that silence window, before the VAD decides.
"""
import unittest, unittest.mock

from stt_latency import FirstByteAfterSpeechEnd


class TestFirstByteAfterSpeechEnd(unittest.TestCase):
    def setUp(self):
        self.clock = FirstByteAfterSpeechEnd()
        self.clock.speech_started(100.0)

    def test_byte_after_vad_decision_measures_from_true_speech_end(self):
        self.clock.transcript_arrived(101.0)          # mid-speech interim: ignored
        self.assertIsNone(self.clock.speech_stopped(decided_at=103.4, stop_secs=0.4))
        latency = self.clock.transcript_arrived(103.7)
        self.assertAlmostEqual(latency, 0.7)          # 103.7 - (103.4 - 0.4)

    def test_byte_inside_silence_window_is_reported_when_vad_decides(self):
        self.clock.transcript_arrived(102.9)          # before speech end: ignored
        self.clock.transcript_arrived(103.25)         # 0.25s after true end (103.0)
        latency = self.clock.speech_stopped(decided_at=103.4, stop_secs=0.4)
        self.assertAlmostEqual(latency, 0.25)

    def test_reported_once_per_utterance(self):
        self.clock.speech_stopped(decided_at=103.4, stop_secs=0.4)
        self.assertIsNotNone(self.clock.transcript_arrived(103.5))
        self.assertIsNone(self.clock.transcript_arrived(103.9))

    def test_new_utterance_resets(self):
        self.clock.speech_stopped(decided_at=103.4, stop_secs=0.4)
        self.clock.transcript_arrived(103.5)
        self.clock.speech_started(104.0)
        self.clock.speech_stopped(decided_at=106.4, stop_secs=0.4)
        self.assertAlmostEqual(self.clock.transcript_arrived(106.3), 0.3)

    def test_no_speech_end_means_no_latency(self):
        self.assertIsNone(self.clock.transcript_arrived(101.0))

    def test_implausible_values_are_dropped(self):
        self.clock.speech_stopped(decided_at=103.4, stop_secs=0.4)
        self.assertIsNone(self.clock.transcript_arrived(125.0))

    def test_final_latency_is_measured_from_true_speech_end(self):
        self.clock.speech_stopped(decided_at=103.4, stop_secs=0.4)
        self.assertAlmostEqual(self.clock.final_latency(104.2), 1.2)
        self.assertIsNone(FirstByteAfterSpeechEnd().final_latency(104.2))


class TestTurnOriginPreservesSttLatency(unittest.IsolatedAsyncioTestCase):
    async def test_emitted_stt_latency_survives_turn_origin_mixin(self):
        from pipecat.frames.frames import VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
        from pipecat.processors.frame_processor import FrameDirection
        from processors.turn_telemetry import ORIGIN_KEY
        from turn_telemetry import TurnTracker
        import agent

        sent = []
        svc = agent.CustomGeminiTranscribeLiveService.__new__(agent.CustomGeminiTranscribeLiveService)
        svc._latency_clock = FirstByteAfterSpeechEnd()
        svc._vad_stop_secs = 0.4
        svc._turn_tracker = TurnTracker("s1", "tts-llm-stt", vad_stop_padding_ms=400)
        svc._audio_queue = None
        svc._audio_passthrough = False
        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            sent.append(frame)
        with unittest.mock.patch.object(agent.STTService, "process_frame", new=unittest.mock.AsyncMock()),                 unittest.mock.patch.object(agent.STTService, "push_frame", side_effect=capture):
            svc._turn_tracker.start()
            start = VADUserStartedSpeakingFrame()
            start.metadata[ORIGIN_KEY] = svc._turn_tracker.current
            await svc.process_frame(start, FrameDirection.DOWNSTREAM)

            # Case 1: byte arrives after VAD stop (inside receive_transcripts task, where ORIGIN is None).
            turn = svc._turn_tracker.stop(vad=True, now=100.4)
            stop = VADUserStoppedSpeakingFrame(stop_secs=0.4, timestamp=100.4)
            stop.metadata[ORIGIN_KEY] = turn
            await svc.process_frame(stop, FrameDirection.DOWNSTREAM)
            await svc._emit_stt_latency(svc._latency_clock.transcript_arrived(100.65))

        payload = sent[-1].message["data"]["payload"]
        self.assertEqual(payload["type"], "stt_latency")
        self.assertAlmostEqual(payload["value"], 0.65)
        self.assertEqual(payload["turn_id"], turn.turn_id)


if __name__ == "__main__":
    unittest.main()
