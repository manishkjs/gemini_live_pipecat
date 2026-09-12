"""Deterministic persona -> architecture routing for the voice agents.

Why this module exists
----------------------
Persona behaviour used to be inferred by sniffing substrings out of the caller's
``system_instruction`` (``"Ranvir" in system_instruction``, ``"Lamborghini" in
system_instruction`` and friends). That coupling is wrong in three ways:

1. It is fragile. Editing one word of a prompt silently disables a whole engine.
2. It leaks. Any persona that happens to mention a car inherits car tooling.
3. It confuses layers. Prompt text describes *behaviour*; it must never decide
   *infrastructure*.

Routing is therefore keyed on the immutable ``persona_id`` that the client already
owns, and nothing else. No prompt text is ever inspected here or downstream.

Adding a new architecture
-------------------------
Subclass :class:`BasePersonaArchitecture`, then register the persona in
:data:`PERSONA_REGISTRY`. ``agent_live.py`` does not need to change: it asks the
registry for an architecture object and calls the same three methods on whatever
it gets back.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Dict, List, NamedTuple, Optional


class ArchitecturePattern(str, Enum):
    """The prompt/tooling strategy a persona runs under."""

    #: A single static system instruction, no persona-specific tools.
    MONOLITHIC_STATIC = "monolithic_static"
    #: Ranvir's strict concession ladder with server-authoritative deal state.
    STATE_LADDER_NEGOTIATOR = "negotiator_ladder"
    #: Pragya's just-in-time SOP Phase Cards fetched via ``get_phase_card``.
    JIT_PHASE_CARDS = "jit_phase_cards"


class PersonaConfig(NamedTuple):
    persona_id: str
    architecture: ArchitecturePattern
    #: False locks the prompt editor in Voice Studio. Used where the prompt is
    #: load-bearing for a state machine and a demo edit would silently break it.
    is_ui_editable: bool = True


PERSONA_REGISTRY: Dict[str, PersonaConfig] = {
    # Pragya - Lamborghini VIP outbound concierge. Prompt is locked in the UI
    # because the JIT phase engine depends on its exact contract.
    "wealth-manager": PersonaConfig(
        persona_id="wealth-manager",
        architecture=ArchitecturePattern.JIT_PHASE_CARDS,
        is_ui_editable=False,
    ),
    "pragya": PersonaConfig(
        persona_id="pragya",
        architecture=ArchitecturePattern.JIT_PHASE_CARDS,
        is_ui_editable=False,
    ),
    # Ranvir - car negotiator. Entirely independent of the supercar modules;
    # they share no code, no state and no branch.
    "car-negotiator": PersonaConfig(
        persona_id="car-negotiator",
        architecture=ArchitecturePattern.STATE_LADDER_NEGOTIATOR,
    ),
    "debt-collector": PersonaConfig("debt-collector", ArchitecturePattern.MONOLITHIC_STATIC),
    "reservation-agent": PersonaConfig("reservation-agent", ArchitecturePattern.MONOLITHIC_STATIC),
    "storyteller": PersonaConfig("storyteller", ArchitecturePattern.MONOLITHIC_STATIC),
    "ai-companion": PersonaConfig("ai-companion", ArchitecturePattern.MONOLITHIC_STATIC),
    "groww-advisor": PersonaConfig("groww-advisor", ArchitecturePattern.MONOLITHIC_STATIC),
    "custom": PersonaConfig("custom", ArchitecturePattern.MONOLITHIC_STATIC),
}


def resolve_persona_architecture(persona_id: Optional[str]) -> ArchitecturePattern:
    """Map a persona id to its architecture. Unknown ids fall back to monolithic.

    An unknown id is not an error: direct API callers and the ``custom`` persona
    legitimately have no registry entry, and the safe default is the plain
    static-prompt pipeline with no persona-specific tooling.
    """
    if not persona_id:
        return ArchitecturePattern.MONOLITHIC_STATIC
    config = PERSONA_REGISTRY.get(persona_id.strip())
    return config.architecture if config else ArchitecturePattern.MONOLITHIC_STATIC


def is_persona_ui_editable(persona_id: Optional[str]) -> bool:
    """Whether Voice Studio may let a demo user edit this persona's prompt."""
    if not persona_id:
        return True
    config = PERSONA_REGISTRY.get(persona_id.strip())
    return config.is_ui_editable if config else True


# ---------------------------------------------------------------------------
# Architecture strategies
# ---------------------------------------------------------------------------


class BasePersonaArchitecture(ABC):
    """One persona execution strategy: its tools, its handlers, its state.

    Implementations must be safe to construct even when their optional
    dependencies are missing, so construction stays cheap and import-light.
    Heavy imports belong inside the methods.
    """

    pattern: ArchitecturePattern = ArchitecturePattern.MONOLITHIC_STATIC

    def has_exclusive_tools(self) -> bool:
        """If True, only get_tool_schemas() are passed to the model, omitting global standard_tools."""
        return False

    @abstractmethod
    def get_tool_schemas(self) -> List[Any]:
        """Persona-specific tool schemas appended to the standard set."""

    @abstractmethod
    def register_handlers(
        self,
        llm: Any,
        broadcast: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> List[str]:
        """Wire handlers onto ``llm``. Returns the names registered."""

    async def on_user_transcript(
        self,
        text: str,
        broadcast: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> None:
        """Observe a completed caller utterance. Default: do nothing.

        This is the seam for telemetry that must not cost the model anything --
        progress tracking, funnel position, analytics. It runs on a transcript
        that already exists, so it adds no tokens, no tool round-trip and no
        turn latency. Architectures that need it override; the rest ignore it.
        """
        return None


    def compose_system_prompt(self, system_instruction: Optional[str]) -> Optional[str]:
        """Final say over the system instruction sent to the model.

        Defaults to whatever the client supplied. Architectures whose prompt is
        load-bearing override this, which is what actually makes a "locked"
        prompt locked: the UI hides the editor, but this discards edits even if
        the client sends them anyway.
        """
        return system_instruction



class MonolithicArchitecture(BasePersonaArchitecture):
    """Static system prompt, no persona-specific tools. The default."""

    pattern = ArchitecturePattern.MONOLITHIC_STATIC

    def get_tool_schemas(self) -> List[Any]:
        return []

    def register_handlers(self, llm: Any, broadcast=None) -> List[str]:
        return []


class NegotiatorLadderArchitecture(BasePersonaArchitecture):
    """Ranvir. Server-authoritative concession ladder via ``negotiation.Deal``."""

    pattern = ArchitecturePattern.STATE_LADDER_NEGOTIATOR

    def __init__(self) -> None:
        self._deal = None

    @property
    def deal(self):
        """Lazily built so importing this module never pulls in negotiation."""
        if self._deal is None:
            import negotiation

            self._deal = negotiation.Deal(strict_ladder=True)
        return self._deal

    def get_tool_schemas(self) -> List[Any]:
        import negotiation
        from pipecat.adapters.schemas.function_schema import FunctionSchema

        return [
            FunctionSchema(
                name=s["name"],
                description=s["description"],
                properties=s["properties"],
                required=s["required"],
            )
            for s in negotiation.TOOL_SCHEMAS
        ]

    def register_handlers(self, llm: Any, broadcast=None) -> List[str]:
        from loguru import logger

        deal = self.deal

        async def handle_concede_price(params):
            reason = (params.arguments or {}).get("reason", "buyer negotiated price")
            res = deal.concede(reason)
            logger.info(f"[Negotiator] concede_price -> {res}")
            await params.result_callback(res)

        async def handle_include_extra(params):
            item = (params.arguments or {}).get("item", "")
            res = deal.grant_extra(item)
            logger.info(f"[Negotiator] include_extra -> {res}")
            await params.result_callback(res)

        async def handle_close_deal(params):
            price = (params.arguments or {}).get("price_usd", 0)
            res = deal.close(price)
            logger.info(f"[Negotiator] close_deal -> {res}")
            await params.result_callback(res)

        llm.register_function("concede_price", handle_concede_price)
        llm.register_function("include_extra", handle_include_extra)
        llm.register_function("close_deal", handle_close_deal)
        return ["concede_price", "include_extra", "close_deal"]


class JITPhaseCardsArchitecture(BasePersonaArchitecture):
    """Pragya. One tool, one prompt, and server-derived funnel telemetry.

    Two things used to be conflated and are now separated:

    * **What the model can do** -- exactly one tool,
      ``create_appointment_booking``. Every extra declared tool is re-billed as
      prompt text on every single turn, so the tool list is the smallest set
      that can still complete the call's actual goal.
    * **Where the call has got to** -- derived on the server from the caller's
      own transcript (see :mod:`supercar_phases`). Previously the UI advanced
      only when the model called ``get_phase_card``, which meant a caller could
      give their PIN code, get booked, and still be displayed as "Phase 1"
      because no tool had happened to fire. Progress display is now independent
      of the model's tool choices, and costs nothing.
    """

    pattern = ArchitecturePattern.JIT_PHASE_CARDS

    #: The one phase that is deliberately not delivered as a card.
    #:
    #: The deck is keyed by the tracker's own phase IDs, so every other advance
    #: looks its card up directly — there is no translation table to drift.
    #: ``SOP_01_OPENING`` is excluded because the opening already *is* the root
    #: system instruction: the tracker starts there and never "moves" into it,
    #: so pushing that card would re-brief her on a call she has already begun.
    CARDLESS_PHASES = frozenset({"SOP_01_OPENING"})

    def __init__(self) -> None:
        self._tracker = None
        self._llm = None

    @property
    def tracker(self):
        """Lazily built so importing this module stays dependency-free."""
        if self._tracker is None:
            from supercar_phases import PragyaPhaseTracker

            self._tracker = PragyaPhaseTracker()
        return self._tracker

    def has_exclusive_tools(self) -> bool:
        return True

    def compose_system_prompt(self, system_instruction: Optional[str]) -> Optional[str]:
        """Always the outbound concierge root prompt, whatever the client sent.

        Client input is discarded here on purpose: the call's opening contract
        is load-bearing, and a well-meant demo edit would break it silently.
        """
        from supercar_cards import get_pragya_root_system_instruction

        return get_pragya_root_system_instruction()

    def get_tool_schemas(self) -> List[Any]:
        from supercar_tools import SUPERCAR_TOOL_SCHEMAS

        return list(SUPERCAR_TOOL_SCHEMAS)

    async def _push_phase_card(self, phase_id: str, reason: str = "") -> bool:
        """Deliver the card for ``phase_id`` into the live session, silently.

        Returns whether the model actually received it. The phase light is only
        honest if it reports delivery — otherwise the UI says "new prompt is in"
        while Pragya is still working off the old one.

        The card is injected with ``speak_now=False``: it is a brief for her
        *next* reply to the caller, not something to answer out loud. Committing
        the turn here made her respond to the card and collide with the reply
        she was already forming.
        """
        from loguru import logger

        if phase_id in self.CARDLESS_PHASES:
            return False

        inject = getattr(self._llm, "inject_directive", None)
        if inject is None:
            # No live session (tests, replay, a transport without the hook).
            # The phase still advances; it just cannot claim a card went in.
            return False

        from supercar_cards import PRAGYA_SUPERCAR_CARDS, format_supercar_prompt_card

        card = PRAGYA_SUPERCAR_CARDS.get(phase_id)
        if card is None:
            logger.warning(f"[Pragya/Card] No card authored for {phase_id}.")
            return False

        delivered = await inject(
            format_supercar_prompt_card(card, context=reason),
            tag=f"Pragya/Card {phase_id}",
            speak_now=False,
        )
        return bool(delivered)

    async def on_user_transcript(self, text: str, broadcast=None) -> None:
        """Advance the funnel from caller speech and announce real moves only."""
        from loguru import logger

        tracker = self.tracker
        moved = tracker.observe_user_text(text)
        if not moved:
            return

        card_pushed = await self._push_phase_card(moved, reason=text[:120])
        logger.info(
            f"[Pragya/Phase] -> {moved} ({tracker.title_of(moved)}) "
            f"card_pushed={card_pushed}"
        )
        if broadcast:
            await broadcast(
                {
                    "type": "phase_transition",
                    "phase_id": moved,
                    "title": tracker.title_of(moved),
                    "reason": text[:120],
                    "card_pushed": card_pushed,
                }
            )

    def register_handlers(self, llm: Any, broadcast=None) -> List[str]:
        from loguru import logger
        from supercar_tools import create_appointment_booking

        # Kept so a phase advance can push its SOP card straight into the live
        # session -- the phase light is meant to be proof a new prompt landed.
        self._llm = llm

        async def handle_create_appointment_booking(params):
            args = params.arguments or {}
            pincode = (
                args.get("pincode")
                or args.get("city_or_pincode")
                or args.get("city")
                or args.get("center_id", "")
            )
            res = create_appointment_booking(
                pincode=pincode,
                date=args.get("date", "Tomorrow"),
                time=args.get("time", "11:00 AM"),
                customer_name_or_phone=args.get("customer_name_or_phone") or args.get("customer_phone", ""),
                vehicle_variant=args.get("vehicle_variant", "Lamborghini Revuelto"),
                center_id=args.get("center_id"),
            )
            logger.info(f"[Pragya/Booking] booking -> {res.get('booking_id')} ({res.get('center_name')})")

            if res.get("status") == "confirmed":
                # An executed booking is the only evidence that closes the
                # funnel -- the caller merely agreeing is not.
                moved = self.tracker.observe_booking_confirmed()
                if moved:
                    # Lands just ahead of the tool result, so the confirmation
                    # she reads out is already governed by the aftercare card.
                    card_pushed = await self._push_phase_card(
                        moved, reason="appointment confirmed"
                    )
                    logger.info(
                        f"[Pragya/Phase] -> {moved} ({self.tracker.title_of(moved)}) "
                        f"card_pushed={card_pushed}"
                    )
                    if broadcast:
                        await broadcast(
                            {
                                "type": "phase_transition",
                                "phase_id": moved,
                                "title": self.tracker.title_of(moved),
                                "reason": "appointment confirmed",
                                "card_pushed": card_pushed,
                            }
                        )
                if broadcast:
                    await broadcast(
                        {
                            "type": "booking_confirmed",
                            "booking_id": res.get("booking_id"),
                            "center_name": res.get("center_name"),
                            "city": res.get("city"),
                            "address": res.get("address"),
                            "date": res.get("date"),
                            "time": res.get("time"),
                            "vehicle_variant": res.get("vehicle_variant"),
                        }
                    )

            await params.result_callback(res)

        llm.register_function("create_appointment_booking", handle_create_appointment_booking)
        return ["create_appointment_booking"]


_ARCHITECTURE_IMPLEMENTATIONS = {
    ArchitecturePattern.MONOLITHIC_STATIC: MonolithicArchitecture,
    ArchitecturePattern.STATE_LADDER_NEGOTIATOR: NegotiatorLadderArchitecture,
    ArchitecturePattern.JIT_PHASE_CARDS: JITPhaseCardsArchitecture,
}


def get_persona_architecture(persona_id: Optional[str]) -> BasePersonaArchitecture:
    """Build the architecture strategy for a persona id.

    This is the single entry point ``agent_live.py`` uses. It never inspects the
    system instruction.
    """
    pattern = resolve_persona_architecture(persona_id)
    return _ARCHITECTURE_IMPLEMENTATIONS[pattern]()
