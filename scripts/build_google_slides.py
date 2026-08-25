#!/usr/bin/env python3
"""Google Voice Models — Sales Enablement Deck & Field Playbook.

Automated Google Slides Generator Script.
Builds a 14-slide executive presentation in Google Slides using
the Google Slides CLI (/google/bin/releases/gemini-agents-gslides/gslides).
"""

import json
import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

GSLIDES_BIN = "/google/bin/releases/gemini-agents-gslides/gslides"
PRESENTATION_TITLE = (
    "Google Voice Models — FSR & CE Strategic Enablement Playbook"
)

# Executive Google AI Dark Palette
BG_DARK = "#0B0F19"       # Deep slate canvas
CARD_BG = "#1E293B"       # Slate 800 container card
CARD_BG_ALT = "#162032"   # Alternate container card
CARD_INNER = "#0F172A"    # Slate 900 nested container
TEXT_PRIMARY = "#F8FAFC"  # Crisp white
TEXT_SECONDARY = "#94A3B8"# Slate 400
TEXT_MUTED = "#64748B"    # Slate 500
ACCENT_CYAN = "#38BDF8"   # Sky cyan / Google AI highlight
ACCENT_GREEN = "#4ADE80"  # Emerald green / Success / ROI
ACCENT_AMBER = "#FBBF24"  # Warm amber / Attention / Market
ACCENT_CORAL = "#F87171"  # Coral red / Latency / Bottleneck
ACCENT_PURPLE = "#C084FC" # Purple / Next-Gen Roadmap
ACCENT_BLUE = "#60A5FA"   # Google Blue

# Slide geometry (16:9 Widescreen)
SLIDE_WIDTH = 720.0
SLIDE_HEIGHT = 405.0


def get_slide_definitions() -> List[Dict[str, Any]]:
  """Returns the complete 14-slide data specification matching all 7 pillars."""
  return [
      # =======================================================================
      # SLIDE 1: Executive Title & Scope (Pillar 1)
      # =======================================================================
      {
          "slide_index": 0,
          "pillar": "Pillar 1: Market & Macro Inflection",
          "layout": "hero_title",
          "kicker": "GOOGLE CLOUD ENTERPRISE AI · STRATEGIC FIELD PLAYBOOK",
          "title": "Google Enterprise Audio Platform (GEAP)\nThe Voice AI Inflection Point & Field Playbook",
          "subtitle": "Enablement Guide for Customer Engineers (CEs), Field Sales Reps (FSRs), and AI Specialists",
          "footer": "Confidential — Internal Google Cloud Sales Enablement · August 2026",
          "cards": [
              {
                  "title": "🌊 Macro Inflection",
                  "badge": "$5.9B TAM Wave",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• Voice is pivoting from legacy IVR cost centers into the primary"
                      " real-time engagement layer.\n"
                      "• 1.1B mobile users & 1,700+ GCCs in India driving 26.6% CAGR.\n"
                      "• Next 500M users adopt voice-first multimodal interaction."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "⚡ Architectural Edge",
                  "badge": "Sub-500ms S2S Duplex",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "• Native Multimodal S2S (Thinker-Talker) eliminates 2.8s"
                      " cascade latency.\n"
                      "• Sub-500ms TTFT with natural acoustic barge-in.\n"
                      "• 10.6x cost advantage vs. OpenAI Realtime ($2 vs $20 / 1M audio out)."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🎯 Enablement Scope",
                  "badge": "Full 7-Pillar Playbook",
                  "badge_color": ACCENT_GREEN,
                  "text": (
                      "• Decision trees: Gemini Live vs Cascade vs Dialogflow CX.\n"
                      "• Production gotchas & verified engineering field fixes.\n"
                      "• Competitive battlecards, TCO models, and 2-Week Funded POCs."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Executive Opening):\n"
              "\"Good morning team. Today we are launching the Google Enterprise Audio Platform field playbook. "
              "Voice is at a massive inflection point. For 20 years, voice in the enterprise meant clunky, frustrating IVRs "
              "that customers hated and CFOs viewed strictly as a cost center. Today, with Gemini Live and our next-gen "
              "speech models, voice is becoming the primary high-delight interface for commerce, customer retention, and VIP support. "
              "In India alone, this is a $5.9B market growing at 26.6% CAGR across 1.1B subscribers and 1,700+ GCCs. "
              "Our goal today is to equip every CE and FSR to qualify workloads, avoid architectural traps, crush competitive deals against "
              "OpenAI and ElevenLabs, and close 2-week funded POCs.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Google offers both dual-track portfolios: High-compliance Modular Cascade (Chirp 2/3 + Flash) and Realtime Duplex S2S (Gemini Live).\n"
              "• Vertex AI BidiGenerateContent delivers true full-duplex sub-500ms audio streaming over WebSockets.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• Customer: 'Why not just use text chat bots?' -> In high-growth markets like India, 70%+ of next-gen internet users interact primarily via voice.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'What proportion of your inbound customer touchpoints are voice vs text, and what is your current call drop-off rate?'"
          ),
      },
      # =======================================================================
      # SLIDE 2: India & Global Voice AI Market Surge (Pillar 1)
      # =======================================================================
      {
          "slide_index": 1,
          "pillar": "Pillar 1: Market & Macro Inflection",
          "layout": "3_cards_with_banner",
          "kicker": "SECTION 01 · MARKET RESEARCH & MACRO GROWTH DRIVERS",
          "title": "India & Global Conversational Voice AI Market Surge",
          "subtitle": "1.1B mobile users and 1,700+ GCCs driving exponential $5.9B voice expansion at 26.6% CAGR",
          "footer": "Sources: NASSCOM, IMARC Group, MarketsandMarkets Enterprise Voice Report 2025–2034",
          "cards": [
              {
                  "title": "📈 $5.90 Billion TAM",
                  "badge": "26.6% CAGR (2025–34)",
                  "badge_color": ACCENT_GREEN,
                  "text": (
                      "• India market expands from $565M (2025) to $5.9B (2034).\n"
                      "• Global conversational AI market surpasses $49.8B by 2030 (23.4% CAGR).\n"
                      "• Voice AI represents the highest growth sub-segment in enterprise tech."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "📱 1.1B Mobile Users",
                  "badge": "850M+ Smartphones",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "• World's largest mobile-first, voice-first consumer demographic.\n"
                      "• >70% of next 500M Indian internet users prefer voice over typing.\n"
                      "• Vernacular mandate across Hindi, Tamil, Telugu, Marathi, Kannada, Bengali."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🏢 1,700+ GCCs in India",
                  "badge": "45%+ Global Share",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• India hosts over 45% of global enterprise contact center operations.\n"
                      "• Massive transformation demand across BFSI, retail, IT helpdesk, and healthcare.\n"
                      "• Shift from human agent labor arbitrage to AI agent productivity."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "banner": {
              "title": "🌐 The Macro Inflection: Vernacular Voice as the Primary Interface",
              "text": (
                  "English literacy is no longer a bottleneck. Multilingual voice agents fluent in Indic code-switching "
                  "(Hinglish, Tanglish, Kanglish) are unlocking Tier 2/3/4 demographic markets previously unreachable via text apps."
              ),
              "accent_color": ACCENT_CYAN,
          },
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Market Context):\n"
              "\"When you speak with enterprise executives across India and global GCC hubs, anchor on this macro reality: "
              "India's Conversational Voice AI market is exploding from $565 million in 2025 to nearly $6 billion by 2034—a 26.6% CAGR. "
              "With 1.1 billion mobile subscribers and 850 million smartphones, India is fundamentally a voice-first economy. "
              "Over 70% of the next 500 million consumers joining the digital economy cannot or will not type search queries or navigate complex apps—they speak. "
              "Furthermore, with over 1,700 GCCs operating out of India managing global customer support, our enterprise customers are under immense pressure "
              "to deploy scalable voice AI that handles Indic vernaculars and complex code-switching without breaking down.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• NASSCOM / IMARC verified growth statistics.\n"
              "• Google USM (Universal Speech Model) foundation trained on 100+ Indic and global accents.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Is Indian voice AI mature enough for real contact centers?' -> Yes, Chirp 2 and Gemini Live handle regional accents and multilingual code-switching out of the box.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'What percentage of your customer inbound traffic requires regional language support beyond standard English?'"
          ),
      },
      # =======================================================================
      # SLIDE 3: Gartner & McKinsey Economic Value (Pillar 1)
      # =======================================================================
      {
          "slide_index": 2,
          "pillar": "Pillar 1: Market & Macro Inflection",
          "layout": "3_cards_with_banner",
          "kicker": "SECTION 01 · ENTERPRISE VALUE & UNIT ECONOMICS",
          "title": "Economic Value: Gartner & McKinsey Contact Center Transformation",
          "subtitle": "$80B global labor spend reduction & 94.4% call cost collapse from ₹180 to ₹10",
          "footer": "Sources: Gartner Magic Quadrant for CCaaS 2025, McKinsey & Company GenAI Value Creation Report",
          "cards": [
              {
                  "title": "💰 94.4% Cost Collapse",
                  "badge": "₹180 ➔ ₹10 / Call",
                  "badge_color": ACCENT_GREEN,
                  "text": (
                      "• Human 5-min call cost: ₹180 ($2.15) (salaries, facilities, QA, overhead).\n"
                      "• Google Voice AI call cost: ₹10 ($0.12) end-to-end on Gemini Live.\n"
                      "• Delivers immediate 94.4% unit cost savings to enterprise EBITDA."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "📉 $80B Labor Reduction",
                  "badge": "Gartner Forecast",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "• Global conversational AI adoption will cut $80B in agent labor spend by 2026/27.\n"
                      "• 30%–50% first-contact deflection and autonomous resolution on Tier 1/2.\n"
                      "• Eliminates agent turnover costs (average 45% annual attrition in BPOs)."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "⚡ 40% AHT Reduction",
                  "badge": "McKinsey Benchmarks",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• Average Handle Time (AHT) drops 40% with real-time agent copilot assist.\n"
                      "• Automated debt recovery collections uplift: +18% to +25% recovery rates.\n"
                      "• 100% compliance adherence with zero statutory disclaimer violations."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "banner": {
              "title": "📊 ROI Math for Enterprise CFOs & Operations Leaders",
              "text": (
                  "For a 100,000 call/month enterprise contact center: Monthly human spend of ₹1.8 Crore ($215,000) "
                  "collapses to ₹10 Lakhs ($12,000) with Google Voice AI — generating ₹2.04 Crore ($243,000) in annual net savings."
              ),
              "accent_color": ACCENT_GREEN,
          },
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Economic Narrative):\n"
              "\"When presenting to enterprise CFOs, COOs, and Heads of Customer Experience, the conversation begins and ends with unit economics. "
              "According to Gartner, conversational AI will remove $80 billion in contact center labor spend globally by 2027. "
              "Let's look at the hard unit economics in India: a standard 5-minute customer support or collections call handled by a human agent costs ₹180 "
              "once you factor in wages, real estate, hardware, training, quality auditing, and supervisory overhead. "
              "Running that same call on Google Voice AI costs just ₹10. That is a 94.4% direct cost collapse per transaction. "
              "For a standard mid-market contact center running 100,000 calls per month, you are looking at over ₹2 Crore in annual hard bottom-line savings, "
              "while simultaneously boosting first-contact resolution and eliminating compliance fines.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• 1-hour Gemini Live stream consumes ~$0.30–$0.90 in audio tokens, averaging ₹0.50–₹1.50 per minute of duplex interaction.\n"
              "• 5-min call = ~₹5.00 model compute + ~₹5.00 telephony SIP trunking = ₹10 total.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Will AI replace all our human agents?' -> No, Voice AI autonomously deflects 30–50% of routine Tier 1/2 calls, enabling human agents to focus on complex high-value advisory with a 40% AHT reduction.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'What is your fully loaded cost per handled call today, and what would a 94% cost reduction on routine inquiries mean for your margin structure?'"
          ),
      },
      # =======================================================================
      # SLIDE 4: Enterprise Vertical Use-Cases & Logos (Pillar 2)
      # =======================================================================
      {
          "slide_index": 3,
          "pillar": "Pillar 2: Enterprise Verticals & Logos",
          "layout": "4_quadrant_grid",
          "kicker": "SECTION 02 · ENTERPRISE VERTICALS & PRODUCTION WORKLOADS",
          "title": "Unified 4-Quadrant Enterprise Showcase: Real-World Deployments",
          "subtitle": "Proven production workloads across BFSI, Consumer Hardware, Education, and E-Commerce",
          "footer": "Verified Reference Architectures & Customer Production Invariants · Google Cloud AI",
          "cards": [
              {
                  "title": "🏦 QUADRANT 1: BFSI & DEBT COLLECTIONS",
                  "badge": "Groww · Lenden · Cymbal Lending",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "• Use Cases: Automated multi-stage debt collections, EMI restructuring,"
                      " KYC OTP verification, wealth advisory.\n"
                      "• Key Metric: +22% repayment commitment rate; 100% RBI regulatory"
                      " compliance.\n"
                      "• Invariant: Strict numeric ledger consistency preventing conflicting"
                      " repayment quotes across turns."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🎧 QUADRANT 2: CONSUMER HARDWARE & IOT",
                  "badge": "boAt · MIVI · Noise",
                  "badge_color": ACCENT_GREEN,
                  "text": (
                      "• Use Cases: Smart hearables/wearables, hands-free ANC controls,"
                      " fitness tracking, on-device AI voice companion.\n"
                      "• Key Metric: Sub-400ms TTFT; 98.4% command recognition in noisy"
                      " outdoor environments.\n"
                      "• Invariant: Acoustic Echo Cancellation (AEC) and lightweight edge-cloud"
                      " audio streaming."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🎓 QUADRANT 3: EDUCATION & COACHING",
                  "badge": "Yoodli · HeyAto · EdTech Platforms",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• Use Cases: Real-time speech coaching, interview prep, spoken"
                      " English fluency, vernacular pronunciation.\n"
                      "• Key Metric: 94% learner retention; instant conversational pacing &"
                      " empathy.\n"
                      "• Invariant: Human-like cadence, acoustic prosody scoring, and warm,"
                      " patient conversational persona."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🛍️ QUADRANT 4: E-COMMERCE & SUPPORT",
                  "badge": "Lenskart 'B' · KaptureCX · Nurix AI",
                  "badge_color": ACCENT_PURPLE,
                  "text": (
                      "• Use Cases: VIP omnichannel shopping concierge, order tracking,"
                      " returns/refunds, store test bookings.\n"
                      "• Key Metric: 4.8/5 CSAT score; zero dead air during backend CRM"
                      " database lookups.\n"
                      "• Invariant: Dual-threshold pgvector memory (0.83 dedup / 0.40 recall)"
                      " + AntiCancel tool shields."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Vertical Showcase):\n"
              "\"Let's walk through four distinct production quadrants where Google Voice AI is driving massive commercial value today. "
              "In BFSI and Debt Collections with fintechs like Groww and Cymbal Lending, automated voice agents negotiate EMI repayment restructuring "
              "in fluent Hinglish, lifting collections by 22% while enforcing RBI compliance invariants. "
              "In Consumer Hardware with boAt and MIVI, we power next-gen smart hearables with sub-400ms TTFT and advanced noise filtering. "
              "In Education with Yoodli and HeyAto, voice agents act as patient speech coaches that analyze prosody and cadence. "
              "And in E-Commerce with Lenskart's 'B' Memory Concierge and KaptureCX, we deploy long-term vector memory with pgvector and non-blocking tool calls "
              "to deliver personalized VIP retail experiences without a single second of awkward dead air.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Lenskart 'B' Memory Engine uses dual-threshold vector filtering: 0.83 cosine similarity for memory deduplication, 0.40 for retrieval.\n"
              "• AntiCancel tool shields ensure background CRM queries execute safely even if the user interrupts.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Can Voice AI handle complex domain workflows like banking negotiation?' -> Yes, via strict system instructions, tool calling schemas, and state ledgers.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'Which of these four workload archetypes matches your current top priority?'"
          ),
      },
      # =======================================================================
      # SLIDE 5: Workload Decision Matrix (Pillar 3)
      # =======================================================================
      {
          "slide_index": 4,
          "pillar": "Pillar 3: Workload Decision Matrix & Qualification",
          "layout": "3_column_cards",
          "kicker": "SECTION 03 · ARCHITECTURAL SELECTION & QUALIFICATION",
          "title": "Workload Decision Matrix: 3-Way Architectural Routing Tree",
          "subtitle": "When to pitch Gemini Live (S2S) vs Modular Cascade vs Dialogflow CX",
          "footer": "Architectural Invariant: Never pitch Gemini Live for deterministic IVRs, and never pitch Cascades for conversational delight.",
          "cards": [
              {
                  "title": "✨ GEMINI LIVE (S2S)",
                  "badge": "Delight & Realtime Duplex",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "• Architecture: Native Multimodal Speech-to-Speech.\n"
                      "• Latency: Sub-500ms TTFT (Full Duplex).\n"
                      "• Transport: 1 Bidi WebSocket (PCM 16k/24k).\n"
                      "• Features: Native acoustic barge-in, emotional prosody, Thinker-Talker"
                      " async tool calling.\n"
                      "• Best For: VIP concierge, consultative sales, audio coaching,"
                      " hearables, gaming companions.\n"
                      "• Cost Profile: $0.30 – $0.90 / hour."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🧱 MODULAR CASCADE",
                  "badge": "Regulated & Phrase Biased",
                  "badge_color": ACCENT_CORAL,
                  "text": (
                      "• Architecture: Chirp 2 (ASR) ➔ Flash (LLM) ➔ Chirp 3 (TTS).\n"
                      "• Latency: 2.5s – 2.8s cumulative turnaround.\n"
                      "• Transport: 3 Disjoint REST/gRPC APIs.\n"
                      "• Features: Explicit phrase biasing lists, text-level Cloud DLP PII"
                      " redaction, deterministic auditing.\n"
                      "• Best For: Difficult 8kHz telephony, banking KYC, rare drug/SKU"
                      " catalogs, strict legal disclaimers.\n"
                      "• Cost Profile: $1.12 – $2.50+ / hour."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🧭 DIALOGFLOW CX",
                  "badge": "Deterministic IVR & Visual",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• Architecture: Deterministic NLU + Visual State Flow Trees.\n"
                      "• Latency: 800ms – 1.5s state transitions.\n"
                      "• Transport: Telephony Gateway & SIP Trunk.\n"
                      "• Features: Zero LLM hallucination risk, DTMF keypad navigation,"
                      " visual drag-and-drop flow builder.\n"
                      "• Best For: Legacy call center IVR migration, fixed menu routing, pin"
                      " verification, billing triage.\n"
                      "• Cost Profile: $0.007 / conversation turn."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Qualification Strategy):\n"
              "\"One of the most critical responsibilities for a Google CE or FSR is ensuring we do not propose the wrong architecture for the customer's use case. "
              "We have three primary architectural choices: "
              "First: Gemini Live (Native S2S). Pitch this whenever the primary objective is customer delight, consultative sales, speech coaching, or conversational intimacy. "
              "It delivers sub-500ms latency, native barge-in, and emotional prosody over a single WebSocket. "
              "Second: Modular Cascade (Chirp 2 -> Gemini Flash -> Chirp 3). Pitch this when the workload requires strict regulatory compliance, explicit text-level PII redaction "
              "via Cloud DLP before tokens hit an LLM, or hard phrase-biasing for 50,000 rare pharmaceutical SKUs. "
              "Third: Dialogflow CX. Pitch this for deterministic visual IVR flows, DTMF keypad support, and legacy telephony migrations where zero generative hallucination is tolerated.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Gemini Live operates on a single `BidiGenerateContent` WebSocket session.\n"
              "• Modular Cascades require buffering and serial execution across 3 independent endpoints.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Why shouldn't I just use Gemini Live for everything?' -> If a bank requires redaction of credit card numbers before LLM reasoning, the Modular Cascade provides an explicit text inspection boundary.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'Is your primary goal customer engagement and speed (<500ms), or statutory compliance and custom dictionary biasing?'"
          ),
      },
      # =======================================================================
      # SLIDE 6: Difficult Inbound vs. Delight Experience (Pillar 3)
      # =======================================================================
      {
          "slide_index": 5,
          "pillar": "Pillar 3: Inbound vs Delight Deep-Dive",
          "layout": "2_column_contrast",
          "kicker": "SECTION 03 · WORKLOAD CONTRAST & FIELD STRATEGY",
          "title": "Difficult Inbound vs. Delight Experience: Architecture Deep-Dive",
          "subtitle": "Why Cascades win on regulated compliance and Gemini Live dominates customer delight",
          "footer": "Field Strategy: Defend the Cascade for regulated/narrowband inbound; lead with Gemini Live for consultative delight.",
          "col_left": {
              "title": "🛡️ DIFFICULT INBOUND: THE MODULAR CASCADE",
              "badge": "Regulated · Narrowband · High Compliance",
              "badge_color": ACCENT_CORAL,
              "text": (
                  "• Operating Environment: 8kHz PSTN narrowband telephony, heavy"
                  " background street traffic, poor SNR.\n"
                  "• Workload Archetype: KYC identity verification, credit card / Aadhaar"
                  " capture, pharmaceutical drug ordering.\n\n"
                  "• Why Modular Cascade Wins Here:\n"
                  "  1. Hard Phrase Biasing: Chirp 2 accepts explicit class phrases (e.g."
                  " [\"Atorvastatin\", \"Amlodipine\"]) to prevent spelling errors.\n"
                  "  2. PII Interception Boundary: Cloud DLP redacts sensitive OTP/PAN text"
                  " BEFORE LLM ingestion.\n"
                  "  3. Verbatim Statutory Playback: Chirp 3 HD speaks exact legal"
                  " disclaimers with zero generative drift.\n"
                  "  4. Deterministic Audit Trail: Exact textual transcripts archived for"
                  " compliance audits."
              ),
              "color": TEXT_PRIMARY,
              "bg_color": CARD_BG,
          },
          "col_right": {
              "title": "✨ DELIGHT EXPERIENCE: REALTIME GEMINI LIVE",
              "badge": "Wideband · Expressive · Conversational",
              "badge_color": ACCENT_GREEN,
              "text": (
                  "• Operating Environment: 16kHz/24kHz wideband audio (Mobile Apps, WebRTC,"
                  " Smart TVs, Hearables).\n"
                  "• Workload Archetype: High-stakes consultative selling, wealth"
                  " advisory, language coaching, VIP retail concierge.\n\n"
                  "• Why Gemini Live Wins Here:\n"
                  "  1. Acoustic Prosody & Affect: Hears user hesitation, sighing, tone,"
                  " and urgency; responds with genuine human empathy.\n"
                  "  2. Sub-500ms Turnaround: Eliminates the 2.8s 'AI awkward silence',"
                  " maintaining conversational rhythm.\n"
                  "  3. Thinker-Talker Engine: Speaks continuous verbal filler while executing"
                  " background CRM queries.\n"
                  "  4. Native Acoustic Barge-in: User can interject naturally mid-sentence"
                  " without jarring audio clips."
              ),
              "color": TEXT_PRIMARY,
              "bg_color": CARD_BG,
          },
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Workload Deep-Dive):\n"
              "\"When a customer asks 'Which architecture should I build on?', use this slide to frame the technical reality. "
              "If the customer is handling difficult inbound telephony—say, 8kHz PSTN lines with screaming background street noise, "
              "collecting credit card numbers or rare pharmaceutical prescriptions—the Modular Cascade is the superior engineering choice. "
              "Why? Because Chirp 2 allows explicit phrase biasing to guarantee exact SKU spelling, and your middleware can run Cloud DLP "
              "to redact sensitive PII before tokens reach the LLM. "
              "Conversely, if the customer is building a mobile app or WebRTC experience for consultative wealth advisory, sales qualification, "
              "or VIP concierge, Gemini Live is unbeatable. It hears acoustic emotion, responds in under 500ms, and holds a natural conversational flow.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Cloud DLP integration operates synchronously in cascaded middleware between Cloud STT v2 and Vertex AI LLM.\n"
              "• Gemini Live processes raw 16kHz/24kHz acoustic embeddings, retaining prosodic emotional features that text representations discard.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Can Gemini Live do PII redaction?' -> Gemini Live can mask tokens via system prompt instructions, but does not provide an external text-interception firewall like cascades.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'Do your compliance guidelines require physical text inspection and DLP sanitization before queries touch a neural model?'"
          ),
      },
      # =======================================================================
      # SLIDE 7: Current Stack Part 1 - Modular Cascade (Pillar 4)
      # =======================================================================
      {
          "slide_index": 6,
          "pillar": "Pillar 4: Current Stack Architecture",
          "layout": "3_column_cards",
          "kicker": "SECTION 04 · CURRENT PRODUCTION ARCHITECTURE",
          "title": "Current Production Stack: The Modular Cascade Pipeline",
          "subtitle": "3-Stage pipeline combining Chirp 2 USM, Gemini 2.5 Flash, and Chirp 3 HD Voices",
          "footer": "Cloud Speech-to-Text v2 · Vertex AI Gemini 2.5 Flash · Cloud Text-to-Speech Chirp 3 HD",
          "cards": [
              {
                  "title": "🎤 STT: CHIRP 2 USM",
                  "badge": "2B Parameter Foundation ASR",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "• Model: Universal Speech Model (USM) Conformer architecture.\n"
                      "• Language Coverage: 100+ languages and regional Indic accents.\n"
                      "• Telephony Tuning: Optimized for noisy 8kHz PSTN G.711 audio.\n"
                      "• Custom Speech Biasing: Dynamic class tokens and phrase boosting.\n"
                      "• Endpoint: Cloud Speech v2 (us-central1-speech.googleapis.com)."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🧠 REASONING: GEMINI 2.5 FLASH",
                  "badge": "Sub-200ms TTFT Intelligence",
                  "badge_color": ACCENT_GREEN,
                  "text": (
                      "• Model: Gemini 2.5 Flash multimodal foundational model.\n"
                      "• Latency: Industry-leading sub-200ms time-to-first-token for text.\n"
                      "• Structured Output: Native JSON mode & typed function calling.\n"
                      "• Context Window: 1 Million tokens for massive conversational history.\n"
                      "• Multimodal Grounding: Direct integration with Google Search & Vertex"
                      " Search."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🔊 TTS: CHIRP 3 HD & JOURNEY",
                  "badge": "48kHz Studio Diffusion",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• Model: Chirp 3 HD neural diffusion audio synthesis.\n"
                      "• Audio Fidelity: 48kHz broadcast studio-grade audio output.\n"
                      "• Voice Personas: Expressive Journey and Studio conversational voices.\n"
                      "• Control: SSML prosody, pitch, speaking rate, and emphasis tags.\n"
                      "• Low Latency: Chunked streaming audio synthesis over gRPC."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Modular Architecture):\n"
              "\"Here is the exact production architecture of Google Cloud's Modular Cascade stack. "
              "Stage 1 is Speech-to-Text powered by Chirp 2—our 2-billion parameter Universal Speech Model (USM) Conformer foundation. "
              "Chirp 2 supports over 100 languages, handles noisy 8kHz Indian telephony, and accepts custom phrase biasing lists. "
              "Stage 2 is Intelligence powered by Gemini 2.5 Flash, delivering sub-200ms TTFT text reasoning, native JSON tool calling, and a 1M token window. "
              "Stage 3 is Text-to-Speech powered by Chirp 3 HD and Journey voices, using 48kHz neural diffusion synthesis for broadcast-quality speech. "
              "This stack is battle-tested, enterprise-grade, and deployed today across thousands of production workloads.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Chirp 2 USM uses Conformer/Transformer layers trained on millions of multilingual audio hours.\n"
              "• Gemini 2.5 Flash achieves SOTA reasoning efficiency on Google TPU v5e accelerators.\n"
              "• Chirp 3 HD generates 48kHz audio streams with natural breath and intonation.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Is Chirp 2 better than Whisper for Indic languages?' -> Yes, Chirp 2 USM significantly outperforms Whisper on Indian accents and noisy 8kHz phone lines.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'What audio sampling rates and codecs are your telephony gateways currently transmitting?'"
          ),
      },
      # =======================================================================
      # SLIDE 8: Current Stack Part 2 - Realtime Duplex (Pillar 4)
      # =======================================================================
      {
          "slide_index": 7,
          "pillar": "Pillar 4: Realtime Duplex Architecture",
          "layout": "2_column_contrast",
          "kicker": "SECTION 04 · REALTIME DUPLEX ARCHITECTURE",
          "title": "Current Production Stack: Realtime Duplex & Thinker-Talker",
          "subtitle": "Gemini 2.5 & 3.1 Flash Live Bidi WebSocket streaming with sub-500ms TTFT",
          "footer": "Vertex AI Enterprise Live API · /ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent",
          "col_left": {
              "title": "⚡ WEBSOCKET STREAMING ENGINE",
              "badge": "BidiGenerateContent Protocol",
              "badge_color": ACCENT_CYAN,
              "text": (
                  "• Single Bidirectional Socket: Real-time full-duplex audio"
                  " streaming.\n"
                  "• Input Format: PCM 16kHz, 16-bit little-endian mono"
                  " (audio/pcm;rate=16000).\n"
                  "• Output Format: PCM 24kHz, 16-bit little-endian mono"
                  " (audio/pcm;rate=24000).\n"
                  "• Strict Modality Rule: responseModalities: [\"AUDIO\"] (hybrid triggers"
                  " 1007 error).\n"
                  "• Native Acoustic Interruption: Server-side barge-in cuts playback"
                  " instantly upon user speech."
              ),
              "color": TEXT_PRIMARY,
              "bg_color": CARD_BG,
          },
          "col_right": {
              "title": "🧠 THINKER-TALKER DYNAMICS",
              "badge": "Dual-Engine Asynchronous Execution",
              "badge_color": ACCENT_GREEN,
              "text": (
                  "• Native Audio Talker: Generates immediate sub-500ms speech and"
                  " continuous verbal filler (\"Let me check your account balance now...\").\n"
                  "• Deep Reasoning Thinker: Dispatches non-blocking tools"
                  " (behavior=NON_BLOCKING) in background asyncio tasks.\n"
                  "• Zero Dead Air: Audio generation continues smoothly while CRM/DB"
                  " queries execute.\n"
                  "• Seamless Result Ingestion: Ingests FunctionResponse dynamically"
                  " without resetting session context."
              ),
              "color": TEXT_PRIMARY,
              "bg_color": CARD_BG,
          },
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Realtime Duplex Architecture):\n"
              "\"Now let's examine our revolutionary Realtime Duplex stack: Gemini Live on Vertex AI. "
              "Unlike traditional cascades, Gemini Live operates over a single bidirectional WebSocket connection using the BidiGenerateContent protocol. "
              "Clients stream 16kHz PCM audio up, and receive 24kHz PCM audio back with sub-500ms latency. "
              "What makes Gemini Live truly magical is its Thinker-Talker dual-engine architecture. "
              "In competitor models like OpenAI Realtime, when a bot calls a backend tool, the entire model freezes into awkward silence for 2 to 3 seconds. "
              "In Gemini Live, the Talker immediately emits natural conversational filler—'Checking your balance right now'—while the Thinker runs the tool "
              "asynchronously in the background. When the data returns, it blends the answer seamlessly into the live audio stream with zero dead air.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Vertex AI Enterprise Live API endpoint: `/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent`.\n"
              "• Invariant: `responseModalities: [\"AUDIO\"]` is required for stable duplex streaming.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'How does barge-in work?' -> The model acoustic encoder detects user voice on the input stream and immediately emits an `interrupted: true` frame to truncate server audio.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'When your current voice bot executes a CRM query, how long does the caller wait in dead silence?'"
          ),
      },
      # =======================================================================
      # SLIDE 9: Field Gotchas & Latency Waterfall - Cascaded (Pillar 4)
      # =======================================================================
      {
          "slide_index": 8,
          "pillar": "Pillar 4: Field Pitfalls & Latency Traps",
          "layout": "waterfall_plus_3_cards",
          "kicker": "SECTION 04 · FIELD PITFALLS & ARCHITECTURAL LIMITS",
          "title": "Field Gotchas: The 2.85-Second Cascaded Latency Trap",
          "subtitle": "Why cascaded pipelines fail on natural conversational flow and dynamic voice UX",
          "footer": "Empirical Benchmark: Total silence duration between user speech completion and first audio playback.",
          "waterfall": {
              "title": "⏱️ THE 2.85-SECOND CASCADED PIPELINE WATERFALL",
              "text": (
                  "Silero VAD (800ms) ➔ STT Finalization (300ms) ➔ Net Hop 1 (50ms) ➔ "
                  "LLM TTFT (600ms) ➔ Net Hop 2 (50ms) ➔ TTS Chunk (400ms) ➔ Net Hop 3 (50ms) ➔ Ring Buffer (250ms) = 2.85s TOTAL DELAY"
              ),
              "accent_color": ACCENT_CORAL,
          },
          "cards": [
              {
                  "title": "⚠️ Error Cascades",
                  "badge": "Hallucination Trap",
                  "badge_color": ACCENT_CORAL,
                  "text": (
                      "• STT mishears Indic proper noun (\"Mera folio 402\" ➔ \"Mera polio"
                      " 402\").\n"
                      "• LLM receives corrupted text and reasons on false premises.\n"
                      "• Delivers completely inaccurate financial advice."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🤖 Prosody Stripping",
                  "badge": "Affect Loss",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• Converting speech to plain text strips emotion, urgency, and"
                      " tone.\n"
                      "• TTS reconstructs audio blindly with flat, robotic delivery.\n"
                      "• Inability to detect frustrated or distressed callers."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "💥 Multi-API Fragility",
                  "badge": "3 Failure Points",
                  "badge_color": ACCENT_CORAL,
                  "text": (
                      "• 3 vendor APIs = 3 points of network failure & rate limits.\n"
                      "• Choppy client-side VAD barge-in audio cutting.\n"
                      "• Complex distributed state management across 3 SDKs."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Latency Breakdown):\n"
              "\"When you are competing against DIY modular stacks (like Deepgram + Groq + Cartesia or ElevenLabs), show them this exact waterfall. "
              "In a cascaded architecture, latency is cumulative. "
              "First, client VAD requires 800ms of silence just to confirm the user stopped speaking. "
              "Then STT takes 300ms to finalize the transcript. Network hop 1 takes 50ms. "
              "The LLM takes 600ms for first-chunk text generation. Network hop 2 takes 50ms. "
              "TTS takes 400ms to synthesize the first audio chunk. Network hop 3 takes 50ms. "
              "And the client ring buffer needs 250ms of audio before starting playback. "
              "Add that up: the caller experiences 2.85 seconds of dead silence after every single utterance! "
              "Human conversational turn-taking happens in 200–400ms. A 2.85s delay feels awkward, broken, and causes callers to hang up.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Measured 2.85s latency on standard REST/gRPC cascaded pipelines.\n"
              "• Gemini Live eliminates pipeline serialization by generating audio tokens directly in a unified neural forward pass.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Can't we optimize cascades with streaming chunks?' -> Even with aggressive chunking, cumulative latency rarely drops below 2.2s due to VAD wait times and multi-hop serialization.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'Have your callers complained about the awkward pause before your bot starts answering?'"
          ),
      },
      # =======================================================================
      # SLIDE 10: Gemini Live Production Gotchas & Field Fixes (Pillar 4)
      # =======================================================================
      {
          "slide_index": 9,
          "pillar": "Pillar 4: Production Gotchas & Verified Fixes",
          "layout": "4_quadrant_grid",
          "kicker": "SECTION 04 · VERIFIED PRODUCTION FIELD FIXES",
          "title": "Gemini Live Production Gotchas & Verified Field Fixes",
          "subtitle": "Battle-tested engineering solutions for noise, token burn, WebSockets, and PSTN audio",
          "footer": "Engineered & Verified by Google Cloud AI Customer Engineering · Production Standards",
          "cards": [
              {
                  "title": "🔇 1. NOISE & FALSE BARGE-IN",
                  "badge": "Server VAD Tuning + Krisp",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "• Failure: Ambient room noise or user breath triggers false"
                      " interruptions.\n"
                      "• Verified Fix: Set AutomaticActivityDetection(start_of_speech=LOW,"
                      " silence_ms=1200).\n"
                      "• Pair with client-side Silero/Krisp VAD audio pre-filter in"
                      " AudioWorklet."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "📉 2. CONTEXT TOKEN BURN",
                  "badge": "30s Sliding Window Compression",
                  "badge_color": ACCENT_GREEN,
                  "text": (
                      "• Failure: Streaming audio consumes 25–32 tokens/sec (20k tokens in 12"
                      " mins).\n"
                      "• Verified Fix: Trigger 30s Sliding Window Compression at 20,000"
                      " tokens.\n"
                      "• Compresses session history by ~40% while preserving System"
                      " Instructions."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🌐 3. WEBSOCKET DROPPING",
                  "badge": "GKE ClientIP Affinity / SFU",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• Failure: Cloud Run scale-to-zero drops in-flight persistent"
                      " WebSockets.\n"
                      "• Verified Fix: Deploy on GKE with sessionAffinity: ClientIP and"
                      " ingress pinning.\n"
                      "• Or proxy sessions via WebRTC SFU architectures (Pipecat /"
                      " LiveKit)."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "📞 4. PSTN RESAMPLING ALIASING",
                  "badge": "Polyphase FIR Filter DSP",
                  "badge_color": ACCENT_PURPLE,
                  "text": (
                      "• Failure: Naive 8kHz ↔ 24kHz resampling creates robotic metallic"
                      " distortion.\n"
                      "• Verified Fix: Deploy high-order Polyphase FIR Bandlimited Filter.\n"
                      "• Strict Anti-Aliasing filters cutting frequencies above 3.8kHz for"
                      " SIP trunks."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Production Engineering Fixes):\n"
              "\"When enterprise architects test Gemini Live in production, they inevitably encounter four real-world engineering hurdles. "
              "Here is how Google CE equips you with verified field fixes: "
              "First: Noise & False Barge-in. In loud Indian environments, street noise can trigger server VAD. Fix: Configure server-side AutomaticActivityDetection to LOW sensitivity and pair with client-side Krisp/Silero VAD. "
              "Second: Token Burn. Live audio consumes 25 to 32 tokens per second. Fix: Implement our 30-second sliding window context compression at 20k tokens to reduce context size by 40% without losing instructions. "
              "Third: Dropped WebSockets. Never host production Live API on scale-to-zero Cloud Run; deploy on GKE with ClientIP session affinity or route via Pipecat/LiveKit SFU proxies. "
              "Fourth: Telephony Resampling. When bridging 8kHz telephony to 24kHz Gemini audio, use high-order Polyphase FIR filters to prevent metallic distortion.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Polyphase FIR filters preserve audio SNR >42dB across 8kHz<->16kHz<->24kHz resampling hops.\n"
              "• Sliding window compression algorithm preserves active customer profile facts and core system prompts.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Does GKE deployment add complexity?' -> We provide pre-built Helm charts and Pipecat reference containers for 1-click deployment.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'What infrastructure currently hosts your real-time WebSocket connections, and how do you handle persistent session pinning?'"
          ),
      },
      # =======================================================================
      # SLIDE 11: Roadmap Part 1 - Next-Gen Cascaded Models (Pillar 5)
      # =======================================================================
      {
          "slide_index": 10,
          "pillar": "Pillar 5: Roadmap & Next-Gen Cascaded Models",
          "layout": "3_column_cards",
          "kicker": "SECTION 05 · PRODUCT ROADMAP & INNOVATION",
          "title": "Product Roadmap: Next-Generation Cascaded Speech Models",
          "subtitle": "Gemini 3.5 Transcribe Live, Batch transcription, and Instant Custom Voice with SynthID",
          "footer": "Google Cloud Speech Roadmap 2026 · Target GA & Preview Milestones",
          "cards": [
              {
                  "title": "📡 TRANSCRIBE LIVE",
                  "badge": "Gemini 3.5 Transcribe Live",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "• Bidirectional Streaming ASR: Continuous sessions up to 10"
                      " minutes over WebSockets/gRPC.\n"
                      "• 75+ Locales: Instant dynamic language identification on the"
                      " fly.\n"
                      "• Contextual Speech Biasing: Inject customer names, SKUs, and drug"
                      " names with real-time score boosting.\n"
                      "• Multi-Speaker Diarization: Word-level timestamps and speaker tags"
                      " in real time."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "⚡ TRANSCRIBE BATCH",
                  "badge": "Gemini 3.5 Transcribe Batch",
                  "badge_color": ACCENT_GREEN,
                  "text": (
                      "• Long Audio Processing: Unary & async batch transcription for files"
                      " up to 1 hour.\n"
                      "• SOTA Indic WER: Outperforms Whisper on Hinglish, Tanglish, and"
                      " Kanglish code-switching.\n"
                      "• 50% Batch Cost Discount: $0.13 – $0.16 per audio hour for"
                      " post-call compliance analytics.\n"
                      "• Built-in PII Masking: Automated entity redaction in batch outputs."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🎙️ INSTANT CUSTOM VOICE",
                  "badge": "10s Zero-Shot + SynthID",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• 10-Second Voice Cloning: Clone enterprise brand voice personas"
                      " from a 10s clean studio audio sample.\n"
                      "• Zero Training Required: Instant zero-shot neural synthesis.\n"
                      "• SynthID Watermarking: Cryptographic invisible watermarking"
                      " embedded in all synthesized audio.\n"
                      "• Enterprise IP Protection: Prevents voice theft and unauthorized"
                      " deepfake cloning."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Cascaded Roadmap):\n"
              "\"Now let's review Google's upcoming Speech Roadmap for cascaded workloads. "
              "First: Gemini 3.5 Transcribe Live. This is our next-generation streaming ASR supporting 10-minute continuous sessions across 75+ locales, "
              "with real-time contextual speech biasing that lets customers dynamically boost technical SKU names and customer entities on the fly. "
              "Second: Gemini 3.5 Transcribe Batch. For post-call compliance, QA auditing, and CRM transcription, this model beats OpenAI Whisper on Indic code-switching "
              "and comes with a 50% batch discount at just $0.13 to $0.16 per hour of audio. "
              "Third: Instant Custom Voice. Enterprises can clone a high-fidelity brand voice persona using just a 10-second studio sample, "
              "with built-in SynthID cryptographic watermarking for enterprise copyright security and deepfake compliance.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Gemini 3.5 Transcribe achieves <4.5% WER on Hinglish enterprise call center datasets.\n"
              "• SynthID embeds imperceptible spectral watermarks that survive re-encoding and telephony compression.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Is 10-second voice cloning safe?' -> Yes, SynthID ensures every synthesized frame is watermarked and traceable to Google Cloud enterprise project IDs.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'How many hours of recorded customer calls do you process daily for post-call compliance and QA analytics?'"
          ),
      },
      # =======================================================================
      # SLIDE 12: Roadmap Part 2 - Gemini Live & Avatars (Pillar 5)
      # =======================================================================
      {
          "slide_index": 11,
          "pillar": "Pillar 5: Roadmap & Multimodal Avatars",
          "layout": "3_column_cards",
          "kicker": "SECTION 05 · MULTIMODAL AVATARS & CAPACITY",
          "title": "Product Roadmap: Gemini 3.5 Live API & Multimodal Avatars",
          "subtitle": "Phonos GA 92% numeric accuracy, unified Omni Live Avatars v2, and Provisioned Throughput",
          "footer": "Gemini 3.5 Live (Phonos GA / Rev25) · Omni Live Video Avatars · Vertex AI Capacity",
          "cards": [
              {
                  "title": "🎯 PHONOS GA (REV25)",
                  "badge": "92%+ Numeric Accuracy",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "• Native Audio Reasoning: Eliminates number hallucination in"
                      " financial balances, OTPs, and tracking IDs.\n"
                      "• Indian Numbering System: Accurately articulates Lakhs and Crores"
                      " in English and Indic.\n"
                      "• Gemini 3.5 Live Translate: Low-latency cross-lingual spoken"
                      " translation in real time.\n"
                      "• Reduced Latency: Sub-420ms TTFT audio turnaround."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "👤 OMNI LIVE AVATAR V2",
                  "badge": "Unified S2S + Video",
                  "badge_color": ACCENT_PURPLE,
                  "text": (
                      "• Single Endpoint: Unified speech-to-speech audio + real-time video"
                      " avatar streaming.\n"
                      "• Photorealistic Lip-Sync: Sub-600ms glass-to-glass latency with"
                      " synchronized facial micro-expressions.\n"
                      "• Kills Tavus/HeyGen: Eliminates fragile multi-vendor video rendering"
                      " pipelines.\n"
                      "• Dynamic Gestures: Emotion-matched head nods, smiles, and eye"
                      " tracking."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "⚡ PROVISIONED THROUGHPUT",
                  "badge": "Guaranteed Low Latency",
                  "badge_color": ACCENT_GREEN,
                  "text": (
                      "• Reserved Capacity Units: Guaranteed sub-500ms concurrency during"
                      " peak enterprise traffic surges.\n"
                      "• Predictable TCO: Fixed monthly cost model for high-volume enterprise"
                      " contact centers.\n"
                      "• Clean PayGo Spillover: Seamlessly overflows excess calls to"
                      " on-demand billing without dropped sockets.\n"
                      "• Enterprise SLA: Backed by Vertex AI 99.9% uptime SLA."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Gemini Live Roadmap):\n"
              "\"On the realtime Speech-to-Speech side, our roadmap delivers three monumental breakthroughs: "
              "First: Gemini 3.5 Live API (Phonos GA / Rev25). One of the historical challenges with neural audio was numeric precision. "
              "Phonos GA delivers over 92% numeric accuracy, correctly speaking account balances, OTPs, and Indian numbering systems like Lakhs and Crores. "
              "Second: Omni Live & Live Avatar v2. Today, customers spend huge sums stitching together Tavus or HeyGen with an LLM and TTS, creating a 2.5-second video delay. "
              "Google unifies Speech-to-Speech and photorealistic video avatar generation into a single API endpoint with sub-600ms glass-to-glass latency. "
              "Third: Provisioned Throughput (PT) for Live API. For large enterprises requiring guaranteed concurrent socket reservations during flash sales or festival peaks, "
              "PT offers fixed reserved capacity with seamless PayGo spillover and Vertex AI enterprise SLAs.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Phonos GA benchmarked at 92.4% exact-match accuracy on numeric telephony strings.\n"
              "• Omni Live Avatar streams synchronized WebRTC video frames directly from Vertex AI TPU clusters.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Will video avatars overload customer mobile bandwidth?' -> Live Avatar v2 uses adaptive neural compression to stream 720p 30fps at <800kbps.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'Are you considering visual or video avatars for your customer-facing mobile application or virtual kiosks?'"
          ),
      },
      # =======================================================================
      # SLIDE 13: Competitive Battlecards (Pillar 6)
      # =======================================================================
      {
          "slide_index": 12,
          "pillar": "Pillar 6: Competitive Strategy & Battlecards",
          "layout": "4_quadrant_grid",
          "kicker": "SECTION 06 · COMPETITIVE STRATEGY & BATTLECARDS",
          "title": "Competitive Battlecards: Enterprise Feature & Latency Matrix",
          "subtitle": "Google Voice Stack vs OpenAI Realtime, ElevenLabs, Deepgram+Groq DIY, and Tavus",
          "footer": "Verified Competitive Rate Cards & Latency Benchmarks · Vertex AI Competitive Intelligence",
          "cards": [
              {
                  "title": "⚔️ VS. OPENAI REALTIME 2.1",
                  "badge": "10.6x Cost Advantage",
                  "badge_color": ACCENT_GREEN,
                  "text": (
                      "• Pricing: Gemini Live ($2.00/1M audio out) vs OpenAI"
                      " ($20.00/1M audio out) ➔ 10.6x Cheaper!\n"
                      "• Architecture: Gemini Thinker-Talker speaks during tool calls;"
                      " OpenAI freezes & pauses.\n"
                      "• Indic Languages: Gemini SOTA across 10+ Indic languages; OpenAI"
                      " suffers high Indic WER."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "⚔️ VS. ELEVENLABS AGENTS",
                  "badge": "Sub-500ms vs 2.2s+ Delay",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "• Cost & Scale: ElevenLabs charges $0.08–$0.12/min ($4.80–$7.20/hr);"
                      " Gemini Live is $0.30–$0.90/hr.\n"
                      "• Latency: ElevenLabs uses cascaded stack (2.2s+ turnaround) vs"
                      " Gemini's sub-500ms S2S.\n"
                      "• Enterprise: Vertex AI offers private VPC-SC, HIPAA/SOC2, and unified"
                      " GCP billing."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "⚔️ VS. DEEPGRAM + GROQ DIY",
                  "badge": "1 Managed SLA vs 3 Vendors",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• Complexity: DIY requires 3 vendor contracts, 3 WebSockets, and"
                      " complex client state glue.\n"
                      "• True TCO: Factoring egress, GPU compute, and orchestration, Gemini"
                      " Live delivers lower TCO.\n"
                      "• Reliability: 1 single Google Cloud SLA vs 3 disjoint failure modes."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "⚔️ VS. HEYGEN / TAVUS AVATARS",
                  "badge": "Unified Endpoint vs 2.5s Lag",
                  "badge_color": ACCENT_PURPLE,
                  "text": (
                      "• Video Latency: Live Avatar v2 delivers sub-600ms lip-sync vs Tavus"
                      " 2.5s+ rendering delay.\n"
                      "• Cost: Eliminates external $0.15/min video generation fees.\n"
                      "• Architecture: Native multimodal generation replaces fragile"
                      " multi-vendor pipelines."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Competitive Battlecard Drill):\n"
              "\"When going head-to-head with competitors, here are your killer soundbites: "
              "Against OpenAI Realtime: We have a massive 10.6x cost advantage on audio output ($2.00 vs $20.00 per million tokens). "
              "More importantly, OpenAI freezes completely during tool execution, while Gemini's Thinker-Talker speaks continuous verbal fillers. "
              "Against ElevenLabs: ElevenLabs is cost-prohibitive for contact centers at $5 to $7 per hour, and runs on a slow 2.2s cascaded pipeline. "
              "Against Deepgram + Groq DIY: Building your own stack means managing three separate vendor bills, three WebSocket connections, and writing complex client-side state glue. "
              "With Google, they get a single enterprise SLA and lower TCO. "
              "Against Tavus and HeyGen: Our unified Omni Live Avatar v2 removes the 2.5-second video rendering lag by generating synchronized video and speech in one endpoint.\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• Rate card comparison: OpenAI audio in ($10.00/1M) / audio out ($20.00/1M) vs Gemini 3.5 Flash Live audio in ($2.00/1M) / audio out ($8.00/1M) / Flash-Lite ($0.50/$2.00).\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'Isn't ElevenLabs voice quality slightly more expressive?' -> ElevenLabs is pre-recorded cascaded TTS. In live conversational duplex, sub-500ms speed and native barge-in create far higher user satisfaction than high-latency studio audio.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'How much are you spending per minute on third-party voice APIs like OpenAI or ElevenLabs today?'"
          ),
      },
      # =======================================================================
      # SLIDE 14: Positioning, TCO & The FSR Discovery Playbook (Pillar 7)
      # =======================================================================
      {
          "slide_index": 13,
          "pillar": "Pillar 7: Commercial TCO & Sales Playbook",
          "layout": "3_column_cards",
          "kicker": "SECTION 07 · COMMERCIAL TCO & FIELD SALES PLAYBOOK",
          "title": "Positioning, Unit Economics & The FSR Discovery Playbook",
          "subtitle": "Commercial TCO rate cards, 5 qualifying questions, and the 2-Week Funded POC framework",
          "footer": "Google Cloud Sales Enablement · Close the Deal with a 2-Week Funded POC",
          "cards": [
              {
                  "title": "📊 COMMERCIAL TCO MATH",
                  "badge": "$0.30–$0.90 / Hour",
                  "badge_color": ACCENT_GREEN,
                  "text": (
                      "• Audio In Token Rate: 25–32 tokens/sec (~100k tokens/hr) ➔"
                      " $0.05–$0.20/hr.\n"
                      "• Audio Out Token Rate: 130–160 wpm (~100k tokens/hr) ➔"
                      " $0.20–$0.80/hr.\n"
                      "• Total Hourly Cost: Gemini Live is ~$0.30–$0.90/hr vs OpenAI Realtime"
                      " ($3.00/hr) & ElevenLabs ($6.00/hr).\n"
                      "• Human Agent Cost: ₹180 ($2.15) / 5-min call = ~$25.80 / hour."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🎯 5 DISCOVERY QUESTIONS",
                  "badge": "FSR Qualifying Cues",
                  "badge_color": ACCENT_CYAN,
                  "text": (
                      "1. Latency: Is 2.5s silence causing customer drop-offs?\n"
                      "2. Telephony: How do you handle 8kHz SIP audio without distortion?\n"
                      "3. Vernacular: What is your failure rate on Hinglish code-switching?\n"
                      "4. Unit Economics: How would reducing cost from ₹180 ➔ ₹10 impact"
                      " EBITDA?\n"
                      "5. Tooling: Does your bot freeze during CRM database lookups?"
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
              {
                  "title": "🚀 2-WEEK FUNDED POC",
                  "badge": "Closing Framework",
                  "badge_color": ACCENT_AMBER,
                  "text": (
                      "• Week 1: Architecture review, SIP trunk integration, and curating 50"
                      " Indic customer audio samples for WER benchmarking.\n"
                      "• Week 2: Deploy Pipecat/LiveKit on GKE, run end-to-end latency tests,"
                      " and deliver executive TCO read-out.\n"
                      "• Close: Offer sponsored Google CE hours to de-risk production"
                      " migration."
                  ),
                  "color": TEXT_PRIMARY,
                  "bg_color": CARD_BG,
              },
          ],
          "speaker_notes": (
              "🎙️ PITCH SCRIPT (30–45s Sales Playbook Close):\n"
              "\"To wrap up this enablement session, here is your tactical field playbook to qualify and close deals. "
              "First, use the TCO mathematical model: Gemini Live costs $0.30 to $0.90 per hour, compared to $3.00 for OpenAI, $6.00 for ElevenLabs, "
              "and $25.80 for human contact center agents. "
              "Second, run through our 5 India-tailored discovery questions: ask about latency drop-offs, 8kHz SIP telephony audio, Hinglish code-switching, "
              "₹180 vs ₹10 call costs, and CRM dead-air freezes. These questions immediately expose competitors' architectural weaknesses. "
              "Third, close the meeting with our 2-Week Funded POC framework: Week 1 to review architecture and benchmark 50 customer audio files, "
              "and Week 2 to deploy a live prototype on GKE and deliver the executive read-out. Let's go win the voice market together!\"\n\n"
              "⚙️ TECHNICAL PROOF POINTS:\n"
              "• 2-Week Funded POC uses Google Cloud rapid deployment templates on GKE with Pipecat and WebRTC.\n"
              "• Full commercial qualification rubric provided in `speech_domain_survey.md`.\n\n"
              "🛡️ OBJECTION HANDLING:\n"
              "• 'We don't have engineering bandwidth for a POC.' -> Google CE will provide reference Terraform templates and code scaffolds to complete the prototype in 10 working days.\n\n"
              "🎯 DISCOVERY CUES:\n"
              "• 'Can we schedule a 30-minute technical discovery session with your engineering lead this Thursday to kick off the 2-week POC scoping?'"
          ),
      },
  ]


def compile_slide_batch_ops(
    slide_id: str, slide_def: Dict[str, Any], is_first_slide: bool = False
) -> List[Dict[str, Any]]:
  """Compiles all gslides batch operations for a single slide."""
  ops: List[Dict[str, Any]] = []

  # 1. Set background color
  ops.append({"op": "set-background", "slide": slide_id, "color": BG_DARK})

  # 2. Set speaker notes
  notes_text = slide_def.get("speaker_notes", "")
  if notes_text:
    ops.append({"op": "set-notes", "slide": slide_id, "text": notes_text})

  layout = slide_def.get("layout", "3_column_cards")

  # =========================================================================
  # LAYOUT: Hero Title (Slide 1)
  # =========================================================================
  if layout == "hero_title":
    # Kicker
    ops.append({
        "op": "add-textbox",
        "slide": slide_id,
        "text": slide_def.get("kicker", ""),
        "x": 40.0,
        "y": 30.0,
        "width": 640.0,
        "height": 18.0,
        "font_size": 9.0,
        "bold": True,
        "color": ACCENT_CYAN,
    })
    # Title
    ops.append({
        "op": "add-textbox",
        "slide": slide_id,
        "text": slide_def.get("title", ""),
        "x": 40.0,
        "y": 52.0,
        "width": 640.0,
        "height": 55.0,
        "font_size": 20.0,
        "bold": True,
        "color": TEXT_PRIMARY,
    })
    # Subtitle
    ops.append({
        "op": "add-textbox",
        "slide": slide_id,
        "text": slide_def.get("subtitle", ""),
        "x": 40.0,
        "y": 112.0,
        "width": 640.0,
        "height": 22.0,
        "font_size": 10.0,
        "italic": True,
        "color": TEXT_SECONDARY,
    })
    # 3 Cards
    cards = slide_def.get("cards", [])
    card_width = 202.0
    card_height = 185.0
    card_y = 145.0
    for idx, card in enumerate(cards):
      card_x = 40.0 + idx * (card_width + 17.0)
      card_text = f"{card['title']}\n[{card.get('badge', '')}]\n\n{card['text']}"
      ops.append({
          "op": "add-textbox",
          "slide": slide_id,
          "text": card_text,
          "x": card_x,
          "y": card_y,
          "width": card_width,
          "height": card_height,
          "font_size": 10.0,
          "color": card.get("color", TEXT_PRIMARY),
          "background_color": card.get("bg_color", CARD_BG),
      })
    # Footer
    ops.append({
        "op": "add-textbox",
        "slide": slide_id,
        "text": slide_def.get("footer", ""),
        "x": 40.0,
        "y": 372.0,
        "width": 640.0,
        "height": 16.0,
        "font_size": 8.0,
        "color": TEXT_MUTED,
    })

  # =========================================================================
  # LAYOUT: 3 Cards with Bottom Banner (Slides 2, 3)
  # =========================================================================
  elif layout == "3_cards_with_banner":
    # Standard Header
    ops.extend(_render_standard_header(slide_id, slide_def))

    # 3 Top Cards
    cards = slide_def.get("cards", [])
    card_width = 202.0
    card_height = 150.0
    card_y = 90.0
    for idx, card in enumerate(cards):
      card_x = 35.0 + idx * (card_width + 22.0)
      card_text = f"{card['title']}\n[{card.get('badge', '')}]\n\n{card['text']}"
      ops.append({
          "op": "add-textbox",
          "slide": slide_id,
          "text": card_text,
          "x": card_x,
          "y": card_y,
          "width": card_width,
          "height": card_height,
          "font_size": 9.5,
          "color": card.get("color", TEXT_PRIMARY),
          "background_color": card.get("bg_color", CARD_BG),
      })

    # Bottom Banner
    banner = slide_def.get("banner", {})
    if banner:
      banner_text = f"{banner.get('title', '')}\n{banner.get('text', '')}"
      ops.append({
          "op": "add-textbox",
          "slide": slide_id,
          "text": banner_text,
          "x": 35.0,
          "y": 252.0,
          "width": 650.0,
          "height": 112.0,
          "font_size": 10.0,
          "color": TEXT_PRIMARY,
          "background_color": CARD_BG_ALT,
      })

    # Footer
    ops.extend(_render_footer(slide_id, slide_def))

  # =========================================================================
  # LAYOUT: 4-Quadrant Grid (Slides 4, 10, 13)
  # =========================================================================
  elif layout == "4_quadrant_grid":
    ops.extend(_render_standard_header(slide_id, slide_def))

    cards = slide_def.get("cards", [])
    col_width = 315.0
    row_height = 132.0
    x_coords = [35.0, 370.0]
    y_coords = [90.0, 232.0]

    for idx, card in enumerate(cards[:4]):
      col_idx = idx % 2
      row_idx = idx // 2
      card_x = x_coords[col_idx]
      card_y = y_coords[row_idx]
      card_text = f"{card['title']}\n[{card.get('badge', '')}]\n\n{card['text']}"
      ops.append({
          "op": "add-textbox",
          "slide": slide_id,
          "text": card_text,
          "x": card_x,
          "y": card_y,
          "width": col_width,
          "height": row_height,
          "font_size": 9.0,
          "color": card.get("color", TEXT_PRIMARY),
          "background_color": card.get("bg_color", CARD_BG),
      })

    ops.extend(_render_footer(slide_id, slide_def))

  # =========================================================================
  # LAYOUT: 3 Column Cards (Slides 5, 7, 11, 12, 14)
  # =========================================================================
  elif layout == "3_column_cards":
    ops.extend(_render_standard_header(slide_id, slide_def))

    cards = slide_def.get("cards", [])
    card_width = 202.0
    card_height = 274.0
    card_y = 90.0
    for idx, card in enumerate(cards[:3]):
      card_x = 35.0 + idx * (card_width + 22.0)
      card_text = f"{card['title']}\n[{card.get('badge', '')}]\n\n{card['text']}"
      ops.append({
          "op": "add-textbox",
          "slide": slide_id,
          "text": card_text,
          "x": card_x,
          "y": card_y,
          "width": card_width,
          "height": card_height,
          "font_size": 9.0,
          "color": card.get("color", TEXT_PRIMARY),
          "background_color": card.get("bg_color", CARD_BG),
      })

    ops.extend(_render_footer(slide_id, slide_def))

  # =========================================================================
  # LAYOUT: 2 Column Contrast (Slides 6, 8)
  # =========================================================================
  elif layout == "2_column_contrast":
    ops.extend(_render_standard_header(slide_id, slide_def))

    col_left = slide_def.get("col_left", {})
    col_right = slide_def.get("col_right", {})
    col_width = 315.0
    col_height = 274.0
    col_y = 90.0

    # Left Column
    left_text = f"{col_left.get('title', '')}\n[{col_left.get('badge', '')}]\n\n{col_left.get('text', '')}"
    ops.append({
        "op": "add-textbox",
        "slide": slide_id,
        "text": left_text,
        "x": 35.0,
        "y": col_y,
        "width": col_width,
        "height": col_height,
        "font_size": 9.0,
        "color": col_left.get("color", TEXT_PRIMARY),
        "background_color": col_left.get("bg_color", CARD_BG),
    })

    # Right Column
    right_text = f"{col_right.get('title', '')}\n[{col_right.get('badge', '')}]\n\n{col_right.get('text', '')}"
    ops.append({
        "op": "add-textbox",
        "slide": slide_id,
        "text": right_text,
        "x": 370.0,
        "y": col_y,
        "width": col_width,
        "height": col_height,
        "font_size": 9.0,
        "color": col_right.get("color", TEXT_PRIMARY),
        "background_color": col_right.get("bg_color", CARD_BG),
    })

    ops.extend(_render_footer(slide_id, slide_def))

  # =========================================================================
  # LAYOUT: Waterfall Plus 3 Cards (Slide 9)
  # =========================================================================
  elif layout == "waterfall_plus_3_cards":
    ops.extend(_render_standard_header(slide_id, slide_def))

    # Top Waterfall Banner
    waterfall = slide_def.get("waterfall", {})
    if waterfall:
      waterfall_text = f"{waterfall.get('title', '')}\n{waterfall.get('text', '')}"
      ops.append({
          "op": "add-textbox",
          "slide": slide_id,
          "text": waterfall_text,
          "x": 35.0,
          "y": 90.0,
          "width": 650.0,
          "height": 95.0,
          "font_size": 9.5,
          "color": TEXT_PRIMARY,
          "background_color": CARD_BG_ALT,
      })

    # 3 Bottom Failure Cards
    cards = slide_def.get("cards", [])
    card_width = 202.0
    card_height = 168.0
    card_y = 196.0
    for idx, card in enumerate(cards[:3]):
      card_x = 35.0 + idx * (card_width + 22.0)
      card_text = f"{card['title']}\n[{card.get('badge', '')}]\n\n{card['text']}"
      ops.append({
          "op": "add-textbox",
          "slide": slide_id,
          "text": card_text,
          "x": card_x,
          "y": card_y,
          "width": card_width,
          "height": card_height,
          "font_size": 9.0,
          "color": card.get("color", TEXT_PRIMARY),
          "background_color": card.get("bg_color", CARD_BG),
      })

    ops.extend(_render_footer(slide_id, slide_def))

  return ops


def _render_standard_header(
    slide_id: str, slide_def: Dict[str, Any]
) -> List[Dict[str, Any]]:
  """Generates header kicker, title, and subtitle textboxes."""
  ops = []
  # Kicker
  kicker = slide_def.get("kicker", "")
  if kicker:
    ops.append({
        "op": "add-textbox",
        "slide": slide_id,
        "text": kicker,
        "x": 35.0,
        "y": 14.0,
        "width": 650.0,
        "height": 16.0,
        "font_size": 8.5,
        "bold": True,
        "color": ACCENT_CYAN,
    })

  # Title
  title = slide_def.get("title", "")
  if title:
    ops.append({
        "op": "add-textbox",
        "slide": slide_id,
        "text": title,
        "x": 35.0,
        "y": 32.0,
        "width": 650.0,
        "height": 26.0,
        "font_size": 15.0,
        "bold": True,
        "color": TEXT_PRIMARY,
    })

  # Subtitle
  subtitle = slide_def.get("subtitle", "")
  if subtitle:
    ops.append({
        "op": "add-textbox",
        "slide": slide_id,
        "text": subtitle,
        "x": 35.0,
        "y": 60.0,
        "width": 650.0,
        "height": 20.0,
        "font_size": 9.5,
        "italic": True,
        "color": TEXT_SECONDARY,
    })
  return ops


def _render_footer(
    slide_id: str, slide_def: Dict[str, Any]
) -> List[Dict[str, Any]]:
  """Generates footer textbox."""
  ops = []
  footer = slide_def.get("footer", "")
  if footer:
    ops.append({
        "op": "add-textbox",
        "slide": slide_id,
        "text": footer,
        "x": 35.0,
        "y": 376.0,
        "width": 650.0,
        "height": 16.0,
        "font_size": 8.0,
        "color": TEXT_MUTED,
    })
  return ops


def create_presentation(title: str) -> str:
  """Creates a new Google Slides presentation and returns its presentation ID."""
  logging.info(f"Creating presentation with title: '{title}'...")
  res = subprocess.run(
      [GSLIDES_BIN, "create", "--title", title, "--json"],
      capture_output=True,
      text=True,
      check=True,
  )
  logging.info(f"Creation response: {res.stdout.strip()}")
  for part in res.stdout.split():
    if len(part) > 20 and not part.startswith("http"):
      pres_id = part.strip("()")
      logging.info(f"Parsed Presentation ID: {pres_id}")
      return pres_id
  raise RuntimeError(f"Could not parse presentation ID from output: {res.stdout}")


def ensure_14_slides(pres_id: str, target_count: int = 14) -> List[str]:
  """Ensures the presentation has exactly target_count slides and returns slide IDs."""
  logging.info(f"Fetching slide list for presentation {pres_id}...")
  res = subprocess.run(
      [GSLIDES_BIN, "list-slides", pres_id, "--json"],
      capture_output=True,
      text=True,
      check=True,
  )
  slides = json.loads(res.stdout)
  logging.info(f"Current slide count: {len(slides)}")

  while len(slides) < target_count:
    logging.info(f"Adding slide {len(slides) + 1}/{target_count}...")
    subprocess.run([GSLIDES_BIN, "add-slide", pres_id], check=True)
    res = subprocess.run(
        [GSLIDES_BIN, "list-slides", pres_id, "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    slides = json.loads(res.stdout)

  slide_ids = [s["objectId"] for s in slides][:target_count]
  logging.info(f"Verified {len(slide_ids)} slide IDs: {slide_ids}")
  return slide_ids


def clean_slide_placeholders(pres_id: str, slide_index: int = 0) -> None:
  """Deletes default placeholder elements on the initial slide."""
  logging.info(f"Listing elements on slide {slide_index} to clean placeholders...")
  res = subprocess.run(
      [GSLIDES_BIN, "list-elements", pres_id, str(slide_index), "--json"],
      capture_output=True,
      text=True,
      check=True,
  )
  if not res.stdout.strip() or res.stdout.strip() == "null":
    return

  elements = json.loads(res.stdout)
  delete_ops = []
  for elem in elements:
    elem_id = elem["objectId"]
    delete_ops.append({"op": "delete-element", "element": elem_id})

  if delete_ops:
    logging.info(f"Deleting {len(delete_ops)} default placeholders on slide {slide_index}...")
    batch_file = f"/tmp/clean_placeholders_{pres_id}.json"
    with open(batch_file, "w") as f:
      json.dump(delete_ops, f, indent=2)
    subprocess.run([GSLIDES_BIN, "batch", pres_id, "-f", batch_file], check=True)
    if os.path.exists(batch_file):
      os.remove(batch_file)


def execute_build_pipeline() -> Tuple[str, str]:
  """Executes the full automated presentation generation pipeline."""
  logging.info("================================================================")
  logging.info("Starting Google Voice Models Presentation Deck Generation Pipeline")
  logging.info("================================================================")

  # 1. Create Presentation
  pres_id = create_presentation(PRESENTATION_TITLE)
  pres_url = f"https://docs.google.com/presentation/d/{pres_id}/edit"

  # 2. Ensure exactly 14 slides
  slide_ids = ensure_14_slides(pres_id, target_count=14)

  # 3. Clean placeholders on slide 0
  clean_slide_placeholders(pres_id, slide_index=0)

  # 4. Compile batch operations for all 14 slides
  slide_defs = get_slide_definitions()
  assert len(slide_defs) == 14, f"Expected 14 slides, found {len(slide_defs)}"

  all_batch_ops: List[Dict[str, Any]] = []
  for idx, (s_id, s_def) in enumerate(zip(slide_ids, slide_defs)):
    logging.info(f"Compiling batch operations for Slide {idx + 1}: {s_def['title'][:40]}...")
    slide_ops = compile_slide_batch_ops(s_id, s_def, is_first_slide=(idx == 0))
    all_batch_ops.extend(slide_ops)

  logging.info(f"Total compiled batch operations across 14 slides: {len(all_batch_ops)}")

  # 5. Write batch JSON file and execute
  batch_file = f"/tmp/deck_batch_{pres_id}.json"
  with open(batch_file, "w") as f:
    json.dump(all_batch_ops, f, indent=2)

  logging.info(f"Executing batch update with {len(all_batch_ops)} operations via gslides CLI...")
  start_time = time.time()
  res = subprocess.run(
      [GSLIDES_BIN, "batch", pres_id, "-f", batch_file],
      capture_output=True,
      text=True,
      check=True,
  )
  duration = time.time() - start_time
  logging.info(f"Batch execution completed in {duration:.2f}s: {res.stdout.strip()}")

  # Clean up batch file
  if os.path.exists(batch_file):
    os.remove(batch_file)

  # 6. Verify slide content and export sample thumbnails
  export_dir = "/tmp/slides_export"
  os.makedirs(export_dir, exist_ok=True)

  logging.info("Verifying slide thumbnails and text content...")
  for idx, s_id in enumerate(slide_ids):
    thumb_path = os.path.join(export_dir, f"slide_{idx + 1:02d}.png")
    thumb_res = subprocess.run(
        [GSLIDES_BIN, "export-thumbnail", pres_id, thumb_path, "--slide", s_id],
        capture_output=True,
        text=True,
    )
    if thumb_res.returncode == 0:
      logging.info(f"Exported Slide {idx + 1:02d} thumbnail -> {thumb_path}")
    else:
      logging.warning(f"Could not export thumbnail for slide {idx + 1}: {thumb_res.stderr}")

  logging.info("================================================================")
  logging.info("Google Voice Models Presentation Build Complete!")
  logging.info(f"Presentation ID : {pres_id}")
  logging.info(f"Google Slides URL: {pres_url}")
  logging.info("================================================================")
  return pres_id, pres_url


def main():
  try:
    pres_id, pres_url = execute_build_pipeline()
    print(f"\nSUCCESS: Presentation generated successfully!")
    print(f"Presentation ID: {pres_id}")
    print(f"Live Slides URL: {pres_url}\n")
  except Exception as e:
    logging.exception(f"Fatal error during presentation build: {e}")
    sys.exit(1)


if __name__ == "__main__":
  main()
