import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

function loadLib(relPath) {
  const root = fileURLToPath(new URL('../src/', import.meta.url));
  const cache = new Map();

  function compile(rel) {
    const full = path.resolve(root, rel);
    if (cache.has(full)) return cache.get(full);
    const source = fs.readFileSync(full, 'utf8');
    const js = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const mod = { exports: {} };
    cache.set(full, mod.exports);
    vm.runInNewContext(
      js,
      {
        module: mod,
        exports: mod.exports,
        require: (specifier) => {
          const resolved = specifier.startsWith('@/')
            ? specifier.slice(2)
            : path.relative(root, path.resolve(path.dirname(full), specifier));
          const withExt = resolved.endsWith('.ts') ? resolved : `${resolved}.ts`;
          return compile(withExt);
        },
        URL,
        URLSearchParams,
        window: {
          location: {
            origin: 'https://voice-studio.example.com',
            protocol: 'https:',
            host: 'voice-studio.example.com',
          },
        },
      },
      { filename: full },
    );
    cache.set(full, mod.exports);
    return mod.exports;
  }

  return compile(relPath);
}

test('formatCents and formatSessionCents express all costs strictly in cents (¢)', () => {
  const cc = loadLib('lib/call-console.ts');

  assert.equal(cc.formatCents(0), '0.00¢');
  assert.equal(cc.formatCents(-1), '0.00¢');
  assert.equal(cc.formatCents(0.00004), '<0.01¢');
  assert.equal(cc.formatCents(0.0009), '0.09¢');
  assert.equal(cc.formatCents(0.0255), '2.55¢');
  assert.equal(cc.formatCents(0.124), '12.40¢');

  assert.equal(
    cc.formatSessionCents({
      engine: 'live',
      model: 'gemini-3.8-live',
      sessionCostUSD: 0.0021,
      cascadeCost: null,
      incomplete: false,
      estimated: false,
    }),
    '0.21¢',
  );
  assert.equal(
    cc.formatSessionCents({
      engine: 'live',
      model: 'gemini-3.8-live',
      sessionCostUSD: 0.0021,
      cascadeCost: null,
      incomplete: false,
      estimated: true,
    }),
    '~0.21¢',
  );
  assert.equal(
    cc.formatSessionCents({
      engine: 'cascade',
      model: 'gemini-3.8-live',
      sessionCostUSD: 0,
      cascadeCost: { known_usd: '0.0032', complete: true, stages: [] },
      incomplete: false,
      estimated: false,
    }),
    '0.32¢',
  );
});

test('getScenarioStages covers all 9 personas with complete Tara 8-stage SOP and Custom setup stages', () => {
  const cc = loadLib('lib/call-console.ts');
  const personasMod = loadLib('lib/personas.ts');

  assert.equal(personasMod.PERSONAS.length, 9);

  for (const persona of personasMod.PERSONAS) {
    const stages = cc.getScenarioStages(persona);
    assert.ok(stages.length >= 3, `${persona.id} must have at least 3 stages`);
    for (const st of stages) {
      assert.match(st.num, /^\d{2}$/);
      assert.ok(st.title.length > 0);
      assert.ok(st.detail.length > 0);
      assert.doesNotMatch(st.detail, /—/, `${persona.id} stage copy must not contain em-dashes`);
    }
    const accent = cc.getPersonaUiAccent(persona.id);
    assert.match(accent, /^#[0-9a-f]{6}$/i);
    assert.ok(cc.getPersonaCastRole(persona).length > 0);
  }

  const tara = personasMod.PERSONAS.find((p) => p.id === 'travel-concierge');
  assert.equal(cc.getScenarioStages(tara).length, 8);

  const custom = personasMod.PERSONAS.find((p) => p.id === 'custom');
  assert.equal(cc.getScenarioStages(custom).length, 3);
});

test('getPipelineNodes reflects Live, 3.8 Avatar, Cascade STT, and Skip STT configurations', () => {
  const cc = loadLib('lib/call-console.ts');
  const vs = loadLib('lib/voice-session.ts');

  const liveNodes = cc.getPipelineNodes({
    ...vs.DEFAULT_SETTINGS,
    engine: 'live',
    model: 'gemini-3.8-live',
    avatarEnabled: false,
  });
  assert.equal(liveNodes.length, 3);
  assert.equal(liveNodes[1].title, 'gemini-3.8-live');

  const avatarNodes = cc.getPipelineNodes({
    ...vs.DEFAULT_SETTINGS,
    engine: 'live',
    model: 'gemini-3.8-live',
    avatarEnabled: true,
  });
  assert.equal(avatarNodes[1].title, 'gemini-3.8-live + Avatar');

  const cascadeSkipNodes = cc.getPipelineNodes({
    ...vs.DEFAULT_SETTINGS,
    engine: 'cascade',
    skipStt: true,
    llmModel: 'gemini-3.8-flash',
    ttsModel: 'gemini-3.8-flash-tts',
  });
  assert.equal(cascadeSkipNodes[0].title, 'Direct audio to LLM');
  assert.equal(cascadeSkipNodes[1].title, 'gemini-3.8-flash');
  assert.equal(cascadeSkipNodes[2].title, 'gemini-3.8-flash-tts');
});

test('resolveVoiceBubbleState decouples speaker mute from transcript turns by pausing audio stretch animation', () => {
  const cc = loadLib('lib/call-console.ts');

  const idle = cc.resolveVoiceBubbleState({
    active: false,
    phase: 'idle',
    sound: true,
    muted: false,
    playingSample: false,
    agentName: 'Meera',
  });
  assert.equal(idle.isActive, false);
  assert.equal(idle.label, '');

  const sample = cc.resolveVoiceBubbleState({
    active: false,
    phase: 'idle',
    sound: true,
    muted: false,
    playingSample: true,
    agentName: 'Meera',
  });
  assert.equal(sample.isActive, true);
  assert.equal(sample.isSample, true);
  assert.equal(sample.label, 'Playing sample');

  const speakingAudible = cc.resolveVoiceBubbleState({
    active: true,
    phase: 'speaking',
    sound: true,
    muted: false,
    playingSample: false,
    agentName: 'Meera',
  });
  assert.equal(speakingAudible.isActive, true);
  assert.equal(speakingAudible.isSample, false);
  assert.equal(speakingAudible.label, 'Meera · speaking');

  const speakingSpeakerOff = cc.resolveVoiceBubbleState({
    active: true,
    phase: 'speaking',
    sound: false,
    muted: false,
    playingSample: false,
    agentName: 'Meera',
  });
  assert.equal(speakingSpeakerOff.isActive, false);
  assert.equal(speakingSpeakerOff.label, 'Meera · speaker off');

  const listeningMuted = cc.resolveVoiceBubbleState({
    active: true,
    phase: 'listening',
    sound: true,
    muted: true,
    playingSample: false,
    agentName: 'Meera',
  });
  assert.equal(listeningMuted.isActive, false);
  assert.equal(listeningMuted.isMuted, true);
  assert.equal(listeningMuted.label, 'Mic muted');
});

test('computeBubbleBarScale and computeBubblePillStretch scale monotonically with live audio RMS', () => {
  const cc = loadLib('lib/call-console.ts');

  assert.equal(cc.computeBubbleBarScale(0, 1.0), 0.26);
  assert.equal(cc.computeBubbleBarScale(0.005, 1.0), 0.26);
  const lowBar = cc.computeBubbleBarScale(0.25, 1.0);
  const highBar = cc.computeBubbleBarScale(0.85, 1.0);
  assert.ok(lowBar > 0.26, `expected lowBar > 0.26, got ${lowBar}`);
  assert.ok(highBar > lowBar, `expected highBar (${highBar}) > lowBar (${lowBar})`);
  assert.ok(cc.computeBubbleBarScale(4, 1.15) <= 1.22);

  assert.equal(cc.computeBubblePillStretch(0), 1);
  const lowStretch = cc.computeBubblePillStretch(0.25);
  const highStretch = cc.computeBubblePillStretch(0.85);
  assert.ok(lowStretch > 1);
  assert.ok(highStretch > lowStretch);
});

test('resolveStreamingAssistantState prevents Speaking now from attaching to stale assistant turns', () => {
  const cc = loadLib('lib/call-console.ts');

  assert.deepEqual({ ...cc.resolveStreamingAssistantState([], true, 'speaking') }, {
    streamingAssistantIndex: -1,
    showPendingAssistantTurn: true,
  });

  assert.deepEqual(
    {
      ...cc.resolveStreamingAssistantState(
        [{ role: 'assistant' }, { role: 'user' }],
        true,
        'speaking',
      ),
    },
    {
      streamingAssistantIndex: -1,
      showPendingAssistantTurn: true,
    },
  );

  assert.deepEqual(
    {
      ...cc.resolveStreamingAssistantState(
        [{ role: 'assistant' }, { role: 'user' }, { role: 'assistant' }],
        true,
        'speaking',
      ),
    },
    {
      streamingAssistantIndex: 2,
      showPendingAssistantTurn: false,
    },
  );

  assert.deepEqual(
    {
      ...cc.resolveStreamingAssistantState(
        [{ role: 'assistant' }, { role: 'user' }, { role: 'assistant' }],
        true,
        'listening',
      ),
    },
    {
      streamingAssistantIndex: -1,
      showPendingAssistantTurn: false,
    },
  );
});

test('formatBackendUrlError and reconcileCustomDetailsOpen keep disclosure open across typo repair', () => {
  const cc = loadLib('lib/call-console.ts');

  const rawTypeError = new TypeError("Failed to construct 'URL': Invalid URL");
  const cleanCopy = cc.formatBackendUrlError(rawTypeError);
  assert.ok(!cleanCopy.toLowerCase().includes('failed to construct'));
  assert.ok(cleanCopy.includes('http://'));
  assert.equal(
    cc.formatBackendUrlError(new Error('Backend URL cannot contain query parameters or fragments')),
    'Backend URL cannot contain query parameters or fragments',
  );

  // Closed stays closed when no error; error forces open; fixing error (null) keeps open!
  assert.equal(cc.hasCustomBackendOrigin('', 'http://127.0.0.1:7860'), false);
  assert.equal(cc.hasCustomBackendOrigin('http://127.0.0.1:7860/', 'http://127.0.0.1:7860'), false);
  assert.equal(cc.hasCustomBackendOrigin('https://custom.example.com', 'http://127.0.0.1:7860'), true);
  assert.equal(cc.reconcileCustomDetailsOpen(false, null), false);
  const afterTypo = cc.reconcileCustomDetailsOpen(false, cleanCopy);
  assert.equal(afterTypo, true);
  const afterBackspace = cc.reconcileCustomDetailsOpen(afterTypo, null);
  assert.equal(afterBackspace, true);
});
