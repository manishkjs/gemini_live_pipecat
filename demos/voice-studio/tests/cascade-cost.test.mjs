import test from 'node:test';
import assert from 'node:assert/strict';
import { readCascadeCost } from '../src/lib/cascade-cost.ts';

const snapshot = () => ({
  session_id: 'call', revision: 2, currency: 'USD', basis: 'public-list-price', reviewed_at: '2026-09-13',
  known_usd: '0.002', complete: false,
  stages: ['stt', 'llm', 'tts'].map(stage => ({stage, known_usd: stage === 'llm' ? '0.002' : '0',
    complete: stage === 'llm', disabled: false, requests: 1, issues: stage === 'llm' ? [] : ['Missing usage'], rates: []})),
});

test('Cascade keeps a partial subtotal distinct from complete call cost', () => {
  const s = readCascadeCost(snapshot(), 'call');
  assert.equal(s.known_usd, '0.002');
  assert.equal(s.complete, false);
});
test('Cascade ignores another call, replay and out-of-order snapshots', () => {
  assert.equal(readCascadeCost(snapshot(), 'another'), null);
  assert.equal(readCascadeCost(snapshot(), 'call', 2), null);
  assert.equal(readCascadeCost(snapshot(), 'call', 3), null);
});
test('Cascade rejects invalid amounts and false complete claims', () => {
  for (const amount of ['NaN', 'Infinity', '-1', '', ' ']) assert.equal(readCascadeCost({...snapshot(), known_usd: amount}, 'call'), null);
  assert.equal(readCascadeCost({...snapshot(), complete: true}, 'call'), null);
  assert.equal(readCascadeCost({...snapshot(), known_usd: '99'}, 'call'), null);
  const duplicate = snapshot(); duplicate.stages[2].stage = 'llm';
  assert.equal(readCascadeCost(duplicate, 'call'), null);
});

test('Stage label always shows the known amount; partial stages say so instead of hiding it', async () => {
  const { stageLabel } = await import('../src/lib/cascade-cost.ts');
  const row = (o) => ({ stage: 'llm', known_usd: '0.0040', complete: true, disabled: false, requests: 2, issues: [], rates: [], ...o });
  assert.equal(stageLabel(row({})), '$0.0040');
  assert.equal(stageLabel(row({ complete: false, issues: ['Awaiting final provider usage'] })), '$0.0040 + in flight');
  assert.equal(stageLabel(row({ known_usd: '0', complete: false, issues: ['x'] })), 'pending');
  assert.equal(stageLabel(row({ estimated: true, known_usd: '0.0021' })), '~$0.0021');
  assert.equal(stageLabel(row({ disabled: true })), 'off');
  assert.equal(stageLabel(undefined), 'pending');
});
