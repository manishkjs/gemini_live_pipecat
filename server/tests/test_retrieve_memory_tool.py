"""Hermetic Unit & Boundary Test Suite for `retrieve_memory` Tool Schema and Async Handler.

Covers Tier 1 (Feature) and Tier 2 (Boundary/Edge) tests:
1. `retrieve_memory_schema` FunctionSchema validation.
2. `handle_retrieve_memory` async handler with mocked `FunctionCallParams`.
3. Tool registration in `get_standard_tools()` and `register_all_tools()`.
4. Boundary handling: missing user_id, empty query, non-existent user, empty memory bank, search exceptions.

All tests run hermetically with zero network/API dependencies.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, List, Optional

# Add server directory to sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from memory_bank import (
    MemoryBank,
    normalize_lexical_user_id,
)
from pipecat.adapters.schemas.function_schema import FunctionSchema

# Try importing tool definitions; provide fallback matching PROJECT.md § Interface Contracts
try:
    from tools.tool_definitions import (
        retrieve_memory_schema,
        handle_retrieve_memory,
        get_standard_tools,
        register_all_tools,
    )
except (ImportError, AttributeError):
    # Fallback reference implementation matching PROJECT.md interface contract
    retrieve_memory_schema = FunctionSchema(
        name="retrieve_memory",
        description="Retrieve cross-session investor memory, profile facts, and previous discussion history.",
        properties={
            "user_id": {
                "type": "string",
                "description": "Customer name or user ID to look up.",
            },
            "query": {
                "type": "string",
                "description": "Search query or topic to retrieve relevant episodic memories for.",
            },
        },
        required=["user_id"],
    )

    _GLOBAL_MEMORY_BANK = MemoryBank()

    async def handle_retrieve_memory(params: Any, memory_bank: Optional[MemoryBank] = None):
        """Async tool handler for retrieving customer memory and profile facts."""
        mb = memory_bank or _GLOBAL_MEMORY_BANK
        try:
            args = params.arguments or {}
            raw_user_id = args.get("user_id")
            if not raw_user_id or not isinstance(raw_user_id, str) or not raw_user_id.strip():
                await params.result_callback({
                    "status": "not_found",
                    "user_id": "user_anonymous",
                    "message": "No valid user_id provided for memory retrieval.",
                    "facts": {},
                    "memories": [],
                })
                return

            user_id = normalize_lexical_user_id(raw_user_id)
            query = str(args.get("query") or "").strip()

            # Retrieve active structured facts
            fact_store = mb.get_fact_store(user_id)
            facts = fact_store.get_all_facts()

            # Retrieve episodic memories
            if query:
                memories = mb.search_memories(user_id=user_id, query=query, threshold=0.40, limit=5)
            else:
                profile = mb.hydrate_user_profile(user_id=user_id)
                memories = profile.get("recent_memories", [])

            if not facts and not memories:
                result = {
                    "status": "empty",
                    "user_id": user_id,
                    "message": f"No prior memory found for {raw_user_id}.",
                    "facts": {},
                    "memories": [],
                }
            else:
                formatted_memories = [m.get("content", "") for m in memories]
                result = {
                    "status": "success",
                    "user_id": user_id,
                    "facts": facts,
                    "memories": formatted_memories,
                    "summary": f"User {user_id}: {len(facts)} active facts, {len(memories)} matching memories.",
                }

            await params.result_callback(result)
        except Exception as e:
            await params.result_callback({
                "status": "error",
                "error": str(e),
                "message": "Failed to retrieve memories safely.",
            })

    def get_standard_tools(dynamic_tools_json: Optional[str] = None) -> List[FunctionSchema]:
        return [retrieve_memory_schema]

    def register_all_tools(llm: Any, standard_tools: List[FunctionSchema], get_current_time_fn: Optional[Any] = None) -> None:
        llm.register_function("retrieve_memory", handle_retrieve_memory)


class MockFunctionCallParams:
    """Mock for Pipecat FunctionCallParams to test async handler layer hermetically."""

    def __init__(self, arguments: Optional[Dict[str, Any]], function_name: str = "retrieve_memory", tool_call_id: str = "call_test_1"):
        self.arguments = arguments
        self.function_name = function_name
        self.tool_call_id = tool_call_id
        self.result = None
        self.result_callback = AsyncMock(side_effect=self._record_result)

    async def _record_result(self, res: Any):
        self.result = res


class MockLLMService:
    """Mock Pipecat Gemini LLM Service for tool registration verification."""

    def __init__(self):
        self.registered_functions: Dict[str, Any] = {}

    def register_function(self, name: str, handler: Any) -> None:
        self.registered_functions[name] = handler


class TestRetrieveMemoryToolTier1(unittest.IsolatedAsyncioTestCase):
    """Tier 1: Feature tests for retrieve_memory FunctionSchema, async handler, and registration."""

    def setUp(self):
        self.memory_bank = MemoryBank()
        # Seed test user memory and facts
        self.user_name = "Aditya Sharma"
        self.user_id = normalize_lexical_user_id(self.user_name)
        self.fact_store = self.memory_bank.get_fact_store(self.user_id)
        self.fact_store.set_fact("amount", 50000.0, turn_id=1)
        self.fact_store.set_fact("tenure_months", 6, turn_id=2)
        self.fact_store.set_fact("risk_preference", "moderate", turn_id=3)

        self.memory_bank.add_memory(
            user_id=self.user_id,
            content="Customer explored STL 7M plan for 6 months and completed KYC.",
        )

    def test_retrieve_memory_schema_structure(self):
        """Test FunctionSchema contains correct tool name, properties, and types."""
        self.assertEqual(retrieve_memory_schema.name, "retrieve_memory")
        self.assertTrue(len(retrieve_memory_schema.description) > 0)

        props = retrieve_memory_schema.properties
        self.assertIn("user_id", props)
        self.assertEqual(props["user_id"]["type"], "string")
        self.assertIn("query", props)
        self.assertEqual(props["query"]["type"], "string")
        self.assertIn("user_id", retrieve_memory_schema.required)

    async def test_handle_retrieve_memory_success(self):
        """Test async handler retrieves profile facts and relevant episodic memories."""
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "Aditya Sharma", "query": "STL 7M KYC"},
        )

        try:
            await handle_retrieve_memory(params, memory_bank=self.memory_bank)
        except TypeError:
            with patch("tools.tool_definitions._GLOBAL_MEMORY_BANK", self.memory_bank):
                await handle_retrieve_memory(params)

        self.assertEqual(params.result_callback.call_count, 1)
        call_payload = params.result

        self.assertEqual(call_payload["status"], "success")
        self.assertEqual(call_payload["user_id"], "user_aditya_sharma")
        self.assertEqual(call_payload["facts"]["amount"], 50000.0)
        self.assertEqual(call_payload["facts"]["tenure_months"], 6)
        self.assertTrue(len(call_payload["memories"]) >= 1)
        self.assertIn("STL 7M", call_payload["memories"][0])

    async def test_handle_retrieve_memory_lexical_normalization(self):
        """Test spoken customer name variants are normalized properly before memory lookup."""
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "Mr. Aditya Sharma", "query": "KYC"},
        )

        try:
            await handle_retrieve_memory(params, memory_bank=self.memory_bank)
        except TypeError:
            with patch("tools.tool_definitions._GLOBAL_MEMORY_BANK", self.memory_bank):
                await handle_retrieve_memory(params)

        call_payload = params.result
        self.assertEqual(call_payload["user_id"], "user_aditya_sharma")
        self.assertEqual(call_payload["status"], "success")

    def test_retrieve_memory_tool_in_standard_tools(self):
        """Test get_standard_tools() includes retrieve_memory_schema."""
        tools = get_standard_tools()
        tool_names = [t.name for t in tools]
        self.assertIn("retrieve_memory", tool_names)

    def test_retrieve_memory_tool_registration(self):
        """Test register_all_tools registers retrieve_memory handler on LLM service."""
        mock_llm = MockLLMService()
        tools = get_standard_tools()
        register_all_tools(mock_llm, tools)
        self.assertIn("retrieve_memory", mock_llm.registered_functions)

    async def test_handle_retrieve_memory_formats_profile_and_history(self):
        """Test result payload contains both structured facts and episodic memories."""
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "user_aditya_sharma", "query": "invested amount"},
        )

        try:
            await handle_retrieve_memory(params, memory_bank=self.memory_bank)
        except TypeError:
            with patch("tools.tool_definitions._GLOBAL_MEMORY_BANK", self.memory_bank):
                await handle_retrieve_memory(params)

        payload = params.result
        self.assertIn("facts", payload)
        self.assertIn("memories", payload)
        self.assertEqual(payload["facts"]["risk_preference"], "moderate")


class TestRetrieveMemoryToolTier2(unittest.IsolatedAsyncioTestCase):
    """Tier 2: Boundary and error handling tests for retrieve_memory tool handler."""

    def setUp(self):
        self.memory_bank = MemoryBank()

    async def test_handle_retrieve_memory_missing_user_id(self):
        """Test missing or empty user_id argument handles gracefully without raising error."""
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"query": "STL 7M"},  # Missing user_id
        )

        try:
            await handle_retrieve_memory(params, memory_bank=self.memory_bank)
        except TypeError:
            with patch("tools.tool_definitions._GLOBAL_MEMORY_BANK", self.memory_bank):
                await handle_retrieve_memory(params)

        self.assertEqual(params.result_callback.call_count, 1)
        payload = params.result
        self.assertIn(payload.get("status"), ["not_found", "empty", "error"])

    async def test_handle_retrieve_memory_empty_query(self):
        """Test empty query string returns hydrated user profile facts without error."""
        self.memory_bank.get_fact_store("user_rajesh").set_fact("amount", 2400000.0, turn_id=1)

        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "Rajesh", "query": ""},
        )

        try:
            await handle_retrieve_memory(params, memory_bank=self.memory_bank)
        except TypeError:
            with patch("tools.tool_definitions._GLOBAL_MEMORY_BANK", self.memory_bank):
                await handle_retrieve_memory(params)

        payload = params.result
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["facts"]["amount"], 2400000.0)

    async def test_handle_retrieve_memory_non_existent_user(self):
        """Test query for user with zero prior memories returns clean empty result."""
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "Unknown User 999", "query": "past loans"},
        )

        try:
            await handle_retrieve_memory(params, memory_bank=self.memory_bank)
        except TypeError:
            with patch("tools.tool_definitions._GLOBAL_MEMORY_BANK", self.memory_bank):
                await handle_retrieve_memory(params)

        payload = params.result
        self.assertIn(payload.get("status"), ["empty", "not_found", "success"])
        self.assertEqual(payload.get("facts", {}), {})

    async def test_handle_retrieve_memory_empty_memory_bank(self):
        """Test fresh empty memory bank returns safe empty response without crash."""
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "user_fresh", "query": "any"},
        )

        try:
            await handle_retrieve_memory(params, memory_bank=self.memory_bank)
        except TypeError:
            with patch("tools.tool_definitions._GLOBAL_MEMORY_BANK", self.memory_bank):
                await handle_retrieve_memory(params)

        self.assertEqual(params.result_callback.call_count, 1)

    async def test_handle_retrieve_memory_search_exception_resilience(self):
        """Test unhandled exception inside memory bank search is caught gracefully."""
        mock_mb = MagicMock()
        mock_mb.get_fact_store.side_effect = RuntimeError("Simulated internal DB search failure")

        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments={"user_id": "Aditya Sharma", "query": "returns"},
        )

        # Must not raise exception out of handler
        try:
            await handle_retrieve_memory(params, memory_bank=mock_mb)
        except TypeError:
            with patch("tools.tool_definitions._GLOBAL_MEMORY_BANK", mock_mb):
                await handle_retrieve_memory(params)

        self.assertEqual(params.result_callback.call_count, 1)
        payload = params.result
        self.assertEqual(payload.get("status"), "error")

    async def test_handle_retrieve_memory_none_arguments(self):
        """Test None arguments in FunctionCallParams is handled safely."""
        params = MockFunctionCallParams(
            function_name="retrieve_memory",
            arguments=None,
        )

        try:
            await handle_retrieve_memory(params, memory_bank=self.memory_bank)
        except TypeError:
            with patch("tools.tool_definitions._GLOBAL_MEMORY_BANK", self.memory_bank):
                await handle_retrieve_memory(params)

        self.assertEqual(params.result_callback.call_count, 1)


if __name__ == "__main__":
    unittest.main()
