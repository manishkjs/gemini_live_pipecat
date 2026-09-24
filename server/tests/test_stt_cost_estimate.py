"""Transcribe Live returns no usage_metadata (probed 2026-09-24), so the STT stage
was permanently 'pending'. Price it from streamed audio instead, and say it's an estimate."""
import unittest
from decimal import Decimal

from cascade_pricing import CascadeCostLedger, quote


class TestTranscribeLiveEstimate(unittest.TestCase):
    def record(self, **usage):
        return dict(stage="stt", model="gemini-3.5-transcribe-live", provider="gemini",
                    complete=True, estimated=True, usage=usage)

    def test_audio_seconds_at_25_tokens_per_second_plus_transcript_text(self):
        # 60s audio -> 1500 tok * $3.50/M = 0.00525 ; 300 chars -> 100 tok * $21/M = 0.0021
        value, reason, _ = quote(self.record(audio_seconds=60.0, transcript_chars=300))
        self.assertIsNone(reason)
        self.assertEqual(value, Decimal("0.00735"))

    def test_zero_audio_is_zero_not_pending(self):
        value, reason, _ = quote(self.record(audio_seconds=0.0, transcript_chars=0))
        self.assertEqual((value, reason), (Decimal(0), None))

    def test_invalid_audio_seconds_is_not_billed(self):
        for bad in (-1, float("nan"), True, "10"):
            value, reason, _ = quote(self.record(audio_seconds=bad, transcript_chars=0))
            self.assertIsNone(value, bad)
            self.assertTrue(reason)

    def test_snapshot_marks_stage_estimated_and_complete(self):
        ledger = CascadeCostLedger("call")
        key = ledger.begin("stt", "gemini-3.5-transcribe-live", "gemini", "us-central1")
        ledger.update(key, complete=True, estimated=True,
                      usage={"audio_seconds": 60.0, "transcript_chars": 300})
        stt = ledger.snapshot()["stages"][0]
        self.assertEqual(stt["known_usd"], "0.00735")
        self.assertTrue(stt["complete"])
        self.assertTrue(stt["estimated"])
        self.assertEqual(stt["issues"], [])


if __name__ == "__main__":
    unittest.main()
