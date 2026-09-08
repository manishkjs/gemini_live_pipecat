import test from 'node:test';
import assert from 'node:assert/strict';
import {
  getLiveRateCard,
  isLivePricingEligible,
  calculateTurnCost,
  formatCost,
  LIVE_RATE_CARDS,
} from '../src/lib/pricing.ts';

test('rate card resolution matches 2.5 models correctly with official pricing', () => {
  const models = [
    'gemini-live-2.5-flash-native-audio',
    'gemini-live-2.5-flash',
  ];
  for (const model of models) {
    const card = getLiveRateCard(model);
    assert.ok(card, `Should find rate card for ${model}`);
    assert.equal(card.tier, 'gemini-2.5');
    assert.equal(card.audioInPerMillion, 3.00);
    assert.equal(card.audioOutPerMillion, 12.00);
    assert.equal(card.textInPerMillion, 0.50);
    assert.equal(card.textOutPerMillion, 2.00);
  }
});

test('rate card resolution matches 3.1 models correctly with official pricing', () => {
  const models = [
    'gemini-3.1-flash-live-preview',
  ];
  for (const model of models) {
    const card = getLiveRateCard(model);
    assert.ok(card, `Should find rate card for ${model}`);
    assert.equal(card.tier, 'gemini-3.1');
    assert.equal(card.audioInPerMillion, 3.00);
    assert.equal(card.audioOutPerMillion, 12.00);
    assert.equal(card.textInPerMillion, 0.75);
    assert.equal(card.textOutPerMillion, 4.50);
  }
});

test('strictly NO pricing data for 3.5 models per user requirement', () => {
  const models35 = [
    'gemini-3.5-flash-live-preview',
    'gemini-3.5-flash-lite-live-preview',
    'gemini-3.5-live-preview',
    'gemini-3.5-live-extended-thinking-preview',
  ];
  for (const model of models35) {
    assert.equal(getLiveRateCard(model), null, `Rate card for ${model} must be null`);
    assert.equal(isLivePricingEligible('live', model), false, `Live pricing for ${model} must be false`);
  }
});

test('isLivePricingEligible enforces live-flow-only visibility', () => {
  // Live engine with supported 2.5 and 3.1 models
  assert.equal(isLivePricingEligible('live', 'gemini-live-2.5-flash-native-audio'), true);
  assert.equal(isLivePricingEligible('live', 'gemini-live-2.5-flash'), true);
  assert.equal(isLivePricingEligible('live', 'gemini-3.1-flash-live-preview'), true);

  // 3.5 models must NEVER be eligible
  assert.equal(isLivePricingEligible('live', 'gemini-3.5-flash-live-preview'), false);
  assert.equal(isLivePricingEligible('live', 'gemini-3.5-flash-lite-live-preview'), false);

  // Cascade engine must NEVER be eligible regardless of model name
  assert.equal(isLivePricingEligible('cascade', 'gemini-live-2.5-flash-native-audio'), false);
  assert.equal(isLivePricingEligible('cascade', 'gemini-2.5-flash'), false);
  assert.equal(isLivePricingEligible('cascade', 'gemini-3.1-flash-tts-preview'), false);

  // Unknown models
  assert.equal(isLivePricingEligible('live', 'unknown-model'), false);
  assert.equal(isLivePricingEligible('live', ''), false);
});

test('calculateTurnCost computes exact costs with modality breakdown', () => {
  // Gemini 2.5 Live:
  // Prompt: 10,000 audio in ($3.00/1M = $0.03), 1,000 text in ($0.50/1M = $0.0005)
  // Response: 5,000 audio out ($12.00/1M = $0.06), 200 text out ($2.00/1M = $0.0004)
  const usage25 = {
    prompt_token_count: 11000,
    response_token_count: 5200,
    total_token_count: 16200,
    prompt_details: { audio: 10000, text: 1000 },
    response_details: { audio: 5000, text: 200 },
  };

  const cost25 = calculateTurnCost('gemini-live-2.5-flash-native-audio', usage25);
  assert.ok(cost25, 'Cost result should be returned');
  const expectedAudioIn25 = (10000 / 1_000_000) * 3.00;
  const expectedTextIn25 = (1000 / 1_000_000) * 0.50;
  const expectedAudioOut25 = (5000 / 1_000_000) * 12.00;
  const expectedTextOut25 = (200 / 1_000_000) * 2.00;
  const expectedTotal25 = expectedAudioIn25 + expectedTextIn25 + expectedAudioOut25 + expectedTextOut25;

  assert.ok(Math.abs(cost25.totalUSD - expectedTotal25) < 0.000001);
  assert.equal(cost25.tier, 'gemini-2.5');

  // Gemini 3.1 Live with the exact same usage:
  // Audio in rate is $3.00/1M, Audio out rate is $12.00/1M, Text in is $0.75/1M, Text out is $4.50/1M
  const cost31 = calculateTurnCost('gemini-3.1-flash-live-preview', usage25);
  assert.ok(cost31);
  const expectedAudioIn31 = (10000 / 1_000_000) * 3.00;
  const expectedTextIn31 = (1000 / 1_000_000) * 0.75;
  const expectedAudioOut31 = (5000 / 1_000_000) * 12.00;
  const expectedTextOut31 = (200 / 1_000_000) * 4.50;
  const expectedTotal31 = expectedAudioIn31 + expectedTextIn31 + expectedAudioOut31 + expectedTextOut31;
  assert.ok(Math.abs(cost31.totalUSD - expectedTotal31) < 0.000001);
  assert.equal(cost31.tier, 'gemini-3.1');

  // 3.5 model returns null cost
  assert.equal(calculateTurnCost('gemini-3.5-flash-live-preview', usage25), null);
});

test('calculateTurnCost handles fallback when modality details are missing', () => {
  const usageFallback = {
    prompt_token_count: 5000,
    response_token_count: 2000,
    total_token_count: 7000,
  };

  const cost25 = calculateTurnCost('gemini-live-2.5-flash-native-audio', usageFallback);
  assert.ok(cost25);
  // Uses text in ($0.50/1M) for static prompt tokens and audio out ($12.00/1M) for response
  const expected = (5000 / 1_000_000) * 0.50 + (2000 / 1_000_000) * 12.00;
  assert.ok(Math.abs(cost25.totalUSD - expected) < 0.000001);
});

test('formatCost formats fractional cents with elegance', () => {
  assert.equal(formatCost(0), '$0.0000');
  assert.equal(formatCost(0.00004), '<$0.0001');
  assert.equal(formatCost(0.00142), '$0.0014');
  assert.equal(formatCost(0.0245), '$0.0245');
  assert.equal(formatCost(1.23456), '$1.23');
});
