import { accumulateSplit, calculateTurnCost, EMPTY_TOKEN_SPLIT, type TokenSplit, type UsageTokenData } from "./pricing.ts";

export type UsageRecord = UsageTokenData & {
  event_id?: string;
  session_id?: string;
  response_id?: string;
  service?: string;
  model?: string;
  revision?: number;
  phase?: "interim" | "final";
};

/** One finalized provider request per entry. Equal counts are not identities. */
export class UsageLedger {
  private records = new Map<string, UsageRecord>();
  private seen = new Set<string>();
  private legacySequence = 0;

  ingest(record: UsageRecord): boolean {
    if (record.phase === "interim") return false;
    for (const value of [record.prompt_token_count, record.response_token_count, record.total_token_count]) {
      if (value != null && (!Number.isSafeInteger(value) || value < 0)) return false;
    }
    if (record.event_id && this.seen.has(record.event_id)) return false;
    const key = record.response_id
      ? `${record.session_id ?? ""}:${record.service ?? "llm"}:${record.response_id}`
      : record.event_id ?? `legacy:${++this.legacySequence}`;
    const previous = this.records.get(key);
    if (previous && (record.revision ?? 0) <= (previous.revision ?? 0)) return false;
    if (record.event_id) this.seen.add(record.event_id);
    this.records.set(key, record);
    return true;
  }

  snapshot(engine: string, model: string) {
    let tokens = 0, costUSD = 0, minUSD = 0, maxUSD = 0;
    let estimated = false, complete = true;
    let split: TokenSplit = { ...EMPTY_TOKEN_SPLIT };
    for (const record of this.records.values()) {
      tokens += record.total_token_count ?? ((record.prompt_token_count ?? 0) + (record.response_token_count ?? 0));
      split = accumulateSplit(split, record);
      if (engine === "live") {
        const cost = calculateTurnCost(record.model ?? model, record);
        if (cost) {
          costUSD += cost.totalUSD;
          minUSD += cost.minUSD;
          maxUSD += cost.maxUSD;
          estimated ||= cost.estimated;
        } else {
          estimated = true;
          complete = false;
        }
      }
    }
    return { tokens, split, costUSD, minUSD, maxUSD, estimated, complete };
  }
}
