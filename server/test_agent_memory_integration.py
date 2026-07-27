import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from memory_function import (
    save_user_memory_schema,
    search_user_memory_schema,
    save_user_memory_handler,
    search_user_memory_handler,
)

class TestAgentMemoryIntegration(unittest.IsolatedAsyncioTestCase):
    def test_tools_schema_includes_memory_tools(self):
        tools = ToolsSchema(
            standard_tools=[
                save_user_memory_schema,
                search_user_memory_schema,
            ]
        )
        tool_names = [t.name for t in tools.standard_tools]
        self.assertIn("save_user_memory", tool_names)
        self.assertIn("search_user_memory", tool_names)

    @patch("memory_function.get_mem0_instance")
    async def test_save_user_memory_handler_integration(self, mock_get_mem0):
        mock_mem0 = MagicMock()
        mock_get_mem0.return_value = mock_mem0
        mock_mem0.search.return_value = {"results": []}
        mock_mem0.add.return_value = {"results": [{"id": "test-1"}]}

        mock_cb = AsyncMock()
        params = MagicMock()
        params.arguments = {"memory_text": "User wants 6 months tenure"}
        params.result_callback = mock_cb

        await save_user_memory_handler(params)
        mock_cb.assert_called_once()
        self.assertIn("saved successfully", mock_cb.call_args[0][0]["content"].lower())

if __name__ == "__main__":
    unittest.main()
