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
    "ranvir": "car-negotiator",
    "meera": "debt-collector",
    "kabir": "storyteller",
    "aisha": "ai-companion",
}


def normalize_persona_id(persona_id: str | None) -> str:
    key = (persona_id or "").strip().lower()
    return PERSONA_ALIASES.get(key, key)
