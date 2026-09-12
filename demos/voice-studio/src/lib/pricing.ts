/**
 * Gemini Live Pricing & Rate Cards Module
 * Official Google Gemini API Pricing:
 * - Gemini 2.5 Flash Native Audio: https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash-native-audio
 * - Gemini 3.1 Flash Live Preview: https://ai.google.dev/gemini-api/docs/pricing#gemini-3.1-flash-live-preview
 *
 * NOTE: Pricing data is strictly enabled ONLY for Gemini 2.5 Native Audio and Gemini 3.1 Live Preview.
 * 3.5 models and Cascade engine have NO pricing data.
 */

export type LivePricingTier = "gemini-2.5" | "gemini-3.1";

export interface LiveRateCard {
  tier: LivePricingTier;
  displayName: string;
  badge: string;
  audioInPerMillion: number;
  audioOutPerMillion: number;
  textInPerMillion: number;
  textOutPerMillion: number;
  estHourlyUSD: string;
  description: string;
}

export const LIVE_RATE_CARDS: Record<LivePricingTier, LiveRateCard> = {
  "gemini-2.5": {
    tier: "gemini-2.5",
    displayName: "Gemini 2.5 Flash Native Audio",
    badge: "2.5 Native Audio",
    audioInPerMillion: 3.00,
    audioOutPerMillion: 12.00,
    textInPerMillion: 0.50,
    textOutPerMillion: 2.00,
    estHourlyUSD: "$3.00/1M audio in · $12.00/1M audio out",
    description: "Paid Tier: $3.00/1M audio in, $12.00/1M audio out · $0.50/1M text in, $2.00/1M text out",
  },
  "gemini-3.1": {
    tier: "gemini-3.1",
    displayName: "Gemini 3.1 Flash Live Preview",
    badge: "3.1 Live Preview",
    audioInPerMillion: 3.00,
    audioOutPerMillion: 12.00,
    textInPerMillion: 0.75,
    textOutPerMillion: 4.50,
    estHourlyUSD: "$3.00/1M audio in · $12.00/1M audio out",
    description: "Paid Tier: $3.00/1M audio in ($0.005/min), $12.00/1M audio out ($0.018/min) · $0.75/1M text in, $4.50/1M text out",
  },
};

/**
 * Resolves the rate card for a given Gemini Live model identifier.
 * Returns null if the model is 3.5 or any non-2.5/non-3.1 model.
 */
export function getLiveRateCard(model: string): LiveRateCard | null {
  if (!model) return null;
  const clean = model.toLowerCase().replace(/-aistudio$/, "");

  // Explicitly reject 3.5 models per user requirement
  if (clean.includes("3.5")) {
    return null;
  }

  // Gemini 2.5 Flash Native Audio / Live
  if (/^(gemini-live-2\.5-flash(?:-native-audio)?|gemini-2\.5-flash-native-audio(?:-preview(?:-\d{2}-\d{4})?)?)$/.test(clean)) {
    return LIVE_RATE_CARDS["gemini-2.5"];
  }

  // Gemini 3.1 Flash Live Preview
  if (clean === "gemini-3.1-flash-live-preview") {
    return LIVE_RATE_CARDS["gemini-3.1"];
  }

  return null;
}

/**
 * Strictly gates cost visibility.
 * Price is visible ONLY when engine is 'live' and model is Gemini 2.5 or 3.1 Live.
 * Returns false for Cascade engine, 3.5 models, or unsupported models.
 */
export function isLivePricingEligible(engine: string, model: string): boolean {
  if (engine !== "live") return false;
  return getLiveRateCard(model) !== null;
}

export interface UsageTokenData {
  prompt_token_count?: number | null;
  response_token_count?: number | null;
  total_token_count?: number | null;
  prompt_details?: { text?: number; audio?: number };
  response_details?: { text?: number; audio?: number };
}

export interface TurnCostResult {
  totalUSD: number;
  minUSD: number;
  maxUSD: number;
  residualOutputTokens: number;
  audioInUSD: number;
  audioOutUSD: number;
  textInUSD: number;
  textOutUSD: number;
  /**
   * Prompt tokens that `prompt_token_count` bills but `prompt_tokens_details`
   * never attributes to a modality. Non-zero on `gemini-3.1-flash-live-preview`
   * on every turn (b/560037988); zero on 2.5 and 3.5, which reconcile exactly.
   */
  residualTokens: number;
  residualUSD: number;
  /**
   * True when any part of this figure rests on an assumption rather than on
   * reported modality detail — either because details were absent entirely, or
   * because they did not sum to the reported token count.
   */
  estimated: boolean;
  tier: LivePricingTier;
  rateCard: LiveRateCard;
}

/**
 * Estimates model cost, preserving uncertainty when modality detail is incomplete.
 */
export function calculateTurnCost(model: string, usage?: UsageTokenData | null): TurnCostResult | null {
  if (!usage) return null;
  const card = getLiveRateCard(model);
  if (!card) return null;

  const counters = [usage.prompt_token_count, usage.response_token_count, usage.total_token_count];
  const details = [...Object.values(usage.prompt_details ?? {}), ...Object.values(usage.response_details ?? {})];
  if ([...counters, ...details].some(n => n != null && (!Number.isSafeInteger(n) || n < 0))) return null;
  const split = accumulateSplit(EMPTY_TOKEN_SPLIT, usage);
  const attributedIn = split.audioIn + split.textIn;
  const attributedOut = split.audioOut + split.textOut;
  if ((usage.prompt_token_count != null && attributedIn > usage.prompt_token_count) ||
      (usage.response_token_count != null && attributedOut > usage.response_token_count)) return null;
  const audioInUSD = split.audioIn * card.audioInPerMillion / 1_000_000;
  const textInUSD = split.textIn * card.textInPerMillion / 1_000_000;
  const audioOutUSD = split.audioOut * card.audioOutPerMillion / 1_000_000;
  const textOutUSD = split.textOut * card.textOutPerMillion / 1_000_000;
  const knownUSD = audioInUSD + textInUSD + audioOutUSD + textOutUSD;
  const residualUSD = split.residualIn * card.textInPerMillion / 1_000_000;
  // Unknown modalities have a range. Keep the historical point estimate for
  // callers, but never present that assumption as a measured bill.
  const minUSD = knownUSD + (split.residualIn * Math.min(card.textInPerMillion, card.audioInPerMillion)
    + split.residualOut * Math.min(card.textOutPerMillion, card.audioOutPerMillion)) / 1_000_000;
  const maxUSD = knownUSD + (split.residualIn * Math.max(card.textInPerMillion, card.audioInPerMillion)
    + split.residualOut * Math.max(card.textOutPerMillion, card.audioOutPerMillion)) / 1_000_000;
  return {
    totalUSD: knownUSD + residualUSD + split.residualOut * card.audioOutPerMillion / 1_000_000,
    minUSD, maxUSD, audioInUSD, textInUSD, audioOutUSD, textOutUSD,
    residualTokens: split.residualIn, residualOutputTokens: split.residualOut, residualUSD,
    estimated: split.residualIn > 0 || split.residualOut > 0 ||
      usage.prompt_token_count == null || usage.response_token_count == null,
    tier: card.tier, rateCard: card,
  };
}

/**
 * Formats a fractional USD value into human-friendly currency.
 * Handles sub-cent amounts gracefully (e.g., $0.0014, <$0.0001, $1.23).
 */
export function formatCost(usd: number): string {
  if (!usd || usd <= 0) return "$0.0000";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1.0) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

/**
 * Estimates LLM token count for a text string.
 *
 * Script-aware, and mirrors `estimate_tokens()` in `server/agent_live.py` so
 * the two halves of the app never disagree about the size of a prompt. Latin
 * text runs ~3.8 characters per token; Devanagari runs closer to ~1.8, so a
 * single divisor would let a Hindi instruction blow the budget while the
 * counter still read comfortably under it.
 */
export function estimateTokens(text: string): number {
  const t = text?.trim();
  if (!t) return 0;
  let devanagari = 0;
  for (const ch of t) {
    const c = ch.codePointAt(0)!;
    if (c >= 0x0900 && c <= 0x097f) devanagari++;
  }
  return Math.max(1, Math.round(devanagari / 1.8 + (t.length - devanagari) / 3.8));
}

/* ==========================================================================
   SESSION TOKEN SPLIT
   --------------------------------------------------------------------------
   A single "Tokens: 16,562" figure is close to meaningless for a duplex voice
   call, because the four buckets it merges are priced 24x apart end to end
   ($0.50/M text-in vs $12.00/M audio-out). A session that is 80% audio costs
   roughly six times one of the same token count that is 80% text.

   These helpers keep the split honest in two ways the flat counter cannot:
     - `residualIn` carries prompt tokens that `prompt_token_count` bills but
       `prompt_tokens_details` never attributes (b/560037988). They are real
       money and must not silently vanish into the text bucket.
     - Accumulation is pure, so it can only ever be driven by the discrete
       per-turn `usage` event, never by a streaming chunk callback.
   ========================================================================== */

export interface TokenSplit {
  textIn: number;
  audioIn: number;
  /** Billed on input but unattributed to any modality by the server. */
  residualIn: number;
  textOut: number;
  audioOut: number;
  /** Output tokens the server billed but left unattributed. */
  residualOut: number;
}

export const EMPTY_TOKEN_SPLIT: TokenSplit = {
  textIn: 0,
  audioIn: 0,
  residualIn: 0,
  textOut: 0,
  audioOut: 0,
  residualOut: 0,
};

export function totalIn(s: TokenSplit): number {
  return s.textIn + s.audioIn + s.residualIn;
}

export function totalOut(s: TokenSplit): number {
  return s.textOut + s.audioOut + s.residualOut;
}

/**
 * Folds one turn's `usage` payload into the running session split.
 *
 * Pure and total: an absent or malformed payload returns the accumulator
 * untouched rather than poisoning the session counters with NaN.
 */
export function accumulateSplit(acc: TokenSplit, usage?: UsageTokenData | null): TokenSplit {
  if (!usage) return acc;

  const num = (v: unknown) => (typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : 0);

  const pd = (usage.prompt_details || {}) as Record<string, number>;
  const rd = (usage.response_details || {}) as Record<string, number>;

  const modality = (details: Record<string, number>, name: string) => Object.entries(details)
    .filter(([key]) => key.toLowerCase().replace(/^modality\./, "") === name)
    .reduce((sum, [, value]) => sum + num(value), 0);
  const textIn = modality(pd, "text");
  const audioIn = modality(pd, "audio");
  const textOut = modality(rd, "text");
  const audioOut = modality(rd, "audio");

  const promptTotal = num(usage.prompt_token_count);
  const responseTotal = num(usage.response_token_count);

  return {
    textIn: acc.textIn + textIn,
    audioIn: acc.audioIn + audioIn,
    residualIn: acc.residualIn + Math.max(0, promptTotal - textIn - audioIn),
    textOut: acc.textOut + textOut,
    audioOut: acc.audioOut + audioOut,
    residualOut: acc.residualOut + Math.max(0, responseTotal - textOut - audioOut),
  };
}

/** Compact token count for dense UI: 847, 1.2k, 16.6k. */
export function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(1)}k`;
}
