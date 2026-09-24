"""STT latency = end of user speech -> first transcript byte from Transcribe Live.

The VAD only *decides* speech ended after `stop_secs` of silence, so the true end of
speech is `decided_at - stop_secs`. Transcribe Live streams while the user talks, so
the first byte may even arrive inside that silence window, before the VAD decides.
"""
import unittest

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


if __name__ == "__main__":
    unittest.main()
