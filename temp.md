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

---

## 4. Review response — 12 September 2026

Reviewed the blueprint and the three peer-review questions at remote commit `0a79422` against the current implementation. The remote changes since `c285590` affect this document only. This section preserves the original proposals above and records agreements, corrections, and decisions for discussion; it does not authorize an architecture change.

**Verdict: the JIT direction fits this demo, but the cost argument and several implementation assumptions need correction before we use them in a customer presentation.** Keep the current UI structure, persona architectures, and Observability entry point. Improve routing and measurement before promising savings.

### Direct answers to the three peer-review questions

1. **Opening:** keep the existing root opening for this iteration. A dynamic opening introduces a startup-ordering dependency, and appending it does not itself remove it from retained context. Measure an alternative startup flow before claiming either latency or cost benefits.
2. **State first:** test a compact known/missing/next-action preface, followed by the conversational brief. Clear facts and warmth can coexist; neither attention nor naturalness is guaranteed by position alone. Correct state capture matters more than heading order.
3. **Discovery:** three hooks are useful entry points, not enough evidence of a loop-free five-turn conversation. Evaluate follow-up questions, comparisons, ownership/service problems, uncertain delivery dates, and a caller who declines a visit. Answer from verified facts, acknowledge uncertainty, and avoid repeatedly offering a visit after a refusal. Do not pad a phase to a target turn count.

### What I agree with

| Proposal | Assessment / implementation boundary |
| --- | --- |
| Lean root plus stage briefs | Good fit for deferring instructions until relevant. Four visible phases currently mean one opening in the root plus three injected cards. |
| More conversational discovery | Agree. Lead with one relevant sensory detail; retain verified specifications for callers who ask. The current card already asks for a sensory detail, so this is a refinement. |
| Natural bridges instead of verbatim exits | Agree. Make the next step optional and follow the caller's intent; admiration alone is not consent to book. |
| Put known/missing information near the top | Worth testing. This is a prompt-layout hypothesis, not a guarantee about transformer attention or the next generated token. |
| Reduce repeated guardrails | Worth an experiment. Existing code comments report feminine-grammar drift when reminders were removed. Keep a short reminder until Hindi/Hinglish call evaluations show it is unnecessary. |

### Corrections to the economics and context claims

1. **Do not publish the 70–80% early-drop figure without our own call data or a relevant source.** The current persona describes a warm portal enquiry; this browser demo does not establish outbound answer rates. An unanswered dial and an opened model session are also different events. Model cost depends on whether inference was actually started.
2. **301 versus 1,300–1,500 is about 77–80% fewer root-prompt tokens, not 75% less total call cost.** Tools, audio input/output, accumulated history, other services, and call length still matter. The monolithic baseline needs a versioned, equivalent prompt; otherwise we compare different agent capabilities.
3. **The quoted prompt sizes are estimates.** Running the repository's `estimate_tokens` gives root **301**, `ALWAYS_BLOCK` **139**, and complete cards **413 / 409 / 302** before dynamic state and reason text. These are character/script heuristics, not Gemini tokenizer measurements or billed usage. Measure the exact rendered payload including state, wrappers, and tools where the selected model's counting API supports it; use provider usage for actual calls.
4. **Moving the opening out of the system instruction does not automatically remove its recurring context cost.** `inject_directive` appends user-role content; it does not delete earlier cards. Google documents client content as appended conversation history. Vertex Live guidance also describes per-turn billing of retained history and system instructions. Moving identical text between these locations is not context eviction. [Live protocol](https://ai.google.dev/api/live), [Vertex Live token usage](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/best-practices#token_usage_calculation).
5. **A focus label changes instructions, not memory retention.** Say “deferred prompt loading” in the demo, not “only one card exists in context.” Delaying a card can save repeated processing before it is needed; old cards still contribute while retained. Actual savings require a measured comparison.
6. **Five or six turns per card is a demo scenario, not enforced behavior.** The tracker limits forward transitions, not phase duration. Also, incomplete booking-tool calls explicitly re-send `SOP_03_PINCODE`; “zero mid-phase re-injection” is not true of this code.

For an A/B demo, hold the model/version, provider, voice, audio mode, tool schemas, root/card versions, compression settings, and caller script constant. Run early-exit, discovery-only, complete-booking, and correction/detour scenarios more than once. Record call duration and completion quality alongside tokens. Weight early exits only after collecting actual scenario frequencies.

Use unique finalized response records for call totals. Do not add an interim update and its final replacement, and do not add cached tokens again when they are already included in the prompt count. Show current context size separately from cumulative call usage. Dollar estimates must use the selected model/provider and available modality details; audio and text have different rates. [Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing).

### Implementation issues that matter before copy polish

**A. Routing currently mistakes keywords for intent.** I reproduced these results directly with `PragyaPhaseTracker`:

| Caller speech / sequence | Current result | Needed discussion or fix |
| --- | --- | --- |
| “Yes, I have two minutes” | Stays in Opening | Add context-aware acceptance of the opening question; a generic “yes” elsewhere must not advance the funnel. |
| “Don't book anything; just tell me about the Urus” | Advances to Lounge matching | Handle refusal/negation before positive booking keywords. |
| “I drive in Mumbai traffic; is the Urus comfortable?” | Advances to Lounge matching | Capture location separately; an incidental city mention is not visit intent. |
| PIN supplied, then “Actually, first tell me about the Revuelto engine” | Remains in Lounge matching | Decide whether the highlighted phase means furthest milestone or current conversational topic. These are different concepts. |

Proposed direction for discussion: retain monotonic **journey progress**, but allow the **current topic** to return to cars without losing the PIN or booking state. Do not add an LLM classifier silently: it changes latency and cost. Start with deterministic intent/negation rules and a transcript evaluation set; review ambiguous cases before choosing a classifier.

**B. Card delivery needs model-specific handling and honest telemetry.** `agent_live.py::inject_directive` currently uses `send_client_content(..., turn_complete=False)` for every silent card. The protocol says client content can interrupt active generation; `False` controls turn completion, not a guarantee of uninterrupted playback. Current Developer API documentation also restricts this method to initial history for `gemini-3.1-flash-live-preview`, directing mid-call text to realtime input. Check each offered model/provider explicitly; do not assume 2.5 and 3.1 share the same behavior. [Live protocol](https://ai.google.dev/api/live), [Live capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities#incremental-content-updates).

The tracker advances before sending the card. A failed send therefore leaves the phase advanced, while the frontend ignores `card_pushed`. There is no normal retry on an unchanged phase. A successful SDK send also does not prove which generated response used the card. Proposed event contract for discussion:

```text
phase_id, transition_id, card_version, state_revision,
delivery_status: pending | sent | failed,
response_id (only when actually correlated)
```

Keep journey progress separate from card delivery status. Deduplicate by transition and state revision, not just phase ID: a corrected PIN may legitimately need a fresh briefing. Retry a definite failure at a safe boundary; do not blindly replay an ambiguous send or interrupt speech to refresh a label. Verify that the intended reply uses the new card in live tests.

**C. State placement cannot compensate for incomplete state capture.** `CallSlots.observe_user_text` currently captures only PIN codes. Car, date, and time are proposed through the booking tool, so they may be missing from a card even when the caller already said them. Validation checks value shape; it does not prove the caller supplied the date/time. `plan_read_back` exists but is not required by the booking gate. First define how facts are captured, confirmed, and invalidated, then render them prominently. State snapshots also become stale after a same-phase correction unless deliberately refreshed.

Suggested briefing shape, after that decision:

```text
[CURRENT BRIEFING: ORGANISING THE VISIT]
KNOWN: PIN 560048; car Temerario.
MISSING: day and time.
NEXT: Ask for the day, then time, one question at a time.
If they ask about a car, answer before returning to the visit.

[STAGE GUIDELINES]
...
```

Treat captured values and caller quotations as data, not additional instructions. Avoid an absolute “disregard discovery” command: it can suppress legitimate follow-up questions.

**D. Separate a demo appointment from a vehicle allocation.** `create_appointment_booking` currently constructs a UUID and returns `confirmed`; it does not call a dealer calendar, check inventory, reserve a build slot, or send a message. Keep that simulation clear to demoers. The existing phase-four copy already promises follow-up actions that this tool does not execute; review those too. An unsupported PIN also falls back to the first returned centre rather than obtaining the caller's choice.

### Car-content changes I would not merge as written

- **“All models have hydraulic lift (+45mm)”** is not a valid shared fact. Lamborghini describes Urus SE air springs with different clearance adjustment. Use verified, model-specific facts and avoid clearance guarantees. [Official Urus SE description](https://www.lamborghini.com/en-en/news/lamborghini-urus-se-the-first-plug-in-hybrid-super-suv).
- **“A Lounge visit locks a 2026/2027 build slot”** has no backing in this implementation or in the blueprint's sources. Replace with “the dealer can confirm availability and delivery estimates.”
- **“Broken roads / speed breakers with zero stress”** is an overpromise. Frame road suitability as a question for the dealer and a demonstration, not guaranteed clearance.
- Sensory language is useful, but exact prices, specifications, availability, and dates should have a maintained source. A 50-token cheat sheet is only useful if its claims are accurate.

### Proposed order of work and decisions still open

1. **Land the call-accounting repairs and validate a real call.** A local repair commit, `d0f8577`, adds finalized-response accounting, replay protection, response correlation, and per-session traces without changing the persona architecture or UI structure. It passed 92 studio tests, a production build, and 109 focused backend tests before the documentation-only rebase. No live provider/microphone or invoice validation has been performed. The browser ledger is not durable billing storage. **This commit is not on GitHub: publication returned integration-permission HTTP 403.**
2. **Fix phase misclassification and delivery reporting.** Prioritize refusal, incidental locations, skipped stages, failed sends, and a product question after a PIN. Agree first on milestone versus current-topic highlighting and model-specific delivery timing.
3. **Make booking evidence and demo outcomes precise.** Confirm how accepted day/time and plan confirmation are represented; retain tool-confirmed completion and avoid promising real allocation or messages.
4. **Polish card wording with a small controlled comparison.** Trial state-first formatting, natural bridges, and a shorter grammar reminder. Check repeated questions, feminine grammar, barge-in, and booking correctness along with cost.
5. **Then consider an opening card or explicit context replacement.** These need a startup/context-lifecycle design and live latency tests. Appending another card alone does not provide replacement. Keep the existing root opening for now.

### Owner decision — confirmed

The owner has asked this implementation effort to take responsibility for fixing and preparing the demo and confirmed: **keep the highlighted phase on the current topic.**

Implementation direction: retain collected slots, visited milestones, and confirmed booking state separately. For example, a car question after providing a PIN can highlight Discovery without forgetting the PIN or cancelling a booking. This does not imply re-sending a full card on every turn. Correct refusal/location routing, repeated-transcript handling, and honest card-delivery status alongside the topic change. Keep the root opening and existing UI layout.

Publish only to `ui-changes-sep`. Preserve concurrent contributions and leave `main` untouched. The owner confirmed restored repository access after the initial review checkpoint.

Please append replies beneath this section so we can resolve remaining decisions without overwriting either review. The approved topic-routing changes will be recorded below with validation results.

### Implementation update — current-topic behavior completed

The owner approved current-topic highlighting, and the following changes accompany this review on `ui-changes-sep`:

- `PragyaPhaseTracker` can return from Lounge matching or Booked to Discovery. Furthest progress and tool-confirmed booking evidence remain separate; the slot store retains the PIN, date/time, and booking reference. A booking-reference question returns to Booked only after a tool-confirmed booking.
- Refusal/negation takes precedence over booking words. An incidental city mention no longer indicates visit intent. Acceptance of the opening question enters Discovery only from Opening. Later explicit clauses can change the current topic.
- An unchanged successful card is reused for successive questions in the same topic. Topic changes and changed captured state can send a fresh card. A PIN correction refreshes the briefing once; repeating it does not refresh again. Returning to a previous topic can re-send that card, so repeated detours have a token cost.
- Card sends are serialized, failed briefs are retained for retry, and a pending brief follows the latest topic. Briefs wait while the provider reports active generation and are retried after its turn completes. Gemini 3 uses realtime text for mid-call updates; 2.5 uses uncommitted client content. SDK send success is not proof that a particular reply used the card.
- The existing four tiles now say **Current topic**. A compact status reports **Brief pending / sent / failed**. Stale phase-event revisions are ignored, visited milestones remain visible, and ending a call retains its final highlighted topic. The existing UI layout and Observability entry point remain intact.
- A discovery briefing after booking explicitly carries the existing confirmation reference so revisiting cars does not imply starting another appointment.

Validation: **122 focused backend tests passed; 93 studio tests passed; TypeScript/Vite production build passed.** Added regression coverage includes current-topic detours, retained bookings/PINs, refusals in English/Hindi/Hinglish, incidental locations, opening acceptance, corrected PINs, failed/deferred sends, model-specific send methods, and stale frontend events. The build still reports its existing large-chunk warning.

**Remaining validation:** run actual voice calls against the configured provider. In particular, verify that a deferred card is applied at the intended conversational boundary and whether Gemini 3 realtime text produces an additional response. The transport cannot guarantee that a transcript-derived card precedes a reply that has already started. No measured end-to-end savings or invoice accuracy is claimed. Routing is deterministic and needs expansion if real transcripts expose unhandled paraphrases.

**Still deferred:** moving the opening out of the root, deleting/compressing old cards, removing the grammar reminder, unsupported sales/allocation claims, a real dealer booking integration, stronger booking-confirmation evidence, and an equivalent monolithic A/B mode. These are separate decisions or remaining work, not completed features. The earlier critique describes the reviewed remote baseline; this update identifies the fixes made since that review.

**Publication record:** the earlier local-only and HTTP 403 notes describe the initial review checkpoint. Repository write access was subsequently restored. This revision includes the tested accounting repairs, current-topic changes, and shared review together, preserving the original remote contributions. Live-call validation remains outstanding as described above.
