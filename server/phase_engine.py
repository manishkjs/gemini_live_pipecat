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
import time
from enum import IntEnum
import math
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    FunctionCallResultFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    LLMMessagesAppendFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from google.genai import Client, types
from google.genai.types import Content, Part
from diagnostic_buffer import append_diagnostic_log


# ═══════════════════════════════════════════════════════════════════════
# TIER-2 INTENT CLASSIFIER SYSTEM INSTRUCTION
# ═══════════════════════════════════════════════════════════════════════

INTENT_CLASSIFIER_SYSTEM_PROMPT = """\
You are an expert real-time conversational intent classifier and sales funnel state-transition evaluator for the Cymbal Lending P2P voicebot.

Your objective:
Analyze the chronological multi-turn voice dialogue history and the latest customer utterance to determine the customer's true underlying intent and whether the conversation has progressed to a new sales funnel phase.

Sales Funnel Phases (1-9):
1: Time Check & Availability - Customer availability, callback requests, greetings, or busy signals.
2: Discovery & P2P Familiarity - Customer investment background, awareness of P2P lending, wealth growth vs regular monthly income goals.
3: Educational Pivot & Concept Education - How P2P lending works, disintermediation, comparison with Fixed Deposits (7%) vs P2P returns (18-24%).
4: Platform Legitimacy & RBI Trust - RBI NBFC-P2P registration, ICICI escrow mechanism, 10-year track record, legal compliance.
5: Risk Mitigation, Defaults & Recovery - Borrower credit risk, default handling, 100+ borrower diversification, 96.18% historical recovery rate.
6: Confidence, Readiness Check & Active Objection Overcoming - Customer hesitation, reluctance, saying 'I don't want to invest / not interested / don't want to do it / मुझे नहीं करना', target investment amount, tenure horizon, and risk appetite.
7: Product Recommendation & Mathematical Calculation - Specific returns calculation, rupee profit, monthly payout, tenure options (3M STL 15%, 6M STL 18%, 12M MTL 24%).
8: App & KYC Navigation - PAN card verification, Aadhaar OTP via DigiLocker, Penny-drop bank verification, mobile app steps.
9: Commitment & Activation Close - Deposit commitment confirmation, payment method, activation timeline, concluding remarks.

Classification Invariants:
1. Contextual Coherence: Always evaluate the customer's utterance in the context of the Bot's preceding question (e.g., if Bot asked about P2P awareness in Phase 2 and Customer says "पहली बार सुन रहा हूँ", route to Phase 3 Concept Education).
2. Confidence Calibration: Set confidence >= 0.70 only when the trajectory clearly indicates movement. If ambiguous, stay in the current active phase.
3. Response Format: You MUST return a single JSON object strictly matching this schema:
{
  "target_phase": int,
  "confidence": float,
  "reason": str
}
"""

# Lazy initialized Vertex AI Client for async classification
_AI_CLASSIFIER_CLIENT: Optional[Client] = None

def get_ai_classifier_client() -> Client:
    global _AI_CLASSIFIER_CLIENT
    if _AI_CLASSIFIER_CLIENT is None:
        import os
        from google.genai import Client
        project = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"
        location = os.getenv("INTENT_CLASSIFIER_LOCATION") or "global"
        _AI_CLASSIFIER_CLIENT = Client(project=project, location=location, vertexai=True)
    return _AI_CLASSIFIER_CLIENT

PHASE_PROMPT_CARDS: Dict[int, Dict[str, str]] = {
    1: {
        "title": "Time Check & Availability",
        "directive": (
            "You are in Phase 1: Opening & Availability Check.\n"
            "• Goal: Greet with warmth, introduce yourself as Pragya, and check if user has 2 quick minutes.\n"
            "• Phrasing: 'नमस्ते! मैं प्रज्ञा बात कर रही हूँ Cymbal Lending से। क्या आपके पास 2 मिनट का समय है बात करने के लिए?'\n"
            "• Early Reluctance Handling: If user immediately says 'not interested' or 'I don't want to invest', disarm pressure warmly: 'अरे बिल्कुल कोई pressure नहीं है! आज आपको कुछ भी invest नहीं करना — बस 1 मिनट में समझ लीजिए कि smart investors FD के 6% के मुकाबले 18-24% safe returns कैसे बना रहे हैं। क्या आपने पहले कभी P2P lending के बारे में सुना है?'\n"
            "• Female Verbs & Language Lock: Use 'बता रही हूँ', 'करती हूँ'. Even if user speaks English, reply in friendly Hinglish.\n"
            "• Empathy & Action Filler: Acknowledge user warmly without parroting. If checking records: 'मैं तुरंत platform details confirm करके आपको बताती हूँ, बस एक सेकंड दीजिए...'\n"
            "• Invariant: DO NOT pitch returns until user confirms availability. If busy, secure a friendly callback time."
        )
    },
    2: {
        "title": "Discovery & P2P Familiarity",
        "directive": (
            "You are in Phase 2: Discovery & Goals Profiling.\n"
            "• Goal: Discover if user is new to P2P lending and uncover their wealth goal.\n"
            "• Phrasing: 'पहले यह बताइए — P2P lending के बारे में आपने पहले कभी सुना है, या पहली बार explore कर रहे हैं?'\n"
            "• Female Verbs & Language Lock: Use 'समझती हूँ', 'पूछ रही हूँ', 'मदद करूँगी'. Reply in Hinglish.\n"
            "• Empathy & Action Filler: Relate to their investment background naturally without repeating their words. If looking up facts: 'मैं तुरंत exact platform details check करके आपको समझाती हूँ, बस एक छोटा सा सेकंड दीजिए...'\n"
            "• Rule: Keep it relaxed and fun. Do NOT quote return % or ask investment amounts yet."
        )
    },
    3: {
        "title": "Concept Education & Disintermediation",
        "directive": (
            "You are in Phase 3: Concept Education (Asset Class).\n"
            "• Goal: Demystify P2P lending with playful, crystal-clear wit (18%–24% p.a. returns).\n"
            "• Witty Analogy: 'हाहा, देखिए सीधा सा फंडा है — जैसे बैंक हमसे 6% पे FD लेता है और 20% पे लोन बांट के मुनाफा कमाता है, यहाँ आप सीधे बैंक बन जाते हैं! बीच का सारा बैंक मार्जिन सीधे आपकी जेब में 18% से 24% रिटर्न के रूप में आता है।'\n"
            "• Female Verbs & Language Lock: Use 'समझाती हूँ', 'बता रही हूँ', 'देती हूँ'. Reply in Hinglish.\n"
            "• Empathy & Action Filler: Relate to their FD/bank comparisons warmly. If querying knowledge base: 'मैं तुरंत verified lending facts निकालती हूँ, बस एक सेकंड hold कीजिएगा...'\n"
            "• Highlight: Borrowers are pre-vetted salaried professionals with KYC & income checks."
        )
    },
    4: {
        "title": "Platform Legitimacy & RBI Trust",
        "directive": (
            "You are in Phase 4: Platform Legitimacy & RBI Trust.\n"
            "• Goal: Build rock-solid confidence with a warm smile.\n"
            "• Direct Answer: 'जी बिल्कुल! Cymbal Lending एक RBI-registered NBFC-P2P platform है। आपका सारा पैसा ICICI Trustee Escrow Account के through सुरक्षित रूप से मैनेज होता है — platform खुद पैसे hold नहीं करता। 10 साल का भरोसेमंद ट्रैक रिकॉर्ड है!'\n"
            "• Female Verbs & Language Lock: Use 'बताती हूँ', 'देती हूँ', 'करती हूँ'. Reply in Hinglish.\n"
            "• Empathy & Action Filler: Validate trust concerns genuinely ('safety समझना सबसे ज़रूरी है!'). Before search_knowledge_base: 'मैं तुरंत live RBI registration और escrow records confirm करके बताती हूँ, बस मुझे एक सेकंड दीजिए...'\n"
            "• Knowledge Base: You can query search_knowledge_base for exact platform facts, certifications, or details whenever needed."
        )
    },
    5: {
        "title": "Risk Mitigation & Diversification Math",
        "directive": (
            "You are in Phase 5: Risk Mitigation & Diversification.\n"
            "• Goal: Explain safety layers with everyday relatable clarity.\n"
            "• Clear Answer: 'देखिए, रिस्क को मैनेज करने का हमारा तरीका बहुत स्मार्ट है — आपका ₹50,000 किसी एक इंसान को नहीं, बल्कि 100 से ज़्यादा vetted borrowers में split होता है। अगर 1-2 delay भी करें, तो बाकी 98 borrowers का interest आपका पूरा profit और पूंजी सुरक्षित रखता है!'\n"
            "• Female Verbs & Language Lock: Use 'समझा रही हूँ', 'देती हूँ', 'करूँगी'. Reply in Hinglish.\n"
            "• Empathy & Action Filler: Acknowledge risk questions with confidence. Before search_knowledge_base: 'मैं तुरंत recovery team और NPA metrics check करके आपको accurate picture बताती हूँ, बस एक सेकंड दीजिए...'\n"
            "• Quoted returns (18%–24%) are already net of historical NPA provisions."
        )
    },
    6: {
        "title": "Confidence, Readiness & Objection Overcoming",
        "directive": (
            "You are in Phase 6: Confidence, Readiness Check & Active Objection Overcoming.\n"
            "• Goal: If customer hesitates, expresses doubt, or says 'I don't want to do it / मुझे नहीं करना / not interested', NEVER surrender or hang up! Actively push and uncover the root cause using the 3-Step formula:\n"
            "  1) Disarm Pressure: 'अरे बिल्कुल! आपको आज ₹1 भी लगाने की कोई जल्दी नहीं है — zero pressure!'\n"
            "  2) Pitch ₹250 Micro-Test: 'लेकिन क्या आप जानते हैं कि Cymbal Lending पर आपको लाखों लगाने की ज़रूरत नहीं है — आप सिर्फ ₹250 या ₹5,000 की छोटी सी रकम से test करके live monthly interest payout देख सकते हैं!'\n"
            "  3) Direct Root-Cause Probe: 'वैसे क्या मैं honestly जान सकती हूँ कि main hesitation किस बात को लेकर है — क्या safety और risk का concern है, या liquidity का?'\n"
            "• If user is comfortable: Ask their target amount (₹25k, ₹50k, ₹1L) and tenure (6M or 12M).\n"
            "• Female Verbs & Language Lock: Use 'पूछ रही हूँ', 'समझती हूँ', 'बताती हूँ'. Reply in Hinglish.\n"
            "• Empathy & Action Filler: Encourage their investment readiness warmly (DO NOT parrot amounts verbatim). If looking up options: 'मैं तुरंत best suitable plans check करके बताती हूँ, बस एक सेकंड दीजिए...'"
        )
    },
    7: {
        "title": "Product Recommendation & Mathematical Calculation",
        "directive": (
            "You are in Phase 7: Product Recommendation & Calculation.\n"
            "• Goal: Deliver exact deterministic calculations with high energy.\n"
            "• Mandatory 2-Part Spoken Preamble BEFORE Tool Call:\n"
            "  1) Non-Parroting Empathy: Warm reaction to the user's wealth goal (DO NOT literally repeat the user's words! E.g., 'अरे वाह, wealth grow करने का यह बहुत ही smart decision है!').\n"
            "  2) Substantial Spoken Action Filler: Multi-phrase natural filler ('मैं तुरंत system में calculation run करके आपके लिए exact monthly payout और net profit calculate करके बताती हूँ, बस एक सेकंड दीजिए...').\n"
            "• Female Verbs & Language Lock: Use 'बता रही हूँ', 'calculate करती हूँ', 'दिखाती हूँ'. Reply in Hinglish.\n"
            "• 9-Month Rejection: If user asks 9M, you can call calculate_returns(amount, tenure_months=9) or immediately speak: 'हाहा, 9 महीने का कोई प्लान नहीं है — आप 6 महीने (18% XIRR) या 12 महीने (24% XIRR) चुन सकते हैं!' Never pause or stay silent.\n"
            "• Narrate exact profit and monthly payout clearly in Devanagari Hindi."
        )
    },
    8: {
        "title": "App & KYC Navigation",
        "directive": (
            "You are in Phase 8: App & KYC Navigation.\n"
            "• Goal: Guide 3-step digital onboarding clearly in speech, or query search_knowledge_base for detailed document/app rules.\n"
            "• 3-Step Instant KYC: 'KYC तो बस 2 मिनट का काम है — 1) Instant PAN check, 2) Aadhaar Digilocker OTP, और 3) Bank linking। बस ऐप खोलिए, KYC कम्प्लीट कीजिए और तुरंत शुरू हो जाइए!'\n"
            "• Female Verbs & Language Lock: Use 'गाइड करती हूँ', 'बता रही हूँ', 'मदद करूँगी'. Reply in Hinglish.\n"
            "• Empathy & Action Filler: Empathize with digital onboarding simplicity. Before search_knowledge_base: 'मैं तुरंत exact document और KYC guidelines verify करके आपको बताती हूँ, बस एक छोटा सा पल दीजिए...'"
        )
    },
    9: {
        "title": "Commitment & Activation Close",
        "directive": (
            "You are in Phase 9: Commitment & Activation Close (Call Concluding / Final Validation).\n"
            "• Goal: Conclude warmly and playfully validate next steps.\n"
            "• Context-Aware Validation: Dynamically remind the customer of whatever specific plan, return calculation, or account setup was explored in this session, and ask if they are ready to activate today or when they prefer a quick follow-up.\n"
            "• Female Verbs & Language Lock: Use 'धन्यवाद करती हूँ', 'बात कर रही थी', 'मदद करूँगी'. Reply in Hinglish.\n"
            "• Empathy & Action Filler: Celebrate their smart decision or validate their preference warmly with natural conversational flow (no rigid echo).\n"
            "• Closing Discipline: If confirmed, celebrate warmly ('अरे वाह, welcome to smart investing!'). If they need time, close politely with zero loops back to opening greetings."
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
        location = os.getenv("INTENT_CLASSIFIER_LOCATION") or "global"
        _AI_CLASSIFIER_CLIENT = Client(project=project, location=location, vertexai=True)
    return _AI_CLASSIFIER_CLIENT


class ConsultativePhaseTracker:
    """Manages active consultative sales phase and yields prompt cards to Gemini Live."""

    def __init__(self, gemini_service, enable_client_content: bool = True):
        self.gemini_service = gemini_service
        self.current_phase = 1
        self._turn_seq = 0
        self._is_bot_speaking = False
        self._pending_phase: Optional[int] = None
        self._pending_reason: Optional[str] = None
        self._lock = asyncio.Lock()
        self.enable_client_content = enable_client_content
        self.session_transcript: List[Dict[str, str]] = []

    def record_turn(self, role: str, text: str):
        """Records user or assistant dialogue turns into the session transcript."""
        if text and text.strip():
            self.session_transcript.append({"role": role, "text": text.strip()})

    def set_bot_speaking(self, speaking: bool):
        self._is_bot_speaking = speaking

    async def on_bot_stopped_speaking(self):
        """Called when bot finishes speaking. Safely flushes pending prompt card and copilot hints without audio interruption."""
        self._is_bot_speaking = False
        if self._pending_phase is not None:
            phase = self._pending_phase
            reason = self._pending_reason
            self._pending_phase = None
            self._pending_reason = None
            logger.info(f"⚡ [PhaseEngine] Delivering queued Phase {phase} Prompt Card now that bot has finished speaking.")
            await self._yield_prompt_to_gemini(phase, reason)

        if getattr(self, "_pending_hint", None) is not None:
            hint = self._pending_hint
            self._pending_hint = None
            logger.info("⚡ [PhaseEngine] Delivering queued Copilot hint now that bot has finished speaking.")
            await self._dispatch_raw_system_content(hint, tag="QueuedCopilotHint")

    async def yield_copilot_hint(self, hint_payload: str) -> bool:
        """Safely dispatches a Copilot hint respecting bot speaking state to prevent mid-speech VAD barge-in."""
        if not self.enable_client_content:
            return False

        if self._is_bot_speaking:
            logger.info("⏳ [PhaseEngine] Bot is actively speaking. Queuing Copilot hint for delivery after speech.")
            self._pending_hint = hint_payload
            return True

        return await self._dispatch_raw_system_content(hint_payload, tag="CopilotHint")

    async def _dispatch_raw_system_content(self, text: str, tag: str = "SystemContent") -> bool:
        """Dispatches a raw system content WebSocket turn to Gemini Live."""
        session = getattr(self.gemini_service, "_session", None)
        if session and hasattr(session, "send_client_content"):
            try:
                await session.send_client_content(
                    turns=[Content(role="system", parts=[Part(text=text)])],
                    turn_complete=False
                )
                logger.info(f"⚡ [PhaseEngine] Dispatched {tag} to Gemini Live.")
                return True
            except Exception as e:
                logger.warning(f"[PhaseEngine] Failed to dispatch {tag}: {e}")
        return False

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

            if self._is_bot_speaking:
                logger.info(f"⏳ [PhaseEngine] Bot is actively speaking. Queuing Phase {target_phase} prompt card for delivery after speech.")
                self._pending_phase = target_phase
                self._pending_reason = trigger_reason
            else:
                await self._yield_prompt_to_gemini(target_phase, trigger_reason)

    async def _yield_prompt_to_gemini(self, target_phase: int, trigger_reason: str):
        """Send realtime clientContent turn to Gemini Live WebSocket."""
        card = PHASE_PROMPT_CARDS[target_phase]
        directive_text = (
            f"[ACTIVE_PHASE: Phase {target_phase} - {card['title']}]\n"
            f"{card['directive']}"
        )

        logger.info(
            f"📋 [PhaseEngine:ActivePromptCard] Phase {target_phase} ({card['title']}) Context Directive:\n"
            f"   ├─ trigger_reason: {trigger_reason}\n"
            f"   └─ payload:\n"
            f"      {directive_text}"
        )

        if self.enable_client_content:
            session = getattr(self.gemini_service, "_session", None)
            if session and hasattr(session, "send_client_content"):
                try:
                    logger.info(f"📡 [GeminiLive:send_client_content] Dispatching WebSocket turn to Gemini Live for Phase {target_phase}")
                    await session.send_client_content(
                        turns=[
                            Content(
                                role="system",
                                parts=[Part(text=directive_text)]
                            )
                        ],
                        turn_complete=False
                    )
                    logger.info(f"⚡ [PhaseEngine] Prompt card for Phase {target_phase} successfully yielded to Gemini Live.")
                except Exception as e:
                    logger.warning(f"[PhaseEngine] Failed to yield prompt via send_client_content: {e}")

    async def yield_hydrated_context(self, user_id: str, profile: Dict[str, Any]):
        """Yield hydrated user memories and facts as a dynamic clientContent frame to Gemini Live."""
        facts = profile.get("facts", {})
        recent_mems = profile.get("recent_memories", [])
        episodic_mems = profile.get("episodic_memories", [])
        facts_summary = ", ".join(f"{k}: {v}" for k, v in facts.items()) if facts else "None"

        mem_items = []
        if recent_mems and isinstance(recent_mems, list):
            for m in recent_mems[:3]:
                if isinstance(m, dict):
                    ts = m.get("created_at") or m.get("timestamp") or ""
                    content = m.get("content") or m.get("summary") or ""
                    ts_prefix = f"[{ts[:10]}] " if ts else ""
                    if content:
                        mem_items.append(f"{ts_prefix}{content}")
                elif isinstance(m, str) and m.strip():
                    mem_items.append(m.strip())
        elif episodic_mems and isinstance(episodic_mems, list):
            for m in episodic_mems[:3]:
                if isinstance(m, str) and m.strip():
                    mem_items.append(m.strip())
                elif isinstance(m, dict):
                    content = m.get("content") or m.get("summary") or str(m)
                    if content:
                        mem_items.append(content)

        mem_summary = "; ".join(mem_items) if mem_items else "None"

        directive_text = (
            f"[RETURNING_USER_CONTEXT: User '{user_id}']\n"
            f"Known Investor Facts: {facts_summary}\n"
            f"Previous Discussion History: {mem_summary}\n"
            f"Directive: Acknowledge the user warmly by name. Proactively reference their known preferences or past discussions where relevant."
        )

        logger.info(
            f"📋 [PhaseEngine:ReturningUserContext] Hydrated Context for '{user_id}':\n"
            f"   └─ payload:\n"
            f"      {directive_text}"
        )

        if self.enable_client_content:
            session = getattr(self.gemini_service, "_session", None)
            if session and hasattr(session, "send_client_content"):
                try:
                    logger.info(f"📡 [GeminiLive:send_client_content] Dispatching WebSocket turn for {user_id}")
                    await session.send_client_content(
                        turns=[
                            Content(
                                role="system",
                                parts=[Part(text=directive_text)]
                            )
                        ],
                        turn_complete=False
                    )
                    logger.info(f"⚡ [PhaseEngine] Hydrated profile for {user_id} successfully yielded to Gemini Live.")
                except Exception as e:
                    logger.warning(f"[PhaseEngine] Failed to yield user context via send_client_content: {e}")


    async def _async_ai_classify_intent(
        self,
        text: str,
        initial_phase: int,
        turn_id: int,
        history: Optional[List[Dict[str, str]]] = None,
    ):
        """Asynchronous Tier-2 Semantic Intent Classification via Gemini Flash AI with full session dialogue context."""
        try:
            client = get_ai_classifier_client()
            
            # Format dialogue context till this point (last 10 turns)
            history_to_format = history if history is not None else self.session_transcript
            formatted_turns = []
            for turn in history_to_format[-10:]:
                role_label = "Bot" if turn.get("role") in ["assistant", "bot", "model"] else "Customer"
                turn_txt = (turn.get("text") or "").strip()
                if turn_txt:
                    formatted_turns.append(f"{role_label}: \"{turn_txt}\"")
            dialogue_context = "\n".join(formatted_turns) if formatted_turns else f"Customer: \"{text}\""

            phase_card = PHASE_PROMPT_CARDS.get(initial_phase, {})
            phase_title = phase_card.get("title", f"Phase {initial_phase}")

            user_query = f"""\
Current Active Funnel Phase: Phase {initial_phase} ({phase_title})

Conversation Dialogue Till This Point (in chronological order):
{dialogue_context}

Latest Customer Utterance: "{text}"

Evaluate the full dialogue context and return the target phase decision in JSON.
"""
            classifier_model = os.getenv("INTENT_CLASSIFIER_MODEL", "gemini-3.5-flash-lite")
            res = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=classifier_model,
                    contents=user_query,
                    config=types.GenerateContentConfig(
                        system_instruction=INTENT_CLASSIFIER_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                    ),
                ),
                timeout=4.0
            )
            if hasattr(res, "usage_metadata") and res.usage_metadata:
                um = res.usage_metadata
                prompt_tok = getattr(um, "prompt_token_count", 0)
                cand_tok = getattr(um, "candidates_token_count", 0)
                total_tok = getattr(um, "total_token_count", 0)
                logger.info(f"📊 [Tier-2:Gemini 3.5 Flash Lite Usage] Input: {prompt_tok} tok + Output: {cand_tok} tok = {total_tok} total")

            data = json.loads(res.text)
            target = data.get("target_phase")
            confidence = float(data.get("confidence", 0.0))
            reason = data.get("reason", "Semantic match")

            if self.current_phase == initial_phase and confidence >= 0.70 and target in PHASE_PROMPT_CARDS and target != self.current_phase:
                target_title = PHASE_PROMPT_CARDS[target]["title"]
                logger.info(
                    f"\n════════════════════════════════════════════════════════════════════════\n"
                    f"🧠 [DECISION: TIER-2 GEMINI 3.5 FLASH LITE]\n"
                    f"   ├─ Utterance: '{text}'\n"
                    f"   ├─ State Transition: Phase {initial_phase} ➔ Phase {target} ({target_title})\n"
                    f"   ├─ AI Confidence: {confidence:.2f}\n"
                    f"   └─ Semantic Rationale: {reason}\n"
                    f"════════════════════════════════════════════════════════════════════════"
                )
                append_diagnostic_log("🧠 AI Decision (Gemini 3.5)", f"Phase {initial_phase} ➔ Phase {target} ({target_title}) | Conf: {confidence:.2f} | Reason: {reason}")
                await self.transition_to(target, trigger_reason=f"Gemini 3.5 Flash Lite: {reason}")
            else:
                logger.info(f"💤 [Tier-2:Gemini 3.5 Flash Lite] Kept Phase {initial_phase} (Evaluated Target: {target}, Conf: {confidence:.2f}) | Reason: {reason}")
        except Exception as e:
            logger.debug(f"[PhaseEngine:FlashClassifier] Background classification note: {e}")

    async def handle_user_transcript(self, text: str, history: Optional[List[Dict[str, str]]] = None):
        """Evaluate transcribed user utterance and trigger phase transitions."""
        if not text:
            return
        self.record_turn("user", text)
        lower = text.strip().lower()
        initial_phase = self.current_phase
        matched_rule = None
        target_tier1 = None

        # ── Tier 1: Fast-Path Rule Check (Instant 0ms) ───────────────
        # Jump to Phase 6: Mid-call disinterest, reluctance, objection, or 'don't want to do it / phone rakho'
        if self.current_phase > 1 and (
            any(w in lower for w in [
                "nahi karna", "nahi invest", "dont want", "don't want", "not interested", "dont think", "don't think",
                "phone rakho", "rehne do", "mood nahi", "man nahi", "no interest", "mat batao", "ruk jao", "disconnect"
            ]) or any(w in text for w in [
                "नहीं करना", "इन्वेस्ट नहीं करना", "फोन रखो", "फ़ोन रखो", "रहने दो", "मूड नहीं", "मन नहीं", "मत बताओ", "रुको"
            ])
        ):
            target_tier1 = 6
            matched_rule = "User expressed disinterest / reluctance -> trigger Phase 6 Objection Overcoming"

        # Jump to Phase 9: Farewells, Wrap-Up, Bye, Boy, Alvida, Concluding (when call has already started)
        elif self.current_phase > 1 and (
            any(re.search(rf"\b{re.escape(w)}\b", lower) for w in [
                "bye", "boy", "by", "alvida", "thank you", "thanks", "chalo bye", "ok bye",
                "theek hai bye", "wrap up", "chalta hu", "chalti hu", "rakhta hu", "rakhti hu",
                "baad mein baat", "call you later", "later"
            ]) or any(w in text for w in ["बाय", "अलविदा", "थैंक यू", "धन्यवाद", "चलो बाय", "ठीक है बाय", "बाद में बात"])
        ):
            target_tier1 = 9
            matched_rule = "User wrapping up call / farewell -> validate commitment & close"

        # Jump to Phase 1: Disinterest / Callback request right at the start of Turn 1
        elif self.current_phase == 1 and any(w in lower or w in text for w in ["इंटरेस्ट नहीं", "interest nahi", "baad mein", "बाद में", "busy", "बिजी", "not interested", "nahi chahiye", "नहीं चाहिए", "call back", "कॉल बैक"]):
            target_tier1 = 1
            matched_rule = "User indicated busy / not interested on initial turn"

        # Jump to Phase 8: KYC / Document queries / Escrow deposit flow
        elif any(w in lower or w in text for w in ["kyc", "केवाईसी", "documents", "डॉक्यूमेंट", "aadhaar", "आधार", "pan card", "पैन कार्ड", "bank account", "बैंक खाता", "penny drop", "पेनी ड्रॉप", "digilocker", "डिजीलॉकर", "ब्रांच जाना", "branch visit", "एस्क्रो में", "पैसे कैसे ऐड", "add funds", "डिपॉजिट कैसे"]):
            target_tier1 = 8
            matched_rule = "User asked for KYC / deposit navigation"

        # Jump to Phase 4: RBI / Escrow / Trust / Penalty
        elif any(w in lower or w in text for w in ["rbi", "आरबीआई", "escrow", "एस्क्रो", "safe", "legal", "लीगल", "penalty", "approved", "trustee"]):
            target_tier1 = 4
            matched_rule = "User asked about platform safety / RBI"

        # Jump to Phase 5: Risk / Diversification / Default / Doesn't pay back
        elif any(w in lower or w in text for w in [
            "default", "डिफ़ॉल्ट", "npa", "एनपीए", "doob", "डूब", "risk", "रिस्क", "100 borrower", "kitne borrower",
            "doesn't pay", "doesnt pay", "wapas na", "wapas nahi", "वापस नहीं", "paisa doob", "पैसा डूब",
            "bhag gaya", "भाग गया", "na de", "delay", "kya hoga agar", "recovery", "रिकवरी"
        ]):
            target_tier1 = 5
            matched_rule = "User asked about credit risk, defaults & recovery"

        # Jump to Phase 7: Returns / Calculations
        elif any(w in lower or w in text for w in ["kitna milega", "कितना मिलेगा", "फायदा होगा", "return kitna", "profit", "monthly payout", "emi kitna", "calculate", "returns"]):
            target_tier1 = 7
            matched_rule = "User asked for returns / calculation"

        # Jump to Phase 3: Educational Comparison (FD / Mutual Funds vs P2P)
        elif any(w in lower or w in text for w in ["fd", "fixed deposit", "mutual fund", "7%", "8%", "6%", "बैंक में", "bank me", "18%", "24%", "kaise possible"]):
            target_tier1 = 3
            matched_rule = "User compared returns / asked about mechanism"

        # Phase 1 -> 2: User gives consent / confirms availability
        elif self.current_phase == 1 and (
            "हाँ" in text or "हां" in text or
            any(re.search(rf"\b{re.escape(w)}\b", lower) for w in ["haan", "yes", "batao", "bataiye", "sure", "theek hai", "boliye", "ok", "okay"])
        ):
            target_tier1 = 2
            matched_rule = "User confirmed availability / conversational consent"

        # Phase 2 -> 3: User shares investment background
        elif self.current_phase == 2 and any(w in lower or w in text for w in ["suna hai", "explore", "invest", "pehli baar", "पहली बार", "first time", "kabhi invest nahi kiya"]):
            target_tier1 = 3
            matched_rule = "User shared P2P familiarity background"

        if target_tier1 is not None and target_tier1 != self.current_phase:
            target_title = PHASE_PROMPT_CARDS[target_tier1]["title"]
            logger.info(
                f"\n════════════════════════════════════════════════════════════════════════\n"
                f"⚡ [DECISION: TIER-1 REGEX FAST-PATH (0ms)]\n"
                f"   ├─ Utterance: '{text}'\n"
                f"   ├─ State Transition: Phase {self.current_phase} ➔ Phase {target_tier1} ({target_title})\n"
                f"   └─ Matched Pattern: {matched_rule}\n"
                f"════════════════════════════════════════════════════════════════════════"
            )
            append_diagnostic_log("⚡ Fast-Path Decision (Tier-1 Regex)", f"Phase {self.current_phase} ➔ Phase {target_tier1} ({target_title}) | Rule: {matched_rule}")
            await self.transition_to(target_tier1, trigger_reason=f"Tier-1 Regex: {matched_rule}")
            return

        # ── Tier 2: Async Gemini 3.5 Flash Lite AI Classifier for Subtle Phrasings ─
        if self.current_phase == initial_phase and len(text.strip()) > 4:
            logger.info(f"🔍 [PhaseEngine:Classifier] Tier-1 Regex: No match for '{text}'. Dispatching to TIER-2 (Gemini 3.5 Flash Lite async with dialogue history)...")
            self._turn_seq += 1
            asyncio.create_task(self._async_ai_classify_intent(text, initial_phase, self._turn_seq, history=history))


class PhaseTransitionProcessor(FrameProcessor):
    """Pipeline processor that intercepts conversational triggers & tool executions to drive phase transitions."""

    def __init__(self, tracker: ConsultativePhaseTracker):
        super().__init__()
        self.tracker = tracker

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        await super().process_frame(frame, direction)

        # Track bot speaking state to prevent mid-turn WebSocket interruption
        if isinstance(frame, (BotStartedSpeakingFrame, TTSStartedFrame)):
            self.tracker.set_bot_speaking(True)

        elif isinstance(frame, (BotStoppedSpeakingFrame, TTSStoppedFrame)):
            await self.tracker.on_bot_stopped_speaking()

        # ── Trigger A: Intercept User Speech Transcript ───────────────
        elif isinstance(frame, TranscriptionFrame):
            text = (getattr(frame, "text", "") or "").strip()
            if text:
                await self.tracker.handle_user_transcript(text)

        # ── Trigger B: Intercept Functional Tool Executions ───────────
        elif isinstance(frame, FunctionCallResultFrame):
            tool_name = getattr(frame, "function_name", "")
            
            if tool_name in ["calculate_returns", "calculate_stl_returns", "calculate_mtl_returns", "calculate_manual_lending", "calculate_sip_returns"]:
                logger.info(f"🛠️ [DECISION: TOOL EXECUTION] Tool '{tool_name}' triggered transition ➔ Phase 7 (Returns & Math)")
                append_diagnostic_log("🛠️ Tool Decision", f"Tool '{tool_name}' ➔ Phase 7 (Returns & Math)")
                await self.tracker.transition_to(7, trigger_reason=f"Financial calculation tool executed ({tool_name})")
            elif tool_name in ["get_onboarding_guide", "get_kyc_guidance", "get_app_screen_flow"]:
                logger.info(f"🛠️ [DECISION: TOOL EXECUTION] Tool '{tool_name}' triggered transition ➔ Phase 8 (App & KYC)")
                append_diagnostic_log("🛠️ Tool Decision", f"Tool '{tool_name}' ➔ Phase 8 (App & KYC)")
                await self.tracker.transition_to(8, trigger_reason=f"KYC/App navigation tool executed ({tool_name})")
            elif tool_name == "search_knowledge_base":
                if self.tracker.current_phase < 4:
                    logger.info(f"🛠️ [DECISION: TOOL EXECUTION] Tool '{tool_name}' triggered transition ➔ Phase 4 (Platform Trust)")
                    append_diagnostic_log("🛠️ Tool Decision", f"Tool '{tool_name}' ➔ Phase 4 (Platform Trust)")
                    await self.tracker.transition_to(4, trigger_reason="Knowledge base search executed")

        await self.push_frame(frame, direction)


# ═══════════════════════════════════════════════════════════════════════
# 8 DECISION STAGES & TRANSITION GATES (Milestone M3)
# ═══════════════════════════════════════════════════════════════════════

class DecisionStage(IntEnum):
    """8 Decision Stages tracking investor psychological readiness."""
    UNAWARE = 1
    CURIOUS = 2
    INTERESTED = 3
    EVALUATING = 4
    HESITANT = 5
    READY = 6
    COMMITTED = 7
    DISENGAGED = 8


class StageTransitionManager:
    """Manages progression across 8 Decision Stages with strict business & hysteresis gates."""

    MAX_FORWARD_SKIP: int = 3
    MAX_CLOSE_ATTEMPTS: int = 2
    HYSTERESIS_COOLDOWN_TURNS: int = 2
    STALENESS_THRESHOLD_TURNS: int = 5

    def __init__(self, initial_stage: DecisionStage = DecisionStage.UNAWARE):
        self.current_stage: DecisionStage = initial_stage
        self._close_attempts: int = 0
        self._has_recommendation: bool = False
        self._hesitant_turn: Optional[int] = None
        self._stage_entry_turn: int = 1
        self._last_turn: int = 1

    @property
    def close_attempts(self) -> int:
        return self._close_attempts

    @close_attempts.setter
    def close_attempts(self, value: int) -> None:
        self._close_attempts = value

    @property
    def hesitant_entered_turn(self) -> Optional[int]:
        return self._hesitant_turn

    @hesitant_entered_turn.setter
    def hesitant_entered_turn(self, value: Optional[int]) -> None:
        self._hesitant_turn = value

    def _get_amount_from_fact_store(self, fact_store: Any) -> Optional[float]:
        if fact_store is None:
            return None
        val = None
        if isinstance(fact_store, dict):
            val = fact_store.get("amount")
        elif hasattr(fact_store, "get_fact") and callable(fact_store.get_fact):
            val = fact_store.get_fact("amount")
        elif hasattr(fact_store, "amount"):
            val = getattr(fact_store, "amount")
        elif hasattr(fact_store, "facts") and isinstance(fact_store.facts, dict):
            val = fact_store.facts.get("amount")

        if val is None:
            return None
        try:
            f_val = float(val)
            if math.isnan(f_val) or math.isinf(f_val) or f_val <= 0:
                return None
            return f_val
        except (ValueError, TypeError):
            return None

    def can_transition(
        self,
        from_stage: DecisionStage,
        to_stage: DecisionStage,
        fact_store: Any = None,
        user_intent: Optional[str] = None,
        turn_id: int = 1,
    ) -> Tuple[bool, str]:
        """Evaluates whether transitioning from from_stage to to_stage is permitted."""
        if from_stage == to_stage:
            return True, "No stage change"

        delta = int(to_stage) - int(from_stage)

        # 1. Stage Skip Guard (max 3 forward jumps unless explicit READY intent)
        if delta > self.MAX_FORWARD_SKIP:
            is_explicit_ready = (
                user_intent is not None
                and (
                    (isinstance(user_intent, str) and user_intent.strip().upper() == "READY")
                    or (isinstance(user_intent, DecisionStage) and user_intent == DecisionStage.READY)
                )
            )
            if not is_explicit_ready:
                return False, f"Skip Guard: Forward jump of {delta} stages blocked without explicit READY intent"

        # 2. Hysteresis Guard (cooldown when in or transitioning from HESITANT)
        if self._hesitant_turn is not None and to_stage in (DecisionStage.EVALUATING, DecisionStage.COMMITTED, DecisionStage.READY):
            elapsed = turn_id - self._hesitant_turn
            cooldown_active = (elapsed <= self.HYSTERESIS_COOLDOWN_TURNS) if self.current_stage == DecisionStage.HESITANT else (elapsed < self.HYSTERESIS_COOLDOWN_TURNS)
            if cooldown_active:
                return False, f"Hysteresis Guard: Hysteresis active: In {self.HYSTERESIS_COOLDOWN_TURNS}-turn cooldown from HESITANT ({elapsed} elapsed)"

        # 3. COMMITTED Gate (requires valid positive amount in FactStore)
        if to_stage == DecisionStage.COMMITTED:
            amount = self._get_amount_from_fact_store(fact_store)
            if amount is None or amount <= 0:
                return False, "COMMITTED Gate: Missing or invalid investment amount in FactStore"

        # 4. Recommendation Gate when advancing to READY
        if to_stage == DecisionStage.READY:
            if fact_store is not None:
                amount = self._get_amount_from_fact_store(fact_store)
                if amount is not None and amount <= 0:
                    return False, "Recommendation Gate: Invalid investment amount in FactStore"

        return True, "Transition allowed"

    def can_recommend_product(self, fact_store: Any = None) -> Tuple[bool, str]:
        """Recommendation Gate: requires investment amount in FactStore."""
        amount = self._get_amount_from_fact_store(fact_store)
        if amount is None or amount <= 0:
            return False, "Recommendation Gate: Cannot recommend product without amount in FactStore"
        return True, "Recommendation allowed"

    def record_recommendation(self) -> None:
        """Marks that a product recommendation has been presented."""
        self._has_recommendation = True

    def can_attempt_close(self) -> Tuple[bool, str]:
        """Close Limiter Gate: requires prior recommendation and max 2 attempts."""
        if not self._has_recommendation:
            return False, "Close Limiter Gate: Prior product recommendation required before close"
        if self._close_attempts >= self.MAX_CLOSE_ATTEMPTS:
            return False, f"Close Limiter Gate: Maximum close attempts ({self.MAX_CLOSE_ATTEMPTS}) reached"
        return True, "Close attempt allowed"

    def record_close_attempt(self) -> int:
        """Increments and returns total close attempts."""
        self._close_attempts += 1
        return self._close_attempts

    def transition_to(
        self,
        to_stage: DecisionStage,
        fact_store: Any = None,
        user_intent: Optional[str] = None,
        turn_id: int = 1,
    ) -> bool:
        """Executes a decision stage transition if permitted by all gates."""
        allowed, _ = self.can_transition(
            self.current_stage, to_stage, fact_store, user_intent, turn_id
        )
        if not allowed:
            return False

        if to_stage == DecisionStage.HESITANT:
            self._hesitant_turn = turn_id
        elif self._hesitant_turn is not None and (turn_id - self._hesitant_turn) > self.HYSTERESIS_COOLDOWN_TURNS:
            self._hesitant_turn = None

        if to_stage != self.current_stage:
            self.current_stage = to_stage
            self._stage_entry_turn = turn_id

        self._last_turn = turn_id
        return True

    def check_staleness(self, current_turn: int) -> bool:
        """Checks if current stage has remained unchanged for >= STALENESS_THRESHOLD_TURNS."""
        stagnant_turns = current_turn - self._stage_entry_turn
        return stagnant_turns >= self.STALENESS_THRESHOLD_TURNS

    def auto_advance(self, current_turn: int) -> Optional[DecisionStage]:
        """Advances stage by +1 (up to DISENGAGED) if staleness threshold exceeded."""
        if self.check_staleness(current_turn):
            next_val = min(int(self.current_stage) + 1, int(DecisionStage.DISENGAGED))
            next_stage = DecisionStage(next_val)
            self.current_stage = next_stage
            self._stage_entry_turn = current_turn
            return next_stage
        return None


# ═══════════════════════════════════════════════════════════════════════
# NUMERIC CONSISTENCY LEDGER (Milestone M3)
# ═══════════════════════════════════════════════════════════════════════

class NumericLedger:
    """Tracks bot-stated return %, maturity values, and EMI payouts to guarantee cross-turn numeric consistency."""

    MAX_CEILING_INR: float = 5000000.0  # ₹50 Lakhs RBI platform ceiling

    def __init__(self):
        self._quotes: List[Dict[str, Any]] = []

    def record_quote(
        self,
        principal: float,
        tenure_months: int,
        xirr_pct: float,
        profit: float,
        maturity_amount: float,
        monthly_emi: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Records a calculated financial quote with deterministic bounds validation."""
        if not isinstance(principal, (int, float)) or math.isnan(principal) or math.isinf(principal) or principal <= 0:
            raise ValueError(f"Principal must be a positive finite number, got {principal}")
        if principal > self.MAX_CEILING_INR:
            raise ValueError(f"Principal ₹{principal:,.0f} exceeds RBI ceiling of ₹{self.MAX_CEILING_INR:,.0f}")
        if tenure_months <= 0:
            raise ValueError(f"Tenure must be positive, got {tenure_months}")

        quote = {
            "principal": float(principal),
            "tenure_months": int(tenure_months),
            "xirr_pct": float(xirr_pct),
            "profit": float(profit),
            "maturity_amount": float(maturity_amount),
            "monthly_emi": float(monthly_emi) if monthly_emi is not None else None,
            "recorded_at": time.time(),
        }
        self._quotes.append(quote)
        return quote

    def verify_quote(
        self,
        principal: float,
        tenure_months: int,
        quoted_maturity: float,
        tolerance: float = 1.0,
    ) -> bool:
        """Verifies if a quoted maturity matches previously recorded quotes within tolerance."""
        matching = [
            q for q in self._quotes
            if abs(q["principal"] - float(principal)) < 0.01 and q["tenure_months"] == int(tenure_months)
        ]
        if not matching:
            return False
        latest = matching[-1]
        return abs(latest["maturity_amount"] - float(quoted_maturity)) <= tolerance

    def get_quote(self, principal: float, tenure_months: int) -> Optional[Dict[str, Any]]:
        """Retrieves the latest quote matching given principal and tenure."""
        matching = [
            q for q in self._quotes
            if abs(q["principal"] - float(principal)) < 0.01 and q["tenure_months"] == int(tenure_months)
        ]
        return matching[-1] if matching else None

    def get_latest_quote(self) -> Optional[Dict[str, Any]]:
        """Returns the most recently recorded quote across all tenures and principals."""
        return self._quotes[-1] if self._quotes else None

    def get_all_quotes(self) -> List[Dict[str, Any]]:
        """Returns all recorded quotes in chronological order."""
        return list(self._quotes)

    def get_history(self) -> List[Dict[str, Any]]:
        """Alias for get_all_quotes."""
        return list(self._quotes)

    def clear(self) -> None:
        """Clears all recorded quotes for session reset."""
        self._quotes.clear()


# ═══════════════════════════════════════════════════════════════════════
# 5-TIER HUMAN ESCALATION & CALLBACK MATRIX (Milestone M3)
# ═══════════════════════════════════════════════════════════════════════

class EscalationTracker:
    """Tracks repeated human requests and complex queries to trigger human manager callback escalation."""

    def __init__(self):
        self.human_requests_count: int = 0
        self.queries: List[str] = []
        self.repeated_queries_count: int = 0

    def record_human_request(self) -> int:
        """Records a user request to speak to a human manager and returns current escalation tier."""
        self.human_requests_count += 1
        return self.get_escalation_tier()

    def record_user_query(self, text: str) -> int:
        """Records a user query/question, tracking repeated queries, and returns current escalation tier."""
        self.queries.append(text)
        if len(self.queries) >= 3:
            self.repeated_queries_count = len(self.queries)
        return self.get_escalation_tier()

    def get_escalation_tier(self) -> int:
        """Computes current escalation tier (1-5) based on matrix rules:
        - Tier 5: repeated human requests >= 2 OR repeated queries >= 3 (Callback booking required)
        - Tier 4: human requests == 1
        - Tier 3: distinct queries >= 2
        - Tier 2: distinct queries == 1
        - Tier 1: normal conversation (0 queries, 0 human requests)
        """
        if self.human_requests_count >= 2 or self.repeated_queries_count >= 3:
            return 5
        if self.human_requests_count == 1:
            return 4
        if len(self.queries) >= 2:
            return 3
        if len(self.queries) == 1:
            return 2
        return 1

    def is_callback_booking_required(self) -> bool:
        """Returns True if escalation tier >= 5, requiring proactive callback scheduling."""
        return self.get_escalation_tier() >= 5

