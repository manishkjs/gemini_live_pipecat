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
import asyncio
from enum import Enum
from typing import Any, Callable, Dict, List, NamedTuple, Optional


class ArchitecturePattern(str, Enum):
    """The prompt/tooling strategy a persona runs under."""

    #: A single static system instruction, no persona-specific tools.
    MONOLITHIC_STATIC = "monolithic_static"
    #: Ranvir's strict concession ladder with server-authoritative deal state.
    STATE_LADDER_NEGOTIATOR = "negotiator_ladder"
    #: Pragya's context cards selected by Gemini through ``switch_phase``.
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
    "lamborghini-concierge": PersonaConfig(
        persona_id="lamborghini-concierge",
        architecture=ArchitecturePattern.JIT_PHASE_CARDS,
        is_ui_editable=False,
    ),
    # Deprecated id, kept only so a browser holding the old value in
    # localStorage still reaches the phase-card architecture. Dropping it
    # outright would degrade those sessions to a plain prompt with no cards and
    # no tools, which is a failure that looks like a model regression.
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
    model_controls_conversation = False

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
    """Gemini chooses a phase; the server delivers its card and validates tools.

    Opening lives in the root instruction. No transcript observer, classifier,
    forced sequence or background model call selects the other three phases.
    """

    pattern = ArchitecturePattern.JIT_PHASE_CARDS
    model_controls_conversation = True

    def __init__(self) -> None:
        self._tracker = None
        self._slots = None
        self._llm = None
        self._card_lock = asyncio.Lock()
        self._last_card_key = None
        self._card_delivery_status = None
        self._phase_broadcast = None
        self._phase_event_revision = 0

    @property
    def tracker(self):
        if self._tracker is None:
            from supercar_phases import PragyaPhaseTracker
            self._tracker = PragyaPhaseTracker()
        return self._tracker

    @property
    def slots(self):
        if self._slots is None:
            from supercar_phases import CallSlots
            self._slots = CallSlots()
        return self._slots

    def has_exclusive_tools(self) -> bool:
        return True

    def compose_system_prompt(self, system_instruction: Optional[str]) -> Optional[str]:
        from supercar_cards import get_pragya_root_system_instruction
        return get_pragya_root_system_instruction()

    def get_tool_schemas(self) -> List[Any]:
        from supercar_tools import SUPERCAR_TOOL_SCHEMAS
        return list(SUPERCAR_TOOL_SCHEMAS)

    async def _emit(self, payload: Dict[str, Any]) -> None:
        """A UI connection failure must not prevent the model's tool response."""
        if self._phase_broadcast is not None:
            try:
                await self._phase_broadcast(payload)
            except Exception as exc:
                from loguru import logger
                logger.warning(f"[Pragya] UI event failed: {exc}")

    async def _broadcast_phase(self, card_pushed: bool) -> None:
        self._phase_event_revision += 1
        await self._emit({
            "type": "phase_transition",
            "phase_id": self.tracker.current_phase,
            "title": self.tracker.title_of(self.tracker.current_phase),
            "reason": "model selected phase" if card_pushed else "card delivery failed; phase unchanged",
            "card_pushed": card_pushed,
            "delivery_status": self._card_delivery_status,
            "revision": self._phase_event_revision,
            "furthest_phase": self.tracker.furthest_phase,
            "slots": self.slots.as_dict(),
        })

    def _collect_fields(self, args: Dict[str, Any]) -> List[str]:
        return self.slots.propose(
            pincode=args.get("pincode"),
            visit_date=args.get("date"),
            visit_time=args.get("time"),
            car_choice=args.get("vehicle_variant"),
        )

    async def _switch_phase(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from loguru import logger
        from supercar_cards import PRAGYA_SUPERCAR_CARDS, format_supercar_prompt_card

        phase_id = args.get("phase_id")
        try:
            self.tracker.validate_phase(phase_id)
        except ValueError as exc:
            return {"status": "invalid_phase", "message": str(exc)}

        invalid = self._collect_fields(args)
        if invalid:
            return {"status": "invalid_arguments", "invalid_fields": invalid}

        state = self.slots.as_dict()
        key = (phase_id, tuple(sorted(state.items())))
        if key == self._last_card_key:
            if self._card_delivery_status != "sent":
                self._card_delivery_status = "sent"
                await self._broadcast_phase(True)
            return {"status": "success", "phase_id": phase_id, "delivery_status": "already_sent"}

        try:
            # This blocking tool has paused Gemini. Send context BEFORE its
            # function response, even if the provider's responding flag is set.
            delivered = await self._llm.inject_directive(
                format_supercar_prompt_card(PRAGYA_SUPERCAR_CARDS[phase_id], state=state),
                tag=f"Pragya/Card {phase_id}", speak_now=False, at_tool_boundary=True,
            )
        except Exception as exc:
            logger.warning(f"[Pragya/Card] Send failed: {exc}")
            delivered = False

        self._card_delivery_status = "sent" if delivered else "failed"
        if delivered:
            self._last_card_key = key
            self.tracker.select_phase(phase_id)
        await self._broadcast_phase(bool(delivered))
        if not delivered:
            return {
                "status": "delivery_failed", "phase_id": self.tracker.current_phase,
                "message": "The new card was not sent. Retry switch_phase before using that phase.",
            }
        # The card is already in context. Do not duplicate it in the tool result.
        return {"status": "success", "phase_id": phase_id, "delivery_status": "sent"}

    async def _book_appointment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from supercar_tools import create_appointment_booking

        invalid = self._collect_fields(args)
        await self._emit({"type": "call_state", "slots": self.slots.as_dict()})
        if invalid:
            return {"status": "invalid_arguments", "invalid_fields": invalid}
        missing = self.slots.missing_for_booking()
        if missing:
            return {"status": "needs_info", "missing": missing}

        res = create_appointment_booking(
            pincode=self.slots.get("pincode"),
            date=self.slots.get("visit_date"),
            time=self.slots.get("visit_time"),
            customer_name_or_phone=args.get("customer_name_or_phone", ""),
            vehicle_variant=self.slots.get("car_choice") or "the car chosen at the Lounge",
        )
        if res.get("status") == "confirmed":
            self.slots.set_tool(booking_status="confirmed", booking_ref=res.get("booking_id"))
            self.slots.set_server(lounge_id=res.get("center_id"), lounge_name=res.get("center_name"))
            self.tracker.booking_confirmed = True
            await self._emit({"type": "call_state", "slots": self.slots.as_dict()})
            await self._emit({
                "type": "booking_confirmed",
                **{key: res.get(key) for key in (
                    "booking_id", "center_name", "city", "address", "date", "time", "vehicle_variant",
                )},
            })
        # Recording a booking does not select a card. Gemini chooses the next
        # phase after reading this tool result, just as for any topic change.
        return res

    def register_handlers(self, llm: Any, broadcast=None) -> List[str]:
        self._llm = llm
        self._phase_broadcast = broadcast

        async def handle_switch_phase(params):
            async with self._card_lock:
                result = await self._switch_phase(params.arguments or {})
            await params.result_callback(result)

        async def handle_create_appointment_booking(params):
            async with self._card_lock:
                result = await self._book_appointment(params.arguments or {})
            await params.result_callback(result)

        llm.register_function("switch_phase", handle_switch_phase)
        llm.register_function("create_appointment_booking", handle_create_appointment_booking)
        return ["switch_phase", "create_appointment_booking"]


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
