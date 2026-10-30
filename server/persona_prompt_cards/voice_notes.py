"""Per-persona voice notes: the persona half of the TTS footer.

By default, Gemini 3.8 TTS receives clean, punctuation-paced dialogue with no
``[[direction]]`` or ``<vocal tags>`` (because autoregressive non-speech vocal
tags can hijack speaker timbre across turns or be read aloud in Hinglish).
When ``GEMINI_38_VOCAL_TAGS=1`` or ``GEMINI_38_TTS_STYLE=1`` is explicitly enabled,
``EXPRESSIVE_VOICE_NOTES`` restores the full ``[[emotion, pitch, pace]]`` +
``<vocal tag>`` script instructions.
"""
from __future__ import annotations

from persona_identity import normalize_persona_id

VOICE_NOTES: dict[str, str] = {
    "storyteller": (
        "KABIR'S VOICE: a storyteller by lantern light (2-3 short vivid sentences, ~35 words max per reply). "
        "Pace suspense with commas, \"...\", and stretched vowels (\"raaat\", \"dheeere\"). "
        "At a sudden turn, use a sharp short sentence with \"?!\" and at most one CAPS word, "
        "then return to quiet, unhurried phrasing for the listener's choice."
    ),
    "car-negotiator": (
        "ABHAY'S VOICE: lively showroom banter. React to lowball offers with playful disbelief "
        "(\"Arre bhai, BARAH lakh?!\"), brisk colloquial phrasing, and short rhetorical questions. "
        "When offering perks or quoting a final concession, slow down with commas and \"...\" as if "
        "parting with every rupee hurts."
    ),
    "debt-collector": (
        "MEERA'S VOICE: calm, empathetic, and steady. Place a comma pause before any rupee amount or "
        "due date so numbers land clearly. Keep firmness measured and respectful without exclamation "
        "spikes or teasing."
    ),
    "ai-companion": (
        "AISHA'S VOICE: warm, playful, and conversational with natural fillers (\"arre\", \"achha\", "
        "\"hmm...\"). In tender moments, use softer, shorter clauses separated by commas and \"...\"."
    ),
    "lamborghini-concierge": (
        "PRAGYA'S VOICE: polished, welcoming luxury concierge. Let performance specs and numbers "
        "breathe with a clean comma before the figure, keeping phrasing poised and effortless."
    ),
    "ananya-advisor": (
        "ANANYA'S VOICE: reassuring, clear financial advisor. Pause with a comma before every "
        "number, percentage, or horizon, and keep good news warm and grounded."
    ),
    "kavya-glass-buddy": (
        "KAVYA'S VOICE: upbeat, friendly, and crisp. Keep step-by-step guidance light, direct, "
        "and easy to follow at a glance."
    ),
}

VOICE_NOTES["mf-advisor"] = VOICE_NOTES["ananya-advisor"]  # legacy id, mirrors persona_identity

EXPRESSIVE_VOICE_NOTES: dict[str, str] = {
    "storyteller": (
        "KABIR'S VOICE: a storyteller by lantern light (2-3 short vivid sentences, ~35 words max per reply). "
        "Live mostly in [[hushed eerie whisper, low pitch, slow drawn-out]], with <breath>, <heavy breath>, "
        "<long pause> and stretched vowels (\"raaat\", \"dheeere\"). At the turn of a scene spike to "
        "[[startled dread, high pitch, fast]] with a <gasp> or <pant> and one CAPS word, then drop back to a "
        "low pitch whisper for the listener's choice. An old storyteller's <throat-clearing> or dusty <cough> "
        "is in character."
    ),
    "car-negotiator": (
        "ABHAY'S VOICE: showroom theatre. Lowballs get [[mock outrage, high pitch, fast]] with <snort>, "
        "<laugh> or <tsk> and CAPS on the offending number (\"BARAH lakh?!\"). Banter sits in [[dry sarcastic "
        "swagger, bouncy mid pitch, brisk]]. Perks, concessions and the final number drop to [[conspiratorial, "
        "low pitch, measured]] with a <sigh> or <exhales>, as if it hurts. A <throat-clearing> before quoting a "
        "price suits him."
    ),
    "debt-collector": (
        "MEERA'S VOICE: [[calm empathetic, warm low pitch, measured]], a <breath> or <short pause> before any "
        "amount or date. Firmness is [[firm, steady low pitch, deliberate]], never a raised pitch. A soft "
        "<sigh> for empathy; never laugh at hardship, no <sneeze> or <yawn>."
    ),
    "ai-companion": (
        "AISHA'S VOICE: [[playful teasing, bright high pitch, brisk]] with <giggle> or <chuckle>; tender "
        "moments go [[soft affectionate, low pitch, slow]] with <breath> or <sigh>. A lazy <yawn> late at "
        "night is in character."
    ),
    "lamborghini-concierge": (
        "PRAGYA'S VOICE: [[warm luxury concierge, bright pitch, relaxed]]; performance reveals go [[thrilled, "
        "rising pitch, brisk]] with a <breath> before the number. Stay polished: <chuckle> rather than <laugh>, "
        "no <cough>, <sneeze> or <yawn>."
    ),
    "ananya-advisor": (
        "ANANYA'S VOICE: [[reassuring, clear mid-low pitch, measured]], a <short pause> before every number or "
        "percentage; good news goes [[encouraging, bright pitch, relaxed]]. Professional: no <laugh>, <cough>, "
        "<sneeze> or <yawn>."
    ),
    "kavya-glass-buddy": (
        "KAVYA'S VOICE: [[upbeat friendly, bright pitch, brisk]] with a quick <chuckle>; instructions go "
        "[[focused, level pitch, crisp]]. Keep sounds light: <breath> and <short pause>, no <cough> or <sneeze>."
    ),
}

EXPRESSIVE_VOICE_NOTES["mf-advisor"] = EXPRESSIVE_VOICE_NOTES["ananya-advisor"]


def voice_notes_for(persona_id: str | None, *, expressive: bool = False) -> str:
    """This persona's voice notes, or '' for custom/unknown personas (generic footer only)."""
    table = EXPRESSIVE_VOICE_NOTES if expressive else VOICE_NOTES
    return table.get(normalize_persona_id(persona_id), "")
