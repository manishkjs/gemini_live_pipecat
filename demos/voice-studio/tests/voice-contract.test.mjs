import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildConnectRequest, buildConnectUrl, buildBackendPageUrl, validateSocketUrl, DEFAULT_SETTINGS } from '../src/lib/voice-session.ts';
import { PERSONAS } from '../src/lib/personas.ts';
const settings = { ...DEFAULT_SETTINGS, backendUrl: 'https://voice.example.com', language: 'hi-IN' };

for (const persona of PERSONAS) {
  for (const engine of ['live', 'cascade']) {
    test(`${persona.name} routes to ${engine} with the intended instructions`, () => {
      const { url, body } = buildConnectRequest({ ...settings, engine, personaId: persona.id });
      assert.equal(url.pathname, '/connect');
      assert.equal(url.searchParams.get('bot_type'), engine === 'live' ? 'gemini-live' : 'tts-llm-stt');
      if (persona.id === 'custom') assert.deepEqual(body, {});
      else {
        assert.equal(body.system_instruction, `${persona.prompt} Speak in Hindi, unless the user requests another language.`);
        assert.ok(body.system_instruction.length < 1500, 'Existing backend must accept the complete preset');
      }
      if (engine === 'live') {
        assert.equal(url.searchParams.get('model'), settings.model);
        assert.equal(url.searchParams.get('voice'), 'Aoede');
        assert.equal(url.searchParams.get('language'), 'hi-IN');
        assert.equal(url.searchParams.get('tts'), 'false');
        assert.equal(url.searchParams.has('llm_model'), false);
      } else {
        assert.equal(url.searchParams.get('stt_model'), settings.sttModel);
        assert.equal(url.searchParams.get('llm_model'), settings.llmModel);
        assert.equal(url.searchParams.get('tts_model'), settings.ttsModel);
        assert.equal(url.searchParams.get('tts_voice'), 'Aoede');
        assert.equal(url.searchParams.get('stt_language'), 'hi-IN');
        assert.equal(url.searchParams.get('skip_stt'), 'false');
        assert.equal(url.searchParams.has('model'), false);
      }
    });
  }
}
test('custom instructions replace any persona preset and are sent in the body for both engines', () => {
  for (const persona of PERSONAS) for (const engine of ['live', 'cascade']) {
    const { url, body } = buildConnectRequest({ ...settings, personaId: persona.id, engine, instructions: '  Say नमस्ते & ask a question?  ' });
    assert.equal(body.system_instruction, 'Say नमस्ते & ask a question? Speak in Hindi, unless the user requests another language.');
    assert.equal(url.searchParams.has('system_instruction'), false);
    assert.equal(decodeURIComponent(url.href).includes('नमस्ते'), false);
  }
});
test('blank custom instructions omit the override and preserve the backend default', () => {
  assert.deepEqual(buildConnectRequest({ ...settings, personaId: 'custom', instructions: ' \n ' }).body, {});
});
test('maximum custom instruction length remains under the backend limit with a language suffix', () => {
  const { body } = buildConnectRequest({ ...settings, instructions: 'x'.repeat(1000) });
  assert.ok(body.system_instruction.length < 1500);
  assert.throws(() => buildConnectRequest({ ...settings, instructions: 'x'.repeat(1001) }));
});
test('invalid persona, engine and language cannot silently start a different session', () => {
  for (const invalid of [{ personaId: 'missing' }, { engine: 'missing' }, { language: 'missing' }]) {
    assert.throws(() => buildConnectRequest({ ...settings, ...invalid }));
  }
});
test('path prefixes and trailing slashes are preserved correctly', () => {
  assert.equal(buildConnectUrl({ ...settings, backendUrl: 'https://voice.example.com/demo/' }).pathname, '/demo/connect');
});
test('rejects malformed, credentialed or unsupported backend addresses', () => {
  for (const backendUrl of ['not a URL', 'javascript:alert(1)', 'https://user:pass@example.com', 'https://voice.example.com?key=secret', 'https://voice.example.com/#fragment']) {
    assert.throws(() => buildConnectUrl({ ...settings, backendUrl }));
  }
});
test('accepts the backend WebSocket response and retains connection settings', () => {
  assert.equal(validateSocketUrl('wss://voice.example.com/ws?voice=Aoede', settings.backendUrl), 'wss://voice.example.com/ws?voice=Aoede');
});
test('rejects malformed, insecure, credentialed or unexpected WebSocket destinations', () => {
  for (const url of [undefined, 'https://voice.example.com/ws', 'wss://other.example.com/ws', 'ws://voice.example.com/ws', 'wss://user:pass@voice.example.com/ws']) {
    assert.throws(() => validateSocketUrl(url, settings.backendUrl));
  }
});
test('permits a local HTTP and WebSocket pair for local development', () => {
  assert.equal(validateSocketUrl('ws://localhost:7860/ws', 'http://localhost:7860'), 'ws://localhost:7860/ws');
  assert.equal(validateSocketUrl('ws://127.0.0.1:7860/ws', 'http://localhost:7860'), 'ws://127.0.0.1:7860/ws');
  assert.equal(validateSocketUrl('ws://localhost:7860/ws', 'http://127.0.0.1:7860'), 'ws://localhost:7860/ws');
});

test('every prepared persona defines an appropriate default voice', () => {
  for (const persona of PERSONAS) {
    assert.ok(typeof persona.defaultVoice === 'string' && persona.defaultVoice.length > 0);
  }
  assert.equal(PERSONAS.find(p => p.id === 'storyteller').defaultVoice, 'Puck');
  assert.equal(PERSONAS.find(p => p.id === 'debt-collector').defaultVoice, 'Aoede');
});

// Public asset references must survive a fresh clone without external image hosting.
test('every prepared persona ships a valid square PNG portrait', () => {
  for (const persona of PERSONAS.filter(item => item.id !== 'custom')) {
    assert.match(persona.portrait, /^\/personas\/[a-z]+\.png$/);
    const bytes = readFileSync(new URL(`../public${persona.portrait}`, import.meta.url));
    assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.equal(bytes.readUInt32BE(16), bytes.readUInt32BE(20), 'Portrait must stay square for all avatar placements');
    assert.ok(bytes.readUInt32BE(16) >= 256);
  }
  assert.equal(PERSONAS.find(item => item.id === 'custom').portrait, null);
});

test('observability and original UI shortcuts target the existing backend pages', () => {
  assert.equal(buildBackendPageUrl('https://voice.example.com', 'diagnostics'), 'https://voice.example.com/diagnostics');
  assert.equal(buildBackendPageUrl('https://voice.example.com', 'original'), 'https://voice.example.com/');
  assert.equal(buildBackendPageUrl('https://voice.example.com/demo/', 'diagnostics'), 'https://voice.example.com/demo/diagnostics');
  assert.equal(buildBackendPageUrl('https://voice.example.com/demo/', 'original'), 'https://voice.example.com/demo/');
  assert.equal(buildBackendPageUrl('http://localhost:7860', 'diagnostics'), 'http://localhost:7860/diagnostics');
});
test('backend page shortcuts reject unsafe or credential-bearing navigation targets', () => {
  for (const value of ['', 'javascript:alert(1)', 'https://user:pass@example.com', 'https://voice.example.com/?key=secret']) {
    assert.throws(() => buildBackendPageUrl(value, 'diagnostics'));
    assert.throws(() => buildBackendPageUrl(value, 'original'));
  }
});
