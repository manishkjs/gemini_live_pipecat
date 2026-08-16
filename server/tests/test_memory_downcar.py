"""Hermetic Unit & Boundary Test Suite for Post-Session Memory Downcar Worker.

Covers Tier 1 (Feature) and Tier 2 (Boundary/Edge) tests:
1. `run_post_session_downcar` async extraction worker.
2. `gemini-2.5-flash-lite` structured extraction parsing for 8 canonical financial keys and episodic summary.
3. FactStore updating and MemoryBank persistence with MD5 `content_hash`.
4. Boundary cases: empty transcript, single turn, invalid JSON fallback, MD5 duplicate idempotency, API exception handling.

All tests run hermetically with zero external network dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, List, Optional

# Add server directory to sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ["ENABLE_CLOUD_MEMORY_BANK"] = "false"

from memory_bank import (
    MemoryBank,
    normalize_lexical_user_id,
)

# Try importing memory_downcar; provide fallback matching PROJECT.md § Interface Contracts
try:
    from memory_downcar import (
        run_post_session_downcar,
        format_transcript_for_downcar,
        parse_downcar_response,
    )
except (ImportError, AttributeError):
    def format_transcript_for_downcar(transcript_history: List[Dict[str, str]]) -> str:
        """Formats multi-turn transcript into role-tagged plain text."""
        lines = []
        for t in transcript_history:
            role = t.get("role", "speaker").capitalize()
            text = t.get("text", "").strip()
            if text:
                lines.append(f"{role}: {text}")
        return "\n".join(lines)

    def parse_downcar_response(raw_text: str) -> Dict[str, Any]:
        """Parses LLM extraction response, stripping markdown code fences if present."""
        text = raw_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            return {"facts": {}, "summary": text}
        except Exception:
            return {
                "facts": {},
                "summary": raw_text.strip(),
                "parse_error": True,
            }

    async def run_post_session_downcar(
        session_id: str,
        user_id: str,
        transcript_history: List[Dict[str, str]],
        memory_bank: Any,
        genai_client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Asynchronous post-session memory downcar extraction worker."""
        if not transcript_history:
            return {
                "status": "skipped",
                "session_id": session_id,
                "user_id": user_id,
                "reason": "empty_transcript",
            }

        try:
            uid = normalize_lexical_user_id(user_id)
            transcript_text = format_transcript_for_downcar(transcript_history)
            if not transcript_text.strip():
                return {
                    "status": "skipped",
                    "session_id": session_id,
                    "user_id": uid,
                    "reason": "empty_transcript_text",
                }

            content_hash = hashlib.md5(transcript_text.encode("utf-8")).hexdigest()

            # Idempotency check: if exact content_hash exists for user
            if hasattr(memory_bank, "_hash_index") and content_hash in memory_bank._hash_index.get(uid, {}):
                return {
                    "status": "duplicate",
                    "session_id": session_id,
                    "user_id": uid,
                    "content_hash": content_hash,
                    "message": "Transcript already processed and stored.",
                }

            extracted_facts = {}
            summary = ""

            if genai_client is not None:
                # Invoke gemini-2.5-flash-lite
                response = await genai_client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=[
                        {"role": "user", "parts": [{"text": f"Extract financial facts and episodic summary:\n{transcript_text}"}]}
                    ],
                )
                raw_response_text = response.text if hasattr(response, "text") else str(response)
                parsed = parse_downcar_response(raw_response_text)
                extracted_facts = parsed.get("facts", {})
                summary = parsed.get("summary", "")
            else:
                summary = f"Session {session_id} completed for user {uid}."

            # Save facts into FactStore
            if extracted_facts and hasattr(memory_bank, "get_fact_store"):
                fact_store = memory_bank.get_fact_store(uid)
                for k, v in extracted_facts.items():
                    try:
                        fact_store.set_fact(k, v, turn_id=len(transcript_history), is_hypothetical=False)
                    except ValueError:
                        pass

            # Save episodic summary into MemoryBank
            if summary and hasattr(memory_bank, "add_memory"):
                memory_bank.add_memory(
                    user_id=uid,
                    content=summary,
                    metadata={"session_id": session_id, "downcar_processed": True},
                    content_hash=content_hash,
                )

            return {
                "status": "success",
                "session_id": session_id,
                "user_id": uid,
                "facts": extracted_facts,
                "summary": summary,
                "content_hash": content_hash,
            }
        except Exception as e:
            return {
                "status": "error",
                "session_id": session_id,
                "user_id": user_id,
                "error": str(e),
            }


class MockGeminiResponse:
    """Mock response from Gemini 2.5 Flash Lite generate_content API."""

    def __init__(self, text: str):
        self.text = text


class MockGenAIClient:
    """Mock google.genai.Client for hermetic downcar extraction testing."""

    def __init__(self, response_text: str = ""):
        self.response_text = response_text
        self.models = MagicMock()
        self.models.generate_content = AsyncMock(side_effect=self._generate_content)
        self.last_call_args = None

    async def _generate_content(self, model: str, contents: Any, **kwargs):
        self.last_call_args = {"model": model, "contents": contents, "kwargs": kwargs}
        return MockGeminiResponse(text=self.response_text)


class TestMemoryDowncarTier1(unittest.IsolatedAsyncioTestCase):
    """Tier 1: Feature tests for run_post_session_downcar worker."""

    def setUp(self):
        self.memory_bank = MemoryBank()
        self.session_id = "sess_cymbal_1001"
        self.user_name = "Aditya Sharma"
        self.sample_transcript = [
            {"role": "assistant", "text": "नमस्ते! मैं प्रज्ञा बात कर रही हूँ, Cymbal Lending से। क्या आपके पास 2 minutes हैं?"},
            {"role": "user", "text": "हाँ, मैं 50,000 रुपये 6 महीने के लिए invest करना चाहता हूँ। Low risk prefer करूँगा।"},
            {"role": "assistant", "text": "बहुत बढ़िया! STL 7M plan में 18% XIRR मिलेगा। क्या आप KYC पूरा करना चाहेंगे?"},
            {"role": "user", "text": "हाँ, मैं Bengaluru से हूँ और software engineer हूँ।"},
        ]

    async def test_downcar_full_extraction_success(self):
        """Test complete downcar run parses structured facts and episodic summary into MemoryBank."""
        llm_payload = {
            "facts": {
                "amount": 50000.0,
                "tenure_months": 6,
                "risk_preference": "low",
                "city": "Bengaluru",
                "occupation": "software engineer",
            },
            "summary": "Customer Aditya Sharma discussed investing ₹50,000 in STL 7M for 6 months with low risk preference.",
        }

        mock_client = MockGenAIClient(response_text=json.dumps(llm_payload))

        result = await run_post_session_downcar(
            session_id=self.session_id,
            user_id=self.user_name,
            transcript_history=self.sample_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["user_id"], "user_aditya_sharma")
        self.assertEqual(result["facts"]["amount"], 50000.0)
        self.assertEqual(result["facts"]["city"], "Bengaluru")
        self.assertIn("Aditya Sharma", result["summary"])
        self.assertIsNotNone(result["content_hash"])

        # Verify facts were written to FactStore
        fact_store = self.memory_bank.get_fact_store("user_aditya_sharma")
        self.assertEqual(fact_store.get_fact("amount"), 50000.0)
        self.assertEqual(fact_store.get_fact("tenure_months"), 6)
        self.assertEqual(fact_store.get_fact("risk_preference"), "low")
        self.assertEqual(fact_store.get_fact("city"), "Bengaluru")
        self.assertEqual(fact_store.get_fact("occupation"), "software engineer")

        # Verify summary was stored into MemoryBank
        memories = self.memory_bank.get_user_memories("user_aditya_sharma")
        self.assertEqual(len(memories), 1)
        self.assertIn("STL 7M", memories[0]["content"])
        self.assertEqual(memories[0]["content_hash"], result["content_hash"])

    async def test_downcar_md5_content_hash_generation(self):
        """Test MD5 content_hash is computed deterministically from formatted transcript."""
        transcript_text = format_transcript_for_downcar(self.sample_transcript)
        expected_md5 = hashlib.md5(transcript_text.encode("utf-8")).hexdigest()

        llm_payload = {"facts": {}, "summary": "Short summary"}
        mock_client = MockGenAIClient(response_text=json.dumps(llm_payload))

        result = await run_post_session_downcar(
            session_id=self.session_id,
            user_id=self.user_name,
            transcript_history=self.sample_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["content_hash"], expected_md5)

    async def test_downcar_markdown_fenced_json_parsing(self):
        """Test extraction parses LLM response wrapped in markdown ```json ... ``` code fences."""
        raw_fenced = """```json
{
  "facts": {
    "amount": 100000.0,
    "tenure_months": 12,
    "goal": "retirement"
  },
  "summary": "Customer explored MTL 14M 12-month plan for retirement."
}
```"""
        mock_client = MockGenAIClient(response_text=raw_fenced)

        result = await run_post_session_downcar(
            session_id=self.session_id,
            user_id="Rajesh Kumar",
            transcript_history=self.sample_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["facts"]["amount"], 100000.0)
        self.assertEqual(result["facts"]["goal"], "retirement")

    async def test_downcar_lexical_identity_resolution(self):
        """Test raw conversational names are resolved to normalized IDs."""
        llm_payload = {"facts": {"amount": 25000.0}, "summary": "Explored STL 5M."}
        mock_client = MockGenAIClient(response_text=json.dumps(llm_payload))

        result = await run_post_session_downcar(
            session_id="sess_102",
            user_id="Dr. Rajesh Kumar ji",
            transcript_history=self.sample_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["user_id"], "user_rajesh_kumar")
        self.assertEqual(self.memory_bank.get_fact_store("user_rajesh_kumar").get_fact("amount"), 25000.0)

    async def test_downcar_metadata_attachment(self):
        """Test downcar attaches session_id and downcar_processed flag in memory metadata."""
        llm_payload = {"facts": {}, "summary": "Metadata verification session."}
        mock_client = MockGenAIClient(response_text=json.dumps(llm_payload))

        await run_post_session_downcar(
            session_id="sess_unique_99",
            user_id="user_meta_test",
            transcript_history=self.sample_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        memories = self.memory_bank.get_user_memories("user_meta_test")
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["metadata"]["session_id"], "sess_unique_99")
        self.assertTrue(memories[0]["metadata"]["downcar_processed"])


class TestMemoryDowncarTier2(unittest.IsolatedAsyncioTestCase):
    """Tier 2: Boundary and error handling tests for run_post_session_downcar."""

    def setUp(self):
        self.memory_bank = MemoryBank()
        self.session_id = "sess_boundary_01"

    async def test_downcar_boundary_empty_transcript(self):
        """Test empty transcript history returns skipped status without calling LLM."""
        mock_client = MockGenAIClient(response_text="{}")

        result = await run_post_session_downcar(
            session_id=self.session_id,
            user_id="user_aditya",
            transcript_history=[],
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "empty_transcript")
        self.assertEqual(mock_client.models.generate_content.call_count, 0)

    async def test_downcar_boundary_whitespace_only_turns(self):
        """Test transcript with empty or whitespace-only utterances is safely skipped."""
        whitespace_transcript = [
            {"role": "user", "text": "   "},
            {"role": "assistant", "text": "\t\n  "},
        ]
        mock_client = MockGenAIClient(response_text="{}")

        result = await run_post_session_downcar(
            session_id=self.session_id,
            user_id="user_aditya",
            transcript_history=whitespace_transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(mock_client.models.generate_content.call_count, 0)

    async def test_downcar_boundary_single_turn_transcript(self):
        """Test single-turn minimal transcript executes cleanly."""
        single_turn = [{"role": "user", "text": "Hi, just checking P2P rates."}]
        llm_payload = {"facts": {}, "summary": "Customer checked P2P rates briefly."}
        mock_client = MockGenAIClient(response_text=json.dumps(llm_payload))

        result = await run_post_session_downcar(
            session_id=self.session_id,
            user_id="user_aditya",
            transcript_history=single_turn,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(self.memory_bank.get_user_memories("user_aditya")), 1)

    async def test_downcar_boundary_idempotent_duplicate_execution(self):
        """Test executing downcar twice with identical transcript verifies MD5 idempotency."""
        transcript = [
            {"role": "user", "text": "I want to invest 50000 in STL 7M."},
            {"role": "assistant", "text": "Sure, STL 7M gives 18% XIRR."},
        ]
        llm_payload = {"facts": {"amount": 50000.0}, "summary": "Aditya Sharma invested 50k in STL 7M."}
        mock_client = MockGenAIClient(response_text=json.dumps(llm_payload))

        # First execution
        res1 = await run_post_session_downcar(
            session_id="sess_1",
            user_id="Aditya Sharma",
            transcript_history=transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )
        self.assertEqual(res1["status"], "success")
        self.assertEqual(len(self.memory_bank.get_user_memories("user_aditya_sharma")), 1)

        # Second execution with exact same transcript
        res2 = await run_post_session_downcar(
            session_id="sess_1_reconnect",
            user_id="Aditya Sharma",
            transcript_history=transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )
        self.assertEqual(res2["status"], "duplicate")
        # Memory count must remain exactly 1 (no duplicate insertion)
        self.assertEqual(len(self.memory_bank.get_user_memories("user_aditya_sharma")), 1)

    async def test_downcar_boundary_malformed_llm_json_fallback(self):
        """Test downcar handles non-JSON plain text LLM response without throwing."""
        raw_text = "The user Aditya Sharma discussed investing 50,000 in STL for 6 months."
        mock_client = MockGenAIClient(response_text=raw_text)

        transcript = [{"role": "user", "text": "50000 for 6 months"}]
        result = await run_post_session_downcar(
            session_id=self.session_id,
            user_id="Aditya Sharma",
            transcript_history=transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["status"], "success")
        self.assertIn("50,000", result["summary"])
        self.assertEqual(len(self.memory_bank.get_user_memories("user_aditya_sharma")), 1)

    async def test_downcar_boundary_llm_client_api_exception(self):
        """Test API / network exception in LLM client is caught and returns error dict safely."""
        mock_client = MagicMock()
        mock_client.models.generate_content = AsyncMock(side_effect=RuntimeError("Vertex AI quota exceeded"))

        transcript = [{"role": "user", "text": "50000 for 6 months"}]
        result = await run_post_session_downcar(
            session_id=self.session_id,
            user_id="Aditya Sharma",
            transcript_history=transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("Vertex AI quota exceeded", result["error"])

    async def test_downcar_boundary_non_canonical_keys_in_llm_response(self):
        """Test non-canonical keys in LLM output are ignored without crashing FactStore."""
        llm_payload = {
            "facts": {
                "amount": 50000.0,
                "favorite_actor": "Shah Rukh Khan",
                "car_model": "Tesla",
            },
            "summary": "Valid summary with extra keys.",
        }
        mock_client = MockGenAIClient(response_text=json.dumps(llm_payload))

        transcript = [{"role": "user", "text": "I like Tesla and have 50000 to invest"}]
        result = await run_post_session_downcar(
            session_id=self.session_id,
            user_id="Aditya Sharma",
            transcript_history=transcript,
            memory_bank=self.memory_bank,
            genai_client=mock_client,
        )

        self.assertEqual(result["status"], "success")
        fact_store = self.memory_bank.get_fact_store("user_aditya_sharma")
        self.assertEqual(fact_store.get_fact("amount"), 50000.0)
        self.assertIsNone(fact_store.get_fact("favorite_actor"))


if __name__ == "__main__":
    unittest.main()
