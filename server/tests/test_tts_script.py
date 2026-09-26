"""Gemini 3.8 TTS speech-script contract (per the 3.8 Flash TTS developer guide).

In 3.8, `text` is a verbatim transcript: everything is spoken except inline
<vocal tags> and |pipe| backchannels. The cascade LLM must therefore write a
performable script, and the text pipeline must deliver the tags intact.
"""
import asyncio
import random
import unittest

import tts_script


def run(coro_or_value):
    return asyncio.run(coro_or_value) if asyncio.iscoroutine(coro_or_value) else coro_or_value


class TestSpeechPrompt(unittest.TestCase):
    def test_38_models_get_the_expressive_script_prompt(self):
        for model in ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-3.8-flash-lite-tts-aistudio"):
            p = tts_script.speech_prompt_for(model)
            for must in ("<laugh>", "<sigh>", "<short pause>", "verbatim", "..."):
                self.assertIn(must, p, f"{model}: {must}")
            self.assertIn("English", p, "tags stay in English even in Hindi")
            self.assertIn("|", p, "must forbid pipe backchannels for a single speaker")

    def test_older_gemini_tts_never_learns_38_tags(self):
        for model in ("gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"):
            p = tts_script.speech_prompt_for(model)
            self.assertTrue(p)
            self.assertNotIn("<laugh>", p)

    def test_non_gemini_tts_gets_no_prompt(self):
        self.assertEqual(tts_script.speech_prompt_for("google-tts"), "")

    def test_prompt_stays_small(self):
        # ~3.8 chars/token heuristic; keep the per-turn tax well under 400 tokens.
        self.assertLess(len(tts_script.speech_prompt_for("gemini-3.8-flash-tts")) / 3.8, 400)


class TestGemini38TextFilter(unittest.TestCase):
    def setUp(self):
        self.f = tts_script.Gemini38TextFilter()

    def filt(self, text):
        return run(self.f.filter(text))

    def test_supported_vocal_tags_survive_markdown_filtering(self):
        self.assertEqual(self.filt("Arre wah! <laugh> Bahut badhiya."), "Arre wah! <laugh> Bahut badhiya.")
        self.assertEqual(self.filt("Hmm... <sigh> theek hai, <short pause> dekhte hain."),
                         "Hmm... <sigh> theek hai, <short pause> dekhte hain.")
        self.assertIn("<throat-clearing>", self.filt("<throat-clearing> Achha suniye."))

    def test_plural_and_variant_vocal_tags_are_normalized(self):
        self.assertEqual(
            self.filt("Haha <laughs> theek hai, <sighs> <throat clearing> <pause> bataiye."),
            "Haha <laugh> theek hai, <sigh> <throat-clearing> <short pause> bataiye.",
        )

    def test_unknown_angle_tags_are_removed(self):
        out = self.filt("Theek hai <b>bold</b> <warmly> chaliye.")
        self.assertNotIn("<", out)
        self.assertIn("chaliye", out)

    def test_pipe_backchannels_are_dropped_for_a_single_speaker(self):
        out = self.filt("Main |haan| sun raha hoon.")
        self.assertNotIn("|", out)
        self.assertNotIn("haan", out, "a backchannel is another speaker's line, never ours")

    def test_markdown_is_still_stripped(self):
        self.assertEqual(self.filt("**Zaroor** karenge."), "Zaroor karenge.")

    def test_caps_ellipsis_and_ipa_pass_through(self):
        self.assertEqual(self.filt("Yeh SACH mein... important hai, /məˈniːʃ/."),
                         "Yeh SACH mein... important hai, /məˈniːʃ/.")


class TestDisplayText(unittest.TestCase):
    def test_display_text_hides_performance_markup(self):
        self.assertEqual(tts_script.display_text("Arre wah! <laugh> Bahut  badhiya."), "Arre wah! Bahut badhiya.")


class TestNormalizeSpokenText(unittest.TestCase):
    def test_ellipsis_is_preserved_but_double_dots_collapse(self):
        self.assertEqual(tts_script.normalize_spoken_text("Hmm... theek hai.."), "Hmm... theek hai.")
        self.assertEqual(tts_script.normalize_spoken_text("Ruko...."), "Ruko...")

    def test_bracketed_stage_directions_are_removed(self):
        self.assertEqual(tts_script.normalize_spoken_text("[warmly] Namaste!"), "Namaste!")


class TestTtsFooter(unittest.TestCase):
    """Every persona's prompt ends with a footer: 'your output is fed to TTS, write it like this'."""

    PERSONAS = ("storyteller", "car-negotiator", "debt-collector", "ai-companion",
                "lamborghini-concierge", "ananya-advisor", "kavya-glass-buddy")

    def test_footer_tells_the_llm_its_output_goes_to_tts(self):
        p = tts_script.speech_prompt_for("gemini-3.8-flash-lite-tts")
        self.assertIn("TEXT-TO-SPEECH", p)
        self.assertIn("[[", p, "must teach the per-part direction block")
        for tag in ("<breath>", "<cough>", "<sneeze>", "<throat-clearing>", "<gasp>", "<snort>"):
            self.assertIn(tag, p)
        for knob in ("pitch", "pace"):
            self.assertIn(knob, p)

    def test_every_persona_gets_its_own_voice_notes(self):
        generic = tts_script.speech_prompt_for("gemini-3.8-flash-lite-tts")
        notes = set()
        for pid in self.PERSONAS:
            p = tts_script.speech_prompt_for("gemini-3.8-flash-lite-tts", pid)
            self.assertTrue(p.startswith(generic), pid)
            extra = p[len(generic):]
            self.assertIn("[[", extra, f"{pid}: persona notes must show a direction example")
            notes.add(extra)
        self.assertEqual(len(notes), len(self.PERSONAS), "notes must be persona-specific")

    def test_kabir_and_abhay_contrast_high_and_low_pitch(self):
        for pid in ("storyteller", "car-negotiator"):
            p = tts_script.speech_prompt_for("gemini-3.8-flash-lite-tts", pid)
            self.assertIn("high pitch", p, pid)
            self.assertIn("low pitch", p, pid)

    def test_kabir_voice_notes_cap_scene_length(self):
        p = tts_script.speech_prompt_for("gemini-3.8-flash-lite-tts", "storyteller")
        self.assertIn("2-3 short", p)

    def test_persona_aliases_resolve(self):
        self.assertEqual(tts_script.speech_prompt_for("gemini-3.8-flash-tts", "mf-advisor"),
                         tts_script.speech_prompt_for("gemini-3.8-flash-tts", "ananya-advisor"))

    def test_unknown_persona_gets_generic_footer(self):
        self.assertEqual(tts_script.speech_prompt_for("gemini-3.8-flash-tts", "nobody"),
                         tts_script.speech_prompt_for("gemini-3.8-flash-tts"))

    def test_older_tts_never_learns_direction_blocks(self):
        p = tts_script.speech_prompt_for("gemini-3.1-flash-tts-preview", "storyteller")
        self.assertNotIn("[[", p)

    def test_footer_with_persona_notes_stays_small(self):
        for pid in self.PERSONAS:
            p = tts_script.speech_prompt_for("gemini-3.8-flash-lite-tts", pid)
            self.assertLess(len(p) / 3.8, 530, pid)


class TestStyledParts(unittest.TestCase):
    def test_splits_direction_blocks_into_parts(self):
        parts = tts_script.split_styled_parts(
            "[[mock outrage, high pitch, fast]] <snort> Kya?! [[conspiratorial, low pitch, measured]] Dekho... suno.")
        self.assertEqual(parts, [
            ("mock outrage, high pitch, fast", "<snort> Kya?!"),
            ("conspiratorial, low pitch, measured", "Dekho... suno."),
        ])

    def test_text_without_direction_has_no_style(self):
        self.assertEqual(tts_script.split_styled_parts("Achha, theek hai."), [(None, "Achha, theek hai.")])

    def test_direction_alone_is_kept_so_the_next_sentence_inherits_it(self):
        self.assertEqual(tts_script.split_styled_parts("[[calm, low pitch, slow]]"), [("calm, low pitch, slow", "")])

    def test_direction_split_by_sentence_aggregation_is_never_spoken(self):
        # A stray '.' inside [[...]] can make the sentence aggregator cut the block.
        self.assertEqual(tts_script.split_styled_parts("[[calm, slow pace."), [])
        self.assertEqual(tts_script.split_styled_parts("low pitch]] Suno."), [(None, "Suno.")])

    def test_filter_keeps_direction_blocks(self):
        out = run(tts_script.Gemini38TextFilter().filter("[[amused, high pitch, brisk]] **Arre** bhai! <laugh>"))
        self.assertEqual(out, "[[amused, high pitch, brisk]] Arre bhai! <laugh>")

    def test_display_text_hides_direction_blocks(self):
        self.assertEqual(tts_script.display_text("[[eerie whisper, low pitch, slow]] Suno... <breath> kaun hai?"),
                         "Suno... kaun hai?")


class TestSpokenParts(unittest.TestCase):
    """run_tts gets one sentence at a time; a direction lasts until the next one."""

    def test_sentence_without_direction_inherits_the_previous_one(self):
        parts, carried = tts_script.spoken_parts("BARAH lakh?!", "mock outrage, high pitch, fast")
        self.assertEqual(parts, [("mock outrage, high pitch, fast", "BARAH lakh?!")])
        self.assertEqual(carried, "mock outrage, high pitch, fast")

    def test_mid_sentence_shift_becomes_two_parts(self):
        parts, carried = tts_script.spoken_parts(
            "[[shocked, high pitch, fast]] <gasp> ACHANAK! [[whisper, low pitch, slow]] <breath> Suno..", None)
        self.assertEqual(parts, [("shocked, high pitch, fast", "<gasp> ACHANAK!"),
                                 ("whisper, low pitch, slow", "<breath> Suno.")])
        self.assertEqual(carried, "whisper, low pitch, slow")

    def test_direction_only_chunk_speaks_nothing_but_carries(self):
        parts, carried = tts_script.spoken_parts("[[calm, low pitch, slow]]", None)
        self.assertEqual(parts, [])
        self.assertEqual(carried, "calm, low pitch, slow")

    def test_leading_vocal_tag_before_direction_attaches_to_next_part(self):
        parts, carried = tts_script.spoken_parts(
            " <gasp> [[whisper, low pitch, slow]] Bataiye... <heavy breath> kya karoge?",
            "startled dread, high pitch, fast",
        )
        self.assertEqual(
            parts,
            [("whisper, low pitch, slow", "<gasp> Bataiye... <heavy breath> kya karoge?")],
        )
        self.assertEqual(carried, "whisper, low pitch, slow")

    def test_trailing_vocal_tag_attaches_to_previous_part(self):
        parts, _ = tts_script.spoken_parts(
            "[[startled dread, high pitch, fast]] Achanak aawaaz aayi! [[whisper, low pitch, slow]] <gasp>",
            None,
        )
        self.assertEqual(
            parts,
            [("startled dread, high pitch, fast", "Achanak aawaaz aayi! <gasp>")],
        )

    def test_tag_only_chunk_speaks_nothing_and_extracts_tags_for_next_sentence(self):
        parts, carried = tts_script.spoken_parts(" <long pause> <gasp>! ", "whisper, low pitch, slow")
        self.assertEqual(parts, [])
        self.assertEqual(carried, "whisper, low pitch, slow")
        self.assertEqual(tts_script.extract_vocal_tags(" <long pause> <gasp>! "), "<long pause> <gasp>")

    def test_punctuation_only_fragments_are_skipped(self):
        self.assertEqual(tts_script.spoken_parts(" . ", "x")[0], [])

    def test_stray_single_brackets_are_still_dropped(self):
        self.assertEqual(tts_script.spoken_parts("[warmly] Namaste!", None)[0], [(None, "Namaste!")])


class TestTranscriptStream(unittest.TestCase):
    """The cascade transcript is built from raw LLM tokens, and markup can be cut across any of them."""

    @staticmethod
    def pieces(*chunks):
        stream = tts_script.TranscriptStream()
        return [stream.feed(chunk) for chunk in chunks] + [stream.flush()]

    @staticmethod
    def studio_join(pieces):
        """How the studio appends cascade chunks (use-voice-session.ts): it adds a space
        between a chunk ending in a non-space and one starting with a letter or digit."""
        text = ""
        for piece in pieces:
            if piece:
                text += (" " if text and not text[-1].isspace() and piece[0].isalnum() else "") + piece
        return text

    def test_markup_is_removed_and_spacing_is_kept(self):
        cases = {
            "[[amused disbelief, high pitch, fast]] Arre bhai! <laugh> Kya baat hai.": "Arre bhai! Kya baat hai.",
            "Arre wah! <laugh> Bahut  badhiya.": "Arre wah! Bahut badhiya.",
            "Main |haan| sun raha hoon.": "Main sun raha hoon.",
            "[warmly] Namaste!": "Namaste!",
            "Suno <laugh>!": "Suno!",
            "मैं ठीक हूँ <sigh> ।": "मैं ठीक हूँ।",
            "Hmm...\n\n[[calm, low pitch, slow]] Suno.": "Hmm...\nSuno.",
            "2 < 3 and 5 > 4": "2 < 3 and 5 > 4",
        }
        for raw, shown in cases.items():
            self.assertEqual(tts_script.transcript_text(raw), shown, raw)

    def test_unfinished_markup_at_the_end_of_a_reply_is_hidden(self):
        self.assertEqual(tts_script.transcript_text("Theek hai [[calm, slow"), "Theek hai")
        self.assertEqual(tts_script.transcript_text("Theek hai <laug"), "Theek hai")
        self.assertEqual(tts_script.transcript_text("Main |haan"), "Main haan", "an unclosed pipe is residue, not a line")

    def test_a_lone_bracket_does_not_swallow_the_reply(self):
        tail = "bahut lambi baat " * 20  # well past the 200-char limit of a direction block
        self.assertEqual(tts_script.transcript_text("Suno [" + tail), ("Suno " + tail).strip())

    def test_a_direction_block_split_across_tokens_never_reaches_the_screen(self):
        pieces = self.pieces("[[amused disb", "elief, high pitch", ", fast]] Arre bhai! <la", "ugh> Kya haal hai?")
        self.assertEqual(pieces[:2], ["", ""], "nothing is shown while the block is still open")
        self.assertEqual("".join(pieces), "Arre bhai! Kya haal hai?")

    def test_finished_words_are_released_before_the_reply_ends(self):
        stream = tts_script.TranscriptStream()
        self.assertEqual(stream.feed("[[warm, low pitch, slow]] Arre bhai! Kya "), "Arre bhai! Kya")
        self.assertEqual(stream.feed("haal [[brighter, high pitch"), " haal")
        self.assertEqual(stream.feed(", fast]] hai?"), "")
        self.assertEqual(stream.flush(), " hai?")

    def test_a_word_is_never_sent_in_two_pieces(self):
        # The studio would render "Nam" + "askaar" as "Nam askaar".
        pieces = self.pieces("Nam", "askaar dost, kaise", " ho?")
        self.assertEqual(self.studio_join(pieces), "Namaskaar dost, kaise ho?")

    def test_flush_starts_the_next_reply_clean(self):
        stream = tts_script.TranscriptStream()
        self.assertEqual(stream.feed("Pehla jawab [[calm"), "Pehla jawab")
        self.assertEqual(stream.flush(), "", "the unclosed block is dropped")
        self.assertEqual(stream.feed("Doosra "), "Doosra", "no space is owed across replies")

    def test_any_chunking_shows_the_same_transcript(self):
        rng = random.Random(38)
        atoms = ["Arre", "bhai", "hi", "gh", "2", "मैं", " ", "  ", "\n", ",", "!", "...", "।", "-",
                 "[[", "]]", "[", "]", "<", ">", "|", "<laugh>", "<short pause>", "|haan|",
                 "[[calm, low pitch, slow]]", "[warmly]", "pitch"]
        for _ in range(3000):
            raw = "".join(rng.choice(atoms) for _ in range(rng.randint(0, 24)))
            whole = tts_script.transcript_text(raw)
            cuts = sorted(rng.sample(range(len(raw) + 1), k=min(len(raw) + 1, rng.randint(0, 8))))
            chunks = [raw[a:b] for a, b in zip([0, *cuts], [*cuts, len(raw)])]
            pieces = self.pieces(*chunks)
            self.assertEqual("".join(pieces), whole, repr(chunks))
            self.assertEqual(self.studio_join(pieces), whole, repr(chunks))
            self.assertFalse(set("[]|") & set(whole), repr(raw))
            self.assertEqual(whole, whole.strip(), repr(raw))


if __name__ == "__main__":
    unittest.main()


class TestVoiceGenderRule(unittest.TestCase):
    def test_male_clones_get_masculine_self_reference(self):
        for voice in ("Gemini-Clone-Male", "Custom-Male"):
            rule = tts_script.voice_gender_rule(voice)
            self.assertIn("masculine", rule, voice)
            self.assertIn("सकता हूँ", rule, voice)

    def test_female_clone_gets_feminine_self_reference(self):
        self.assertIn("सकती हूँ", tts_script.voice_gender_rule("Custom-Female"))

    def test_named_voices_are_left_to_the_persona(self):
        for voice in ("Puck", "Gacrux", "Custom-Key", ""):
            self.assertEqual(tts_script.voice_gender_rule(voice), "", voice)
