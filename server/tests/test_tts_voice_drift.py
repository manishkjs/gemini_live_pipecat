"""Gemini 3.8 TTS voice drift guards.

The 3.8 guide ("Consistency across generations") says long character notes and
accent, age or gender text in `speech_metadata.style` are the most common cause
of voice drift; those traits belong to the voice. Each Pipecat run_tts call is a
separate generation, so one-word fragments must not be sent on their own.
"""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import types

import tts_script
import voice_profiles


def run(coro):
    return asyncio.run(coro)


def make_service(**kw):
    from agent import CustomVertexGeminiTTSService
    from pipecat.services.google.tts import GeminiTTSService

    with patch.object(GeminiTTSService, "_create_client", return_value=None), \
         patch("agent.genai.Client", return_value=None), \
         patch("agent._resolve_gemini_api_key", return_value="fake-key"):
        return CustomVertexGeminiTTSService(project_id="p", location="us-central1", **kw)


PERSONA_PROMPT = "Empathetic yet firm collections specialist. Calm, reassuring Indian English cadence."


class TestStyleCarriesOnlySituationalDelivery(unittest.TestCase):
    def setUp(self):
        self.svc = make_service(
            voice_id="Gacrux", model="gemini-3.8-flash-lite-tts", voice_prompt=PERSONA_PROMPT,
            language_code="hi-IN", tts_style="Empathetic", tts_accent="Indian", tts_pitch="Default",
            tts_pace_label="Natural",
        )

    def test_direction_is_sent_without_accent_or_character_notes(self):
        style = self.svc._build_speech_metadata_style("hi-IN", "calm empathetic, warm low pitch, measured")
        self.assertEqual(style, "calm empathetic, warm low pitch, measured")
        self.assertNotIn("Accent", style)
        self.assertNotIn("collections specialist", style)

    def test_static_style_has_no_accent_persona_or_default_pitch(self):
        style = self.svc._build_speech_metadata_style("hi-IN", None)
        self.assertEqual(style, "Empathetic, natural pace")

    def test_explicit_session_pitch_is_kept(self):
        svc = make_service(voice_id="Gacrux", model="gemini-3.8-flash-tts", tts_style="Warm", tts_pitch="Low")
        self.assertEqual(svc._build_speech_metadata_style("en-IN", None), "Warm, natural pace, low pitch")

    def test_raw_style_override_is_respected(self):
        svc = make_service(voice_id="Gacrux", model="gemini-3.8-flash-tts", voice_prompt="Style: whispered urgently.")
        self.assertEqual(svc._build_speech_metadata_style("en-IN", None), "Style: whispered urgently.")

    def test_identity_words_from_the_llm_are_dropped(self):
        style = self.svc._build_speech_metadata_style("hi-IN", "amused, Indian accent, high pitch, fast")
        self.assertEqual(style, "amused, high pitch, fast")

    def test_direction_that_is_only_identity_falls_back_to_session_style(self):
        style = self.svc._build_speech_metadata_style("hi-IN", "Indian accent, 30 year old woman")
        self.assertEqual(style, "Empathetic, natural pace")


class TestSituationalStyle(unittest.TestCase):
    def test_keeps_emotion_pitch_and_pace(self):
        self.assertEqual(tts_script.situational_style("mock outrage, high pitch, fast"), "mock outrage, high pitch, fast")

    def test_drops_accent_age_and_gender(self):
        self.assertEqual(tts_script.situational_style("warm, British accent, slow"), "warm, slow")
        self.assertEqual(tts_script.situational_style("warm, Indian English cadence, slow"), "warm, slow")
        self.assertEqual(tts_script.situational_style("calm, Hinglish lilt, low pitch"), "calm, low pitch")
        self.assertEqual(tts_script.situational_style("bright, 25-year-old, brisk"), "bright, brisk")
        self.assertEqual(tts_script.situational_style("soft, female voice, slow"), "soft, slow")
        self.assertEqual(tts_script.situational_style("gentle, mature voice, slow"), "gentle, slow")
        self.assertIsNone(tts_script.situational_style("Indian accent"))
        self.assertIsNone(tts_script.situational_style(None))

    def test_identity_filter_lives_in_code_not_in_the_prompt(self):
        footer = tts_script.speech_prompt_for("gemini-3.8-flash-lite-tts")
        self.assertNotIn("accent", footer.lower(), "the filter is code-side so the per-turn prompt does not grow")


class TestMinWordsSentenceAggregator(unittest.TestCase):
    async def _collect(self, agg, text):
        return [a.text async for a in agg.aggregate(text)]

    def test_one_word_greeting_rides_with_the_next_sentence(self):
        agg = tts_script.MinWordsSentenceAggregator(min_words=4)
        out = run(self._collect(agg, "नमस्ते. Aapka Sahaj Finance ka loan overdue hai. Aap "))
        self.assertEqual(out, ["नमस्ते. Aapka Sahaj Finance ka loan overdue hai."])

    def test_markup_does_not_count_as_words(self):
        agg = tts_script.MinWordsSentenceAggregator(min_words=4)
        out = run(self._collect(agg, "[[calm, low pitch, slow]] <breath> Haan. Main sun raha hoon ji. Aur "))
        self.assertEqual(out, ["[[calm, low pitch, slow]] <breath> Haan. Main sun raha hoon ji."])
        self.assertEqual(tts_script.spoken_word_count("[[calm, low pitch]] <breath> Haan."), 1)
        self.assertEqual(tts_script.spoken_word_count("[speaking softly and slowly] Haan."), 1)
        self.assertEqual(tts_script.spoken_word_count("[[firm, steady, low pitch."), 0)
        self.assertEqual(tts_script.spoken_word_count("calm empathetic, warm low pitch]] Haan."), 1)

    def test_ellipsis_and_interrobang_are_not_split_mid_cluster(self):
        agg = tts_script.MinWordsSentenceAggregator(min_words=4)
        out = run(self._collect(agg, "[[calm, low pitch, slow]] Hmm... theek hai. Main abhi dekhta hoon. Aur "))
        self.assertEqual(out, ["[[calm, low pitch, slow]] Hmm... theek hai. Main abhi dekhta hoon."])

        agg2 = tts_script.MinWordsSentenceAggregator(min_words=4)
        out2 = run(self._collect(agg2, "[[calm, low pitch, slow]] Aapka loan overdue hai?! Haan ji. "))
        tail2 = run(agg2.flush())
        self.assertEqual(out2, ["[[calm, low pitch, slow]] Aapka loan overdue hai?!"])
        self.assertEqual(tail2.text, "Haan ji.")

    def test_period_inside_direction_block_does_not_emit_half_open_fragment(self):
        agg = tts_script.MinWordsSentenceAggregator(min_words=4)
        out = run(self._collect(agg, "[[calm empathetic, warm low pitch. measured]] Haan ji, main abhi dekhta hoon. Aur "))
        self.assertEqual(out, ["[[calm empathetic, warm low pitch. measured]] Haan ji, main abhi dekhta hoon."])

    def test_short_tail_is_flushed_at_end_of_reply(self):
        agg = tts_script.MinWordsSentenceAggregator(min_words=4)
        out = run(self._collect(agg, "Aap aaj kitna pay kar sakte hain? Theek hai."))
        self.assertEqual(out, ["Aap aaj kitna pay kar sakte hain?"])
        tail = run(agg.flush())
        self.assertEqual(tail.text, "Theek hai.")
        self.assertIsNone(run(agg.flush()))

    def test_held_fragment_is_flushed_even_without_more_text(self):
        agg = tts_script.MinWordsSentenceAggregator(min_words=4)
        out = run(self._collect(agg, "Haan. Ji"))
        self.assertEqual(out, [])
        self.assertEqual(run(agg.flush()).text, "Haan. Ji")

    def test_interruption_drops_held_text(self):
        agg = tts_script.MinWordsSentenceAggregator(min_words=4)
        run(self._collect(agg, "Haan. Ji"))
        run(agg.handle_interruption())
        self.assertIsNone(run(agg.flush()))

    def test_after_the_lead_sentence_the_rest_of_the_reply_is_one_generation(self):
        agg = tts_script.MinWordsSentenceAggregator(min_words=4)
        text = ("Namaste ji, Sahaj Finance se baat kar raha hoon. Aapka loan payment past due hai. "
                "Main samajh sakta hoon ki thodi problem chal rahi hai. Aap aaj kitna payment kar sakte hain? ")
        out = run(self._collect(agg, text))
        self.assertEqual(out, ["Namaste ji, Sahaj Finance se baat kar raha hoon."], "only the lead sentence goes out early")
        tail = run(agg.flush())
        self.assertEqual(tail.text, "Aapka loan payment past due hai. Main samajh sakta hoon ki thodi problem chal rahi hai. "
                                    "Aap aaj kitna payment kar sakte hain?")
        # The next reply starts fresh: its first sentence is released again.
        out2 = run(self._collect(agg, "Theek hai ji, main note kar leta hoon. Aur kuch? "))
        self.assertEqual(out2, ["Theek hai ji, main note kar leta hoon."])

    def test_long_held_tail_is_released_before_the_reply_ends(self):
        agg = tts_script.MinWordsSentenceAggregator(min_words=4, max_hold_words=12)
        text = "Lead sentence goes out first. Second one is held. Third one is also held here. Fourth makes it long enough now. Aur "
        out = run(self._collect(agg, text))
        self.assertEqual(out[0], "Lead sentence goes out first.")
        self.assertEqual(len(out), 2, out)
        self.assertTrue(out[1].startswith("Second one is held."), out[1])

    def test_only_38_tts_gets_the_merging_aggregator(self):
        svc38 = make_service(voice_id="Puck", model="gemini-3.8-flash-tts")
        self.assertIsInstance(svc38._text_aggregator, tts_script.MinWordsSentenceAggregator)
        svc25 = make_service(voice_id="Puck", model="gemini-2.5-flash-preview-tts")
        self.assertNotIsInstance(svc25._text_aggregator, tts_script.MinWordsSentenceAggregator)


class TestNoPerPartStyleOn38(unittest.TestCase):
    """The 3.8 request carries a plain transcript unless GEMINI_38_TTS_STYLE=1."""

    def _captured_contents(self, svc, text):
        captured = {}

        class _Stream:
            def __init__(self):
                self._done = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        async def fake_stream(model, contents, config):
            captured["contents"] = contents
            captured["config"] = config
            return _Stream()

        svc._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=fake_stream)))
        svc._cascade_meter = None

        async def drain():
            return [f async for f in svc.run_tts(text, "ctx")]

        run(drain())
        return captured

    def test_38_sends_plain_transcript_without_speech_metadata(self):
        svc = make_service(voice_id="en-in-csagent-4", model="gemini-3.8-flash-lite-tts", language_code="hi-IN")
        cap = self._captured_contents(svc, "[[calm, low pitch, measured]] Namaste ji, <short pause> Sahaj Finance se bol raha hoon.")
        parts = cap["contents"][0].parts
        self.assertEqual(len(parts), 1)
        self.assertIsNone(getattr(parts[0], "speech_metadata", None))
        self.assertIn("Namaste ji, <short pause> Sahaj Finance se bol raha hoon.", parts[0].text)
        self.assertNotIn("[[", parts[0].text)
        self.assertEqual(cap["config"].speech_config.voice_config.voice, "en-in-csagent-4")

    def test_style_can_be_switched_back_on(self):
        svc = make_service(voice_id="en-in-csagent-4", model="gemini-3.8-flash-lite-tts", language_code="hi-IN")
        svc._use_speech_style = True
        cap = self._captured_contents(svc, "[[calm, low pitch, measured]] Namaste ji, Sahaj Finance se bol raha hoon.")
        self.assertEqual(cap["contents"][0].parts[0].speech_metadata.style, "calm, low pitch, measured")

    def test_style_default_comes_from_env(self):
        with patch.dict(os.environ, {"GEMINI_38_TTS_STYLE": "1"}):
            self.assertTrue(make_service(voice_id="Puck", model="gemini-3.8-flash-tts")._use_speech_style)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_38_TTS_STYLE", None)
            self.assertFalse(make_service(voice_id="Puck", model="gemini-3.8-flash-tts")._use_speech_style)


class TestLibraryVoices(unittest.TestCase):
    def test_library_ids_are_recognized(self):
        for voice in ("en-in-csagent-3", "en-in-concierge-12", "hi-in-narrator-2"):
            self.assertTrue(voice_profiles.is_library_voice_id(voice), voice)
        for voice in ("Gacrux", "en-US-Chirp3-HD-Gacrux", "hi-IN-Chirp3-HD-Sulafat", "voicekey_abc", "Custom-Male", "", None):
            self.assertFalse(voice_profiles.is_library_voice_id(voice), voice)

    def test_library_voice_reaches_voice_config_intact(self):
        svc = make_service(voice_id="en-in-csagent-3", model="gemini-3.8-flash-lite-tts")
        self.assertEqual(svc._settings.voice, "en-in-csagent-3")
        cfg = svc._voice_config()
        self.assertIsInstance(cfg, types.VoiceConfig)
        self.assertEqual(cfg.voice, "en-in-csagent-3")
        self.assertIsNone(cfg.prebuilt_voice_config)

    def test_studio_voice_with_indian_accent_maps_to_indian_library_voice_on_38_tts(self):
        svc_female = make_service(voice_id="Gacrux", model="gemini-3.8-flash-lite-tts", tts_accent="Indian")
        self.assertEqual(svc_female._settings.voice, "en-in-csagent-3")
        self.assertEqual(svc_female._voice_config().voice, "en-in-csagent-3")

        svc_male = make_service(voice_id="Fenrir", model="gemini-3.8-flash-tts", tts_accent="Indian")
        self.assertEqual(svc_male._settings.voice, "en-in-commercial-7")
        self.assertEqual(svc_male._voice_config().voice, "en-in-commercial-7")

        svc_us = make_service(voice_id="Gacrux", model="gemini-3.8-flash-lite-tts", tts_accent="American (US)")
        self.assertEqual(svc_us._settings.voice, "Gacrux")
        self.assertEqual(svc_us._voice_config().prebuilt_voice_config.voice_name, "Gacrux")

    def test_library_voice_gender_and_grammar_rule(self):
        self.assertEqual(voice_profiles.voice_gender("en-in-csagent-3"), "female")
        self.assertEqual(voice_profiles.voice_gender("en-in-csagent-4"), "male")
        self.assertIn("female voice", tts_script.voice_gender_rule("en-in-csagent-3"))
        self.assertIn("male voice", tts_script.voice_gender_rule("en-in-csagent-4"))


if __name__ == "__main__":
    unittest.main()
