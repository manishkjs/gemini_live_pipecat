"""Milestone M5 Adversarial Stress & White-Box Coverage Hardening Suite.

Comprehensive adversarial test suite covering:
1. FactStore: 8 canonical keys, aliases, turn-by-turn history, 6-turn TTL boundaries (5, 6, 7),
   hypothetical confirmation, staggered expirations, key validation, history integrity.
2. MemoryBank & Vector Engine: 0.83 dedup vs 0.82999, 0.40 retrieval vs 0.39999, MD5 idempotency,
   90-day hydration boundaries, cross-user isolation, embedder & cosine similarity mathematical bounds.
3. Lexical Identity Normalization: conversational prefixes, honorifics, titles, punctuation,
   unsupported characters, fallback to 'user_anonymous', idempotency fuzzing.
4. retrieve_memory Tool: FunctionSchema validation, async execution paths, empty memory bank,
   missing user_id, empty query hydration, exception resilience, context injection.
5. Navigation Flows: Onboarding router, 3-step KYC guidance, Escrow deposit, 8 loan filter parameters,
   consultative guidance, fallback handling for unknown queries.
6. Memory Downcar Worker: Transcript formatting, markdown code-fence JSON stripping, malformed JSON
   recovery, heuristic offline extraction, MD5 hash idempotency, end-to-end background lifecycle.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from memory_bank import (
    CANONICAL_FACT_KEYS,
    DEFAULT_HYDRATION_LOOKBACK_DAYS,
    DEDUPLICATION_THRESHOLD,
    HYPOTHETICAL_TTL_TURNS,
    KEY_ALIASES,
    RETRIEVAL_THRESHOLD,
    DefaultTextEmbedder,
    FactStore,
    MemoryBank,
    cosine_similarity,
    normalize_lexical_user_id,
)
from tools.navigation import (
    get_app_screen_flow,
    get_consultative_guidance,
    get_kyc_guidance,
    get_navigation_guidance,
    get_onboarding_guide,
)
from tools.tool_definitions import (
    handle_retrieve_memory,
    retrieve_memory_schema,
)
from memory_downcar import (
    extract_facts_and_summary_offline,
    format_transcript_for_downcar,
    parse_downcar_response,
    run_post_session_downcar,
)


# ═══════════════════════════════════════════════════════════════════════
# HELPER MOCK CLASSES
# ═══════════════════════════════════════════════════════════════════════

class MockFunctionCallParams:
    """Mock for Pipecat FunctionCallParams to test async handler layer hermetically."""

    def __init__(
        self,
        arguments: Optional[Dict[str, Any]],
        function_name: str = "retrieve_memory",
        tool_call_id: str = "call_adv_test_1",
        context: Optional[Any] = None,
    ):
        self.arguments = arguments
        self.function_name = function_name
        self.tool_call_id = tool_call_id
        self.context = context
        self.result = None
        self.result_callback = AsyncMock(side_effect=self._record_result)

    async def _record_result(self, res: Any):
        self.result = res


class MockPreciseEmbedder:
    """Mock embedder providing deterministic vectors for exact similarity testing."""

    def __init__(self, mapping: Dict[str, List[float]]):
        self.mapping = mapping

    def embed(self, text: str) -> List[float]:
        return self.mapping.get(text, [0.0] * 2048)


# ═══════════════════════════════════════════════════════════════════════
# 1. FACT STORE ADVERSARIAL WHITE-BOX & TTL BOUNDARIES
# ═══════════════════════════════════════════════════════════════════════

class TestFactStoreAdversarialWhitebox(unittest.TestCase):
    """Deep white-box stress testing of FactStore and 6-turn TTL state transitions."""

    def setUp(self):
        self.fact_store = FactStore()

    def test_canonical_keys_and_alias_normalization(self):
        """Verify all 8 canonical keys and their recognized aliases map correctly."""
        alias_test_cases = [
            ("amount", "amount", 500000),
            ("tenure_months", "tenure_months", 12),
            ("tenure", "tenure_months", 6),
            ("tenure_month", "tenure_months", 7),
            ("months", "tenure_months", 5),
            ("risk_preference", "risk_preference", "low"),
            ("risk", "risk_preference", "moderate"),
            ("risk_appetite", "risk_preference", "high"),
            ("timeline", "timeline", "medium-term"),
            ("horizon", "timeline", "short-term"),
            ("goal", "goal", "wealth growth"),
            ("investment_goal", "goal", "regular monthly income"),
            ("occupation", "occupation", "doctor"),
            ("profession", "occupation", "engineer"),
            ("job", "occupation", "business owner"),
            ("city", "city", "Mumbai"),
            ("location", "city", "Bengaluru"),
            ("experience", "experience", "experienced"),
            ("inv_experience", "experience", "beginner"),
        ]

        for input_key, expected_canonical_key, test_val in alias_test_cases:
            fs = FactStore()
            fs.set_fact(input_key, test_val, turn_id=1)
            self.assertEqual(
                fs.get_fact(expected_canonical_key),
                test_val,
                f"Alias '{input_key}' failed to store under '{expected_canonical_key}'",
            )
            self.assertEqual(fs.get_fact(input_key), test_val)

    def test_invalid_and_malformed_keys_rejected(self):
        """Invalid, empty, non-string, or unknown keys must raise ValueError on write."""
        invalid_keys = [
            "",
            "   ",
            None,
            123,
            45.67,
            [],
            {},
            "salary",
            "cibil_score",
            "crypto_address",
            "pan_number",
            "bank_account",
        ]

        for inv_key in invalid_keys:
            with self.assertRaises(ValueError, msg=f"Key {inv_key!r} should have raised ValueError"):
                self.fact_store.set_fact(inv_key, "some_value", turn_id=1)

    def test_get_fact_on_invalid_key_returns_none_safely(self):
        """get_fact on unknown/invalid keys returns None without throwing exceptions."""
        self.assertIsNone(self.fact_store.get_fact("unknown_key_xyz"))
        self.assertIsNone(self.fact_store.get_fact(""))
        self.assertIsNone(self.fact_store.get_fact("credit_rating"))

    def test_ttl_exact_boundary_transitions(self):
        """Verify strict 6-turn TTL boundary: active at turn 5, 6; expires at turn 7."""
        # Set hypothetical fact at turn 1
        self.fact_store.set_fact("amount", 200000, turn_id=1, is_hypothetical=True)
        self.assertTrue(self.fact_store.is_fact_hypothetical("amount"))
        self.assertEqual(self.fact_store.get_fact("amount"), 200000)

        # Turns 2 through 6 (delta 1 through 5 turns) -> Must NOT expire
        for t in range(2, 7):
            expired = self.fact_store.tick_turn(turn_id=t)
            self.assertEqual(len(expired), 0, f"TTL expired prematurely at turn {t}")
            self.assertEqual(self.fact_store.get_fact("amount"), 200000)
            self.assertTrue(self.fact_store.is_fact_hypothetical("amount"))

        # Turn 7 (delta = 7 - 1 = 6 turns >= 6) -> MUST expire
        expired = self.fact_store.tick_turn(turn_id=7)
        self.assertEqual(len(expired), 1, "TTL failed to expire at exact turn 7")
        self.assertEqual(expired[0]["key"], "amount")
        self.assertEqual(expired[0]["old_value"], 200000)
        self.assertIsNone(expired[0]["new_value"])
        self.assertEqual(expired[0]["action"], "expire_hypothetical")

        # After expiration
        self.assertIsNone(self.fact_store.get_fact("amount"))
        self.assertFalse(self.fact_store.is_fact_hypothetical("amount"))
        self.assertIsNone(self.fact_store.get_hypothetical_metadata("amount"))

    def test_ttl_reversion_to_prior_confirmed_value(self):
        """When a hypothetical fact overwrites a confirmed fact, TTL expiry reverts to confirmed value."""
        # Turn 1: Confirmed fact
        self.fact_store.set_fact("amount", 100000, turn_id=1, is_hypothetical=False)
        self.assertEqual(self.fact_store.get_fact("amount"), 100000)
        self.assertFalse(self.fact_store.is_fact_hypothetical("amount"))

        # Turn 3: Hypothetical fact overwrites confirmed fact
        self.fact_store.set_fact("amount", 500000, turn_id=3, is_hypothetical=True)
        self.assertEqual(self.fact_store.get_fact("amount"), 500000)
        self.assertTrue(self.fact_store.is_fact_hypothetical("amount"))
        meta = self.fact_store.get_hypothetical_metadata("amount")
        self.assertEqual(meta["previous_value"], 100000)
        self.assertEqual(meta["set_turn"], 3)

        # Turn 8 (delta = 8 - 3 = 5 turns) -> Still hypothetical 500000
        self.fact_store.tick_turn(turn_id=8)
        self.assertEqual(self.fact_store.get_fact("amount"), 500000)

        # Turn 9 (delta = 9 - 3 = 6 turns >= 6) -> Reverts to 100000
        expired = self.fact_store.tick_turn(turn_id=9)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["old_value"], 500000)
        self.assertEqual(expired[0]["new_value"], 100000)
        self.assertEqual(self.fact_store.get_fact("amount"), 100000)
        self.assertFalse(self.fact_store.is_fact_hypothetical("amount"))

    def test_hypothetical_confirmed_before_expiry_persists(self):
        """Setting a confirmed value on a hypothetical key cancels TTL and prevents expiration."""
        self.fact_store.set_fact("tenure_months", 6, turn_id=1, is_hypothetical=True)
        self.assertTrue(self.fact_store.is_fact_hypothetical("tenure_months"))

        # Turn 4: User confirms the tenure
        self.fact_store.set_fact("tenure_months", 6, turn_id=4, is_hypothetical=False)
        self.assertFalse(self.fact_store.is_fact_hypothetical("tenure_months"))
        self.assertIsNone(self.fact_store.get_hypothetical_metadata("tenure_months"))

        # Turn 7, 8, 9, 10 -> Should NEVER expire
        for t in range(7, 12):
            expired = self.fact_store.tick_turn(turn_id=t)
            self.assertEqual(len(expired), 0)
            self.assertEqual(self.fact_store.get_fact("tenure_months"), 6)

    def test_staggered_multiple_hypothetical_expirations(self):
        """Multiple hypothetical parameters set at different turns expire at their respective 6-turn marks."""
        # Turn 1: amount=100000 (hypothetical, expires at turn 7)
        self.fact_store.set_fact("amount", 100000, turn_id=1, is_hypothetical=True)
        # Turn 3: tenure=12 (hypothetical, expires at turn 9)
        self.fact_store.set_fact("tenure_months", 12, turn_id=3, is_hypothetical=True)
        # Turn 5: goal="retirement" (hypothetical, expires at turn 11)
        self.fact_store.set_fact("goal", "retirement", turn_id=5, is_hypothetical=True)

        # Tick Turn 7 -> Only amount expires
        exp_7 = self.fact_store.tick_turn(turn_id=7)
        self.assertEqual(len(exp_7), 1)
        self.assertEqual(exp_7[0]["key"], "amount")
        self.assertIsNone(self.fact_store.get_fact("amount"))
        self.assertEqual(self.fact_store.get_fact("tenure_months"), 12)
        self.assertEqual(self.fact_store.get_fact("goal"), "retirement")

        # Tick Turn 9 -> Only tenure expires
        exp_9 = self.fact_store.tick_turn(turn_id=9)
        self.assertEqual(len(exp_9), 1)
        self.assertEqual(exp_9[0]["key"], "tenure_months")
        self.assertIsNone(self.fact_store.get_fact("tenure_months"))
        self.assertEqual(self.fact_store.get_fact("goal"), "retirement")

        # Tick Turn 11 -> Goal expires
        exp_11 = self.fact_store.tick_turn(turn_id=11)
        self.assertEqual(len(exp_11), 1)
        self.assertEqual(exp_11[0]["key"], "goal")
        self.assertIsNone(self.fact_store.get_fact("goal"))
        self.assertEqual(len(self.fact_store.get_all_facts()), 0)

    def test_history_audit_trail_and_clear(self):
        """Verify change history records all operations and clear() wipes all state."""
        self.fact_store.set_fact("city", "Pune", turn_id=1)
        self.fact_store.set_fact("city", "Mumbai", turn_id=2)
        self.fact_store.set_fact("risk_preference", "low", turn_id=3, is_hypothetical=True)
        self.fact_store.tick_turn(turn_id=9)

        history = self.fact_store.get_change_history()
        self.assertEqual(len(history), 4)
        actions = [entry["action"] for entry in history]
        self.assertEqual(actions, ["set_fact", "set_fact", "set_hypothetical", "expire_hypothetical"])

        # Clear
        self.fact_store.clear()
        self.assertEqual(len(self.fact_store.get_all_facts()), 0)
        self.assertEqual(len(self.fact_store.get_change_history()), 0)


# ═══════════════════════════════════════════════════════════════════════
# 2. DUAL-THRESHOLD VECTOR SIMILARITY ENGINE ADVERSARIAL
# ═══════════════════════════════════════════════════════════════════════

class TestDualThresholdVectorAdversarial(unittest.TestCase):
    """Stress testing of dual-threshold vector engine (0.83 dedup, 0.40 retrieval)."""

    def test_cosine_similarity_mathematical_bounds_and_edges(self):
        """Verify cosine similarity handles identical, orthogonal, opposite, zero vectors, and length mismatches."""
        v1 = [1.0, 0.0, 0.0]
        v2 = [1.0, 0.0, 0.0]
        v_orth = [0.0, 1.0, 0.0]
        v_opp = [-1.0, 0.0, 0.0]
        v_zero = [0.0, 0.0, 0.0]

        # Identical
        self.assertAlmostEqual(cosine_similarity(v1, v2), 1.0, places=5)
        # Orthogonal
        self.assertAlmostEqual(cosine_similarity(v1, v_orth), 0.0, places=5)
        # Opposite
        self.assertAlmostEqual(cosine_similarity(v1, v_opp), -1.0, places=5)
        # Zero vectors
        self.assertEqual(cosine_similarity(v1, v_zero), 0.0)
        # Empty vectors or length mismatch
        self.assertEqual(cosine_similarity([], [1.0, 2.0]), 0.0)
        self.assertEqual(cosine_similarity([1.0], [1.0, 2.0]), 0.0)

    def test_dedup_threshold_exact_boundary(self):
        """Verify vector deduplication at exact 0.83 threshold boundary.

        - sim >= 0.83000 (e.g. 0.83001 or 0.830) -> updates in place (count=1).
        - sim < 0.83000 (e.g. 0.82999) -> inserts new memory (count=2).
        """
        dim = 2048
        base_vec = [0.0] * dim
        base_vec[0] = 1.0

        vec_above = [0.0] * dim
        vec_above[0] = 0.83001
        vec_above[1] = math.sqrt(max(0.0, 1.0 - 0.83001**2))

        vec_below = [0.0] * dim
        vec_below[0] = 0.82999
        vec_below[1] = math.sqrt(max(0.0, 1.0 - 0.82999**2))

        # Test Case A: Similarity 0.83001 >= 0.83 -> In-place update
        mock_embedder_a = MockPreciseEmbedder({
            "base memory": base_vec,
            "near duplicate memory": vec_above,
        })
        mb_a = MemoryBank(embedder=mock_embedder_a, dedup_threshold=0.83)
        mb_a.add_memory("user_test", "base memory", metadata={"v": 1})
        self.assertEqual(len(mb_a.get_user_memories("user_test")), 1)

        added = mb_a.add_memory("user_test", "near duplicate memory", metadata={"v": 2})
        self.assertTrue(added)
        memories_a = mb_a.get_user_memories("user_test")
        self.assertEqual(len(memories_a), 1, "0.83001 similarity should have updated existing record in place")
        self.assertEqual(memories_a[0]["content"], "near duplicate memory")
        self.assertEqual(memories_a[0]["metadata"]["v"], 2)

        # Test Case B: Similarity 0.82999 < 0.83 -> Distinct insertion
        mock_embedder_b = MockPreciseEmbedder({
            "base memory": base_vec,
            "distinct memory": vec_below,
        })
        mb_b = MemoryBank(embedder=mock_embedder_b, dedup_threshold=0.83)
        mb_b.add_memory("user_test", "base memory", metadata={"v": 1})
        self.assertEqual(len(mb_b.get_user_memories("user_test")), 1)

        added_b = mb_b.add_memory("user_test", "distinct memory", metadata={"v": 2})
        self.assertTrue(added_b)
        memories_b = mb_b.get_user_memories("user_test")
        self.assertEqual(len(memories_b), 2, "0.82999 similarity should have inserted a second distinct record")

    def test_retrieval_threshold_exact_boundary(self):
        """Verify memory search retrieval at exact 0.40 threshold boundary.

        - sim >= 0.40000 (e.g. 0.40001) -> retrieved.
        - sim < 0.40000 (e.g. 0.39999) -> excluded.
        """
        dim = 2048
        query_vec = [0.0] * dim
        query_vec[0] = 1.0

        vec_match = [0.0] * dim
        vec_match[0] = 0.40001
        vec_match[1] = math.sqrt(max(0.0, 1.0 - 0.40001**2))

        # Use dimension 2 for vec_non_match so its dot product with vec_match is < 0.83 (preventing dedup)
        vec_non_match = [0.0] * dim
        vec_non_match[0] = 0.39999
        vec_non_match[2] = math.sqrt(max(0.0, 1.0 - 0.39999**2))

        mock_embedder = MockPreciseEmbedder({
            "search query": query_vec,
            "relevant record": vec_match,
            "irrelevant record": vec_non_match,
        })
        mb = MemoryBank(embedder=mock_embedder, retrieval_threshold=0.40)
        mb.add_memory("user_search", "relevant record")
        mb.add_memory("user_search", "irrelevant record")

        results = mb.search_memories("user_search", "search query", threshold=0.40)
        self.assertEqual(len(results), 1, "Only 0.40001 similarity should be retrieved")
        self.assertEqual(results[0]["content"], "relevant record")
        self.assertGreaterEqual(results[0]["similarity"], 0.40)

    def test_md5_hash_idempotency_and_hash_index_cleanup(self):
        """Verify MD5 hash index prevents duplicates and properly cleans up on near-duplicate updates."""
        mb = MemoryBank()
        uid = "user_aditya"
        text = "Customer invested 5 Lakhs in STL 7M on 14th August"
        h = hashlib.md5(text.encode("utf-8")).hexdigest()

        # Insert once
        res1 = mb.add_memory(uid, text, metadata={"turn": 1}, content_hash=h)
        self.assertTrue(res1)
        self.assertEqual(len(mb.get_user_memories(uid)), 1)
        self.assertIn(h, mb._hash_index[uid])

        # Insert again with same content_hash -> Must NOT duplicate
        res2 = mb.add_memory(uid, text, metadata={"turn": 2}, content_hash=h)
        self.assertTrue(res2)
        self.assertEqual(len(mb.get_user_memories(uid)), 1)
        self.assertEqual(mb.get_user_memories(uid)[0]["metadata"]["turn"], 2)

    def test_cross_session_profile_hydration_window_and_isolation(self):
        """Verify 90-day hydration lookback cutoffs and strict multi-user isolation."""
        now = datetime.now(timezone.utc)
        mb = MemoryBank(lookback_days=90)

        # User 1: One memory at 89 days (valid), one at 91 days (expired)
        mb.add_memory("user_1", "Valid 89d memory")
        mb._memories["user_1"][0]["created_at"] = (now - timedelta(days=89)).isoformat()
        mb._memories["user_1"][0]["updated_at"] = (now - timedelta(days=89)).isoformat()

        mb.add_memory("user_1", "Expired 91d memory")
        mb._memories["user_1"][1]["created_at"] = (now - timedelta(days=91)).isoformat()
        mb._memories["user_1"][1]["updated_at"] = (now - timedelta(days=91)).isoformat()

        # User 2: One memory at 10 days
        mb.add_memory("user_2", "User 2 recent memory")
        mb._memories["user_2"][0]["created_at"] = (now - timedelta(days=10)).isoformat()
        mb._memories["user_2"][0]["updated_at"] = (now - timedelta(days=10)).isoformat()

        # FactStores
        mb.get_fact_store("user_1").set_fact("amount", 250000, turn_id=1)
        mb.get_fact_store("user_2").set_fact("amount", 1000000, turn_id=1)

        # Hydrate User 1
        prof1 = mb.hydrate_user_profile("user_1", days_lookback=90)
        self.assertEqual(prof1["memory_count"], 1)
        self.assertEqual(prof1["episodic_memories"], ["Valid 89d memory"])
        self.assertEqual(prof1["facts"]["amount"], 250000)
        self.assertNotIn("User 2", str(prof1))

        # Hydrate User 2
        prof2 = mb.hydrate_user_profile("user_2", days_lookback=90)
        self.assertEqual(prof2["memory_count"], 1)
        self.assertEqual(prof2["episodic_memories"], ["User 2 recent memory"])
        self.assertEqual(prof2["facts"]["amount"], 1000000)
        self.assertNotIn("Valid 89d", str(prof2))


# ═══════════════════════════════════════════════════════════════════════
# 3. LEXICAL IDENTITY NORMALIZATION ADVERSARIAL STRESS
# ═══════════════════════════════════════════════════════════════════════

class TestLexicalNormalizationAdversarial(unittest.TestCase):
    """Adversarial stress testing for normalize_lexical_user_id."""

    def test_null_empty_whitespace_and_invalid_types(self):
        """Verify non-string, empty, whitespace-only, and punctuation-only inputs default to 'user_anonymous'."""
        bad_inputs = [
            None,
            "",
            "   ",
            "\t\n\r",
            "!!!@@@###$$$%%%^^^&&&***",
            "---___---",
            ".....",
            12345,
            67.89,
            [],
            {},
            object(),
        ]
        for inp in bad_inputs:
            self.assertEqual(
                normalize_lexical_user_id(inp),
                "user_anonymous",
                f"Failed for input {inp!r}",
            )

    def test_spoken_hindi_and_english_conversational_intros(self):
        """Verify various conversational speech patterns correctly extract customer names."""
        test_cases = [
            ("Aditya Sharma", "user_aditya_sharma"),
            ("Mr. Rajesh Kumar", "user_rajesh_kumar"),
            ("Mera naam Priya Patel hai", "user_priya_patel"),
            ("Namaste, main Deepak bol raha hoon", "user_deepak"),
            ("Namaskar! Mera naam Rohit Gupta hai", "user_rohit_gupta"),
            ("Hello, this is Sunita Rao speaking", "user_sunita_rao"),
            ("You are talking to Vikram Singh", "user_vikram_singh"),
            ("My name is Sanjay Sharma", "user_sanjay_sharma"),
            ("Hi, call me Rahul", "user_rahul"),
            ("Haan ji main Ajay baat kar raha hoon", "user_ajay"),
        ]

        for raw_input, expected in test_cases:
            actual = normalize_lexical_user_id(raw_input)
            self.assertEqual(
                actual,
                expected,
                f"Spoken intro '{raw_input}' failed: expected '{expected}', got '{actual}'",
            )

    def test_idempotency_property(self):
        """Verify normalize_lexical_user_id(normalize_lexical_user_id(x)) == normalize_lexical_user_id(x)."""
        samples = [
            "Aditya Sharma",
            "Mr. Rajesh Kumar",
            "Mera naam Priya Patel hai",
            "user_aditya_sharma",
            "user_rajesh_kumar",
            "user-deepak-singh",
            "Dr. Vikram Singh ji",
            "Special @#% Name",
        ]
        for s in samples:
            norm1 = normalize_lexical_user_id(s)
            norm2 = normalize_lexical_user_id(norm1)
            norm3 = normalize_lexical_user_id(norm2)
            self.assertEqual(norm1, norm2)
            self.assertEqual(norm2, norm3)


# ═══════════════════════════════════════════════════════════════════════
# 4. RETRIEVE MEMORY TOOL ADVERSARIAL EXECUTION
# ═══════════════════════════════════════════════════════════════════════

class TestRetrieveMemoryToolAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing for retrieve_memory FunctionSchema and async handler."""

    def setUp(self):
        self.mb = MemoryBank()

    def test_schema_properties(self):
        """Verify FunctionSchema name, properties, and required parameters."""
        schema = retrieve_memory_schema
        self.assertEqual(schema.name, "retrieve_memory")
        props = getattr(schema, "properties", {})
        self.assertIn("user_id", props)
        self.assertIn("query", props)
        self.assertIn("user_id", schema.required)

    async def _run_handler(self, args: Optional[Dict[str, Any]], mb: Optional[Any] = None) -> Dict[str, Any]:
        result_holder = {}

        async def callback(res: Dict[str, Any]):
            result_holder.update(res)

        params = MockFunctionCallParams(
            arguments=args,
            function_name="retrieve_memory",
        )
        params.result_callback = AsyncMock(side_effect=callback)
        await handle_retrieve_memory(params, memory_bank=mb if mb is not None else self.mb)
        return result_holder

    async def test_missing_or_empty_user_id_returns_not_found(self):
        """Empty or missing user_id returns status 'not_found' without crashing."""
        for bad_args in [{}, {"user_id": ""}, {"user_id": "   "}, {"user_id": None}, None]:
            res = await self._run_handler(bad_args)
            self.assertEqual(res.get("status"), "not_found")
            self.assertEqual(res.get("user_id"), "user_anonymous")
            self.assertEqual(res.get("count"), 0)

    async def test_uninitialized_memory_bank_handled_safely(self):
        """When memory bank is None, returns status 'empty' safely."""
        with patch("tools.tool_definitions._GLOBAL_MEMORY_BANK", None):
            res = await self._run_handler({"user_id": "Aditya Sharma"}, mb=False)
            self.assertIn(res.get("status"), ["empty", "not_found"])

    async def test_empty_query_triggers_profile_hydration(self):
        """When query is omitted/empty, retrieve_memory hydrates profile facts and memories."""
        uid = "user_rajesh"
        self.mb.get_fact_store(uid).set_fact("amount", 500000, turn_id=1)
        self.mb.get_fact_store(uid).set_fact("tenure_months", 12, turn_id=1)
        self.mb.add_memory(uid, "Rajesh prefers conservative low-risk STL 7M plan.")

        res = await self._run_handler({"user_id": "Rajesh", "query": ""})
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("user_id"), "user_rajesh")
        self.assertEqual(res.get("facts").get("amount"), 500000)
        self.assertEqual(res.get("facts").get("tenure_months"), 12)
        self.assertEqual(len(res.get("memories")), 1)

    async def test_search_exception_caught_and_wrapped_in_error_status(self):
        """Simulated exception inside memory search returns status 'error' without propagating."""
        broken_mb = MagicMock()
        broken_mb.get_fact_store.side_effect = RuntimeError("Simulated DB connection failure")

        res = await self._run_handler({"user_id": "Aditya", "query": "KYC"}, mb=broken_mb)
        self.assertEqual(res.get("status"), "error")
        self.assertIn("Simulated DB connection failure", res.get("error"))


# ═══════════════════════════════════════════════════════════════════════
# 5. NAVIGATION FLOWS ADVERSARIAL STRESS
# ═══════════════════════════════════════════════════════════════════════

class TestNavigationFlowsAdversarial(unittest.TestCase):
    """Stress testing of screen navigation flows and edge queries."""

    def test_kyc_guidance_all_branches_and_fallbacks(self):
        """Verify KYC guidance covers PAN, Aadhaar, Bank penny drop, and overview fallback."""
        pan_res = get_kyc_guidance("pan verification")
        self.assertEqual(pan_res["step"], "PAN Verification")
        self.assertIn("PAN number", pan_res["instructions_hinglish"])

        aadhaar_res = get_kyc_guidance("aadhaar otp digilocker")
        self.assertEqual(aadhaar_res["step"], "Aadhaar / Address Verification")
        self.assertIn("Digilocker", aadhaar_res["instructions_hinglish"])

        bank_res = get_kyc_guidance("penny drop bank linking")
        self.assertEqual(bank_res["step"], "Bank Account Linking")
        self.assertIn("Penny drop", bank_res["instructions_hinglish"])

        overview_res = get_kyc_guidance("unknown_step_xyz")
        self.assertEqual(overview_res["step"], "Complete KYC 3-Step Overview")

    def test_app_screen_flow_all_options_and_8_filter_parameters(self):
        """Verify app screen flows: deposit, lumpsum, manual, and 8 loan filters."""
        dep_res = get_app_screen_flow("deposit funds via upi")
        self.assertEqual(dep_res["flow_name"], "Adding Funds to Cymbal Escrow Wallet")

        lump_res = get_app_screen_flow("lumpsum stl mtl")
        self.assertEqual(lump_res["flow_name"], "Lumpsum Lending (STL / MTL)")

        man_res = get_app_screen_flow("manual lending borrowers")
        self.assertEqual(man_res["flow_name"], "Manual Lending Selection")

        filter_res = get_app_screen_flow("loan filter options")
        self.assertEqual(filter_res["flow_name"], "App Loan Filter Options")
        self.assertEqual(len(filter_res["available_filters"]), 8)

        gen_res = get_app_screen_flow("random_screen_query")
        self.assertEqual(gen_res["flow_name"], "General App Navigation")

    def test_consultative_guidance_topics(self):
        """Verify consultative guidance covers Bank FD, NPA risk, RBI trust, and liquidity."""
        fd_res = get_consultative_guidance("bank fd vs p2p")
        self.assertEqual(fd_res["topic"], "Bank FD Comparison")

        risk_res = get_consultative_guidance("npa default risk")
        self.assertEqual(risk_res["topic"], "Risk & Default Mitigation")

        rbi_res = get_consultative_guidance("rbi trust escrow safety")
        self.assertEqual(rbi_res["topic"], "Platform Legitimacy & RBI Trust")

        liq_res = get_consultative_guidance("withdraw liquidity emi edi")
        self.assertEqual(liq_res["topic"], "Liquidity & Repayment Mechanics")


# ═══════════════════════════════════════════════════════════════════════
# 6. MEMORY DOWNCAR EXTRACTION ADVERSARIAL STRESS
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryDowncarAdversarial(unittest.IsolatedAsyncioTestCase):
    """Stress testing of post-session memory downcar extraction and JSON parsing."""

    def test_format_transcript_adversarial_inputs(self):
        """Verify format_transcript_for_downcar handles empty, malformed, and valid lists."""
        self.assertEqual(format_transcript_for_downcar([]), "")
        self.assertEqual(format_transcript_for_downcar(None), "")
        self.assertEqual(format_transcript_for_downcar("not_a_list"), "")

        turns = [
            {"role": "user", "text": "Namaste"},
            {"participant": "model", "content": "Namaste! Kaise madad kar sakti hoon?"},
            {"role": "user", "text": "5 Lakh invest karna hai"},
            12345,
            None,
            {},
        ]
        formatted = format_transcript_for_downcar(turns)
        self.assertIn("User: Namaste", formatted)
        self.assertIn("Model: Namaste! Kaise madad kar sakti hoon?", formatted)
        self.assertIn("User: 5 Lakh invest karna hai", formatted)

    def test_parse_downcar_response_markdown_code_fences(self):
        """Verify parsing handles ```json ... ``` code fences, raw JSON, and corrupted strings."""
        # Standard markdown code fence
        payload_1 = """```json
        {
            "facts": {"amount": 500000.0, "tenure_months": 12, "goal": "wealth growth"},
            "summary": "Customer Aditya invested 5 Lakhs for 12 months."
        }
        ```"""
        p1 = parse_downcar_response(payload_1)
        self.assertEqual(p1["facts"]["amount"], 500000.0)
        self.assertEqual(p1["facts"]["tenure_months"], 12)
        self.assertEqual(p1["summary"], "Customer Aditya invested 5 Lakhs for 12 months.")

        # Plain code fence ``` ... ```
        payload_2 = """```
        {
            "facts": {"risk_preference": "low", "city": "Bengaluru"},
            "summary": "Customer discussed low risk plans."
        }
        ```"""
        p2 = parse_downcar_response(payload_2)
        self.assertEqual(p2["facts"]["risk_preference"], "low")
        self.assertEqual(p2["facts"]["city"], "Bengaluru")

        # Root-level facts without "facts" wrapper
        payload_3 = """{
            "amount": 250000.0,
            "occupation": "doctor",
            "summary": "Customer is a doctor investing 2.5 Lakhs."
        }"""
        p3 = parse_downcar_response(payload_3)
        self.assertEqual(p3["facts"]["amount"], 250000.0)
        self.assertEqual(p3["facts"]["occupation"], "doctor")

        # Corrupted / invalid JSON string -> Fallback without crashing
        corrupted = "I could not extract JSON: error in conversation."
        p_err = parse_downcar_response(corrupted)
        self.assertEqual(p_err["facts"], {})
        self.assertEqual(p_err["summary"], corrupted)
        self.assertTrue(p_err.get("parse_error"))

    def test_offline_heuristic_extraction_engine(self):
        """Verify extract_facts_and_summary_offline extracts all 8 canonical keys and formats summary."""
        transcript = (
            "User: Mera naam Manish Sharma hai.\n"
            "Model: Namaste Manish ji!\n"
            "User: Main Bangalore mein rehta hoon aur software engineer hoon.\n"
            "User: Main pehli baar P2P try kar raha hoon. 5 Lakhs invest karna hai 12 months ke liye.\n"
            "User: Mera goal wealth growth hai with low risk.\n"
            "Model: STL 7M plan perfect rahega."
        )

        facts, summary = extract_facts_and_summary_offline(transcript, "user_manish_sharma", "sess_001")
        self.assertEqual(facts.get("amount"), 500000.0)
        self.assertEqual(facts.get("tenure_months"), 12)
        self.assertEqual(facts.get("city"), "Bangalore")
        self.assertEqual(facts.get("occupation"), "software engineer")
        self.assertEqual(facts.get("experience"), "beginner")
        self.assertEqual(facts.get("goal"), "wealth growth")
        self.assertEqual(facts.get("risk_preference"), "low")
        self.assertIn("Manish Sharma", summary)
        self.assertIn("500000", summary)

    async def test_run_post_session_downcar_full_lifecycle_and_idempotency(self):
        """Verify end-to-end background downcar execution, FactStore update, and duplicate prevention."""
        mb = MemoryBank()
        uid = "Aditya Sharma"
        session_id = "sess_adv_1001"
        transcript = [
            {"role": "user", "text": "Namaste, I am Aditya Sharma."},
            {"role": "model", "text": "Namaste Aditya ji!"},
            {"role": "user", "text": "I want to invest 2 Lakhs for 6 months for wealth growth."},
        ]

        # Execute Downcar (hermetic offline path)
        res1 = await run_post_session_downcar(
            session_id=session_id,
            user_id=uid,
            transcript_history=transcript,
            memory_bank=mb,
        )

        self.assertEqual(res1["status"], "success")
        self.assertEqual(res1["user_id"], "user_aditya_sharma")
        self.assertEqual(res1["facts"]["amount"], 200000.0)
        self.assertEqual(res1["facts"]["tenure_months"], 6)
        self.assertTrue(res1["memory_added"])

        # Verify FactStore was updated
        fact_store = mb.get_fact_store("user_aditya_sharma")
        self.assertEqual(fact_store.get_fact("amount"), 200000.0)
        self.assertEqual(fact_store.get_fact("tenure_months"), 6)

        # Verify MemoryBank has the memory
        memories = mb.get_user_memories("user_aditya_sharma")
        self.assertEqual(len(memories), 1)

        # Re-run Downcar with identical transcript -> Must return status 'duplicate'
        res2 = await run_post_session_downcar(
            session_id=session_id,
            user_id=uid,
            transcript_history=transcript,
            memory_bank=mb,
        )
        self.assertEqual(res2["status"], "duplicate")
        self.assertEqual(len(mb.get_user_memories("user_aditya_sharma")), 1)

    async def test_run_post_session_downcar_empty_transcript_skipped(self):
        """Downcar skips safely when transcript is empty or whitespace-only."""
        mb = MemoryBank()
        res_empty = await run_post_session_downcar(
            session_id="sess_empty",
            user_id="user_test",
            transcript_history=[],
            memory_bank=mb,
        )
        self.assertEqual(res_empty["status"], "skipped")
        self.assertEqual(res_empty["reason"], "empty_transcript")


# ═══════════════════════════════════════════════════════════════════════
# 7. ADVANCED MULTI-COMPONENT INTEGRATION & ADVERSARIAL STRESS
# ═══════════════════════════════════════════════════════════════════════

class TestAdvancedStressAndSecurity(unittest.IsolatedAsyncioTestCase):
    """Multi-component stress testing covering large payloads, multi-session lifecycles, and scoping."""

    def test_massive_transcript_formatting_and_md5_stability(self):
        """Stress format_transcript_for_downcar with 1,000 turns; verify MD5 stability."""
        massive_history = [
            {"role": "user" if i % 2 == 0 else "model", "text": f"Utterance turn {i} discussing investment parameters"}
            for i in range(1000)
        ]
        formatted = format_transcript_for_downcar(massive_history)
        self.assertEqual(len(formatted.split("\n")), 1000)
        hash1 = hashlib.md5(formatted.encode("utf-8")).hexdigest()
        hash2 = hashlib.md5(formatted.encode("utf-8")).hexdigest()
        self.assertEqual(hash1, hash2)

    def test_search_memories_edge_parameters(self):
        """Verify search_memories handles extreme limits, empty queries, and extreme thresholds."""
        mb = MemoryBank()
        uid = "user_boundary_search"
        mb.add_memory(uid, "First memory regarding STL 7M")
        mb.add_memory(uid, "Second memory regarding MTL 14M")
        mb.add_memory(uid, "Third memory regarding KYC PAN verification")

        # Empty query -> []
        self.assertEqual(mb.search_memories(uid, ""), [])
        self.assertEqual(mb.search_memories(uid, "   "), [])
        self.assertEqual(mb.search_memories(uid, None), [])

        # Limit = 0 -> []
        self.assertEqual(mb.search_memories(uid, "STL", limit=0), [])

        # Threshold = 1.0 -> Only exact identical match
        exact_matches = mb.search_memories(uid, "First memory regarding STL 7M", threshold=1.0)
        self.assertTrue(len(exact_matches) >= 1)
        self.assertAlmostEqual(exact_matches[0]["similarity"], 1.0, places=3)

        # Threshold = -1.0 -> Returns all up to limit
        all_matches = mb.search_memories(uid, "KYC", threshold=-1.0, limit=10)
        self.assertEqual(len(all_matches), 3)

    def test_fact_store_complex_lifecycle_with_multiple_hypotheticals(self):
        """Complex sequence: set confirmed facts, set multiple hypotheticals, confirm one, let other expire."""
        fs = FactStore()

        # Turn 1: Confirmed amount and city
        fs.set_fact("amount", 100000.0, turn_id=1, is_hypothetical=False)
        fs.set_fact("city", "Delhi", turn_id=1, is_hypothetical=False)

        # Turn 2: Hypothetical tenure and goal
        fs.set_fact("tenure_months", 12, turn_id=2, is_hypothetical=True)
        fs.set_fact("goal", "wealth growth", turn_id=2, is_hypothetical=True)

        # Turn 4: User updates hypothetical amount to 300,000 (overwriting confirmed 100,000)
        fs.set_fact("amount", 300000.0, turn_id=4, is_hypothetical=True)
        self.assertEqual(fs.get_fact("amount"), 300000.0)

        # Turn 5: User confirms goal
        fs.set_fact("goal", "wealth growth", turn_id=5, is_hypothetical=False)
        self.assertFalse(fs.is_fact_hypothetical("goal"))

        # Turn 8: (Turn 8 - Turn 2 = 6 turns) -> tenure_months expires
        exp_8 = fs.tick_turn(turn_id=8)
        self.assertEqual(len(exp_8), 1)
        self.assertEqual(exp_8[0]["key"], "tenure_months")
        self.assertIsNone(fs.get_fact("tenure_months"))

        # Turn 10: (Turn 10 - Turn 4 = 6 turns) -> amount expires and reverts to 100,000
        exp_10 = fs.tick_turn(turn_id=10)
        self.assertEqual(len(exp_10), 1)
        self.assertEqual(exp_10[0]["key"], "amount")
        self.assertEqual(fs.get_fact("amount"), 100000.0)
        self.assertFalse(fs.is_fact_hypothetical("amount"))

        # Final state check
        facts = fs.get_all_facts()
        self.assertEqual(facts["amount"], 100000.0)
        self.assertEqual(facts["city"], "Delhi")
        self.assertEqual(facts["goal"], "wealth growth")
        self.assertNotIn("tenure_months", facts)

    def test_user_scoped_clear_vs_global_clear(self):
        """Verify clear(user_id) isolates wiping to that user without affecting others."""
        mb = MemoryBank()
        mb.add_memory("user_alice", "Alice memory")
        mb.get_fact_store("user_alice").set_fact("amount", 50000, turn_id=1)

        mb.add_memory("user_bob", "Bob memory")
        mb.get_fact_store("user_bob").set_fact("amount", 100000, turn_id=1)

        # Clear Alice only
        mb.clear("user_alice")
        self.assertEqual(len(mb.get_user_memories("user_alice")), 0)
        self.assertEqual(len(mb.get_fact_store("user_alice").get_all_facts()), 0)

        # Bob remains unaffected
        self.assertEqual(len(mb.get_user_memories("user_bob")), 1)
        self.assertEqual(mb.get_fact_store("user_bob").get_fact("amount"), 100000)

        # Global clear
        mb.clear()
        self.assertEqual(len(mb.get_user_memories("user_bob")), 0)
        self.assertEqual(len(mb.get_fact_store("user_bob").get_all_facts()), 0)

    async def test_full_session_flow_hydration_tool_and_downcar(self):
        """End-to-end multi-turn journey: Session 1 Downcar -> Session 2 Profile Hydration -> Tool Execution."""
        mb = MemoryBank()
        uid = "Rajesh Kumar"

        # Session 1: Downcar extracts facts and writes episodic memory
        sess1_transcript = [
            {"role": "user", "text": "Hello, my name is Rajesh Kumar. I live in Mumbai."},
            {"role": "model", "text": "Namaste Rajesh ji! How can I help you today?"},
            {"role": "user", "text": "I am a chartered accountant looking for wealth growth. 5 Lakhs for 12 months with low risk."},
        ]
        downcar_res = await run_post_session_downcar(
            session_id="sess_e2e_1",
            user_id=uid,
            transcript_history=sess1_transcript,
            memory_bank=mb,
        )
        self.assertEqual(downcar_res["status"], "success")

        # Session 2: On new session start, user profile hydrates
        profile = mb.hydrate_user_profile(uid, days_lookback=90)
        self.assertTrue(profile["profile_hydrated"])
        self.assertEqual(profile["facts"]["amount"], 500000.0)
        self.assertEqual(profile["facts"]["city"], "Mumbai")
        self.assertEqual(profile["facts"]["occupation"], "chartered accountant")
        self.assertEqual(profile["facts"]["goal"], "wealth growth")

        # In-call tool invocation via handle_retrieve_memory
        result_holder = {}

        async def callback(res: Dict[str, Any]):
            result_holder.update(res)

        params = MockFunctionCallParams(
            arguments={"user_id": uid, "query": "wealth growth low risk 12 months"},
            function_name="retrieve_memory",
        )
        params.result_callback = AsyncMock(side_effect=callback)
        await handle_retrieve_memory(params, memory_bank=mb)

        self.assertEqual(result_holder["status"], "success")
        self.assertEqual(result_holder["user_id"], "user_rajesh_kumar")
        self.assertEqual(result_holder["facts"]["amount"], 500000.0)
        self.assertTrue(len(result_holder["memories"]) >= 1)


if __name__ == "__main__":
    unittest.main()

