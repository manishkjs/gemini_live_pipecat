import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildConnectRequest, buildConnectUrl, buildBackendPageUrl, validateSocketUrl, THINKING_LEVELS, DEFAULT_SETTINGS } from '../src/lib/voice-session.ts';
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

/**
 * validateSocketUrl branches on `typeof window`, and every test above runs in
 * Node where that is undefined. These stub a window so the branch the browser
 * actually executes is covered too.
 */
function withBrowser(location, run) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window');
  globalThis.window = { location };
  try {
    return run();
  } finally {
    if (previous) Object.defineProperty(globalThis, 'window', previous);
    else delete globalThis.window;
  }
}

// A real window.location always defines `port` ("" when the URL uses the
// protocol default), so the stub must too.
const cloudtop = { hostname: 'rangarok.c.googlers.com', host: 'rangarok.c.googlers.com', port: '', protocol: 'https:' };

test('in a browser, a loopback ws_url is rewritten onto the page host for proxying', () => {
  withBrowser(cloudtop, () => {
    // The backend's :7860 must not survive; the proxy listens on the page host.
    assert.equal(
      validateSocketUrl('ws://127.0.0.1:7860/ws?voice=Aoede', 'https://rangarok.c.googlers.com'),
      'wss://rangarok.c.googlers.com/ws?voice=Aoede',
    );
  });
});

test('in a browser on localhost, a loopback ws_url on the backend port is accepted', () => {
  // Regression: Vite serves the page on :5173 while /connect reports the
  // backend's own ws://127.0.0.1:7860/ws. Both are loopback, so this is the
  // ordinary local development pairing and must not be rejected.
  const localPage = { hostname: 'localhost', host: 'localhost:5173', port: '5173', protocol: 'http:' };
  withBrowser(localPage, () => {
    assert.equal(
      validateSocketUrl('ws://127.0.0.1:7860/ws?bot_type=gemini-live', 'http://localhost:5173'),
      'ws://127.0.0.1:7860/ws?bot_type=gemini-live',
    );
    assert.equal(
      validateSocketUrl('ws://localhost:7860/ws', 'http://localhost:5173'),
      'ws://localhost:7860/ws',
    );
  });
});

test('in a browser, the same host on a different port is accepted', () => {
  // The page and the WebSocket routinely differ only by port.
  withBrowser(cloudtop, () => {
    assert.equal(
      validateSocketUrl('wss://rangarok.c.googlers.com:7860/ws', 'https://rangarok.c.googlers.com'),
      'wss://rangarok.c.googlers.com:7860/ws',
    );
  });
});

test('in a browser, the page port is preserved when the page is served on one', () => {
  const tunnelled = { hostname: 'rangarok.c.googlers.com', host: 'rangarok.c.googlers.com:5173', port: '5173', protocol: 'http:' };
  withBrowser(tunnelled, () => {
    assert.equal(
      validateSocketUrl('ws://127.0.0.1:7860/ws', 'http://rangarok.c.googlers.com:5173'),
      'ws://rangarok.c.googlers.com:5173/ws',
    );
  });
});

test('in a browser, a foreign WebSocket host is still rejected', () => {
  withBrowser(cloudtop, () => {
    for (const url of ['wss://attacker.example.com/ws', 'ws://attacker.example.com/ws', 'wss://evil.test:443/ws']) {
      assert.throws(() => validateSocketUrl(url, 'https://rangarok.c.googlers.com'), /must match your configured server host/);
    }
  });
});

test('in a browser, the configured backend host and the page host are both allowed', () => {
  withBrowser(cloudtop, () => {
    assert.equal(
      validateSocketUrl('wss://voice.example.com/ws', 'https://voice.example.com'),
      'wss://voice.example.com/ws',
    );
    assert.equal(
      validateSocketUrl('ws://rangarok.c.googlers.com/ws', 'https://voice.example.com'),
      'wss://rangarok.c.googlers.com/ws',
    );
  });
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

test('thinking level serializes correctly for Gemini Live', () => {
  const { url } = buildConnectRequest({
    ...settings,
    engine: 'live',
    thinkingLevel: 'medium',
  });
  assert.equal(url.searchParams.get('thinking'), 'true');
  assert.equal(url.searchParams.get('thinking_level'), 'medium');
});

test('thinking level "off" sends no reasoning config at all', () => {
  for (const thinkingLevel of ['off', undefined]) {
    const { url, body } = buildConnectRequest({ ...settings, engine: 'live', thinkingLevel });
    assert.equal(url.searchParams.get('thinking'), null);
    assert.equal(url.searchParams.get('thinking_level'), null);
    assert.equal(body.thinking_level, undefined);
  }
});

test('the deprecated thinking_budget is never sent for any level', () => {
  // Gemini 3 rejects requests carrying both thinking_budget and thinking_level.
  for (const thinkingLevel of ['off', 'minimal', 'low', 'medium', 'high']) {
    const { url, body } = buildConnectRequest({ ...settings, engine: 'live', thinkingLevel });
    assert.equal(url.searchParams.get('thinking_budget'), null);
    assert.equal(body.thinking_budget, undefined);
  }
});

test('every advertised thinking level is accepted and round-trips', () => {
  for (const [value] of THINKING_LEVELS) {
    const { url } = buildConnectRequest({ ...settings, engine: 'live', thinkingLevel: value });
    assert.equal(url.searchParams.get('thinking_level'), value === 'off' ? null : value);
  }
});

test('custom voices serialize by name and the cloning key never enters the URL', () => {
  const { url: urlMale } = buildConnectRequest({ ...settings, engine: 'live', voice: 'Custom-Male' });
  assert.equal(urlMale.searchParams.get('voice'), 'Custom-Male');

  const key = 'my-replicated-voice-id-123';
  const { url: urlKey, body } = buildConnectRequest({
    ...settings,
    engine: 'live',
    voice: 'Custom-Key',
    customVoiceKey: key,
  });
  // The selection is a voice *name*; the credential behind it stays in the body
  // so it never reaches browser history, access logs or the diagnostics buffer.
  assert.equal(urlKey.searchParams.get('voice'), 'Custom-Key');
  assert.equal(urlKey.searchParams.get('custom_voice_key'), null);
  assert.equal(decodeURIComponent(urlKey.href).includes(key), false);
  assert.equal(body.custom_voice_key, key);
});

test('parameters are not duplicated across the query string and the body', () => {
  // The backend appends body fields onto the existing query string, so anything
  // sent twice ends up twice in the generated ws_url.
  const { url, body } = buildConnectRequest({
    ...settings,
    engine: 'live',
    thinkingLevel: 'high',
    voice: 'Custom-Key',
    customVoiceKey: 'voicekey_abc123',
  });
  for (const key of Object.keys(body)) {
    assert.equal(url.searchParams.has(key), false, `"${key}" is sent in both the query and the body`);
  }
});

