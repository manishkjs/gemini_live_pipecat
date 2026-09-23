# Voice Studio UI Refresh — Review & Implementation Brief

> **Status:** Suggestions only. **Zero source files modified.** This document is the brief;
> hand it to the implementing agent as-is.
>
> **Verified against:** `feat/pragya-supercar-phase-cards` @ `b830d91`, live dev server on
> `:5173`, `demos/voice-studio/src/components/voice-studio.css` (2,806 lines).

**Direction:** keep the two-pane design and make it a calmer, clearer voice workspace. The
structure is right. The wins are hierarchy, readability, responsive behaviour, and making the
interface's promises match what the session actually does.

**Implementation order:** responsive rules and misleading states first; then persona and
transcript simplification; then styling tokens, drawer accessibility, and asset loading.
Keep the existing React stack and session transport throughout.

---

## 0. Claims verified in source

Every defect below was confirmed by reading the code, not inferred.

| Claim | Evidence | Status |
| :--- | :--- | :--- |
| Breakpoints conflict | `voice-studio.css:1039` `@media (max-width:1180px)` sets `grid-template-columns:1fr` at `:1041`; `voice-studio.css:1697` `@media (max-width:1080px)` sets it **back** to two columns at `:1702` | ✅ confirmed |
| Fixed panel heights | `voice-studio.css:1050` `height:720px`; `voice-studio.css:1725` `height:640px` | ✅ confirmed |
| Stylesheet sprawl | 2,806 lines, 9 `@media` blocks, several minified single-line rules (`:1784`, `:1788`, `:1789`) | ✅ confirmed |
| Tone resolver bug | `transcript-panel.tsx:124` and `:169` use `persona.prompt` directly; `getPersonaPrompt` is never imported in this file | ✅ confirmed |
| `startPreview` is dead code | Defined `use-voice-session.ts:199`, exported `:509`, **zero references** anywhere in `src/components/` | ✅ confirmed |
| Engine badge hardcoded | `voice-studio.tsx:97` renders literal `GEMINI LIVE TILE` regardless of engine | ✅ confirmed |
| "Mic ready" precedes access | `conversation-stage.tsx:93` renders `"Mic ready"` in the inactive branch | ✅ confirmed |
| Empty-state points the wrong way | `transcript-panel.tsx:102` says *"Select Gemini Live or Cascade **on the left**"* — those controls are on the **right** in the current layout | ✅ confirmed, and worse than reported |
| Portraits oversized | 7 PNGs, **11.8 MB** total, rendered mainly at 48px | ✅ confirmed |
| Drawer is not a dialog | `src/components/observability-drawer.tsx` — not built on the Radix `Dialog` primitives used elsewhere | ✅ confirmed |

---

## 1. Visual direction

Keep the charcoal background, Indian portraits, compact waveform, and lime primary action.
Use lime **mainly** for the selected persona and the Start button.

| Element | Recommended treatment |
| :--- | :--- |
| Desktop layout | ~288px persona sidebar; conversation fills remaining space |
| Persona rows | 48px portrait, 16px name, 14px role, one short description |
| Selected persona | Subtle tinted background, clear border, existing radio indicator |
| Conversation stage | Compact horizontal strip; 72–88px waveform |
| Transcript | 16px text, 1.6 line height, restrained message backgrounds |
| Controls | ≥40px tall on desktop; 44px touch targets |
| Metadata | 12px minimum; regular labels 14px |
| Surfaces | Three consistent background levels; fewer gradients and shadows |
| Motion | Brief fades and meaningful audio movement; respect reduced motion |

Selection is currently communicated **five ways at once**: border, glow, radio, avatar dot,
and a "Selected" pill. Keep the border and radio. Remove the rest. This single change makes
the sidebar feel deliberate rather than decorated.

Preserve all seven prepared personas plus Custom Agent.

---

## 2. Make the first screen easier to understand

The initial conversation area exposes a large system-prompt block, putting implementation
detail ahead of the demo experience.

The prepared-persona flow should show:

1. A short scenario description
2. "Your role" in one sentence
3. One suggested opening
4. **Start session** and **Play sample** actions
5. A collapsed **Agent instructions** control

```
Talk to Kavya
Plan a birthday dinner with a reservation agent.
Your role: You need a table for four on Saturday evening.
Try saying: "Can you help me book a birthday dinner?"
```

Keep instructions editable, but collapsed by default for prepared personas. For Custom Agent,
show the instruction editor immediately. Preserve the current behaviour where a blank custom
prompt falls back to backend defaults.

**Pin Custom Agent below the scrollable persona list.** It is currently the eighth entry and
falls below the first viewport. It is a primary journey and deserves a permanent slot.

On mobile, replace the tall persona list with a compact selected-persona button that opens the
chooser, and show the conversation directly underneath.

---

## 3. Fix the responsive layout before adding polish

Consolidate the conflicting rules. **Do not append another override section** to the
2,806-line stylesheet — replace the corresponding existing declarations.

```css
.studio-shell {
  height: 100dvh;
  max-height: none;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0 24px;
}

.studio-header { flex: 0 0 64px; }

.studio-workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(250px, 288px) minmax(0, 1fr);
  gap: 16px;
  overflow: hidden;
}

.studio-sidebar,
.gemini-live-tile,
.transcript-panel { min-width: 0; min-height: 0; }

.gemini-live-tile {
  height: auto;
  display: flex;
  flex-direction: column;
}

.transcript-panel { flex: 1; height: auto; }

.transcript-scroll {
  flex: 1;
  min-height: 0;
  height: auto;
  max-height: none;
  overflow-y: auto;
  scrollbar-gutter: stable;
}

.tile-top-bar {
  height: auto;
  min-height: 48px;
  flex-wrap: wrap;
}

.studio-footer { flex: 0 0 32px; }
```

Then implement **one** coherent mobile layout: compact persona chooser, wrapping
engine/language controls, reachable call controls, and no fixed 640px/720px panel heights.

---

## 4. Consistent tokens and typography

The interface mixes lime, emerald, cyan, purple, gradients, and several competing text sizes.
Observability reads like a different application.

Introduce shared tokens in `src/globals.css` and use them across studio, settings, and drawer:

```css
:root {
  color-scheme: dark;

  --studio-bg: #101216;
  --studio-surface: #171b20;
  --studio-raised: #20262d;
  --studio-border: #343d47;

  --studio-text: #f3f5f7;
  --studio-muted: #aeb8c4;
  --studio-accent: #d5f580;
  --studio-danger: #ff9b9b;

  --studio-radius: 12px;
  --studio-control-height: 44px;

  --font-sans:
    Inter, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

body { font-family: var(--font-sans); }

.message-content p { font-size: 1rem; line-height: 1.6; }

.persona-description,
.field label,
.engine-tabs [data-slot="tabs-trigger"] { font-size: 0.875rem; }

.message-meta time,
.ticker-pill,
.transcript-footer { font-size: 0.75rem; }

.studio-shell :where(button, a, input, textarea):focus-visible {
  outline: 2px solid var(--studio-accent);
  outline-offset: 3px;
}
```

Remove the studio's local `--muted` text-colour override. That name is already a semantic
**surface** token in the shared theme; use `--studio-muted` or `--muted-foreground` for text.

Keep persona colours as small accents. Make message bubbles predominantly neutral rather than
saturated green.

---

## 5. Correct the labels and restore the sample journey

Small changes, immediate impact.

| Current behaviour | Recommended change |
| :--- | :--- |
| `GEMINI LIVE TILE` stays visible with Cascade selected (`voice-studio.tsx:97`) | Use **"Voice session"** |
| Empty state says controls are "on the left" (`transcript-panel.tsx:102`) — they are on the right | Position-independent instructions |
| "Mic ready" before microphone access (`conversation-stage.tsx:93`) | "Microphone requested when you start" |
| Stage says "Connected" whenever `active` is true | Distinguish connecting / sample playback / connected |
| `startPreview()` exists with no UI entry point | Restore a secondary **Play sample** button |
| Footer shows `Live cost: $0.0000` under Cascade | Apply the existing pricing eligibility check |

```tsx
<section className="gemini-live-tile" aria-label="Voice session">
  {/* Existing contents */}
</section>

// Replace the hardcoded badge at voice-studio.tsx:97
<span className="gemini-live-badge">Voice session</span>
```

```tsx
// conversation-stage.tsx — restore the existing, orphaned sample action
{!active && !custom && persona.sample.length > 0 && (
  <Button
    variant="outline"
    className="sample-action"
    onClick={studio.startPreview}
  >
    Play sample
  </Button>
)}
```

Label playback **"Scripted sample · no API calls."** The selected engine must not imply the
sample was generated by that engine.

```tsx
const sessionHint =
  source === "preview"
    ? "Playing a scripted sample."
    : phase === "connecting"
      ? "Connecting to your voice backend…"
      : active
        ? "Speak naturally. You can interrupt anytime."
        : "Your microphone will be requested when you start.";
```

---

## 6. Make persona copy, tone, and prompts agree

Professional defaults were added, but some descriptions, openings, journeys, and samples still
describe the signature behaviour. Aisha's default prompt describes a friendly companion while
her card describes a romantic, possessive girlfriend. Meera's professional prompt conflicts
with her sample.

Store the complete presentation for each tone together:

```ts
type PersonaExperience = {
  description: string;
  userRole: string;
  opening: string;
  journey: string[];
  prompt: string;
  sample: SampleTurn[];
};

type PersonaExperiences = Record<PersonaTone, PersonaExperience>;
```

Use the selected experience consistently for card, briefing, prompt, and sample. Keep custom
instructions as a separate override.

**Immediate bug — `transcript-panel.tsx`.** Its prompt preview (`:169`) and editor
initialisation (`:124`) use `persona.prompt` even when Signature tone is selected. Settings
already uses the correct resolver. Apply the same logic:

```tsx
import { getPersonaPrompt } from "@/lib/personas";

const presetPrompt = getPersonaPrompt(persona, settings.tone);
const effectivePrompt = settings.instructions.trim() || presetPrompt;

// Preview:
<p className="persona-prompt-preview">{effectivePrompt}</p>

// Existing edit-button handler:
onClick={() => {
  if (!settings.instructions.trim()) {
    update("instructions", presetPrompt);
  }
  setShowInlineEditor((previous) => !previous);
}}
```

For demo data, make simulated bookings, portfolio values, and transactions visibly identifiable
as examples, with that context beside the relevant result.

---

## 7. Make the transcript the main working surface

Keep the compact waveform. The current 96px allocation (`voice-studio.css:504`) is already
close; simplifying the surrounding text matters more than shaving pixels.

- Show elapsed time and **one** useful response metric in the compact footer.
- Move token breakdowns, per-stage timings, and detailed costs into Observability.
- Offer **"Show turn metrics"** for users who want inline diagnostic badges.
- Follow new messages only while the user is near the bottom.
- Show **"Jump to latest"** when they scroll upward.
- Do not start a new smooth-scroll animation for every streaming update.
- Preserve the completed transcript until the user starts another session or explicitly clears it.
- Announce completed turns to screen readers without re-reading every partial-token update.

The existing `followTranscript` ref is a good foundation — extend it rather than replacing the
session hook.

Guard the footer cost with the eligibility logic already used elsewhere:

```tsx
{isLivePricingEligible(settings.engine, settings.model) && (
  <span title="Estimated session token cost">
    Estimated cost: {formatCost(sessionCostUSD)}
  </span>
)}
```

### 7b. Observed telemetry gaps (live Pragya Cascade session, 987 tokens, 01:15 elapsed)

| Gap | Why it matters | Fix |
| :--- | :--- | :--- |
| `Live cost $0.0000` | The headline metric of a cost-optimisation demo renders as zero | 6 decimals, or cents, or cost-per-1,000-calls |
| Avatar repeated under every bubble | Five identical portraits stack down the pane | Group consecutive turns; avatar on speaker change only |
| Wall-clock timestamps (`12:35 AM` ×4) | Meaningless inside a 75-second call | Relative offsets (`+00:12`), or drop |
| `Response 2.48s` unlabelled | Last turn or average? | Label it `Avg response` |
| Latency/token chips very low contrast | Unreadable on a projector | Raise contrast and size, especially the token chip |

---

## 8. Keep Observability, give it production behaviour

The icon and functionality should stay prominent. Session filtering is already there — keep it.

`src/components/observability-drawer.tsx` uses a backdrop `<div>` and an `<aside>`. Escape does
not close it. Rebuild on the existing Radix-backed `Dialog` primitives so that:

- Focus moves into the drawer
- Tab stays inside while open
- Escape closes it
- Focus returns to the Observability button
- The drawer has a proper accessible title

Keep the existing telemetry content; style the dialog as a right-side panel.

Also:

- Show **"Waiting for session" / "Updating" / "Telemetry unavailable"** from actual state. The
  current "Live Telemetry" indicator appears even without working telemetry.
- Display `—` for unavailable measurements; reserve `0` for a measured zero.
- Keep metric colours consistent; replace decorative emoji with the existing icon set.
- Reduce desktop width below the current 880px maximum where the data stays readable.
- Keep context-compression detail in Observability; use a small, unobtrusive status message in
  the conversation.

---

## 9. Organise Settings around user decisions

Keep every existing setting, but group them:

| Group | Contents |
| :--- | :--- |
| Voice | Language, voice, speaking rate |
| Agent | Tone, instructions |
| Engine | Live model, or Cascade STT/LLM/TTS models |
| Advanced | VAD, reasoning, compression, tools, backend URL |

Show friendly model names in selectors with the exact model ID as secondary detail.

Allow users to **inspect** settings during a call while keeping session-changing fields
disabled, explained with *"Available after this session ends."* Currently the entire Settings
entry is disabled mid-call.

---

## 10. Performance and focused regression checks

The seven portrait PNGs total **11.8 MB** and are displayed mainly as small avatars. Generate
optimised thumbnail variants, retain the originals, use consistent portrait crops, and lazy-load
offscreen portraits.

Consider loading Observability and Settings on open. The build reports large JS chunks —
measure the initial download before changing bundling.

**Verification checklist for the implementing agent:**

- [ ] All eight persona entries remain reachable
- [ ] Custom instructions and blank backend defaults work on both engines
- [ ] Sample playback is clearly distinguished from a backend session
- [ ] Observability works during a call and supports Escape and keyboard navigation
- [ ] Microphone, speaker, interruption, copy, and end-session behaviour intact
- [ ] Layouts work at 390, 768, 1024, 1280, 1440px, plus 200% zoom
- [ ] The existing 82 JS tests and the production build still pass

---

## 11. Hook for the Pragya Phase Cards work

See [`2026-09-11-pragya-supercar-phase-cards.md`](./2026-09-11-pragya-supercar-phase-cards.md),
Revision v2 §R6–R7.

The DEMO FOCUS panel currently unmounts when a session starts. It must stay mounted and be
driven by the `phase_transition` RTVI message, lighting up the active SOP as Pragya jumps
01 → 02 → 04, with the live token counter beside it. Pragya's prompt editor is read-only but
should be a **live inspector**, not a dead grey box: it shows the card currently in play and
swaps as she transitions. The lock protects the state machine; the live swap is what makes the
lock interesting.
