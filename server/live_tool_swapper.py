"""Register each prompt card's tools in a running Gemini Live session with ``context_update``.

The rule
--------
A card and its tools arrive together. The tool call whose result carries a new prompt card
first sends ``context_update`` with that card's tools, then returns the result. The model is
blocked on that tool response (every Tara tool is BLOCKING), so the frame never lands
mid-generation, and the generation that reads the card already has exactly the card's tools.
Verified live on Vertex ``gemini-3.8-live``: with only SelectLanguageTool declared, a
context_update sent before the tool response let the follow-up call PaymentTool in the same
turn, 5/5 trials, the same as a session that declared PaymentTool from the start.

What it buys
------------
Every declared tool is billed on every model generation. Card 1 declares one tool, cards 2
and 3 three each, cards 4 to 7 four, and card 8 five; no card declares all six.

Where it works (verified live, not assumed)
-------------------------------------------
* Vertex ``gemini-3.8-live``: the frame is applied and a newly added tool fires after it.
* Not AI Studio (gated and silently ignored), not the 2.5 native-audio models (close 1007),
  not ``gemini-3.5-flash-live-preview`` (silently ignored). Those keep the full tool set.

Failure handling
----------------
A send that fails (or finds no websocket) stays pending. It is retried at the next
``turn_complete`` (``flush``) and, on reconnect, the setup message declares it
(``setup_tools``), so a new or resumed session never falls back to the opening tools.

google-genai 2.25 has no typed ``context_update`` method, so the frame is written to the
SDK session's websocket. Wire names are camelCase and schema types uppercase.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from loguru import logger

#: Vertex Live models where a mid-session ``context_update`` tool swap is honoured.
CONTEXT_UPDATE_TOOL_MODELS = frozenset({"gemini-3.8-live"})


def supports_context_update(model: Optional[str], vertex: bool) -> bool:
    """True only for Vertex sessions on a model that applies ``context_update`` tools."""
    name = (model or "").strip()
    if name.startswith("google/"):
        name = name[len("google/"):]
    return bool(vertex) and name in CONTEXT_UPDATE_TOOL_MODELS


def context_update_frame(declarations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The raw client frame that replaces the declared tools."""
    return {"context_update": {"tools": {"tools": [{"functionDeclarations": declarations}]}}}


@dataclass(frozen=True)
class ToolRegistration:
    """What one card registration did, for logs and the UI."""

    declared: Tuple[str, ...]
    added: Tuple[str, ...]
    removed: Tuple[str, ...]
    status: str  # "sent" | "unchanged" | "pending" (send failed; retried, then set up on reconnect)
    via: str = "context_update"

    def as_event(self, card: int) -> Dict[str, Any]:
        return {"card": card, "declared": list(self.declared), "added": list(self.added),
                "removed": list(self.removed), "via": self.via, "status": self.status}


class LiveToolSwapper:
    """Tracks the declared tools of one Live session and replaces them per card.

    ``declarations_for(names)`` returns wire declarations (dicts) for the given tool names.
    """

    def __init__(self, declarations_for: Callable[[Sequence[str]], List[Dict[str, Any]]],
                 initial: Iterable[str], label: str = "ToolSwap") -> None:
        self._declarations_for = declarations_for
        self.active: Tuple[str, ...] = tuple(initial)
        self.pending: Optional[Tuple[str, ...]] = None
        self.swaps = 0
        self.label = label

    @property
    def desired(self) -> Tuple[str, ...]:
        """What the session should declare once every pending swap has landed."""
        return self.pending if self.pending is not None else self.active

    async def register(self, llm: Any, names: Iterable[str]) -> ToolRegistration:
        """Declare ``names`` now. Call it inside the tool call that delivers the card, before
        returning that call's result."""
        wanted = tuple(names)
        before = self.desired
        added = tuple(n for n in wanted if n not in before)
        removed = tuple(n for n in before if n not in wanted)
        if wanted == self.active:
            self.pending = None
            return ToolRegistration(wanted, added, removed, "unchanged")
        self.pending = wanted
        sent = await self._send(llm)
        return ToolRegistration(wanted, added, removed, "sent" if sent else "pending")

    async def flush(self, llm: Any) -> bool:
        """Retry a swap whose send failed. Called at ``turn_complete``; True when sent."""
        if self.pending is None:
            return False
        if getattr(llm, "_mixin_bot_responding", False) or getattr(llm, "_bot_is_responding", False):
            return False  # a retry outside a tool call waits for an idle model
        return await self._send(llm)

    async def _send(self, llm: Any) -> bool:
        session = getattr(llm, "_session", None)
        websocket = getattr(session, "_ws", None)
        if getattr(llm, "_disconnecting", False) or websocket is None:
            logger.warning(f"[{self.label}] No live websocket; tools stay pending for the next setup.")
            return False
        names = self.pending
        try:
            await websocket.send(json.dumps(context_update_frame(self._declarations_for(names))))
        except Exception as exc:  # keep it pending: a retry or the next setup carries it
            logger.warning(f"[{self.label}] context_update send failed: {exc}")
            return False
        previous, self.active, self.pending = self.active, names, None
        self.swaps += 1
        added = [n for n in names if n not in previous]
        removed = [n for n in previous if n not in names]
        logger.info(f"[{self.label}] Swap {self.swaps}: now {list(names)} (+{added} -{removed}).")
        return True

    def setup_tools(self) -> Tuple[str, ...]:
        """The tools a new setup message must declare. Pending swaps land with it."""
        self.active, self.pending = self.desired, None
        return self.active
