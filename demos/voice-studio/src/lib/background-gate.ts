/**
 * Pure state-transition helpers for the Google Decisions (`gemini-decision-1`)
 * Background Speech & Side-Talk Gate in Voice Studio.
 *
 * Keeping all ref/queue transitions outside React `setMessages` updaters makes
 * badge pairing deterministic under React 19 StrictMode double-invocation,
 * overlapping Cascade turns, multi-sentence turns, and `skip_stt` audio turns.
 */

export type BackgroundGateReading = {
  readonly decision: "respond" | "ignore";
  readonly addressedProbability: number;
  readonly backgroundProbability: number;
  readonly latencyMs: number;
  readonly mode: "live" | "cascade";
  readonly reason: string;
  readonly audioDurationSecs?: number;
  readonly inputTokens?: number;
  readonly outputTokens?: number;
  readonly utteranceId?: number;
  readonly utteranceIds?: readonly number[];
  /** True on earlier bubbles of a multi-sentence ignored turn so the chip renders once. */
  readonly continuation?: boolean;
};

export interface PendingBackgroundGate {
  readonly reading: BackgroundGateReading;
  readonly recordedAt: number;
}

export interface BackgroundGateStats {
  readonly count: number;
  readonly ignoredCount: number;
  readonly totalInputTokens: number;
  readonly totalOutputTokens: number;
  readonly lastLatencyMs: number | null;
  readonly lastDecision: "respond" | "ignore" | null;
  readonly lastAddressedProbability: number | null;
}

export const EMPTY_BACKGROUND_GATE_STATS: BackgroundGateStats = {
  count: 0,
  ignoredCount: 0,
  totalInputTokens: 0,
  totalOutputTokens: 0,
  lastLatencyMs: null,
  lastDecision: null,
  lastAddressedProbability: null,
};

export interface GateBubbleShape {
  readonly id: string;
  readonly role: "user" | "assistant";
  readonly text: string;
  readonly createdAt?: number;
  readonly metrics?: { readonly backgroundGate?: BackgroundGateReading; readonly [key: string]: unknown };
}

export const PENDING_BACKGROUND_GATE_TTL_MS = 10_000;

export function parseBackgroundGatePayload(val: Record<string, unknown> | null | undefined): {
  reading: BackgroundGateReading;
  transcript: string;
} {
  const decision = val?.decision === "ignore" ? "ignore" : "respond";
  const mode = val?.mode === "live" ? "live" : "cascade";
  const rawAddressed = Number(val?.addressed_probability);
  const addressedProbability = Number.isFinite(rawAddressed)
    ? Math.max(0, Math.min(1, rawAddressed))
    : decision === "respond"
      ? 1
      : 0;
  const rawBackground = Number(val?.background_probability);
  const backgroundProbability = Number.isFinite(rawBackground)
    ? Math.max(0, Math.min(1, rawBackground))
    : Math.max(0, 1 - addressedProbability);
  const rawLatency = Number(val?.latency_ms);
  const latencyMs = Number.isFinite(rawLatency) ? Math.max(0, Math.round(rawLatency)) : 0;
  const rawDur = Number(val?.audio_duration_secs);
  const audioDurationSecs = Number.isFinite(rawDur) && rawDur >= 0 ? rawDur : undefined;
  const rawIn = Number(val?.input_tokens);
  const inputTokens = Number.isFinite(rawIn) && rawIn >= 0 ? Math.round(rawIn) : undefined;
  const rawOut = Number(val?.output_tokens);
  const outputTokens = Number.isFinite(rawOut) && rawOut >= 0 ? Math.round(rawOut) : undefined;
  const rawUtt = Number(val?.utterance_id);
  const utteranceId = Number.isSafeInteger(rawUtt) && rawUtt > 0 ? rawUtt : undefined;
  let utteranceIds: number[] | undefined;
  if (Array.isArray(val?.utterance_ids)) {
    const parsedIds = Array.from(
      new Set(
        val.utterance_ids
          .map((item) => Number(item))
          .filter((n) => Number.isSafeInteger(n) && n > 0),
      ),
    );
    if (parsedIds.length > 0) {
      utteranceIds = parsedIds;
    }
  }
  const transcript = typeof val?.transcript === "string" ? val.transcript.trim() : "";

  return {
    reading: {
      decision,
      addressedProbability,
      backgroundProbability,
      latencyMs,
      mode,
      reason: typeof val?.reason === "string" ? val.reason : "",
      audioDurationSecs,
      inputTokens,
      outputTokens,
      utteranceId,
      ...(utteranceIds ? { utteranceIds } : {}),
    },
    transcript,
  };
}

export function accumulateBackgroundGateStats(
  prev: BackgroundGateStats,
  reading: BackgroundGateReading,
): BackgroundGateStats {
  return {
    count: prev.count + 1,
    ignoredCount: prev.ignoredCount + (reading.decision === "ignore" ? 1 : 0),
    totalInputTokens: prev.totalInputTokens + (reading.inputTokens ?? 0),
    totalOutputTokens: prev.totalOutputTokens + (reading.outputTokens ?? 0),
    lastLatencyMs: reading.latencyMs,
    lastDecision: reading.decision,
    lastAddressedProbability: reading.addressedProbability,
  };
}

export function formatIgnoredBackgroundLabel(
  transcript: string,
  audioDurationSecs?: number,
): string {
  if (transcript.trim()) {
    return transcript.trim();
  }
  const durText =
    audioDurationSecs !== undefined && audioDurationSecs > 0
      ? ` (${audioDurationSecs.toFixed(1)}s)`
      : "";
  return `🔇 Background speech${durText}`;
}

export function consumePendingBackgroundGate(
  pending: PendingBackgroundGate | null,
  nowMs: number,
  utteranceId?: number,
  ttlMs = PENDING_BACKGROUND_GATE_TTL_MS,
): { attached?: BackgroundGateReading; nextPending: PendingBackgroundGate | null } {
  if (!pending) {
    return { nextPending: null };
  }
  if (nowMs - pending.recordedAt > ttlMs) {
    return { nextPending: null };
  }
  if (
    pending.reading.utteranceId !== undefined &&
    utteranceId !== undefined &&
    pending.reading.utteranceId !== utteranceId
  ) {
    // Keep pending if a newer utterance has not superseded it, else drop stale.
    return pending.reading.utteranceId > utteranceId
      ? { nextPending: pending }
      : { nextPending: null };
  }
  return { attached: pending.reading, nextPending: null };
}

function normalizeGateTranscript(s: string): string {
  return s.replace(/\[.*?\]/g, "").trim().replace(/\s+/g, " ");
}

function matchTranscriptSlice<T extends GateBubbleShape>(
  items: readonly T[],
  candidateIndices: readonly number[],
  cleanTranscript: string,
): number[] | null {
  const targetNorm = normalizeGateTranscript(cleanTranscript);
  if (!targetNorm) {
    return null;
  }
  for (let start = 0; start < candidateIndices.length; start++) {
    const parts: string[] = [];
    const matched: number[] = [];
    for (let end = start; end < candidateIndices.length; end++) {
      const idx = candidateIndices[end];
      parts.push(items[idx].text.trim());
      matched.push(idx);
      const joined = normalizeGateTranscript(parts.join(" "));
      if (joined === targetNorm) {
        return matched;
      }
      if (joined.length > targetNorm.length) {
        break;
      }
    }
  }
  return null;
}

/**
 * Pure `setMessages` helper that attaches a Cascade `BackgroundGateReading` to
 * the user bubble IDs belonging to that utterance.
 *
 * - When `matchedByUtteranceId` is false (unkeyed fallback) and `transcript` is
 *   present, narrows candidates to the exact single or multi-sentence bubble
 *   slice matching `transcript`, so an overlapping Turn 2 bubble is never
 *   accidentally marked `STAYED QUIET`.
 * - For `decision === "ignore"`, dims every bubble in the matched utterance and
 *   sets `continuation: true` on all bubbles except the last so `STAYED QUIET`
 *   renders once.
 */
export function attachCascadeGateToTurn<T extends GateBubbleShape>(
  items: readonly T[],
  turnIds: readonly string[],
  reading: BackgroundGateReading,
  transcript = "",
  matchedByUtteranceId = false,
): T[] {
  if (turnIds.length === 0) {
    return [...items];
  }
  const idSet = new Set(turnIds);
  const candidateIndices: number[] = [];
  for (let i = 0; i < items.length; i++) {
    const msg = items[i];
    if (msg.role === "user" && idSet.has(msg.id) && !msg.metrics?.backgroundGate) {
      candidateIndices.push(i);
    }
  }
  if (candidateIndices.length === 0) {
    return [...items];
  }

  const cleanTx = normalizeGateTranscript(transcript);
  let txMatchedIndices = cleanTx
    ? matchTranscriptSlice(items, candidateIndices, cleanTx)
    : null;
  if (cleanTx && txMatchedIndices === null && matchedByUtteranceId) {
    // SmartTurn / SpeechTimeout can merge >= 2 VAD segments (utterance_id K-1, K)
    // into a single Cascade turn whose `utterance_id` is K while `transcript`
    // spans Clauses 1..K. Expand across contiguous unbadged user bubbles since
    // the last assistant turn iff the matched slice ends at `candidateIndices[-1]`.
    const lastCandidateIdx = candidateIndices[candidateIndices.length - 1];
    const priorUnbadgedIndices: number[] = [];
    for (let i = 0; i <= lastCandidateIdx; i++) {
      const msg = items[i];
      if (msg.role === "assistant") {
        priorUnbadgedIndices.length = 0;
        continue;
      }
      if (msg.role === "user" && !msg.metrics?.backgroundGate) {
        priorUnbadgedIndices.push(i);
      }
    }
    const expandedMatch = matchTranscriptSlice(items, priorUnbadgedIndices, cleanTx);
    if (
      expandedMatch !== null &&
      expandedMatch[expandedMatch.length - 1] === lastCandidateIdx
    ) {
      txMatchedIndices = expandedMatch;
    }
  }
  if (cleanTx && txMatchedIndices === null) {
    // When a non-empty transcript was evaluated, refuse to attach onto a
    // bubble whose text does not match (protects against skewed utterance_ids).
    if (!matchedByUtteranceId && candidateIndices.length > 1) {
      return [...items];
    }
    if (matchedByUtteranceId) {
      return [...items];
    }
  }
  const effectiveIndices = txMatchedIndices ?? candidateIndices;

  const next = [...items];
  if (reading.decision === "ignore") {
    const primaryIdx = effectiveIndices[effectiveIndices.length - 1];
    for (const idx of effectiveIndices) {
      const target = items[idx];
      const gateForBubble: BackgroundGateReading =
        idx === primaryIdx ? reading : { ...reading, continuation: true };
      next[idx] = {
        ...target,
        metrics: { ...target.metrics, backgroundGate: gateForBubble },
      };
    }
    return next;
  }

  let chosenIdx = effectiveIndices[0];
  if (cleanTx) {
    for (const idx of effectiveIndices) {
      if (normalizeGateTranscript(items[idx].text) === cleanTx) {
        chosenIdx = idx;
        break;
      }
    }
  }
  const target = items[chosenIdx];
  next[chosenIdx] = {
    ...target,
    metrics: { ...target.metrics, backgroundGate: reading },
  };
  return next;
}
