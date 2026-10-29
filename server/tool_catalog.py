"""Shared tool schema catalog, override validation, and runtime registration for Live and Cascade.

Ensures what `/persona-prompt/{persona_id}` previews, what `/connect` validates,
and what `agent_live.py` (Gemini Live) and `agent.py` (Cascade) actually execute
stay 100% identical with zero duplicate declarations.
"""
from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any, Dict, List, Optional, Tuple

# Gemini FunctionDeclaration name contract: starts with letter or underscore,
# max 64 chars, alphanumeric or _ . : -
VALID_TOOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-:]{0,63}$")


def _strip_additional_properties(value: Any) -> Any:
    """Recursively remove JSON Schema ``additionalProperties`` rejected by Gemini FunctionDeclarations."""
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in value.items():
            if k == "additionalProperties":
                continue
            if k == "properties" and isinstance(v, dict):
                cleaned[k] = {
                    pk: _strip_additional_properties(pv)
                    for pk, pv in v.items()
                    if not (pk == "additionalProperties" and isinstance(pv, bool))
                }
            else:
                cleaned[k] = _strip_additional_properties(v)
        return cleaned
    if isinstance(value, list):
        return [_strip_additional_properties(item) for item in value]
    return value


def normalize_tool_definitions(tools_raw: Any) -> List[Dict[str, Any]]:
    """Validate client-submitted tool definitions without importing heavy media SDKs.

    Raises ValueError on malformed JSON, non-list payloads, invalid tool entries,
    invalid Gemini function names, or duplicate tool names.
    """
    if isinstance(tools_raw, str):
        stripped = tools_raw.strip()
        if not stripped:
            raise ValueError("Tools override string must not be empty")
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid tools JSON: {exc}") from exc
    elif isinstance(tools_raw, list):
        parsed = tools_raw
    else:
        raise ValueError("Tools must be a JSON array of tool definitions")

    if not isinstance(parsed, list):
        raise ValueError("Tools must be a JSON array of tool definitions")
    if len(parsed) > 64:
        raise ValueError("Too many tool definitions (max 64)")

    normalized: List[Dict[str, Any]] = []
    seen_names: set[str] = set()
    for idx, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"Tool at index {idx} must be an object")
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError(f"Tool at index {idx} must have a non-empty string 'name'")
        name = raw_name.strip()
        if not VALID_TOOL_NAME_RE.match(name):
            raise ValueError(
                f"Invalid tool name '{name}': must start with a letter or underscore, "
                "contain only letters, digits, '_', '.', ':', or '-', and be at most 64 characters"
            )
        if name in seen_names:
            raise ValueError(f"Duplicate tool declaration '{name}'")
        seen_names.add(name)

        description = item.get("description", "")
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise ValueError(f"Tool '{name}' description must be a string")

        properties = item.get("properties", {})
        if properties is None:
            properties = {}
        if not isinstance(properties, dict):
            raise ValueError(f"Tool '{name}' properties must be an object")
        properties = _strip_additional_properties(properties)

        required = item.get("required", [])
        if required is None:
            required = []
        if not isinstance(required, list) or any(not isinstance(r, str) for r in required):
            raise ValueError(f"Tool '{name}' required must be an array of strings")

        normalized.append(
            {
                "name": name,
                "description": description,
                "properties": properties,
                "required": list(required),
            }
        )
    return normalized


def uses_per_card_live_tool_swap(
    persona_id: Optional[str],
    *,
    bot_type: str,
    model: Optional[str] = None,
    avatar_enabled: bool = False,
    voice: Optional[str] = None,
    has_custom_voice_audio: bool = False,
) -> bool:
    """Return True when the session dynamically swaps tools per card via Live ``context_update``."""
    if bot_type != "gemini-live":
        return False
    from persona_registry import ArchitecturePattern, resolve_persona_architecture

    if resolve_persona_architecture(persona_id) != ArchitecturePattern.JIT_TRAVEL_CARDS:
        return False

    from live_tool_swapper import supports_context_update
    import voice_profiles

    forces_vertex_38 = (
        avatar_enabled
        or voice_profiles.is_gemini_clone_voice(voice)
        or (voice == "Custom-Live-Voice" and has_custom_voice_audio)
    )
    if forces_vertex_38:
        return supports_context_update("gemini-3.8-live", True)

    raw_model = (model or "gemini-3.8-live").strip()
    is_ai_studio = "aistudio" in raw_model.lower()
    clean_model = raw_model.replace("-aistudio", "")
    if clean_model.startswith("google/"):
        clean_model = clean_model[len("google/") :]
    return supports_context_update(clean_model, not is_ai_studio)


def get_current_time_schema() -> Any:
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    return FunctionSchema(
        name="get_current_time",
        description="Get the current time.",
        properties={
            "is_explicit_request": {
                "type": "boolean",
                "description": (
                    "Return `true` ONLY if the user explicitly asks for the current time or date.\n\n"
                    "- Explaining schedules or timelines.\n"
                    "- Mentioning time casually in conversation."
                ),
            }
        },
        required=["is_explicit_request"],
    )


async def get_current_time_handler(params: Any) -> None:
    await params.result_callback(
        {"time": datetime.now().strftime("%A, %B %d, %Y %I:%M %p")}
    )


async def dynamic_tool_handler(params: Any) -> None:
    from loguru import logger

    logger.info(f"Dynamic tool called: {params.function_name} with args: {params.arguments}")
    await params.result_callback(
        {"status": "success", "message": f"Tool {params.function_name} called successfully"}
    )


def build_default_tool_schemas(persona_architecture: Any, engine: str = "live") -> List[Any]:
    """Return the default backend FunctionSchema list for a persona and engine.

    In ``cascade`` mode, only the persona's own tool schemas are declared by default
    (avoiding extra per-turn token tax on Gemma/Flash unless explicitly customized).
    In ``live`` mode, non-exclusive personas also declare ``get_current_time`` and
    ``search_knowledge_base``.
    """
    if engine == "cascade":
        if persona_architecture is not None:
            return list(persona_architecture.get_tool_schemas("cascade"))
        return []

    if persona_architecture is not None and getattr(
        persona_architecture, "has_exclusive_tools", lambda eng="live": False
    )(engine):
        return list(persona_architecture.get_tool_schemas(engine))

    from rag_function import search_knowledge_base_schema

    base: List[Any] = [
        get_current_time_schema(),
        search_knowledge_base_schema,
    ]
    if persona_architecture is not None:
        base.extend(persona_architecture.get_tool_schemas(engine))
    return base


def validate_and_parse_tool_overrides(tools_raw: Any) -> List[Any]:
    """Validate client-submitted tool definitions and convert them to deduplicated FunctionSchemas."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    return [
        FunctionSchema(
            name=entry["name"],
            description=entry["description"],
            properties=entry["properties"],
            required=entry["required"],
        )
        for entry in normalize_tool_definitions(tools_raw)
    ]


def resolve_session_tools(
    persona_architecture: Any,
    *,
    engine: str,
    tools_raw: Optional[str] = None,
) -> Tuple[List[Any], bool]:
    """Return ``(active_schemas, has_explicit_override)``.

    When ``tools_raw`` is provided, validated overrides *replace* the default
    declarations instead of appending onto them, preventing duplicate
    ``get_current_time`` / ``search_knowledge_base`` / persona declarations.
    """
    if tools_raw is not None and str(tools_raw).strip() != "":
        overrides = validate_and_parse_tool_overrides(tools_raw)
        return overrides, True
    return build_default_tool_schemas(persona_architecture, engine=engine), False


def register_runtime_tool_handlers(
    llm: Any,
    *,
    active_schemas: List[Any],
    persona_architecture: Any,
    broadcast: Any = None,
    engine: str = "live",
) -> set[str]:
    """Register built-in, persona, and custom dynamic handlers on ``llm``."""
    from rag_function import search_knowledge_base_handler

    llm.register_function("get_current_time", get_current_time_handler)
    llm.register_function("search_knowledge_base", search_knowledge_base_handler)
    built_in_tools = {"get_current_time", "search_knowledge_base"}

    if persona_architecture is not None:
        registered = persona_architecture.register_handlers(
            llm, broadcast=broadcast, engine=engine
        )
        if registered:
            built_in_tools.update(registered)

    for tool in active_schemas:
        if tool.name not in built_in_tools:
            llm.register_function(tool.name, dynamic_tool_handler)

    return built_in_tools
