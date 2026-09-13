"""Backward-compatibility shim for Kavya Glass Buddy cards.

Canonical cards now reside in `persona_prompt_cards.kavya_cards`.
"""

from __future__ import annotations

from persona_prompt_cards.kavya_cards import (
    KAVYA_ALWAYS_BLOCK,
    KAVYA_GLASS_BUDDY_CARDS,
    KavyaGlassBuddyPhaseCard,
    format_kavya_prompt_card,
    get_kavya_monolithic_system_instruction,
    get_kavya_phase_card,
    get_kavya_root_system_instruction,
    render_kavya_state_line,
)

__all__ = [
    "KavyaGlassBuddyPhaseCard",
    "KAVYA_ALWAYS_BLOCK",
    "KAVYA_GLASS_BUDDY_CARDS",
    "get_kavya_phase_card",
    "render_kavya_state_line",
    "format_kavya_prompt_card",
    "get_kavya_root_system_instruction",
    "get_kavya_monolithic_system_instruction",
]
