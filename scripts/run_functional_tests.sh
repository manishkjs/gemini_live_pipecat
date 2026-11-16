#!/usr/bin/env bash
# Automated post-code-work functional & unit verification gate.
# Runs:
#   1. Wire-level SDK & Persona/Language functional mock suite (test_functional_wire_contracts.py)
#   2. Full backend unit test discovery (580+ tests across server/tests/)
#   3. FastAPI route & security contract tests (server/test_routes.py)
set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly SERVER_DIR="${REPO_ROOT}/server"

if [[ -x "${SERVER_DIR}/venv/bin/python" ]]; then
  PYTHON_BIN="${SERVER_DIR}/venv/bin/python"
elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi
readonly PYTHON_BIN

echo "==> [1/3] Running Wire-Level SDK & Persona/Language Functional Suite..."
(cd "${SERVER_DIR}" && "${PYTHON_BIN}" -m unittest tests.test_functional_wire_contracts -v)

echo "==> [2/3] Running Full Backend Unit Test Suite (server/tests)..."
(cd "${SERVER_DIR}" && "${PYTHON_BIN}" -m unittest discover -s tests -p "test_*.py")

echo "==> [3/3] Running FastAPI Route & Security Contract Suite (server/test_routes.py)..."
(cd "${SERVER_DIR}" && "${PYTHON_BIN}" test_routes.py)

echo "==> All functional, unit, and route contract suites passed."
