"""Shared persona IDs for architecture, prompt and phase-card resolution.

Aliases are API compatibility, never caller-speech classification. Keep the
existing UI IDs valid when display names or internal prompt modules change.
"""

PERSONA_ALIASES = {
    "pragya": "lamborghini-concierge",
    # Legacy callers must retain Pragya's cards and booking tools.
    "wealth-manager": "lamborghini-concierge",
    "groww-advisor": "ananya-advisor",
    "ananya": "ananya-advisor",
    "reservation-agent": "kavya-glass-buddy",
    "kavya": "kavya-glass-buddy",
    "glass-buddy": "kavya-glass-buddy",
    "abhay": "car-negotiator",
    "ranvir": "car-negotiator",  # legacy name, kept so old links still route
    "meera": "debt-collector",
    "kabir": "storyteller",
    "aisha": "ai-companion",
}


def normalize_persona_id(persona_id: str | None) -> str:
    key = (persona_id or "").strip().lower()
    return PERSONA_ALIASES.get(key, key)


GENERIC_FALLBACK_VOICE_PROMPT = "Warm, natural conversational tone."

PERSONA_VOICE_DESIGN_DEFAULTS: dict[str, dict[str, str]] = {
    "lamborghini-concierge": {
        "voice": "Gacrux",
        "style": "Warm & Friendly",
        "pace": "Natural",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Warm, confident luxury automotive concierge from Mumbai. Speak with a welcoming smile.",
    },
    "car-negotiator": {
        "voice": "Fenrir",
        "style": "Expressive / Dramatic",
        "pace": "Conversational",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Sharp, witty Delhi car dealer with lively pitch modulation, playful sarcasm, and punchy emphasis.",
    },
    "debt-collector": {
        "voice": "Gacrux",
        "style": "Empathetic",
        "pace": "Natural",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Empathetic yet firm collections specialist. Calm, reassuring Indian English cadence.",
    },
    "storyteller": {
        "voice": "Gacrux",
        "style": "Expressive / Dramatic",
        "pace": "Conversational",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Expressive Indian storyteller. Rich theatrical modulation and warm emotional pacing.",
    },
    "ai-companion": {
        "voice": "Aoede",
        "style": "Warm & Friendly",
        "pace": "Conversational",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Warm, witty, affectionate companion with playful modulation and natural conversational flow.",
    },
    "ananya-advisor": {
        "voice": "Aoede",
        "style": "Professional",
        "pace": "Natural",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Trusted wealth & mutual fund advisor. Articulate, reassuring, and clear with financial numbers.",
    },
    "kavya-glass-buddy": {
        "voice": "Aoede",
        "style": "Conversational",
        "pace": "Brisk",
        "accent": "Indian",
        "pitch": "Default",
        "prompt": "Friendly smart-glasses AI companion. Crisp, upbeat, and helpful.",
    },
}

# Also allow direct lookups by legacy alias keys.
for _alias, _canonical in PERSONA_ALIASES.items():
    if _canonical in PERSONA_VOICE_DESIGN_DEFAULTS:
        PERSONA_VOICE_DESIGN_DEFAULTS[_alias] = PERSONA_VOICE_DESIGN_DEFAULTS[_canonical]
PERSONA_VOICE_DESIGN_DEFAULTS["mf-advisor"] = PERSONA_VOICE_DESIGN_DEFAULTS["ananya-advisor"]


def resolve_persona_voice_design(
    persona_id: str | None,
    tts_style: str | None = None,
    tts_pace_label: str | None = None,
    tts_accent: str | None = None,
    tts_pitch: str | None = None,
    tts_voice_prompt: str | None = None,
) -> dict[str, str]:
    """Resolve TTS Voice Design fields for a persona, upgrading generic UI fallbacks."""
    canonical = normalize_persona_id(persona_id)
    defaults = PERSONA_VOICE_DESIGN_DEFAULTS.get(canonical, {})

    is_generic_fallback = (
        (not tts_style or tts_style.strip() == "Empathetic")
        and (not tts_voice_prompt or tts_voice_prompt.strip() == GENERIC_FALLBACK_VOICE_PROMPT)
        and bool(defaults)
    )

    if is_generic_fallback:
        return {
            "style": defaults.get("style", "Empathetic"),
            "pace": defaults.get("pace", "Natural"),
            "accent": tts_accent or defaults.get("accent", "Indian"),
            "pitch": tts_pitch or defaults.get("pitch", "Default"),
            "prompt": defaults.get("prompt", GENERIC_FALLBACK_VOICE_PROMPT),
        }

    return {
        "style": tts_style or defaults.get("style", "Empathetic"),
        "pace": tts_pace_label or defaults.get("pace", "Natural"),
        "accent": tts_accent or defaults.get("accent", "Indian"),
        "pitch": tts_pitch or defaults.get("pitch", "Default"),
        "prompt": tts_voice_prompt or defaults.get("prompt", ""),
    }

