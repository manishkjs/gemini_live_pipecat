import unittest
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch
from memory_function import (
    save_user_memory_schema,
    search_user_memory_schema,
    save_user_memory_handler,
    search_user_memory_handler,
    get_memory_bank_config,
)

class TestMemoryFunction(unittest.IsolatedAsyncioTestCase):
    async def test_save_and_search_local_memory(self):
        test_file = os.path.join(os.path.dirname(__file__), "test_user_memories_tmp.json")
        if os.path.exists(test_file):
            os.remove(test_file)

        try:
            with patch("memory_function.get_memory_file_path", return_value=test_file):
                # Test saving memory
                mock_cb_save = AsyncMock()
                params_save = MagicMock()
                params_save.arguments = {
                    "memory_text": "User prefers a 12-month tenure for loan",
                    "category": "preference"
                }
                params_save.result_callback = mock_cb_save

                await save_user_memory_handler(params_save)
                mock_cb_save.assert_called_once()
                saved_res = mock_cb_save.call_args[0][0]
                self.assertIn("saved successfully", saved_res.get("content", "").lower())

                # Verify JSON file content
                self.assertTrue(os.path.exists(test_file))
                with open(test_file, "r") as f:
                    data = json.load(f)
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["memory_text"], "User prefers a 12-month tenure for loan")

                # Test searching memory
                mock_cb_search = AsyncMock()
                params_search = MagicMock()
                params_search.arguments = {"query": "tenure"}
                params_search.result_callback = mock_cb_search

                await search_user_memory_handler(params_search)
                mock_cb_search.assert_called_once()
                search_res = mock_cb_search.call_args[0][0]
                self.assertIn("12-month tenure", search_res.get("content", ""))

        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

    async def test_empty_memory_text_validation(self):
        mock_cb = AsyncMock()
        params = MagicMock()
        params.arguments = {"memory_text": ""}
        params.result_callback = mock_cb

        await save_user_memory_handler(params)
        mock_cb.assert_called_once()
        res = mock_cb.call_args[0][0]
        self.assertIn("cannot be empty", res.get("content", "").lower())

    async def test_memory_bank_api_save_success(self):
        mock_cb = AsyncMock()
        params = MagicMock()
        params.arguments = {"memory_text": "User lives in Bangalore", "category": "location"}
        params.result_callback = mock_cb

        mock_post = MagicMock()
        mock_post.json.return_value = {"name": "projects/p/locations/l/reasoningEngines/r/memories/m1"}
        mock_post.raise_for_status.return_value = None

        with patch("memory_function.get_memory_bank_config", return_value=("projects/p/locations/l/reasoningEngines/r", "p", "l")):
            with patch("google.auth.default", return_value=(MagicMock(token="fake_token"), "p")):
                with patch("requests.post", return_value=mock_post) as mock_requests_post:
                    await save_user_memory_handler(params)
                    mock_cb.assert_called_once()
                    self.assertIn("memory bank", mock_cb.call_args[0][0]["content"].lower())
                    mock_requests_post.assert_called_once()

    async def test_memory_bank_api_search_success(self):
        mock_cb = AsyncMock()
        params = MagicMock()
        params.arguments = {"query": "location"}
        params.result_callback = mock_cb

        mock_post = MagicMock()
        mock_post.json.return_value = {
            "memories": [{"fact": "User lives in Bangalore"}]
        }
        mock_post.raise_for_status.return_value = None

        with patch("memory_function.get_memory_bank_config", return_value=("projects/p/locations/l/reasoningEngines/r", "p", "l")):
            with patch("google.auth.default", return_value=(MagicMock(token="fake_token"), "p")):
                with patch("requests.post", return_value=mock_post):
                    await search_user_memory_handler(params)
                    mock_cb.assert_called_once()
                    self.assertIn("Bangalore", mock_cb.call_args[0][0]["content"])

if __name__ == "__main__":
    unittest.main()
