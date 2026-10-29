"""Structural startup check in an uncontaminated interpreter."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class TestServerStartup(unittest.TestCase):
    def test_import_does_not_load_media_sdks(self):
        server_dir = str(Path(__file__).resolve().parents[1])
        result = subprocess.run([sys.executable, "-c", """
import sys
import server
for name in ('grpc', 'pipecat', 'google.genai', 'vertexai', 'google.cloud.speech_v2'):
    assert name not in sys.modules, f'Eager import: {name}'
"""], env={**os.environ, "PYTHONPATH": server_dir}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
