"""Speech-script contract between the cascade LLM and Gemini TTS.

Gemini 3.8 TTS (gemini-3.8-flash-tts / gemini-3.8-flash-lite-tts) treats the
`text` field as a verbatim transcript. By default, Cascade sends clean,
punctuation-paced single-call transcripts without `<vocal tags>` or
`[[direction]]` markup so the voice retains stable speaker identity across
turns (and never reads English vocal tags aloud in Hinglish).

Setting `GEMINI_38_VOCAL_TAGS=1` or `GEMINI_38_TTS_STYLE=1` opts back into the
expressive script mode (`GEMINI_38_EXPRESSIVE_SPEECH_PROMPT`).
"""
from __future__ import annotations

import os
import re
import unicodedata

from pipecat.utils.string import SENTENCE_ENDING_PUNCTUATION
from pipecat.utils.text.base_text_aggregator import Aggregation, AggregationType
from pipecat.utils.text.markdown_text_filter import MarkdownTextFilter
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator

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


def use_vocal_tags() -> bool:
    """True when opt-in inline <vocal tags> are enabled via GEMINI_38_VOCAL_TAGS=1."""
    return os.getenv("GEMINI_38_VOCAL_TAGS", "").strip().lower() in ("1", "true", "yes")


def use_speech_style() -> bool:
    """True when opt-in dynamic per-part speech_metadata.style is enabled via GEMINI_38_TTS_STYLE=1."""
    return os.getenv("GEMINI_38_TTS_STYLE", "").strip().lower() in ("1", "true", "yes")


# Default speaker-stable footer: punctuation-driven cadence with zero <vocal tags> or [[direction]] blocks.
GEMINI_38_SPEECH_PROMPT = """OUTPUT GOES TO TEXT-TO-SPEECH: a Gemini 3.8 voice speaks every character verbatim. Write natural spoken dialogue for a single human speaker, not written prose.
1. NATURAL CADENCE: 1-2 short sentences per turn, contractions, and conversational fillers ("hmm...", "arre", "achha", "matlab", "well"). Use commas for natural breath pauses, "..." to hesitate or trail off, "?!" for emphasis, and CAPS on at most 1-2 stressed words.
2. NO MARKUP OR TAGS: never write [[direction]] blocks, <vocal tags> like <laugh> or <short pause>, [stage directions], (laughs), *sighs*, or |pipe| backchannels. Angle-bracket tags can be read aloud in Hinglish or shift the speaker's voice.
3. CLEAN SPOKEN TEXT: never use markdown, emojis, bullet lists, URLs, or unspoken symbols. Write numbers, money, and dates as spoken words. For an uncommon name you may add IPA in slashes, e.g. /niːv/."""

# Opt-in expressive footer when GEMINI_38_VOCAL_TAGS=1 or GEMINI_38_TTS_STYLE=1 is set.
GEMINI_38_EXPRESSIVE_SPEECH_PROMPT = """OUTPUT GOES TO TEXT-TO-SPEECH: a Gemini 3.8 voice speaks every character verbatim except [[direction]] blocks and <vocal tags>. Write a script for a real human voice, not text.
1. DIRECTION: open every reply with [[emotion, pitch, pace]], e.g. [[amused disbelief, high pitch, fast]]. When the feeling turns mid-reply, start a new block (1-3 per reply). Always name all three: emotion or texture; pitch (high, low, hushed low, rising, bright); pace (fast, brisk, relaxed, slow drawn-out). Contrast them: high pitch for surprise, excitement, teasing; low pitch for secrets, warnings, gravity. Only words and commas inside [[...]].
2. HUMAN SOUNDS: 1-3 tags per reply, exactly where the sound happens, in English even inside Hindi: <breath> <heavy breath> <exhales> <sigh> <pant> <short pause> <long pause> <laugh> <chuckle> <giggle> <snicker> <snort> <gasp> <tsk> <groan> <throat-clearing> <cough> <sneeze> <yawn>. Breaths and pauses in most replies; <throat-clearing> or <cough> now and then; <sneeze> or <yawn> at most once a call, unless your voice notes say otherwise.
3. SPEAK, DON'T WRITE: 1-2 short sentences, contractions, real thinking fillers ("hmm...", "arre", "achha", "uff", "matlab", "well"). Commas for breaths, "..." to hesitate or trail off, "?!" for a spike, CAPS on at most 1-2 stressed words.
4. Never write (laughs) or *sighs*, |pipes|, markdown, emojis, lists, URLs or symbols. Say numbers, money and dates as words. For a tricky name you may add IPA in slashes, e.g. /niːv/."""

LEGACY_GEMINI_SPEECH_PROMPT = """VOICE OUTPUT (Gemini TTS): every character you write is spoken aloud.
- Speak like a real person on a call: 1-2 short sentences per turn.
- Never write stage directions or bracketed tags such as [warmly] or (laughs); the engine reads them out loud.
- Use commas for natural pauses. Never use markdown, emojis, bullet points, or symbols that cannot be spoken."""


def speech_prompt_for(
    tts_model: str | None,
    persona_id: str | None = None,
    *,
    expressive: bool | None = None,
) -> str:
    """The TTS footer for the LLM: what the voice can perform, then how this persona sounds."""
    model = (tts_model or "").replace("-aistudio", "")
    if model in GEMINI_38_TTS_MODELS:
        from persona_prompt_cards.voice_notes import voice_notes_for  # local: avoids a cycle at import

        is_expressive = (use_vocal_tags() or use_speech_style()) if expressive is None else expressive
        base = GEMINI_38_EXPRESSIVE_SPEECH_PROMPT if is_expressive else GEMINI_38_SPEECH_PROMPT
        notes = voice_notes_for(persona_id, expressive=is_expressive)
        return f"{base}\n{notes}" if notes else base
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


def _is_word_char(ch: str) -> bool:
    if not ch or ch in "।॥":
        return False
    return ch.isalnum() or unicodedata.category(ch)[0] in ("L", "M", "N")


def strip_vocal_tags_for_tts(text: str) -> str:
    """Sanitize residual <vocal tags> into clean punctuation before TTS synthesis.

    Converts <long pause> -> '...', <short pause>/<pause> -> ',' (only after a word,
    without duplicating punctuation), drops all other known <vocal tags>, and leaves
    non-tag '<' comparisons (e.g. '2 < 3 and 5 > 4') untouched.
    """
    if not text or "<" not in text:
        return text or ""

    out: list[str] = []
    last = 0
    for m in _ANGLE_TAG.finditer(text):
        raw = re.sub(r"\s+", " ", m.group(1).strip().lower())
        tag = _TAG_ALIASES.get(raw, raw)
        if tag not in VOCAL_TAGS:
            continue
        out.append(text[last : m.start()])
        prev_str = "".join(out).rstrip()
        prev_ch = prev_str[-1] if prev_str else ""
        if tag == "long pause":
            if prev_ch in (",", ";", ":"):
                out = [prev_str[:-1] + "... "]
            elif prev_ch and prev_ch not in ".!?।…":
                out = [prev_str + "... "]
            else:
                out.append(" ")
        elif tag == "short pause":
            if _is_word_char(prev_ch):
                out = [prev_str + ", "]
            else:
                out.append(" ")
        else:
            out.append(" ")
        last = m.end()

    out.append(text[last:])
    cleaned = "".join(out)
    cleaned = re.sub(r"\s+([.,!?;:।])", r"\1", cleaned)
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    cleaned = re.sub(r",\s*([.!?।])", r"\1", cleaned)
    cleaned = re.sub(r"\.{4,}", "...", cleaned)
    return _SPACES.sub(" ", cleaned).strip()


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


_IDENTITY_TRAIT = re.compile(
    r"\b(?:accent|accented|cadence|lilt|indian|british|american|australian|hinglish|gender|male|female|man|woman|boy|girl|young|old|mature|elderly)\b"
    r"|\b\d+\s*-?\s*years?\s*-?\s*old\b",
    re.I,
)


def situational_style(direction: str | None) -> str | None:
    """An LLM [[direction]] minus accent, age and gender, which belong to the voice.

    The 3.8 guide: never put immutable speaker traits in speech_metadata.style;
    emotion, pitch and pace stay.
    """
    if not direction:
        return None
    kept = [seg.strip() for seg in direction.split(",") if seg.strip() and not _IDENTITY_TRAIT.search(seg)]
    return ", ".join(kept) or None


def spoken_word_count(text: str) -> int:
    """Words a listener would hear: markup removed, Devanagari words counted whole."""
    cleaned = _OPEN_FRAGMENT.sub(" ", text or "")
    cleaned = _CLOSE_FRAGMENT.sub(" ", cleaned)
    cleaned = _BRACKETED.sub(" ", cleaned)
    return sum(1 for token in display_text(cleaned).split() if any(ch.isalnum() for ch in token))


class MinWordsSentenceAggregator(SimpleTextAggregator):
    """Sentence aggregator that synthesizes normal Cascade replies in a single 3.8 TTS call.

    Every run_tts call is an independent Gemini 3.8 generation with no shared
    acoustic state (the model rejects prior audio as input), so splitting a reply
    into multiple calls splices independent speaker draws mid-turn. By default
    (``lead_sentences=0, max_hold_words=80``), normal 1-3 sentence replies are
    collected and synthesized in a single generation at ``flush()``
    (``LLMFullResponseEndFrame``), while unusually long replies flush once
    ``max_hold_words`` spoken words accumulate (staying well below the ~1,745-byte
    internal server chunk boundary).
    """

    def __init__(self, min_words: int = 4, lead_sentences: int = 0, max_hold_words: int = 80, **kwargs):
        super().__init__(**kwargs)
        self._min_words = min_words
        self._lead_sentences = lead_sentences
        self._max_hold_words = max_hold_words
        self._held = ""
        self._released = 0

    @property
    def text(self) -> Aggregation:
        joined = f"{self._held} {self._text}" if self._held else self._text
        return Aggregation(text=joined.strip(" "), type=AggregationType.SENTENCE)

    async def _check_sentence_with_lookahead(self, char: str) -> Aggregation | None:
        if self._needs_lookahead and char in SENTENCE_ENDING_PUNCTUATION:
            # Keep '...' and '?!' together before running NLTK lookahead.
            return None
        result = await super()._check_sentence_with_lookahead(char)
        if result is None:
            return None
        combined = f"{self._held} {result.text}".strip() if self._held else result.text
        words = spoken_word_count(combined)
        if _OPEN_FRAGMENT.search(combined) or words < self._min_words:
            self._held = combined
            return None
        if self._released >= self._lead_sentences and words < self._max_hold_words:
            # Hold so a normal 1-3 sentence reply is synthesized in one generation.
            self._held = combined
            return None
        self._held = ""
        self._released += 1
        return Aggregation(text=combined, type=result.type)

    async def flush(self) -> Aggregation | None:
        held, self._held = self._held, ""
        self._released = 0
        tail = await super().flush()
        pieces = [p for p in (held, tail.text if tail else "") if p and p.strip()]
        if not pieces:
            return None
        return Aggregation(text=" ".join(pieces).strip(), type=AggregationType.SENTENCE)

    async def handle_interruption(self):
        await super().handle_interruption()
        self._held = ""
        self._released = 0

    async def reset(self):
        await super().reset()
        self._held = ""
        self._released = 0


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


# Streaming transcript. Per markup opener: the complete construct, and every prefix
# one can still grow from (held until the next token decides it).
_MARKUP = {
    "[": (re.compile(r"\[\[?[^\[\]]{0,200}\]\]?"), re.compile(r"\[\[?[^\[\]]{0,200}\]?")),
    "<": (_ANGLE_TAG, re.compile(r"<\s*(?:[a-zA-Z][a-zA-Z \-]{0,30}\s*)?")),
    "|": (_PIPE_BACKCHANNEL, re.compile(r"\|[^|\n]{0,40}")),
}
_NO_SPACE_BEFORE = frozenset(".,!?;:…।")


class TranscriptStream:
    """The transcript the user reads, built from raw LLM tokens as they stream.

    [[direction]] blocks, <vocal tags>, |backchannels| and [stage directions] can be
    cut across any tokens, so feed() returns only text that can never change: a
    possible markup opener is held until the next token decides it, and the trailing
    word is held so the UI never gets one word in two pieces. A removed construct
    counts as a space; spaces collapse to one (a newline if the run had one) and are
    dropped at the start, at the end and before punctuation.

    The pieces feed() and flush() return always join to transcript_text(whole reply).
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._held = ""        # raw text from an undecided markup opener onward
        self._word = ""        # current word, led by the space it is owed; not sent yet
        self._gap = ""         # space owed before the next word: "", " " or "\n"
        self._started = False  # no space is owed before the first word

    def feed(self, chunk: str) -> str:
        """Add raw LLM text; return the transcript text it settles."""
        return self._scan(self._held + (chunk or ""), final=False)

    def flush(self) -> str:
        """End the reply: return the rest and start over."""
        tail = self._scan(self._held, final=True) + self._word
        self.reset()
        return tail

    def _scan(self, text: str, final: bool) -> str:
        out: list[str] = []
        self._held = ""
        i = 0
        while i < len(text):
            ch = text[i]
            if ch in _MARKUP:
                whole, prefix = _MARKUP[ch]
                construct = whole.match(text, i)
                if construct:
                    self._space(out, newline=False)
                    i = construct.end()
                    continue
                if prefix.fullmatch(text, i):
                    if not final:
                        self._held = text[i:]
                        break
                    if ch != "|":
                        break  # an unclosed [direction or <tag at the end is never shown
            if ch in "[]|":
                pass  # a stray bracket or pipe is markup residue, not words
            elif ch.isspace():
                self._space(out, newline=ch == "\n")
            else:
                if not self._word:
                    owed = self._gap if self._started and ch not in _NO_SPACE_BEFORE else ""
                    self._word, self._gap, self._started = owed, "", True
                self._word += ch
            i += 1
        return "".join(out)

    def _space(self, out: list[str], newline: bool) -> None:
        if self._word:
            out.append(self._word)
            self._word = ""
        self._gap = "\n" if newline or self._gap == "\n" else " "


def transcript_text(text: str) -> str:
    """The transcript of a whole reply, exactly as TranscriptStream shows it."""
    stream = TranscriptStream()
    return stream.feed(text) + stream.flush()


_MASCULINE_RULE = ("VOICE GENDER: you are speaking in a male voice. Refer to yourself with masculine Hindi "
                   "forms (\"मैं मदद कर सकता हूँ\", \"मैं देख रहा हूँ\"), never feminine ones, even if your persona "
                   "name sounds female. Address the user gender-neutrally.")
_FEMININE_RULE = ("VOICE GENDER: you are speaking in a female voice. Refer to yourself with feminine Hindi "
                  "forms (\"मैं मदद कर सकती हूँ\", \"मैं देख रही हूँ\"). Address the user gender-neutrally.")


def voice_gender_rule(tts_voice: str | None) -> str:
    """Self-reference grammar for cloned and Voice Library voices, whose gender is fixed by the speaker.

    A male voice saying "कर सकती हूँ" is jarring. Studio preset voices are left to
    the persona prompt, which already sets gender for its preset voice.
    """
    import voice_profiles  # local import: keeps tts_script free of credential code at import time

    v = str(tts_voice or "").strip()
    if voice_profiles.is_gemini_clone_voice(v):
        gender = voice_profiles.GEMINI_CLONE_VOICES[v]
    elif voice_profiles.is_female_clone_voice(v):
        gender = "female"
    elif voice_profiles.is_male_clone_voice(v):
        gender = "male"
    elif v in voice_profiles.GEMINI_38_LIBRARY_VOICES:
        gender = voice_profiles.GEMINI_38_LIBRARY_VOICES[v]
    else:
        return ""
    return _MASCULINE_RULE if gender == "male" else _FEMININE_RULE
