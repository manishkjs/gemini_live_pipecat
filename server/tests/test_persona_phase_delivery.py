import unittest
from unittest.mock import AsyncMock
from diagnostic_buffer import bind_session
from persona_registry import AnanyaMFAdvisorArchitecture, KavyaGlassBuddyArchitecture


class TestPhaseDelivery(unittest.IsolatedAsyncioTestCase):
    async def test_both_personas_retry_failed_delivery(self):
        for factory, target in [(AnanyaMFAdvisorArchitecture, "SOP_02_SCHEME_DETAILS"),
                                (KavyaGlassBuddyArchitecture, "SOP_02_VISION_CAPTURE")]:
            bind_session("phase-session")
            arch = factory()
            arch._llm = AsyncMock()
            arch._llm.inject_directive.side_effect = [False, RuntimeError("offline"), True]
            arch._broadcast = AsyncMock()
            initial = arch.engine.active_phase
            for revision in (1, 2):
                result = await arch._switch_phase({"phase_id": target})
                assert result["status"] == "delivery_failed"
                assert result["phase_id"] == arch.engine.active_phase == initial
                event = arch._broadcast.call_args.args[0]
                assert event["phase_id"] == initial and event["card_pushed"] is False
                assert event["revision"] == revision and event["session_id"] == "phase-session"
            assert (await arch._switch_phase({"phase_id": target}))["status"] == "success"
            assert arch.engine.active_phase == target
            assert (await arch._switch_phase({"phase_id": target}))["delivery_status"] == "already_sent"
            assert arch._llm.inject_directive.await_count == 3
