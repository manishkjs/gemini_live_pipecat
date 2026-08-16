"""Adversarial Stress Test Suite & Oracles for Milestone M1 (Memory Bank Core & Lexical Identity).

Rigorous stress-testing of `server/memory_bank.py` across:
1. FactStore 6-turn TTL Boundaries (turn 5 kept, turn 6 expired, hypothetical overwriting confirmed & reverting, multiple facts at interleaved turns, differential fuzzing against oracle, 10,000-step marathon).
2. Dual-Threshold Vector Math (exact 0.830 dedup boundary vs 0.82999, exact 0.400 retrieval boundary vs 0.39999, ranking order, MD5 idempotency, extreme vectors, stopword handling, high-dimensional orthogonality).
3. Spoken Lexical User Normalization (honorific permutations, mixed Hindi/English phrases, special characters, whitespace fuzzing, idempotency, anonymous fallbacks).
4. 90-Day Cross-Session Profile Hydration (boundary dates, facts+memories bundling, empty state, corrupt metadata, multi-user isolation).
"""

from __future__ import annotations

import hashlib
import math
import os
import random
import sys
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

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


class ControlledVectorEmbedder:
    """Mock embedder providing exact controlled unit vectors for analytical boundary testing."""

    def __init__(self):
        self._map: Dict[str, List[float]] = {}

    def set_vector(self, text: str, vec: List[float]) -> None:
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            self._map[text.strip()] = [x / norm for x in vec]
        else:
            self._map[text.strip()] = list(vec)

    def embed(self, text: str) -> List[float]:
        clean = text.strip()
        if clean in self._map:
            return self._map[clean]
        # Deterministic MD5 unit vector fallback
        h = hashlib.md5(clean.encode("utf-8")).digest()
        raw = [float(b) for b in h[:8]]
        norm = math.sqrt(sum(x * x for x in raw))
        return [x / norm for x in raw]


# ═══════════════════════════════════════════════════════════════════════
# 1. FACTSTORE 6-TURN TTL BOUNDARY & DIFFERENTIAL ORACLE TESTS
# ═══════════════════════════════════════════════════════════════════════

class NaiveFactStoreOracle:
    """Independent naive brute-force oracle for FactStore behavior."""

    def __init__(self, ttl: int = 6):
        self.ttl = ttl
        # key -> {"confirmed": value, "hypothetical": value, "set_turn": int}
        self.store: Dict[str, Dict[str, Any]] = {}
        self.history: List[Dict[str, Any]] = []

    def set_fact(self, key: str, value: Any, turn_id: int, is_hypothetical: bool = False):
        if key in KEY_ALIASES:
            key = KEY_ALIASES[key]
        if key not in CANONICAL_FACT_KEYS:
            raise ValueError(f"Invalid key {key}")

        if key not in self.store:
            self.store[key] = {"confirmed": None, "hypothetical": None, "set_turn": None}

        if is_hypothetical:
            self.store[key]["hypothetical"] = value
            self.store[key]["set_turn"] = turn_id
        else:
            self.store[key]["confirmed"] = value
            self.store[key]["hypothetical"] = None
            self.store[key]["set_turn"] = None

    def tick_turn(self, turn_id: int):
        for key, data in list(self.store.items()):
            if data["hypothetical"] is not None and data["set_turn"] is not None:
                if (turn_id - data["set_turn"]) >= self.ttl:
                    # Expire hypothetical
                    data["hypothetical"] = None
                    data["set_turn"] = None

    def get_fact(self, key: str) -> Optional[Any]:
        if key in KEY_ALIASES:
            key = KEY_ALIASES[key]
        if key not in self.store:
            return None
        data = self.store[key]
        if data["hypothetical"] is not None:
            return data["hypothetical"]
        return data["confirmed"]

    def get_all_facts(self) -> Dict[str, Any]:
        res = {}
        for k in CANONICAL_FACT_KEYS:
            val = self.get_fact(k)
            if val is not None:
                res[k] = val
        return res


class TestFactStoreAdversarialBoundaries(unittest.TestCase):
    """Adversarial stress testing of FactStore TTL and edge cases."""

    def test_ttl_exact_boundary_delta_5_kept_delta_6_expired(self):
        """Verify exact boundary: delta=5 remains active, delta=6 expires."""
        fs = FactStore(ttl_turns=6)
        fs.set_fact("amount", 500000, turn_id=10, is_hypothetical=True)

        # Turn 10 to 15 (delta 0 to 5)
        for t in range(10, 16):
            events = fs.tick_turn(t)
            self.assertEqual(len(events), 0, f"Turn {t} (delta {t-10}) should not trigger expiration")
            self.assertEqual(fs.get_fact("amount"), 500000)
            self.assertTrue(fs.is_fact_hypothetical("amount"))

        # Turn 16 (delta = 16 - 10 = 6) -> Must expire
        events_16 = fs.tick_turn(16)
        self.assertEqual(len(events_16), 1)
        self.assertEqual(events_16[0]["key"], "amount")
        self.assertEqual(events_16[0]["action"], "expire_hypothetical")
        self.assertIsNone(fs.get_fact("amount"))
        self.assertFalse(fs.is_fact_hypothetical("amount"))

    def test_hypothetical_overwrite_of_confirmed_and_revert(self):
        """Verify hypothetical overwrites confirmed value and cleanly reverts upon TTL expiration."""
        fs = FactStore(ttl_turns=6)
        # Turn 1: Confirmed amount 25,000
        fs.set_fact("amount", 25000, turn_id=1, is_hypothetical=False)
        self.assertEqual(fs.get_fact("amount"), 25000)
        self.assertFalse(fs.is_fact_hypothetical("amount"))

        # Turn 4: User explores hypothetical 10,00,000
        fs.set_fact("amount", 1000000, turn_id=4, is_hypothetical=True)
        self.assertEqual(fs.get_fact("amount"), 1000000)
        self.assertTrue(fs.is_fact_hypothetical("amount"))

        # Turn 5 to 9 (delta 1 to 5) -> value stays 10,00,000
        for t in range(5, 10):
            fs.tick_turn(t)
            self.assertEqual(fs.get_fact("amount"), 1000000)

        # Turn 10 (delta = 10 - 4 = 6) -> reverts to confirmed base 25,000
        events_10 = fs.tick_turn(10)
        self.assertEqual(len(events_10), 1)
        self.assertEqual(events_10[0]["old_value"], 1000000)
        self.assertEqual(events_10[0]["new_value"], 25000)
        self.assertEqual(fs.get_fact("amount"), 25000)
        self.assertFalse(fs.is_fact_hypothetical("amount"))

        # Advance further to turn 30 -> remains 25,000
        fs.tick_turn(30)
        self.assertEqual(fs.get_fact("amount"), 25000)

    def test_chained_hypothetical_updates_preserve_original_confirmed_base(self):
        """Verify multiple chained hypothetical updates preserve the true base confirmed value."""
        fs = FactStore(ttl_turns=6)
        # Turn 1: Base confirmed tenure = 12
        fs.set_fact("tenure_months", 12, turn_id=1, is_hypothetical=False)

        # Turn 2: First hypothetical exploration tenure = 3
        fs.set_fact("tenure_months", 3, turn_id=2, is_hypothetical=True)
        self.assertEqual(fs.get_fact("tenure_months"), 3)

        # Turn 5: Second hypothetical exploration tenure = 6 (overwriting previous hypothetical)
        fs.set_fact("tenure_months", 6, turn_id=5, is_hypothetical=True)
        self.assertEqual(fs.get_fact("tenure_months"), 6)

        # Turn 8: Delta from turn 2 is 6, but delta from turn 5 is only 3 -> MUST NOT EXPIRE
        events_8 = fs.tick_turn(8)
        self.assertEqual(len(events_8), 0)
        self.assertEqual(fs.get_fact("tenure_months"), 6)

        # Turn 11: Delta from turn 5 is 6 -> Expires and reverts to 12 (NOT 3!)
        events_11 = fs.tick_turn(11)
        self.assertEqual(len(events_11), 1)
        self.assertEqual(fs.get_fact("tenure_months"), 12)
        self.assertFalse(fs.is_fact_hypothetical("tenure_months"))

    def test_interleaved_multiple_facts_expiring_at_different_turns(self):
        """Verify multiple facts with different set turns expire independently at exact turns."""
        fs = FactStore(ttl_turns=6)
        # Fact 1: amount set at turn 1 (expires turn 7)
        fs.set_fact("amount", 100000, turn_id=1, is_hypothetical=True)
        # Fact 2: city set at turn 3 (expires turn 9)
        fs.set_fact("city", "Mumbai", turn_id=3, is_hypothetical=True)
        # Fact 3: goal set at turn 6 (expires turn 12)
        fs.set_fact("goal", "Retirement", turn_id=6, is_hypothetical=True)
        # Fact 4: occupation confirmed at turn 2 (never expires)
        fs.set_fact("occupation", "Doctor", turn_id=2, is_hypothetical=False)

        # Turn 6 check
        fs.tick_turn(6)
        self.assertEqual(len(fs.get_all_facts()), 4)

        # Turn 7: amount expires
        ev_7 = fs.tick_turn(7)
        self.assertEqual(len(ev_7), 1)
        self.assertEqual(ev_7[0]["key"], "amount")
        self.assertIsNone(fs.get_fact("amount"))
        self.assertEqual(fs.get_fact("city"), "Mumbai")
        self.assertEqual(fs.get_fact("goal"), "Retirement")
        self.assertEqual(fs.get_fact("occupation"), "Doctor")

        # Turn 9: city expires
        ev_9 = fs.tick_turn(9)
        self.assertEqual(len(ev_9), 1)
        self.assertEqual(ev_9[0]["key"], "city")
        self.assertIsNone(fs.get_fact("city"))
        self.assertEqual(fs.get_fact("goal"), "Retirement")

        # Turn 12: goal expires
        ev_12 = fs.tick_turn(12)
        self.assertEqual(len(ev_12), 1)
        self.assertEqual(ev_12[0]["key"], "goal")
        self.assertIsNone(fs.get_fact("goal"))

        # Confirmed fact remains forever
        self.assertEqual(fs.get_fact("occupation"), "Doctor")
        self.assertEqual(fs.get_all_facts(), {"occupation": "Doctor"})

    def test_differential_fuzzing_against_oracle_5000_steps(self):
        """Differential fuzzing: Compare FactStore state with NaiveFactStoreOracle across 5000 random actions."""
        rng = random.Random(42)
        fs = FactStore(ttl_turns=6)
        oracle = NaiveFactStoreOracle(ttl=6)

        keys = list(CANONICAL_FACT_KEYS) + list(KEY_ALIASES.keys())
        current_turn = 1

        for step in range(5000):
            action = rng.choice(["set_confirmed", "set_hypothetical", "tick", "clear_key", "query"])

            if action == "set_confirmed":
                k = rng.choice(keys)
                val = f"val_{rng.randint(1, 1000)}"
                fs.set_fact(k, val, turn_id=current_turn, is_hypothetical=False)
                oracle.set_fact(k, val, turn_id=current_turn, is_hypothetical=False)

            elif action == "set_hypothetical":
                k = rng.choice(keys)
                val = f"hyp_{rng.randint(1, 1000)}"
                fs.set_fact(k, val, turn_id=current_turn, is_hypothetical=True)
                oracle.set_fact(k, val, turn_id=current_turn, is_hypothetical=True)

            elif action == "tick":
                current_turn += rng.randint(1, 4)
                fs.tick_turn(current_turn)
                oracle.tick_turn(current_turn)

            elif action == "clear_key":
                k = rng.choice(keys)
                fs.set_fact(k, None, turn_id=current_turn, is_hypothetical=False)
                oracle.set_fact(k, None, turn_id=current_turn, is_hypothetical=False)

            # Verification assertion against oracle
            for canonical in CANONICAL_FACT_KEYS:
                actual_val = fs.get_fact(canonical)
                expected_val = oracle.get_fact(canonical)
                self.assertEqual(
                    actual_val,
                    expected_val,
                    f"Mismatch at step {step}, turn {current_turn} for key '{canonical}': actual={actual_val}, expected={expected_val}",
                )

            self.assertEqual(fs.get_all_facts(), oracle.get_all_facts())


# ═══════════════════════════════════════════════════════════════════════
# 2. DUAL-THRESHOLD VECTOR MATH & RETRIEVAL ORACLE TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestDualThresholdVectorAdversarial(unittest.TestCase):
    """Adversarial testing of vector math and strict threshold boundaries."""

    def test_exact_deduplication_boundary_082999_vs_083000(self):
        """Test precision boundary at 0.83 deduplication threshold."""
        embedder = ControlledVectorEmbedder()
        mb = MemoryBank(embedder=embedder, dedup_threshold=0.83)

        # Base vector
        embedder.set_vector("base_entry", [1.0, 0.0, 0.0, 0.0])
        mb.add_memory("user_test", "base_entry")
        self.assertEqual(len(mb.get_user_memories("user_test")), 1)

        # 0.829999: Sub-threshold -> Must be inserted as separate memory record
        cos_val_sub = 0.829999
        sin_val_sub = math.sqrt(1.0 - cos_val_sub * cos_val_sub)
        embedder.set_vector("near_sub", [cos_val_sub, sin_val_sub, 0.0, 0.0])
        mb.add_memory("user_test", "near_sub")
        self.assertEqual(len(mb.get_user_memories("user_test")), 2)

        # 0.830001: Above threshold -> Must deduplicate in place (count remains 2)
        cos_val_sup = 0.830001
        sin_val_sup = math.sqrt(1.0 - cos_val_sup * cos_val_sup)
        embedder.set_vector("near_sup", [cos_val_sup, sin_val_sup, 0.0, 0.0])
        mb.add_memory("user_test", "near_sup")
        self.assertEqual(len(mb.get_user_memories("user_test")), 2)

    def test_exact_retrieval_boundary_039999_vs_040000(self):
        """Test precision boundary at 0.40 retrieval threshold."""
        embedder = ControlledVectorEmbedder()
        mb = MemoryBank(embedder=embedder, retrieval_threshold=0.40)

        embedder.set_vector("query_vec", [1.0, 0.0, 0.0, 0.0])

        # Sub-threshold 0.39999 -> Excluded
        cos_sub = 0.39999
        sin_sub = math.sqrt(1.0 - cos_sub * cos_sub)
        embedder.set_vector("item_below", [cos_sub, sin_sub, 0.0, 0.0])
        mb.add_memory("user_test", "item_below")

        # Super-threshold 0.40001 -> Included
        cos_sup = 0.40001
        sin_sup = math.sqrt(1.0 - cos_sup * cos_sup)
        embedder.set_vector("item_above", [cos_sup, sin_sup, 0.0, 0.0])
        mb.add_memory("user_test", "item_above")

        results = mb.search_memories("user_test", "query_vec", threshold=0.40)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "item_above")
        self.assertAlmostEqual(results[0]["similarity"], 0.4000, places=3)

    def test_retrieval_ranking_and_limit_oracle(self):
        """Verify retrieval results are strictly ordered descending and capped by limit.
        
        Uses an 8-dimensional space where each memory's non-query component is along an independent
        orthogonal axis, preventing any mutual deduplication between memories while preserving exact
        similarity with the query along axis 0.
        """
        embedder = ControlledVectorEmbedder()
        mb = MemoryBank(embedder=embedder, dedup_threshold=0.83, retrieval_threshold=0.40)

        # Query vector along dim 0: [1, 0, 0, 0, 0, 0, 0, 0]
        q_vec = [1.0] + [0.0] * 7
        embedder.set_vector("q", q_vec)

        # Target similarities with query: 0.90, 0.75, 0.60, 0.45, 0.30, 0.15
        similarities = [0.90, 0.75, 0.60, 0.45, 0.30, 0.15]
        for i, sim in enumerate(similarities):
            # dim 0 = sim, dim (i+1) = sqrt(1 - sim^2), all others = 0
            sin_v = math.sqrt(max(0.0, 1.0 - sim * sim))
            vec = [0.0] * 8
            vec[0] = sim
            vec[i + 1] = sin_v

            # Mutual dot product between any item_i and item_j is sim_i * sim_j <= 0.90 * 0.75 = 0.675 < 0.83
            name = f"mem_sim_{int(sim*100)}"
            embedder.set_vector(name, vec)
            mb.add_memory("user_test", name)

        # All 6 memories must be added as distinct records
        self.assertEqual(len(mb.get_user_memories("user_test")), 6)

        # Query with threshold 0.40 -> Expect 4 items (0.90, 0.75, 0.60, 0.45)
        res_all = mb.search_memories("user_test", "q", threshold=0.40, limit=10)
        self.assertEqual(len(res_all), 4)
        for j in range(len(res_all) - 1):
            self.assertGreaterEqual(res_all[j]["similarity"], res_all[j + 1]["similarity"])

        self.assertEqual(res_all[0]["content"], "mem_sim_90")
        self.assertEqual(res_all[1]["content"], "mem_sim_75")
        self.assertEqual(res_all[2]["content"], "mem_sim_60")
        self.assertEqual(res_all[3]["content"], "mem_sim_45")

        # Query with limit 2 -> Expect top 2
        res_lim2 = mb.search_memories("user_test", "q", threshold=0.40, limit=2)
        self.assertEqual(len(res_lim2), 2)
        self.assertEqual(res_lim2[0]["content"], "mem_sim_90")
        self.assertEqual(res_lim2[1]["content"], "mem_sim_75")

    def test_default_text_embedder_l2_normalization_fuzzing(self):
        """Fuzz DefaultTextEmbedder on diverse Hindi/English strings, ensuring unit L2 norm for non-stopwords."""
        embedder = DefaultTextEmbedder()
        sample_corpus = [
            "Customer wants 5 Lakhs for 12 months STL investment.",
            "KYC verification completed with Aadhaar Digilocker and PAN.",
            "Escrow deposit via ICICI UPI successful.",
            "नमस्ते, मैं 50 हजार रुपये लगाना चाहता हूँ।",
            "Mera naam Priya Patel hai aur mujhe low risk plan chahiye.",
            "Special @#&* chars and numbers 1234567890.",
            "   \t\n messy whitespace and words   ",
            "SingleWord",
        ]

        for text in sample_corpus:
            vec = embedder.embed(text)
            self.assertEqual(len(vec), embedder.DIMENSION)
            norm = math.sqrt(sum(x * x for x in vec))
            self.assertAlmostEqual(norm, 1.0, places=5, msg=f"Vector for '{text}' must have unit norm")

        # Stopword-only string yields zero vector safely
        stopword_vec = embedder.embed("a is the")
        self.assertEqual(sum(stopword_vec), 0.0)

        # Empty string yields zero vector safely
        zero_vec = embedder.embed("")
        self.assertEqual(sum(zero_vec), 0.0)


# ═══════════════════════════════════════════════════════════════════════
# 3. SPOKEN LEXICAL NORMALIZATION ADVERSARIAL CASES
# ═══════════════════════════════════════════════════════════════════════

class TestLexicalNormalizationAdversarial(unittest.TestCase):
    """Adversarial testing of customer name normalization across spoken Hindi/English patterns."""

    def test_conversational_and_honorific_permutations(self):
        """Test comprehensive matrix of spoken greetings, introductions, and honorifics."""
        cases = [
            # Standard
            ("Aditya Sharma", "user_aditya_sharma"),
            ("Rajesh Kumar", "user_rajesh_kumar"),
            ("Priya Patel", "user_priya_patel"),
            # English honorifics
            ("Mr. Aditya Sharma", "user_aditya_sharma"),
            ("Mrs. Sunita Rao", "user_sunita_rao"),
            ("Ms. Ananya Joshi", "user_ananya_joshi"),
            ("Dr. Rajesh Kumar", "user_rajesh_kumar"),
            ("Prof. Amit Patel", "user_amit_patel"),
            ("Sir Deepak Verma", "user_deepak_verma"),
            ("Madam Anita Singh", "user_anita_singh"),
            # Hindi honorifics & titles
            ("Shri Amit Patel", "user_amit_patel"),
            ("Shree Rajesh Kumar", "user_rajesh_kumar"),
            ("Smt. Sunita Rao", "user_sunita_rao"),
            ("Shrimati Sunita Rao", "user_sunita_rao"),
            ("Kumari Pooja", "user_pooja"),
            ("Vikram Singh ji", "user_vikram_singh"),
            ("Deepak jee", "user_deepak"),
            ("Amit Sahab", "user_amit"),
            ("Rajesh saab", "user_rajesh"),
            # Spoken Hindi intros
            ("Mera naam Priya Patel hai", "user_priya_patel"),
            ("Namaste, main Deepak bol raha hoon", "user_deepak"),
            ("Namaskar! Mera naam Rajesh Kumar hai", "user_rajesh_kumar"),
            ("Aap baat kar rahe hain Sanjay Sharma se", "user_sanjay_sharma"),
            ("Haan ji main Aditya baat kar raha hoon", "user_aditya"),
            ("Main Sunita bol rahi hoon", "user_sunita"),
            ("Pranam, mera naam Rohit Gupta hai", "user_rohit_gupta"),
            # Spoken English intros
            ("Hello, this is Sunita Rao speaking", "user_sunita_rao"),
            ("My name is Rohit Gupta", "user_rohit_gupta"),
            ("You are talking to Rajesh Kumar", "user_rajesh_kumar"),
            ("Hi, call me Vikram", "user_vikram"),
            ("I am Dr. Amit Patel", "user_amit_patel"),
            # Mixed Code-Mixing & Punctuation
            ("Namaste, this is Mr. Aditya Sharma speaking from Cymbal", "user_aditya_sharma_from_cymbal"),
            ("Deepak (Investor #42)", "user_deepak_investor_42"),
            ("  --- Priya === Patel +++ ", "user_priya_patel"),
            ("user_aditya_sharma", "user_aditya_sharma"),
            ("user-priya-patel", "user_priya_patel"),
        ]

        for raw_input, expected_key in cases:
            actual_key = normalize_lexical_user_id(raw_input)
            self.assertEqual(
                actual_key,
                expected_key,
                f"Failed for input '{raw_input}': expected '{expected_key}', got '{actual_key}'",
            )

    def test_lexical_normalization_adversarial_fallbacks(self):
        """Test non-string, empty, whitespace-only, and symbol-only fallbacks."""
        invalid_inputs = [
            None,
            "",
            "   ",
            "\t\n\r  ",
            "!!!@@@###$$$%%%^^^&&&***",
            "---___---",
            "...",
            12345,
            12.34,
            [],
            {},
            object(),
        ]
        for inp in invalid_inputs:
            res = normalize_lexical_user_id(inp)
            self.assertEqual(res, "user_anonymous", f"Input {inp!r} should normalize to 'user_anonymous'")

    def test_lexical_normalization_idempotency_fuzzing(self):
        """Ensure normalize_lexical_user_id(normalize_lexical_user_id(x)) == normalize_lexical_user_id(x)."""
        fuzz_samples = [
            "Aditya Sharma",
            "Dr. Rajesh Kumar ji",
            "Mera naam Priya Patel hai",
            "user_vikram_singh",
            "123 Investor",
            "Special @#% Name",
        ]
        for sample in fuzz_samples:
            once = normalize_lexical_user_id(sample)
            twice = normalize_lexical_user_id(once)
            thrice = normalize_lexical_user_id(twice)
            self.assertEqual(once, twice)
            self.assertEqual(twice, thrice)


# ═══════════════════════════════════════════════════════════════════════
# 4. CROSS-SESSION HYDRATION ADVERSARIAL STRESS
# ═══════════════════════════════════════════════════════════════════════

class TestHydrationAdversarial(unittest.TestCase):
    """Stress testing of 90-day cross-session profile hydration."""

    def test_hydration_multi_session_timeline_isolation(self):
        """Test hydration accurately groups memories across 90-day boundary and isolates users."""
        now = datetime.now(timezone.utc)
        mb = MemoryBank(lookback_days=90)

        # User A: 3 memories (10d ago, 85d ago, 95d ago)
        mb.add_memory("user_alice", "Alice recent memory (10d)")
        mb._memories["user_alice"][0]["created_at"] = (now - timedelta(days=10)).isoformat()
        mb._memories["user_alice"][0]["updated_at"] = (now - timedelta(days=10)).isoformat()

        mb.add_memory("user_alice", "Alice old valid memory (85d)")
        mb._memories["user_alice"][1]["created_at"] = (now - timedelta(days=85)).isoformat()
        mb._memories["user_alice"][1]["updated_at"] = (now - timedelta(days=85)).isoformat()

        mb.add_memory("user_alice", "Alice expired memory (95d)")
        mb._memories["user_alice"][2]["created_at"] = (now - timedelta(days=95)).isoformat()
        mb._memories["user_alice"][2]["updated_at"] = (now - timedelta(days=95)).isoformat()

        # User B: 1 memory (5d ago)
        mb.add_memory("user_bob", "Bob memory (5d)")
        mb._memories["user_bob"][0]["created_at"] = (now - timedelta(days=5)).isoformat()
        mb._memories["user_bob"][0]["updated_at"] = (now - timedelta(days=5)).isoformat()

        # FactStores
        mb.get_fact_store("user_alice").set_fact("amount", 100000, turn_id=1)
        mb.get_fact_store("user_bob").set_fact("amount", 500000, turn_id=1)

        # Hydrate Alice
        alice_prof = mb.hydrate_user_profile("user_alice", days_lookback=90)
        self.assertEqual(alice_prof["memory_count"], 2)
        self.assertIn("Alice recent memory (10d)", alice_prof["episodic_memories"])
        self.assertIn("Alice old valid memory (85d)", alice_prof["episodic_memories"])
        self.assertNotIn("Alice expired memory (95d)", alice_prof["episodic_memories"])
        self.assertEqual(alice_prof["facts"]["amount"], 100000)

        # Hydrate Bob
        bob_prof = mb.hydrate_user_profile("user_bob", days_lookback=90)
        self.assertEqual(bob_prof["memory_count"], 1)
        self.assertEqual(bob_prof["facts"]["amount"], 500000)
        self.assertNotIn("Alice", str(bob_prof))


if __name__ == "__main__":
    unittest.main()
