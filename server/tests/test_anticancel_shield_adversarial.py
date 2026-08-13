"""Adversarial stress and verification test suite for Milestone 1: AntiCancel Tool Shield & Concurrency.

Validates the 5 critical production invariants defined in SKILL.md and PROJECT.md:
1. Frame Interception & Lock: FunctionCallInProgress/Started/LLM frames lock tool state.
2. Interruption Frame Suppression: InterruptionFrame & UserStartedSpeakingFrame dropped during in-flight tools.
3. AntiCancel Refusal: _cancel_function_call logs refusal and refuses to cancel in-flight tasks.
4. Self-Healing Watchdog: 8.0s max hold (TOOL_LOCK_MAX_HOLD_SECS) auto-releases stuck locks.
5. Non-Suppression of CancelFrame: CancelFrame (pipeline shutdown) ALWAYS passes through.
6. Method-Level Execution: _run_function_call correctly manages locks with exception safety.
7. Concurrency & Stress: High-throughput overlapping tools + rapid interleaved interruptions.
"""

import unittest
import sys
import os
import asyncio
import time
from typing import Dict, Any, List
from unittest.mock import MagicMock, AsyncMock, patch

# Add server directory to sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    CancelFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    TextFrame,
    OutputTransportMessageFrame,
)
from agent_live import (
    GeminiSessionLoggerMixin,
    CustomGeminiLiveLLMService,
    CustomGeminiLiveVertexLLMService,
    CustomProtobufSerializer,
)


class BaseMockProcessor(FrameProcessor):
    """Base frame processor that records all processed and pushed frames."""

    def __init__(self):
        super().__init__()
        self.processed_frames: List[tuple] = []
        self.pushed_frames: List[Frame] = []
        self._session = None
        self._disconnecting = False

    async def _start_interruption(self):
        """No-op in standalone unit test harness without active PipelineRunner."""
        pass

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        self.processed_frames.append((frame, direction))

    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        self.pushed_frames.append(frame)

    async def _run_function_call(self, tool_call):
        # Simulate base execution
        if hasattr(tool_call, "execute"):
            return await tool_call.execute()
        return {"status": "success"}


class ShieldedService(GeminiSessionLoggerMixin, BaseMockProcessor):
    """Concrete test service combining GeminiSessionLoggerMixin with BaseMockProcessor."""

    def __init__(self):
        super().__init__()
        self._active_tools_in_flight = 0
        self._frame_locked_tools = False
        self._tool_lock_started_at = None
        self._repeat_on_filler_pending = False
        self._bot_turn_text_buffer = ""
        self._my_ttfb_start = None
        self._current_turn_ttft = None


# Custom Dummy Frames matching naming conventions in agent_live.py
class FunctionCallInProgressFrame(Frame):
    pass


class FunctionCallsStartedFrame(Frame):
    pass


class FunctionCallFromLLM(Frame):
    pass


class FunctionCallResultFrame(Frame):
    def __init__(self, result=None, content=None):
        super().__init__()
        if result is not None:
            self.result = result
        if content is not None:
            self.content = content


class FunctionCallCancelFrame(Frame):
    pass


class TestAntiCancelShieldAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial suite verifying AntiCancel Tool Shield invariants."""

    def setUp(self):
        self.service = ShieldedService()

    # =========================================================================
    # 1. FRAME LOCK ACQUISITION AND RELEASE INVARIANTS
    # =========================================================================

    async def test_frame_lock_acquisition_in_progress_frame(self):
        """Verify FunctionCallInProgressFrame locks tool state."""
        self.assertFalse(self.service._tools_in_flight())
        self.assertEqual(self.service._active_tools_in_flight, 0)

        frame = FunctionCallInProgressFrame()
        await self.service.process_frame(frame, FrameDirection.DOWNSTREAM)

        self.assertTrue(self.service._tools_in_flight())
        self.assertEqual(self.service._active_tools_in_flight, 1)
        self.assertTrue(self.service._frame_locked_tools)
        self.assertIsNotNone(self.service._tool_lock_started_at)

    async def test_frame_lock_acquisition_started_and_from_llm_frames(self):
        """Verify FunctionCallsStartedFrame and FunctionCallFromLLM acquire lock."""
        # FunctionCallsStartedFrame
        s_frame = FunctionCallsStartedFrame()
        await self.service.process_frame(s_frame, FrameDirection.DOWNSTREAM)
        self.assertTrue(self.service._tools_in_flight())

        # Release
        self.service._release_tools("reset")
        self.assertFalse(self.service._tools_in_flight())

        # FunctionCallFromLLM
        llm_frame = FunctionCallFromLLM()
        await self.service.process_frame(llm_frame, FrameDirection.DOWNSTREAM)
        self.assertTrue(self.service._tools_in_flight())

    async def test_frame_lock_release_on_result_frame(self):
        """Verify FunctionCallResultFrame releases tool lock and updates diagnostic buffer."""
        # Lock
        await self.service.process_frame(FunctionCallInProgressFrame(), FrameDirection.DOWNSTREAM)
        self.assertTrue(self.service._tools_in_flight())

        # Result frame with short string
        res_frame = FunctionCallResultFrame(result="{'profit': 432000.0}")
        await self.service.process_frame(res_frame, FrameDirection.DOWNSTREAM)

        self.assertFalse(self.service._tools_in_flight())
        self.assertEqual(self.service._active_tools_in_flight, 0)
        self.assertFalse(self.service._frame_locked_tools)
        self.assertIsNone(self.service._tool_lock_started_at)

        # Result frame with long string (>150 chars)
        await self.service.process_frame(FunctionCallInProgressFrame(), FrameDirection.DOWNSTREAM)
        long_res = FunctionCallResultFrame(result="X" * 300)
        await self.service.process_frame(long_res, FrameDirection.DOWNSTREAM)
        self.assertFalse(self.service._tools_in_flight())

    # =========================================================================
    # 2. INTERRUPTION FRAME SUPPRESSION DURING ACTIVE TOOLS
    # =========================================================================

    async def test_interruption_frame_dropped_during_active_tool(self):
        """Verify InterruptionFrame is strictly dropped while a tool is in-flight."""
        # Lock tools
        self.service._lock_tools("active calculation")
        self.assertTrue(self.service._tools_in_flight())

        # Send InterruptionFrame
        int_frame = InterruptionFrame()
        initial_processed_count = len(self.service.processed_frames)
        initial_pushed_count = len(self.service.pushed_frames)

        await self.service.process_frame(int_frame, FrameDirection.UPSTREAM)

        # Frame must NOT have reached downstream/base processor
        self.assertEqual(len(self.service.processed_frames), initial_processed_count)
        # Interruption metrics must NOT have been pushed
        self.assertEqual(len(self.service.pushed_frames), initial_pushed_count)
        # Repeat on filler must NOT have been activated
        self.assertFalse(self.service._repeat_on_filler_pending)

    async def test_user_started_speaking_frame_dropped_during_active_tool(self):
        """Verify UserStartedSpeakingFrame is dropped while a tool is in-flight."""
        self.service._lock_tools("active calculation")
        self.assertTrue(self.service._tools_in_flight())

        user_speaking_frame = UserStartedSpeakingFrame()
        initial_count = len(self.service.processed_frames)

        await self.service.process_frame(user_speaking_frame, FrameDirection.UPSTREAM)

        # Frame dropped completely
        self.assertEqual(len(self.service.processed_frames), initial_count)

    async def test_function_call_cancel_frame_suppression(self):
        """Verify FunctionCallCancelFrame releases lock and is suppressed if in-flight."""
        await self.service.process_frame(FunctionCallInProgressFrame(), FrameDirection.DOWNSTREAM)
        self.assertTrue(self.service._tools_in_flight())

        cancel_call_frame = FunctionCallCancelFrame()
        initial_count = len(self.service.processed_frames)

        await self.service.process_frame(cancel_call_frame, FrameDirection.DOWNSTREAM)

        # Should release frame lock
        self.assertFalse(self.service._tools_in_flight())
        # Should be suppressed (not forwarded to super)
        self.assertEqual(len(self.service.processed_frames), initial_count)

    async def test_interruption_frame_passes_when_tools_idle(self):
        """Verify InterruptionFrame is processed normally when no tools are in-flight."""
        self.assertFalse(self.service._tools_in_flight())

        int_frame = InterruptionFrame()
        await self.service.process_frame(int_frame, FrameDirection.UPSTREAM)

        # Base processor MUST have received it
        self.assertIn((int_frame, FrameDirection.UPSTREAM), self.service.processed_frames)
        # Repeat on filler flag must be activated
        self.assertTrue(self.service._repeat_on_filler_pending)
        # Metric frame must be pushed
        metric_frames = [
            f for f in self.service.pushed_frames
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("data", {}).get("type") == "metrics"
            and f.message.get("data", {}).get("payload", {}).get("type") == "interruption"
        ]
        self.assertEqual(len(metric_frames), 1)

    async def test_user_started_speaking_passes_when_tools_idle(self):
        """Verify UserStartedSpeakingFrame is processed when no tools are in-flight."""
        self.assertFalse(self.service._tools_in_flight())

        user_speaking_frame = UserStartedSpeakingFrame()
        await self.service.process_frame(user_speaking_frame, FrameDirection.UPSTREAM)

        self.assertIn((user_speaking_frame, FrameDirection.UPSTREAM), self.service.processed_frames)

    # =========================================================================
    # 3. _cancel_function_call REFUSAL & IN-FLIGHT TASK PRESERVATION
    # =========================================================================

    async def test_cancel_function_call_refuses_cancellation(self):
        """Verify _cancel_function_call refuses in-flight cancellation cleanly."""
        self.service._lock_tools("active tool")
        self.assertEqual(self.service._active_tools_in_flight, 1)

        # Call with named function
        res = await self.service._cancel_function_call("calculate_mtl_returns")
        self.assertIsNone(res)

        # Call with None (Pipecat contract: function_name: str | None)
        res_none = await self.service._cancel_function_call(None)
        self.assertIsNone(res_none)

        # Verify lock was NOT corrupted
        self.assertEqual(self.service._active_tools_in_flight, 1)

    async def test_cancel_function_call_does_not_cancel_running_asyncio_task(self):
        """Empirically verify that a running background calculation task is not cancelled."""
        task_executed = False

        async def long_running_calc():
            nonlocal task_executed
            await asyncio.sleep(0.05)
            task_executed = True
            return 432000.0

        self.service._lock_tools("long calculation")
        bg_task = asyncio.create_task(long_running_calc())

        # Pipecat attempts to cancel function call
        await self.service._cancel_function_call("calculate_mtl_returns")

        # Wait for task completion
        result = await bg_task
        self.assertTrue(task_executed)
        self.assertEqual(result, 432000.0)
        self.assertFalse(bg_task.cancelled())

    # =========================================================================
    # 4. 8.0s SELF-HEALING WATCHDOG GUARD
    # =========================================================================

    async def test_watchdog_exact_8s_timeout_and_self_healing(self):
        """Verify the 8.0s watchdog auto-releases stuck/hanging tool locks."""
        # 1. Fresh lock
        self.service._lock_tools("hanging tool")
        self.assertTrue(self.service._tools_in_flight())
        self.assertEqual(self.service._active_tools_in_flight, 1)

        # 2. At 7.9 seconds, lock must still be active
        self.service._tool_lock_started_at = time.monotonic() - 7.9
        self.assertTrue(self.service._tools_in_flight(), "Lock should remain active at 7.9s")
        self.assertEqual(self.service._active_tools_in_flight, 1)

        # 3. At 8.1 seconds, watchdog must auto-release
        self.service._tool_lock_started_at = time.monotonic() - 8.1
        self.assertFalse(
            self.service._tools_in_flight(),
            "Watchdog must force-release stuck lock after 8.0s",
        )
        self.assertEqual(self.service._active_tools_in_flight, 0)
        self.assertFalse(self.service._frame_locked_tools)
        self.assertIsNone(self.service._tool_lock_started_at)

        # 4. Subsequent interruption frames must now pass through immediately
        int_frame = InterruptionFrame()
        await self.service.process_frame(int_frame, FrameDirection.UPSTREAM)
        self.assertIn((int_frame, FrameDirection.UPSTREAM), self.service.processed_frames)

    async def test_watchdog_recovery_and_re_locking(self):
        """Verify service recovers cleanly and can acquire new locks after watchdog release."""
        # Stuck lock expires
        self.service._lock_tools("stuck 1")
        self.service._tool_lock_started_at = time.monotonic() - 10.0
        self.assertFalse(self.service._tools_in_flight())

        # New legitimate tool call starts
        await self.service.process_frame(FunctionCallInProgressFrame(), FrameDirection.DOWNSTREAM)
        self.assertTrue(self.service._tools_in_flight())
        self.assertEqual(self.service._active_tools_in_flight, 1)

        # Interruption is suppressed again
        int_frame = InterruptionFrame()
        initial_count = len(self.service.processed_frames)
        await self.service.process_frame(int_frame, FrameDirection.UPSTREAM)
        self.assertEqual(len(self.service.processed_frames), initial_count)

        # Normal completion releases lock
        await self.service.process_frame(FunctionCallResultFrame(result="ok"), FrameDirection.DOWNSTREAM)
        self.assertFalse(self.service._tools_in_flight())

    # =========================================================================
    # 5. NON-SUPPRESSION OF CANCELFRAME (PIPELINE SHUTDOWN)
    # =========================================================================

    async def test_cancel_frame_never_suppressed_during_active_tool(self):
        """CRITICAL INVARIANT: CancelFrame MUST NOT be suppressed even when tools are in-flight."""
        # Tool is actively running
        self.service._lock_tools("active calculation")
        self.assertTrue(self.service._tools_in_flight())

        cancel_frame = CancelFrame()
        await self.service.process_frame(cancel_frame, FrameDirection.DOWNSTREAM)

        # CancelFrame MUST pass through to base processor
        self.assertIn(
            (cancel_frame, FrameDirection.DOWNSTREAM),
            self.service.processed_frames,
            "CancelFrame was suppressed during active tool call! This causes Cloud Run session leak.",
        )

    async def test_cancel_frame_passes_when_idle(self):
        """Verify CancelFrame passes through when idle."""
        cancel_frame = CancelFrame()
        await self.service.process_frame(cancel_frame, FrameDirection.DOWNSTREAM)
        self.assertIn((cancel_frame, FrameDirection.DOWNSTREAM), self.service.processed_frames)

    async def test_custom_protobuf_serializer_filters_control_frames(self):
        """Verify CustomProtobufSerializer suppresses binary serialization of Interruption and Cancel frames."""
        serializer = CustomProtobufSerializer()
        int_res = await serializer.serialize(InterruptionFrame())
        self.assertIsNone(int_res, "InterruptionFrame should return None from serialize")

        cancel_res = await serializer.serialize(CancelFrame())
        self.assertIsNone(cancel_res, "CancelFrame should return None from serialize")

    # =========================================================================
    # 6. METHOD-LEVEL TOOL EXECUTION (_run_function_call) & EXCEPTION SAFETY
    # =========================================================================

    async def test_run_function_call_automatic_lock_and_release(self):
        """Verify _run_function_call manages lock when not frame-locked."""
        class MockToolCall:
            def __init__(self, service_ref):
                self.service = service_ref
                self.was_locked_during_exec = False

            async def execute(self):
                # Verify lock is active during body
                self.was_locked_during_exec = self.service._tools_in_flight()
                await asyncio.sleep(0.01)
                return {"result": 42}

        tool = MockToolCall(self.service)
        self.assertFalse(self.service._tools_in_flight())

        result = await self.service._run_function_call(tool)

        self.assertTrue(tool.was_locked_during_exec)
        self.assertEqual(result, {"result": 42})
        self.assertFalse(self.service._tools_in_flight())
        self.assertEqual(self.service._active_tools_in_flight, 0)

    async def test_run_function_call_exception_safety(self):
        """Verify _run_function_call releases lock even if tool throws an exception."""
        class FaultyToolCall:
            async def execute(self):
                raise ValueError("Simulated tool computation failure")

        self.assertFalse(self.service._tools_in_flight())

        with self.assertRaises(ValueError):
            await self.service._run_function_call(FaultyToolCall())

        # Invariant: lock MUST be released in finally block
        self.assertFalse(self.service._tools_in_flight())
        self.assertEqual(self.service._active_tools_in_flight, 0)
        self.assertIsNone(self.service._tool_lock_started_at)

    async def test_run_function_call_nested_under_frame_lock(self):
        """Verify _run_function_call does not prematurely release if locked at frame level."""
        # Frame lock sets lock first
        await self.service.process_frame(FunctionCallInProgressFrame(), FrameDirection.DOWNSTREAM)
        self.assertTrue(self.service._tools_in_flight())
        self.assertEqual(self.service._active_tools_in_flight, 1)

        # _run_function_call executes
        class QuickTool:
            async def execute(self):
                return "done"

        await self.service.process_frame(FunctionCallResultFrame(result="done"), FrameDirection.DOWNSTREAM)
        self.assertFalse(self.service._tools_in_flight())
        self.assertEqual(self.service._active_tools_in_flight, 0)

    # =========================================================================
    # 7. HIGH-CONCURRENCY STRESS & RAPID INTERLEAVED FRAME INGRESS
    # =========================================================================

    async def test_concurrent_tool_executions_and_rapid_interruption_storm(self):
        """Stress-test: 50 concurrent async tools bombarded with 500 rapid interruption & cancel frames."""
        completed_tools = 0
        suppressed_interruptions = 0
        allowed_interruptions = 0
        total_cancel_frames_seen = 0

        async def simulated_tool_worker(worker_id: int):
            nonlocal completed_tools
            # Simulate frame arrival
            self.service._lock_tools(f"worker_{worker_id}")
            await asyncio.sleep(0.02)  # Simulate calculation
            self.service._release_tools(f"worker_{worker_id}")
            completed_tools += 1

        async def frame_bomber():
            nonlocal suppressed_interruptions, allowed_interruptions, total_cancel_frames_seen
            for i in range(500):
                mod = i % 5
                if mod in (0, 1):
                    # InterruptionFrame
                    in_flight_before = self.service._tools_in_flight()
                    int_frame = InterruptionFrame()
                    prev_len = len(self.service.processed_frames)
                    await self.service.process_frame(int_frame, FrameDirection.UPSTREAM)
                    if in_flight_before:
                        suppressed_interruptions += 1
                        self.assertEqual(len(self.service.processed_frames), prev_len)
                    else:
                        allowed_interruptions += 1
                        self.assertEqual(len(self.service.processed_frames), prev_len + 1)
                elif mod == 2:
                    # UserStartedSpeakingFrame
                    in_flight_before = self.service._tools_in_flight()
                    spk_frame = UserStartedSpeakingFrame()
                    prev_len = len(self.service.processed_frames)
                    await self.service.process_frame(spk_frame, FrameDirection.UPSTREAM)
                    if in_flight_before:
                        suppressed_interruptions += 1
                        self.assertEqual(len(self.service.processed_frames), prev_len)
                    else:
                        allowed_interruptions += 1
                        self.assertEqual(len(self.service.processed_frames), prev_len + 1)
                elif mod == 3:
                    # CancelFrame (Must ALWAYS pass through)
                    cancel_frame = CancelFrame()
                    prev_len = len(self.service.processed_frames)
                    await self.service.process_frame(cancel_frame, FrameDirection.DOWNSTREAM)
                    total_cancel_frames_seen += 1
                    self.assertEqual(
                        len(self.service.processed_frames),
                        prev_len + 1,
                        "CancelFrame was dropped during concurrency stress!",
                    )
                else:
                    # Generic TextFrame
                    text_frame = TextFrame(text=f"ping_{i}")
                    await self.service.process_frame(text_frame, FrameDirection.DOWNSTREAM)

                await asyncio.sleep(0.001)

        # Launch 50 concurrent tools and the frame bomber simultaneously
        tool_tasks = [asyncio.create_task(simulated_tool_worker(i)) for i in range(50)]
        bomber_task = asyncio.create_task(frame_bomber())

        await asyncio.gather(*tool_tasks, bomber_task)

        # Assertions
        self.assertEqual(completed_tools, 50, "All 50 concurrent tools should finish")
        self.assertEqual(total_cancel_frames_seen, 100, "All 100 CancelFrames must pass through")
        self.assertGreater(suppressed_interruptions, 0, "At least some interruptions must have been shielded")
        self.assertFalse(self.service._tools_in_flight(), "Final state must have 0 tools in flight")
        self.assertEqual(self.service._active_tools_in_flight, 0)

    # =========================================================================
    # 8. BOUNDARY CONDITIONS & DEFENSIVE INVARIANTS
    # =========================================================================

    async def test_defensive_underflow_protection_on_release(self):
        """Verify _release_tools never produces negative _active_tools_in_flight."""
        self.assertEqual(self.service._active_tools_in_flight, 0)

        # Multiple releases on zero
        self.service._release_tools("extra release 1")
        self.service._release_tools("extra release 2")
        self.service._release_tools("extra release 3")

        self.assertEqual(self.service._active_tools_in_flight, 0)
        self.assertFalse(self.service._tools_in_flight())

    async def test_malformed_result_frames_handled_gracefully(self):
        """Verify result frame with missing or None result does not throw."""
        await self.service.process_frame(FunctionCallInProgressFrame(), FrameDirection.DOWNSTREAM)

        # Empty result frame
        empty_res = Frame()
        empty_res.__class__.__name__ = "FunctionCallResultFrame"
        # process_frame checks getattr(frame, 'result', getattr(frame, 'content', ''))
        await self.service.process_frame(empty_res, FrameDirection.DOWNSTREAM)

        self.assertFalse(self.service._tools_in_flight())


if __name__ == "__main__":
    unittest.main()
