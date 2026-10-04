"""Readable backend trace of what Tara's model receives and returns.

One tool call prints, in order:

    ▶ TOOL CALL      the exact arguments the model sent
    ◆ SESSION STATE  the server-owned state (``TravelBookingEngine.state``): card, step and
                     every field that changed, old -> new
    ⇢ CONTEXT_UPDATE the frame written to the Live websocket before the result: tools
                     (+added -removed) and the system instruction. The base SI is static; the
                     dynamic part (prompt card + session state + footer) is printed exactly
    ◀ TOOL RESULT    the exact JSON returned to the model (a prompt_card inside it is the same
                     text the context update printed, so it is shown by header and size)

Sizes are tokens, estimated at 4 characters per token.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

INDENT = "      "


def tokens(text: str) -> int:
    return max(1, len(text or "") // 4) if text else 0


def _indent(text: str) -> str:
    return "\n".join(INDENT + line for line in (text or "").splitlines())


def state_lines(rendered: str) -> Dict[str, str]:
    """``render_session_state`` output -> {label: value} (the header line is skipped)."""
    out: Dict[str, str] = {}
    for line in (rendered or "").splitlines()[1:]:
        label, sep, value = line.partition(": ")
        if sep:
            out[label] = value
    return out


def state_changes(before: Mapping[str, str], after: Mapping[str, str]) -> List[Tuple[str, str, str]]:
    return [(label, before.get(label, "-"), value) for label, value in after.items()
            if before.get(label) != value]


def tool_call(name: str, args: Optional[Mapping[str, Any]]) -> str:
    return f"[Tara] ▶ TOOL CALL {name}\n{INDENT}args: {json.dumps(dict(args or {}), ensure_ascii=False)}"


def session_state(card: Tuple[int, int], step: Tuple[str, str],
                  changes: Sequence[Tuple[str, str, str]]) -> str:
    card_part = f"card {card[0]}" if card[0] == card[1] else f"card {card[0]} -> {card[1]}"
    step_part = f"step {step[0]}" if step[0] == step[1] else f"step {step[0]} -> {step[1]}"
    head = f"[Tara] ◆ SESSION STATE (server-owned, TravelBookingEngine) {card_part}, {step_part}"
    if not changes:
        return f"{head}\n{INDENT}no field changed"
    rows = "\n".join(f"{INDENT}{label}: {old} -> {new}" for label, old, new in changes)
    return f"{head}\n{rows}"


def context_update(seq: int, tools: Optional[Dict[str, Any]], instruction: Optional[str],
                   dynamic: Optional[str], card_changed: bool) -> str:
    """``tools``: {declared, added, removed} when the frame swapped tools, else None.
    ``dynamic``: the CURRENT PROMPT CARD part of ``instruction``."""
    lines = [f"[Tara] ⇢ CONTEXT_UPDATE #{seq} -> Gemini Live websocket (sent before the tool result)"]
    if tools:
        lines.append(f"{INDENT}tools: now {list(tools['declared'])} "
                     f"(+{list(tools['added'])} -{list(tools['removed'])})")
    else:
        lines.append(f"{INDENT}tools: unchanged (not in this frame)")
    if instruction is None:
        lines.append(f"{INDENT}systemInstruction: unchanged (not in this frame)")
        return "\n".join(lines)
    base = instruction[: len(instruction) - len(dynamic or "")]
    digest = hashlib.sha1(base.encode()).hexdigest()[:8]
    lines.append(f"{INDENT}systemInstruction: ~{tokens(instruction)} tokens = static base ~{tokens(base)} "
                 f"(sha {digest}, greeting replaced by IN CALL) + dynamic ~{tokens(dynamic or '')}")
    if card_changed:
        lines.append(f"{INDENT}dynamic part, exact (new card):")
        lines.append(_indent(dynamic or ""))
    else:
        state = (dynamic or "").partition("Session state:")
        lines.append(f"{INDENT}dynamic part: same card directive; session state, exact:")
        lines.append(_indent("Session state:" + state[2].split("\n\n")[0]))
    return "\n".join(lines)


def tool_result(name: str, result: Mapping[str, Any]) -> str:
    shown = dict(result)
    card = shown.get("prompt_card")
    if isinstance(card, str):
        first = card.splitlines()[0] if card else ""
        shown["prompt_card"] = f"<{first} | ~{tokens(card)} tokens>"
    text = json.dumps(shown, ensure_ascii=False)
    return f"[Tara] ◀ TOOL RESULT {name} (~{tokens(json.dumps(result, ensure_ascii=False))} tokens)\n{INDENT}{text}"


def compaction(card: int, held: bool) -> str:
    if held:
        return (f"[Tara] ✂ COMPACTION: the server trimmed old turns. The live system instruction still "
                f"holds card {card} + session state, so nothing is re-sent.")
    return f"[Tara] ✂ COMPACTION: the server trimmed old turns. Re-sending card {card} into the history."
