import test from 'node:test';
import assert from 'node:assert/strict';
import { UsageLedger } from '../src/lib/usage-ledger.ts';
import { calculateTurnCost, getLiveRateCard, accumulateSplit, EMPTY_TOKEN_SPLIT } from '../src/lib/pricing.ts';

const model = 'gemini-3.1-flash-live-preview';
const record = (id, total = 100) => ({
  session_id: 'call', response_id: id, event_id: `call:${id}:usage`,
  phase: 'final', service: 'live', revision: 0,
  prompt_token_count: 0, response_token_count: total, total_token_count: total,
  prompt_details: {}, response_details: { audio: total },
});

test('partial output has an explicit residual and cost range', () => {
  const result = calculateTurnCost(model, { ...record('a'), response_details: { audio: 10 } });
  assert.equal(result.residualOutputTokens, 90);
  assert.equal(result.estimated, true);
  assert.ok(Math.abs(result.minUSD - 0.000525) < 1e-12);
  assert.ok(Math.abs(result.maxUSD - 0.0012) < 1e-12);
  assert.ok(result.totalUSD > result.audioOutUSD);
});

test('replay is idempotent but equal counts from distinct requests both count', () => {
  const ledger = new UsageLedger();
  assert.equal(ledger.ingest(record('a')), true);
  assert.equal(ledger.ingest(record('a')), false);
  assert.equal(ledger.ingest(record('b')), true);
  assert.equal(ledger.snapshot('live', model).tokens, 200);
  assert.equal(ledger.snapshot('live', model).split.audioOut, 200);
});

test('interim usage is ignored and a final revision replaces previous usage', () => {
  const ledger = new UsageLedger();
  assert.equal(ledger.ingest({ ...record('a'), phase: 'interim' }), false);
  ledger.ingest(record('a'));
  ledger.ingest({ ...record('a', 120), event_id: 'revision-1', revision: 1 });
  ledger.ingest({ ...record('a', 90), event_id: 'late-revision-0', revision: 0 });
  assert.equal(ledger.snapshot('live', model).tokens, 120);
  assert.equal(ledger.snapshot('live', model).split.audioOut, 120);
});

test('invalid counts cannot poison session totals or produce a precise cost', () => {
  for (const bad of [-1, NaN, Infinity, 1.5]) {
    const ledger = new UsageLedger();
    assert.equal(ledger.ingest({ ...record('a'), total_token_count: bad }), false);
    assert.equal(calculateTurnCost(model, { ...record('a'), response_details: { audio: bad } }), null);
  }
  assert.equal(calculateTurnCost(model, { ...record('a'), response_details: { audio: 200 } }), null);
  assert.equal(accumulateSplit(EMPTY_TOKEN_SPLIT, { prompt_details: { text: -9 } }).textIn, 0);
});

test('model matching cannot price an unrelated text or TTS model as Live', () => {
  for (const id of ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-3.1-flash-tts-preview']) {
    assert.equal(getLiveRateCard(id), null);
  }
});

test('incomplete pricing cannot turn into a zero-dollar complete estimate', () => {
  const ledger = new UsageLedger();
  ledger.ingest({ ...record('a'), response_details: { audio: 200 } });
  assert.equal(ledger.snapshot('live', model).complete, false);
});

test('ledger snapshot with unpriced video tokens preserves partial subtotal while marking total incomplete and min/max null', () => {
  const ledger = new UsageLedger();
  ledger.ingest({
    session_id: 'call', response_id: 'turn-1', event_id: 'call:turn-1:usage',
    phase: 'final', service: 'live', revision: 0, model: 'gemini-3.8-live',
    prompt_token_count: 1417, response_token_count: 60113, thoughts_token_count: 141, total_token_count: 61671,
    prompt_details: { text: 1417 }, response_details: { audio: 223, text: 34, video: 59856 },
  });
  const snap = ledger.snapshot('live', 'gemini-3.8-live');
  assert.equal(snap.incomplete, true);
  assert.equal(snap.complete, false);
  assert.equal(snap.minUSD, null);
  assert.equal(snap.maxUSD, null);
  assert.ok(snap.costUSD > 0, 'Partial audio/text subtotal must still be tracked');
});

