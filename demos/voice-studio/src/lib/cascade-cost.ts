/** Server-authoritative, revisioned public-rate estimates for a single call. */
export type CascadeStageCost = {
  stage: "stt" | "llm" | "tts";
  known_usd: string;
  complete: boolean;
  disabled: boolean;
  requests: number;
  issues: string[];
  rates: Record<string, string>[];
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
        s.rates.some(r => !r || typeof r !== "object" || Object.values(r).some(x => typeof x !== "string"))) return null;
    if (s.complete && s.issues.length) return null;
    names.add(s.stage);
  }
  if (v.complete !== v.stages.every(s => s.complete) ||
      Math.abs(v.stages.reduce((sum, s) => sum + Number(s.known_usd), 0) - Number(v.known_usd)) > 1e-8) return null;
  return v;
}
