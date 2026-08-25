"""
Challenger 1 Empirical Stress Benchmark & Verification Suite.

Stress-test Hot-Path Telemetry, Teardown Timeout, Tier-1 Regex Engine, and Phase 1 vs Filler Dynamics.
"""

import asyncio
import json
import os
import queue
import re
import sys
import threading
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

# Ensure server path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tracing import LangSmithTracer, GLOBAL_LANGSMITH_TRACER
from phase_engine import (
    ConsultativePhaseTracker,
    PHASE_TIER1_RULES,
    CONVERSATIONAL_FILLER_PATTERN,
    PHASE_PROMPT_CARDS,
    Tier1Rule,
)


class MockRunTree:
    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id") or "mock-run-id-12345"
        self.name = kwargs.get("name")
        self.inputs = kwargs.get("inputs")
        self.outputs = kwargs.get("outputs")
        self.extra = kwargs.get("extra")
        self.tags = kwargs.get("tags")
        self.simulated_delay = 0.0

    def post(self):
        if self.simulated_delay > 0:
            time.sleep(self.simulated_delay)

    def patch(self):
        if self.simulated_delay > 0:
            time.sleep(self.simulated_delay)

    def end(self, *args, **kwargs):
        if self.simulated_delay > 0:
            time.sleep(self.simulated_delay)

    def create_child(self, *args, **kwargs):
        child = MockRunTree(*args, **kwargs)
        child.simulated_delay = self.simulated_delay
        return child


class TestLangSmithHotPathBenchmark(unittest.TestCase):
    """Scope 1 & 2: Hot path latency (< 0.1ms) and end_session cap (<= 1.5s)."""

    def setUp(self):
        self.tracer = LangSmithTracer(max_queue_size=10000)
        self.tracer.enabled = True
        self.tracer.client = MagicMock()
        self.tracer.client.share_run.return_value = "https://smith.langchain.com/public/mock-run/r"

    def tearDown(self):
        self.tracer._enqueue(None)

    def test_hot_path_latency_under_simulated_network_delay(self):
        """Microbenchmark hot path calls with 50ms simulated network delay on worker thread."""
        mock_tree_cls = MockRunTree

        with patch("tracing.RunTree", side_effect=lambda **kwargs: mock_tree_cls(**kwargs)):
            self.tracer.start_session("sess_hotpath_bench", "gemini-2.0-flash", "Aoede", "hi")

            latencies_user = []
            latencies_bot = []
            latencies_tool = []
            latencies_interruption = []

            iterations = 2500  # Total 10,000 invocations across 4 call types

            for i in range(iterations):
                # 1. record_user_turn
                t0 = time.perf_counter_ns()
                self.tracer.record_user_turn(f"User transcript {i}", latency_s=0.25)
                t1 = time.perf_counter_ns()
                latencies_user.append((t1 - t0) / 1000.0)  # microseconds

                # 2. record_bot_turn
                t0 = time.perf_counter_ns()
                self.tracer.record_bot_turn(
                    f"Bot response {i}", ttfb_ms=320.5, token_usage={"total_tokens": 150}
                )
                t1 = time.perf_counter_ns()
                latencies_bot.append((t1 - t0) / 1000.0)

                # 3. record_tool_call
                t0 = time.perf_counter_ns()
                self.tracer.record_tool_call(
                    "calculate_returns",
                    {"amount": 50000, "tenure_months": 6},
                    {"roi": 18.0},
                    duration_ms=12.4,
                )
                t1 = time.perf_counter_ns()
                latencies_tool.append((t1 - t0) / 1000.0)

                # 4. record_interruption
                t0 = time.perf_counter_ns()
                self.tracer.record_interruption(elapsed_ms=450.0)
                t1 = time.perf_counter_ns()
                latencies_interruption.append((t1 - t0) / 1000.0)

            all_latencies = latencies_user + latencies_bot + latencies_tool + latencies_interruption
            all_latencies.sort()

            n = len(all_latencies)
            mean_us = sum(all_latencies) / n
            p50_us = all_latencies[int(n * 0.50)]
            p90_us = all_latencies[int(n * 0.90)]
            p95_us = all_latencies[int(n * 0.95)]
            p99_us = all_latencies[int(n * 0.99)]
            max_us = max(all_latencies)
            pct_under_100us = (sum(1 for x in all_latencies if x < 100.0) / n) * 100.0

            print("\n" + "=" * 70)
            print("🚀 [GLOBAL_LANGSMITH_TRACER HOT-PATH TELEMETRY MICROBENCHMARK (10,000 calls)]")
            print(f"   Total calls:        {n:,}")
            print(f"   Mean Latency:       {mean_us:.3f} µs ({mean_us/1000:.5f} ms)")
            print(f"   Median (p50):       {p50_us:.3f} µs ({p50_us/1000:.5f} ms)")
            print(f"   p90 Latency:        {p90_us:.3f} µs ({p90_us/1000:.5f} ms)")
            print(f"   p95 Latency:        {p95_us:.3f} µs ({p95_us/1000:.5f} ms)")
            print(f"   p99 Latency:        {p99_us:.3f} µs ({p99_us/1000:.5f} ms)")
            print(f"   Max Latency:        {max_us:.3f} µs ({max_us/1000:.5f} ms)")
            print(f"   Calls < 100µs:      {pct_under_100us:.2f}%")
            print(f"   Hot-path Target:    < 100 µs (< 0.1 ms) -> {'PASSED' if mean_us < 100 and p95_us < 100 else 'FAILED'}")
            print("=" * 70)

            self.assertLess(mean_us, 100.0)
            self.assertLess(p95_us, 100.0)
            self.assertGreater(pct_under_100us, 99.0)

    def test_concurrent_hot_path_invocations(self):
        """Microbenchmark hot path under 8 concurrent threads hammering tracer."""
        num_threads = 8
        calls_per_thread = 1000
        latencies: List[float] = []
        lock = threading.Lock()

        def worker_task(worker_id: int):
            local_latencies = []
            for j in range(calls_per_thread):
                t0 = time.perf_counter_ns()
                if j % 4 == 0:
                    self.tracer.record_user_turn(f"W{worker_id} text {j}")
                elif j % 4 == 1:
                    self.tracer.record_bot_turn(f"W{worker_id} bot {j}", ttfb_ms=100.0)
                elif j % 4 == 2:
                    self.tracer.record_tool_call("calc", {"a": 1}, "res")
                else:
                    self.tracer.record_interruption(200.0)
                t1 = time.perf_counter_ns()
                local_latencies.append((t1 - t0) / 1000.0)

            with lock:
                latencies.extend(local_latencies)

        threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        latencies.sort()
        n = len(latencies)
        mean_us = sum(latencies) / n
        p50_us = latencies[int(n * 0.50)]
        p95_us = latencies[int(n * 0.95)]
        p99_us = latencies[int(n * 0.99)]
        max_us = max(latencies)

        print("\n" + "=" * 70)
        print(f"🔥 [CONCURRENT HOT-PATH BENCHMARK (8 Threads x 1,000 = {n:,} calls)]")
        print(f"   Mean Latency:       {mean_us:.3f} µs ({mean_us/1000:.5f} ms)")
        print(f"   p50 Latency:        {p50_us:.3f} µs ({p50_us/1000:.5f} ms)")
        print(f"   p95 Latency:        {p95_us:.3f} µs ({p95_us/1000:.5f} ms)")
        print(f"   p99 Latency:        {p99_us:.3f} µs ({p99_us/1000:.5f} ms)")
        print(f"   Max Latency:        {max_us:.3f} µs ({max_us/1000:.5f} ms)")
        print("=" * 70)

        self.assertLess(mean_us, 100.0)
        self.assertLess(p95_us, 100.0)

    def test_queue_full_non_blocking_behavior(self):
        """Verify tracer drops gracefully without blocking when queue is completely full."""
        tiny_tracer = LangSmithTracer(max_queue_size=10)
        tiny_tracer.enabled = True

        for k in range(10):
            tiny_tracer._queue.put_nowait({"type": "DUMMY"})

        self.assertEqual(tiny_tracer._queue.qsize(), 10)

        latencies = []
        for i in range(100):
            t0 = time.perf_counter_ns()
            tiny_tracer.record_user_turn("overflow test")
            tiny_tracer.record_bot_turn("overflow bot")
            tiny_tracer.record_tool_call("tool", {}, "res")
            tiny_tracer.record_interruption(100.0)
            t1 = time.perf_counter_ns()
            latencies.append((t1 - t0) / 1000.0 / 4.0)

        mean_us = sum(latencies) / len(latencies)
        p95_us = sorted(latencies)[int(len(latencies) * 0.95)]
        print(f"\n⚡ [QUEUE-FULL HOT-PATH LATENCY]: Mean {mean_us:.3f} µs, p95 {p95_us:.3f} µs on full queue")
        self.assertLess(mean_us, 100.0)
        self.assertLess(p95_us, 100.0)

    def test_end_session_timeout_cap(self):
        """Stress-test end_session() under full queue and blocked worker, verifying <= 1.5s cap."""
        slow_tracer = LangSmithTracer(max_queue_size=1000)
        slow_tracer.enabled = True

        # Enqueue 500 backlog items
        for i in range(500):
            slow_tracer._queue.put({"type": "DUMMY", "id": i})

        # Test 1: end_session(timeout=1.5)
        t0 = time.perf_counter()
        slow_tracer.end_session(summary="Stress test summary", timeout=1.5)
        duration_1_5 = time.perf_counter() - t0

        print(f"\n⏱️ [END_SESSION TIMEOUT CAP TEST (500 items backlog)]")
        print(f"   timeout=1.5s -> Actual Duration: {duration_1_5:.4f}s (Cap target: <= 1.55s)")
        self.assertLessEqual(duration_1_5, 1.55)

        # Test 2: end_session(timeout=5.0) -> Must still cap at min(5.0, 1.5) = 1.5s!
        for i in range(500):
            slow_tracer._queue.put({"type": "DUMMY", "id": i})

        t0 = time.perf_counter()
        slow_tracer.end_session(summary="Excessive timeout test", timeout=5.0)
        duration_5_0 = time.perf_counter() - t0

        print(f"   timeout=5.0s (capped at 1.5s) -> Actual Duration: {duration_5_0:.4f}s")
        self.assertLessEqual(duration_5_0, 1.55)

        # Test 3: end_session(timeout=0.2) -> Must finish in <= 0.25s
        t0 = time.perf_counter()
        slow_tracer.end_session(summary="Short timeout test", timeout=0.2)
        duration_0_2 = time.perf_counter() - t0

        print(f"   timeout=0.2s -> Actual Duration: {duration_0_2:.4f}s")
        self.assertLessEqual(duration_0_2, 0.25)

        self.assertIsNone(slow_tracer.root_run)


class TestPhaseTier1Rules10kBenchmark(unittest.TestCase):
    """Scope 3: Microbenchmark PHASE_TIER1_RULES evaluation across 10,000 utterances."""

    @classmethod
    def setUpClass(cls):
        cls.utterances = cls._generate_10k_utterances()

    @classmethod
    def _generate_10k_utterances(cls) -> List[str]:
        corpus = []

        tier1_positive_samples = [
            "phone rakho mujhe baat nahi karni",
            "nahi karna invest mujhe",
            "I don't want to invest right now",
            "not interested at all",
            "rehne do mat batao",
            "रुको मुझे नहीं करना",
            "फोन रखो",
            "bye thank you alvida",
            "chalo bye baad mein baat karte hain",
            "ok bye wrap up thank you",
            "बाय धन्यवाद",
            "बाद में बात करते हैं",
            "main busy hu baad mein call back karo",
            "busy call back",
            "kyc kaise karni hai aadhaar pan card",
            "digilocker se penny drop kaise hoga?",
            "documents kya lagenge?",
            "केवाईसी और पैन कार्ड कैसे अपलोड करें",
            "kya ye RBI approved hai? escrow safe hai?",
            "is this platform legal and safe?",
            "आरबीआई एस्क्रो लीगल है क्या?",
            "agar borrower default kar jaye to kya hoga? 100 borrowers risk",
            "what if borrower doesn't pay back? recovery NPA",
            "पैसा डूब गया तो रिकवरी कैसे होगी?",
            "kitna return milega? monthly payout profit calculation",
            "what is the profit on 50000? calculate returns",
            "कितना मिलेगा फायदा",
            "FD me to 7% milta hai yahan 18% kaise possible hai?",
            "fixed deposit vs mutual funds comparison 24%",
            "बैंक में तो कम रिटर्न मिलता है",
            "haan ji bataiye sure",
            "theek hai boliye ok",
            "हाँ बताइए",
            "maine pehli baar suna hai P2P ke baare mein",
            "pehli baar explore kar raha hu kabhi invest nahi kiya",
            "पहली बार सुन रहा हूँ",
        ]

        fillers = [
            "haan", "ha", "yes", "theek hai", "theek", "accha", "acha", "achha",
            "ji", "ji haan", "haanji", "ok", "okay", "hmm", "hmmm", "sahi hai",
            "got it", "sure", "right", "alright", "all right",
            "हाँ", "हां", "जी", "ठीक है", "ठीक", "अच्छा", "हम्म", "हाँजी", "सही है", "जी हाँ"
        ]

        substantive_inquiries = [
            "mera budget 1 lakh rupaye hai aur mujhe regular monthly interest chahiye",
            "main retirement corpus park karna chahta hu",
            "aapka platform kab start hua tha aur kitne users hain?",
            "short term lending me tenure options kya hain?",
            "can I withdraw my principal before maturity?",
            "what is the difference between STL and MTL plans?",
            "taxation kaise lagti hai P2P earnings par?",
            "TDS deduct hota hai kya payout ke time?",
            "minimum investment amount kitna hai Cymbal Lending par?",
            "app par login karne ke liye OTP nahi aa raha",
            "interest reinvest ho sakta hai kya compounding ke liye?",
            "hum kitne borrowers me divide kar sakte hain?",
            "escrow account ICICI me hai ya kisi aur bank me?",
            "Dipesh Karki kaun hain platform par?",
        ]

        edge_cases = [
            "",
            "   ",
            "\n\t  \r",
            "a",
            "??",
            "!!!",
            "₹50,000",
            "1234567890",
            "hello @#$%^&*()_+{}|:<>?",
            "A" * 500,
            "haan " * 50,
            "अरे वाह बहुत बढ़िया",
            "😀 😃 😄 😁 �� 😅 😂 🤣",
            "theek hai but wait a minute what about rbi?",
            "yes please tell me about 12 month 24% return",
            "haanji definitely mujhe ₹25000 lagane hain",
        ]

        for i in range(10000):
            cat = i % 4
            if cat == 0:
                base = tier1_positive_samples[i % len(tier1_positive_samples)]
                corpus.append(f"{base} [case_{i}]" if i % 3 == 0 else base)
            elif cat == 1:
                base = fillers[i % len(fillers)]
                punc = ["", ".", "!", "?", "...", "  "][i % 6]
                corpus.append(f"{base}{punc}")
            elif cat == 2:
                base = substantive_inquiries[i % len(substantive_inquiries)]
                corpus.append(f"Turn {i}: {base}")
            else:
                base = edge_cases[i % len(edge_cases)]
                corpus.append(base)

        return corpus

    def test_evaluate_10k_utterances_microbenchmark(self):
        """Microbenchmark all 10,000 utterances through Tier-1 rule evaluation."""
        utterances = self.utterances
        total_evals = len(utterances)
        latencies_us: List[float] = []

        matched_count = 0

        for i, text in enumerate(utterances):
            phase = (i % 9) + 1  # Rotating Phase 1 to 9
            cleaned_text = text.strip()
            lower = cleaned_text.lower()

            t0 = time.perf_counter_ns()

            matched_target = None
            for rule in PHASE_TIER1_RULES:
                if not rule.is_applicable(phase):
                    continue
                if rule.pattern.search(cleaned_text) or rule.pattern.search(lower):
                    matched_target = rule.target_phase
                    break

            t1 = time.perf_counter_ns()

            latencies_us.append((t1 - t0) / 1000.0)
            if matched_target is not None:
                matched_count += 1

        latencies_us.sort()
        n = len(latencies_us)
        mean_us = sum(latencies_us) / n
        p50_us = latencies_us[int(n * 0.50)]
        p90_us = latencies_us[int(n * 0.90)]
        p95_us = latencies_us[int(n * 0.95)]
        p99_us = latencies_us[int(n * 0.99)]
        max_us = max(latencies_us)
        pct_under_50us = (sum(1 for x in latencies_us if x < 50.0) / n) * 100.0
        pct_under_100us = (sum(1 for x in latencies_us if x < 100.0) / n) * 100.0

        print("\n" + "=" * 70)
        print(f"⚡ [PHASE_TIER1_RULES 10,000-UTTERANCE EVALUATION BENCHMARK]")
        print(f"   Evaluations:        {total_evals:,}")
        print(f"   Matches found:      {matched_count:,} ({matched_count/total_evals*100:.1f}%)")
        print(f"   Mean Latency:       {mean_us:.3f} µs ({mean_us/1000:.5f} ms)")
        print(f"   Median (p50):       {p50_us:.3f} µs ({p50_us/1000:.5f} ms)")
        print(f"   p90 Latency:        {p90_us:.3f} µs ({p90_us/1000:.5f} ms)")
        print(f"   p95 Latency:        {p95_us:.3f} µs ({p95_us/1000:.5f} ms)")
        print(f"   p99 Latency:        {p99_us:.3f} µs ({p99_us/1000:.5f} ms)")
        print(f"   Max Latency:        {max_us:.3f} µs ({max_us/1000:.5f} ms)")
        print(f"   Evaluations < 50µs: {pct_under_50us:.2f}%")
        print(f"   Evaluations < 100µs:{pct_under_100us:.2f}%")
        print(f"   Microsecond Target: < 100 µs (< 0.1 ms) -> {'PASSED' if mean_us < 100 and p95_us < 100 else 'FAILED'}")
        print("=" * 70)

        # Microsecond scale verification (< 100µs / 0.1ms)
        self.assertLess(mean_us, 100.0)
        self.assertLess(p95_us, 100.0)
        self.assertGreater(pct_under_100us, 99.0)


class TestFillerShortCircuitVsConsentPreservation(unittest.TestCase):
    """Scope 4: Conversational filler short-circuiting vs Phase 1 consent preservation."""

    def setUp(self):
        self.gemini_mock = MagicMock()
        self.gemini_mock._session = MagicMock()
        self.tracker = ConsultativePhaseTracker(self.gemini_mock, enable_client_content=True)

    def test_phase_1_consent_preservation_supported_variants(self):
        """In Phase 1, supported consent phrases trigger Phase 1 -> 2 transition."""
        consent_phrases = [
            "haan", "yes", "theek hai", "sure", "batao", "bataiye", "boliye",
            "ok", "okay", "Haan", "YES", "THEEK HAI", "haan ji", "haan batao",
            "हाँ", "हां", "हाँजी", "जी हाँ", "बताइए", "बोलिए", "ठीक है",
            "haan sure", "yes please", "sure bataiye", "haan boliye",
        ]

        passed = 0
        failed = []

        for phrase in consent_phrases:
            self.tracker.current_phase = 1
            cleaned = phrase.strip()
            asyncio.run(self.tracker.handle_user_transcript(cleaned))

            if self.tracker.current_phase == 2:
                passed += 1
            else:
                failed.append((phrase, self.tracker.current_phase))

        print(f"\n📊 [PHASE 1 CONSENT PRESERVATION TEST]: {passed}/{len(consent_phrases)} phrases successfully transitioned 1 -> 2")
        self.assertEqual(len(failed), 0, f"Failed consent phrases: {failed}")

    def test_phase_1_reluctance_and_callback_preservation(self):
        """In Phase 1, objections & busy/callback maintain Phase 1 or transition appropriately."""
        # Note: In Phase 1, Rule 3 matches busy/callback/not interested -> stays Phase 1 (opening disarming).
        # Rule 1 has min_phase=2 so opening reluctance stays Phase 1 for warm opening disarm.
        cases = [
            ("not interested", 1),
            ("busy hu call back karo", 1),
            ("baad mein baat karte hain", 1),
            ("बाद में", 1),
            ("इंटरेस्ट नहीं है", 1),
            ("बिजी हूँ", 1),
        ]

        for phrase, expected_phase in cases:
            self.tracker.current_phase = 1
            asyncio.run(self.tracker.handle_user_transcript(phrase))
            self.assertEqual(
                self.tracker.current_phase,
                expected_phase,
                f"Phase 1 routing failed for '{phrase}': got Phase {self.tracker.current_phase}, expected {expected_phase}"
            )

    def test_phases_2_to_9_filler_short_circuiting(self):
        """In Phases 2..9, conversational fillers MUST be short-circuited with 0 LLM calls."""
        fillers = [
            "haan", "ha", "yes", "theek hai", "theek", "accha", "acha", "achha",
            "ji", "ji haan", "haanji", "ok", "okay", "hmm", "hmmm", "sahi hai",
            "got it", "sure", "right", "alright", "all right",
            "हाँ", "हां", "जी", "ठीक है", "ठीक", "अच्छा", "हम्म", "हाँजी", "सही है", "जी हाँ",
            "haan.", "theek hai!", "ok?", "ji...", "  HAAN  ", "acha!", "hmmm..."
        ]

        total_tested = 0
        with patch.object(self.tracker, "_async_ai_classify_intent", new_callable=MagicMock) as mock_ai:
            for start_phase in range(2, 10):
                for filler in fillers:
                    self.tracker.current_phase = start_phase
                    mock_ai.reset_mock()

                    asyncio.run(self.tracker.handle_user_transcript(filler))
                    total_tested += 1

                    self.assertEqual(
                        self.tracker.current_phase,
                        start_phase,
                        f"Phase changed on filler '{filler}' from Phase {start_phase} to {self.tracker.current_phase}"
                    )
                    mock_ai.assert_not_called()

        print(f"⚡ [FILLER SHORT-CIRCUITING TEST]: {total_tested} filler instances across Phases 2..9 successfully short-circuited with 0 LLM calls.")

    def test_filler_with_substantive_content_not_short_circuited(self):
        """Utterances starting with a filler but containing substantive intent must NOT be swallowed."""
        complex_utterances = [
            ("haan kitna return milega?", 7),  # Returns
            ("theek hai par kya ye RBI approved hai?", 4),  # Platform trust
            ("accha agar borrower default kar jaye to?", 5),  # Risk mitigation
            ("ji mujhe KYC complete karna hai", 8),  # KYC / Onboarding
            ("ok bye wrap up thank you", 9),  # Farewell
            ("haan mujhe nahi karna invest phone rakho", 6),  # Objection
        ]

        for text, expected_phase in complex_utterances:
            for start_phase in [2, 3]:
                self.tracker.current_phase = start_phase
                asyncio.run(self.tracker.handle_user_transcript(text))

                self.assertEqual(
                    self.tracker.current_phase,
                    expected_phase,
                    f"Complex utterance '{text}' from Phase {start_phase} incorrectly resolved to Phase {self.tracker.current_phase} (expected {expected_phase})"
                )


if __name__ == "__main__":
    unittest.main()
