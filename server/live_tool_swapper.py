"""Keep a running Gemini Live session's tools and system instruction current with ``context_update``.

The rule
--------
A card and its tools arrive together. The tool call whose result carries a new prompt card
first sends ``context_update`` with that card's tools, then returns the result. The model is
blocked on that tool response (every Tara tool is BLOCKING), so the frame never lands
mid-generation, and the generation that reads the card already has exactly the card's tools.
Verified live on Vertex ``gemini-3.8-live``: with only SelectLanguageTool declared, a
context_update sent before the tool response let the follow-up call PaymentTool in the same
turn, 5/5 trials, the same as a session that declared PaymentTool from the start.

The same frame also carries the system instruction (base rules + current card + live session
state), refreshed on every tool call. A sliding-window compaction drops history but keeps the
system instruction, so the card survives it. Measured live: card in history only, 6 of 7
replies after a compaction replayed the card-1 greeting; card in the SI, 0 of 7.

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

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from loguru import logger

#: Upper bound for one context_update write; on timeout the update stays pending.
SEND_TIMEOUT_S = 2.0

#: Vertex Live models where a mid-session ``context_update`` tool swap is honoured.
CONTEXT_UPDATE_TOOL_MODELS = frozenset({"gemini-3.8-live"})


def supports_context_update(model: Optional[str], vertex: bool) -> bool:
    """True only for Vertex sessions on a model that applies ``context_update`` tools."""
    name = (model or "").strip()
    if name.startswith("google/"):
        name = name[len("google/"):]
    return bool(vertex) and name in CONTEXT_UPDATE_TOOL_MODELS


def context_update_frame(declarations: Optional[List[Dict[str, Any]]] = None,
                         system_instruction: Optional[str] = None) -> Dict[str, Any]:
    """The raw client frame that replaces the declared tools, the system instruction, or both."""
    update: Dict[str, Any] = {}
    if declarations is not None:
        # An empty list sends the bare wrapper {"tools": {}}: the proto's clear-all-tools form.
        update["tools"] = {"tools": [{"functionDeclarations": declarations}]} if declarations else {}
    if system_instruction is not None:
        update["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    return {"context_update": update}


@dataclass(frozen=True)
class ToolRegistration:
    """What one card registration did, for logs and the UI.

    ``status`` describes the tools only, so the UI's tool toast fires on real tool changes and
    not on every system instruction refresh.
    """

    declared: Tuple[str, ...]
    added: Tuple[str, ...]
    removed: Tuple[str, ...]
    status: str  # "sent" | "unchanged" | "pending" (send failed; retried, then set up on reconnect)
    via: str = "context_update"

    def as_event(self, card: int) -> Dict[str, Any]:
        return {"card": card, "declared": list(self.declared), "added": list(self.added),
                "removed": list(self.removed), "via": self.via, "status": self.status}


class LiveToolSwapper:
    """Tracks what one Live session declares (tools and system instruction) and replaces it.

    ``declarations_for(names)`` returns wire declarations (dicts) for the given tool names.

    Why the system instruction rides here too: a sliding-window compaction drops history but
    always keeps the system instruction. A card that lives only in the history vanishes with
    it, and the model falls back to the setup SI's opening line (measured live: 6 of 7 replies
    after a compaction replayed the greeting; with the card in the SI, 0 of 7).
    """

    def __init__(self, declarations_for: Callable[[Sequence[str]], List[Dict[str, Any]]],
                 initial: Iterable[str], label: str = "ToolSwap") -> None:
        self._declarations_for = declarations_for
        self.active: Tuple[str, ...] = tuple(initial)
        self.pending: Optional[Tuple[str, ...]] = None
        #: The system instruction the session holds (None: still the setup one).
        self.instruction: Optional[str] = None
        self.pending_instruction: Optional[str] = None
        self.swaps = 0
        #: Frames written to the websocket, and what the last one carried (for the trace).
        self.frames = 0
        self.last_frame: Dict[str, Any] = {}
        self.label = label

    @property
    def desired(self) -> Tuple[str, ...]:
        """What the session should declare once every pending swap has landed."""
        return self.pending if self.pending is not None else self.active

    async def register(self, llm: Any, names: Iterable[str],
                       system_instruction: Optional[str] = None) -> ToolRegistration:
        """Declare ``names`` (and ``system_instruction``, when given) now. Call it inside the
        tool call that delivers the card, before returning that call's result."""
        wanted = tuple(names)
        before = self.desired
        added = tuple(n for n in wanted if n not in before)
        removed = tuple(n for n in before if n not in wanted)
        self.pending = None if wanted == self.active else wanted
        if system_instruction is not None:
            same = system_instruction == self.instruction
            self.pending_instruction = None if same else system_instruction
        if self.pending is None and self.pending_instruction is None:
            return ToolRegistration(wanted, added, removed, "unchanged")
        tools_changed = self.pending is not None
        sent = await self._send(llm)
        if not tools_changed:
            return ToolRegistration(wanted, added, removed, "unchanged")
        return ToolRegistration(wanted, added, removed, "sent" if sent else "pending")

    async def flush(self, llm: Any) -> bool:
        """Retry a swap whose send failed. Called at ``turn_complete``; True when sent."""
        if self.pending is None and self.pending_instruction is None:
            return False
        if getattr(llm, "_mixin_bot_responding", False) or getattr(llm, "_bot_is_responding", False):
            return False  # a retry outside a tool call waits for an idle model
        return await self._send(llm)

    def session_lost(self) -> None:
        """A new (not resumed) session started from the setup SI: resend ours next time."""
        if self.instruction is not None and self.pending_instruction is None:
            self.pending_instruction = self.instruction
        self.instruction = None

    async def _send(self, llm: Any) -> bool:
        session = getattr(llm, "_session", None)
        websocket = getattr(session, "_ws", None)
        if getattr(llm, "_disconnecting", False) or websocket is None:
            logger.warning(f"[{self.label}] No live websocket; the update stays pending.")
            return False
        names, instruction = self.pending, self.pending_instruction
        declarations = self._declarations_for(names) if names is not None else None
        try:
            # Bounded: the send runs under the architecture lock, which turn_complete's flush also
            # waits on, so a stalled socket must not stall the receive loop with it.
            await asyncio.wait_for(websocket.send(json.dumps(context_update_frame(declarations, instruction))),
                                   timeout=SEND_TIMEOUT_S)
        except Exception as exc:  # keep it pending: a retry or the next setup carries it
            logger.warning(f"[{self.label}] context_update send failed: {exc!r}")
            return False
        self.frames += 1
        self.last_frame = {"tools": names, "previous_tools": self.active, "instruction": instruction}
        if instruction is not None:
            self.instruction, self.pending_instruction = instruction, None
            logger.debug(f"[{self.label}] System instruction refreshed (~{len(instruction) // 4} tokens).")
        if names is not None:
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
