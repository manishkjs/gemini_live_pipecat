"""Hermetic Unit & Boundary Test Suite for `save_memory` Tool Schema and Async Handler.

Covers:
1. `save_memory_schema` FunctionSchema validation and required fields.
2. `handle_save_memory` async handler persisting facts into FactStore.
3. `handle_save_memory` async handler adding episodic memory note to MemoryBank.
4. Tool registration in `get_standard_tools()` and `register_all_tools()`.
5. Error handling and default fallback parameters.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, List, Optional

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ["ENABLE_CLOUD_MEMORY_BANK"] = "false"

from memory_bank import MemoryBank, normalize_lexical_user_id
from tools.tool_definitions import (
    save_memory_schema,
    handle_save_memory,
    get_standard_tools,
    register_all_tools,
)


class TestSaveMemorySchema(unittest.TestCase):
    """Tests for save_memory FunctionSchema."""

    def test_schema_name_and_required(self):
        self.assertEqual(save_memory_schema.name, "save_memory")
        self.assertIn("note", save_memory_schema.required)

    def test_schema_properties(self):
        props = save_memory_schema.properties
        self.assertIn("user_id", props)
        self.assertIn("amount", props)
        self.assertIn("tenure_months", props)
        self.assertIn("risk_preference", props)
        self.assertIn("goal", props)
        self.assertIn("note", props)

    def test_schema_in_standard_tools(self):
        tools = get_standard_tools()
        tool_names = [t.name for t in tools]
        self.assertIn("save_memory", tool_names)
        self.assertIn("retrieve_memory", tool_names)


class TestSaveMemoryHandler(unittest.IsolatedAsyncioTestCase):
    """Tests for handle_save_memory async execution."""

    def setUp(self):
        self.memory_bank = MemoryBank(enable_cloud=False)

    async def test_save_memory_with_facts_and_note(self):
        """Test handle_save_memory persists structured facts and episodic note."""
        mock_params = MagicMock()
        mock_params.arguments = {
            "user_id": "Mr. Rajesh Kumar",
            "amount": 100000.0,
            "tenure_months": 12,
            "risk_preference": "low",
            "goal": "wealth creation",
            "note": "Agreed to start with ₹1,00,000 MTL plan next week after salary credit.",
        }
        mock_callback = AsyncMock()
        mock_params.result_callback = mock_callback

        await handle_save_memory(mock_params, memory_bank=self.memory_bank)

        mock_callback.assert_awaited_once()
        result = mock_callback.call_args[0][0]
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["user_id"], "user_rajesh_kumar")
        self.assertEqual(result["facts_saved"]["amount"], 100000.0)
        self.assertEqual(result["facts_saved"]["tenure_months"], 12)

        # Verify FactStore contains active facts
        fact_store = self.memory_bank.get_fact_store("user_rajesh_kumar")
        self.assertEqual(fact_store.get_fact("amount"), 100000.0)
        self.assertEqual(fact_store.get_fact("tenure_months"), 12)

        # Verify MemoryBank contains episodic note
        mems = self.memory_bank.get_user_memories("user_rajesh_kumar")
        self.assertEqual(len(mems), 1)
        self.assertIn("MTL plan", mems[0]["content"])

    async def test_save_memory_default_user_fallback(self):
        """Test missing user_id defaults gracefully to active/default user."""
        mock_params = MagicMock()
        mock_params.arguments = {
            "note": "User asked to follow up tomorrow evening.",
        }
        mock_callback = AsyncMock()
        mock_params.result_callback = mock_callback

        await handle_save_memory(mock_params, memory_bank=self.memory_bank)

        mock_callback.assert_awaited_once()
        result = mock_callback.call_args[0][0]
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["user_id"].startswith("user_"))

    async def test_save_memory_exception_handling(self):
        """Test exceptions in memory bank trigger clean error callback."""
        mock_params = MagicMock()
        mock_params.arguments = {"note": "Test note"}
        mock_callback = AsyncMock()
        mock_params.result_callback = mock_callback

        mock_bad_mb = MagicMock()
        mock_bad_mb.add_memory.side_effect = RuntimeError("Disk full")

        await handle_save_memory(mock_params, memory_bank=mock_bad_mb)
        mock_callback.assert_awaited_once()
        result = mock_callback.call_args[0][0]
        self.assertEqual(result["status"], "error")


class TestRegisterAllTools(unittest.TestCase):
    """Tests for register_all_tools with save_memory."""

    def test_register_all_tools_includes_save_memory(self):
        mock_llm = MagicMock()
        tools = get_standard_tools()
        register_all_tools(mock_llm, tools)

        registered_names = [call[0][0] for call in mock_llm.register_function.call_args_list]
        self.assertIn("save_memory", registered_names)
        self.assertIn("retrieve_memory", registered_names)


if __name__ == "__main__":
    unittest.main()
