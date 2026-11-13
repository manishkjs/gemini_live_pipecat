"""Offline unit tests for Vertex AI RAG REST retrieval in rag_function.py."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import rag_function


class TestRagFunctionRest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        rag_function._rag_http_session = None
        rag_function._vertex_initialized = False

    def tearDown(self) -> None:
        rag_function._rag_http_session = None
        rag_function._vertex_initialized = False

    async def test_retrieve_contexts_rest_pools_session_parses_answers_and_dedupes(self) -> None:
        fake_response = mock.MagicMock()
        fake_response.json.return_value = {
            "contexts": {
                "contexts": [
                    {"text": "Question: Late fee?\nAnswer: ₹250 flat bounce charge."},
                    {"text": "Question: Duplicate?\nAnswer: ₹250 flat bounce charge."},
                    {"text": "Prepayment penalty is zero on floating rate loans."},
                    {"text": ""},
                ]
            }
        }
        fake_session = mock.MagicMock()
        fake_session.post.return_value = fake_response

        corpus_id = "projects/test-proj/locations/asia-south1/ragCorpora/998877"
        results: list[dict] = []

        async def capture_result(payload: dict) -> None:
            results.append(payload)

        params = SimpleNamespace(
            arguments={"query_for_vector_search": "bounce fee policy", "total_records": 4},
            result_callback=capture_result,
        )

        with mock.patch.dict(
            "os.environ",
            {"RAG_CORPUS_RESOURCE_ID": corpus_id, "GCP_PROJECT_ID": "test-proj"},
            clear=False,
        ), mock.patch.object(rag_function, "rag", None), mock.patch.object(
            rag_function, "vertexai", None
        ), mock.patch.object(
            rag_function.google.auth,
            "default",
            return_value=(mock.sentinel.creds, "test-proj"),
        ) as auth_mock, mock.patch.object(
            rag_function, "AuthorizedSession", return_value=fake_session
        ) as session_cls_mock:
            await rag_function.search_knowledge_base_handler(params)  # type: ignore[arg-type]
            await rag_function.search_knowledge_base_handler(params)  # type: ignore[arg-type]

        # Pooled AuthorizedSession is initialized only once across multiple RAG tool calls.
        self.assertEqual(auth_mock.call_count, 1)
        self.assertEqual(session_cls_mock.call_count, 1)
        self.assertEqual(fake_session.post.call_count, 2)

        called_url = fake_session.post.call_args.args[0]
        called_json = fake_session.post.call_args.kwargs["json"]
        self.assertEqual(
            called_url,
            "https://asia-south1-aiplatform.googleapis.com/v1beta1/"
            "projects/test-proj/locations/asia-south1:retrieveContexts",
        )
        self.assertEqual(
            called_json,
            {
                "vertexRagStore": {"ragResources": [{"ragCorpus": corpus_id}]},
                "query": {"text": "bounce fee policy", "similarityTopK": 4},
            },
        )
        self.assertEqual(
            results[0]["content"],
            "1. ₹250 flat bounce charge.\n\n2. Prepayment penalty is zero on floating rate loans.",
        )

    async def test_retrieve_contexts_rest_handles_http_error_gracefully(self) -> None:
        fake_session = mock.MagicMock()
        fake_session.post.side_effect = RuntimeError("503 upstream unavailable")
        results: list[dict] = []

        async def capture_result(payload: dict) -> None:
            results.append(payload)

        params = SimpleNamespace(
            arguments={"query_for_vector_search": "policy", "total_records": 3},
            result_callback=capture_result,
        )
        with mock.patch.dict(
            "os.environ",
            {
                "RAG_CORPUS_RESOURCE_ID": "projects/p/locations/us-central1/ragCorpora/1",
                "GCP_PROJECT_ID": "p",
            },
            clear=False,
        ), mock.patch.object(rag_function, "rag", None), mock.patch.object(
            rag_function, "vertexai", None
        ), mock.patch.object(rag_function, "_rag_http_session", fake_session):
            await rag_function.search_knowledge_base_handler(params)  # type: ignore[arg-type]

        self.assertEqual(
            results[0]["content"],
            "Knowledge base search failed. Please try again.",
        )


if __name__ == "__main__":
    unittest.main()
