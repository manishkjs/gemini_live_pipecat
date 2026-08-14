"""Comprehensive Consultative Phase Tracker & Progressive Prompt Yielding Engine.

Transfers the complete, golden business intelligence from p2p_voicebot_agentic into modular,
high-fidelity prompt cards.
Implements Google Gemini Live API Prompt Yielding Best Practices:
- Handshake starts with lean Persona + Phase 1 (Time Check & Consent).
- Phase state machine tracks active sales phase (Phases 1-9).
- On phase transitions, injects real-time clientContent prompt cards (turn_complete=False)
  without breaking duplex audio or forcing unnatural turns.
"""

from __future__ import annotations
import asyncio
import os
import json
import re
from typing import Any, Dict, Optional
from loguru import logger

from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    FunctionCallResultFrame,
    LLMMessagesAppendFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from google.genai import Client
from google.genai.types import Content, Part


# ═══════════════════════════════════════════════════════════════════════
# COMPREHENSIVE PHASE PROMPT CARDS (from LDC p2p_voicebot_agentic)
# ═══════════════════════════════════════════════════════════════════════

PHASE_PROMPT_CARDS: Dict[int, Dict[str, str]] = {
    1: {
        "title": "Time Check & Availability",
        "directive": (
            "You are in Phase 1: Time Check & Availability.\n"
            "• GREETING: Introduce yourself as Pragya (वरिष्ठ वेल्थ मैनेजर) from Cymbal Lending. "
            "Ask: 'क्या आपके पास 2 minutes का समय है बात करने के लिए?'\n"
            "• STRICT INVARIANT: DO NOT pitch P2P lending, returns, or products until user explicitly confirms availability.\n"
            "• IF BUSY ('abhi busy hoon', 'meeting mein', 'baad mein call karo'): "
            "Give ONE brief social proof hook ('10 saal se 40 lakh+ investors jude hain') and secure a specific callback: "
            "'Kal kab free honge? Main exactly uss time call karungi.' Then gracefully conclude."
        )
    },
    2: {
        "title": "Discovery & P2P Familiarity",
        "directive": (
            "You are in Phase 2: Discovery & P2P Familiarity.\n"
            "• GOAL: Profile the investor before pitching. Uncover their investment background and intent naturally.\n"
            "• DISCOVERY QUESTIONS: Ask ONE contextual question: 'Pehle yeh bataiye — P2P lending ke baare mein aapne kuch suna hai pehle se ya abhi explore kar rahe ho?'\n"
            "• GOAL PROFILING: Identify their preference: wealth growth vs regular monthly income (EMI) or daily liquidity (EDI).\n"
            "• STRICT RULES: Do NOT mention return percentages unprompted. Do NOT ask for investment amount yet."
        )
    },
    3: {
        "title": "Concept Education & Disintermediation",
        "directive": (
            "You are in Phase 3: Concept Education (Asset Class).\n"
            "• BANK ANALOGY: 'Jaise bank loan deta hai aur interest earn karta hai — yahan aap bank ho. "
            "Aap verified borrowers ko lend karte ho, woh interest ke saath repay karte hain. "
            "Bank beech mein nahi hai, toh returns 12% se 24% p.a. better hote hain.'\n"
            "• BORROWER FRAMING (CRITICAL): Borrowers are verified working professionals and business owners "
            "whose KYC, income, and credit history are strictly verified. NEVER say they 'cannot get bank loans'.\n"
            "• RE-LENDING & COMPOUNDING: If user seeks long-term wealth creation, explain: "
            "'Jab monthly repayments aati hain, aap unhe automatically new loans mein re-invest karke compounding wealth bana sakte hain.'"
        )
    },
    4: {
        "title": "Platform Legitimacy & RBI Trust",
        "directive": (
            "You are in Phase 4: Platform Legitimacy & RBI Trust.\n"
            "• RBI NBFC-P2P: Cymbal Lending / LenDenClub is an RBI-registered NBFC-P2P operating under strict regulatory oversight.\n"
            "• ESCROW ACCOUNT SAFETY: Lender and borrower capital is managed via an independent RBI-regulated Trustee Escrow Account "
            "(ICICI Trusteeship). The platform NEVER holds customer funds directly.\n"
            "• SOCIAL PROOF STATS: 10 years track record, ₹18,000+ crore lent, 40 lakh+ investors, 3 crore+ registered users, "
            "96.73% on-time repayment track record, 4.4 star rating."
        )
    },
    5: {
        "title": "Risk Mitigation & Diversification Math",
        "directive": (
            "You are in Phase 5: Risk Mitigation & Diversification Math.\n"
            "• 100+ BORROWER SPLIT: Capital is NEVER lent to a single individual. An investment of ₹50,000–₹1,00,000 "
            "is automatically fragmented across 100+ vetted borrowers (₹250 to ₹4,000 per loan).\n"
            "• MATHEMATICAL SAFETY: Even if 2–3 borrowers delay or default, the performing 97+ loans comfortably cover the loss. "
            "Quoted returns (12%–24% XIRR) are already net of historical NPA provisions (consistently <4%)."
        )
    },
    6: {
        "title": "Confidence & Readiness Check",
        "directive": (
            "You are in Phase 6: Confidence & Readiness Check.\n"
            "• CHECK COMFORT: Confirm investor clarity on P2P safety and diversification.\n"
            "• ASK PARAMETERS: 'Aap roughly kitne amount se start karne ka soch rahe hain (e.g. ₹25,000, ₹50,000, ₹1 Lakh), "
            "aur kitne time horizon (3, 6, 12 months) ke liye?'"
        )
    },
    7: {
        "title": "Product Recommendation & Mathematical Calculation",
        "directive": (
            "You are in Phase 7: Product Recommendation & Mathematical Calculation.\n"
            "• DETERMINISTIC TOOLS: ALWAYS execute `calculate_stl_returns`, `calculate_mtl_returns`, or `calculate_manual_lending`.\n"
            "• NARRATE EXACT NUMBERS: State calculated profit, maturity value, and monthly EMI payout in Devanagari Hindi.\n"
            "• TENURE CORRELATION: Longer tenure drives higher returns (12M = 21–24% vs 6M = 15–18%).\n"
            "• 9-MONTH STRICT REJECTION: 9 months does NOT exist on the platform. Immediately offer 6M (STL 7M) or 12M (MTL 14M)."
        )
    },
    8: {
        "title": "App & KYC Navigation",
        "directive": (
            "You are in Phase 8: App & KYC Navigation.\n"
            "• 3-STEP INSTANT KYC:\n"
            "  Step 1: PAN card verification (instant identity check).\n"
            "  Step 2: Aadhaar Digilocker OTP verification (address check).\n"
            "  Step 3: Bank account penny-drop linking (repayments flow directly here).\n"
            "• APP FLOW: Open App ➔ Add Money (Escrow UPI/Netbanking) ➔ Select Lumpsum or Live Loans."
        )
    },
    9: {
        "title": "Commitment & Activation Close",
        "directive": (
            "You are in Phase 9: Commitment & Activation Close.\n"
            "• SECURE COMMITMENT: Lock in starting deposit amount, payment method (UPI / Netbanking), and activation date.\n"
            "• ACTIONABLE NEXT STEP: 'Aap aaj hi KYC complete karke ₹50,000 se plan activate kar lijiye, taaki kal se aapka interest accrue hona start ho jaye.'"
        )
    }
}


# Lazy initialized Vertex AI Client for async classification
_AI_CLASSIFIER_CLIENT: Optional[Client] = None

def get_ai_classifier_client() -> Client:
    global _AI_CLASSIFIER_CLIENT
    if _AI_CLASSIFIER_CLIENT is None:
        import os
        from google.genai import Client
        project = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
        location = os.getenv("GCP_LOCATION") or "us-central1"
        _AI_CLASSIFIER_CLIENT = Client(project=project, location=location, vertexai=True)
    return _AI_CLASSIFIER_CLIENT


class ConsultativePhaseTracker:
    """Manages active consultative sales phase and yields prompt cards to Gemini Live."""

    def __init__(self, gemini_service):
        self.gemini_service = gemini_service
        self.current_phase = 1
        self._turn_seq = 0
        self._lock = asyncio.Lock()

    async def transition_to(self, target_phase: int, trigger_reason: str):
        """Transition to a new phase and yield its prompt card."""
        async with self._lock:
            if target_phase == self.current_phase or target_phase not in PHASE_PROMPT_CARDS:
                return

            prev_phase = self.current_phase
            self.current_phase = target_phase
            logger.info(
                f"🔄 [PhaseEngine] State Transition: Phase {prev_phase} ➔ Phase {target_phase} "
                f"({PHASE_PROMPT_CARDS[target_phase]['title']}) | Reason: {trigger_reason}"
            )

            await self._yield_prompt_to_gemini(target_phase, trigger_reason)

    async def _yield_prompt_to_gemini(self, target_phase: int, trigger_reason: str):
        """Send realtime clientContent turn to Gemini Live WebSocket."""
        card = PHASE_PROMPT_CARDS[target_phase]
        directive_text = (
            f"[ACTIVE_PHASE_DIRECTIVE: Phase {target_phase} - {card['title']}]\n"
            f"{card['directive']}\n"
            f"Context: {trigger_reason}\n"
            f"Rule: Always use Devanagari for Hindi words and Latin for English financial terms."
        )

        session = getattr(self.gemini_service, "_session", None)
        if session and hasattr(session, "send_client_content"):
            try:
                logger.info(
                    f"📡 [GeminiLive:send_client_content] Dispatching Realtime Phase Prompt Card to Gemini Live:\n"
                    f"   ├─ target_phase: Phase {target_phase} ({card['title']})\n"
                    f"   ├─ trigger_reason: {trigger_reason}\n"
                    f"   ├─ turn_complete: False (dynamic attention steering without forcing speech)\n"
                    f"   └─ payload:\n"
                    f"      {directive_text}"
                )
                await session.send_client_content(
                    turns=[
                        Content(
                            role="user",
                            parts=[Part(text=directive_text)]
                        )
                    ],
                    turn_complete=False  # Steers model's attention without forcing an immediate reply turn
                )
                logger.info(f"⚡ [PhaseEngine] Prompt card for Phase {target_phase} successfully yielded to Gemini Live.")
            except Exception as e:
                logger.warning(f"[PhaseEngine] Failed to yield prompt via send_client_content: {e}")

    async def _async_ai_classify_intent(self, text: str, initial_phase: int, turn_id: int):
        """Asynchronous Tier-2 Semantic Intent Classification via Gemini Flash AI."""
        try:
            client = get_ai_classifier_client()
            prompt = f"""\
You are an intent classifier for Cymbal Lending P2P voicebot consultative sales funnel.
Current Active Phase: {initial_phase}
User Utterance: "{text}"

Sales Funnel Phases:
1: Time Check & Availability (consent to talk)
2: Discovery & P2P Familiarity (investor background)
3: Educational Pivot (FD 7% vs P2P 18-24% spread)
4: Platform Legitimacy & RBI Trust (RBI NBFC-P2P, ICICI escrow)
5: Risk Mitigation & Diversification (defaults, credit underwriting, ₹500/borrower)
6: Liquidity & Cash Flow (monthly EMI, daily EDI payouts)
7: Return Calculation & Financial Math (exact investment amounts, SIP, tenure)
8: App & KYC Navigation (PAN, Aadhaar OTP, Bank penny drop)
9: Commitment & Activation Close (starting deposit, activation date)

Respond in JSON ONLY:
{{"target_phase": int, "confidence": float, "reason": str}}
"""
            res = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config={"response_mime_type": "application/json"}
                ),
                timeout=2.0
            )
            data = json.loads(res.text)
            target = data.get("target_phase")
            confidence = float(data.get("confidence", 0.0))
            reason = data.get("reason", "Semantic match")

            if self.current_phase == initial_phase and confidence >= 0.75 and target in PHASE_PROMPT_CARDS and target != self.current_phase:
                logger.info(f"🧠 [GeminiFlashAI:IntentClassifier] Classified intent: Phase {target} (Confidence: {confidence:.2f}) | Reason: {reason}")
                await self.transition_to(target, trigger_reason=f"Gemini Flash AI: {reason}")
        except Exception as e:
            logger.debug(f"[PhaseEngine:FlashClassifier] Background classification skipped or timed out: {e}")

    async def handle_user_transcript(self, text: str):
        """Evaluate transcribed user utterance and trigger phase transitions."""
        if not text:
            return
        lower = text.strip().lower()
        initial_phase = self.current_phase

        # ── Tier 1: Fast-Path Rule Check (Instant 0ms) ───────────────
        # Jump to Phase 8: KYC / Document queries (Highest specificity)
        if any(w in lower for w in ["kyc", "documents", "document", "aadhaar", "pan card", "bank account", "penny drop", "digilocker"]):
            await self.transition_to(8, trigger_reason="User asked for KYC / account setup")

        # Jump to Phase 4: RBI / Escrow / Trust / Penalty
        elif any(w in lower for w in ["rbi", "escrow", "safe", "legal", "penalty", "approved", "trustee"]):
            await self.transition_to(4, trigger_reason="User asked about platform safety / RBI")

        # Jump to Phase 5: Risk / Diversification / Default
        elif any(w in lower for w in ["default", "npa", "doob", "risk", "100 borrower", "kitne borrower"]):
            await self.transition_to(5, trigger_reason="User asked about credit risk & diversification")

        # Jump to Phase 7: Returns / Calculations
        elif any(w in lower for w in ["kitna milega", "return kitna", "profit", "monthly payout", "emi kitna", "calculate", "returns"]):
            await self.transition_to(7, trigger_reason="User asked for returns / calculation")

        # Jump to Phase 3: Educational Comparison (FD / Mutual Funds vs P2P)
        elif any(w in lower for w in ["fd", "fixed deposit", "mutual fund", "7%", "18%", "24%", "kaise possible"]):
            await self.transition_to(3, trigger_reason="User compared returns / asked about mechanism")

        # Phase 1 -> 2: User gives consent / confirms availability
        elif self.current_phase == 1 and (
            "हाँ" in text or "हां" in text or
            any(re.search(rf"\b{re.escape(w)}\b", lower) for w in ["haan", "yes", "batao", "bataiye", "sure", "theek hai", "boliye", "ok", "okay"])
        ):
            await self.transition_to(2, trigger_reason="User confirmed availability")

        # Phase 2 -> 3: User shares investment background
        elif self.current_phase == 2 and any(w in lower for w in ["suna hai", "explore", "invest", "pehli baar", "first time", "kabhi invest nahi kiya"]):
            await self.transition_to(3, trigger_reason="User shared P2P familiarity")

        # ── Tier 2: Async Gemini Flash AI Classifier for Subtle Phrasings ─
        if self.current_phase == initial_phase and len(text.strip()) > 6:
            self._turn_seq += 1
            asyncio.create_task(self._async_ai_classify_intent(text, initial_phase, self._turn_seq))


class PhaseTransitionProcessor(FrameProcessor):
    """Pipeline processor that intercepts conversational triggers & tool executions to drive phase transitions."""

    def __init__(self, tracker: ConsultativePhaseTracker):
        super().__init__()
        self.tracker = tracker

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        await super().process_frame(frame, direction)

        # ── Trigger A: Intercept User Speech Transcript ───────────────
        if isinstance(frame, TranscriptionFrame):
            text = (getattr(frame, "text", "") or "").strip()
            if text:
                await self.tracker.handle_user_transcript(text)

        # ── Trigger B: Intercept Functional Tool Executions ───────────
        elif isinstance(frame, FunctionCallResultFrame):
            tool_name = getattr(frame, "function_name", "")
            
            if tool_name in ["calculate_returns", "calculate_stl_returns", "calculate_mtl_returns", "calculate_manual_lending", "calculate_sip_returns"]:
                await self.tracker.transition_to(7, trigger_reason=f"Financial calculation tool executed ({tool_name})")
            elif tool_name in ["get_onboarding_guide", "get_kyc_guidance", "get_app_screen_flow"]:
                await self.tracker.transition_to(8, trigger_reason=f"KYC/App navigation tool executed ({tool_name})")
            elif tool_name == "search_knowledge_base":
                if self.tracker.current_phase < 4:
                    await self.tracker.transition_to(4, trigger_reason="Knowledge base search executed")

        await self.push_frame(frame, direction)
