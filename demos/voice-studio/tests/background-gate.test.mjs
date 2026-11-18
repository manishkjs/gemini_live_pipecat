import assert from "node:assert/strict";
import test from "node:test";

import {
  accumulateBackgroundGateStats,
  attachCascadeGateToTurn,
  consumePendingBackgroundGate,
  EMPTY_BACKGROUND_GATE_STATS,
  formatIgnoredBackgroundLabel,
  parseBackgroundGatePayload,
} from "../src/lib/background-gate.ts";

test("Live multi-sentence Turn N never steals Turn N+1 respond badge", () => {
  const { reading: gate1 } = parseBackgroundGatePayload({
    decision: "respond",
    mode: "live",
    addressed_probability: 0.96,
    background_probability: 0.04,
    latency_ms: 280,
  });
  let pending = { reading: gate1, recordedAt: 1000 };

  const c1 = consumePendingBackgroundGate(pending, 1200);
  pending = c1.nextPending;
  assert.equal(c1.attached?.addressedProbability, 0.96);
  assert.equal(pending, null);

  // Turn 1 sentence 2 arrives: pending is null so it stays unbadged.
  const c2 = consumePendingBackgroundGate(pending, 1500);
  assert.equal(c2.attached, undefined);

  const turn1Messages = [
    { id: "u1-s1", role: "user", text: "Hello there.", metrics: { backgroundGate: c1.attached } },
    { id: "u1-s2", role: "user", text: "I want to check my SIP." },
    { id: "a1", role: "assistant", text: "Sure, let me check." },
  ];

  const { reading: gate2 } = parseBackgroundGatePayload({
    decision: "respond",
    mode: "live",
    addressed_probability: 0.91,
    background_probability: 0.09,
    latency_ms: 310,
  });
  pending = { reading: gate2, recordedAt: 4000 };
  assert.equal(turn1Messages[1].metrics, undefined);

  const c3 = consumePendingBackgroundGate(pending, 4300);
  assert.equal(c3.attached?.addressedProbability, 0.91);
  assert.equal(c3.nextPending, null);
});

test("Cascade multi-sentence ignored turn dims every sentence bubble and renders badge once", () => {
  const { reading } = parseBackgroundGatePayload({
    decision: "ignore",
    mode: "cascade",
    addressed_probability: 0.05,
    background_probability: 0.95,
    latency_ms: 340,
    transcript: "Mummy ek minute. TV band karo.",
    utterance_id: 4,
  });

  const initial = Object.freeze([
    Object.freeze({ id: "a0", role: "assistant", text: "How can I help?" }),
    Object.freeze({ id: "u1", role: "user", text: "Mummy ek minute." }),
    Object.freeze({ id: "u2", role: "user", text: "TV band karo." }),
  ]);

  const firstRun = attachCascadeGateToTurn(
    initial,
    ["u1", "u2"],
    reading,
    "Mummy ek minute. TV band karo.",
    true,
  );
  const secondRun = attachCascadeGateToTurn(
    initial,
    ["u1", "u2"],
    reading,
    "Mummy ek minute. TV band karo.",
    true,
  );
  assert.deepEqual(firstRun, secondRun);

  assert.equal(firstRun[1].metrics?.backgroundGate?.decision, "ignore");
  assert.equal(firstRun[1].metrics?.backgroundGate?.continuation, true);
  assert.equal(firstRun[2].metrics?.backgroundGate?.decision, "ignore");
  assert.equal(firstRun[2].metrics?.backgroundGate?.continuation, undefined);
});

test("Overlapping Cascade Turn 1 (ignore) + Turn 2 (respond) never mis-badges Turn 2", () => {
  const { reading: ignoreT1, transcript: tx1 } = parseBackgroundGatePayload({
    decision: "ignore",
    mode: "cascade",
    addressed_probability: 0.03,
    background_probability: 0.97,
    latency_ms: 320,
    transcript: "Breaking news on Channel 9!",
    utterance_id: 1,
  });
  const { reading: respondT2, transcript: tx2 } = parseBackgroundGatePayload({
    decision: "respond",
    mode: "cascade",
    addressed_probability: 0.96,
    background_probability: 0.04,
    latency_ms: 210,
    transcript: "What is my account balance?",
    utterance_id: 2,
  });

  const initial = [
    { id: "a0", role: "assistant", text: "How can I help?" },
    { id: "m1", role: "user", text: "Breaking news on Channel 9!" },
    { id: "m2", role: "user", text: "What is my account balance?" },
  ];

  // Keyed by utterance_id: m1 gets ignore, m2 gets respond.
  const afterT1Keyed = attachCascadeGateToTurn(initial, ["m1"], ignoreT1, tx1, true);
  const afterT2Keyed = attachCascadeGateToTurn(afterT1Keyed, ["m2"], respondT2, tx2, true);
  assert.equal(afterT2Keyed[1].metrics?.backgroundGate?.decision, "ignore");
  assert.equal(afterT2Keyed[2].metrics?.backgroundGate?.decision, "respond");
  assert.equal(afterT2Keyed[2].metrics?.backgroundGate?.addressedProbability, 0.96);

  // Unkeyed fallback with both IDs present: transcript slice matching STILL isolates m1 from m2!
  const afterT1Unkeyed = attachCascadeGateToTurn(initial, ["m1", "m2"], ignoreT1, tx1, false);
  assert.equal(afterT1Unkeyed[1].metrics?.backgroundGate?.decision, "ignore");
  assert.equal(afterT1Unkeyed[2].metrics, undefined);
  const afterT2Unkeyed = attachCascadeGateToTurn(afterT1Unkeyed, ["m1", "m2"], respondT2, tx2, false);
  assert.equal(afterT2Unkeyed[2].metrics?.backgroundGate?.decision, "respond");

  // Skewed utterance_id guard: even if matchedByUtteranceId=true points at m2, a mismatched
  // non-empty transcript refuses to corrupt m2 with Turn 1's ignore badge.
  const skewedAttempt = attachCascadeGateToTurn(initial, ["m2"], ignoreT1, tx1, true);
  assert.equal(skewedAttempt[2].metrics, undefined);

  // Bracketed STT tags (`[music]`, `[noise]`) stripped by TranscriptionBroadcaster in UI bubbles
  // still match raw LLMContext transcripts cleanly!
  const bracketedBubble = [
    { id: "a0", role: "assistant", text: "How can I help?" },
    { id: "m-music", role: "user", text: "Breaking news on Channel 9!" },
  ];
  const afterBracketed = attachCascadeGateToTurn(
    bracketedBubble,
    ["m-music"],
    ignoreT1,
    "[music] Breaking news on Channel 9! [noise]",
    true,
  );
  assert.equal(afterBracketed[1].metrics?.backgroundGate?.decision, "ignore");
});

test("Cascade skip_stt attaches badge to audio placeholder bubble and formats empty fallback", () => {
  const { reading } = parseBackgroundGatePayload({
    decision: "ignore",
    mode: "cascade",
    addressed_probability: 0.08,
    background_probability: 0.92,
    latency_ms: 295,
    audio_duration_secs: 1.6,
    transcript: "",
    utterance_id: 3,
  });

  const items = [
    { id: "a0", role: "assistant", text: "Welcome!" },
    { id: "u-audio", role: "user", text: "🎤 Audio Message (1.6s)" },
  ];
  const updated = attachCascadeGateToTurn(items, ["u-audio"], reading, "", true);
  assert.equal(updated[1].metrics?.backgroundGate?.decision, "ignore");
  assert.equal(updated[1].metrics?.backgroundGate?.latencyMs, 295);
  assert.equal(formatIgnoredBackgroundLabel("", 1.6), "🔇 Background speech (1.6s)");
});

test("parseBackgroundGatePayload preserves >160-character transcripts and accumulates gate token stats", () => {
  const longText = "Please transfer five thousand rupees from my savings account ".repeat(5).trim();
  assert.ok(longText.length > 250);
  const parsed = parseBackgroundGatePayload({
    decision: "respond",
    mode: "cascade",
    addressed_probability: 0.98,
    background_probability: 0.02,
    latency_ms: 220,
    transcript: longText,
    input_tokens: 84,
    output_tokens: 2,
    utterance_id: 7,
  });
  assert.equal(parsed.transcript, longText);
  assert.equal(parsed.reading.inputTokens, 84);
  assert.equal(parsed.reading.outputTokens, 2);
  assert.equal(parsed.reading.utteranceId, 7);

  let stats = accumulateBackgroundGateStats(EMPTY_BACKGROUND_GATE_STATS, parsed.reading);
  const ignored = parseBackgroundGatePayload({
    decision: "ignore",
    mode: "live",
    addressed_probability: 0.04,
    latency_ms: 190,
    input_tokens: 60,
    output_tokens: 2,
  });
  stats = accumulateBackgroundGateStats(stats, ignored.reading);
  assert.equal(stats.count, 2);
  assert.equal(stats.ignoredCount, 1);
  assert.equal(stats.totalInputTokens, 144);
  assert.equal(stats.totalOutputTokens, 4);
  assert.equal(stats.lastLatencyMs, 190);
  assert.equal(stats.lastDecision, "ignore");
});

test("attachCascadeGateToTurn dims and badges multi-VAD-segment SmartTurn clauses when matchedByUtteranceId holds only the final clause ID", () => {
  const parsed = parseBackgroundGatePayload({
    decision: "ignore",
    mode: "cascade",
    addressed_probability: 0.04,
    background_probability: 0.96,
    latency_ms: 280,
    transcript: "Hey mom pass the water. I am on a call right now.",
    utterance_id: 2,
    utterance_ids: [1, 2],
  });
  assert.deepEqual(parsed.reading.utteranceIds, [1, 2]);

  const items = [
    { id: "a0", role: "assistant", text: "How can I help?" },
    { id: "m1", role: "user", text: "Hey mom pass the water.", metrics: { utteranceId: 1 } },
    { id: "m2", role: "user", text: "I am on a call right now.", metrics: { utteranceId: 2 } },
  ];
  // Even when a caller passes only ["m2"] (utteranceId=2) with matchedByUtteranceId=true,
  // both clauses of the merged SmartTurn utterance are dimmed and m2 gets the chip!
  const updated = attachCascadeGateToTurn(
    items,
    ["m2"],
    parsed.reading,
    parsed.transcript,
    true,
  );
  assert.equal(updated[1].metrics?.backgroundGate?.decision, "ignore");
  assert.equal(updated[1].metrics?.backgroundGate?.continuation, true);
  assert.equal(updated[2].metrics?.backgroundGate?.decision, "ignore");
  assert.equal(updated[2].metrics?.backgroundGate?.continuation, undefined);
});
