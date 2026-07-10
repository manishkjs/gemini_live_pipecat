import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
import sys

# Mock optional krisp dependency before importing agent_live
sys.modules["pipecat.audio.krisp_instance"] = MagicMock()
sys.modules["pipecat.audio.filters.krisp_viva_filter"] = MagicMock()
sys.modules["pipecat.audio.turn.krisp_viva_turn"] = MagicMock()
sys.modules["pipecat.turns.user_start.krisp_viva_ip_user_turn_start_strategy"] = MagicMock()

# Import classes to test
import agent_live
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.frames.frames import FunctionCallResultFrame

class TestAgentLiveRefinements(unittest.IsolatedAsyncioTestCase):

    def test_settings_include_resumption_and_cwc(self):
        """Test that run_agent_live configures session resumption and CWC sliding window."""
        # This should fail until we update Settings in run_agent_live
        # Let's inspect the Settings class or defaults in agent_live if exposed,
        # or we test our new helper function / mixin attributes.
        self.assertTrue(hasattr(agent_live, "get_default_settings"))
        settings = agent_live.get_default_settings()
        self.assertIsNotNone(settings.extra.get("session_resumption"))
        self.assertIn("sliding_window", settings.context_window_compression)
        self.assertEqual(settings.context_window_compression["sliding_window"]["trigger_tokens"], 20000)

    async def test_tool_result_scheduling_extraction(self):
        """Test that _tool_result pops scheduling from response dict to top-level FunctionResponse."""
        mixin = agent_live.GeminiSessionLoggerMixin()
        # Mocking required attributes for _tool_result
        mixin._session = MagicMock(spec=["send"])
        mixin._session.send = AsyncMock()
        
        result_frame = FunctionCallResultFrame(
            function_name="dynamic_tool_handler",
            tool_call_id="call_123",
            arguments={},
            result={"status": "success", "scheduling": "SILENT"}
        )
        
        await mixin._tool_result(result_frame)
        
        # Verify send was called with scheduling at top level of FunctionResponse
        mixin._session.send.assert_called_once()
        call_arg = mixin._session.send.call_args[0][0]
        # In pipecat, call_arg is client_content or tool_response pydantic model
        # We assert scheduling is extracted properly
        self.assertEqual(getattr(call_arg, "scheduling", None) or call_arg.get("scheduling"), "SILENT")

    async def test_two_layer_deduplication(self):
        """Test that dynamic_tool_handler returns 'OK' on duplicate calls."""
        # First call succeeds
        res1 = await agent_live.dynamic_tool_handler("test_tool", {"action": "jump"}, round_id=1)
        self.assertNotEqual(res1, "OK")
        
        # Second call with same round_id returns OK
        res2 = await agent_live.dynamic_tool_handler("test_tool", {"action": "jump"}, round_id=1)
        self.assertEqual(res2, "OK")

    async def test_go_away_handling(self):
        """Test that _connection_task_handler intercepts go_away and calls _reconnect."""
        mixin = agent_live.GeminiSessionLoggerMixin()
        mixin._reconnect = AsyncMock()
        
        # Simulate go_away message from server
        go_away_msg = MagicMock()
        go_away_msg.go_away = True
        
        await mixin._handle_server_message(go_away_msg)
        mixin._reconnect.assert_called_once()

    async def test_reconnect_audio_buffering(self):
        """Test that audio frames are buffered during reconnect and flushed when session is ready."""
        mixin = agent_live.GeminiSessionLoggerMixin()
        mixin._session = None  # Simulating disconnected state during handshake
        mixin._audio_buffer = []
        
        # Attempt to send audio while disconnected
        audio_frame = MagicMock()
        await mixin._buffer_or_send_audio(audio_frame)
        
        self.assertEqual(len(mixin._audio_buffer), 1)
        self.assertEqual(mixin._audio_buffer[0], audio_frame)

    async def test_custom_service_tool_result_compatibility(self):
        """Test that CustomGeminiLiveLLMService._tool_result is compatible with 3-arg call from parent."""
        with patch("google.genai.Client") as mock_client:
            service = agent_live.CustomGeminiLiveLLMService(api_key="dummy")
            service._session = MagicMock()
            service._session.send = AsyncMock()
            
            # Simulate a 3-argument call that would be made by GeminiLiveLLMService internally
            # e.g., in _process_completed_function_calls:
            # await self._tool_result(tool_call_id, tool_name, response_dict)
            try:
                await service._tool_result("call_123", "test_tool", {"status": "success"})
            except TypeError as e:
                self.fail(f"_tool_result signature mismatch: {e}")

    async def test_reconnect_audio_flushing(self):
        """Test that buffered audio frames are flushed when session is ready."""
        frame1 = MagicMock()
        frame2 = MagicMock()
        with patch("google.genai.Client") as mock_client:
            service = agent_live.CustomGeminiLiveLLMService(api_key="dummy")
            service._session = None
            service._audio_buffer = []
            
            await service._buffer_or_send_audio(frame1)
            await service._buffer_or_send_audio(frame2)
            self.assertEqual(len(service._audio_buffer), 2)
            
            # Now session becomes ready
            mock_session = MagicMock()
            service._send_user_audio = AsyncMock()
            
            await service._handle_session_ready(mock_session)
            
            # Verify that _send_user_audio was called for both frames
            self.assertEqual(service._send_user_audio.call_count, 2)
            service._send_user_audio.assert_has_calls([
                unittest.mock.call(frame1),
                unittest.mock.call(frame2)
            ])
            # Verify buffer is cleared
            self.assertEqual(len(service._audio_buffer), 0)

    async def test_custom_service_tool_result_scheduling(self):
        """Test that CustomGeminiLiveLLMService._tool_result preserves scheduling: SILENT when calling parent."""
        with patch("google.genai.Client") as mock_client:
            service = agent_live.CustomGeminiLiveLLMService(api_key="dummy")
            service._session = MagicMock()
            service._session.send_tool_response = AsyncMock()
            
            # We must mock _function_is_async to return True if we want to test scheduling?
            # Actually, if we pass scheduling in dict, we want it to be extracted.
            # Let's see if we need to mock it.
            service._function_is_async = MagicMock(return_value=True)
            # _supports_non_blocking_tools is True by default for non-Gemini 3 models.
            # Let's force it to True.
            service._settings.model = "gemini-2.5-flash" 
            
            await service._tool_result("call_123", "test_tool", {"status": "success", "scheduling": "SILENT"})
            
            service._session.send_tool_response.assert_called_once()
            kwargs = service._session.send_tool_response.call_args[1]
            response = kwargs["function_responses"]
            
            self.assertEqual(response.scheduling, "SILENT")

    async def test_start_trigger_processor(self):
        """Test that StartTriggerProcessor queues a greeting on start_trigger."""
        processor = agent_live.StartTriggerProcessor()
        processor.push_frame = AsyncMock()
        
        # Create an InputTransportMessageFrame with start_trigger
        frame = agent_live.InputTransportMessageFrame(message={"type": "start_trigger"})
        await processor.process_frame(frame)
        
        # Verify push_frame was called with LLMMessagesAppendFrame and LLMRunFrame
        self.assertEqual(processor.push_frame.call_count, 2)
        call1 = processor.push_frame.call_args_list[0][0][0]
        self.assertIsInstance(call1, agent_live.LLMMessagesAppendFrame)
        self.assertEqual(call1.messages, [{"role": "user", "content": "Hello!"}])
        
        call2 = processor.push_frame.call_args_list[1][0][0]
        self.assertIsInstance(call2, agent_live.LLMRunFrame)

if __name__ == "__main__":
    unittest.main()
