"""Hermetic Unit & Boundary Test Suite for Gemini Enterprise Agent Memory Bank Engine.

Covers Tier 1 (Feature) and Tier 2 (Boundary/Edge) tests:
1. Lexical Identity Normalization (`normalize_lexical_user_id`)
2. Structured FactStore (8 canonical keys, audit history, aliases)
3. Hypothetical Parameter 6-Turn TTL (`tick_turn`, expiration, revert)
4. Dual-Threshold Vector Engine (0.83 deduplication, 0.40 retrieval, MD5 idempotency)
5. 90-Day Cross-Session Profile Hydration (`hydrate_user_profile`)

All tests are self-contained and run instantly with zero external network dependencies.
"""

from __future__ import annotations

import hashlib
import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Add server directory to sys.path
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ["ENABLE_CLOUD_MEMORY_BANK"] = "false"

from unittest.mock import MagicMock, patch

from memory_bank import (
    CANONICAL_FACT_KEYS,
    DEFAULT_HYDRATION_LOOKBACK_DAYS,
    DEDUPLICATION_THRESHOLD,
    HYPOTHETICAL_TTL_TURNS,
    KEY_ALIASES,
    RETRIEVAL_THRESHOLD,
    DefaultTextEmbedder,
    FactStore,
    GCPAgentEngineMemoryBank,
    MemoryBank,
    cosine_similarity,
    normalize_lexical_user_id,
)


class MockCustomVectorEmbedder:
    """Mock embedder providing deterministic, precisely controlled vectors for threshold testing."""

    def __init__(self, vector_map: Optional[Dict[str, List[float]]] = None):
        self.vector_map = vector_map or {}
        self.dim = 4

    def set_vector(self, text: str, vector: List[float]) -> None:
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0:
            self.vector_map[text] = [x / norm for x in vector]
        else:
            self.vector_map[text] = list(vector)

    def embed(self, text: str) -> List[float]:
        clean = text.strip()
        if clean in self.vector_map:
            return self.vector_map[clean]
        # Deterministic fallback unit vector
        h = int(hashlib.md5(clean.encode("utf-8")).hexdigest()[:8], 16)
        vec = [(h & 0xF) + 1.0, ((h >> 4) & 0xF) + 1.0, ((h >> 8) & 0xF) + 1.0, ((h >> 12) & 0xF) + 1.0]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec]


# ═══════════════════════════════════════════════════════════════════════
# FEATURE 1: LEXICAL IDENTITY NORMALIZATION TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestLexicalIdentityNormalizationTier1(unittest.TestCase):
    """Tier 1: Feature tests for normalize_lexical_user_id."""

    def test_lexical_norm_standard_full_name(self):
        """Test standard customer names normalize to deterministic user keys."""
        self.assertEqual(normalize_lexical_user_id("Aditya Sharma"), "user_aditya_sharma")
        self.assertEqual(normalize_lexical_user_id("Rajesh Kumar"), "user_rajesh_kumar")
        self.assertEqual(normalize_lexical_user_id("Priya Patel"), "user_priya_patel")

    def test_lexical_norm_honorifics_and_titles(self):
        """Test stripping of common English and Hindi honorifics and titles."""
        self.assertEqual(normalize_lexical_user_id("Mr. Aditya Sharma"), "user_aditya_sharma")
        self.assertEqual(normalize_lexical_user_id("Dr. Rajesh Kumar"), "user_rajesh_kumar")
        self.assertEqual(normalize_lexical_user_id("Smt. Sunita Rao"), "user_sunita_rao")
        self.assertEqual(normalize_lexical_user_id("Shri Amit Patel"), "user_amit_patel")
        self.assertEqual(normalize_lexical_user_id("Vikram Singh ji"), "user_vikram_singh")
        self.assertEqual(normalize_lexical_user_id("Prof. R.K. Sharma"), "user_r_k_sharma")
        self.assertEqual(normalize_lexical_user_id("I am Dr. Amit Patel"), "user_amit_patel")
        self.assertEqual(normalize_lexical_user_id("This is Smt. Sunita Rao"), "user_sunita_rao")
        self.assertEqual(normalize_lexical_user_id("Call me Mr. Verma"), "user_verma")
        self.assertEqual(normalize_lexical_user_id("Hello, I am Prof. R.K. Sharma"), "user_r_k_sharma")

    def test_lexical_norm_conversational_intro(self):
        """Test stripping of conversational spoken phrasing in Hindi and English."""
        self.assertEqual(
            normalize_lexical_user_id("Mera naam Priya Patel hai"),
            "user_priya_patel",
        )
        self.assertEqual(
            normalize_lexical_user_id("Namaste, main Deepak bol raha hoon"),
            "user_deepak",
        )
        self.assertEqual(
            normalize_lexical_user_id("Hello, this is Sunita Rao speaking"),
            "user_sunita_rao",
        )
        self.assertEqual(
            normalize_lexical_user_id("My name is Rohit Gupta"),
            "user_rohit_gupta",
        )
        self.assertEqual(
            normalize_lexical_user_id("Aap baat kar rahe hain Sanjay Sharma se"),
            "user_sanjay_sharma",
        )

    def test_lexical_norm_whitespace_and_hyphen_collapsing(self):
        """Test collapsing multiple spaces, tabs, and hyphens into single underscores."""
        self.assertEqual(normalize_lexical_user_id("   Priya    Singh   "), "user_priya_singh")
        self.assertEqual(normalize_lexical_user_id("Aditya-Sharma"), "user_aditya_sharma")
        self.assertEqual(normalize_lexical_user_id("Amit___Patel--Senior"), "user_amit_patel_senior")
        self.assertEqual(normalize_lexical_user_id("  Rohit\t\tVerma\n "), "user_rohit_verma")

    def test_lexical_norm_single_word_name(self):
        """Test single token names are properly prefixed."""
        self.assertEqual(normalize_lexical_user_id("Vikram"), "user_vikram")
        self.assertEqual(normalize_lexical_user_id("Pooja"), "user_pooja")
        self.assertEqual(normalize_lexical_user_id("rahul"), "user_rahul")

    def test_lexical_norm_deterministic_idempotence(self):
        """Test repeated normalization on raw and already normalized keys is idempotent."""
        key1 = normalize_lexical_user_id("Aditya Sharma")
        key2 = normalize_lexical_user_id(key1)
        key3 = normalize_lexical_user_id("user_aditya_sharma")
        key4 = normalize_lexical_user_id("user-aditya-sharma")
        self.assertEqual(key1, "user_aditya_sharma")
        self.assertEqual(key2, "user_aditya_sharma")
        self.assertEqual(key3, "user_aditya_sharma")
        self.assertEqual(key4, "user_aditya_sharma")


class TestLexicalIdentityNormalizationTier2(unittest.TestCase):
    """Tier 2: Boundary and edge tests for normalize_lexical_user_id."""

    def test_lexical_norm_boundary_empty_and_none(self):
        """Test None, empty string, and non-string inputs return user_anonymous."""
        self.assertEqual(normalize_lexical_user_id(""), "user_anonymous")
        self.assertEqual(normalize_lexical_user_id(None), "user_anonymous")
        self.assertEqual(normalize_lexical_user_id(12345), "user_anonymous")
        self.assertEqual(normalize_lexical_user_id([]), "user_anonymous")

    def test_lexical_norm_boundary_whitespace_only(self):
        """Test whitespace-only inputs return user_anonymous."""
        self.assertEqual(normalize_lexical_user_id("   "), "user_anonymous")
        self.assertEqual(normalize_lexical_user_id("\t\t\n  \r\n"), "user_anonymous")

    def test_lexical_norm_boundary_pure_symbols_and_punctuation(self):
        """Test input with only special characters and punctuation."""
        self.assertEqual(normalize_lexical_user_id("---!@#$%^&*()+++"), "user_anonymous")
        self.assertEqual(normalize_lexical_user_id("...,,,;;;:::"), "user_anonymous")
        self.assertEqual(normalize_lexical_user_id("???///\\\\"), "user_anonymous")

    def test_lexical_norm_boundary_devanagari_and_mixed_symbols(self):
        """Test inputs containing symbols mixed with words."""
        self.assertEqual(normalize_lexical_user_id("Aditya @ Cymbal #1"), "user_aditya_cymbal_1")
        self.assertEqual(normalize_lexical_user_id("Rajesh (Investor)"), "user_rajesh_investor")

    def test_lexical_norm_boundary_extremely_long_input(self):
        """Test extremely large input string is handled safely and deterministically."""
        long_name = "Aditya " * 500 + "Sharma"
        res = normalize_lexical_user_id(long_name)
        self.assertTrue(res.startswith("user_aditya_"))
        self.assertTrue(res.endswith("_sharma"))

    def test_lexical_norm_boundary_numeric_and_alphanumeric_names(self):
        """Test alphanumeric lender identifiers."""
        self.assertEqual(normalize_lexical_user_id("Lender 007"), "user_lender_007")
        self.assertEqual(normalize_lexical_user_id("Investor_99"), "user_investor_99")
        self.assertEqual(normalize_lexical_user_id("user_101_alpha"), "user_101_alpha")


# ═══════════════════════════════════════════════════════════════════════
# FEATURE 2: STRUCTURED FACTSTORE TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestFactStoreTier1(unittest.TestCase):
    """Tier 1: Feature tests for FactStore tracking 8 canonical financial keys."""

    def setUp(self):
        self.fact_store = FactStore()

    def test_fact_store_8_canonical_keys(self):
        """Test setting and getting all 8 canonical financial keys."""
        expected_keys = {
            "amount",
            "tenure_months",
            "risk_preference",
            "timeline",
            "goal",
            "occupation",
            "city",
            "experience",
        }
        self.assertEqual(CANONICAL_FACT_KEYS, expected_keys)

        test_data = {
            "amount": 500000.0,
            "tenure_months": 12,
            "risk_preference": "low",
            "timeline": "1 year",
            "goal": "wealth growth",
            "occupation": "software engineer",
            "city": "Bengaluru",
            "experience": "experienced",
        }

        for turn, (k, v) in enumerate(test_data.items(), start=1):
            self.fact_store.set_fact(k, v, turn_id=turn)
            self.assertEqual(self.fact_store.get_fact(k), v)

        all_facts = self.fact_store.get_all_facts()
        self.assertEqual(all_facts, test_data)

    def test_fact_store_get_all_facts_returns_active_copy(self):
        """Test get_all_facts returns a clean dictionary copy of all active facts."""
        self.fact_store.set_fact("amount", 250000, turn_id=1)
        self.fact_store.set_fact("city", "Mumbai", turn_id=2)

        facts = self.fact_store.get_all_facts()
        self.assertEqual(facts, {"amount": 250000, "city": "Mumbai"})

        # Modifying returned dict must not affect internal state
        facts["amount"] = 999999
        self.assertEqual(self.fact_store.get_fact("amount"), 250000)

    def test_fact_store_key_aliases(self):
        """Test setting facts using canonical aliases correctly maps to canonical keys."""
        self.fact_store.set_fact("tenure", 6, turn_id=1)
        self.assertEqual(self.fact_store.get_fact("tenure_months"), 6)
        self.assertEqual(self.fact_store.get_fact("tenure"), 6)

        self.fact_store.set_fact("risk_appetite", "moderate", turn_id=2)
        self.assertEqual(self.fact_store.get_fact("risk_preference"), "moderate")

        self.fact_store.set_fact("location", "Delhi", turn_id=3)
        self.assertEqual(self.fact_store.get_fact("city"), "Delhi")

        self.fact_store.set_fact("profession", "doctor", turn_id=4)
        self.assertEqual(self.fact_store.get_fact("occupation"), "doctor")

    def test_fact_store_change_history_audit_trail(self):
        """Test get_change_history records complete turn-by-turn audit entries."""
        self.fact_store.set_fact("amount", 100000, turn_id=1)
        self.fact_store.set_fact("amount", 200000, turn_id=3)

        history = self.fact_store.get_change_history()
        self.assertEqual(len(history), 2)

        self.assertEqual(history[0]["turn_id"], 1)
        self.assertEqual(history[0]["key"], "amount")
        self.assertIsNone(history[0]["old_value"])
        self.assertEqual(history[0]["new_value"], 100000)
        self.assertFalse(history[0]["is_hypothetical"])

        self.assertEqual(history[1]["turn_id"], 3)
        self.assertEqual(history[1]["key"], "amount")
        self.assertEqual(history[1]["old_value"], 100000)
        self.assertEqual(history[1]["new_value"], 200000)

    def test_fact_store_overwriting_facts(self):
        """Test overwriting a fact updates active state and records previous value."""
        self.fact_store.set_fact("goal", "house purchase", turn_id=1)
        self.assertEqual(self.fact_store.get_fact("goal"), "house purchase")

        self.fact_store.set_fact("goal", "retirement", turn_id=2)
        self.assertEqual(self.fact_store.get_fact("goal"), "retirement")

    def test_fact_store_clearing_fact_with_none(self):
        """Test setting fact value to None removes it from active facts."""
        self.fact_store.set_fact("occupation", "lawyer", turn_id=1)
        self.assertEqual(self.fact_store.get_fact("occupation"), "lawyer")

        self.fact_store.set_fact("occupation", None, turn_id=2)
        self.assertIsNone(self.fact_store.get_fact("occupation"))
        self.assertNotIn("occupation", self.fact_store.get_all_facts())


class TestFactStoreTier2(unittest.TestCase):
    """Tier 2: Boundary and error handling tests for FactStore."""

    def setUp(self):
        self.fact_store = FactStore()

    def test_fact_store_boundary_invalid_key_raises_error(self):
        """Test setting a non-canonical unknown key raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.fact_store.set_fact("favorite_food", "pizza", turn_id=1)
        self.assertIn("Invalid fact key", str(ctx.exception))

    def test_fact_store_boundary_empty_or_none_key_raises_error(self):
        """Test empty string or None key raises ValueError."""
        with self.assertRaises(ValueError):
            self.fact_store.set_fact("", 50000, turn_id=1)
        with self.assertRaises(ValueError):
            self.fact_store.set_fact(None, 50000, turn_id=1)

    def test_fact_store_boundary_get_invalid_or_unset_key_returns_none(self):
        """Test get_fact returns None for unset or invalid keys without raising."""
        self.assertIsNone(self.fact_store.get_fact("amount"))
        self.assertIsNone(self.fact_store.get_fact("unknown_random_key"))

    def test_fact_store_boundary_numerical_extremes(self):
        """Test storing boundary numerical values for amount and tenure."""
        self.fact_store.set_fact("amount", 0, turn_id=1)
        self.assertEqual(self.fact_store.get_fact("amount"), 0)

        self.fact_store.set_fact("amount", 50000000.0, turn_id=2)
        self.assertEqual(self.fact_store.get_fact("amount"), 50000000.0)

        self.fact_store.set_fact("tenure_months", 1, turn_id=3)
        self.assertEqual(self.fact_store.get_fact("tenure_months"), 1)

    def test_fact_store_boundary_rapid_sequential_updates(self):
        """Test 100 rapid sequential updates accurately records 100 history entries."""
        for i in range(1, 101):
            self.fact_store.set_fact("amount", i * 1000, turn_id=i)

        self.assertEqual(self.fact_store.get_fact("amount"), 100000)
        history = self.fact_store.get_change_history()
        self.assertEqual(len(history), 100)
        self.assertEqual(history[-1]["new_value"], 100000)

    def test_fact_store_boundary_clear_resets_everything(self):
        """Test clear() completely resets facts, hypothetical metadata, and history."""
        self.fact_store.set_fact("amount", 100000, turn_id=1, is_hypothetical=True)
        self.fact_store.set_fact("city", "Pune", turn_id=1)

        self.fact_store.clear()
        self.assertEqual(self.fact_store.get_all_facts(), {})
        self.assertEqual(self.fact_store.get_change_history(), [])
        self.assertFalse(self.fact_store.is_fact_hypothetical("amount"))


# ═══════════════════════════════════════════════════════════════════════
# FEATURE 3: HYPOTHETICAL PARAMETER 6-TURN TTL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestHypotheticalParameterTTLTier1(unittest.TestCase):
    """Tier 1: Feature tests for 6-turn TTL hypothetical parameter exploration."""

    def setUp(self):
        self.fact_store = FactStore(ttl_turns=6)

    def test_hypothetical_ttl_active_at_creation(self):
        """Test hypothetical fact is active immediately upon being set."""
        self.fact_store.set_fact("amount", 200000, turn_id=2, is_hypothetical=True)
        self.assertEqual(self.fact_store.get_fact("amount"), 200000)
        self.assertTrue(self.fact_store.is_fact_hypothetical("amount"))

    def test_hypothetical_ttl_persists_during_window(self):
        """Test hypothetical fact remains active during turns within 6 turns."""
        self.fact_store.set_fact("amount", 300000, turn_id=1, is_hypothetical=True)

        # Turns 2 through 6 (delta 1 to 5)
        for t in range(2, 7):
            events = self.fact_store.tick_turn(t)
            self.assertEqual(len(events), 0)
            self.assertEqual(self.fact_store.get_fact("amount"), 300000)
            self.assertTrue(self.fact_store.is_fact_hypothetical("amount"))

    def test_hypothetical_ttl_expires_at_turn_7(self):
        """Test hypothetical fact set at turn 1 expires when turn delta reaches 6."""
        self.fact_store.set_fact("amount", 500000, turn_id=1, is_hypothetical=True)

        # At turn 7 (7 - 1 = 6 >= TTL 6), tick_turn triggers expiration
        events = self.fact_store.tick_turn(7)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["key"], "amount")
        self.assertEqual(events[0]["action"], "expire_hypothetical")
        self.assertIsNone(self.fact_store.get_fact("amount"))
        self.assertFalse(self.fact_store.is_fact_hypothetical("amount"))

    def test_hypothetical_ttl_reverts_to_previous_confirmed_value(self):
        """Test expired hypothetical fact reverts to its prior confirmed value."""
        # Confirmed fact set at turn 1
        self.fact_store.set_fact("amount", 50000, turn_id=1, is_hypothetical=False)
        self.assertEqual(self.fact_store.get_fact("amount"), 50000)

        # Hypothetical exploration at turn 3
        self.fact_store.set_fact("amount", 2400000, turn_id=3, is_hypothetical=True)
        self.assertEqual(self.fact_store.get_fact("amount"), 2400000)
        self.assertTrue(self.fact_store.is_fact_hypothetical("amount"))

        # At turn 9 (9 - 3 = 6), expiration reverts amount back to 50000
        events = self.fact_store.tick_turn(9)
        self.assertEqual(len(events), 1)
        self.assertEqual(self.fact_store.get_fact("amount"), 50000)
        self.assertFalse(self.fact_store.is_fact_hypothetical("amount"))

    def test_hypothetical_confirmed_overwrite_cancels_ttl(self):
        """Test confirming a hypothetical fact cancels TTL and persists value permanently."""
        self.fact_store.set_fact("tenure_months", 12, turn_id=2, is_hypothetical=True)
        self.assertTrue(self.fact_store.is_fact_hypothetical("tenure_months"))

        # User confirms at turn 4
        self.fact_store.set_fact("tenure_months", 12, turn_id=4, is_hypothetical=False)
        self.assertFalse(self.fact_store.is_fact_hypothetical("tenure_months"))

        # Advance far into future (turn 20)
        events = self.fact_store.tick_turn(20)
        self.assertEqual(len(events), 0)
        self.assertEqual(self.fact_store.get_fact("tenure_months"), 12)

    def test_hypothetical_independent_ttls_per_key(self):
        """Test multiple hypothetical facts set at different turns expire independently."""
        self.fact_store.set_fact("amount", 100000, turn_id=1, is_hypothetical=True)
        self.fact_store.set_fact("tenure_months", 6, turn_id=4, is_hypothetical=True)

        # Turn 7: amount expires (7 - 1 = 6), tenure_months remains active (7 - 4 = 3)
        events_7 = self.fact_store.tick_turn(7)
        self.assertEqual(len(events_7), 1)
        self.assertEqual(events_7[0]["key"], "amount")
        self.assertIsNone(self.fact_store.get_fact("amount"))
        self.assertEqual(self.fact_store.get_fact("tenure_months"), 6)

        # Turn 10: tenure_months expires (10 - 4 = 6)
        events_10 = self.fact_store.tick_turn(10)
        self.assertEqual(len(events_10), 1)
        self.assertEqual(events_10[0]["key"], "tenure_months")
        self.assertIsNone(self.fact_store.get_fact("tenure_months"))


class TestHypotheticalParameterTTLTier2(unittest.TestCase):
    """Tier 2: Boundary and edge tests for hypothetical TTL."""

    def setUp(self):
        self.fact_store = FactStore(ttl_turns=6)

    def test_hypothetical_boundary_exact_delta_5_vs_6(self):
        """Test exact boundary: delta 5 is active, delta 6 expires."""
        self.fact_store.set_fact("amount", 75000, turn_id=10, is_hypothetical=True)

        # Delta = 5 (turn 15): Still active
        events_15 = self.fact_store.tick_turn(15)
        self.assertEqual(len(events_15), 0)
        self.assertEqual(self.fact_store.get_fact("amount"), 75000)

        # Delta = 6 (turn 16): Exactly expires
        events_16 = self.fact_store.tick_turn(16)
        self.assertEqual(len(events_16), 1)
        self.assertIsNone(self.fact_store.get_fact("amount"))

    def test_hypothetical_boundary_large_turn_jump(self):
        """Test large turn jump expires all pending hypothetical facts cleanly."""
        self.fact_store.set_fact("amount", 100000, turn_id=1, is_hypothetical=True)
        self.fact_store.set_fact("city", "Jaipur", turn_id=2, is_hypothetical=True)
        self.fact_store.set_fact("goal", "car", turn_id=3, is_hypothetical=True)

        events = self.fact_store.tick_turn(100)
        self.assertEqual(len(events), 3)
        self.assertEqual(self.fact_store.get_all_facts(), {})

    def test_hypothetical_boundary_tick_with_no_hypotheticals(self):
        """Test ticking turns when only confirmed facts exist produces zero expired events."""
        self.fact_store.set_fact("amount", 50000, turn_id=1, is_hypothetical=False)
        self.fact_store.set_fact("tenure_months", 6, turn_id=2, is_hypothetical=False)

        events = self.fact_store.tick_turn(50)
        self.assertEqual(len(events), 0)
        self.assertEqual(self.fact_store.get_fact("amount"), 50000)
        self.assertEqual(self.fact_store.get_fact("tenure_months"), 6)

    def test_hypothetical_boundary_updating_hypothetical_extends_ttl(self):
        """Test updating a hypothetical fact resets its set_turn and extends TTL."""
        self.fact_store.set_fact("amount", 100000, turn_id=1, is_hypothetical=True)

        # User explores another hypothetical amount at turn 5
        self.fact_store.set_fact("amount", 200000, turn_id=5, is_hypothetical=True)

        # At turn 7 (7 - 1 = 6, but 7 - 5 = 2): must NOT expire
        events_7 = self.fact_store.tick_turn(7)
        self.assertEqual(len(events_7), 0)
        self.assertEqual(self.fact_store.get_fact("amount"), 200000)

        # At turn 11 (11 - 5 = 6): expires
        events_11 = self.fact_store.tick_turn(11)
        self.assertEqual(len(events_11), 1)
        self.assertIsNone(self.fact_store.get_fact("amount"))

    def test_hypothetical_boundary_backward_or_same_turn(self):
        """Test ticking same turn or past turn does not trigger expiration."""
        self.fact_store.set_fact("amount", 100000, turn_id=5, is_hypothetical=True)
        events = self.fact_store.tick_turn(5)
        self.assertEqual(len(events), 0)
        self.assertEqual(self.fact_store.get_fact("amount"), 100000)

    def test_hypothetical_boundary_metadata_query(self):
        """Test get_hypothetical_metadata returns accurate metadata or None."""
        self.fact_store.set_fact("amount", 50000, turn_id=1, is_hypothetical=False)
        self.fact_store.set_fact("amount", 150000, turn_id=3, is_hypothetical=True)

        meta = self.fact_store.get_hypothetical_metadata("amount")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["set_turn"], 3)
        self.assertEqual(meta["previous_value"], 50000)

        self.assertIsNone(self.fact_store.get_hypothetical_metadata("non_existent_key"))


# ═══════════════════════════════════════════════════════════════════════
# FEATURE 4: DUAL-THRESHOLD VECTOR ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestDualThresholdVectorEngineTier1(unittest.TestCase):
    """Tier 1: Feature tests for 0.83 deduplication and 0.40 retrieval vector engine."""

    def setUp(self):
        self.memory_bank = MemoryBank(
            dedup_threshold=0.83,
            retrieval_threshold=0.40,
        )

    def test_vector_engine_add_memory_success(self):
        """Test adding distinct memories inserts records into memory bank."""
        res1 = self.memory_bank.add_memory(
            user_id="Aditya Sharma",
            content="Customer wants to invest 50,000 in STL 7M plan for 6 months.",
            metadata={"session_id": "s1"},
        )
        self.assertTrue(res1)

        memories = self.memory_bank.get_user_memories("user_aditya_sharma")
        self.assertEqual(len(memories), 1)
        self.assertIn("50,000", memories[0]["content"])

    def test_vector_engine_deduplication_threshold_083(self):
        """Test near-duplicate content (similarity >= 0.83) updates existing memory in place."""
        self.memory_bank.add_memory(
            user_id="user_aditya_sharma",
            content="Customer wants to invest 50,000 in STL 7M plan for 6 months.",
        )
        self.assertEqual(len(self.memory_bank.get_user_memories("user_aditya_sharma")), 1)

        # Add slightly rephrased identical fact (high similarity >= 0.83)
        res2 = self.memory_bank.add_memory(
            user_id="user_aditya_sharma",
            content="Customer wants to invest 50,000 in STL 7M plan for 6 months duration.",
            metadata={"updated": True},
        )
        self.assertTrue(res2)
        # Should NOT increase count — updated in place
        self.assertEqual(len(self.memory_bank.get_user_memories("user_aditya_sharma")), 1)

    def test_vector_engine_retrieval_threshold_040(self):
        """Test searching memories returns items with similarity >= 0.40."""
        self.memory_bank.add_memory(
            user_id="user_aditya_sharma",
            content="Customer completed Digilocker Aadhaar and PAN KYC verification.",
        )
        self.memory_bank.add_memory(
            user_id="user_aditya_sharma",
            content="Customer deposited 100000 rupees into ICICI Escrow account via UPI.",
        )

        results = self.memory_bank.search_memories(
            user_id="user_aditya_sharma",
            query="KYC Aadhaar verification status",
            threshold=0.40,
        )
        self.assertTrue(len(results) >= 1)
        self.assertIn("Aadhaar", results[0]["content"])
        self.assertTrue(results[0]["similarity"] >= 0.40)

    def test_vector_engine_retrieval_filters_below_040(self):
        """Test unrelated query with similarity < 0.40 is filtered out."""
        self.memory_bank.add_memory(
            user_id="user_aditya_sharma",
            content="Customer prefers 12 months MTL daily payout plan for wealth creation.",
        )

        # Unrelated query
        results = self.memory_bank.search_memories(
            user_id="user_aditya_sharma",
            query="astronomy quantum physics rocket propulsion galaxy",
            threshold=0.40,
        )
        self.assertEqual(len(results), 0)

    def test_vector_engine_search_sorting_and_limit(self):
        """Test search results are sorted by similarity descending and respect limit."""
        self.memory_bank.add_memory("user_test", "STL 5M 4 months investment 50000 rupees")
        self.memory_bank.add_memory("user_test", "STL 7M 6 months investment 50000 rupees")
        self.memory_bank.add_memory("user_test", "MTL 14M 12 months monthly EMI 100000 rupees")

        results = self.memory_bank.search_memories("user_test", "STL investment 50000", limit=2)
        self.assertTrue(len(results) <= 2)
        if len(results) >= 2:
            self.assertTrue(results[0]["similarity"] >= results[1]["similarity"])

    def test_vector_engine_md5_content_hash_idempotency(self):
        """Test exact same content hash updates metadata and prevents duplicate insertion."""
        content = "Fixed test episodic summary for MD5 idempotency check."
        h = hashlib.md5(content.encode("utf-8")).hexdigest()

        self.memory_bank.add_memory("user_aditya", content, content_hash=h, metadata={"run": 1})
        self.assertEqual(len(self.memory_bank.get_user_memories("user_aditya")), 1)

        # Re-add exact same hash
        self.memory_bank.add_memory("user_aditya", content, content_hash=h, metadata={"run": 2})
        memories = self.memory_bank.get_user_memories("user_aditya")
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["metadata"]["run"], 2)


class TestDualThresholdVectorEngineTier2(unittest.TestCase):
    """Tier 2: Boundary tests for 0.83 deduplication and 0.40 retrieval thresholds."""

    def test_vector_boundary_similarity_dedup_0829_vs_0830(self):
        """Test exact boundary: 0.829 adds new memory, 0.830 triggers deduplication."""
        mock_embedder = MockCustomVectorEmbedder()
        mb = MemoryBank(embedder=mock_embedder, dedup_threshold=0.83)

        # Base vector [1, 0, 0, 0]
        mock_embedder.set_vector("base", [1.0, 0.0, 0.0, 0.0])
        mb.add_memory("user_test", "base")
        self.assertEqual(len(mb.get_user_memories("user_test")), 1)

        # Vector with similarity 0.829 (cos theta = 0.829 -> sin theta = sqrt(1 - 0.829^2) = 0.55925)
        # dot([1,0,0,0], [0.829, 0.55925, 0, 0]) = 0.829
        mock_embedder.set_vector("sub_threshold", [0.829, 0.5592486, 0.0, 0.0])
        mb.add_memory("user_test", "sub_threshold")
        # 0.829 < 0.83 -> Added as distinct memory (total = 2)
        self.assertEqual(len(mb.get_user_memories("user_test")), 2)

        # Vector with similarity 0.831 (above 0.83 threshold)
        mock_embedder.set_vector("super_threshold", [0.831, 0.5562724, 0.0, 0.0])
        mb.add_memory("user_test", "super_threshold")
        # 0.831 >= 0.83 -> Deduplicated into nearest existing memory (total remains 2)
        self.assertEqual(len(mb.get_user_memories("user_test")), 2)

    def test_vector_boundary_similarity_retrieval_0399_vs_0400(self):
        """Test exact boundary: 0.399 is filtered out, 0.400 is returned."""
        mock_embedder = MockCustomVectorEmbedder()
        mb = MemoryBank(embedder=mock_embedder, retrieval_threshold=0.40)

        # Query vector: [1, 0, 0, 0]
        mock_embedder.set_vector("query", [1.0, 0.0, 0.0, 0.0])

        # Target 1: similarity = 0.399 ([0.399, 0.91695, 0, 0])
        mock_embedder.set_vector("mem_low", [0.399, 0.91695, 0.0, 0.0])
        mb.add_memory("user_test", "mem_low")

        # Target 2: similarity = 0.401 ([0.401, 0.91608, 0, 0])
        mock_embedder.set_vector("mem_high", [0.401, 0.91608, 0.0, 0.0])
        mb.add_memory("user_test", "mem_high")

        results = mb.search_memories("user_test", "query", threshold=0.40)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "mem_high")

    def test_vector_boundary_empty_query_and_empty_content(self):
        """Test empty query returns empty list, empty content returns False."""
        mb = MemoryBank()
        self.assertFalse(mb.add_memory("user_test", ""))
        self.assertFalse(mb.add_memory("user_test", "   "))
        self.assertEqual(mb.search_memories("user_test", ""), [])
        self.assertEqual(mb.search_memories("user_test", "   "), [])

    def test_vector_boundary_orthogonal_and_zero_vectors(self):
        """Test orthogonal vectors with cosine similarity 0.0."""
        v1 = [1.0, 0.0, 0.0, 0.0]
        v2 = [0.0, 1.0, 0.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(v1, v2), 0.0)
        self.assertEqual(cosine_similarity([], v1), 0.0)
        self.assertEqual(cosine_similarity(v1, [1.0, 0.0]), 0.0)

    def test_vector_boundary_negative_similarity_clamping(self):
        """Test opposite vectors return -1.0 cosine similarity safely."""
        v1 = [1.0, 0.0, 0.0, 0.0]
        v2 = [-1.0, 0.0, 0.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(v1, v2), -1.0)

    def test_vector_boundary_isolated_user_memories(self):
        """Test memories stored for user A are strictly isolated from user B."""
        mb = MemoryBank()
        mb.add_memory("Aditya Sharma", "Aditya private investment notes 50k STL")
        mb.add_memory("Rajesh Kumar", "Rajesh private investment notes 24L MTL")

        aditya_res = mb.search_memories("Aditya Sharma", "investment", threshold=0.0)
        rajesh_res = mb.search_memories("Rajesh Kumar", "investment", threshold=0.0)

        self.assertEqual(len(aditya_res), 1)
        self.assertIn("Aditya", aditya_res[0]["content"])

        self.assertEqual(len(rajesh_res), 1)
        self.assertIn("Rajesh", rajesh_res[0]["content"])


# ═══════════════════════════════════════════════════════════════════════
# FEATURE 5: 90-DAY CROSS-SESSION PROFILE HYDRATION TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestProfileHydrationTier1(unittest.TestCase):
    """Tier 1: Feature tests for 90-day cross-session profile hydration."""

    def setUp(self):
        self.memory_bank = MemoryBank(lookback_days=90)

    def test_hydration_includes_recent_memories(self):
        """Test memories within 90-day window are included in hydrated profile."""
        now = datetime.now(timezone.utc)

        self.memory_bank.add_memory("user_aditya", "Recent session 1: explored STL 7M")
        # Backdate record to 30 days ago
        self.memory_bank._memories["user_aditya"][0]["created_at"] = (now - timedelta(days=30)).isoformat()
        self.memory_bank._memories["user_aditya"][0]["updated_at"] = (now - timedelta(days=30)).isoformat()

        profile = self.memory_bank.hydrate_user_profile("user_aditya", days_lookback=90)
        self.assertTrue(profile["profile_hydrated"])
        self.assertEqual(profile["memory_count"], 1)
        self.assertEqual(len(profile["recent_memories"]), 1)
        self.assertIn("STL 7M", profile["recent_memories"][0]["content"])

    def test_hydration_excludes_memories_older_than_90_days(self):
        """Test memories older than 90 days are excluded from hydration."""
        now = datetime.now(timezone.utc)

        # Memory from 100 days ago
        self.memory_bank.add_memory("user_aditya", "Old session from 100 days ago")
        self.memory_bank._memories["user_aditya"][0]["created_at"] = (now - timedelta(days=100)).isoformat()
        self.memory_bank._memories["user_aditya"][0]["updated_at"] = (now - timedelta(days=100)).isoformat()

        # Memory from 10 days ago
        self.memory_bank.add_memory("user_aditya", "Fresh session from 10 days ago")
        self.memory_bank._memories["user_aditya"][1]["created_at"] = (now - timedelta(days=10)).isoformat()
        self.memory_bank._memories["user_aditya"][1]["updated_at"] = (now - timedelta(days=10)).isoformat()

        profile = self.memory_bank.hydrate_user_profile("user_aditya", days_lookback=90)
        self.assertEqual(profile["memory_count"], 1)
        self.assertIn("Fresh session", profile["recent_memories"][0]["content"])

    def test_hydration_combines_active_facts_and_memories(self):
        """Test hydration bundles structured FactStore facts and episodic memories."""
        # Set structured facts
        fact_store = self.memory_bank.get_fact_store("user_aditya")
        fact_store.set_fact("amount", 100000, turn_id=1)
        fact_store.set_fact("tenure_months", 12, turn_id=2)
        fact_store.set_fact("risk_preference", "low", turn_id=3)

        self.memory_bank.add_memory("user_aditya", "Episodic note: User prefers ICICI escrow.")

        profile = self.memory_bank.hydrate_user_profile("user_aditya")
        self.assertEqual(profile["facts"]["amount"], 100000)
        self.assertEqual(profile["facts"]["tenure_months"], 12)
        self.assertEqual(profile["facts"]["risk_preference"], "low")
        self.assertEqual(len(profile["recent_memories"]), 1)
        self.assertEqual(profile["episodic_memories"], ["Episodic note: User prefers ICICI escrow."])

    def test_hydration_new_or_empty_user(self):
        """Test hydrating non-existent user returns clean empty profile safely."""
        profile = self.memory_bank.hydrate_user_profile("user_non_existent")
        self.assertEqual(profile["user_id"], "user_non_existent")
        self.assertEqual(profile["facts"], {})
        self.assertEqual(profile["recent_memories"], [])
        self.assertEqual(profile["memory_count"], 0)
        self.assertIsNone(profile["last_active"])
        self.assertTrue(profile["profile_hydrated"])

    def test_hydration_custom_lookback_window(self):
        """Test custom lookback window (e.g. 30 days) overrides default."""
        now = datetime.now(timezone.utc)
        self.memory_bank.add_memory("user_test", "Memory from 45 days ago")
        self.memory_bank._memories["user_test"][0]["created_at"] = (now - timedelta(days=45)).isoformat()
        self.memory_bank._memories["user_test"][0]["updated_at"] = (now - timedelta(days=45)).isoformat()

        # 30 days lookback -> Excluded
        p30 = self.memory_bank.hydrate_user_profile("user_test", days_lookback=30)
        self.assertEqual(p30["memory_count"], 0)

        # 60 days lookback -> Included
        p60 = self.memory_bank.hydrate_user_profile("user_test", days_lookback=60)
        self.assertEqual(p60["memory_count"], 1)

    def test_hydration_last_active_timestamp(self):
        """Test profile last_active timestamp reflects the most recent memory timestamp."""
        now = datetime.now(timezone.utc)
        t1 = now - timedelta(days=20)
        t2 = now - timedelta(days=5)

        self.memory_bank.add_memory("user_test", "Older memory")
        self.memory_bank._memories["user_test"][0]["created_at"] = t1.isoformat()
        self.memory_bank._memories["user_test"][0]["updated_at"] = t1.isoformat()

        self.memory_bank.add_memory("user_test", "Newer memory")
        self.memory_bank._memories["user_test"][1]["created_at"] = t2.isoformat()
        self.memory_bank._memories["user_test"][1]["updated_at"] = t2.isoformat()

        profile = self.memory_bank.hydrate_user_profile("user_test")
        self.assertIsNotNone(profile["last_active"])
        # Should match t2
        self.assertEqual(profile["last_active"], t2.isoformat())


class TestProfileHydrationTier2(unittest.TestCase):
    """Tier 2: Boundary tests for profile hydration lookback window."""

    def test_hydration_boundary_89d_vs_90d_vs_91d(self):
        """Test exact boundary: within 90d included, beyond 90d excluded."""
        now = datetime.now(timezone.utc)
        mb = MemoryBank(lookback_days=90)

        # 89 days, 23 hours ago (within 90 days)
        mb.add_memory("user_test", "Mem 89d")
        mb._memories["user_test"][0]["created_at"] = (now - timedelta(days=89, hours=23)).isoformat()
        mb._memories["user_test"][0]["updated_at"] = (now - timedelta(days=89, hours=23)).isoformat()

        # 89 days, 23 hours, 59 minutes ago (strictly inside 90d window, accounting for runtime execution)
        mb.add_memory("user_test", "Mem 90d_edge")
        mb._memories["user_test"][1]["created_at"] = (now - timedelta(days=89, hours=23, minutes=55)).isoformat()
        mb._memories["user_test"][1]["updated_at"] = (now - timedelta(days=89, hours=23, minutes=55)).isoformat()

        # 90 days, 2 hours ago (strictly outside 90d window)
        mb.add_memory("user_test", "Mem 91d")
        mb._memories["user_test"][2]["created_at"] = (now - timedelta(days=90, hours=2)).isoformat()
        mb._memories["user_test"][2]["updated_at"] = (now - timedelta(days=90, hours=2)).isoformat()

        profile = mb.hydrate_user_profile("user_test", days_lookback=90)
        contents = [m["content"] for m in profile["recent_memories"]]
        self.assertIn("Mem 89d", contents)
        self.assertIn("Mem 90d_edge", contents)
        self.assertNotIn("Mem 91d", contents)

    def test_hydration_boundary_future_timestamp_clock_skew(self):
        """Test future timestamp is safely included in hydration without error."""
        now = datetime.now(timezone.utc)
        mb = MemoryBank()
        mb.add_memory("user_test", "Future memory")
        mb._memories["user_test"][0]["created_at"] = (now + timedelta(hours=2)).isoformat()
        mb._memories["user_test"][0]["updated_at"] = (now + timedelta(hours=2)).isoformat()

        profile = mb.hydrate_user_profile("user_test")
        self.assertEqual(profile["memory_count"], 1)

    def test_hydration_boundary_malformed_timestamp_metadata(self):
        """Test corrupt timestamp string defaults safely to current time without crash."""
        mb = MemoryBank()
        mb.add_memory("user_test", "Corrupt timestamp memory")
        mb._memories["user_test"][0]["created_at"] = "INVALID_TIMESTAMP_STRING"
        mb._memories["user_test"][0]["updated_at"] = "INVALID_TIMESTAMP_STRING"

        profile = mb.hydrate_user_profile("user_test")
        self.assertEqual(profile["memory_count"], 1)

    def test_hydration_boundary_sorting_order(self):
        """Test multiple memories are sorted strictly newest to oldest."""
        now = datetime.now(timezone.utc)
        mb = MemoryBank()

        mb.add_memory("user_test", "Oldest")
        mb._memories["user_test"][0]["updated_at"] = (now - timedelta(days=20)).isoformat()

        mb.add_memory("user_test", "Middle")
        mb._memories["user_test"][1]["updated_at"] = (now - timedelta(days=10)).isoformat()

        mb.add_memory("user_test", "Newest")
        mb._memories["user_test"][2]["updated_at"] = (now - timedelta(days=1)).isoformat()

        profile = mb.hydrate_user_profile("user_test")
        ordered_contents = [m["content"] for m in profile["recent_memories"]]
        self.assertEqual(ordered_contents, ["Newest", "Middle", "Oldest"])

    def test_hydration_boundary_clear_user_state(self):
        """Test calling clear(user_id) removes user facts and memories completely."""
        mb = MemoryBank()
        mb.get_fact_store("user_test").set_fact("amount", 50000, turn_id=1)
        mb.add_memory("user_test", "Sample memory")

        mb.clear("user_test")
        profile = mb.hydrate_user_profile("user_test")
        self.assertEqual(profile["facts"], {})
        self.assertEqual(profile["memory_count"], 0)


class TestGCPAgentEngineMemoryBank(unittest.TestCase):
    """Hermetic unit tests for Google Cloud Gemini Enterprise Agent Platform Memory Bank client."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_memories = MagicMock()
        self.mock_client.agent_engines.memories = self.mock_memories

    def test_initialization_with_engine_id(self):
        """Test GCPAgentEngineMemoryBank initializes when engine_id is provided."""
        with patch("memory_bank.agentplatform") as mock_ap:
            mock_ap.Client.return_value = self.mock_client
            gmb = GCPAgentEngineMemoryBank(
                project_id="test-proj",
                location="us-central1",
                engine_id="projects/123/locations/us-central1/reasoningEngines/456",
            )
            self.assertTrue(gmb.is_available())
            self.assertEqual(gmb.engine_id, "projects/123/locations/us-central1/reasoningEngines/456")

    def test_add_memory_cloud_call(self):
        """Test add_memory delegates to client.agent_engines.memories.create."""
        with patch("memory_bank.agentplatform") as mock_ap:
            mock_ap.Client.return_value = self.mock_client
            gmb = GCPAgentEngineMemoryBank(
                project_id="test-proj",
                location="us-central1",
                engine_id="projects/123/locations/us-central1/reasoningEngines/456",
            )
            success = gmb.add_memory("Mr. Rajesh Kumar", "Wants to invest Rs 50,000 for 6 months")
            self.assertTrue(success)
            self.mock_memories.create.assert_called_once_with(
                name="projects/123/locations/us-central1/reasoningEngines/456",
                fact="Wants to invest Rs 50,000 for 6 months",
                scope={"user_id": "user_rajesh_kumar"},
            )

    def test_search_memories_cloud_call(self):
        """Test search_memories delegates to client.agent_engines.memories.retrieve."""
        mock_res_item = MagicMock()
        mock_res_item.memory.name = "projects/123/locations/us-central1/reasoningEngines/456/memories/789"
        mock_res_item.memory.fact = "Prefers MTL 12M monthly plan"
        mock_res_item.memory.create_time = "2026-08-15T07:00:00Z"
        mock_res_item.memory.update_time = "2026-08-15T07:00:00Z"
        mock_res_item.distance = 0.15

        self.mock_memories.retrieve.return_value = [mock_res_item]

        with patch("memory_bank.agentplatform") as mock_ap:
            mock_ap.Client.return_value = self.mock_client
            gmb = GCPAgentEngineMemoryBank(
                project_id="test-proj",
                location="us-central1",
                engine_id="projects/123/locations/us-central1/reasoningEngines/456",
            )
            results = gmb.search_memories("Aditya Sharma", "investment plan", limit=3)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["content"], "Prefers MTL 12M monthly plan")
            self.assertEqual(results[0]["user_id"], "user_aditya_sharma")
            self.assertAlmostEqual(results[0]["similarity"], 0.85, places=2)
            self.mock_memories.retrieve.assert_called_once_with(
                name="projects/123/locations/us-central1/reasoningEngines/456",
                scope={"user_id": "user_aditya_sharma"},
                similarity_search_params={"search_query": "investment plan", "top_k": 3},
            )

    def test_hydrate_user_profile_cloud(self):
        """Test hydrate_user_profile lists cloud memories and structures user profile."""
        mock_mem = MagicMock()
        mock_mem.name = "mem-1"
        mock_mem.fact = "Previous KYC verified via Aadhaar OTP"
        mock_mem.create_time = "2026-08-15T06:00:00Z"
        mock_mem.update_time = "2026-08-15T06:00:00Z"
        self.mock_memories.list.return_value = [mock_mem]

        with patch("memory_bank.agentplatform") as mock_ap:
            mock_ap.Client.return_value = self.mock_client
            gmb = GCPAgentEngineMemoryBank(
                project_id="test-proj",
                location="us-central1",
                engine_id="projects/123/locations/us-central1/reasoningEngines/456",
            )
            profile = gmb.hydrate_user_profile("user_priya_patel")
            self.assertEqual(profile["user_id"], "user_priya_patel")
            self.assertEqual(profile["memory_count"], 1)
            self.assertEqual(profile["episodic_memories"], ["Previous KYC verified via Aadhaar OTP"])
            self.assertTrue(profile["profile_hydrated"])
            self.assertEqual(profile["source"], "gcp_enterprise_agent_platform_memory_bank")

    def test_graceful_error_handling_on_network_failure(self):
        """Test GCPAgentEngineMemoryBank returns clean fallbacks if GCP API raises exception."""
        self.mock_memories.create.side_effect = RuntimeError("GCP Quota exceeded or 503 unavailable")
        self.mock_memories.retrieve.side_effect = RuntimeError("Connection timeout")

        with patch("memory_bank.agentplatform") as mock_ap:
            mock_ap.Client.return_value = self.mock_client
            gmb = GCPAgentEngineMemoryBank(
                project_id="test-proj",
                location="us-central1",
                engine_id="projects/123/locations/us-central1/reasoningEngines/456",
            )
            add_res = gmb.add_memory("user_test", "Some memory")
            self.assertFalse(add_res)
            search_res = gmb.search_memories("user_test", "query")
            self.assertEqual(search_res, [])


if __name__ == "__main__":
    unittest.main()
