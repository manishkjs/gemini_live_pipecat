"""The first call on a fresh instance must not pay ~25s of lazy SDK imports.

Startup stays fast (media SDKs are not imported at module load, see
test_server_startup), but the lifespan kicks off a background warmup so the
imports are done before the first WebSocket arrives.
"""
import asyncio
import threading
import unittest
from unittest import mock

import server


class TestPipelineWarmup(unittest.TestCase):
    def test_lifespan_starts_warmup_without_blocking_startup(self):
        started, release = threading.Event(), threading.Event()

        def slow_warmup():
            started.set()
            release.wait(5)

        async def scenario():
            with mock.patch.object(server, "warm_media_pipelines", slow_warmup):
                async with server.lifespan(server.app):
                    # Startup completed even though warmup is still running.
                    await asyncio.to_thread(started.wait, 5)
                    self.assertTrue(started.is_set())
                    release.set()

        asyncio.run(asyncio.wait_for(scenario(), timeout=10))

    def test_warmup_failure_never_breaks_startup(self):
        def broken():
            raise RuntimeError("boom")

        async def scenario():
            with mock.patch.object(server, "warm_media_pipelines", broken):
                async with server.lifespan(server.app):
                    await asyncio.sleep(0.05)

        asyncio.run(asyncio.wait_for(scenario(), timeout=10))

    def test_warm_media_pipelines_loads_every_pipeline_and_turn_model(self):
        with mock.patch.object(server, "load_pipeline") as load, \
                mock.patch.object(server.importlib, "import_module") as imp:
            server.warm_media_pipelines()
        self.assertEqual({c.args[0] for c in load.call_args_list},
                         {"tts-llm-stt", "gemini-live"})
        imp.assert_called_with("pipecat.audio.turn.smart_turn.local_smart_turn_v3")


if __name__ == "__main__":
    unittest.main()
