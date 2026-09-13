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


def _normalize_persona(persona_id: Optional[str]) -> str:
    if not persona_id:
        return ""
    p = persona_id.strip().lower()
    if p in ("lamborghini-concierge", "pragya", "wealth-manager"):
        return "pragya"
    if p in ("ananya-advisor", "groww-advisor", "ananya"):
        return "ananya"
    if p in ("kavya-glass-buddy", "reservation-agent", "kavya", "glass-buddy"):
        return "kavya"
    if p in ("car-negotiator", "ranvir"):
        return "ranvir"
    if p in ("debt-collector", "meera"):
        return "meera"
    if p in ("storyteller", "kabir"):
        return "kabir"
    if p in ("ai-companion", "aisha"):
        return "aisha"
    return p


def get_persona_card(persona_id: str, phase_id: str) -> Optional[PhaseCard]:
    """Resolve a phase card for any persona by id or alias."""
    norm = _normalize_persona(persona_id)
    if norm == "pragya":
        return get_pragya_phase_card(phase_id)
    elif norm == "ananya":
        return get_ananya_phase_card(phase_id)
    elif norm == "kavya":
        return get_kavya_phase_card(phase_id)
    return None


def get_persona_all_cards(persona_id: str) -> Dict[str, PhaseCard]:
    """Retrieve all defined phase cards for a persona."""
    norm = _normalize_persona(persona_id)
    if norm == "pragya":
        return dict(PRAGYA_SUPERCAR_CARDS)
    elif norm == "ananya":
        return dict(ANANYA_MF_CARDS)
    elif norm == "kavya":
        return dict(KAVYA_GLASS_BUDDY_CARDS)
    return {}


def format_persona_prompt_card(
    persona_id: str,
    card: Any,
    state: Optional[Mapping[str, Any]] = None,
    context: str = "",
) -> str:
    """Format a persona phase card into injection text."""
    norm = _normalize_persona(persona_id)
    if norm == "pragya":
        return format_supercar_prompt_card(card, context=context, state=state)
    elif norm == "ananya":
        return format_ananya_prompt_card(card, context=context, state=state)
    elif norm == "kavya":
        return format_kavya_prompt_card(card, context=context, state=state)
    return format_phase_card(card, context=context)


def get_persona_system_instruction(
    persona_id: str,
    engine: str = "live",
    tone: str = "professional",
) -> Optional[str]:
    """Return the system prompt the backend runs for this persona and engine."""
    norm = _normalize_persona(persona_id)
    if norm == "pragya":
        return get_pragya_monolithic_system_instruction() if engine == "cascade" else get_pragya_root_system_instruction()
    elif norm == "ananya":
        return get_ananya_monolithic_system_instruction() if engine == "cascade" else get_ananya_root_system_instruction()
    elif norm == "kavya":
        return get_kavya_monolithic_system_instruction() if engine == "cascade" else get_kavya_root_system_instruction()
    elif norm == "ranvir":
        return get_ranvir_signature_instruction() if tone == "signature" else get_ranvir_system_instruction()
    elif norm == "meera":
        return get_meera_signature_instruction() if tone == "signature" else get_meera_system_instruction()
    elif norm == "kabir":
        return get_kabir_signature_instruction() if tone == "signature" else get_kabir_system_instruction()
    elif norm == "aisha":
        return get_aisha_signature_instruction() if tone == "signature" else get_aisha_system_instruction()
    return None
