"""Backward-compatibility shim for Pragya supercar cards.

Canonical cards now reside in `persona_prompt_cards.pragya_cards`.
"""

from __future__ import annotations

from persona_prompt_cards.pragya_cards import (
    ALWAYS_BLOCK,
    PRAGYA_SUPERCAR_CARDS,
    SupercarPhaseCard,
    format_supercar_prompt_card,
    get_pragya_monolithic_system_instruction,
    get_pragya_phase_card,
    get_pragya_root_system_instruction,
    render_state_line,
)

__all__ = [
    "SupercarPhaseCard",
    "ALWAYS_BLOCK",
    "PRAGYA_SUPERCAR_CARDS",
    "get_pragya_phase_card",
    "render_state_line",
    "format_supercar_prompt_card",
    "get_pragya_root_system_instruction",
    "get_pragya_monolithic_system_instruction",
]
