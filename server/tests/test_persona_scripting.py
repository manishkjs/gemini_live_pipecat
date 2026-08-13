"""Unit tests for Pragya Persona Scripting, Conversational Dynamics, Script Mixing,
PTA Filler Rotation, StartTriggerProcessor, and RepeatOnFiller (Milestone 3 / R3).
"""

import asyncio
import os
import re
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestPersonaPromptIdentity(unittest.TestCase):
    """Validates Pragya persona identity, title, organization, tone, and gender verb rules."""

    def test_persona_name_and_title(self):
        """Asserts Pragya, Senior Wealth Manager (वरिष्ठ वेल्थ मैनेजर), Cymbal Lending, RBI-registered NBFC-P2P."""
        self.assertIn("प्रज्ञा (Pragya)", SYSTEM_PROMPT)
        self.assertIn("Senior Wealth Manager (वरिष्ठ वेल्थ मैनेजर)", SYSTEM_PROMPT)
        self.assertIn("सिम्बल लेंडिंग (Cymbal Lending — an RBI-registered NBFC-P2P lending platform)", SYSTEM_PROMPT)

    def test_female_gender_and_verb_forms(self):
        """Asserts feminine gender declaration and feminine Hindi verb conjugations."""
        self.assertIn("You are female", SYSTEM_PROMPT)
        self.assertIn('"मैं बता रही हूँ"', SYSTEM_PROMPT)
        self.assertIn('"मैं समझ सकती हूँ"', SYSTEM_PROMPT)
        self.assertIn('"मैं help करूँगी"', SYSTEM_PROMPT)

    def test_advisor_tone_not_telemarketer(self):
        """Asserts calm, authoritative wealth advisor tone and anti-telemarketer constraint."""
        self.assertIn("senior private wealth advisor", SYSTEM_PROMPT)
        self.assertIn("never an aggressive telemarketer", SYSTEM_PROMPT)

    def test_tts_prompt_identity(self):
        """Asserts fallback TTS prompt matches persona title, organization, and verb forms."""
        self.assertIn("Pragya", tts_prompt)
        self.assertIn("Senior Wealth Manager (वरिष्ठ वेल्थ मैनेजर)", tts_prompt)
        self.assertIn("Cymbal Lending", tts_prompt)
        self.assertIn('"मैं बता रही हूँ"', tts_prompt)
        self.assertEqual(GEMINI_LLM_TTS_PROMPT, SYSTEM_PROMPT)


class TestScriptMixingAndLanguageRules(unittest.TestCase):
    """Validates Devanagari Hindi + Latin English code-mixing rules and absence of Romanized Hindi."""

    def test_four_script_mixing_rules_presence(self):
        """Asserts all 4 foundational script mixing rules are explicitly defined."""
        # Rule 1: Hindi in Devanagari
        self.assertIn("1. Hindi words MUST be written in Devanagari script", SYSTEM_PROMPT)
        self.assertIn('"मैं"', SYSTEM_PROMPT)
        self.assertIn('"आप"', SYSTEM_PROMPT)
        self.assertIn('"क्या"', SYSTEM_PROMPT)
        self.assertIn('"हाँ"', SYSTEM_PROMPT)

        # Rule 2: English terms in Latin
        self.assertIn("2. English financial/technical terms MUST be written in Latin script", SYSTEM_PROMPT)
        self.assertIn('"portfolio"', SYSTEM_PROMPT)
        self.assertIn('"returns"', SYSTEM_PROMPT)
        self.assertIn('"XIRR"', SYSTEM_PROMPT)
        self.assertIn('"diversification"', SYSTEM_PROMPT)
        self.assertIn('"borrower"', SYSTEM_PROMPT)
        self.assertIn('"KYC"', SYSTEM_PROMPT)
        self.assertIn('"escrow"', SYSTEM_PROMPT)

        # Rule 3: Forbidden Romanized Hindi
        self.assertIn("3. FORBIDDEN: Hindi written in English letters", SYSTEM_PROMPT)

        # Rule 4: Forbidden Devanagari English
        self.assertIn("4. FORBIDDEN: English words written in Devanagari script", SYSTEM_PROMPT)

    def test_no_romanized_hindi_in_number_rules(self):
        """Asserts no Romanized Hindi phrases like 'ek lakh rupaye' in rules and proper number examples."""
        self.assertNotIn("ek lakh rupaye", SYSTEM_PROMPT)
        self.assertIn('"fifty thousand rupees"', SYSTEM_PROMPT)
        self.assertIn('"50,000 रुपये"', SYSTEM_PROMPT)
        self.assertIn('"एक लाख रुपये"', SYSTEM_PROMPT)

    def test_pacing_prosody_and_punctuation_rules(self):
        """Asserts 12-20 words per sentence limit and mandatory punctuation (. , ?)."""
        self.assertIn("12–20 words max per sentence", SYSTEM_PROMPT)
        self.assertIn("ALWAYS use proper punctuation: periods (.), commas (,), question marks (?)", SYSTEM_PROMPT)


class TestPTAFillerRotationAndCaps(unittest.TestCase):
    """Validates PTA (Pause-Think-Answer) 4-group filler rotation and 'अच्छा' occurrence cap."""

    def test_pta_four_groups_defined_in_devanagari(self):
        """Asserts Groups A, B, C, and D are present with proper Devanagari and Latin fillers."""
        self.assertIn('Group A (Thinking): "Hmm...", "Uhh..."', SYSTEM_PROMPT)
        self.assertIn('Group B (Transitions): "तो...", "हाँ तो...", "So..."', SYSTEM_PROMPT)
        self.assertIn('Group C (Acknowledgment): "Okay...", "ठीक है...", "जी बिल्कुल..."', SYSTEM_PROMPT)
        self.assertIn('Group D (Light discovery): "Actually...", "देखिए..."', SYSTEM_PROMPT)

    def test_pta_rotation_and_achha_cap_rules(self):
        """Asserts no consecutive same-group fillers and max 1 occurrence cap for 'अच्छा' / 'Achha'."""
        self.assertIn("Never use fillers from the same group twice in a row", SYSTEM_PROMPT)
        self.assertIn('"अच्छा" ("Achha") is permitted at most ONCE in the entire call.', SYSTEM_PROMPT)


class TestDeterministicToolsGuideline(unittest.TestCase):
    """Validates deterministic calculation mandates and tool output transliteration instructions."""

    def test_mental_arithmetic_forbidden(self):
        """Asserts mental arithmetic is strictly prohibited."""
        self.assertIn("NEVER PERFORM MENTAL ARITHMETIC", SYSTEM_PROMPT)
        self.assertIn("NEVER guess or hallucinate rupee profits or interest rates", SYSTEM_PROMPT)

    def test_tool_output_transliteration_rule(self):
        """Asserts rule commanding transliteration of tool outputs to Devanagari with Latin terms."""
        self.assertIn("ALWAYS transliterate any Romanized Hindi words from tool outputs into Devanagari script", SYSTEM_PROMPT)
        self.assertIn('"50,000 रुपये"', SYSTEM_PROMPT)
        self.assertIn('"6 महीने"', SYSTEM_PROMPT)
        self.assertIn('"लगभग"', SYSTEM_PROMPT)


class TestFewShotExamplesCompliance(unittest.TestCase):
    """Validates few-shot audio examples for Devanagari Hindi + Latin English script adherence."""

    def test_example_1_compliance(self):
        """Example 1 uses 'नमस्ते!', feminine Hindi, and Latin terms."""
        self.assertIn('Pragya: "नमस्ते! मैं प्रज्ञा बात कर रही हूँ, Cymbal Lending से।', SYSTEM_PROMPT)
        self.assertNotIn('Pragya: "Namaste!', SYSTEM_PROMPT)

    def test_example_2_compliance(self):
        """Example 2 uses 'देखिए', 'रुपये', and Devanagari question without Romanized Hindi."""
        self.assertIn('Pragya: "देखिए, अगर आप 50,000 रुपये 6 months के लिए STL 7M plan में invest करते हैं', SYSTEM_PROMPT)
        self.assertIn('क्या आप monthly payout prefer करेंगे?', SYSTEM_PROMPT)
        self.assertNotIn("Kya aap monthly payout prefer karenge?", SYSTEM_PROMPT)
        self.assertNotIn("50,000 rupaye", SYSTEM_PROMPT)
        self.assertNotIn("lagbhag 9,083", SYSTEM_PROMPT)

    def test_example_3_compliance(self):
        """Example 3 uses Devanagari Hindi with Latin financial terms and no Romanized Hindi."""
        self.assertIn('Pragya: "यह बहुत अच्छा question है! 1 लाख रुपये के example से step-by-step समझते हैं:', SYSTEM_PROMPT)
        self.assertIn('5% NPA loss निकालने के बाद 95,000 रुपये performing रहेंगे।', SYSTEM_PROMPT)
        self.assertIn('इसलिए diversification ज़रूरी है!', SYSTEM_PROMPT)
        self.assertNotIn("Yeh bahut achha question hai!", SYSTEM_PROMPT)
        self.assertNotIn("nikalne ke baad", SYSTEM_PROMPT)
        self.assertNotIn("samajhte hain", SYSTEM_PROMPT)


class TestStartTriggerProcessor(unittest.IsolatedAsyncioTestCase):
    """Validates StartTriggerProcessor single-greeting dispatch, language selection, and duplicate suppression."""

    async def test_single_greeting_turn_hi_in(self):
        """Receiving start_trigger in hi-IN emits 'नमस्ते!' greeting frame only once."""
        processor = StartTriggerProcessor(language="hi-IN")
        pushed_frames = []

        async def capture_frame(frame, direction=None):
            pushed_frames.append(frame)

        processor.push_frame = capture_frame

        # First trigger
        msg_frame1 = InputTransportMessageFrame(message={"type": "start_trigger", "id": "req-001"})
        await processor.process_frame(msg_frame1)

        self.assertTrue(processor.triggered)
        # Should push OutputTransportMessageFrame, LLMMessagesAppendFrame, LLMRunFrame
        self.assertEqual(len(pushed_frames), 3)
        self.assertIsInstance(pushed_frames[0], OutputTransportMessageFrame)
        self.assertEqual(pushed_frames[0].message["id"], "req-001")
        self.assertEqual(pushed_frames[0].message["data"]["status"], "ok")

        self.assertIsInstance(pushed_frames[1], LLMMessagesAppendFrame)
        self.assertEqual(pushed_frames[1].messages[0]["content"], "नमस्ते!")

        self.assertIsInstance(pushed_frames[2], LLMRunFrame)

        # Second trigger (duplicate / reconnect)
        pushed_frames.clear()
        msg_frame2 = InputTransportMessageFrame(message={"type": "start_trigger", "id": "req-002"})
        await processor.process_frame(msg_frame2)

        # Only response frame sent; no duplicate LLMMessagesAppendFrame or LLMRunFrame
        self.assertEqual(len(pushed_frames), 1)
        self.assertIsInstance(pushed_frames[0], OutputTransportMessageFrame)
        self.assertEqual(pushed_frames[0].message["id"], "req-002")

    async def test_language_selection_greetings(self):
        """Tests language codes mapping to 'नमस्ते!' vs 'Hello!'."""
        for lang in ("hi-IN", "hi", "en-IN", "hi-Latn"):
            proc = StartTriggerProcessor(language=lang)
            frames = []
            async def capture_f(f, d=None):
                frames.append(f)
            proc.push_frame = capture_f
            await proc.process_frame(InputTransportMessageFrame(message={"type": "start_trigger"}))
            append_frames = [f for f in frames if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(append_frames), 1)
            self.assertEqual(append_frames[0].messages[0]["content"], "नमस्ते!", f"Failed for {lang}")

        for lang in ("en-US", "en-GB", "es-ES", "fr-FR"):
            proc = StartTriggerProcessor(language=lang)
            frames = []
            async def capture_f(f, d=None):
                frames.append(f)
            proc.push_frame = capture_f
            await proc.process_frame(InputTransportMessageFrame(message={"type": "start_trigger"}))
            append_frames = [f for f in frames if isinstance(f, LLMMessagesAppendFrame)]
            self.assertEqual(len(append_frames), 1)
            self.assertEqual(append_frames[0].messages[0]["content"], "Hello!", f"Failed for {lang}")


class TestRepeatOnFillerLogic(unittest.TestCase):
    """Validates repeat-on-filler word count thresholding (<=2 words vs >2 words) and sentence ending regex."""

    def test_word_count_filler_classification(self):
        """<=2 words are classified as fillers; >2 words are genuine interruptions."""
        filler_max_words = 2

        # 1-word fillers
        one_word_fillers = ["haan", "हाँ", "okay", "acha", "hmm", "ji", "theek", "right", "sure"]
        for f in one_word_fillers:
            clean = f.rstrip('।.!?\n').strip()
            word_count = len(clean.split()) if clean else 0
            self.assertLessEqual(word_count, filler_max_words, f"Expected '{f}' to be <= {filler_max_words}")

        # 2-word fillers
        two_word_fillers = ["ji bilkul", "theek hai", "uh huh", "okay sure", "haan ji", "all right", "got it"]
        for f in two_word_fillers:
            clean = f.rstrip('।.!?\n').strip()
            word_count = len(clean.split()) if clean else 0
            self.assertLessEqual(word_count, filler_max_words, f"Expected '{f}' to be <= {filler_max_words}")

        # 3+ word genuine interruptions
        genuine_interruptions = [
            "wait one second",
            "kya bola aapne",
            "tell me more",
            "what is the minimum investment amount",
            "rukhiye ek minute",
            "I have a question",
        ]
        for f in genuine_interruptions:
            clean = f.rstrip('।.!?\n').strip()
            word_count = len(clean.split()) if clean else 0
            self.assertGreater(word_count, filler_max_words, f"Expected '{f}' to be > {filler_max_words}")

    def test_sentence_end_regex_devanagari_and_latin(self):
        """Verifies sentence end pattern matching [.।!?\n] across Latin and Devanagari punctuation."""
        sentence_end_regex = r'[.।!?\n]'

        self.assertTrue(bool(re.search(sentence_end_regex, "हाँ।")))
        self.assertTrue(bool(re.search(sentence_end_regex, "okay.")))
        self.assertTrue(bool(re.search(sentence_end_regex, "really?")))
        self.assertTrue(bool(re.search(sentence_end_regex, "acha!")))
        self.assertTrue(bool(re.search(sentence_end_regex, "ji\n")))
        self.assertFalse(bool(re.search(sentence_end_regex, "haan ji")))


class TestRepeatOnInterruptionProcessor(unittest.IsolatedAsyncioTestCase):
    """Validates RepeatOnInterruptionProcessor frame processing and resume message generation."""

    async def test_short_filler_triggers_resume_frame(self):
        """Interruption followed by <=2 word filler pushes LLMMessagesAppendFrame with run_llm=True."""
        processor = RepeatOnInterruptionProcessor(filler_max_words=2)
        processor._start_interruption = AsyncMock()
        pushed_frames = []

        async def capture_frame(frame, direction=None):
            pushed_frames.append(frame)

        processor.push_frame = capture_frame

        # Step 1: Interruption
        await processor.process_frame(InterruptionFrame(), None)
        self.assertTrue(processor._was_interrupted)

        # Step 2: Short filler transcription
        await processor.process_frame(TranscriptionFrame(text="uh huh", user_id="user", timestamp="12:00"), None)

        append_frames = [f for f in pushed_frames if isinstance(f, LLMMessagesAppendFrame)]
        self.assertEqual(len(append_frames), 1)
        self.assertTrue(append_frames[0].run_llm)
        self.assertIn("The user just said 'uh huh' which is a short filler/acknowledgment", append_frames[0].messages[0]["content"])
        self.assertIn("resume exactly what you were saying", append_frames[0].messages[0]["content"])
        self.assertFalse(processor._was_interrupted)

    async def test_genuine_interruption_stores_context_note(self):
        """Interruption followed by >2 words pushes LLMMessagesAppendFrame with context note without run_llm=True."""
        processor = RepeatOnInterruptionProcessor(filler_max_words=2)
        processor._start_interruption = AsyncMock()
        pushed_frames = []

        async def capture_frame(frame, direction=None):
            pushed_frames.append(frame)

        processor.push_frame = capture_frame

        # Step 1: Interruption
        await processor.process_frame(InterruptionFrame(), None)

        # Step 2: 7-word genuine question
        await processor.process_frame(TranscriptionFrame(text="What is the difference between STL and MTL?", user_id="user", timestamp="12:00"), None)

        append_frames = [f for f in pushed_frames if isinstance(f, LLMMessagesAppendFrame)]
        self.assertEqual(len(append_frames), 1)
        self.assertFalse(getattr(append_frames[0], "run_llm", False))
        self.assertIn("The user interrupted you", append_frames[0].messages[0]["content"])
        self.assertFalse(processor._was_interrupted)


if __name__ == "__main__":
    unittest.main()

