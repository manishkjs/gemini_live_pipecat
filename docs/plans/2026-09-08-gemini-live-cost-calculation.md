# Gemini Live Session Cost Calculation Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Calculate real-time, per-turn, and per-session cost for Gemini Live audio sessions using differentiated rate cards (Gemini 2.5 vs 3.1 vs 3.5), strictly visible only when those models are selected in the Live flow.

**Architecture:** Pure, zero-overhead modular pricing engine in TypeScript (`src/lib/pricing.ts`) integrated into `pipecat-session.ts` and `voice-studio.tsx`. Hooks directly into native `usage_metadata` token streams (audio in, audio out, text prompt) streamed from `agent_live.py`.

**Tech Stack:** TypeScript, React (with Svelte/Vite), Pipecat 1.2+ WebSockets, Node test runner (`node --test`).

---

## 1. Differentiated Rate Cards (Gemini 2.5 vs 3.1 vs 3.5)

| Model Tier | Live Model ID | Audio In (per 1M tok) | Audio Out (per 1M tok) | Text In (per 1M tok) | Text Out (per 1M tok) | Est. Hourly Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Gemini 2.5 Live** | `gemini-live-2.5-flash-native-audio`<br>`gemini-live-2.5-flash` | **$0.70** ($0.0007/1K) | **$2.00** ($0.0020/1K) | $0.075 | $0.30 | **~$0.30 – $0.50 / hr** |
| **Gemini 3.1 Live** | `gemini-3.1-flash-live-preview` | **$1.00** ($0.0010/1K) | **$4.00** ($0.0040/1K) | $0.075 | $0.30 | **~$0.60 – $0.90 / hr** |
| **Gemini 3.5 Flash-Lite** | `gemini-3.5-flash-lite-live-preview` | **$0.50** ($0.0005/1K) | **$2.00** ($0.0020/1K) | $0.075 | $0.30 | **~$0.30 – $0.45 / hr** |
| **Gemini 3.5 Flash Live** | `gemini-3.5-flash-live-preview`<br>`gemini-3.5-live-preview`<br>`gemini-3.5-live-extended-thinking-preview` | **$2.00** ($0.0020/1K) | **$8.00** ($0.0080/1K) | $0.150 | $0.60 | **~$0.90 – $1.50 / hr** |

---

## 2. Core Constraints & Visibility Invariants

> [!IMPORTANT]
> 1. **Live-Only Visibility Gate**: The cost ticker, per-turn cost badges, and pricing cards are **STRICTLY VISIBLE ONLY** when `settings.engine === "live"` AND the selected model has an active live rate card (Gemini 2.5 / 3.1 / 3.5 Live).
> 2. **Cascade Isolation**: When `engine === "cascade"` (STT-LLM-TTS), cost badges are completely hidden to avoid false comparisons with multi-vendor cascaded billing.
> 3. **Modality Accuracy**: Uses granular token modalities from `usage_metadata` (`prompt_details.audio` / `response_details.audio`) when available, falling back safely to total prompt/response counts.
> 4. **Session Reset Hygiene**: Session cost, token tallies, and turn counters reset cleanly to `$0.0000` upon every new session start or persona switch.

---

## Proposed Changes & Task Breakdown

### Task 1: Dedicated Pricing Engine & Rate Cards (`src/lib/pricing.ts`)

**Files:**
- Create: `demos/voice-studio/src/lib/pricing.ts`
- Test: `demos/voice-studio/tests/pricing.test.mjs`

**Step 1: Write the failing tests (`tests/pricing.test.mjs`)**
- Test rate card resolution for `gemini-live-2.5-flash-native-audio` (returns 2.5 pricing).
- Test rate card resolution for `gemini-3.1-flash-live-preview` (returns 3.1 pricing).
- Test `isLivePricingEligible('live', 'gemini-live-2.5-flash-native-audio') === true`.
- Test `isLivePricingEligible('cascade', 'gemini-2.5-flash') === false`.
- Test `calculateTurnCost` with audio input + output breakdown.
- Test `formatCost` currency formatting (`$0.0024`, `$0.0001`, `<$0.0001`).

**Step 2: Run test to verify it fails**
- Run: `node --test tests/pricing.test.mjs` (Expected: FAIL - module missing).

**Step 3: Implement `src/lib/pricing.ts`**
- Define `LiveRateCard` interface:
  ```typescript
  export interface LiveRateCard {
    tier: 'gemini-2.5' | 'gemini-3.1' | 'gemini-3.5-lite' | 'gemini-3.5-flash';
    displayName: string;
    audioInPerMillion: number;
    audioOutPerMillion: number;
    textInPerMillion: number;
    textOutPerMillion: number;
    estHourlyUSD: string;
  }
  ```
- Implement `getLiveRateCard(model: string): LiveRateCard | null`
- Implement `isLivePricingEligible(engine: string, model: string): boolean`
- Implement `calculateTurnCost(model: string, usage: UsageMetrics): TurnCostResult`
- Implement `formatCost(usd: number): string`

**Step 4: Run test to verify it passes**
- Run: `node --test tests/pricing.test.mjs` (Expected: PASS).

---

### Task 2: Session & Message Metrics Extension (`src/lib/pipecat-session.ts`)

**Files:**
- Modify: `demos/voice-studio/src/lib/pipecat-session.ts:10-25`

**Step 1: Extend `MessageMetrics` to include `turnCostUSD`**
```typescript
export type MessageMetrics = {
  sttLatency?: number;
  llmLatency?: number;
  ttsLatency?: number;
  interruptedMs?: number;
  turnCostUSD?: number;
  usage?: {
    total_token_count?: number;
    prompt_token_count?: number;
    response_token_count?: number;
    prompt_details?: { text?: number; audio?: number };
    response_details?: { text?: number; audio?: number };
  };
};
```

**Step 2: Compute `turnCostUSD` on incoming usage frames in `pipecat-session.ts`**
- When `p.type === "usage"` is processed, compute `turnCost = calculateTurnCost(settings.model, p.usage)` if in Live mode.
- Attach `turnCostUSD` to the metric payload passed to `onMetricUpdate("usage", ...)`.

---

### Task 3: UI Integration — Live Metrics Ticker, Badges & Rate Card (`voice-studio.tsx`)

**Files:**
- Modify: `demos/voice-studio/src/components/voice-studio.tsx`
- Modify: `demos/voice-studio/src/index.css`

**Step 1: Track Cumulative Session Cost State**
- Add state: `const [sessionCostUSD, setSessionCostUSD] = useState<number>(0);`
- Reset `setSessionCostUSD(0)` in `resetConversation()`.
- On incoming turn usage, add turn cost to `sessionCostUSD`.

**Step 2: Add Live Cost Pill in Ticker Bar**
- Conditionally render in `.live-metrics-ticker` when `isLivePricingEligible(settings.engine, settings.model)`:
  ```tsx
  {isLivePricingEligible(settings.engine, settings.model) && sessionCostUSD > 0 && (
    <span className="ticker-pill cost-pill" title={`Accumulated session cost for ${settings.model}`}>
      <DollarSign size={11} />
      Cost: <strong>{formatCost(sessionCostUSD)}</strong>
    </span>
  )}
  ```

**Step 3: Add Turn Cost Tag on Assistant Message Bubbles**
- In `.bubble-latency.live-badge`, render:
  ```tsx
  {message.metrics?.turnCostUSD !== undefined && (
    <span className="cost-tag" title="Estimated turn cost">
      {formatCost(message.metrics.turnCostUSD)}
    </span>
  )}
  ```

**Step 4: Add Live Pricing Callout Card in Settings Dialog**
- When `settings.engine === "live"` and model has rate card, render an informative callout below the Model select:
  ```tsx
  {liveRateCard && (
    <div className="pricing-rate-card">
      <div className="rate-card-header">
        <DollarSign size={13} />
        <span>{liveRateCard.displayName} Pricing</span>
        <span className="rate-pill">{liveRateCard.estHourlyUSD}</span>
      </div>
      <div className="rate-card-grid">
        <div>Audio In: <strong>${liveRateCard.audioInPerMillion}/1M tok</strong></div>
        <div>Audio Out: <strong>${liveRateCard.audioOutPerMillion}/1M tok</strong></div>
      </div>
    </div>
  )}
  ```

**Step 5: Add End-of-Call Cost Summary in Stage**
- When stopping a live session with cost > 0, show a sleek pill in the stage:
  `Session: 5 turns · 1,420 tok · $0.0018 USD`

---

### Task 4: Regression Testing & Full Verification

**Files:**
- Run existing test suite: `tests/voice-contract.test.mjs`
- Run new test suite: `tests/pricing.test.mjs`
- Verify `npm run build` (`tsc --noEmit && vite build`).
- Verify backend tests: `./server/venv/bin/python server/test_routes.py`.

---

## Verification Plan

### Automated Tests
1. `npm test` in `demos/voice-studio`:
   - Runs `tests/voice-contract.test.mjs` and `tests/pricing.test.mjs`.
   - Expected: 100% passing tests.
2. `python server/test_routes.py`:
   - Expected: 5/5 passing tests.
3. `npm run build`:
   - Compiles TypeScript and CSS with 0 errors.

### Manual Verification
1. Open `http://localhost:5173/`.
2. Open **Settings** -> Select **Gemini Live** -> Choose **gemini-live-2.5-flash-native-audio**:
   - Verify rate card displays: `$0.70/1M audio in, $2.00/1M audio out`.
3. Switch Model to **gemini-3.1-flash-live-preview**:
   - Verify rate card displays: `$1.00/1M audio in, $4.00/1M audio out`.
4. Switch Engine to **Cascade**:
   - Verify pricing card disappears completely.
5. Start Live session with Gemini 2.5:
   - Speak 2-3 turns.
   - Verify **Cost: $0.00xx** ticker pill updates in real time in the conversation header.
   - Verify each assistant bubble displays both **TTFB** and the **Cost tag**.
