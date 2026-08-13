"""Empirical Adversarial Stress Test Suite for Milestone 3 (R3):
Conversational Dynamics, StartTriggerProcessor, and RepeatOnFiller / RepeatOnInterruptionProcessor.

Coverage:
1. StartTriggerProcessor: Rapid bursts (1000+ frames), concurrent tasks, corrupted frames, malformed data, full locale sweep (including None, int, empty, unhandled), and duplicate suppression.
2. RepeatOnFiller (GeminiSessionLoggerMixin): Word count boundary fuzzing (0, 1, 2, 3, 100+ words), Devanagari danda punctuation ('।', '॥', '?', '!', '...'), Unicode whitespaces, chunk accumulation, and prompt formatting.
3. RepeatOnInterruptionProcessor: Two-tier logic boundary transitions, text buffer accumulation and reset, rapid burst interruptions without speech, and frame direction integrity.
4. Differential Fuzzing: 1,000+ randomized iterations testing state machine robustness under chaotic frame sequences.
"""

import asyncio
import os
import re
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import random
import string

# Ensure server directory is in sys.path
server_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from agent_live import StartTriggerProcessor, GeminiSessionLoggerMixin
from processors.repeat_on_interruption import RepeatOnInterruptionProcessor
from pipecat.frames.frames import (
    Frame,
    TextFrame,
    InterruptionFrame,
    CancelFrame,
    StartFrame,
    EndFrame,
    InputTransportMessageFrame,
    OutputTransportMessageFrame,
    LLMMessagesAppendFrame,
    LLMRunFrame,
    LLMFullResponseEndFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


def mock_processor_lifecycle(proc):
    """Helper to mock task manager and async lifecycle hooks on a standalone FrameProcessor."""
    mock_tm = MagicMock()
    mock_tm.create_task = MagicMock(return_value=MagicMock())
    proc._task_manager = mock_tm
    proc.create_task = MagicMock(return_value=MagicMock())
    proc._start_interruption = AsyncMock()
    proc._stop_interruption = AsyncMock()
    return proc


class MockBaseGeminiService(FrameProcessor):
    """Mock base class mirroring GeminiLiveLLMService for mixin inheritance testing."""
    async def _handle_msg_input_transcription(self, message):
        pass

    async def process_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        pass


class MockGeminiSessionLogger(GeminiSessionLoggerMixin, MockBaseGeminiService):
    """Mock subclass combining GeminiSessionLoggerMixin and MockBaseGeminiService."""
    def __init__(self, filler_max_words: int = 2):
        super().__init__()
        self._disconnecting = False
        self._session = MagicMock()
        self._filler_max_words = filler_max_words
        self._bot_turn_text_buffer = ""
        self._post_interruption_buffer = ""
        self._repeat_on_filler_pending = False
        self._user_is_speaking = False
        self._active_tools_in_flight = 0
        self._frame_locked_tools = False
        self._tool_lock_started_at = None
        self.pushed_frames = []
        self.sent_repeat_instructions = []
        self.created_responses = []
        mock_processor_lifecycle(self)

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        self.pushed_frames.append((frame, direction))

    async def _create_single_response(self, messages):
        self.created_responses.append(messages)


class TestStartTriggerProcessorAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing for StartTriggerProcessor."""

    async def test_rapid_burst_1000_sequential_start_triggers(self):
        """Stress: 1000 consecutive start_trigger frames must produce exactly 1 greeting and 1000 ACK responses."""
        processor = mock_processor_lifecycle(StartTriggerProcessor(language="hi-IN"))
        pushed_frames = []

        async def capture_frame(frame, direction=FrameDirection.DOWNSTREAM):
            pushed_frames.append(frame)

        processor.push_frame = capture_frame

        for i in range(1000):
            req_id = f"req-{i:04d}"
            frame = InputTransportMessageFrame(message={"type": "start_trigger", "id": req_id})
            await processor.process_frame(frame)

        self.assertTrue(processor.triggered)

        # Count frame types
        ack_frames = [f for f in pushed_frames if isinstance(f, OutputTransportMessageFrame)]
        append_frames = [f for f in pushed_frames if isinstance(f, LLMMessagesAppendFrame)]
        run_frames = [f for f in pushed_frames if isinstance(f, LLMRunFrame)]

        self.assertEqual(len(ack_frames), 1000, "Must send an ACK response for every request with an ID")
        self.assertEqual(len(append_frames), 1, "Must emit exactly ONE greeting frame across 1000 bursts")
        self.assertEqual(len(run_frames), 1, "Must emit exactly ONE LLMRunFrame across 1000 bursts")

        # Verify content of greeting
        self.assertEqual(append_frames[0].messages[0]["content"], "नमस्ते!")
        self.assertEqual(ack_frames[0].message["id"], "req-0000")
        self.assertEqual(ack_frames[999].message["id"], "req-0999")

    async def test_concurrent_burst_start_triggers(self):
        """Stress: 50 concurrent async tasks attempting to trigger greeting simultaneously."""
        processor = mock_processor_lifecycle(StartTriggerProcessor(language="en-IN"))
        pushed_frames = []

        async def capture_frame(frame, direction=FrameDirection.DOWNSTREAM):
            pushed_frames.append(frame)

        processor.push_frame = capture_frame

        async def send_trigger(idx):
            await processor.process_frame(
                InputTransportMessageFrame(message={"type": "start_trigger", "id": f"concurrent-{idx}"})
            )

        # Launch 50 concurrent triggers
        await asyncio.gather(*(send_trigger(i) for i in range(50)))

        self.assertTrue(processor.triggered)
        append_frames = [f for f in pushed_frames if isinstance(f, LLMMessagesAppendFrame)]
        run_frames = [f for f in pushed_frames if isinstance(f, LLMRunFrame)]

        self.assertEqual(len(append_frames), 1, "Concurrency must not cause race conditions in single-greeting latch")
        self.assertEqual(len(run_frames), 1)
        self.assertEqual(append_frames[0].messages[0]["content"], "नमस्ते!")

    async def test_corrupted_and_malformed_messages(self):
        """Stress: Process corrupted, malformed, and non-dict messages without throwing unhandled exceptions."""
        processor = mock_processor_lifecycle(StartTriggerProcessor(language="hi-IN"))
        pushed_frames = []

        async def capture_frame(frame, direction=FrameDirection.DOWNSTREAM):
            pushed_frames.append(frame)

        processor.push_frame = capture_frame

        malformed_messages = [
            None,
            "just a string",
            12345,
            3.14159,
            [],
            [{"type": "start_trigger"}],
            {},
            {"type": None},
            {"type": 123},
            {"type": "unrelated_type", "id": "req-999"},
            {"type": "start_trigger", "id": None},
            {"type": "start_trigger", "id": ""},
            {"type": "start_trigger", "id": 12345},  # Non-string ID
            {"invalid_key": "some_value"},
        ]

        for msg in malformed_messages:
            frame = InputTransportMessageFrame(message=msg)
            # Must not throw
            await processor.process_frame(frame)

        self.assertTrue(processor.triggered, "start_trigger with None/empty/int ID should still trigger the greeting")
        append_frames = [f for f in pushed_frames if isinstance(f, LLMMessagesAppendFrame)]
        self.assertEqual(len(append_frames), 1)

    async def test_non_transport_frames_pass_through(self):
        """Frames that are not start_trigger must pass through with direction preserved."""
        processor = mock_processor_lifecycle(StartTriggerProcessor(language="hi-IN"))
        pushed_frames = []

        async def capture_frame(frame, direction=FrameDirection.DOWNSTREAM):
            pushed_frames.append((frame, direction))

        processor.push_frame = capture_frame

        frames_to_test = [
            (TextFrame(text="test text"), FrameDirection.DOWNSTREAM),
            (InterruptionFrame(), FrameDirection.UPSTREAM),
            (TranscriptionFrame(text="hello", user_id="u1", timestamp="t1"), FrameDirection.DOWNSTREAM),
            (UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM),
            (UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM),
            (BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM),
            (BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM),
        ]

        for frame, direction in frames_to_test:
            await processor.process_frame(frame, direction)

        self.assertEqual(len(pushed_frames), len(frames_to_test))
        for i, (orig_frame, orig_dir) in enumerate(frames_to_test):
            self.assertEqual(pushed_frames[i][0], orig_frame)
            self.assertEqual(pushed_frames[i][1], orig_dir)

    async def test_exhaustive_locale_sweep(self):
        """Stress: Comprehensive sweep across Indian, non-Indian, malformed, and boundary locales."""
        # Indian locales -> "नमस्ते!"
        indian_locales = [
            "hi-IN", "hi", "en-IN", "hi-Latn", "hi-Deva", "hindi", "hi_IN", "hi-ZZ"
        ]
        for loc in indian_locales:
            proc = mock_processor_lifecycle(StartTriggerProcessor(language=loc))
            frames = []
            async def capture(f, d=None): frames.append(f)
            proc.push_frame = capture
            await proc.process_frame(InputTransportMessageFrame(message={"type": "start_trigger"}))
            app = [f for f in frames if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(app), 1, f"Failed for {loc}")
            self.assertEqual(app[0].messages[0]["content"], "नमस्ते!", f"Failed greeting for {loc}")

        # Non-Indian locales -> "Hello!"
        foreign_locales = [
            "en-US", "en-GB", "es-ES", "es-US", "fr-FR", "de-DE", "ja-JP", "zh-CN", "ar-XA", "ru-RU",
            "pt-BR", "it-IT", "ko-KR", "nl-NL"
        ]
        for loc in foreign_locales:
            proc = mock_processor_lifecycle(StartTriggerProcessor(language=loc))
            frames = []
            async def capture(f, d=None): frames.append(f)
            proc.push_frame = capture
            await proc.process_frame(InputTransportMessageFrame(message={"type": "start_trigger"}))
            app = [f for f in frames if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(app), 1, f"Failed for {loc}")
            self.assertEqual(app[0].messages[0]["content"], "Hello!", f"Failed greeting for {loc}")

        # Boundary / Malformed types -> "Hello!" without crashing
        weird_locales = [
            None, "", "   ", 123, 3.14, [], {}, True, False
        ]
        for loc in weird_locales:
            proc = mock_processor_lifecycle(StartTriggerProcessor(language=loc))
            frames = []
            async def capture(f, d=None): frames.append(f)
            proc.push_frame = capture
            await proc.process_frame(InputTransportMessageFrame(message={"type": "start_trigger"}))
            app = [f for f in frames if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(app), 1, f"Failed for weird locale: {loc}")
            self.assertEqual(app[0].messages[0]["content"], "Hello!", f"Failed greeting fallback for {loc}")


class TestRepeatOnInterruptionProcessorAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing for RepeatOnInterruptionProcessor."""

    async def test_word_count_boundary_conditions(self):
        """Stress: Boundary testing word counts 0, 1, 2, 3, 4, 100 words."""
        # 0 words (empty text or whitespace only)
        for empty_text in ["", "   ", "\t\n", "\u00a0\u00a0", "\u200b"]:
            proc = mock_processor_lifecycle(RepeatOnInterruptionProcessor(filler_max_words=2))
            pushed = []
            async def cap(f, d=None): pushed.append((f, d))
            proc.push_frame = cap

            await proc.process_frame(InterruptionFrame(), FrameDirection.UPSTREAM)
            await proc.process_frame(TranscriptionFrame(text=empty_text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

            app = [f for f, d in pushed if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(app), 1, f"Failed on empty text: {repr(empty_text)}")
            self.assertTrue(bool(getattr(app[0], "run_llm", False)))
            self.assertFalse(proc._was_interrupted)

        # 1 word
        for text in ["haan", "हाँ", "okay", "acha", "hmm", "ji", "theek"]:
            proc = mock_processor_lifecycle(RepeatOnInterruptionProcessor(filler_max_words=2))
            pushed = []
            async def cap(f, d=None): pushed.append((f, d))
            proc.push_frame = cap

            await proc.process_frame(InterruptionFrame(), FrameDirection.UPSTREAM)
            await proc.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

            app = [f for f, d in pushed if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(app), 1)
            self.assertTrue(bool(getattr(app[0], "run_llm", False)), f"1 word '{text}' must trigger repeat with run_llm=True")
            self.assertIn("short filler/acknowledgment", app[0].messages[0]["content"])

        # 2 words
        for text in ["theek hai", "haan ji", "ji bilkul", "uh huh", "okay sure", "all right"]:
            proc = mock_processor_lifecycle(RepeatOnInterruptionProcessor(filler_max_words=2))
            pushed = []
            async def cap(f, d=None): pushed.append((f, d))
            proc.push_frame = cap

            await proc.process_frame(InterruptionFrame(), FrameDirection.UPSTREAM)
            await proc.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

            app = [f for f, d in pushed if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(app), 1)
            self.assertTrue(bool(getattr(app[0], "run_llm", False)), f"2 words '{text}' must trigger repeat with run_llm=True")

        # 3 words (exact boundary cutoff)
        for text in ["wait one second", "kya bola aapne", "tell me more", "I have question", "rukhiye ek minute"]:
            proc = mock_processor_lifecycle(RepeatOnInterruptionProcessor(filler_max_words=2))
            pushed = []
            async def cap(f, d=None): pushed.append((f, d))
            proc.push_frame = cap

            await proc.process_frame(InterruptionFrame(), FrameDirection.UPSTREAM)
            await proc.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

            app = [f for f, d in pushed if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(app), 1)
            self.assertFalse(bool(getattr(app[0], "run_llm", False)), f"3 words '{text}' must NOT run LLM immediately")
            self.assertIn("The user interrupted you", app[0].messages[0]["content"])

        # 100 words
        long_text = " ".join(["word" for _ in range(100)])
        proc = mock_processor_lifecycle(RepeatOnInterruptionProcessor(filler_max_words=2))
        pushed = []
        async def cap(f, d=None): pushed.append((f, d))
        proc.push_frame = cap

        await proc.process_frame(InterruptionFrame(), FrameDirection.UPSTREAM)
        await proc.process_frame(TranscriptionFrame(text=long_text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

        app = [f for f, d in pushed if isinstance(f, LLMMessagesAppendFrame)]
        self.assertEqual(len(app), 1)
        self.assertFalse(bool(getattr(app[0], "run_llm", False)))
        self.assertIn("The user interrupted you", app[0].messages[0]["content"])

    async def test_hindi_danda_and_special_punctuation(self):
        """Stress: Punctuation like Hindi danda '।', double danda '॥', '?', '!', ellipses."""
        punct_cases = [
            ("हाँ।", 1, True),
            ("हाँ॥", 1, True),
            ("ठीक है?", 2, True),
            ("जी बिल्कुल!", 2, True),
            ("hmm... ठीक है।", 3, False),  # 3 words -> genuine
            ("हाँ, ठीक है।", 3, False),     # 3 words -> genuine
            ("अच्छा...", 1, True),
        ]

        for text, expected_words, expected_run_llm in punct_cases:
            proc = mock_processor_lifecycle(RepeatOnInterruptionProcessor(filler_max_words=2))
            pushed = []
            async def cap(f, d=None): pushed.append((f, d))
            proc.push_frame = cap

            await proc.process_frame(InterruptionFrame(), FrameDirection.UPSTREAM)
            await proc.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

            app = [f for f, d in pushed if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(app), 1)
            actual_run = bool(getattr(app[0], "run_llm", False))
            self.assertEqual(actual_run, expected_run_llm, f"Failed for text '{text}': expected run_llm={expected_run_llm}, got {actual_run}")

    async def test_unicode_whitespace_handling(self):
        """Stress: Unicode whitespaces (NBSP \\u00a0, Em space \\u2003, Thin space \\u2009, Tabs)."""
        unicode_space_cases = [
            ("theek\u00a0hai", 2, True),          # NBSP
            ("theek\u2003hai", 2, True),          # Em space
            ("theek\u2009hai", 2, True),          # Thin space
            ("theek\t\thai\n", 2, True),          # Tabs and newlines
            ("   theek     hai   ", 2, True),     # Multiple standard spaces
            ("ek\u00a0do\u00a0teen", 3, False),   # 3 words with NBSP
        ]

        for text, exp_words, exp_run in unicode_space_cases:
            proc = mock_processor_lifecycle(RepeatOnInterruptionProcessor(filler_max_words=2))
            pushed = []
            async def cap(f, d=None): pushed.append((f, d))
            proc.push_frame = cap

            await proc.process_frame(InterruptionFrame(), FrameDirection.UPSTREAM)
            await proc.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

            app = [f for f, d in pushed if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(app), 1)
            actual_run = bool(getattr(app[0], "run_llm", False))
            self.assertEqual(actual_run, exp_run, f"Failed for '{text}'")

    async def test_rapid_burst_interruptions_without_speech(self):
        """Stress: Multiple rapid interruptions without any transcription frames, followed by normal conversation."""
        proc = mock_processor_lifecycle(RepeatOnInterruptionProcessor(filler_max_words=2))
        pushed = []
        async def cap(f, d=None): pushed.append((f, d))
        proc.push_frame = cap

        # Rapid burst of 10 interruptions in a row
        for _ in range(10):
            await proc.process_frame(InterruptionFrame(), FrameDirection.UPSTREAM)

        self.assertTrue(proc._was_interrupted)

        # Normal text frame during interruption
        await proc.process_frame(TextFrame(text="some text"), FrameDirection.DOWNSTREAM)

        # Now a filler transcription arrives
        await proc.process_frame(TranscriptionFrame(text="theek hai", user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

        app = [f for f, d in pushed if isinstance(f, LLMMessagesAppendFrame)]
        self.assertEqual(len(app), 1, "Should trigger exactly one resume frame for the subsequent filler")
        self.assertTrue(bool(getattr(app[0], "run_llm", False)))
        self.assertFalse(proc._was_interrupted)

    async def test_transcriptions_without_prior_interruption_ignored(self):
        """Transcriptions arriving during normal non-interrupted flow must not trigger repeat frames."""
        proc = mock_processor_lifecycle(RepeatOnInterruptionProcessor(filler_max_words=2))
        pushed = []
        async def cap(f, d=None): pushed.append((f, d))
        proc.push_frame = cap

        # 5 normal user turns without interruption
        for text in ["haan", "theek hai", "what are the returns?", "50000 rupees", "okay"]:
            await proc.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

        app = [f for f, d in pushed if isinstance(f, LLMMessagesAppendFrame)]
        self.assertEqual(len(app), 0, "No repeat frames should be emitted without an interruption")


class TestGeminiSessionLoggerRepeatOnFillerAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing for RepeatOnFiller inside GeminiSessionLoggerMixin."""

    async def test_streaming_chunk_accumulation_and_punctuation_triggers(self):
        """Stress: Streaming partial audio transcription chunks ending with punctuation [. । ! ? \\n]."""
        session_logger = MockGeminiSessionLogger(filler_max_words=2)

        # Step 1: Trigger interruption
        await session_logger.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        self.assertTrue(session_logger._repeat_on_filler_pending)

        # Helper to create mock input transcription message
        def make_msg(chunk_text):
            msg = MagicMock()
            msg.server_content.input_transcription.text = chunk_text
            return msg

        # Step 2: Stream chunks without sentence ending
        session_logger._user_is_speaking = True
        msg1 = make_msg("theek ")
        await session_logger._handle_msg_input_transcription(msg1)
        self.assertEqual(session_logger._post_interruption_buffer, "theek ")
        self.assertTrue(session_logger._repeat_on_filler_pending)
        self.assertEqual(len(session_logger.created_responses), 0)

        # Second chunk: "hai।" (Hindi danda sentence end)
        msg2 = make_msg("hai।")
        await session_logger._handle_msg_input_transcription(msg2)

        # Should detect sentence end and fire repeat instruction
        self.assertFalse(session_logger._repeat_on_filler_pending)
        self.assertEqual(session_logger._post_interruption_buffer, "")
        self.assertEqual(len(session_logger.created_responses), 1)

        repeat_prompt = session_logger.created_responses[0][0]["content"]
        self.assertIn("The user just said 'theek hai।'", repeat_prompt)
        self.assertIn("short filler/acknowledgment", repeat_prompt)
        self.assertIn("REPEAT your previous response from the beginning", repeat_prompt)

    async def test_user_stopped_speaking_trigger_without_punctuation(self):
        """Stress: User stops speaking without emitting punctuation (VAD silence trigger)."""
        session_logger = MockGeminiSessionLogger(filler_max_words=2)
        await session_logger.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)

        def make_msg(chunk_text):
            msg = MagicMock()
            msg.server_content.input_transcription.text = chunk_text
            return msg

        # User says "haan ji" without any punctuation, then stops speaking
        session_logger._user_is_speaking = False  # VAD says stopped
        msg = make_msg("haan ji")
        await session_logger._handle_msg_input_transcription(msg)

        self.assertFalse(session_logger._repeat_on_filler_pending)
        self.assertEqual(len(session_logger.created_responses), 1)
        self.assertIn("The user just said 'haan ji'", session_logger.created_responses[0][0]["content"])

    async def test_genuine_interruption_in_gemini_mixin(self):
        """Stress: 3+ words in GeminiSessionLoggerMixin resets buffer without firing repeat instruction."""
        session_logger = MockGeminiSessionLogger(filler_max_words=2)
        await session_logger.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)

        def make_msg(chunk_text):
            msg = MagicMock()
            msg.server_content.input_transcription.text = chunk_text
            return msg

        session_logger._user_is_speaking = False
        msg = make_msg("what is the interest rate on STL 7M?")
        await session_logger._handle_msg_input_transcription(msg)

        self.assertFalse(session_logger._repeat_on_filler_pending)
        self.assertEqual(session_logger._post_interruption_buffer, "")
        self.assertEqual(len(session_logger.created_responses), 0, "Must NOT send repeat instruction for 3+ words")


class TestDifferentialFuzzingHarness(unittest.IsolatedAsyncioTestCase):
    """Differential & Chaos Fuzzing: 1,000 randomized state machine executions."""

    async def test_fuzz_repeat_on_interruption_processor_1000_iterations(self):
        """Fuzz 1000 iterations of random frame streams and verify zero uncaught exceptions & strict invariant satisfaction."""
        random.seed(42)

        filler_vocab = ["haan", "हाँ", "ji", "जी", "theek", "ठीक", "hai", "है", "okay", "acha", "अच्छा", "hmm", "right", "sure", "uh huh"]
        question_vocab = ["what", "how", "kya", "kyun", "kab", "returns", "profit", "interest", "investment", "rupees", "tenure", "months", "risk", "KYC"]
        punct_vocab = ["", ".", "।", "॥", "?", "!", "\n", "...", "!?"]
        whitespace_vocab = [" ", "\u00a0", "\u2003", "\t", "  "]

        for iteration in range(1000):
            proc = mock_processor_lifecycle(RepeatOnInterruptionProcessor(filler_max_words=2))
            pushed = []
            async def cap(f, d=None): pushed.append((f, d))
            proc.push_frame = cap

            # Generate random sequence of 10-30 events
            num_events = random.randint(10, 30)
            was_interrupted_oracle = False

            for _ in range(num_events):
                event_type = random.choice([
                    "interruption",
                    "text_downstream",
                    "transcription_filler",
                    "transcription_question",
                    "transcription_empty",
                    "response_end",
                    "other_frame",
                ])

                if event_type == "interruption":
                    was_interrupted_oracle = True
                    await proc.process_frame(InterruptionFrame(), FrameDirection.UPSTREAM)
                    self.assertTrue(proc._was_interrupted)

                elif event_type == "text_downstream":
                    txt = "".join(random.choices(string.ascii_letters, k=10))
                    await proc.process_frame(TextFrame(text=txt), FrameDirection.DOWNSTREAM)

                elif event_type == "transcription_filler":
                    # 1 or 2 words
                    w_count = random.randint(1, 2)
                    words = random.sample(filler_vocab, w_count)
                    sep = random.choice(whitespace_vocab)
                    pct = random.choice(punct_vocab)
                    text = sep.join(words) + pct

                    pushed_before = len(pushed)
                    await proc.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

                    if was_interrupted_oracle:
                        # Oracle: word count check
                        clean = text.strip()
                        actual_w_count = len(clean.split())
                        app_frames = [f for f, d in pushed[pushed_before:] if isinstance(f, LLMMessagesAppendFrame)]
                        self.assertEqual(len(app_frames), 1, f"Iteration {iteration}: Missing LLMMessagesAppendFrame for '{text}'")

                        if actual_w_count <= 2:
                            self.assertTrue(bool(getattr(app_frames[0], "run_llm", False)), f"Iteration {iteration}: Expected run_llm=True for '{text}' ({actual_w_count} words)")
                        else:
                            self.assertFalse(bool(getattr(app_frames[0], "run_llm", False)), f"Iteration {iteration}: Expected run_llm=False for '{text}' ({actual_w_count} words)")

                        was_interrupted_oracle = False
                        self.assertFalse(proc._was_interrupted)

                elif event_type == "transcription_question":
                    # 3 to 10 words
                    w_count = random.randint(3, 10)
                    words = random.choices(question_vocab + filler_vocab, k=w_count)
                    sep = random.choice(whitespace_vocab)
                    pct = random.choice(punct_vocab)
                    text = sep.join(words) + pct

                    pushed_before = len(pushed)
                    await proc.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

                    if was_interrupted_oracle:
                        clean = text.strip()
                        actual_w_count = len(clean.split())
                        app_frames = [f for f, d in pushed[pushed_before:] if isinstance(f, LLMMessagesAppendFrame)]
                        self.assertEqual(len(app_frames), 1)
                        if actual_w_count <= 2:
                            self.assertTrue(bool(getattr(app_frames[0], "run_llm", False)))
                        else:
                            self.assertFalse(bool(getattr(app_frames[0], "run_llm", False)))

                        was_interrupted_oracle = False
                        self.assertFalse(proc._was_interrupted)

                elif event_type == "transcription_empty":
                    text = random.choice(["", "   ", "\t", "\u00a0\u00a0"])
                    pushed_before = len(pushed)
                    await proc.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

                    if was_interrupted_oracle:
                        app_frames = [f for f, d in pushed[pushed_before:] if isinstance(f, LLMMessagesAppendFrame)]
                        self.assertEqual(len(app_frames), 1)
                        self.assertTrue(bool(getattr(app_frames[0], "run_llm", False)))
                        was_interrupted_oracle = False
                        self.assertFalse(proc._was_interrupted)

                elif event_type == "response_end":
                    await proc.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
                    if not was_interrupted_oracle:
                        self.assertEqual(proc._current_response, "")

                elif event_type == "other_frame":
                    other = random.choice([
                        BotStartedSpeakingFrame(),
                        BotStoppedSpeakingFrame(),
                        UserStartedSpeakingFrame(),
                        UserStoppedSpeakingFrame(),
                    ])
                    await proc.process_frame(other, FrameDirection.DOWNSTREAM)


if __name__ == "__main__":
    unittest.main()
