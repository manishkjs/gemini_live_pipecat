import { formatCost } from "./pricing.ts";

/** Server-authoritative, revisioned public-rate estimates for a single call. */
export type CascadeStageCost = {
  stage: "stt" | "llm" | "tts";
  known_usd: string;
  complete: boolean;
  disabled: boolean;
  requests: number;
  issues: string[];
  rates: Record<string, string>[];
  /** Priced from measured inputs (e.g. streamed audio seconds) because the provider returns no usage. */
  estimated?: boolean;
  /** Aggregated LLM usage_metadata counters across requests in this call. */
  prompt_tokens?: number;
  cached_tokens?: number;
  uncached_prompt_tokens?: number;
  output_tokens?: number;
  thoughts_tokens?: number;
  cache_hit_rate?: number;
};
export type CascadeCost = {
  session_id: string;
  revision: number;
  currency: "USD";
  basis: "public-list-price";
  reviewed_at: string;
  known_usd: string;
  complete: boolean;
  stages: CascadeStageCost[];
};

const amount = (v: unknown) => typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v)) && Number(v) >= 0;
const optNonNegInt = (v: unknown) => v === undefined || (typeof v === "number" && Number.isSafeInteger(v) && v >= 0);
const optRatio = (v: unknown) => v === undefined || (typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1);

export function readCascadeCost(value: unknown, sessionId: string, previousRevision = -1): CascadeCost | null {
  if (!value || typeof value !== "object") return null;
  const v = value as CascadeCost;
  if (v.session_id !== sessionId || !Number.isSafeInteger(v.revision) || v.revision <= previousRevision ||
      v.currency !== "USD" || v.basis !== "public-list-price" || typeof v.reviewed_at !== "string" ||
      !amount(v.known_usd) || typeof v.complete !== "boolean" || !Array.isArray(v.stages) || v.stages.length !== 3) return null;
  const names = new Set<string>();
  for (const s of v.stages) {
    if (!s || !["stt", "llm", "tts"].includes(s.stage) || names.has(s.stage) || !amount(s.known_usd) ||
        typeof s.complete !== "boolean" || typeof s.disabled !== "boolean" ||
        !Number.isSafeInteger(s.requests) || s.requests < 0 || !Array.isArray(s.issues) ||
        s.issues.some(i => typeof i !== "string") || !Array.isArray(s.rates) ||
        s.rates.some(r => !r || typeof r !== "object" || Object.values(r).some(x => typeof x !== "string")) ||
        !optNonNegInt(s.prompt_tokens) || !optNonNegInt(s.cached_tokens) ||
        !optNonNegInt(s.uncached_prompt_tokens) || !optNonNegInt(s.output_tokens) ||
        !optNonNegInt(s.thoughts_tokens) || !optRatio(s.cache_hit_rate)) return null;
    if (s.complete && s.issues.length) return null;
    names.add(s.stage);
  }
  if (v.complete !== v.stages.every(s => s.complete) ||
      Math.abs(v.stages.reduce((sum, s) => sum + Number(s.known_usd), 0) - Number(v.known_usd)) > 1e-8) return null;
  return v;
}

/** Per-stage summary: never hide money already known just because a request is still in flight. */
export function stageLabel(row: CascadeStageCost | undefined): string {
  if (!row) return "pending";
  if (row.disabled) return "off";
  const known = Number(row.known_usd);
  if (!(known > 0) && !row.complete) return "pending";
  const amount = `${row.estimated ? "~" : ""}${formatCost(known)}`;
  return row.complete ? amount : `${amount} + in flight`;
}

/** Formats the LLM implicit/explicit cache hit rate reported in usage_metadata. */
export function formatCacheHit(row: CascadeStageCost | undefined): string | null {
  if (!row || row.stage !== "llm" || !(row.prompt_tokens && row.prompt_tokens > 0)) return null;
  const pct = Math.round((row.cache_hit_rate ?? (row.cached_tokens ?? 0) / row.prompt_tokens) * 100);
  return `${pct}% cache`;
}

