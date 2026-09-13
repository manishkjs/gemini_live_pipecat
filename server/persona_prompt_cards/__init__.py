"""Persona Prompt Cards & System Instructions Registry.

Houses the phase cards, monolithic instructions, and lean root instructions for
all personas across Gemini Live duplex and Cascade architectures.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from persona_prompt_cards.types import PhaseCard, format_phase_card, render_state_summary
from persona_prompt_cards.pragya_cards import (
    SupercarPhaseCard,
    PRAGYA_SUPERCAR_CARDS,
    get_pragya_phase_card,
    format_supercar_prompt_card,
    get_pragya_root_system_instruction,
    get_pragya_monolithic_system_instruction,
)
from persona_prompt_cards.ananya_cards import (
    AnanyaMFPhaseCard,
    ANANYA_MF_CARDS,
    get_ananya_phase_card,
    format_ananya_prompt_card,
    get_ananya_root_system_instruction,
    get_ananya_monolithic_system_instruction,
)
from persona_prompt_cards.kavya_cards import (
    KavyaGlassBuddyPhaseCard,
    KAVYA_GLASS_BUDDY_CARDS,
    get_kavya_phase_card,
    format_kavya_prompt_card,
    get_kavya_root_system_instruction,
    get_kavya_monolithic_system_instruction,
)
from persona_prompt_cards.ranvir_cards import (
    get_ranvir_system_instruction,
    get_ranvir_signature_instruction,
)
from persona_prompt_cards.meera_cards import (
    get_meera_system_instruction,
    get_meera_signature_instruction,
)
from persona_prompt_cards.kabir_cards import (
    get_kabir_system_instruction,
    get_kabir_signature_instruction,
)
from persona_prompt_cards.aisha_cards import (
    get_aisha_system_instruction,
    get_aisha_signature_instruction,
)

__all__ = [
    "PhaseCard",
    "format_phase_card",
    "render_state_summary",
    # Pragya
    "SupercarPhaseCard",
    "PRAGYA_SUPERCAR_CARDS",
    "get_pragya_phase_card",
    "format_supercar_prompt_card",
    "get_pragya_root_system_instruction",
    "get_pragya_monolithic_system_instruction",
    # Ananya
    "AnanyaMFPhaseCard",
    "ANANYA_MF_CARDS",
    "get_ananya_phase_card",
    "format_ananya_prompt_card",
    "get_ananya_root_system_instruction",
    "get_ananya_monolithic_system_instruction",
    # Kavya
    "KavyaGlassBuddyPhaseCard",
    "KAVYA_GLASS_BUDDY_CARDS",
    "get_kavya_phase_card",
    "format_kavya_prompt_card",
    "get_kavya_root_system_instruction",
    "get_kavya_monolithic_system_instruction",
    # Other personas
    "get_ranvir_system_instruction",
    "get_ranvir_signature_instruction",
    "get_meera_system_instruction",
    "get_meera_signature_instruction",
    "get_kabir_system_instruction",
    "get_kabir_signature_instruction",
    "get_aisha_system_instruction",
    "get_aisha_signature_instruction",
    # Unified API
    "get_persona_card",
    "get_persona_all_cards",
    "format_persona_prompt_card",
    "get_persona_system_instruction",
]


_ALIASES = {
    **dict.fromkeys(("lamborghini-concierge", "pragya", "wealth-manager"), "pragya"),
    **dict.fromkeys(("ananya-advisor", "groww-advisor", "ananya"), "ananya"),
    **dict.fromkeys(("kavya-glass-buddy", "reservation-agent", "kavya", "glass-buddy"), "kavya"),
    "car-negotiator": "ranvir", "debt-collector": "meera", "storyteller": "kabir", "ai-companion": "aisha",
}
_PHASED = {
    "pragya": (PRAGYA_SUPERCAR_CARDS, get_pragya_phase_card, format_supercar_prompt_card,
               get_pragya_root_system_instruction, get_pragya_monolithic_system_instruction),
    "ananya": (ANANYA_MF_CARDS, get_ananya_phase_card, format_ananya_prompt_card,
               get_ananya_root_system_instruction, get_ananya_monolithic_system_instruction),
    "kavya": (KAVYA_GLASS_BUDDY_CARDS, get_kavya_phase_card, format_kavya_prompt_card,
              get_kavya_root_system_instruction, get_kavya_monolithic_system_instruction),
}
_STATIC = {
    "ranvir": (get_ranvir_system_instruction, get_ranvir_signature_instruction),
    "meera": (get_meera_system_instruction, get_meera_signature_instruction),
    "kabir": (get_kabir_system_instruction, get_kabir_signature_instruction),
    "aisha": (get_aisha_system_instruction, get_aisha_signature_instruction),
}


def _normalize_persona(persona_id: Optional[str]) -> str:
    key = (persona_id or "").strip().lower()
    return _ALIASES.get(key, key)


def get_persona_card(persona_id: str, phase_id: str) -> Optional[PhaseCard]:
    entry = _PHASED.get(_normalize_persona(persona_id))
    return entry[1](phase_id) if entry else None


def get_persona_all_cards(persona_id: str) -> Dict[str, PhaseCard]:
    entry = _PHASED.get(_normalize_persona(persona_id))
    return dict(entry[0]) if entry else {}


def format_persona_prompt_card(persona_id: str, card: Any,
                               state: Optional[Mapping[str, Any]] = None, context: str = "") -> str:
    entry = _PHASED.get(_normalize_persona(persona_id))
    return entry[2](card, context=context, state=state) if entry else format_phase_card(card, context=context)


def get_persona_system_instruction(persona_id: str, engine: str = "live", tone: str = "professional") -> Optional[str]:
    key = _normalize_persona(persona_id)
    phased = _PHASED.get(key)
    if phased:
        return phased[4 if engine == "cascade" else 3]()
    static = _STATIC.get(key)
    return static[1 if tone == "signature" else 0]() if static else None


_LANGUAGE_NAMES = {
    "hi-IN": "Hindi", "en-IN": "English", "en-US": "English", "bn-IN": "Bengali",
    "te-IN": "Telugu", "mr-IN": "Marathi", "ta-IN": "Tamil", "gu-IN": "Gujarati",
    "kn-IN": "Kannada", "ml-IN": "Malayalam", "pa-IN": "Punjabi", "ur-IN": "Urdu",
    "es-ES": "Spanish", "fr-FR": "French", "de-DE": "German", "ja-JP": "Japanese",
}


def get_session_preset(persona_id: str, engine="live", tone="professional", language="en-US"):
    """One runtime/preview source. Custom instructions bypass preset resolution."""
    prompt = get_persona_system_instruction(persona_id, engine=engine, tone=tone)
    if prompt and _normalize_persona(persona_id) in _STATIC:
        name = _LANGUAGE_NAMES.get(language)
        if not name:
            raise ValueError("Unsupported preset language")
        prompt += f" Speak in {name}, unless the user requests another language."
    return prompt
