import test from 'node:test';
import assert from 'node:assert/strict';
import { readToolInjection } from '../src/lib/tool-injection.ts';

const transition = (tools) => ({ type: 'phase_transition', title: 'Flight results', revision: 3, tools });

test('a card swap is read with its added and removed tools', () => {
  const event = readToolInjection(transition({
    card: 3, declared: ['SelectLanguageTool', 'FlightActionTool', 'SearchTool'],
    added: ['FlightActionTool'], removed: ['CheckAirportTool'], via: 'context_update', status: 'sent',
  }));
  assert.equal(event.card, 3);
  assert.equal(event.title, 'Flight results');
  assert.deepEqual(event.added, ['FlightActionTool']);
  assert.deepEqual(event.removed, ['CheckAirportTool']);
  assert.equal(event.via, 'context_update');
  assert.equal(event.status, 'sent');
});

test('each card gets a fresh id so the toast re-animates', () => {
  const tools = { card: 2, declared: ['SearchTool'], added: [], removed: [], via: 'static', status: 'sent' };
  assert.notEqual(readToolInjection(transition(tools)).id, readToolInjection({ ...transition(tools), revision: 4 }).id);
});

test('payloads without a tools registration are ignored', () => {
  assert.equal(readToolInjection({ type: 'phase_transition', title: 'x' }), null);
  assert.equal(readToolInjection(transition({ card: 'two', declared: [] })), null);
  assert.equal(readToolInjection(transition({ card: 2 })), null);
  assert.equal(readToolInjection(null), null);
});

test('junk fields are cleaned instead of rendered', () => {
  const event = readToolInjection(transition({
    card: 4, declared: ['TravellerDetailsTool', 7, null], added: 'oops', via: 'carrier-pigeon',
  }));
  assert.deepEqual(event.declared, ['TravellerDetailsTool']);
  assert.deepEqual(event.added, []);
  assert.deepEqual(event.removed, []);
  assert.equal(event.via, 'context_update');
  assert.equal(event.status, 'sent');
});
