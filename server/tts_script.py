"""Speech-script contract between the cascade LLM and Gemini TTS.

Gemini 3.8 TTS (gemini-3.8-flash-tts / gemini-3.8-flash-lite-tts) treats the
`text` field as a verbatim transcript. Everything in it is spoken aloud except:

  * inline vocal tags in <angle brackets>  (<laugh>, <sigh>, <short pause>, ...)
  * |pipe| backchannels, which a *second* speaker voices over the first

Delivery direction (emotion, pace, accent) belongs in the per-part
`speech_metadata.style` field, never in the transcript.

This module owns the three places that contract touches the cascade:

  1. `speech_prompt_for(model)`  - what the LLM is told to write.
  2. `Gemini38TextFilter`        - keeps supported tags intact through the
                                   markdown filter (which otherwise strips any
                                   <...> as HTML) and drops pipe backchannels,
                                   which make no sense for a single speaker.
  3. `display_text(text)`        - the transcript the user reads, without markup.

Source: Gemini 3.8 Flash TTS developer guide (AI Studio, 2026-09-23).
"""
from __future__ import annotations

import re

from pipecat.utils.text.markdown_text_filter import MarkdownTextFilter

GEMINI_38_TTS_MODELS = frozenset({"gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"})

# Inline non-verbal tags documented for Gemini 3.8 TTS. Always English, even
# when the surrounding transcript is Hindi.
VOCAL_TAGS = frozenset({
    "breath", "heavy breath", "exhales", "pant", "sigh",
    "laugh", "chuckle", "giggle", "snicker", "cackle",
    "gasp", "cough", "sneeze", "throat-clearing", "snort",
    "sob", "cry", "whimper", "groan", "yawn",
    "short pause", "long pause", "tsk", "argh",
})

# Common LLM inflections mapped to the exact tag Gemini 3.8 TTS recognizes.
_TAG_ALIASES = {
    "laughs": "laugh",
    "laughing": "laugh",
    "chuckles": "chuckle",
    "chuckling": "chuckle",
    "giggles": "giggle",
    "snickers": "snicker",
    "cackles": "cackle",
    "sighs": "sigh",
    "sighing": "sigh",
    "gasps": "gasp",
    "coughs": "cough",
    "throat clearing": "throat-clearing",
    "clears throat": "throat-clearing",
    "snorts": "snort",
    "sobs": "sob",
    "cries": "cry",
    "whimpers": "whimper",
    "groans": "groan",
    "yawns": "yawn",
    "pants": "pant",
    "exhale": "exhales",
    "breathes": "breath",
    "pause": "short pause",
}

_ANGLE_TAG = re.compile(r"<\s*([a-zA-Z][a-zA-Z \-]{0,30}?)\s*>")
_PIPE_BACKCHANNEL = re.compile(r"\|[^|\n]{1,40}\|")
_BRACKETED = re.compile(r"\[[^\]]*\]")
_SPACES = re.compile(r"[ \t]{2,}")
# Private-use sentinels survive markdown filtering untouched.
_SENTINEL = "\ue000{}\ue001"
_SENTINEL_RE = re.compile("\ue000(\\d+)\ue001")


def is_gemini_38_tts(model: str | None) -> bool:
    return (model or "").replace("-aistudio", "") in GEMINI_38_TTS_MODELS


GEMINI_38_SPEECH_PROMPT = """VOICE OUTPUT (Gemini 3.8 TTS): every character you write is spoken verbatim. Write a spoken script, not text.
- Speak like a real person on a call: 1-2 short sentences per turn, contractions, natural fillers ("hmm", "achha", "well") only where a human would use them.
- Delivery (tone, pace, accent) is already configured. Never write stage directions or narration such as [warmly], (laughs), "she said softly", or "Say cheerfully:".
- Prosody comes from punctuation: commas for breaths, "..." for a hesitant pause, "!" for energy, "?" for a rising question. Put a word in CAPS only to stress it.
- When real emotion calls for it, you may add at most ONE inline vocal tag per turn, placed exactly where the sound happens: <laugh>, <chuckle>, <sigh>, <breath>, <gasp>, <short pause>, <long pause>, <throat-clearing>. Tags are always in English, even inside Hindi. Use none in most turns.
- Never use |pipes|, markdown, emojis, bullet points, URLs, or symbols that cannot be spoken. Write numbers, currency, and dates the way you would say them.
- For a tricky name or acronym you may follow it with its IPA in slashes, e.g. /niːv/."""

LEGACY_GEMINI_SPEECH_PROMPT = """VOICE OUTPUT (Gemini TTS): every character you write is spoken aloud.
- Speak like a real person on a call: 1-2 short sentences per turn.
- Never write stage directions or bracketed tags such as [warmly] or (laughs); the engine reads them out loud.
- Use commas for natural pauses. Never use markdown, emojis, bullet points, or symbols that cannot be spoken."""


def speech_prompt_for(tts_model: str | None) -> str:
    """The script-writing rules for the LLM, matched to what the TTS can perform."""
    model = (tts_model or "").replace("-aistudio", "")
    if model in GEMINI_38_TTS_MODELS:
        return GEMINI_38_SPEECH_PROMPT
    if model.startswith("gemini"):
        return LEGACY_GEMINI_SPEECH_PROMPT
    return ""


def normalize_spoken_text(text: str) -> str:
    """Drop bracketed stage directions; keep a deliberate '...' but collapse stray '..' and '....'."""
    t = _BRACKETED.sub("", text or "")
    t = re.sub(r"\.{4,}", "...", t)
    t = re.sub(r"(?<!\.)\.\.(?!\.)", ".", t)
    return _SPACES.sub(" ", t).strip()


class Gemini38TextFilter(MarkdownTextFilter):
    """MarkdownTextFilter that preserves Gemini 3.8 vocal tags and drops |backchannels|."""

    async def filter(self, text: str) -> str:
        kept: list[str] = []

        def protect(m: re.Match) -> str:
            raw = re.sub(r"\s+", " ", m.group(1).strip().lower())
            tag = _TAG_ALIASES.get(raw, raw)
            if tag not in VOCAL_TAGS:
                return " "
            kept.append(f"<{tag}>")
            return _SENTINEL.format(len(kept) - 1)

        staged = _PIPE_BACKCHANNEL.sub(" ", text or "")
        staged = _ANGLE_TAG.sub(protect, staged)
        filtered = await super().filter(staged)
        restored = _SENTINEL_RE.sub(lambda m: kept[int(m.group(1))], filtered)
        return _SPACES.sub(" ", restored).strip()


def display_text(text: str) -> str:
    """Transcript text for humans: performance markup removed."""
    t = _PIPE_BACKCHANNEL.sub(" ", text or "")
    t = _ANGLE_TAG.sub(" ", t)
    return _SPACES.sub(" ", t).strip()


_MASCULINE_RULE = ("VOICE GENDER: you are speaking in a male voice. Refer to yourself with masculine Hindi "
                   "forms (\"मैं मदद कर सकता हूँ\", \"मैं देख रहा हूँ\"), never feminine ones, even if your persona "
                   "name sounds female. Address the user gender-neutrally.")
_FEMININE_RULE = ("VOICE GENDER: you are speaking in a female voice. Refer to yourself with feminine Hindi "
                  "forms (\"मैं मदद कर सकती हूँ\", \"मैं देख रही हूँ\"). Address the user gender-neutrally.")


def voice_gender_rule(tts_voice: str | None) -> str:
    """Self-reference grammar for cloned voices, whose gender is fixed by the recording.

    A cloned male voice saying "कर सकती हूँ" is jarring. Named voices are left to
    the persona prompt, which already sets gender for its preset voice.
    """
    import voice_profiles  # local import: keeps tts_script free of credential code at import time

    if voice_profiles.is_gemini_clone_voice(tts_voice):
        gender = voice_profiles.GEMINI_CLONE_VOICES[str(tts_voice).strip()]
    elif voice_profiles.is_female_clone_voice(tts_voice):
        gender = "female"
    elif voice_profiles.is_male_clone_voice(tts_voice):
        gender = "male"
    else:
        return ""
    return _MASCULINE_RULE if gender == "male" else _FEMININE_RULE
