"""Regression tests for ui-changes-sep architectural and implementation audit fixes."""
import unittest
from unittest.mock import AsyncMock
from types import SimpleNamespace
from decimal import Decimal

import session_access
import voice_profiles
from agent_live import estimate_tokens
from processors.repeat_on_interruption import is_conversational_filler
from persona_tools.supercar_phases import CallSlots
from turn_telemetry import TurnTracker
from diagnostic_buffer import TURN_LATENCY_RECORDS, DIAGNOSTIC_LOG_BUFFER, record_provider_usage
from cascade_pricing import quote


class TestAuditRegressions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        TURN_LATENCY_RECORDS.clear()
        DIAGNOSTIC_LOG_BUFFER.clear()
        voice_profiles.clear()

    def test_filler_detection_rejects_stop_and_negation_commands(self):
        for cmd in ("no", "stop", "wait", "नहीं", "रुको", "मत", "nahi", "ruko", "600048"):
            self.assertFalse(is_conversational_filler(cmd), f"Should not treat '{cmd}' as filler")
        for filler in ("uh huh", "okay", "हाँ", "अच्छा", "आप बताइए"):
            self.assertTrue(is_conversational_filler(filler), f"Should treat '{filler}' as filler")

    def test_multilingual_token_estimation_covers_non_devanagari_scripts(self):
        tamil = "வணக்கம் எப்படி இருக்கிறீர்கள்"
        telugu = "నమస్కారం ఎలా ఉన్నారు"
        hindi = "नमस्ते आप कैसे हैं"
        self.assertGreater(estimate_tokens(tamil), len(tamil) // 3)
        self.assertGreater(estimate_tokens(telugu), len(telugu) // 3)
        non_ascii = sum(1 for c in hindi if ord(c) > 127)
        self.assertEqual(estimate_tokens(hindi), round(non_ascii / 1.8 + (len(hindi) - non_ascii) / 3.8))

    def test_turn_telemetry_records_late_stage_metrics_after_finish(self):
        tracker = TurnTracker("sess-audit", "tts-llm-stt")
        tracker.start()
        turn = tracker.stop(vad=True, now=10.0)
        turn.audio(now=10.2)
        turn.finish("ok")
        # Late TTS metric arriving after LLMFullResponseEndFrame / turn.finish("ok")
        turn.metric("tts", 0.185)
        tts_records = [r for r in TURN_LATENCY_RECORDS if r["stage"] == "tts" and r["turn_id"] == turn.turn_id]
        self.assertEqual(len(tts_records), 1)
        self.assertAlmostEqual(tts_records[0]["value_ms"], 185.0)

    def test_call_slots_invalidation_cascade_on_reschedule(self):
        slots = CallSlots()
        slots.propose(pincode="110037", visit_date="Tomorrow", visit_time="15:30")
        slots.set_tool(booking_status="confirmed", booking_ref="LAMBO-999")
        self.assertEqual(slots.get("booking_status"), "confirmed")
        # Modifying an already-set visit_time must invalidate the confirmed booking
        slots.propose(visit_time="16:00")
        self.assertEqual(slots.get("booking_status"), "not_started")
        self.assertIsNone(slots.get("booking_ref"))

    def test_session_access_set_instructions_enforces_token_when_supplied(self):
        sid, token, _ = session_access.issue()
        with self.assertRaises(ValueError):
            session_access.set_instructions(sid, "malicious prompt", token="forged_token_123456789012345678901234")
        session_access.set_instructions(sid, "valid prompt", token=token)
        self.assertEqual(session_access.take_instructions(sid), "valid prompt")

    def test_voice_profiles_enforces_max_capacity(self):
        orig_max = voice_profiles.MAX_PROFILES
        try:
            voice_profiles.MAX_PROFILES = 5
            ids = [voice_profiles.register(f"key-{i}") for i in range(8)]
            self.assertEqual(voice_profiles.active_count(), 5)
            # Oldest 3 should be evicted
            self.assertIsNone(voice_profiles.consume(ids[0]))
            self.assertEqual(voice_profiles.consume(ids[-1]), "key-7")
        finally:
            voice_profiles.MAX_PROFILES = orig_max

    def test_diagnostic_buffer_retains_modality_details_for_cascade_pricing(self):
        record_provider_usage({
            "session_id": "sess-cascade",
            "response_id": "resp-1",
            "usage": {
                "prompt_token_count": 1000,
                "response_token_count": 200,
                "total_token_count": 1200,
                "prompt_tokens_details": [{"modality": "TEXT", "token_count": 600}, {"modality": "AUDIO", "token_count": 400}],
                "cache_tokens_details": [{"modality": "TEXT", "token_count": 200}, {"modality": "AUDIO", "token_count": 200}],
                "cached_content_token_count": 400,
            }
        })
        stored = DIAGNOSTIC_LOG_BUFFER[-1]["usage"]
        self.assertIn("prompt_tokens_details", stored)
        val, issue, _ = quote({
            "stage": "llm",
            "model": "gemini-2.5-flash",
            "provider": "vertex",
            "region": "global",
            "complete": True,
            "input_mode": "audio",
            "usage": stored,
        })
        self.assertIsNone(issue)
        self.assertIsNotNone(val)
