/**
 * Pure state-transition helpers for the Google Decisions (`gemini-decision-1`)
 * Background Speech & Side-Talk Gate in Voice Studio.
 *
 * Keeping all ref/queue transitions outside React `setMessages` updaters makes
 * badge pairing deterministic under React 19 StrictMode double-invocation,
 * multi-sentence turns, and `skip_stt` audio-only Cascade turns.
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
  /** True on earlier bubbles of a multi-sentence ignored turn so the chip renders once. */
  readonly continuation?: boolean;
};

export interface PendingBackgroundGate {
  readonly reading: BackgroundGateReading;
  readonly recordedAt: number;
}

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
    },
    transcript,
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
  ttlMs = PENDING_BACKGROUND_GATE_TTL_MS,
): { attached?: BackgroundGateReading; nextPending: PendingBackgroundGate | null } {
  if (!pending) {
    return { nextPending: null };
  }
  if (nowMs - pending.recordedAt <= ttlMs) {
    return { attached: pending.reading, nextPending: null };
  }
  return { nextPending: null };
}

/**
 * Pure `setMessages` helper that attaches a Cascade `BackgroundGateReading` to
 * the user bubble IDs belonging to the current post-assistant user turn.
 *
 * - For `decision === "ignore"`, marks *every* bubble in `turnIds` so multi-sentence
 *   ignored turns dim uniformly and hide caller-emotion chips, setting
 *   `continuation: true` on all bubbles except the last so `STAYED QUIET` renders once.
 * - For `decision === "respond"`, attaches the badge to the exact-transcript bubble
 *   (if matched) or the first bubble in `turnIds`.
 */
export function attachCascadeGateToTurn<T extends GateBubbleShape>(
  items: readonly T[],
  turnIds: readonly string[],
  reading: BackgroundGateReading,
  transcript = "",
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

  const next = [...items];
  if (reading.decision === "ignore") {
    const primaryIdx = candidateIndices[candidateIndices.length - 1];
    for (const idx of candidateIndices) {
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

  let chosenIdx = candidateIndices[0];
  const cleanTx = transcript.trim();
  if (cleanTx) {
    for (const idx of candidateIndices) {
      if (items[idx].text.trim() === cleanTx) {
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
