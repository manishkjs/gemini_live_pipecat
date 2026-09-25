"""Gemini 3.8 TTS speech-script contract (per the 3.8 Flash TTS developer guide).

In 3.8, `text` is a verbatim transcript: everything is spoken except inline
<vocal tags> and |pipe| backchannels. The cascade LLM must therefore write a
performable script, and the text pipeline must deliver the tags intact.
"""
import asyncio
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
