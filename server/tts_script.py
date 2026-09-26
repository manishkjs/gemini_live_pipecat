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
# [[emotion, pitch, pace]]: per-part delivery direction -> speech_metadata.style.
_DIRECTION = re.compile(r"\[\[\s*([^\[\]]{1,200}?)\s*\]\]")
# Halves of a block the sentence aggregator cut apart ("[[calm, slow." | "pace]] Suno.").
_OPEN_FRAGMENT = re.compile(r"\[\[[^\]]*$")
_CLOSE_FRAGMENT = re.compile(r"^[^\[]*\]\]")
# Private-use sentinels survive markdown filtering untouched.
_SENTINEL = "\ue000{}\ue001"
_SENTINEL_RE = re.compile("\ue000(\\d+)\ue001")


def is_gemini_38_tts(model: str | None) -> bool:
    return (model or "").replace("-aistudio", "") in GEMINI_38_TTS_MODELS


# The footer every persona prompt ends with when a Gemini 3.8 voice speaks the reply.
GEMINI_38_SPEECH_PROMPT = """OUTPUT GOES TO TEXT-TO-SPEECH: a Gemini 3.8 voice speaks every character verbatim except [[direction]] blocks and <vocal tags>. Write a script for a real human voice, not text.
1. DIRECTION: open every reply with [[emotion, pitch, pace]], e.g. [[amused disbelief, high pitch, fast]]. When the feeling turns mid-reply, start a new block (1-3 per reply). Always name all three: emotion or texture; pitch (high, low, hushed low, rising, bright); pace (fast, brisk, relaxed, slow drawn-out). Contrast them: high pitch for surprise, excitement, teasing; low pitch for secrets, warnings, gravity. Only words and commas inside [[...]].
2. HUMAN SOUNDS: 1-3 tags per reply, exactly where the sound happens, in English even inside Hindi: <breath> <heavy breath> <exhales> <sigh> <pant> <short pause> <long pause> <laugh> <chuckle> <giggle> <snicker> <snort> <gasp> <tsk> <groan> <throat-clearing> <cough> <sneeze> <yawn>. Breaths and pauses in most replies; <throat-clearing> or <cough> now and then; <sneeze> or <yawn> at most once a call, unless your voice notes say otherwise.
3. SPEAK, DON'T WRITE: 1-2 short sentences, contractions, real thinking fillers ("hmm...", "arre", "achha", "uff", "matlab", "well"). Commas for breaths, "..." to hesitate or trail off, "?!" for a spike, CAPS on at most 1-2 stressed words.
4. Never write (laughs) or *sighs*, |pipes|, markdown, emojis, lists, URLs or symbols. Say numbers, money and dates as words. For a tricky name you may add IPA in slashes, e.g. /niːv/."""

LEGACY_GEMINI_SPEECH_PROMPT = """VOICE OUTPUT (Gemini TTS): every character you write is spoken aloud.
- Speak like a real person on a call: 1-2 short sentences per turn.
- Never write stage directions or bracketed tags such as [warmly] or (laughs); the engine reads them out loud.
- Use commas for natural pauses. Never use markdown, emojis, bullet points, or symbols that cannot be spoken."""


def speech_prompt_for(tts_model: str | None, persona_id: str | None = None) -> str:
    """The TTS footer for the LLM: what the voice can perform, then how this persona sounds."""
    model = (tts_model or "").replace("-aistudio", "")
    if model in GEMINI_38_TTS_MODELS:
        from persona_prompt_cards.voice_notes import voice_notes_for  # local: avoids a cycle at import

        notes = voice_notes_for(persona_id)
        return f"{GEMINI_38_SPEECH_PROMPT}\n{notes}" if notes else GEMINI_38_SPEECH_PROMPT
    if model.startswith("gemini"):
        return LEGACY_GEMINI_SPEECH_PROMPT
    return ""


def split_styled_parts(text: str) -> list[tuple[str | None, str]]:
    """Split a script into (direction, text) parts at each [[direction]] block.

    Text before the first block carries no direction (the caller keeps the
    previous sentence's). A block with no text after it is kept so the next
    sentence inherits it; half-blocks cut by sentence aggregation are dropped.
    """
    t = _CLOSE_FRAGMENT.sub("", _OPEN_FRAGMENT.sub("", text or ""))
    parts: list[tuple[str | None, str]] = []
    style: str | None = None
    cursor = 0
    for m in _DIRECTION.finditer(t):
        lead = t[cursor:m.start()].strip()
        if lead or style:
            parts.append((style, lead))
        style = _SPACES.sub(" ", m.group(1).strip().rstrip(".,;"))
        cursor = m.end()
    tail = t[cursor:].strip()
    if tail or style:
        parts.append((style, tail))
    return parts


def normalize_spoken_text(text: str) -> str:
    """Drop bracketed stage directions; keep a deliberate '...' but collapse stray '..' and '....'."""
    t = _BRACKETED.sub("", text or "")
    t = re.sub(r"\.{4,}", "...", t)
    t = re.sub(r"(?<!\.)\.\.(?!\.)", ".", t)
    return _SPACES.sub(" ", t).strip()


def extract_vocal_tags(text: str) -> str:
    """Return all valid <vocal tags> in `text`, normalized and space-joined."""
    tags: list[str] = []
    for m in _ANGLE_TAG.finditer(text or ""):
        raw = re.sub(r"\s+", " ", m.group(1).strip().lower())
        tag = _TAG_ALIASES.get(raw, raw)
        if tag in VOCAL_TAGS:
            tags.append(f"<{tag}>")
    return " ".join(tags)


def spoken_parts(text: str, carried: str | None) -> tuple[list[tuple[str | None, str]], str | None]:
    """One sentence chunk -> TTS parts [(direction, clean text)] and the direction to carry forward.

    Pipecat hands run_tts one sentence at a time, so a [[direction]] set in one
    sentence keeps applying to the following ones until the LLM sets a new one.
    Tag-only fragments (e.g. a standalone `<gasp>` or `<long pause>` split at
    punctuation) are attached to an adjacent spoken part instead of triggering
    a separate TTS part.
    """
    parts: list[tuple[str | None, str]] = []
    leading_tags: list[str] = []
    for style, segment in split_styled_parts(text):
        if style:
            carried = style
        clean = normalize_spoken_text(segment)
        has_words = any(ch.isalnum() for ch in display_text(clean))
        if has_words:
            if leading_tags:
                clean = f"{' '.join(leading_tags)} {clean}"
                leading_tags.clear()
            parts.append((carried, clean))
        else:
            tags = extract_vocal_tags(clean)
            if tags:
                if parts:
                    prev_style, prev_text = parts[-1]
                    parts[-1] = (prev_style, f"{prev_text} {tags}")
                else:
                    leading_tags.append(tags)
    return parts, carried



class Gemini38TextFilter(MarkdownTextFilter):
    """MarkdownTextFilter that preserves Gemini 3.8 vocal tags and [[direction]] blocks, and drops |backchannels|."""

    async def filter(self, text: str) -> str:
        kept: list[str] = []

        def keep(markup: str) -> str:
            kept.append(markup)
            return _SENTINEL.format(len(kept) - 1)

        def protect_tag(m: re.Match) -> str:
            raw = re.sub(r"\s+", " ", m.group(1).strip().lower())
            tag = _TAG_ALIASES.get(raw, raw)
            return keep(f"<{tag}>") if tag in VOCAL_TAGS else " "

        staged = _PIPE_BACKCHANNEL.sub(" ", text or "")
        staged = _DIRECTION.sub(lambda m: keep(f"[[{m.group(1).strip()}]]"), staged)
        staged = _ANGLE_TAG.sub(protect_tag, staged)
        filtered = await super().filter(staged)
        restored = _SENTINEL_RE.sub(lambda m: kept[int(m.group(1))], filtered)
        return _SPACES.sub(" ", restored).strip()


def display_text(text: str) -> str:
    """Transcript text for humans: performance markup removed."""
    t = _DIRECTION.sub(" ", text or "")
    t = _PIPE_BACKCHANNEL.sub(" ", t)
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
