"""Unit tests for ConsultativePhaseTracker & PhaseTransitionProcessor.

Runs natively with python3 -m unittest.
"""

import unittest
from unittest.mock import AsyncMock

from phase_engine import (
    PHASE_PROMPT_CARDS,
    ConsultativePhaseTracker,
    PhaseTransitionProcessor,
)
from pipecat.frames.frames import (
    TranscriptionFrame,
    FunctionCallResultFrame,
)
from pipecat.processors.frame_processor import FrameDirection


class MockSession:
    def __init__(self):
        self.send_client_content = AsyncMock()


class MockGeminiService:
    def __init__(self):
        self._session = MockSession()


class TestPhaseEngine(unittest.IsolatedAsyncioTestCase):

    async def test_initial_phase_state(self):
        service = MockGeminiService()
        tracker = ConsultativePhaseTracker(gemini_service=service)
        self.assertEqual(tracker.current_phase, 1)
        self.assertIn(1, PHASE_PROMPT_CARDS)
        self.assertIn(9, PHASE_PROMPT_CARDS)

    async def test_state_transition_and_client_content_call(self):
        service = MockGeminiService()
        tracker = ConsultativePhaseTracker(gemini_service=service, enable_client_content=True)

        # Transition to Phase 2
        await tracker.transition_to(2, trigger_reason="User gave consent")
        self.assertEqual(tracker.current_phase, 2)
        self.assertEqual(service._session.send_client_content.call_count, 1)

        # Verify content sent
        call_args = service._session.send_client_content.call_args[1]
        self.assertFalse(call_args["turn_complete"])
        self.assertEqual(len(call_args["turns"]), 1)
        self.assertIn("ACTIVE_PHASE_DIRECTIVE: Phase 2", call_args["turns"][0].parts[0].text)

    async def test_no_spurious_retransition(self):
        service = MockGeminiService()
        tracker = ConsultativePhaseTracker(gemini_service=service, enable_client_content=True)

        await tracker.transition_to(2, trigger_reason="First transition")
        self.assertEqual(service._session.send_client_content.call_count, 1)

        # Transitioning to the SAME phase should be a no-op
        await tracker.transition_to(2, trigger_reason="Duplicate transition")
        self.assertEqual(service._session.send_client_content.call_count, 1)

    async def test_invalid_phase_rejected(self):
        service = MockGeminiService()
        tracker = ConsultativePhaseTracker(gemini_service=service)

        await tracker.transition_to(99, trigger_reason="Invalid phase")
        self.assertEqual(tracker.current_phase, 1)
        self.assertEqual(service._session.send_client_content.call_count, 0)

    async def test_processor_transcription_consent_trigger(self):
        service = MockGeminiService()
        tracker = ConsultativePhaseTracker(gemini_service=service)
        processor = PhaseTransitionProcessor(tracker=tracker)

        frame = TranscriptionFrame(text="हाँ, बताइए", user_id="user", timestamp=123.45)
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        self.assertEqual(tracker.current_phase, 2)

    async def test_processor_transcription_rbi_trigger(self):
        service = MockGeminiService()
        tracker = ConsultativePhaseTracker(gemini_service=service)
        processor = PhaseTransitionProcessor(tracker=tracker)

        frame = TranscriptionFrame(text="Kya ye platform RBI approved hai?", user_id="user", timestamp=123.45)
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        self.assertEqual(tracker.current_phase, 4)

    async def test_processor_transcription_kyc_trigger(self):
        service = MockGeminiService()
        tracker = ConsultativePhaseTracker(gemini_service=service)
        processor = PhaseTransitionProcessor(tracker=tracker)

        frame = TranscriptionFrame(text="KYC ke liye kya documents chahiye?", user_id="user", timestamp=123.45)
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        self.assertEqual(tracker.current_phase, 8)

    async def test_processor_function_call_returns_trigger(self):
        service = MockGeminiService()
        tracker = ConsultativePhaseTracker(gemini_service=service)
        processor = PhaseTransitionProcessor(tracker=tracker)

        frame = FunctionCallResultFrame(
            function_name="calculate_stl_returns",
            tool_call_id="call_123",
            arguments={"amount": 100000, "tenure_months": 6},
            result={"net_profit": 9000},
        )
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        self.assertEqual(tracker.current_phase, 7)

    async def test_processor_function_call_kyc_trigger(self):
        service = MockGeminiService()
        tracker = ConsultativePhaseTracker(gemini_service=service)
        processor = PhaseTransitionProcessor(tracker=tracker)

        frame = FunctionCallResultFrame(
            function_name="get_kyc_guidance",
            tool_call_id="call_456",
            arguments={},
            result={"steps": ["PAN", "Aadhaar", "Bank"]},
        )
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        self.assertEqual(tracker.current_phase, 8)


if __name__ == "__main__":
    unittest.main()
