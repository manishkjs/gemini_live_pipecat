import sys
import os
import unittest

server_dir = os.path.dirname(os.path.abspath(__file__))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from fastapi.testclient import TestClient
from server import app
from tracing import GLOBAL_LANGSMITH_TRACER

class TestDiagnosticsAndTracing(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_diagnostics_route(self):
        r = self.client.get("/diagnostics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Gemini Live Telemetry & LangSmith Traces", r.text)

    def test_logs_endpoint(self):
        from diagnostic_buffer import append_raw_log_entry, record_turn_latency
        record_turn_latency("live_ttfb", 380.0, "Test Turn 1")
        append_raw_log_entry("LLM Latency: 0.450s")
        r = self.client.get("/api/logs")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("logs", data)
        self.assertIn("latency_summary", data)
        self.assertIn("live_ttfb", data["latency_summary"])
        self.assertIn("p50", data["latency_summary"]["live_ttfb"])

    def test_latency_metrics_endpoint(self):
        r = self.client.get("/api/metrics/latency")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("live_ttfb", data)
        self.assertIn("llm", data)
        self.assertIn("stt", data)
        self.assertIn("tts", data)
        self.assertIn("total_turnaround", data)

    def test_trace_endpoint(self):
        r = self.client.get("/api/trace/current")
        self.assertEqual(r.status_code, 200)
        self.assertIn("trace_url", r.json())

    def test_tracer_session(self):
        url = GLOBAL_LANGSMITH_TRACER.start_session("test_sess", "gemini-live-2.5-flash-native-audio", "Puck", "en-US")
        self.assertIsNotNone(url)
        GLOBAL_LANGSMITH_TRACER.record_user_turn("Hello Gemini")
        GLOBAL_LANGSMITH_TRACER.record_bot_turn("Hello!", ttfb_ms=350.0)
        GLOBAL_LANGSMITH_TRACER.record_tool_call("get_current_time", {}, "14:15 UTC", 10.0)
        GLOBAL_LANGSMITH_TRACER.record_interruption(200.0)
        GLOBAL_LANGSMITH_TRACER.end_session("Session finished")

if __name__ == "__main__":
    unittest.main()
