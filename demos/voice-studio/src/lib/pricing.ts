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
  if (clean.includes("2.5") || clean.includes("gemini-live-2.5")) {
    return LIVE_RATE_CARDS["gemini-2.5"];
  }

  // Gemini 3.1 Flash Live Preview
  if (clean.includes("3.1") && (clean.includes("live") || clean.includes("flash"))) {
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
  prompt_token_count?: number;
  response_token_count?: number;
  total_token_count?: number;
  prompt_details?: { text?: number; audio?: number };
  response_details?: { text?: number; audio?: number };
}

export interface TurnCostResult {
  totalUSD: number;
  audioInUSD: number;
  audioOutUSD: number;
  textInUSD: number;
  textOutUSD: number;
  tier: LivePricingTier;
  rateCard: LiveRateCard;
}

/**
 * Computes exact turn cost based on model rate card and usage tokens.
 */
export function calculateTurnCost(model: string, usage?: UsageTokenData | null): TurnCostResult | null {
  if (!usage) return null;
  const card = getLiveRateCard(model);
  if (!card) return null;

  const pd = (usage.prompt_details || {}) as Record<string, number>;
  let audioInTokens = 0;
  let textInTokens = 0;

  for (const [key, val] of Object.entries(pd)) {
    const k = key.toLowerCase();
    const count = typeof val === "number" ? val : 0;
    if (k.includes("audio")) {
      audioInTokens += count;
    } else if (k.includes("text")) {
      textInTokens += count;
    }
  }

  // If prompt details didn't specify modality, prompt tokens are predominantly text (system prompt + history)
  if (audioInTokens === 0 && textInTokens === 0 && usage.prompt_token_count) {
    textInTokens = usage.prompt_token_count;
  }

  const rd = (usage.response_details || {}) as Record<string, number>;
  let audioOutTokens = 0;
  let textOutTokens = 0;

  for (const [key, val] of Object.entries(rd)) {
    const k = key.toLowerCase();
    const count = typeof val === "number" ? val : 0;
    if (k.includes("audio")) {
      audioOutTokens += count;
    } else if (k.includes("text")) {
      textOutTokens += count;
    }
  }

  // In Gemini Live native audio flow, model response without explicit text detail is audio output
  if (audioOutTokens === 0 && textOutTokens === 0 && usage.response_token_count) {
    audioOutTokens = usage.response_token_count;
  }

  const audioInUSD = (audioInTokens / 1_000_000) * card.audioInPerMillion;
  const textInUSD = (textInTokens / 1_000_000) * card.textInPerMillion;
  const audioOutUSD = (audioOutTokens / 1_000_000) * card.audioOutPerMillion;
  const textOutUSD = (textOutTokens / 1_000_000) * card.textOutPerMillion;

  const totalUSD = audioInUSD + textInUSD + audioOutUSD + textOutUSD;

  return {
    totalUSD,
    audioInUSD,
    audioOutUSD,
    textInUSD,
    textOutUSD,
    tier: card.tier,
    rateCard: card,
  };
}

/**
 * Formats a fractional USD value into human-friendly currency.
 * Handles sub-cent amounts gracefully (e.g., $0.0014, <$0.0001, $1.23).
 */
export function formatCost(usd: number): string {
  if (!usd || usd <= 0) return "$0.0000";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 1.0) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}
