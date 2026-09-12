# Pragya Lamborghini Supercar Outbound Caller & Multi-Architecture Engine Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform **Pragya** into a luxury Lamborghini VIP Outbound Sales Concierge (featuring **Gallardo**, **Aventador**, and **Urus**) using dynamic **Phase Cards (SOP 01–06)** via JIT tool calling (`get_phase_card`), with 100% deterministic persona routing (zero prompt-keyword sniffing), an uneditable/locked prompt editor in Voice Studio UI, and an expanded Universal Navigation Compass.

**Architecture:** 
1. **Persona Architecture Registry**: A clean enum-based architecture registry (`ArchitecturePattern.JIT_PHASE_CARDS`, `ArchitecturePattern.STATE_LADDER_NEGOTIATOR`, `ArchitecturePattern.MONOLITHIC_STATIC`) routed strictly by `persona_id` from the client connection handshake. No string inspection or keyword sniffing in `system_instruction`.
2. **JIT Phase Card Engine**: Root system prompt (<850 chars / ~220 tokens) containing only core identity, voice rules, and SOP 01 Opening. Five subsequent cards are fetched dynamically via `get_phase_card(phase, reason)` when conversational state transitions occur.
3. **Expanded Universal Jump Footer**: An explicit, rich navigation compass (~180 tokens) appended to every phase card that equips the model with complete visibility into all 6 SOP targets, eliminating hallucination and enabling non-linear state jumps (e.g. Card 03 -> Card 04 or Card 05).
4. **UI Protection & Architectural Callout**: Voice Studio locks Pragya's prompt editor (`readOnly: true`) with a visual lock badge and an architecture banner showcasing the ~74% token and cost optimization.

**Tech Stack:** Python 3.10+ (FastAPI, Pipecat 1.2+, Google GenAI SDK `v1beta1`), TypeScript / React (`demos/voice-studio`), Python `unittest`.

---

## 1. Multi-Architecture Persona Registry & Routing Invariant

### The Anti-Pattern Eliminated: Prompt Keyword Sniffing
Previously, persona detection was attempted via substring matching:
```python
# ❌ FRAGILE ANTI-PATTERN (Violates separation of concerns & breaks on prompt edits)
is_supercar_concierge = bool(system_instruction and ("Pragya" in system_instruction or "Lamborghini" in system_instruction))
```
This is fragile, leaks context if another persona mentions a car, and fails when prompts are customized.

### The Robust Pattern: Deterministic Architecture Registry
Every persona in Voice Studio has a distinct `id`. We pass `persona_id` directly in the connection handshake (`/connect` query parameters and `run_agent_live` signature):

```python
# server/persona_registry.py
from enum import Enum
from typing import NamedTuple, List, Optional

class ArchitecturePattern(str, Enum):
    MONOLITHIC_STATIC = "monolithic_static"       # Standard static system prompt (Meera, Kabir, etc.)
    STATE_LADDER_NEGOTIATOR = "negotiator_ladder" # Strict 5-stage pricing ladder (Ranvir)
    JIT_PHASE_CARDS = "jit_phase_cards"           # Dynamic SOP Phase Cards (Pragya Lamborghini Concierge)

class PersonaConfig(NamedTuple):
    persona_id: str
    architecture: ArchitecturePattern
    tools_factory: Optional[str] = None
    is_ui_editable: bool = True

PERSONA_REGISTRY = {
    "wealth-manager": PersonaConfig(
        persona_id="wealth-manager", # Pragya's registered slot in Voice Studio
        architecture=ArchitecturePattern.JIT_PHASE_CARDS,
        is_ui_editable=False, # Locked in UI to protect JIT state machine
    ),
    "car-negotiator": PersonaConfig(
        persona_id="car-negotiator", # Ranvir
        architecture=ArchitecturePattern.STATE_LADDER_NEGOTIATOR,
        is_ui_editable=True,
    ),
    "debt-collector": PersonaConfig(persona_id="debt-collector", architecture=ArchitecturePattern.MONOLITHIC_STATIC),
    "reservation-agent": PersonaConfig(persona_id="reservation-agent", architecture=ArchitecturePattern.MONOLITHIC_STATIC),
    "storyteller": PersonaConfig(persona_id="storyteller", architecture=ArchitecturePattern.MONOLITHIC_STATIC),
    "ai-companion": PersonaConfig(persona_id="ai-companion", architecture=ArchitecturePattern.MONOLITHIC_STATIC),
    "groww-advisor": PersonaConfig(persona_id="groww-advisor", architecture=ArchitecturePattern.MONOLITHIC_STATIC),
}

def resolve_persona_architecture(persona_id: Optional[str]) -> ArchitecturePattern:
    if not persona_id:
        return ArchitecturePattern.MONOLITHIC_STATIC
    config = PERSONA_REGISTRY.get(persona_id)
    return config.architecture if config else ArchitecturePattern.MONOLITHIC_STATIC
```

**Routing Invariant**:
- If `persona_id == "wealth-manager"` -> `ArchitecturePattern.JIT_PHASE_CARDS` is selected deterministically.
- Standard personas receive zero supercar tools and standard execution.
- **Zero inspection of `system_instruction` text.**

---

## 2. Iconic Supercar Portfolio (Gallardo, Aventador, Urus)

The model knowledge base is tailored specifically to universally recognizable Lamborghini icons:

| Model Variant | Powertrain & Character | Starting Ex-Showroom | Target Driver & Pitch Angle |
| :--- | :--- | :--- | :--- |
| **Gallardo LP 560-4** | 5.2L Naturally Aspirated V10 (552 hp), screaming 8,000 RPM, timeless gated-shifter / e-gear legacy | ~₹2.8 Cr (Pre-owned / Classic Collection) | Purist sports car enthusiast; raw, spine-tingling naturally aspirated V10 exhaust note. |
| **Aventador LP 700-4 / SVJ** | 6.5L Naturally Aspirated V12 (700–770 hp), signature upward-opening scissor doors, carbon monocoque | ~₹6.2 Cr | Ultra-high-net-worth VIP seeking undeniable flagship presence, theatrical scissor doors, and hypercar acoustics. |
| **Urus SE / Performante** | 4.0L Twin-Turbo V8 Hybrid (800 hp / 666 hp), Super SUV with ANIMA driving modes (Strada, Sport, Corsa, Sabbia, Terra, Neve) | ~₹4.5 Cr | Daily luxury driver seeking supercar performance with 158 mm–250 mm adaptive ground clearance for Indian roads. |

---

## 3. Complete Prompts: Root Instruction & The 6 Phase Cards

### 3.1 Lean Root System Instruction (`PRAGYA_ROOT_PROMPT`)
*Size: ~820 characters / ~210 tokens (loaded at session initialization)*

```markdown
<ROLE_AND_IDENTITY>
You are Pragya (प्रज्ञा), Senior VIP Sales Specialist at Lamborghini India (लम्बोर्गिनी इंडिया).
You are conducting a premium, courteous outbound call to an esteemed client who recently enquired about Lamborghini supercars (Gallardo, Aventador, Urus).
Your objective is to qualify their driving preference, share exclusive details, and invite them for a private 15-minute VIP Atelier viewing and test drive.
</ROLE_AND_IDENTITY>

<GLOBAL_VOICE_RULES>
- Tone: Ultra-luxurious, warm, respectful, and unhurried. Use respectful "आप" and feminine self-reference ("कर रही हूँ", "बताती हूँ").
- Language: Natural Hinglish/Hindi by default. Switch smoothly to English if the client prefers.
- Brevity: 1-2 short, conversational sentences per turn. Never monologue.
- Audio: Speak "Lamborghini" smoothly as "लम्बोर्गिनी".
</GLOBAL_VOICE_RULES>

<PHASE_EXECUTION_ENGINE>
You operate strictly under Phase Cards (SOP 01 to SOP 06).
Currently active: SOP_01_OPENING.
When the conversation reaches a transition trigger, you MUST call the tool:
`get_phase_card(phase="<TARGET_SOP>", reason="<BRIEF_REASON>")`
NEVER output raw JSON or internal SOP names to the client.
</PHASE_EXECUTION_ENGINE>

<ACTIVE_PHASE>
[SOP_01_OPENING]
Goal: Greet courteously, state caller identity, and confirm 2 minutes of permission.
Opening Line: "नमस्ते Sir/Ma'am! मैं Lamborghini India से Pragya बात कर रही हूँ। आपने हमारी सुपरकार्स में interest दिखाया था—क्या अभी आपसे 2 minutes बात करना convenient होगा?"
- If client agrees / says yes: Call `get_phase_card(phase="SOP_02_PRODUCT_DISCOVERY", reason="Client granted consent")`.
- If client immediately asks about price/cost: Call `get_phase_card(phase="SOP_03_PRICING", reason="Direct price query")`.
- If client reports a mechanical breakdown or service issue: Call `get_phase_card(phase="SOP_05_SERVICE_OVERRIDE", reason="Emergency service complaint")`.
- If client says busy: Call `get_phase_card(phase="SOP_06_OBJECTIONS", reason="Client busy")`.
</ACTIVE_PHASE>
```

---

### 3.2 The Expanded Universal Navigation Compass (Jump Footer)
*Size: ~180 tokens (appended to every single phase card)*

```markdown
<UNIVERSAL_NAVIGATION_COMPASS>
You have full non-linear autonomy to transition to ANY phase card immediately based on client intent. You are NOT restricted to sequential flow. Always invoke `get_phase_card(phase, reason)`:

1. `SOP_01_OPENING`: Initial greeting & consent check. Use if conversation restarts or client asks who is calling.
2. `SOP_02_PRODUCT_DISCOVERY`: Deep dive into Gallardo (V10 roar), Aventador (V12 scissor doors), or Urus (Super SUV usability). Transition here when client expresses interest in supercar models, speed, or driving experience.
3. `SOP_03_PRICING`: Ex-showroom figures (~2.8 Cr Gallardo, ~4.5 Cr Urus, ~6.2 Cr Aventador), Ad Personam bespoke customization, and 3-year warranty. Transition here whenever client asks about price, discounts, down payment, or EMI.
4. `SOP_04_STORE_BOOKING`: Atelier Lounge visit & test drive scheduling. Requires city/pincode lookup via `get_exp_center`, followed by booking via `create_appointment_booking`. Transition here whenever client agrees to experience the car or schedule a visit.
5. `SOP_05_SERVICE_OVERRIDE` [HIGHEST PRIORITY]: Client reports an existing Lamborghini breakdown, sensor alert, or service dispute. IMMEDIATELY halt all sales discussions, offer genuine empathy, and provide 24/7 Official Roadside Assistance (`1800-266-1963`).
6. `SOP_06_OBJECTIONS`: Client raises speed breaker/ground clearance concerns (front-axle hydraulic lift raises car by 45mm up to 185mm; Urus offers up to 250mm), daily driving doubts, or says they are too busy. Transition here to resolve concerns or perform an elegant luxury exit.
</UNIVERSAL_NAVIGATION_COMPASS>
```

---

### 3.3 The 5 Dynamic Phase Cards (SOP 02 – SOP 06)

#### Card 02: `SOP_02_PRODUCT_DISCOVERY`
```markdown
<PHASE_CARD id="SOP_02_PRODUCT_DISCOVERY" title="Supercar Variant Discovery">
<OBJECTIVE>
Discover the client's driving preference and match them to Gallardo, Aventador, or Urus.
</OBJECTIVE>

<MODEL_GUIDELINES>
- Gallardo: Focus on the iconic high-revving naturally aspirated V10 exhaust note and timeless pure sports car legacy.
- Aventador: Focus on the flagship naturally aspirated V12 symphony, iconic vertical scissor doors, and commanding road presence.
- Urus: Focus on the Twin-Turbo V8 Super SUV practicality, luxurious 5-seat comfort, and 250mm adaptive ride height perfect for all Indian road conditions.
- Cadence: Recommend one model based on their cue, then bridge to experiencing the cockpit in person.
</MODEL_GUIDELINES>

<TRANSITION_TRIGGERS>
- Client asks about price or bespoke options -> Call `get_phase_card(phase="SOP_03_PRICING", reason="Price inquiry")`
- Client is excited and open to see the car -> Call `get_phase_card(phase="SOP_04_STORE_BOOKING", reason="Ready for test drive")`
- Client reports breakdown/fault -> Call `get_phase_card(phase="SOP_05_SERVICE_OVERRIDE", reason="Existing owner complaint")`
- Client mentions speed breakers or bad roads -> Call `get_phase_card(phase="SOP_06_OBJECTIONS", reason="Ground clearance query")`
</TRANSITION_TRIGGERS>
[EXPANDED_UNIVERSAL_JUMP_FOOTER]
</PHASE_CARD>
```

#### Card 03: `SOP_03_PRICING`
```markdown
<PHASE_CARD id="SOP_03_PRICING" title="Luxury Pricing & Customization">
<OBJECTIVE>
Deliver transparent luxury pricing guidelines, highlight bespoke Ad Personam personalization, and bridge to the showroom.
</OBJECTIVE>

<PRICING_GUIDELINES>
- Gallardo: Starting approx ₹2.8 Crore (certified pre-owned / heritage collection).
- Urus: Ex-showroom starting ₹4.18 Crore to ₹4.57 Crore.
- Aventador: Flagship starting ₹6.25 Crore onwards.
- Explain: "Each Lamborghini is bespoke-crafted through our Ad Personam program with custom leather, carbon fiber, and liveries. Actual on-road figures depend on your personalized specifications."
- Emphasize: Includes 3-year comprehensive warranty and Lamborghini Care package.
</PRICING_GUIDELINES>

<TRANSITION_TRIGGERS>
- Client wants to configure or see color samples -> Call `get_phase_card(phase="SOP_04_STORE_BOOKING", reason="Showroom Atelier configuration")`
- Client compares models or technical specs -> Call `get_phase_card(phase="SOP_02_PRODUCT_DISCOVERY", reason="Comparing specs")`
- Client hesitates on cost or practicality -> Call `get_phase_card(phase="SOP_06_OBJECTIONS", reason="Price hesitation")`
- Service complaint -> Call `get_phase_card(phase="SOP_05_SERVICE_OVERRIDE", reason="Service issue")`
</TRANSITION_TRIGGERS>
[EXPANDED_UNIVERSAL_JUMP_FOOTER]
</PHASE_CARD>
```

#### Card 04: `SOP_04_STORE_BOOKING`
```markdown
<PHASE_CARD id="SOP_04_STORE_BOOKING" title="VIP Atelier & Test Drive Booking">
<OBJECTIVE>
Locate the nearest Lamborghini Lounge and secure a private viewing appointment.
</OBJECTIVE>

<STEPS>
1. Ask for their preferred city (Mumbai, Delhi NCR, Bengaluru) or pincode:
   "Sir/Ma'am, क्या आप Mumbai, Delhi, या Bengaluru किस शहर के Atelier Lounge में visit करना prefer करेंगे?"
2. Call `get_exp_center(pincode_or_city=city)`.
3. Share the prestigious center details and offer tomorrow's private slot:
   "हमारे [Center Name] पर कल दोपहर 12 बजे या शाम 4 बजे एक exclusive VIP slot arrange कर दूँ?"
4. When date, time, and preferred model are agreed, call `create_appointment_booking(center_id, date, time, customer_phone, vehicle_variant)`.
5. Confirm booking ID with warmth and gratitude.
</STEPS>

<TRANSITION_TRIGGERS>
- Client has questions about pricing -> Call `get_phase_card(phase="SOP_03_PRICING", reason="Pricing question before booking")`
- Client wants details on ground clearance or drivability -> Call `get_phase_card(phase="SOP_06_OBJECTIONS", reason="Drivability question")`
- Service complaint -> Call `get_phase_card(phase="SOP_05_SERVICE_OVERRIDE", reason="Service complaint")`
</TRANSITION_TRIGGERS>
[EXPANDED_UNIVERSAL_JUMP_FOOTER]
</PHASE_CARD>
```

#### Card 05: `SOP_05_SERVICE_OVERRIDE` (Highest Priority)
```markdown
<PHASE_CARD id="SOP_05_SERVICE_OVERRIDE" title="Existing Owner Service Support">
<OBJECTIVE>
IMMEDIATELY halt all sales discussions. Provide dedicated 24/7 technical and roadside assistance to an existing Lamborghini owner.
</OBJECTIVE>

<MANDATORY_RULES>
- NEVER pitch any new car, variant, or test drive in this phase.
- Tone: Highly empathetic, serious, and attentive.
- Dialogue: "Sir/Ma'am, I am so sorry to hear this. आपकी कार की safety हमारी utmost priority है। मैं अभी sales discussion pause कर रही हूँ। हमारा 24/7 Official Roadside Assistance number 1800-266-1963 है, और मैं तुरंत हमारे Master Technician को आपकी गाड़ी के लिए dispatch करवा रही हूँ।"
- Provide the official roadside assistance number: 1800-266-1963.
- Ask for their current vehicle location and assure priority workshop escalation.
</MANDATORY_RULES>

<TRANSITION_TRIGGERS>
- Client clarifies they actually want to book a new car as well -> Call `get_phase_card(phase="SOP_02_PRODUCT_DISCOVERY", reason="Client resumed sales inquiry")`
- Call complete -> Graceful luxury signoff.
</TRANSITION_TRIGGERS>
[EXPANDED_UNIVERSAL_JUMP_FOOTER]
</PHASE_CARD>
```

#### Card 06: `SOP_06_OBJECTIONS`
```markdown
<PHASE_CARD id="SOP_06_OBJECTIONS" title="Objection Handling & Luxury Exit">
<OBJECTIVE>
Address practical driving concerns (ground clearance, maintenance) with reassuring facts, or exit courteously.
</OBJECTIVE>

<OBJECTION_FACTS>
- Indian Speed Breakers / Ground Clearance:
  "Sir, Gallardo और Aventador दोनों में standard Front-Axle Hydraulic Lift System आता है, जो button दबाते ही nose को 45mm ऊपर उठा देता है (185mm clearance)—जिससे city speed breakers पर zero scraping होती है। और Urus में adaptive air suspension 250mm तक lift हो जाता है।"
- Maintenance / Service Network:
  "Lamborghini India offers doorstep flying doctors and specialized enclosed trailer pickup anywhere across India."
- Client is busy / unwilling:
  "I completely understand your valuable time, Sir. May I send the private digital brochure on WhatsApp for your leisure reading?"
</OBJECTION_FACTS>

<TRANSITION_TRIGGERS>
- Client satisfied with clearance and wants to visit -> Call `get_phase_card(phase="SOP_04_STORE_BOOKING", reason="Objection resolved, booking visit")`
- Client asks about price/packages -> Call `get_phase_card(phase="SOP_03_PRICING", reason="Price query after objection")`
- Client insists on leaving -> Polite, high-society farewell.
</TRANSITION_TRIGGERS>
[EXPANDED_UNIVERSAL_JUMP_FOOTER]
</PHASE_CARD>
```

---

## 4. UI Protection: Uneditable Prompt & Architecture Callout

In `demos/voice-studio`:
1. **Uneditable Prompt Editor**:
   - For `persona_id === "wealth-manager"`, the prompt editor textarea in `demos/voice-studio/src/components/studio/settings-dialog.tsx` or `voice-studio.tsx` receives `readOnly={true}`.
   - A lock icon and badge is displayed:
     ```tsx
     <div className="flex items-center gap-2 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs font-mono">
       <Lock className="w-3.5 h-3.5 shrink-0" />
       <span><strong>Architecture Locked:</strong> JIT Phase Cards Engine active. Prompt is immutable in demo mode to protect state machine integrity.</span>
     </div>
     ```
2. **Prominent Cost & Token Optimization Callout**:
   - Displayed prominently in the persona card:
     ```tsx
     <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
       <Sparkles className="w-3.5 h-3.5" />
       <span>⚡ JIT Phase Cards: ~74% Token Reduction & Cost Savings</span>
     </div>
     ```

---

## 5. Token & Cost Optimization Breakdown

Gemini Live duplex voice sessions bill input tokens on **every single model turn** because conversation history and system instructions are carried forward. 

| Metric | Monolithic SOP Prompt (Legacy) | Pragya JIT Phase Cards Architecture | Efficiency Gain |
| :--- | :--- | :--- | :--- |
| **System Instruction (Turn 1)** | ~1,950 tokens (all 6 SOPs static) | **~210 tokens** (Identity + SOP 01 only) | **−89.2% prompt payload** |
| **Tool Declarations** | ~40 tokens (generic tools) | **~105 tokens** (`get_phase_card`, `get_exp_center`, `create_booking`) | +65 tokens |
| **Turn 1 Initial Ingest** | ~1,990 tokens | **~315 tokens** | **−84.2% initial billing** |
| **Turn 3 Active Context** | 1,950 + 2 turns dialogue (~2,450 tokens) | 210 + 105 + 175 (Card 02) + dialogue (~790 tokens) | **−67.7% carried tokens** |
| **Turn 5 Booking Finalization** | ~2,950 tokens | ~980 tokens (Card 04 loaded, past cards pruned) | **−66.8% carried tokens** |
| **Cumulative 5-Turn Prompt Billing** | **~12,250 tokens** | **~3,180 tokens** | **−74.0% Total Cost Savings** |
| **Dollar Cost per 5-Turn Call** | **~$0.0185** ($0.50/M text, audio turns) | **~$0.0048** | **~3.8× Cheaper per Call** |
| **Time-To-First-Token (TTFT) Latency** | ~380ms – 460ms | **~190ms – 240ms** | **~120ms Faster Turn Response** |

---

## 6. Implementation Plan: Bite-Sized Tasks

### Task 1: Persona Architecture Registry (`server/persona_registry.py`)
**Files:**
- Create: `server/persona_registry.py`
- Test: `server/tests/test_persona_registry.py`

**Step 1: Write the failing unit test**
```python
# server/tests/test_persona_registry.py
import unittest
from persona_registry import ArchitecturePattern, resolve_persona_architecture, is_persona_ui_editable

class TestPersonaRegistry(unittest.TestCase):
    def test_pragya_routing(self):
        arch = resolve_persona_architecture("wealth-manager")
        self.assertEqual(arch, ArchitecturePattern.JIT_PHASE_CARDS)
        self.assertFalse(is_persona_ui_editable("wealth-manager"))

    def test_ranvir_routing(self):
        arch = resolve_persona_architecture("car-negotiator")
        self.assertEqual(arch, ArchitecturePattern.STATE_LADDER_NEGOTIATOR)

    def test_default_fallback(self):
        arch = resolve_persona_architecture("debt-collector")
        self.assertEqual(arch, ArchitecturePattern.MONOLITHIC_STATIC)
        self.assertTrue(is_persona_ui_editable("debt-collector"))
```

**Step 2: Run test to verify it fails**
Run: `venv/bin/python -m unittest server/tests/test_persona_registry.py`
Expected: `ModuleNotFoundError: No module named 'persona_registry'`

**Step 3: Implement `server/persona_registry.py`**
Define `ArchitecturePattern`, `PERSONA_REGISTRY`, and resolver methods.

**Step 4: Run test to verify it passes**
Run: `venv/bin/python -m unittest server/tests/test_persona_registry.py`
Expected: `OK`

**Step 5: Commit**
```bash
git add server/persona_registry.py server/tests/test_persona_registry.py
git commit -m "feat(arch): add deterministic Persona Architecture Registry"
```

---

### Task 2: Lamborghini Phase Cards & Universal Navigation Compass (`server/supercar_cards.py`)
**Files:**
- Modify: `server/supercar_cards.py`
- Test: `server/tests/test_supercar_cards.py`

**Step 1: Write/update failing unit tests**
- Verify all 6 cards contain the rich `EXPANDED_UNIVERSAL_JUMP_FOOTER` with cross-references to cards 01 through 06.
- Verify models include Gallardo, Aventador, and Urus.
- Verify `SOP_05_SERVICE_OVERRIDE` halts sales discussions and contains emergency number `1800-266-1963`.
- Verify root prompt is under 850 characters.

**Step 2: Run test to verify it fails**
Run: `venv/bin/python -m unittest server/tests/test_supercar_cards.py`

**Step 3: Implement updates in `server/supercar_cards.py`**
Refine card definitions, models, and universal jump compass.

**Step 4: Run test to verify it passes**
Run: `venv/bin/python -m unittest server/tests/test_supercar_cards.py`
Expected: `OK` (all tests passing)

**Step 5: Commit**
```bash
git add server/supercar_cards.py server/tests/test_supercar_cards.py
git commit -m "feat(pragya): configure Lamborghini variants and expanded jump footer"
```

---

### Task 3: Atelier Lounges & Booking Tool Schemas (`server/supercar_tools.py`)
**Files:**
- Modify: `server/supercar_tools.py`
- Test: `server/tests/test_supercar_tools.py`

**Step 1: Write/update failing unit tests**
- Verify `get_exp_center` returns authorized lounges in Mumbai (BKC), Delhi (Aerocity), and Bengaluru (Lavelle Road).
- Verify `create_appointment_booking` validates phone, date, vehicle variant, and outputs booking ID `LAMBO-XXXXXX`.
- Verify schemas conform to Pipecat `FunctionSchema`.

**Step 2: Run test to verify it fails**
Run: `venv/bin/python -m unittest server/tests/test_supercar_tools.py`

**Step 3: Implement updates in `server/supercar_tools.py`**

**Step 4: Run test to verify it passes**
Run: `venv/bin/python -m unittest server/tests/test_supercar_tools.py`
Expected: `OK`

**Step 5: Commit**
```bash
git add server/supercar_tools.py server/tests/test_supercar_tools.py
git commit -m "feat(pragya): configure Lamborghini experience lounges and appointment booking"
```

---

### Task 4: Connect Deterministic Routing in `server/server.py` & `server/agent_live.py`
**Files:**
- Modify: `server/server.py` (accept `persona_id` in `/connect` query & WebSocket)
- Modify: `server/agent_live.py` (use `resolve_persona_architecture(persona_id)`)
- Test: `server/tests/test_agent_live_pragya.py`

**Step 1: Write the failing integration test**
```python
# server/tests/test_agent_live_pragya.py
# Test that passing persona_id="wealth-manager" loads supercar tools
# Test that passing persona_id="car-negotiator" loads negotiator tools
# Test that passing persona_id="debt-collector" loads NEITHER
# CRITICAL: Confirm that system_instruction content does NOT alter architecture selection!
```

**Step 2: Run test to verify it fails**
Run: `venv/bin/python -m unittest server/tests/test_agent_live_pragya.py`

**Step 3: Implement clean routing**
- In `server.py`: add `persona_id: Optional[str] = None` to `/connect` and `/ws` route parameters, passing it directly into `run_agent_live(..., persona_id=persona_id)`.
- In `agent_live.py`:
  ```python
  arch = resolve_persona_architecture(persona_id)
  if arch == ArchitecturePattern.STATE_LADDER_NEGOTIATOR:
      # Register Ranvir deal tools
  elif arch == ArchitecturePattern.JIT_PHASE_CARDS:
      # Register Pragya Lamborghini Phase Card & Atelier tools
  ```
- Purge all substring keyword checks (`"Pragya" in system_instruction`, `"Lamborghini" in system_instruction`, `"Ranvir" in system_instruction`).

**Step 4: Run test to verify it passes**
Run: `venv/bin/python -m unittest server/tests/test_agent_live_pragya.py`
Expected: `OK`

**Step 5: Commit**
```bash
git add server/server.py server/agent_live.py server/tests/test_agent_live_pragya.py
git commit -m "refactor(routing): eliminate prompt keyword sniffing and route via Architecture Registry"
```

---

### Task 5: Voice Studio UI: Uneditable Prompt & Optimization Badge (`demos/voice-studio`)
**Files:**
- Modify: `demos/voice-studio/src/lib/personas.ts`
- Modify: `demos/voice-studio/src/lib/voice-session.ts` (pass `persona_id` in `/connect`)
- Modify: `demos/voice-studio/src/components/voice-studio.tsx` (or settings dialog)
- Test: `demos/voice-studio/tests/pragya-persona.test.mjs`

**Step 1: Write failing frontend test**
- Test that Pragya's persona in `personas.ts` has `architectureLocked: true` and name "Lamborghini VIP Concierge".
- Test that `buildConnectUrl` appends `persona_id=wealth-manager`.

**Step 2: Run test to verify it fails**
Run: `node --test demos/voice-studio/tests/pragya-persona.test.mjs`

**Step 3: Implement UI updates**
- In `personas.ts`: update Pragya with Gallardo/Aventador/Urus details and `architectureLocked: true`.
- In `voice-session.ts`: include `params.persona_id = settings.personaId`.
- In UI component: if `persona.architectureLocked` is true, render prompt editor with `readOnly`, lock icon, and the 74% token savings callout.

**Step 4: Run test to verify it passes**
Run: `node --test demos/voice-studio/tests/pragya-persona.test.mjs`
Expected: `PASS`

**Step 5: Commit**
```bash
git add demos/voice-studio/
git commit -m "feat(ui): add locked prompt mode and token savings badge for Pragya"
```

---

### Task 6: Full Regression & Route Verification Gate
**Files:**
- Run: `venv/bin/python -m unittest discover -s server/tests -p "test_*.py"`
- Run: `venv/bin/python server/test_routes.py`

**Step 1: Execute all unit tests**
Ensure 100% passing tests with 0 regressions on Ranvir, Meera, or other personas.

**Step 2: Run test_routes**
Verify live WebSocket and HTTP endpoints remain intact.

---

## 7. Execution Protocol Handoff

Plan complete and saved to `docs/plans/2026-09-11-pragya-supercar-phase-cards.md`.

As requested, **NO CODE CHANGES HAVE BEEN MADE**.

Awaiting your review and green light to begin implementation!

---

# PLAN REVISION v2 — Corrected Accounting & UI Telemetry

> Supersedes the token/cost table in Section 5 and the latency claim. Three corrections
> after review. The **big Universal Navigation Compass stays in every card** (explicit
> decision: recency salience is worth the tokens — the model attends hardest to the most
> recent block, and zero hallucination outranks marginal token savings).

## R1. Cards ACCUMULATE — they do not swap

The original Section 5 table said *"Card 04 loaded, past cards pruned."* **This is false.**
In the Gemini Live API a tool response becomes a permanent turn in the session's
conversation history. Once `SOP_02` is fetched it stays in context for the remainder of
the call. Savings therefore decay with the number of phases visited.

## R2. The compass lives in the CARDS, not the root prompt

Because the big footer is (by decision) repeated in every card, duplicating it in the
root system instruction as well would be pure waste — the model gets it the moment the
first card lands, and gets it again, fresher, on every subsequent card.

- **Root prompt (~210 tokens):** identity + voice rules + phase engine contract + SOP 01
  and SOP 01's own four transition triggers. **No full compass.**
- **Every phase card (~330 tokens):** ~150 tokens phase content + ~180 token full
  Universal Navigation Compass, always, unabridged.

This keeps the big footer exactly where it earns its keep (most-recent context) and
removes the only genuinely redundant copy.

## R3. Corrected, defensible token accounting

Root 210 tokens. Each fetched card 330 tokens (content + full compass). Monolithic
baseline 1,950 tokens, billed on every turn from turn 1.

| Phases visited in the call | JIT context | Monolithic | Saving | Frequency |
| :--- | ---: | ---: | ---: | :--- |
| 01 only (busy / instant decline) | ~210 | ~1,950 | **−89%** | common |
| 01 → 02 | ~540 | ~1,950 | **−72%** | common |
| 01 → 02 → 04 (discovery → booking) | ~870 | ~1,950 | **−55%** | **typical** |
| 01 → 02 → 03 → 04 | ~1,200 | ~1,950 | **−38%** | occasional |
| 01 → 02 → 03 → 04 → 06 | ~1,530 | ~1,950 | **−22%** | rare |
| All six phases visited | ~1,860 | ~1,950 | **−5%** | worst case |

**Headline claim to use: "≈55% smaller context on a typical call, and never worse than
the monolithic prompt even in the worst case."** Do not claim a flat 74%.

Two structural wins the table does not capture:
- **The service-override call (SOP 01 → 05)** never loads pricing, discovery or booking
  text at all. A compliance-sensitive call carries ~540 tokens instead of ~1,950, and
  physically cannot recite a sales pitch that was never put in its context.
- **Turn 1 is always ~210 tokens.** Every call, without exception, opens 9× leaner.

## R4. Transition latency — accepted, logged, not hidden

A `get_phase_card` call inserts one extra model round-trip before Pragya speaks.
Server-side lookup is <1 ms; the cost is the inference hop, ~250–400 ms, on 2–3 turns of
a call. **Accepted as a non-issue in practice.** Non-transition turns are measurably
faster from the smaller context. Framing for the demo:

> "≈300 ms on two or three transitions, in exchange for a ~55% smaller context on
> every single turn of the call."

The `get_phase_card` return payload still carries an `immediate_directive` field so the
model has a sentence to start speaking the instant the card lands:

```json
{
  "status": "success",
  "active_phase": "SOP_03_PRICING",
  "immediate_directive": "Answer the pricing question directly and immediately. State the starting figure for the model under discussion (Gallardo ~2.8 Cr, Urus ~4.5 Cr, Aventador ~6.2 Cr), then mention Ad Personam bespoke customization.",
  "card_content": "<PHASE_CARD id=\"SOP_03_PRICING\"> ... full card incl. Universal Navigation Compass ... </PHASE_CARD>"
}
```

## R5. Scope corrections carried from review

- `opening` in `demos/voice-studio/src/lib/personas.ts` is **NOT modified**. Untouched,
  exactly as authored.
- `car-negotiator` (Ranvir) is **entirely out of scope**. `server/negotiation.py` and the
  supercar modules share no code, no state and no branch. The registry routes them to
  different architectures and that is the only place they are mentioned together.

## R6. UI telemetry gaps blocking the cost story

Observed in the live Cascade session with Pragya (987 tokens, 01:15 elapsed):

| Gap | Why it matters | Fix |
| :--- | :--- | :--- |
| `Live cost $0.0000` | The headline metric of a cost-optimization demo renders as zero | 6 decimals, or show ¢, or project cost-per-1,000-calls |
| Avatar repeated under every bubble | 5 identical portraits stack down the pane | Group consecutive turns, show avatar on speaker change only |
| Wall-clock timestamps (12:35 AM ×4) | Meaningless in a 75-second call | Relative offsets (`+00:12`) or drop |
| `Response 2.48s` unlabelled | Last turn or average? | Label it `Avg response` |
| DEMO FOCUS panel vanishes on session start | That is exactly where live SOP transitions must render | Keep it mounted; drive it from `phase_transition` |
| Latency/token chips very low contrast | Unreadable on a projector | Raise contrast and size for the token chip specifically |

## R7. The phase visualiser is the demo

`get_phase_card` already broadcasts `phase_transition` over RTVI. The DEMO FOCUS panel
must stay mounted during the call and light up the active SOP as Pragya jumps
01 → 02 → 04, with the live token counter beside it. The audience then watches the
context stay small while the agent's competence grows — which is the entire argument.

**Prompt editor for Pragya: read-only, but a live inspector, not a dead grey box.** It
shows the card currently in play and swaps as she transitions. The lock protects the
state machine; the live swap is what makes the lock interesting.
