import type { CascadeCost } from "./cascade-cost.ts";
import type { Persona, PersonaId } from "./personas.ts";
import type { Phase } from "./studio-types.ts";
import { isAvatarActive, isClonedVoice, isGeminiClonedVoice, isLibraryVoice, isLiveCustomVoice, type SessionSettings } from "./voice-session.ts";

export interface ScenarioStage {
  readonly num: string;
  readonly title: string;
  readonly detail: string;
}

export interface PipelineNode {
  readonly kind: string;
  readonly title: string;
  readonly meta: string;
}

export interface VoiceBubbleInput {
  readonly active: boolean;
  readonly phase: Phase;
  readonly sound: boolean;
  readonly muted: boolean;
  readonly playingSample: boolean;
  readonly agentName: string;
}

export interface VoiceBubbleView {
  readonly isActive: boolean;
  readonly isSample: boolean;
  readonly isListening: boolean;
  readonly isMuted: boolean;
  readonly label: string;
  readonly ariaLabel: string;
}

export interface StreamingAssistantState {
  readonly streamingAssistantIndex: number;
  readonly showPendingAssistantTurn: boolean;
}

export interface SessionCostSummaryInput {
  readonly engine: SessionSettings["engine"];
  readonly model: string;
  readonly sessionCostUSD: number;
  readonly cascadeCost: CascadeCost | null;
  readonly incomplete: boolean;
  readonly estimated: boolean;
}

/**
 * Curated cool violet, indigo, and orchid identity accents for persona portraits.
 * Keeps semantic emerald (live), amber (warning), rose (danger/mute), and sky (primary action)
 * visually distinct across every persona selection.
 */
export const PERSONA_UI_ACCENTS: Readonly<Record<PersonaId, string>> = {
  "debt-collector": "#a78bfa",
  "reservation-agent": "#818cf8",
  storyteller: "#c084fc",
  "ai-companion": "#e879f9",
  "car-negotiator": "#93c5fd",
  "groww-advisor": "#b39ddb",
  "lamborghini-concierge": "#d8b4fe",
  "travel-concierge": "#a5b4fc",
  custom: "#94a3b8",
};

/** Compact role labels rendered beneath each circular portrait in the top cast rail. */
export const PERSONA_CAST_ROLES: Readonly<Record<PersonaId, string>> = {
  "debt-collector": "Debt Collector",
  "reservation-agent": "Cymbal Kart Buddy",
  storyteller: "Storyteller",
  "ai-companion": "AI Companion",
  "car-negotiator": "Car Negotiator",
  "groww-advisor": "Mutual Fund Advisor",
  "lamborghini-concierge": "Lamborghini Concierge",
  "travel-concierge": "Travel Concierge",
  custom: "Custom Prompt",
};

const STAGE_DETAIL_BY_PERSONA: Readonly<Record<PersonaId, readonly string[]>> = {
  "debt-collector": [
    "Verify borrower identity and state the Rs. 8,500 overdue installment",
    "Ask for full or partial UPI settlement today before offering extra days",
    "Offer a split payment or short extension only after pushback",
    "Lock in the exact rupee amount, date, and payment rail",
  ],
  "reservation-agent": [
    "Listen to the shopper's complaint and acknowledge frustration first",
    "Look up order or refund status and explain the root cause plainly",
    "Propose an instant replacement, refund, or wallet credit option",
    "Confirm the chosen resolution and expected timeline",
  ],
  storyteller: [
    "Open mid-scene with sensory detail in natural Hindi and English",
    "Pause at a cliffhanger so the listener steers what happens next",
    "Weave the listener's choice directly into the next plot turn",
    "Land on a vivid twist or satisfying closing beat",
  ],
  "ai-companion": [
    "Notice the tired tone and ask warmly how the day went",
    "Lighten the mood with natural Hinglish banter and callbacks",
    "Listen without lecturing when work stress comes up",
    "Nudge gently to eat, rest, and step away from the screen",
  ],
  "car-negotiator": [
    "Welcome the buyer to the Okhla lot and spotlight the 2022 Creta SX",
    "Defend the Rs. 11.8L sticker with service history and tyre condition",
    "Trade accessories, insurance, or small price steps for a today booking",
    "Shake hands above the Rs. 10.75L floor or walk away politely",
  ],
  "groww-advisor": [
    "Clarify goal horizon, monthly SIP comfort, and drawdown tolerance",
    "Explain Nifty 50 index, flexi-cap, and debt fund trade-offs plainly",
    "Compare direct-plan expense ratios, exit loads, and LTCG tax rules",
    "Summarize a balanced educational allocation with SEBI risk disclaimers",
  ],
  "lamborghini-concierge": [
    "Welcome the caller warmly and ask what brought them to Lamborghini",
    "Match V12 Revuelto, V8 Temerario, or Urus SE to how they drive",
    "Discuss Ad Personam bespoke finishes and private lounge viewing",
    "Arrange a private showroom appointment or track experience",
  ],
  "travel-concierge": [
    "Greet the caller and confirm origin, destination, and travel dates",
    "Capture passenger count, cabin preference, and budget range",
    "Search live flight options and compare top itineraries concisely",
    "Shortlist matching hotels near the preferred neighborhood",
    "Check weather and local seasonal highlights for the trip window",
    "Lock in the selected flight and hotel pairing",
    "Verify traveller names and contact details before ticketing",
    "Issue the confirmed booking summary and PNR reference",
  ],
  custom: [
    "Write or paste your custom system instructions in the prompt tab",
    "Pick Gemini 3.8 Live or Cascade STT and TTS in Settings",
    "Start the call to test barge-in, latency, and token cost live",
  ],
};

/** Returns the curated UI accent color for a persona id. */
export function getPersonaUiAccent(personaId: string): string {
  return PERSONA_UI_ACCENTS[personaId as PersonaId] ?? PERSONA_UI_ACCENTS.custom;
}

/** Returns the short cast-rail role label for a persona. */
export function getPersonaCastRole(persona: Persona): string {
  return PERSONA_CAST_ROLES[persona.id] ?? persona.name;
}

/** Formats a USD amount strictly in cents (e.g. `0.00¢`, `<0.01¢`, `0.09¢`, `12.40¢`). */
export function formatCents(usd: number): string {
  if (!Number.isFinite(usd) || usd <= 0) return "0.00¢";
  const cents = usd * 100;
  if (cents < 0.01) return "<0.01¢";
  return `${cents.toFixed(2)}¢`;
}

/** Formats the running session cost in cents for the dock and console header. */
export function formatSessionCents(input: SessionCostSummaryInput): string {
  if (input.engine === "cascade") {
    if (!input.cascadeCost) return "0.00¢";
    const cents = formatCents(Number(input.cascadeCost.known_usd));
    return input.cascadeCost.complete ? cents : `~${cents}`;
  }
  if (input.sessionCostUSD <= 0) return "0.00¢";
  const base = formatCents(input.sessionCostUSD);
  if (input.incomplete) return `${base}+`;
  return input.estimated ? `~${base}` : base;
}

/** Shortens verbose voice identifiers for compact badges and portrait captions. */
export function formatVoiceShortLabel(voice: string): string {
  if (!voice) return "Default";
  if (isGeminiClonedVoice(voice)) return "Manish · 3.8 Clone";
  if (isLiveCustomVoice(voice)) return "Custom 24 kHz Clone";
  if (voice === "Custom-Male") return "Chirp3 Clone (M)";
  if (voice === "Custom-Female") return "Chirp3 Clone (F)";
  if (isClonedVoice(voice)) return "Custom Voice Key";
  if (isLibraryVoice(voice)) return voice.replace(/^en-in-/, "IN · ");
  return voice.replace(/^[a-z]{2}-[A-Z]{2}-/, "");
}

/** Builds numbered scenario stages with human-written descriptions for the Pre-Call card. */
export function getScenarioStages(persona: Persona): readonly ScenarioStage[] {
  const details = STAGE_DETAIL_BY_PERSONA[persona.id] ?? [];
  if (persona.journey.length === 0) {
    return STAGE_DETAIL_BY_PERSONA.custom.map((detail, idx) => ({
      num: String(idx + 1).padStart(2, "0"),
      title: idx === 0 ? "Author prompt" : idx === 1 ? "Select voice & engine" : "Test live call",
      detail,
    }));
  }
  return persona.journey.map((title, idx) => ({
    num: String(idx + 1).padStart(2, "0"),
    title,
    detail: details[idx] ?? `Guide the caller through ${title.toLowerCase()}`,
  }));
}

/** Builds the 3-node architecture summary shown in the Pre-Call Pipeline tab. */
export function getPipelineNodes(
  settings: SessionSettings,
): readonly [PipelineNode, PipelineNode, PipelineNode] {
  const vadLabel =
    settings.vadMode === "gemini"
      ? "Gemini server VAD"
      : settings.vadMode === "silero"
        ? "Silero local VAD"
        : "Silero + Gemini VAD";

  if (settings.engine === "cascade") {
    const sttTitle = settings.skipStt ? "Direct audio to LLM" : settings.sttModel.replace(/-aistudio$/, "");
    const sttMeta = settings.skipStt ? `Skip STT · ${settings.language}` : `${settings.language} · ${vadLabel}`;
    const llmTitle = settings.llmModel.replace(/-aistudio$/, "");
    const ttsTitle = settings.ttsModel === "google-tts" ? "Chirp 3 HD TTS" : settings.ttsModel;
    const ttsMeta = `${formatVoiceShortLabel(settings.voice)} · ${settings.ttsStyle || "Natural"}`;
    return [
      { kind: "Speech in", title: sttTitle, meta: sttMeta },
      { kind: "Reasoning", title: llmTitle, meta: "Streaming text tokens" },
      { kind: "Speech out", title: ttsTitle, meta: ttsMeta },
    ];
  }

  const avatarOn = isAvatarActive(settings);
  const modelTitle = avatarOn ? "gemini-3.8-live + Avatar" : settings.model.replace(/-aistudio$/, "");
  const thinkingMeta =
    settings.thinkingLevel && settings.thinkingLevel !== "off"
      ? `Thinking: ${settings.thinkingLevel}`
      : "Duplex native audio";
  return [
    { kind: "Transport", title: "Pipecat WebSocket", meta: "16 kHz PCM in · 24 kHz out" },
    { kind: "Model", title: modelTitle, meta: thinkingMeta },
    { kind: "Voice & VAD", title: formatVoiceShortLabel(settings.voice), meta: vadLabel },
  ];
}

/**
 * Computes a per-bar vertical scale (`0.26..1.22`) from a normalized RMS audio level (`0..1`).
 * Rests calmly at `0.26` during silence (`level <= 0.01`) and rises monotonically with loudness.
 */
export function computeBubbleBarScale(level: number, factor: number): number {
  if (!Number.isFinite(level) || !Number.isFinite(factor) || level <= 0.01) {
    return 0.26;
  }
  const clamped = Math.min(1, Math.max(0, level));
  const safeFactor = Math.max(0.2, factor);
  return Math.min(1.22, Number((0.26 + clamped * safeFactor * 0.84).toFixed(4)));
}

/**
 * Computes horizontal stretch (`1.00..1.09`) for the dock voice pill from normalized audio level (`0..1`).
 */
export function computeBubblePillStretch(level: number): number {
  if (!Number.isFinite(level) || level <= 0.01) {
    return 1;
  }
  const clamped = Math.min(1, Math.max(0, level));
  return Number((1 + clamped * 0.09).toFixed(4));
}

/**
 * Resolves which assistant message (if any) owns the live `"Speaking now"` indicator.
 * Prevents `"Speaking now"` from attaching to an older assistant turn above a newer user turn
 * before the first transcript chunk of the new assistant turn arrives.
 */
export function resolveStreamingAssistantState(
  messages: ReadonlyArray<{ readonly role: "user" | "assistant" }>,
  active: boolean,
  phase: Phase,
): StreamingAssistantState {
  if (!active || phase !== "speaking") {
    return { streamingAssistantIndex: -1, showPendingAssistantTurn: false };
  }
  const lastAssistantIdx = messages.findLastIndex((m) => m.role === "assistant");
  const lastUserIdx = messages.findLastIndex((m) => m.role === "user");
  if (lastAssistantIdx > lastUserIdx) {
    return { streamingAssistantIndex: lastAssistantIdx, showPendingAssistantTurn: false };
  }
  return { streamingAssistantIndex: -1, showPendingAssistantTurn: true };
}

/**
 * Computes the visual and accessible state of the dock audio stretch bubble (`#voice-bubble`).
 * Speaker mute (`sound === false`) pauses audio-stretch animations without mutating transcript turns.
 */
export function resolveVoiceBubbleState(input: VoiceBubbleInput): VoiceBubbleView {
  if (!input.active) {
    if (input.playingSample && input.sound) {
      return {
        isActive: true,
        isSample: true,
        isListening: false,
        isMuted: false,
        label: "Playing sample",
        ariaLabel: `Audio status: playing ${input.agentName} voice sample`,
      };
    }
    if (input.muted) {
      return {
        isActive: false,
        isSample: false,
        isListening: false,
        isMuted: true,
        label: "Mic muted",
        ariaLabel: "Audio status: microphone pre-muted before call",
      };
    }
    return {
      isActive: false,
      isSample: false,
      isListening: false,
      isMuted: false,
      label: "",
      ariaLabel: "Audio status: idle",
    };
  }

  if (input.phase === "speaking") {
    if (!input.sound) {
      return {
        isActive: false,
        isSample: false,
        isListening: false,
        isMuted: false,
        label: `${input.agentName} · speaker off`,
        ariaLabel: `Audio status: ${input.agentName} speaking with speaker muted`,
      };
    }
    return {
      isActive: true,
      isSample: false,
      isListening: false,
      isMuted: false,
      label: `${input.agentName} · speaking`,
      ariaLabel: `Audio status: ${input.agentName} speaking`,
    };
  }

  if (input.muted) {
    return {
      isActive: false,
      isSample: false,
      isListening: false,
      isMuted: true,
      label: "Mic muted",
      ariaLabel: "Audio status: microphone muted",
    };
  }

  if (input.phase === "connecting") {
    return {
      isActive: false,
      isSample: false,
      isListening: true,
      isMuted: false,
      label: "Connecting",
      ariaLabel: "Audio status: connecting to voice backend",
    };
  }

  if (input.phase === "thinking") {
    return {
      isActive: false,
      isSample: false,
      isListening: true,
      isMuted: false,
      label: "Thinking",
      ariaLabel: "Audio status: model thinking",
    };
  }

  return {
    isActive: false,
    isSample: false,
    isListening: true,
    isMuted: false,
    label: "Listening",
    ariaLabel: "Audio status: listening for speech",
  };
}

/**
 * Formats Backend URL validation errors into clear user-facing guidance without leaking raw
 * browser `TypeError: Failed to construct 'URL'` strings.
 */
export function formatBackendUrlError(err: unknown): string {
  const fallback = "Enter a full http:// or https:// URL (for example, http://localhost:7860).";
  if (typeof err !== "object" || err === null) {
    return fallback;
  }
  const name = "name" in err && typeof err.name === "string" ? err.name : "";
  const message = "message" in err && typeof err.message === "string" ? err.message.trim() : "";
  if (!message || name === "TypeError" || /failed to construct|invalid url/i.test(message)) {
    return fallback;
  }
  return message;
}

/**
 * Returns `true` only when `backendUrl` is non-empty and differs from the default page origin,
 * keeping the optional Custom Server URL disclosure closed by default on standard origins.
 */
export function hasCustomBackendOrigin(backendUrl?: string, defaultOrigin?: string): boolean {
  const trimmed = (backendUrl ?? "").trim().replace(/\/+$/, "");
  if (!trimmed) {
    return false;
  }
  const baseline = (defaultOrigin ?? "").trim().replace(/\/+$/, "");
  return trimmed !== baseline;
}

/**
 * Reconciles the open state of the Custom Server URL `<details>` disclosure so validation errors
 * force it open while clearing an error (`null`) never collapses it under the user's cursor.
 */
export function reconcileCustomDetailsOpen(
  currentlyOpen: boolean,
  backendUrlError: string | null,
): boolean {
  return backendUrlError ? true : currentlyOpen;
}

/** Stage latencies reported on a turn in seconds. */
export interface TurnLatencyMetrics {
  readonly sttLatency?: number;
  readonly llmLatency?: number;
  readonly ttsLatency?: number;
  readonly interruptedMs?: number;
}

function finiteNonNegative(value: number | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

/**
 * Computes end-to-end turn Time-To-First-Byte (TTFB) in seconds.
 *
 * In `cascade` mode, total TTFB sums all active pipeline stage latencies (`STT + LLM + TTS`) once
 * TTS emits its first audio byte (or if a turn was interrupted after LLM started), preventing
 * partial `STT + LLM` subtotals from flashing prematurely. In `live` mode, `llmLatency` (`ttft`)
 * is single-hop Live TTFB.
 */
export function computeTurnTtfbSeconds(
  metrics: TurnLatencyMetrics | undefined,
  engine: "live" | "cascade",
): number | null {
  if (!metrics) {
    return null;
  }
  const llm = finiteNonNegative(metrics.llmLatency);
  if (engine === "live") {
    return llm;
  }
  const stt = finiteNonNegative(metrics.sttLatency);
  const tts = finiteNonNegative(metrics.ttsLatency);
  const wasInterrupted = finiteNonNegative(metrics.interruptedMs) !== null;
  if (tts === null && !(wasInterrupted && llm !== null)) {
    return null;
  }
  return (stt ?? 0) + (llm ?? 0) + (tts ?? 0);
}

/**
 * Formats a latency duration in seconds for transcript chips, dock stats, and observability
 * (for example, `1.8s`, `0.3s`, `0.05s`), returning `"--"` when unavailable.
 */
export function formatLatencySeconds(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) {
    return "--";
  }
  if (seconds === 0) {
    return "0.0s";
  }
  const roundedHundredths = Math.round(seconds * 100) / 100;
  if (roundedHundredths >= 0.1) {
    return `${(Math.round(seconds * 10) / 10).toFixed(1)}s`;
  }
  if (seconds >= 0.01) {
    return `${roundedHundredths.toFixed(2)}s`;
  }
  return `${(Math.round(seconds * 1000) / 1000).toFixed(3)}s`;
}

/**
 * Returns `true` when the displayed 1-decimal TTFB in seconds is within the fast target budget
 * (`< 0.5s` for single-hop Gemini Live native audio; `< 1.5s` for 3-stage Cascade STT + LLM + TTS).
 */
export function isFastTtfbSeconds(
  seconds: number | null | undefined,
  engine: "live" | "cascade",
): boolean {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) {
    return false;
  }
  const displayedTenths = Math.round(seconds * 10) / 10;
  return displayedTenths < (engine === "cascade" ? 1.5 : 0.5);
}
