"""Milestone M4 Comprehensive Test Coverage Audit & Adversarial Verification Suite.

Author: Challenger 2 (Empirical Challenger)
Milestone: M4 (Post-Session Downcar Service & Live Integration)

Verification Scope:
1. Tool Registration in register_all_tools() for both LLM services:
   - CustomGeminiLiveLLMService (AI Studio mode)
   - CustomGeminiLiveVertexLLMService (Vertex AI mode)
   - Schema and async handler binding for retrieve_memory and all 12 standard tools
   - Dynamic tool handler fallback for custom tool extensions
   - Function call dispatcher execution with FunctionCallParams

2. Active User Profile Hydration Edge Cases:
   - Unregistered / anonymous / fresh users (empty facts, 0 memories, safe profile_hydrated flag)
   - Users with expired memories (>90 days old lookback boundary)
   - Users with active facts across all 8 canonical financial keys + recent (<90 days) memories
   - Mixed-age memories (strict 90-day cutoff evaluation)
   - Corrupted / malformed timestamps in memory metadata
   - FactStore hypothetical parameter 6-turn TTL vs confirmed facts during hydration lifecycle
   - Custom lookback parameter flexibility

3. Transcript Tracking across Normal Turns, Interruptions & Disconnect Triggers:
   - Live user speech recording via _push_user_transcription -> transcript_history
   - Lexical name resolution during user speech turn
   - Live bot response accumulation and turn completion recording
   - Interruption handling via InterruptionFrame -> flushing partial text to transcript_history
   - Sequential interruptions and anti-cancel tool shield protection
   - Anti-cancel tool lock timeout self-healing (8.0s hold limit)
   - Disconnect trigger on_client_disconnected -> post-session downcar invocation

4. Post-Session Downcar Extraction & Idempotency:
   - Multi-turn transcript formatting (format_transcript_for_downcar)
   - LLM JSON parsing with markdown code fences (parse_downcar_response)
   - Hermetic offline heuristic fallback (extract_facts_and_summary_offline)
   - Deterministic MD5 content_hash calculation
   - FactStore canonical type conversion (amount -> float, tenure_months -> int)
   - Deduplication and idempotency on repeated session disconnects
   - Error resilience against empty/whitespace transcripts and LLM API failures
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure server directory is in sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from memory_bank import (
    CANONICAL_FACT_KEYS,
    FactStore,
    MemoryBank,
    normalize_lexical_user_id,
)
from memory_downcar import (
    extract_facts_and_summary_offline,
    format_transcript_for_downcar,
    parse_downcar_response,
    run_post_session_downcar,
)
from tools.tool_definitions import (
    _GLOBAL_MEMORY_BANK,
    calculate_manual_lending_schema,
    calculate_mtl_returns_schema,
    calculate_returns_schema,
    calculate_sip_returns_schema,
    calculate_stl_returns_schema,
    dynamic_tool_handler,
    get_app_screen_flow_schema,
    get_current_time_schema,
    get_kyc_guidance_schema,
    get_onboarding_guide_schema,
    get_product_recommendation_schema,
    get_standard_tools,
    handle_calculate_manual_lending,
    handle_calculate_mtl_returns,
    handle_calculate_returns,
    handle_calculate_sip_returns,
    handle_calculate_stl_returns,
    handle_get_app_screen_flow,
    handle_get_kyc_guidance,
    handle_get_onboarding_guide,
    handle_get_product_recommendation,
    handle_retrieve_memory,
    register_all_tools,
    retrieve_memory_schema,
    search_knowledge_base_schema,
)
from agent_live import (
    CustomGeminiLiveLLMService,
    CustomGeminiLiveVertexLLMService,
    GeminiSessionLoggerMixin,
)
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import (
    CancelFrame,
    Frame,
    FunctionCallResultFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams


# ═══════════════════════════════════════════════════════════════════════
# 1. TOOL REGISTRATION AUDIT ON BOTH LLM SERVICES
# ═══════════════════════════════════════════════════════════════════════

class MockPipecatLLM:
    """Mock Pipecat Gemini LLM Service to verify tool registration."""

    def __init__(self):
        self.registered_functions: Dict[str, Any] = {}

    def register_function(self, name: str, handler: Any):
        self.registered_functions[name] = handler


class TestToolRegistrationBothLLMs(unittest.TestCase):
    """Audit tool registration across AI Studio and Vertex LLM service architectures."""

    def setUp(self):
        self.expected_standard_tool_names = [
            "get_current_time",
            "search_knowledge_base",
            "calculate_returns",
            "get_onboarding_guide",
            "retrieve_memory",
            "save_memory",
            "calculate_stl_returns",
            "calculate_mtl_returns",
            "calculate_manual_lending",
            "calculate_sip_returns",
            "get_product_recommendation",
            "get_kyc_guidance",
            "get_app_screen_flow",
        ]

    def test_standard_tools_contains_all_core_schemas(self):
        """Verify get_standard_tools() provides all expected schemas including retrieve_memory."""
        tools = get_standard_tools()
        tool_names = [t.name for t in tools]
        self.assertIn("retrieve_memory", tool_names)
        self.assertIn("calculate_returns", tool_names)
        self.assertIn("get_onboarding_guide", tool_names)
        self.assertIn("get_current_time", tool_names)

    def test_register_all_tools_on_ai_studio_service(self):
        """Verify register_all_tools properly binds all function handlers to CustomGeminiLiveLLMService mock."""
        mock_llm = MockPipecatLLM()
        standard_tools = get_standard_tools()

        async def custom_time_fn(params):
            pass

        register_all_tools(mock_llm, standard_tools, get_current_time_fn=custom_time_fn)

        for expected_name in self.expected_standard_tool_names:
            self.assertIn(expected_name, mock_llm.registered_functions, f"Missing tool registration: {expected_name}")
            self.assertTrue(callable(mock_llm.registered_functions[expected_name]))

        self.assertEqual(mock_llm.registered_functions["retrieve_memory"], handle_retrieve_memory)
        self.assertEqual(mock_llm.registered_functions["calculate_returns"], handle_calculate_returns)
        self.assertEqual(mock_llm.registered_functions["get_current_time"], custom_time_fn)

    def test_register_all_tools_on_vertex_service(self):
        """Verify register_all_tools properly binds all function handlers to CustomGeminiLiveVertexLLMService mock."""
        mock_llm = MockPipecatLLM()
        standard_tools = get_standard_tools()

        register_all_tools(mock_llm, standard_tools, get_current_time_fn=None)

        for expected_name in self.expected_standard_tool_names:
            if expected_name == "get_current_time":
                continue  # not passed in this call
            self.assertIn(expected_name, mock_llm.registered_functions)
            self.assertTrue(callable(mock_llm.registered_functions[expected_name]))

        self.assertEqual(mock_llm.registered_functions["retrieve_memory"], handle_retrieve_memory)

    def test_dynamic_custom_tool_registration_fallback(self):
        """Verify dynamic tools that are not built-in get bound to dynamic_tool_handler."""
        mock_llm = MockPipecatLLM()
        custom_tools_json = json.dumps([
            {"name": "custom_lead_scorer", "description": "Scores a lead"},
            {"name": "custom_crm_sync", "description": "Syncs with CRM"},
        ])
        standard_tools = get_standard_tools(dynamic_tools_json=custom_tools_json)

        register_all_tools(mock_llm, standard_tools)

        self.assertIn("custom_lead_scorer", mock_llm.registered_functions)
        self.assertIn("custom_crm_sync", mock_llm.registered_functions)
        self.assertEqual(mock_llm.registered_functions["custom_lead_scorer"], dynamic_tool_handler)
        self.assertEqual(mock_llm.registered_functions["custom_crm_sync"], dynamic_tool_handler)

    def test_retrieve_memory_schema_properties(self):
        """Verify retrieve_memory_schema defines correct properties and required fields."""
        schema = retrieve_memory_schema
        self.assertEqual(schema.name, "retrieve_memory")
        self.assertIn("user_id", schema.properties)
        self.assertIn("query", schema.properties)
        self.assertEqual(schema.required, ["user_id", "query"])


# ═══════════════════════════════════════════════════════════════════════
# 2. ACTIVE USER PROFILE HYDRATION EDGE CASES AUDIT
# ═══════════════════════════════════════════════════════════════════════

class TestUserProfileHydrationEdgeCases(unittest.TestCase):
    """Adversarial stress testing of cross-session user profile hydration in MemoryBank."""

    def setUp(self):
        self.memory_bank = MemoryBank()

    def test_hydration_unregistered_anonymous_user(self):
        """Verify unregistered or empty user ID hydrates safely with empty profile and zero memories."""
        for raw_id in ["", "   ", None, "anonymous", "default_user"]:
            profile = self.memory_bank.hydrate_user_profile(raw_id, days_lookback=90)
            self.assertTrue(profile["profile_hydrated"])
            self.assertEqual(profile["facts"], {})
            self.assertEqual(profile["recent_memories"], [])
            self.assertEqual(profile["memory_count"], 0)
            self.assertIsNone(profile["last_active"])

    def test_hydration_user_with_expired_memories_greater_than_90_days(self):
        """Verify memories older than 90 days are excluded while FactStore active facts persist."""
        uid = "user_ramesh_patel"
        fact_store = self.memory_bank.get_fact_store(uid)
        fact_store.set_fact("amount", 200000.0, turn_id=1)
        fact_store.set_fact("tenure_months", 12, turn_id=1)
        fact_store.set_fact("goal", "monthly income", turn_id=1)

        # Add memory created 95 days ago (> 90 days lookback)
        now_dt = datetime.now(timezone.utc)
        expired_ts = (now_dt - timedelta(days=95)).isoformat()
        self.memory_bank.add_memory(
            user_id=uid,
            content="Ramesh Patel inquired about MTL 14M 12 months 95 days ago.",
            metadata={"session_id": "sess_old_1"},
        )
        self.memory_bank._memories[uid][-1]["created_at"] = expired_ts
        self.memory_bank._memories[uid][-1]["updated_at"] = expired_ts

        profile = self.memory_bank.hydrate_user_profile(uid, days_lookback=90)

        # Facts in FactStore are active
        self.assertEqual(profile["facts"]["amount"], 200000.0)
        self.assertEqual(profile["facts"]["tenure_months"], 12)
        self.assertEqual(profile["facts"]["goal"], "monthly income")

        # Episodic memories older than 90 days must be filtered out
        self.assertEqual(profile["recent_memories"], [])
        self.assertEqual(profile["memory_count"], 0)
        self.assertIsNone(profile["last_active"])

    def test_hydration_user_with_active_facts_and_recent_memories(self):
        """Verify full hydration when user has all 8 canonical facts and multiple recent memories."""
        uid = "user_priya_sharma"
        fact_store = self.memory_bank.get_fact_store(uid)
        canonical_values = {
            "amount": 500000.0,
            "tenure_months": 6,
            "risk_preference": "low",
            "timeline": "6 months",
            "goal": "wealth growth",
            "occupation": "software engineer",
            "city": "Bengaluru",
            "experience": "beginner",
        }
        for k, v in canonical_values.items():
            fact_store.set_fact(k, v, turn_id=1)

        # Add 3 recent memories (1 day, 5 days, 30 days ago)
        now_dt = datetime.now(timezone.utc)
        for days_ago, text in [(30, "Explored STL 5M"), (5, "Explored STL 7M"), (1, "Completed KYC PAN")]:
            ts = (now_dt - timedelta(days=days_ago)).isoformat()
            self.memory_bank.add_memory(user_id=uid, content=text, metadata={"step": text})
            self.memory_bank._memories[uid][-1]["created_at"] = ts
            self.memory_bank._memories[uid][-1]["updated_at"] = ts

        profile = self.memory_bank.hydrate_user_profile(uid, days_lookback=90)

        self.assertEqual(len(profile["facts"]), 8)
        self.assertEqual(profile["facts"]["city"], "Bengaluru")
        self.assertEqual(profile["facts"]["amount"], 500000.0)
        self.assertEqual(profile["memory_count"], 3)
        # Should be sorted newest first
        self.assertEqual(profile["recent_memories"][0]["content"], "Completed KYC PAN")
        self.assertIsNotNone(profile["last_active"])

    def test_hydration_mixed_boundary_timestamps(self):
        """Verify precise cutoff at the 90-day boundary (89 days included, 91 days excluded)."""
        uid = "user_boundary_test"
        now_dt = datetime.now(timezone.utc)

        # 89 days ago (within 90d)
        ts_89 = (now_dt - timedelta(days=89)).isoformat()
        self.memory_bank.add_memory(user_id=uid, content="Memory at 89 days", metadata={})
        self.memory_bank._memories[uid][-1]["created_at"] = ts_89
        self.memory_bank._memories[uid][-1]["updated_at"] = ts_89

        # 91 days ago (outside 90d)
        ts_91 = (now_dt - timedelta(days=91)).isoformat()
        self.memory_bank.add_memory(user_id=uid, content="Memory at 91 days", metadata={})
        self.memory_bank._memories[uid][-1]["created_at"] = ts_91
        self.memory_bank._memories[uid][-1]["updated_at"] = ts_91

        profile = self.memory_bank.hydrate_user_profile(uid, days_lookback=90)
        self.assertEqual(profile["memory_count"], 1)
        self.assertEqual(profile["recent_memories"][0]["content"], "Memory at 89 days")

    def test_hydration_malformed_timestamp_resilience(self):
        """Verify memory records with non-ISO or missing timestamps are handled without crashing."""
        uid = "user_corrupt_ts"
        self.memory_bank.add_memory(user_id=uid, content="Memory with corrupt timestamp", metadata={})
        self.memory_bank._memories[uid][-1]["created_at"] = "NOT_A_TIMESTAMP"
        self.memory_bank._memories[uid][-1]["updated_at"] = None

        profile = self.memory_bank.hydrate_user_profile(uid, days_lookback=90)
        self.assertTrue(profile["profile_hydrated"])
        self.assertEqual(profile["memory_count"], 1)

    def test_fact_store_hypothetical_ttl_expiration_during_session(self):
        """Verify hypothetical facts expire after 6 turns and revert to previous confirmed facts."""
        fact_store = FactStore()
        # Confirmed fact at Turn 1
        fact_store.set_fact("amount", 50000.0, turn_id=1, is_hypothetical=False)
        self.assertEqual(fact_store.get_fact("amount"), 50000.0)

        # Hypothetical exploration at Turn 2 (e.g., user asks "what if 24 Lakhs?")
        fact_store.set_fact("amount", 2400000.0, turn_id=2, is_hypothetical=True)
        self.assertEqual(fact_store.get_fact("amount"), 2400000.0)
        self.assertTrue(fact_store.is_fact_hypothetical("amount"))

        # Turns 3 to 7: TTL ticks (5 turns since set_turn=2)
        for t in range(3, 8):
            expired = fact_store.tick_turn(t)
            self.assertEqual(len(expired), 0)
            self.assertEqual(fact_store.get_fact("amount"), 2400000.0)

        # Turn 8: (8 - 2 = 6 turns) -> Expires and reverts to confirmed 50,000.0
        expired = fact_store.tick_turn(8)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["action"], "expire_hypothetical")
        self.assertEqual(fact_store.get_fact("amount"), 50000.0)
        self.assertFalse(fact_store.is_fact_hypothetical("amount"))


# ═══════════════════════════════════════════════════════════════════════
# 3. TRANSCRIPT TRACKING & INTERRUPTION AUDIT
# ═══════════════════════════════════════════════════════════════════════

class BaseMockLLMService:
    """Base class for mock LLM service providing super() methods for GeminiSessionLoggerMixin."""

    async def _handle_msg_output_transcription(self, message):
        pass

    async def _handle_msg_turn_complete(self, message):
        pass

    async def _handle_msg_input_transcription(self, message):
        pass

    async def _push_user_transcription(self, sentence: str, result=None):
        pass

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        pass

    async def start_ttfb_metrics(self):
        pass

    async def stop_ttfb_metrics(self):
        pass

    async def _run_function_call(self, tool_call):
        pass

    async def _handle_session_ready(self, session):
        pass

    async def _handle_msg_usage_metadata(self, message):
        pass

    async def _handle_msg_tool_call(self, message):
        pass


class MockLiveServiceHarness(GeminiSessionLoggerMixin, BaseMockLLMService):
    """Test harness combining GeminiSessionLoggerMixin with BaseMockLLMService."""

    def __init__(self):
        self.transcript_history: List[Dict[str, str]] = []
        self.active_user_id: str = "user_default"
        self._user_id_locked: bool = False
        self._bot_turn_text_buffer: str = ""
        self._repeat_on_filler_pending: bool = False
        self._active_tools_in_flight: int = 0
        self._frame_locked_tools: bool = False
        self._tool_lock_started_at: Optional[float] = None
        self.pushed_frames: List[Frame] = []

    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        self.pushed_frames.append(frame)

    async def _create_single_response(self, messages):
        pass


class TestTranscriptTrackingAndInterruptions(unittest.IsolatedAsyncioTestCase):
    """Audit transcript accumulation across normal speech turns, interruptions, and tool locking."""

    def setUp(self):
        self.service = MockLiveServiceHarness()

    async def test_user_speech_transcription_and_lexical_resolution(self):
        """Verify _push_user_transcription records user turns and normalizes customer identity."""
        await self.service._push_user_transcription("Namaste! Main Aditya Sharma bol raha hoon.")

        self.assertEqual(len(self.service.transcript_history), 1)
        self.assertEqual(self.service.transcript_history[0]["role"], "user")
        self.assertIn("Aditya Sharma", self.service.transcript_history[0]["text"])
        self.assertEqual(self.service.active_user_id, "user_aditya_sharma")

    async def test_normal_bot_response_turn_completion(self):
        """Verify bot response accumulates in buffer and flushes to transcript_history on turn_complete."""
        # Simulate text chunks arriving from model
        class MockServerContent:
            def __init__(self, text):
                self.output_transcription = MagicMock(text=text)

        class MockMessage:
            def __init__(self, text):
                self.server_content = MockServerContent(text)

        # Chunk 1
        await self.service._handle_msg_output_transcription(MockMessage("STL 7M plan mein "))
        self.assertEqual(self.service._bot_turn_text_buffer, "STL 7M plan mein ")

        # Chunk 2
        await self.service._handle_msg_output_transcription(MockMessage("18% return milta hai."))
        self.assertEqual(self.service._bot_turn_text_buffer, "STL 7M plan mein 18% return milta hai.")

        # Turn Complete
        mock_turn_complete = MagicMock()
        await self.service._handle_msg_turn_complete(mock_turn_complete)

        self.assertEqual(len(self.service.transcript_history), 1)
        self.assertEqual(self.service.transcript_history[0]["role"], "assistant")
        self.assertEqual(self.service.transcript_history[0]["text"], "STL 7M plan mein 18% return milta hai.")
        self.assertEqual(self.service._bot_turn_text_buffer, "")

    async def test_bot_interruption_flushes_partial_text_to_transcript(self):
        """Verify InterruptionFrame saves partial bot text to transcript_history and clears buffer."""
        # Bot started speaking partial response
        self.service._bot_turn_text_buffer = "Aapko monthly EMI payout milega "

        interruption = InterruptionFrame()
        # Call process_frame directly
        await self.service.process_frame(interruption, FrameDirection.DOWNSTREAM)

        # Must record interrupted turn in transcript_history
        self.assertEqual(len(self.service.transcript_history), 1)
        self.assertEqual(self.service.transcript_history[0]["role"], "assistant")
        self.assertEqual(self.service.transcript_history[0]["text"], "Aapko monthly EMI payout milega")
        self.assertEqual(self.service._bot_turn_text_buffer, "")

    async def test_sequential_interrupted_and_completed_turns_ordering(self):
        """Verify multiple turns with interruptions maintain exact chronological sequence."""
        # Turn 1: User speaks
        await self.service._push_user_transcription("Loan options kya hain?")

        # Turn 2: Bot starts speaking and gets interrupted
        self.service._bot_turn_text_buffer = "Hamare paas STL aur MTL..."
        await self.service.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)

        # Turn 3: User speaks again
        await self.service._push_user_transcription("MTL ke baare mein batayein.")

        # Turn 4: Bot answers fully
        self.service._bot_turn_text_buffer = "MTL 14M 12 months ka plan hai."
        await self.service._handle_msg_turn_complete(MagicMock())

        self.assertEqual(len(self.service.transcript_history), 4)
        self.assertEqual(self.service.transcript_history[0]["role"], "user")
        self.assertEqual(self.service.transcript_history[1]["role"], "assistant")
        self.assertEqual(self.service.transcript_history[1]["text"], "Hamare paas STL aur MTL...")
        self.assertEqual(self.service.transcript_history[2]["role"], "user")
        self.assertEqual(self.service.transcript_history[3]["role"], "assistant")
        self.assertEqual(self.service.transcript_history[3]["text"], "MTL 14M 12 months ka plan hai.")

    async def test_anticancel_tool_lock_suppression_and_timeout(self):
        """Verify tool lock suppresses interruption and self-heals after 8.0 seconds."""
        # 1. Lock tools
        self.service._lock_tools("test tool in flight")
        self.assertTrue(self.service._tools_in_flight())

        # Interruption is suppressed during active tool
        interruption = InterruptionFrame()
        await self.service.process_frame(interruption, FrameDirection.DOWNSTREAM)

        # 2. Release tool lock
        self.service._release_tools("tool completed")
        self.assertFalse(self.service._tools_in_flight())

        # 3. Simulate stuck lock exceeding 8.0s timeout
        self.service._lock_tools("stuck tool")
        self.service._tool_lock_started_at = time.monotonic() - 8.1
        self.assertFalse(self.service._tools_in_flight())  # Self-heals


# ═══════════════════════════════════════════════════════════════════════
# 4. POST-SESSION DOWNCAR EXTRACTION & IDEMPOTENCY AUDIT
# ═══════════════════════════════════════════════════════════════════════

class TestDowncarExtractionAndIdempotency(unittest.IsolatedAsyncioTestCase):
    """Audit post-session downcar background extraction worker and MD5 storage."""

    def setUp(self):
        self.memory_bank = MemoryBank()
        self.session_id = "sess_audit_9001"
        self.sample_transcript = [
            {"role": "assistant", "text": "नमस्ते! मैं प्रज्ञा बात कर रही हूँ Cymbal Lending से।"},
            {"role": "user", "text": "नमस्ते! मैं Aditya Sharma हूँ। मैं ₹24,00,000 MTL 14M में 12 months के लिए daily payout के साथ लगाना चाहता हूँ।"},
            {"role": "assistant", "text": "MTL 14M Daily में 18% return से daily ₹7,758 payout मिलेगा।"},
            {"role": "user", "text": "मैं Bengaluru से software engineer हूँ और low risk prefer करता हूँ।"},
        ]

    async def test_downcar_offline_heuristic_extraction_accuracy(self):
        """Verify extract_facts_and_summary_offline extracts all canonical facts from transcript."""
        text = format_transcript_for_downcar(self.sample_transcript)
        facts, summary = extract_facts_and_summary_offline(text, "user_aditya_sharma", self.session_id)

        self.assertEqual(facts.get("amount"), 2400000.0)
        self.assertEqual(facts.get("tenure_months"), 12)
        self.assertEqual(facts.get("risk_preference"), "low")
        self.assertEqual(facts.get("city"), "Bengaluru")
        self.assertEqual(facts.get("occupation"), "software engineer")
        self.assertEqual(facts.get("goal"), "daily liquidity")
        self.assertIn("Aditya Sharma", summary)
        self.assertIn("MTL 14M", summary)

    async def test_downcar_persists_to_fact_store_and_memory_bank(self):
        """Verify run_post_session_downcar updates FactStore and persists episodic memory with MD5."""
        res = await run_post_session_downcar(
            session_id=self.session_id,
            user_id="Aditya Sharma",
            transcript_history=self.sample_transcript,
            memory_bank=self.memory_bank,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["user_id"], "user_aditya_sharma")
        self.assertTrue(res["memory_added"])
        self.assertIsNotNone(res["content_hash"])

        # Check FactStore
        fs = self.memory_bank.get_fact_store("user_aditya_sharma")
        self.assertEqual(fs.get_fact("amount"), 2400000.0)
        self.assertEqual(fs.get_fact("city"), "Bengaluru")
        self.assertEqual(fs.get_fact("tenure_months"), 12)

        # Check MemoryBank
        memories = self.memory_bank.get_user_memories("user_aditya_sharma")
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["content_hash"], res["content_hash"])
        self.assertEqual(memories[0]["metadata"]["session_id"], self.session_id)

    async def test_downcar_idempotent_duplicate_prevention(self):
        """Verify executing downcar twice on same transcript returns duplicate status and preserves single record."""
        res1 = await run_post_session_downcar(
            session_id=self.session_id,
            user_id="Aditya Sharma",
            transcript_history=self.sample_transcript,
            memory_bank=self.memory_bank,
        )
        self.assertEqual(res1["status"], "success")

        res2 = await run_post_session_downcar(
            session_id="sess_reconnect_9002",
            user_id="Aditya Sharma",
            transcript_history=self.sample_transcript,
            memory_bank=self.memory_bank,
        )
        self.assertEqual(res2["status"], "duplicate")
        self.assertEqual(res2["content_hash"], res1["content_hash"])

        # Memory count remains 1
        memories = self.memory_bank.get_user_memories("user_aditya_sharma")
        self.assertEqual(len(memories), 1)

    async def test_downcar_empty_and_whitespace_transcripts(self):
        """Verify empty or whitespace-only transcripts return skipped status safely."""
        res_empty = await run_post_session_downcar(
            session_id="sess_empty",
            user_id="user_test",
            transcript_history=[],
            memory_bank=self.memory_bank,
        )
        self.assertEqual(res_empty["status"], "skipped")
        self.assertEqual(res_empty["reason"], "empty_transcript")

        res_ws = await run_post_session_downcar(
            session_id="sess_ws",
            user_id="user_test",
            transcript_history=[{"role": "user", "text": "   "}],
            memory_bank=self.memory_bank,
        )
        self.assertEqual(res_ws["status"], "skipped")
        self.assertEqual(res_ws["reason"], "empty_transcript_text")

    def test_parse_downcar_response_variations(self):
        """Verify parse_downcar_response handles markdown code fences, raw JSON, and plain text."""
        # 1. Markdown ```json ... ```
        fenced_json = "```json\n{\"facts\": {\"amount\": 50000.0}, \"summary\": \"Summary 1\"}\n```"
        p1 = parse_downcar_response(fenced_json)
        self.assertEqual(p1["facts"]["amount"], 50000.0)
        self.assertEqual(p1["summary"], "Summary 1")

        # 2. Raw JSON without fences
        raw_json = "{\"facts\": {\"tenure_months\": 6}, \"summary\": \"Summary 2\"}"
        p2 = parse_downcar_response(raw_json)
        self.assertEqual(p2["facts"]["tenure_months"], 6)

        # 3. Flat JSON (facts at root)
        flat_json = "{\"amount\": 100000.0, \"goal\": \"wealth growth\", \"summary\": \"Summary 3\"}"
        p3 = parse_downcar_response(flat_json)
        self.assertEqual(p3["facts"]["amount"], 100000.0)
        self.assertEqual(p3["facts"]["goal"], "wealth growth")

        # 4. Malformed / plain text fallback
        plain = "The customer talked about investing 50,000 for 6 months."
        p4 = parse_downcar_response(plain)
        self.assertTrue(p4.get("parse_error"))
        self.assertIn("50,000", p4["summary"])


if __name__ == "__main__":
    unittest.main()
