"""
Direct standalone runner for Challenger 4 verification suite.
Can be executed via `python3 tests/run_challenger4_verification.py` or `pytest`.
"""

import sys
import os
import unittest

# Add repo root to path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.test_challenger4_ttfb_and_timeouts import TestChallenger4TTFBAndTimeouts

if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestChallenger4TTFBAndTimeouts)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
