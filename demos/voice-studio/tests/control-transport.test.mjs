/**
 * Wire-transport contract for every user-facing session control.
 *
 * A control that the user can move but that never changes the bytes we send is
 * a lie. This suite makes that class of bug mechanically impossible to
 * reintroduce: every field on `SessionSettings` must be classified below, and
 * every field classified as transported must demonstrably alter the request.
 *
 * When you add a setting, you must add it to TRANSPORT — the manifest
 * completeness test fails otherwise. That is deliberate.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildConnectRequest, DEFAULT_SETTINGS } from '../src/lib/voice-session.ts';

const BASE = { ...DEFAULT_SETTINGS, backendUrl: 'https://voice.example.com', language: 'hi-IN' };

/**
 * How each setting reaches the backend, per engine.
 *
 *   'query:<name>' — must appear as that URL search parameter
 *   'body:<name>'  — must appear as that key in the POST body
 *   'routing'      — changes which endpoint/host/branch is used, not a payload field
 *   null           — genuinely not applicable to this engine
 *
 * `probe` is a value distinct from the default, used to prove the field moves.
 * `requires` is merged in first, for fields only meaningful in a sub-mode.
 */
const TRANSPORT = {
  backendUrl:               { live: 'routing',                    cascade: 'routing',                     probe: 'https://other.example.com' },
  engine:                   { live: 'routing',                    cascade: 'routing',                     probe: 'cascade' },
  personaId:                { live: 'body:system_instruction',    cascade: 'body:system_instruction',     probe: 'storyteller' },
  tone:                     { live: 'body:system_instruction',    cascade: 'body:system_instruction',     probe: 'signature' },
  instructions:             { live: 'body:system_instruction',    cascade: 'body:system_instruction',     probe: 'Be brief.' },
  language:                 { live: 'query:language',             cascade: 'query:stt_language',          probe: 'en-IN' },
  voice:                    { live: 'query:voice',                cascade: 'query:tts_voice',             probe: 'Puck' },
  model:                    { live: 'query:model',                cascade: null,                          probe: 'gemini-3.1-flash-live-preview' },
  tts:                      { live: 'query:tts',                  cascade: null,                          probe: true },
  thinkingLevel:            { live: 'query:thinking_level',       cascade: null,                          probe: 'medium' },
  contextCompression:       { live: 'query:context_compression',  cascade: null,                          probe: true },
  contextCompressionTokens: { live: 'body:context_compression_trigger_tokens', cascade: null,             probe: 9000, requires: { contextCompression: true } },
  sttModel:                 { live: null,                         cascade: 'query:stt_model',             probe: 'chirp_3' },
  llmModel:                 { live: null,                         cascade: 'query:llm_model',             probe: 'gemini-2.5-flash' },
  ttsModel:                 { live: null,                         cascade: 'query:tts_model',             probe: 'google-tts' },
  skipStt:                  { live: null,                         cascade: 'query:skip_stt',              probe: true },
  toolsJson:                { live: 'body:tools',                 cascade: 'body:tools',                  probe: '[{"name":"x"}]' },

  // Partitions the process-global diagnostics buffer so concurrent demoers
  // do not see each other's logs or blend their latency percentiles.
  sessionId:                { live: 'query:session_id',           cascade: 'query:session_id',            probe: 's_abc12345' },

  // Speaking rate only has meaning where an external TTS service renders the
  // audio. On Live that is the `tts` / cloned-voice path; native audio has no
  // pace knob. So the Live probe turns external TTS on first.
  ttsPace:                  { live: 'query:tts_pace',             cascade: 'query:tts_pace',              probe: 1.75, requires: { tts: true } },

  // Turn detection applies to both engines, with different meanings:
  // Cascade drops the VADProcessor; Live defers to Gemini's server-side
  // endpointing. Either way the backend has to be told.
  vad:                      { live: 'query:vad',                  cascade: 'query:vad',                   probe: false },

  // Cloned-voice credentials must never ride in a URL. Once the server-side
  // voice registry lands this becomes `voiceProfileId`.
  customVoiceKey:           { live: 'body:custom_voice_key',      cascade: 'body:custom_voice_key',       probe: 'secret-voice-key-abc123', requires: { voice: 'Custom-Key' } },
};

function requestFor(engine, overrides = {}) {
  const { url, body } = buildConnectRequest({ ...BASE, engine, ...overrides });
  return { params: url.searchParams, body, href: url.href };
}

test('every SessionSettings field is classified in the transport manifest', () => {
  const declared = new Set(Object.keys(TRANSPORT));
  const actual = Object.keys(DEFAULT_SETTINGS);
  const unclassified = actual.filter((key) => !declared.has(key));
  assert.deepEqual(
    unclassified,
    [],
    `Unclassified settings will silently become dead controls: ${unclassified.join(', ')}`,
  );
  const stale = [...declared].filter((key) => !actual.includes(key));
  assert.deepEqual(stale, [], `Manifest references settings that no longer exist: ${stale.join(', ')}`);
});

for (const engine of ['live', 'cascade']) {
  for (const [field, spec] of Object.entries(TRANSPORT)) {
    const channel = spec[engine];
    if (channel === null || channel === 'routing') continue;

    const [kind, name] = channel.split(':');
    test(`${engine}: moving "${field}" changes ${channel}`, () => {
      const context = spec.requires ?? {};
      const before = requestFor(engine, context);
      const after = requestFor(engine, { ...context, [field]: spec.probe });

      if (kind === 'query') {
        assert.notEqual(
          after.params.get(name),
          before.params.get(name),
          `The ${engine} request never sends "${field}" as ?${name}= — the control does nothing.`,
        );
        assert.ok(
          after.params.get(name) !== null,
          `?${name}= is absent from the ${engine} request entirely.`,
        );
      } else {
        assert.notDeepEqual(
          after.body[name],
          before.body[name],
          `The ${engine} request body never carries "${field}" as "${name}" — the control does nothing.`,
        );
      }
    });
  }
}

test('cloned-voice credentials never appear anywhere in the request URL', () => {
  const secret = 'secret-voice-key-abc123';
  for (const engine of ['live', 'cascade']) {
    const { href } = requestFor(engine, { voice: 'Custom-Key', customVoiceKey: secret });
    assert.ok(
      !decodeURIComponent(href).includes(secret),
      `${engine}: the voice cloning key is exposed in the connect URL, which lands in browser history, access logs and the in-app diagnostics buffer.`,
    );
  }
});
