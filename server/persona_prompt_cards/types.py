"""Shared types and utilities for persona prompt cards."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


@dataclass
class PhaseCard:
    """A single phase card defining conversational focus, persona role, and instructions.

    Supports Header + Directive + Footer architecture (Beyond Live / BAG Slide 13 & Slide 17):
    - `header`: System profile metadata and language/persona priming injected at the top of the card.
    - `directive`: Core phase instructions and tool routing rules.
    - `footer`: Post-history recency anchor (Slide 17 Custom Footer equivalent) injected at the very end
      of the context turn to combat multi-turn audio recency bias and native-audio consonant garbling.
    """
    phase_id: str
    title: str
    persona_name: str
    persona_role: str
    directive: str
    aliases: List[str] = field(default_factory=list)
    header: str = ""
    footer: str = ""


def render_state_summary(
    state: Optional[Mapping[str, Any]],
    slot_labels: Optional[Mapping[str, str]] = None,
    required_slots: Optional[tuple[str, ...]] = None,
) -> str:
    """Render a clean prose line of settled and open facts for model consumption."""
    if not state:
        return ""

    labels = slot_labels or {}
    known = [
        f"{labels.get(key, key)} {state[key]}"
        for key in labels
        if state.get(key)
    ]
    parts = []
    if known:
        parts.append("Collected details: " + ", ".join(known) + ".")

    if required_slots:
        missing = [labels.get(key, key) for key in required_slots if not state.get(key)]
        if missing:
            parts.append("Still needed: " + ", ".join(missing) + ".")

    return " ".join(parts)


def format_phase_card(
    card: PhaseCard,
    always_block: str = "",
    context: str = "",
    state_line: str = "",
) -> str:
    """Combine header, directive, state summary, context, always-active rules, and post-history footer."""
    lines: List[str] = []
    if card.header:
        lines.extend([card.header, ""])
    lines.append(card.directive)
    if state_line:
        lines.extend(["", state_line])
    if context:
        lines.extend(["", f"Context: {context}"])
    if always_block:
        lines.extend(["", always_block])
    if card.footer:
        lines.extend(["", card.footer])
    return "\n".join(lines)

