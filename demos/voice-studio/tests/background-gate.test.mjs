import assert from "node:assert/strict";
import test from "node:test";

import {
  attachCascadeGateToTurn,
  consumePendingBackgroundGate,
  formatIgnoredBackgroundLabel,
  parseBackgroundGatePayload,
} from "../src/lib/background-gate.ts";

test("Live multi-sentence Turn N never steals Turn N+1 respond badge", () => {
  // Turn 1: Gate responds -> first sentence consumes pending -> second sentence stays unbadged.
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

  // Turn 2: Live gate emits "respond" BEFORE Gemini emits Turn 2's user transcription.
  // Because Live "respond" holds in `pending` instead of scanning `turn1Messages`,
  // `u1-s2` is untouched and Turn 2's first sentence receives `gate2`.
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
  });

  const initial = Object.freeze([
    Object.freeze({ id: "a0", role: "assistant", text: "How can I help?" }),
    Object.freeze({ id: "u1", role: "user", text: "Mummy ek minute." }),
    Object.freeze({ id: "u2", role: "user", text: "TV band karo." }),
  ]);

  // StrictMode double-invocation check: pure output, zero input mutation.
  const firstRun = attachCascadeGateToTurn(initial, ["u1", "u2"], reading, "Mummy ek minute. TV band karo.");
  const secondRun = attachCascadeGateToTurn(initial, ["u1", "u2"], reading, "Mummy ek minute. TV band karo.");
  assert.deepEqual(firstRun, secondRun);

  assert.equal(firstRun[1].metrics?.backgroundGate?.decision, "ignore");
  assert.equal(firstRun[1].metrics?.backgroundGate?.continuation, true);
  assert.equal(firstRun[2].metrics?.backgroundGate?.decision, "ignore");
  assert.equal(firstRun[2].metrics?.backgroundGate?.continuation, undefined);
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
  });

  const items = [
    { id: "a0", role: "assistant", text: "Welcome!" },
    { id: "u-audio", role: "user", text: "🎤 Audio Message (1.6s)" },
  ];
  const updated = attachCascadeGateToTurn(items, ["u-audio"], reading, "");
  assert.equal(updated[1].metrics?.backgroundGate?.decision, "ignore");
  assert.equal(updated[1].metrics?.backgroundGate?.latencyMs, 295);
  assert.equal(formatIgnoredBackgroundLabel("", 1.6), "🔇 Background speech (1.6s)");
});

test("parseBackgroundGatePayload preserves >160-character transcripts and token counts", () => {
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
  });
  assert.equal(parsed.transcript, longText);
  assert.equal(parsed.reading.inputTokens, 84);
  assert.equal(parsed.reading.outputTokens, 2);
});
