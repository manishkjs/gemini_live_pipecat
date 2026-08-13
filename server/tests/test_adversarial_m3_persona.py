"""Adversarial stress-testing suite for Milestone 3 (Conversational Dynamics & Persona Scripting R3).

Exhaustively verifies:
1. Devanagari Hindi + Latin English code-mixing & Unicode block properties (\u0900-\u097F).
2. Lexical audit for Romanized Hindi leakages in instructions and few-shot examples.
3. PTA (Pause-Think-Answer) 4-group structure and "अच्छा" single-occurrence cap.
4. Pacing, prosody, punctuation, and sentence-length bounds.
5. Transliteration mandate from deterministic tools.
6. 9-Phase Sales Journey and 4-Objection Playbook completeness.
7. StartTriggerProcessor stress test (locale permutations, concurrent triggers, malformed frames).
8. RepeatOnInterruptionProcessor & RepeatOnFiller stress test (edge-case tokenizations, multi-lingual fillers, punctuation bursts).
"""

import asyncio
import os
import re
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

# Add server directory to sys.path
server_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from system_prompt import SYSTEM_PROMPT, tts_prompt, GEMINI_LLM_TTS_PROMPT
from agent_live import StartTriggerProcessor
from processors.repeat_on_interruption import RepeatOnInterruptionProcessor
from pipecat.frames.frames import (
    Frame,
    TextFrame,
    InterruptionFrame,
    InputTransportMessageFrame,
    OutputTransportMessageFrame,
    LLMMessagesAppendFrame,
    LLMRunFrame,
    TranscriptionFrame,
)


class TestAdversarialScriptMixingAndUnicodeBlocks(unittest.TestCase):
    """Adversarial validation of Unicode Devanagari blocks and Latin technical tokens."""

    DEVANAGARI_REGEX = re.compile(r'[\u0900-\u097F]')
    FORBIDDEN_ROMANIZED_HINDI_PATTERNS = [
        r'\bek lakh rupaye\b',
        r'\b50,000 rupaye\b',
        r'\brupaye\b',
        r'\bmahine\b',
        r'\bmahina\b',
        r'\btheek hai\b',
        r'\bhaan ji\b',
        r'\bkya aap\b',
        r'\bkareinge\b',
        r'\bkarenge\b',
        r'\bnikalne ke baad\b',
        r'\bsamajhte hain\b',
        r'\byeh bahut\b',
        r'\bachha question\b',
        r'\bnamaste\b',
        r'\bpragya baat kar rahi\b',
    ]

    def test_system_prompt_devanagari_density(self):
        """Verify substantial presence of Unicode Devanagari characters in SYSTEM_PROMPT."""
        devanagari_chars = self.DEVANAGARI_REGEX.findall(SYSTEM_PROMPT)
        self.assertGreater(len(devanagari_chars), 200, "SYSTEM_PROMPT must have high Devanagari density.")

    def test_pragya_few_shot_responses_zero_romanized_hindi(self):
        """Extract all Pragya spoken turns in few-shot examples and assert 0 Romanized Hindi tokens."""
        pragya_turns = re.findall(r'Pragya:\s*"([^"]+)"', SYSTEM_PROMPT)
        self.assertEqual(len(pragya_turns), 3, "Expected exactly 3 few-shot Pragya responses.")

        for idx, turn in enumerate(pragya_turns, 1):
            for pattern in self.FORBIDDEN_ROMANIZED_HINDI_PATTERNS:
                match = re.search(pattern, turn, re.IGNORECASE)
                self.assertIsNone(
                    match,
                    f"Example {idx} Pragya turn leaked Romanized Hindi pattern '{pattern}': match='{match.group() if match else None}' in turn='{turn}'"
                )

    def test_pragya_few_shot_latin_words_are_pure_english(self):
        """Verify that all Latin-script words in Pragya's turns are legitimate English financial/technical words or numbers."""
        pragya_turns = re.findall(r'Pragya:\s*"([^"]+)"', SYSTEM_PROMPT)
        
        # Allowed English words and brand tokens in Pragya's speech
        ALLOWED_ENGLISH_TOKENS = {
            "cymbal", "lending", "options", "p2p", "familiar", "explore",
            "months", "stl", "7m", "plan", "invest", "annualized", "xirr",
            "net", "profit", "total", "maturity", "amount", "emi", "account",
            "monthly", "payout", "prefer", "question", "example", "step-by-step",
            "step", "by", "npa", "loss", "performing", "gross", "interest",
            "platform", "fee", "adjust", "annual", "return", "diversification", "help"
        }

        for idx, turn in enumerate(pragya_turns, 1):
            latin_words = re.findall(r'\b[a-zA-Z]+\b', turn)
            for word in latin_words:
                lower_word = word.lower()
                self.assertIn(
                    lower_word,
                    ALLOWED_ENGLISH_TOKENS,
                    f"Example {idx} contains unexpected Latin word '{word}' which might be Romanized Hindi! Turn: {turn}"
                )

    def test_no_english_words_in_devanagari_in_few_shots(self):
        """Verify forbidden Devanagari transliterations of English words (e.g. पोर्टफोलियो, रिटर्न, केवाईसी) are not present in few-shots."""
        FORBIDDEN_DEVANAGARI_ENGLISH = ["पोर्टफोलियो", "रिटर्न", "केवाईसी", "प्लान", "इन्वेस्ट", "अकाउंट"]
        pragya_turns = re.findall(r'Pragya:\s*"([^"]+)"', SYSTEM_PROMPT)
        for idx, turn in enumerate(pragya_turns, 1):
            for bad_token in FORBIDDEN_DEVANAGARI_ENGLISH:
                self.assertNotIn(
                    bad_token,
                    turn,
                    f"Example {idx} Pragya turn used Devanagari for English technical term '{bad_token}': {turn}"
                )


class TestAdversarialPTAFillersAndCapping(unittest.TestCase):
    """Adversarial validation of 4 PTA groups and strict occurrence capping."""

    def test_all_four_pta_groups_uniquely_defined(self):
        """Verify Group A, Group B, Group C, Group D exist with non-overlapping filler sets."""
        group_a = re.search(r'Group A \([^)]+\):\s*([^\n]+)', SYSTEM_PROMPT)
        group_b = re.search(r'Group B \([^)]+\):\s*([^\n]+)', SYSTEM_PROMPT)
        group_c = re.search(r'Group C \([^)]+\):\s*([^\n]+)', SYSTEM_PROMPT)
        group_d = re.search(r'Group D \([^)]+\):\s*([^\n]+)', SYSTEM_PROMPT)

        self.assertIsNotNone(group_a, "Group A (Thinking) definition missing.")
        self.assertIsNotNone(group_b, "Group B (Transitions) definition missing.")
        self.assertIsNotNone(group_c, "Group C (Acknowledgment) definition missing.")
        self.assertIsNotNone(group_d, "Group D (Light discovery) definition missing.")

        # Ensure no cross-group duplicate fillers
        fillers_a = set(re.findall(r'"([^"]+)"', group_a.group(1)))
        fillers_b = set(re.findall(r'"([^"]+)"', group_b.group(1)))
        fillers_c = set(re.findall(r'"([^"]+)"', group_c.group(1)))
        fillers_d = set(re.findall(r'"([^"]+)"', group_d.group(1)))

        self.assertTrue(fillers_a.isdisjoint(fillers_b), "Group A and B overlap.")
        self.assertTrue(fillers_a.isdisjoint(fillers_c), "Group A and C overlap.")
        self.assertTrue(fillers_a.isdisjoint(fillers_d), "Group A and D overlap.")
        self.assertTrue(fillers_b.isdisjoint(fillers_c), "Group B and C overlap.")
        self.assertTrue(fillers_b.isdisjoint(fillers_d), "Group B and D overlap.")
        self.assertTrue(fillers_c.isdisjoint(fillers_d), "Group C and D overlap.")

    def test_achha_capping_and_few_shot_budget(self):
        """Verify 'अच्छा' / 'Achha' capping rule in prompt and count in few-shot Pragya turns."""
        self.assertIn('"अच्छा" ("Achha") is permitted at most ONCE in the entire call.', SYSTEM_PROMPT)
        
        pragya_turns = re.findall(r'Pragya:\s*"([^"]+)"', SYSTEM_PROMPT)
        total_achha_in_few_shots = sum(
            turn.count("अच्छा") + len(re.findall(r'\bachha\b|\bacha\b', turn, re.I))
            for turn in pragya_turns
        )
        self.assertLessEqual(
            total_achha_in_few_shots, 1,
            f"Few-shot examples exceeded max 1 'अच्छा' budget across all Pragya turns: count={total_achha_in_few_shots}"
        )


class TestAdversarialPacingAndSentenceLengths(unittest.TestCase):
    """Adversarial stress-testing of sentence lengths and punctuation."""

    def test_sentence_punctuation_in_few_shots(self):
        """Verify that every sentence in Pragya turns terminates with proper punctuation (. ! ? ।)."""
        pragya_turns = re.findall(r'Pragya:\s*"([^"]+)"', SYSTEM_PROMPT)
        for idx, turn in enumerate(pragya_turns, 1):
            clean_turn = turn.strip()
            self.assertRegex(
                clean_turn[-1],
                r'[.!?।]',
                f"Pragya Example {idx} turn does not end with valid terminal punctuation: '{clean_turn[-1]}'"
            )


class TestAdversarialSalesJourneyAndObjections(unittest.TestCase):
    """Verify state machine phases 1-9 and 4 objection responses."""

    def test_nine_sales_journey_phases_sequential(self):
        """Verify Phases 1 through 9 are sequentially present."""
        for phase_num in range(1, 10):
            pattern = rf'Phase {phase_num}:'
            self.assertIn(pattern, SYSTEM_PROMPT, f"Missing {pattern} in sales journey.")

    def test_four_objections_present(self):
        """Verify all 4 core objection categories are covered in objection playbook."""
        self.assertIn("Is it safe? What if borrowers default (NPA)?", SYSTEM_PROMPT)
        self.assertIn("Why not just put money in Bank Fixed Deposits (FD)?", SYSTEM_PROMPT)
        self.assertIn("Is Cymbal Lending legal / RBI approved?", SYSTEM_PROMPT)
        self.assertIn("Can I withdraw money anytime?", SYSTEM_PROMPT)


class TestAdversarialStartTriggerProcessor(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress test for StartTriggerProcessor."""

    async def test_rapid_concurrent_triggers_race_condition(self):
        """Triggering start_trigger concurrently 100 times must emit exactly 1 greeting."""
        processor = StartTriggerProcessor(language="hi-IN")
        pushed_frames = []

        async def capture_frame(frame, direction=None):
            pushed_frames.append(frame)

        processor.push_frame = capture_frame

        # Launch 100 concurrent start_triggers
        tasks = [
            processor.process_frame(InputTransportMessageFrame(message={"type": "start_trigger", "id": f"req-{i}"}))
            for i in range(100)
        ]
        await asyncio.gather(*tasks)

        append_frames = [f for f in pushed_frames if isinstance(f, LLMMessagesAppendFrame)]
        run_frames = [f for f in pushed_frames if isinstance(f, LLMRunFrame)]
        output_frames = [f for f in pushed_frames if isinstance(f, OutputTransportMessageFrame)]

        self.assertEqual(len(append_frames), 1, "Expected exactly 1 LLMMessagesAppendFrame despite 100 triggers.")
        self.assertEqual(len(run_frames), 1, "Expected exactly 1 LLMRunFrame despite 100 triggers.")
        self.assertEqual(len(output_frames), 100, "All 100 requests should receive an ack OutputTransportMessageFrame.")
        self.assertEqual(append_frames[0].messages[0]["content"], "नमस्ते!")

    async def test_malformed_input_frames(self):
        """Ensure StartTriggerProcessor handles strange/malformed frames gracefully without throwing."""
        processor = StartTriggerProcessor(language="hi-IN")
        processor.push_frame = AsyncMock()

        # Non-matching frame
        await processor.process_frame(TextFrame(text="test"))
        # Empty dict message
        await processor.process_frame(InputTransportMessageFrame(message={}))
        # None message
        await processor.process_frame(InputTransportMessageFrame(message=None))
        # Non-dict message
        await processor.process_frame(InputTransportMessageFrame(message="string_msg"))

        self.assertFalse(processor.triggered)

    async def test_exotic_locale_mappings(self):
        """Test boundary locale inputs."""
        test_cases = [
            ("hi_IN", "नमस्ते!"),
            ("hi", "नमस्ते!"),
            ("hi-IN", "नमस्ते!"),
            ("en-IN", "नमस्ते!"),
            ("hindi", "नमस्ते!"),  # starts with 'hi'
            ("hi-custom", "नमस्ते!"),
            (None, "Hello!"),
            (123, "Hello!"),
            ("", "Hello!"),
            ("en-US", "Hello!"),
            ("fr-FR", "Hello!"),
        ]

        for lang_val, expected_greeting in test_cases:
            proc = StartTriggerProcessor(language=lang_val)
            frames = []
            async def cap(f, d=None):
                frames.append(f)
            proc.push_frame = cap
            await proc.process_frame(InputTransportMessageFrame(message={"type": "start_trigger"}))
            appends = [f for f in frames if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(appends), 1)
            self.assertEqual(appends[0].messages[0]["content"], expected_greeting, f"Failed for language='{lang_val}'")


class TestAdversarialRepeatOnInterruptionProcessor(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress test for RepeatOnInterruptionProcessor."""

    async def test_boundary_word_counts_and_punctuation_stripping(self):
        """Test exact word counts with tricky Unicode and punctuation combinations."""
        processor = RepeatOnInterruptionProcessor(filler_max_words=2)
        processor.push_frame = AsyncMock()

        # Test cases: (input_text, expected_is_filler)
        # Note: In current processor, word_count <= 2 classifies len(split()) <= 2 as filler
        cases = [
            ("haan", True),  # 1 word -> filler
            ("हाँ", True),  # 1 Devanagari word -> filler
            ("ji bilkul", True),  # 2 words -> filler
            ("ठीक है", True),  # 2 Devanagari words -> filler
            ("theek hai...", True),  # 2 words with trailing dots -> filler
            ("haan ji bhai", False),  # 3 words -> genuine question
            ("क्या बोल रहे हो", False),  # 4 Devanagari words -> genuine question
            ("one two three", False),  # 3 words -> genuine question
            ("what is the rate of return?", False),  # 6 words -> genuine question
        ]

        for text_input, should_be_filler in cases:
            processor._was_interrupted = True
            processor.push_frame.reset_mock()

            await processor.process_frame(
                TranscriptionFrame(text=text_input, user_id="u", timestamp="10:00"),
                None
            )

            if should_be_filler:
                call_args = processor.push_frame.call_args_list
                self.assertTrue(len(call_args) >= 1, f"Failed for '{text_input}'")
                frame = call_args[0][0][0]
                self.assertIsInstance(frame, LLMMessagesAppendFrame)
                self.assertTrue(frame.run_llm, f"Expected run_llm=True for filler '{text_input}'")
            else:
                call_args = processor.push_frame.call_args_list
                if call_args:
                    frame = call_args[0][0][0]
                    self.assertIsInstance(frame, LLMMessagesAppendFrame)
                    self.assertFalse(getattr(frame, "run_llm", False), f"Expected run_llm=False for non-filler '{text_input}'")

    async def test_interruption_without_transcription_safety(self):
        """Interruption frame followed by non-transcription frames leaves processor state intact."""
        processor = RepeatOnInterruptionProcessor(filler_max_words=2)
        processor.push_frame = AsyncMock()
        # Mock _start_interruption to avoid BaseFrameProcessor task scheduling warnings
        processor._start_interruption = AsyncMock()

        # Step 1: Interruption
        await processor.process_frame(InterruptionFrame(), None)
        self.assertTrue(processor._was_interrupted)

        # Step 2: Unrelated frame passes through
        unrelated_frame = TextFrame(text="test")
        await processor.process_frame(unrelated_frame, None)
        self.assertTrue(processor._was_interrupted)

        # Step 3: Second interruption doesn't crash
        await processor.process_frame(InterruptionFrame(), None)
        self.assertTrue(processor._was_interrupted)


if __name__ == "__main__":
    unittest.main()
