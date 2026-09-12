"""Response event ordering without opening a provider connection.

The service methods are extracted from the real adapters. Only the provider
base and media frames are substituted, so this checks the transport boundary
without loading the audio/model dependency graph.
"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from response_identity import ResponseIdentity
from tracing import SessionTracerRegistry


class OutputFrame:
    def __init__(self, message):
        self.message = message


class TextFrame:
    pass


class EndFrame:
    pass


def adapter_class(filename, class_name, methods):
    path = Path(__file__).resolve().parents[1] / filename
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node.bases = []
    node.body = [n for n in node.body if getattr(n, "name", None) in methods]
    namespace = {
        "ResponseIdentity": ResponseIdentity,
        "current_session_id": lambda: "test-call",
        "FrameDirection": SimpleNamespace(DOWNSTREAM="downstream"),
        "OutputTransportMessageFrame": OutputFrame,
        "TextFrame": TextFrame, "LLMFullResponseEndFrame": EndFrame,
        "logger": SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, error=lambda *a: None),
        "Content": SimpleNamespace, "Part": SimpleNamespace,
        "estimate_tokens": lambda text: len(text),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[class_name]


class ProviderBase:
    def __init__(self):
        self.frames = []

    async def push_frame(self, frame, direction=None):
        self.frames.append(frame)

    async def _handle_msg_model_turn(self, message):
        pass

    async def _handle_msg_turn_complete(self, message):
        pass

    async def _handle_msg_usage_metadata(self, message):
        pass

    async def _process_context(self, context):
        await self.push_frame(TextFrame())
        await self.push_frame(OutputFrame({"data": {"type": "metrics", "payload": {"type": "usage"}}}))
        await self.push_frame(EndFrame())


class TestResponseEvents(unittest.IsolatedAsyncioTestCase):
    def directive_service(self, gemini3=False):
        adapter = adapter_class("agent_live.py", "GeminiSessionLoggerMixin", {"inject_directive"})
        service = adapter()
        service._disconnecting = False
        service._bot_is_responding = False
        service._is_gemini_3 = gemini3
        service._session = SimpleNamespace(send_client_content=AsyncMock(), send_realtime_input=AsyncMock())
        service._create_single_response = AsyncMock()
        return service

    async def test_25_brief_uses_uncommitted_client_content(self):
        service = self.directive_service()
        self.assertTrue(await service.inject_directive("card", speak_now=False))
        args = service._session.send_client_content.call_args.kwargs
        self.assertFalse(args["turn_complete"])
        self.assertEqual(args["turns"][0].parts[0].text, "card")
        service._session.send_realtime_input.assert_not_awaited()
        self.assertEqual(service._last_directive_status, "sent")

    async def test_3_brief_uses_realtime_text(self):
        service = self.directive_service(gemini3=True)
        self.assertTrue(await service.inject_directive("card", speak_now=False))
        service._session.send_realtime_input.assert_awaited_once_with(text="card")
        service._session.send_client_content.assert_not_awaited()

    async def test_brief_defers_while_model_is_responding(self):
        service = self.directive_service()
        service._bot_is_responding = True
        self.assertFalse(await service.inject_directive("card", speak_now=False))
        self.assertEqual(service._last_directive_status, "pending")
        service._session.send_client_content.assert_not_awaited()
        service._session.send_realtime_input.assert_not_awaited()

    async def test_failed_send_is_not_reported_as_sent(self):
        service = self.directive_service()
        service._session.send_client_content.side_effect = RuntimeError("socket closed")
        self.assertFalse(await service.inject_directive("card", speak_now=False))
        self.assertEqual(service._last_directive_status, "failed")

    async def test_live_usage_after_completion_keeps_response_identity(self):
        mixin = adapter_class("agent_live.py", "GeminiSessionLoggerMixin", {
            "response_identity", "push_frame", "_handle_msg_model_turn",
            "_handle_msg_turn_complete", "_handle_msg_usage_metadata",
        })
        class Service(mixin, ProviderBase):
            pass
        service = Service()
        service.persona_architecture = SimpleNamespace(flush_pending_card=AsyncMock())
        message = SimpleNamespace(usage_metadata=SimpleNamespace(
            prompt_token_count=60, response_token_count=40, total_token_count=100,
            cached_content_token_count=10, thoughts_token_count=2,
            tool_use_prompt_token_count=3,
        ))
        await service._handle_msg_model_turn(None)
        first = service.response_identity.current
        await service.push_frame(OutputFrame({"data": {
            "type": "transcription", "participant": "Bot", "text": "Hello",
        }}))
        await service._handle_msg_turn_complete(None)
        service.persona_architecture.flush_pending_card.assert_awaited_once()
        await service._handle_msg_usage_metadata(message)
        await service._handle_msg_usage_metadata(message)
        data = [frame.message["data"] for frame in service.frames]
        self.assertEqual(data[0]["response_id"], first)
        self.assertEqual(data[1]["payload"]["response_id"], first)
        usage = data[2]["payload"]
        self.assertEqual(usage["response_id"], first)
        self.assertEqual(usage["event_id"], data[3]["payload"]["event_id"])
        self.assertEqual(usage["session_id"], "test-call")
        self.assertEqual(usage["usage"]["cached_content_token_count"], 10)
        self.assertEqual(usage["usage"]["total_token_count"], 100)
        await service._handle_msg_model_turn(None)
        self.assertNotEqual(service.response_identity.current, first)

    async def test_cascade_text_and_usage_are_stamped_before_they_are_queued(self):
        mixin = adapter_class("agent.py", "CustomGoogleVertexLLMService", {
            "response_identity", "push_frame", "_process_context",
        })
        class Service(mixin, ProviderBase):
            pass
        service = Service()
        await service._process_context(None)
        first = service.frames[0].response_id
        self.assertEqual(service.frames[1].message["data"]["payload"]["response_id"], first)
        self.assertEqual(service.frames[3].message["data"]["payload"]["response_id"], first)
        self.assertIsNone(service.response_identity.current)
        await service._process_context(None)
        self.assertNotEqual(service.frames[4].response_id, first)

    async def test_traces_remain_isolated_when_sessions_interleave_and_one_ends(self):
        class FakeTracer:
            def __init__(self):
                self.events = []
            def start_session(self, session_id):
                self.session_id = session_id
            def record_user_turn(self, text):
                self.events.append(text)
            def end_session(self):
                self.ended = True
            def get_current_trace_url(self):
                return f"trace:{self.session_id}"
        registry = SessionTracerRegistry()
        b_started, a_ended = asyncio.Event(), asyncio.Event()
        async def a():
            registry.start_session("A")
            await b_started.wait()
            registry.record_user_turn("A's words")
            registry.end_session()
            a_ended.set()
        async def b():
            registry.start_session("B")
            b_started.set()
            await a_ended.wait()
            registry.record_user_turn("B's words")
            self.assertEqual(registry.get_current_trace_url(), "trace:B")
        with patch("tracing.LangSmithTracer", FakeTracer):
            await asyncio.gather(a(), b())
        self.assertEqual(registry._sessions["A"].events, ["A's words"])
        self.assertEqual(registry._sessions["B"].events, ["B's words"])
        self.assertEqual(registry.get_current_trace_url("A"), "trace:A")
        self.assertIsNone(registry.get_current_trace_url("unknown"))
