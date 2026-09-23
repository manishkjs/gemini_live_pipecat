import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { webcrypto } from 'node:crypto';
import ts from 'typescript';

// Execute the real transport event decoder and hook; substitute only browser
// media and React scheduling. No microphone or provider is needed for ordering.
async function harness() {
  const root = fileURLToPath(new URL('../src/', import.meta.url));
  const cache = new Map();
  let handler, cursor = 0;
  const slots = [];
  const connections = [];
  const react = {
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef(initial) { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
    useCallback(fn) { return fn; }, useEffect() {},
  };
  function load(filename, overrides = {}) {
    const full = path.resolve(root, filename);
    if (cache.has(full) && !Object.keys(overrides).length) return cache.get(full);
    const compiled = ts.transpileModule(fs.readFileSync(full, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const exports = {};
    const require = name => {
      if (name in overrides) return overrides[name];
      if (name === '@pipecat-ai/websocket-transport') return {
        WebSocketTransport: class { initialize(_config, callback) { handler = callback; } },
        DailyMediaManager: class {},
      };
      if (name === '@pipecat-ai/client-js') return { RTVIMessage: class {} };
      const resolved = name.startsWith('@/') ? name.slice(2) : path.relative(root, path.resolve(path.dirname(full), name));
      return load(resolved.endsWith('.ts') ? resolved : `${resolved}.ts`);
    };
    vm.runInNewContext(compiled, {
      exports, require, crypto: webcrypto, console, performance, AbortController,
      URL, URLSearchParams, setTimeout, clearTimeout, setInterval, clearInterval,
      window: { location: { protocol: 'http:', origin: 'http://localhost:7860' } },
    }, { filename: full });
    if (!Object.keys(overrides).length) cache.set(full, exports);
    return exports;
  }
  const real = load('lib/pipecat-session.ts');
  const hook = load('hooks/use-voice-session.ts', {
    react, 'motion/react': { useReducedMotion: () => false },
    '@/lib/pipecat-session': { createLiveSession: async (settings, events) => {
      connections.push(settings);
      const session = await real.createLiveSession(settings, events);
      return { ...session, connect: async () => {} };
    } },
  });
  const render = () => { cursor = 0; return hook.useVoiceSession(); };
  const send = data => handler({ type: 'server-message', data });
  return { render, send, connections };
}

test('Cascade cost passes through the actual event decoder and resets per call', async () => {
  const h = await harness();
  await h.render().startBackend('cascade');
  const session_id = h.connections[0].sessionId;
  const payload = {type:'cascade_cost', session_id, revision:2, currency:'USD', basis:'public-list-price',
    reviewed_at:'2026-09-13', known_usd:'0.01', complete:false,
    stages:['stt','llm','tts'].map(stage => ({stage, known_usd:stage==='llm'?'0.01':'0', complete:stage==='llm',
      disabled:false, requests:1, issues:stage==='llm'?[]:['Awaiting usage'], rates:[]}))};
  h.send({type:'metrics', payload});
  assert.equal(h.render().cascadeCost.known_usd, '0.01');
  h.send({type:'metrics', payload:{...payload, revision:1, known_usd:'99'}});
  assert.equal(h.render().cascadeCost.revision, 2);
  assert.equal(h.render().tokenCount, 0); // Costs never masquerade as LLM token events.
  await h.render().endSession();
  await h.render().startBackend('cascade');
  assert.equal(h.render().cascadeCost, null);
  h.send({type:'metrics', payload});
  assert.equal(h.render().cascadeCost, null);
  await h.render().endSession();
});

test('late metrics update their response, including when another reply already exists', async () => {
  const h = await harness();
  await h.render().startBackend();
  const session_id = h.connections[0].sessionId;
  const bot = (id, text) => h.send({ type: 'transcription', participant: 'Bot', response_id: id, text });
  const metric = payload => h.send({ type: 'metrics', payload });
  bot('a', 'First answer');
  metric({ type: 'turn_complete', response_id: 'a', event_id: 'done-a' });
  bot('b', 'Second answer');
  metric({ type: 'llm_latency', response_id: 'a', value: 0.8 });
  const usage = { type: 'usage', session_id, response_id: 'a', event_id: 'usage-a', usage: { total_token_count: 100 } };
  metric(usage);
  metric(usage);
  let state = h.render();
  assert.equal(state.tokenCount, 100);
  assert.equal(state.messages[0].metrics.usage.total_token_count, 100);
  assert.equal(state.messages[0].metrics.llmLatency, 0.8);
  assert.equal(state.messages[1].metrics.usage, undefined);
  assert.equal(state.messages[1].metrics.llmLatency, undefined);
  h.send({ type: 'transcription', participant: 'User', text: 'A late transcript' });
  bot('b', ' continued');
  state = h.render();
  assert.equal(state.messages[1].text, 'Second answer continued');
  assert.equal(state.messages.length, 3);
  await state.endSession();
});

test('metrics received before text are retained for that response only', async () => {
  const h = await harness();
  await h.render().startBackend();
  h.send({ type: 'metrics', payload: { type: 'llm_latency', response_id: 'b', value: 0.25 } });
  h.send({ type: 'transcription', participant: 'Bot', response_id: 'a', text: 'A' });
  h.send({ type: 'transcription', participant: 'Bot', response_id: 'b', text: 'B' });
  const state = h.render();
  assert.equal(state.messages[0].metrics.llmLatency, undefined);
  assert.equal(state.messages[1].metrics.llmLatency, 0.25);
  await state.endSession();
});

test('start is guarded and each new call has a fresh identity and empty ledger', async () => {
  const h = await harness();
  const state = h.render();
  await Promise.all([state.startBackend(), state.startBackend()]);
  assert.equal(h.connections.length, 1);
  const first = h.connections[0].sessionId;
  await h.render().endSession();
  await h.render().startBackend();
  assert.notEqual(h.connections[1].sessionId, first);
  assert.equal(h.render().settings.sessionId, h.connections[1].sessionId);
  h.send({ type: 'metrics', payload: { type: 'usage', session_id: first, response_id: 'old', event_id: 'old-usage', usage: { total_token_count: 999 } } });
  assert.equal(h.render().tokenCount, 0);
  await h.render().endSession();
});

test('choosing Pragya resets her phase using the newly selected persona', async () => {
  const h = await harness();
  h.render().choosePersona('lamborghini-concierge');
  assert.equal(h.render().currentPhase, 'SOP_01_OPENING');
  h.render().choosePersona('custom');
  assert.equal(h.render().currentPhase, '');
});

test('current topic can return to cars while booking and visited milestones remain', async () => {
  const h = await harness();
  h.render().choosePersona('lamborghini-concierge');
  await h.render().startBackend();
  const phase = (phase_id, revision, delivery_status) => h.send({ type: 'phase_transition', phase_id, revision, delivery_status });
  phase('SOP_03_PINCODE', 1, 'sent');
  h.send({ type: 'booking_confirmed', booking_id: 'demo-booking', center_name: 'Demo lounge' });
  phase('SOP_04_BOOKED', 2, 'sent');
  phase('SOP_02_DISCOVERY', 3, 'pending');
  let state = h.render();
  assert.equal(state.currentPhase, 'SOP_04_BOOKED');
  assert.equal(state.phaseDelivery, 'pending');
  assert.equal(state.confirmedBooking.booking_id, 'demo-booking');
  assert.ok(state.visitedPhases.includes('SOP_04_BOOKED'));
  phase('SOP_03_PINCODE', 1, 'sent'); // delayed older event
  assert.equal(h.render().currentPhase, 'SOP_04_BOOKED');
  phase('SOP_02_DISCOVERY', 4, 'sent');
  assert.equal(h.render().phaseDelivery, 'sent');
  await h.render().endSession();
  await h.render().startBackend();
  assert.equal(h.render().phaseDelivery, null);
  assert.equal(h.render().confirmedBooking, null);
  phase('SOP_03_PINCODE', 1, 'failed');
  assert.equal(h.render().currentPhase, 'SOP_01_OPENING');
  assert.equal(h.render().phaseDelivery, 'failed');
  await h.render().endSession();
});

for (const [personaId, initial, target] of [
  ['groww-advisor', 'SOP_01_OVERVIEW', 'SOP_02_SCHEME_DETAILS'],
  ['reservation-agent', 'SOP_01_COMPANION_READY', 'SOP_02_VISION_CAPTURE'],
]) test(`${personaId} commits only delivered phases for the current session`, async () => {
  const h = await harness();
  h.render().choosePersona(personaId);
  assert.equal(h.render().currentPhase, initial);
  await h.render().startBackend();
  h.send({ type: 'phase_transition', phase_id: target, revision: 1, card_pushed: false, delivery_status: 'failed' });
  assert.equal(h.render().currentPhase, initial);
  h.send({ type: 'phase_transition', phase_id: target, revision: 2, card_pushed: true, session_id: 'another-call' });
  assert.equal(h.render().currentPhase, initial);
  h.send({ type: 'phase_transition', phase_id: target, revision: 2, card_pushed: true, delivery_status: 'sent' });
  assert.equal(h.render().currentPhase, target);
  assert.ok(h.render().visitedPhases.includes(target));
  await h.render().endSession();
});

test('call_state RTVI events populate callSlots and empty transcriptions clear interim transcripts without creating empty bubbles', async () => {
  const h = await harness();
  h.render().choosePersona('lamborghini-concierge');
  await h.render().startBackend();
  // Send call_state RTVI event
  h.send({ type: 'call_state', slots: { car_choice: 'Revuelto', pincode: '400001' } });
  let state = h.render();
  assert.equal(state.callSlots?.car_choice, 'Revuelto');
  assert.equal(state.callSlots?.pincode, '400001');

  // Send interim user transcript, then empty final transcription
  h.send({ type: 'interim_transcription', text: 'Stuck partial...' });
  assert.equal(h.render().partialUser, 'Stuck partial...');
  h.send({ type: 'transcription', participant: 'User', text: '' });
  state = h.render();
  assert.equal(state.partialUser, '');
  assert.equal(state.messages.length, 0);

  await state.endSession();
  await h.render().startBackend();
  assert.equal(Object.keys(h.render().callSlots).length, 0);
  await h.render().endSession();
});

