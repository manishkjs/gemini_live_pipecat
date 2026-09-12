# Context Engineering & Prompt Card Architecture Blueprint (Pragya)

## 1. Why JIT Prompt Cards Are the Optimal Architecture

### Outbound Telephony Unit Economics
In cold and warm outbound voice calls, **70% to 80% of calls terminate within the first 15 to 30 seconds** (unanswered, immediate drop-off, "busy hoon", or "not interested").

* **Monolithic Static Prompt (1,300–1,500 tokens):**
  Every dialed call pays the full 1.5k token tax on turn 1. When a caller hangs up 10 seconds into the greeting, the session burns full-size prompt costs on dead air.
* **Lean Root System Instruction (301 tokens):**
  Turn 1 costs only 301 tokens. If the caller hangs up immediately, session cost is reduced by ~75%.
* **Cost Aligns Directly with Caller Engagement:**
  You only pay the token cost for `SOP_02_DISCOVERY` (~412 tokens) if and when the caller agrees to talk. You only pay for `SOP_03_PINCODE` (~408 tokens) if and when they decide to visit a Lounge.

### Steady-State Phase Pacing (5–6 Turns per Card)
Cards are **not** per-turn micro-directives; they are **steady-state conversational playbooks governing 5 to 6 turns**:
* `PragyaPhaseTracker` is strictly monotonic and transitions fire at most 2–3 times in a complete call.
* Once `SOP_02_DISCOVERY` is injected, it remains active for 5–6 turns while the caller asks about engine feel, models, and pricing.
* Zero mid-phase prompt churn or re-injection occurs while the model is engaged inside a phase.

---

## 2. Core Context Engineering Improvements

### A. Root System Instruction: First-Turn Dead Weight
* **The Problem:**
  The current root SI spends ~120 tokens on opening mechanics:
  > *"Open with: नमस्ते, मैं Lamborghini India से Pragya... This first stage serves that one yes; cars, prices and PIN codes come later. If they sound busy, press once warmly..."*
  
  Once turn 1 concludes, this opening pitch is completely obsolete. Yet because it sits in the root SI, it is re-billed and re-attended to across every single subsequent turn (turns 2, 3, 4, 5, 6, 7, 8...).
* **Recommendations:**
  1. **Make Root SI Pure Persona & Register (~160 tokens):** Retain only identity (Pragya, 27, luxury concierge), Hinglish feminine grammar rules (`करती हूँ`, `बता रही हूँ`), conversational cadence (1–2 sentences, then pause), and natural luxury tone.
  2. **Handle Opening as Initial State:** Let the opening pitch live either as the initial turn utterance or as a dedicated first-turn prompt card (`SOP_01_OPENING`). Once caller engagement begins, the context cleanly transitions to `SOP_02_DISCOVERY` without permanent root clutter.

---

### B. Sensory Anchors vs. Spec Sheets in Discovery (`SOP_02`)
* **The Problem:**
  Current car descriptions read like a technical spec brochure:
  * `Revuelto, 1015 CV, zero to hundred in 2.5s`
  * `Temerario, 920 CV V8 hybrid, revs to ten thousand`
  * `Urus SE, 800 CV plug-in hybrid`
  
  Reciting "CV" (cavalli vapore) and horsepower figures sounds mechanical and un-conversational in spoken Hindi/Hinglish.
* **Recommendations:**
  Replace raw specs with **vivid conversational sensory pegs**:
  * **Revuelto:** Naturally aspirated V12 roar, iconic scissor doors, the ultimate flagship drama and presence.
  * **Temerario:** Twin-turbo V8 screaming to 10,000 RPM, pure cornering agility, the driver's hybrid supercar.
  * **Urus SE:** Twin-turbo V8 hybrid, full 5-seater luxury, silent electric city cruising, tackles broken Indian tarmac and tall speed breakers with zero stress.

---

### C. Luxury Context Anchors (Handling Real Indian Supercar Questions)
High-Net-Worth callers in India consistently raise three practical questions that current cards do not address:

1. **Indian Road Conditions & Ground Clearance:**
   * *Context Anchor:* Front suspension hydraulic lift system (+45mm clearance at the push of a button) navigates urban speed breakers and basement parking ramps without scraping.
2. **Delivery Timelines & Allocation:**
   * *Context Anchor:* 2026/2027 VIP allocation slots are strictly limited; the Lounge appointment locks their build slot and allows configuring bespoke *Ad Personam* finishes.
3. **Daily Usability in Traffic:**
   * *Context Anchor:* Urus SE and Temerario feature pure EV hybrid modes for silent, effortless crawling in Mumbai/Bangalore traffic before opening up on the highway.

* **Recommendation:**
  Add a compact 50-token **"Luxury Concierge Cheat-Sheet"** directly into `SOP_02`:
  * `Roads/Speed breakers: All models have hydraulic lift (+45mm); Urus handles broken roads effortlessly.`
  * `Delivery: Allocations are exclusive; the Lounge visit locks their build slot.`
  * `City drive: EV mode delivers quiet city comfort.`

---

### D. Replacing Canned Exit Gates with Natural Bridges
* **The Problem:**
  `SOP_02` currently ends with a rigid verbatim script:
  > *'Is gaadi ke baare mein aur kuch jaanna chahenge? Warna main dekh loon ki aapke sabse paas wala Lounge kaunsa padega?'*
  
  Native audio models sound robotic when repeating canned transition formulas verbatim.
* **Recommendation:**
  Replace script formulas with **situational intent guidelines**:
  * *Bridge to Visit:* Whenever the caller expresses admiration for a car or has had their questions answered, naturally bridge to experiencing the car in person:
    *"Revuelto ki cockpit seating aur exhaust note ko live experience karne ke liye, kya main aapke location ke paas private preview arrange kar doon?"*
  * Give the model the destination concept rather than locking it into rigid phrasing.

---

### E. Inversion of State Placement in Card Injections
* **The Problem:**
  Currently, `render_state_line()` appends captured state at the bottom of the injected card:
  > `[Card Directive...]`  
  > `They have already told you: PIN code 560048, car Temerario. Still needed to book: day, time.`  
  > `[ALWAYS BLOCK...]`
  
  Tucking the state between the body and footer allows the model to attend to generic instructions before noticing the missing state variables.
* **Recommendation:**
  Invert the hierarchy so the live state is the **top headline**:
  ```text
  [ACTIVE BRIEFING]
  ALREADY KNOWN: PIN 560048, Car: Temerario.
  STILL MISSING: Day and Time.
  ACTION: Acknowledge what they told you, ask only for the missing day/time.

  [STAGE GUIDELINES]
  ...
  ```
  In transformer attention mechanisms, placing the dynamic delta at the very beginning of the injected directive immediately anchors the model's next generated token to the missing variables.

---

### F. Card Deduplication & Scope Pinning
* When transitioning across phases, prepend an explicit focus anchor to prevent lingering attention on older cards:
  `[ACTIVE FOCUS: ORGANISING THE VISIT. Disregard earlier discovery directives; focus on locking day and time.]`
* Deduplicate the 139-token `ALWAYS_BLOCK` across injected cards. Keep permanent identity rules in the root SI and let each card carry only its situational 30-token guardrail.

---

## 3. Multi-Agent Dialectical Discussion & Next Steps

> **Note for Peer Agent:**  
> This file is our shared collaboration blackboard on `ui-changes-sep`. Please read the context engineering analysis above and append your critiques, counter-proposals, or refinements in the section below before any code changes are made.

### Open Questions for Peer Review:
1. **Turn 1 Opening Strategy:**  
   Do you agree with stripping the opening pitch from the Root SI down to pure identity & register (~160 tokens) and pushing `SOP_01_OPENING` dynamically on connect? Or does keeping the current 301-token Root SI provide better initial latency/stability for the first 15 seconds?
2. **State Hierarchy & Attention:**  
   In `SOP_03_PINCODE`, does placing `[ACTIVE BRIEFING]` (Already Known vs. Still Missing) at the very top of the card maximize attention on the missing delta, or does it risk overshadowing conversational warmth?
3. **Discovery Pacing (5–6 Turns):**  
   Are the proposed 3 sensory hooks (V12 roar/scissors, 10k RPM agility, Urus road clearance) and the 50-token luxury cheat-sheet sufficient to prevent Pragya from looping during a 5–6 turn discovery phase? What edge-case questions from Indian HNW buyers are missing?

---

### Peer Agent Feedback & Critique:
*(Peer agent: please write your thoughts, critique, and proposed adjustments below)*

