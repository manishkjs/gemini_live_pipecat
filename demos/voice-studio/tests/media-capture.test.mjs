import test from 'node:test';
import assert from 'node:assert/strict';
import { encodeFloat32ToWav24kMonoDataUrl } from '../src/lib/media-capture.ts';

function decodeWavDataUrl(dataUrl) {
  assert.match(dataUrl, /^data:audio\/wav;base64,/);
  const bytes = Buffer.from(dataUrl.slice('data:audio/wav;base64,'.length), 'base64');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const ascii = (off, len) => String.fromCharCode(...bytes.subarray(off, off + len));
  const dataBytes = view.getUint32(40, true);
  const sampleCount = dataBytes / 2;
  const pcm = new Int16Array(sampleCount);
  for (let i = 0; i < sampleCount; i++) {
    pcm[i] = view.getInt16(44 + i * 2, true);
  }
  return {
    riff: ascii(0, 4),
    chunkSize: view.getUint32(4, true),
    wave: ascii(8, 4),
    fmt: ascii(12, 4),
    fmtSize: view.getUint32(16, true),
    audioFormat: view.getUint16(20, true),
    numChannels: view.getUint16(22, true),
    sampleRate: view.getUint32(24, true),
    byteRate: view.getUint32(28, true),
    blockAlign: view.getUint16(32, true),
    bitsPerSample: view.getUint16(34, true),
    dataTag: ascii(36, 4),
    dataBytes,
    byteLength: bytes.byteLength,
    pcm,
  };
}

function sineWave(seconds, sampleRate, amplitude = 0.5, freq = 220) {
  const n = Math.round(seconds * sampleRate);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    out[i] = amplitude * Math.sin((2 * Math.PI * freq * i) / sampleRate);
  }
  return out;
}

test('WAV encoder writes a valid 44-byte 24 kHz 16-bit mono RIFF header', () => {
  const input = sineWave(3, 24000, 0.5);
  const { dataUrl, durationSec, byteLength } = encodeFloat32ToWav24kMonoDataUrl(input, 24000);
  const wav = decodeWavDataUrl(dataUrl);

  assert.equal(durationSec, 3);
  assert.equal(byteLength, 44 + 3 * 24000 * 2);
  assert.equal(wav.byteLength, byteLength);
  assert.equal(wav.riff, 'RIFF');
  assert.equal(wav.chunkSize, 36 + wav.dataBytes);
  assert.equal(wav.wave, 'WAVE');
  assert.equal(wav.fmt, 'fmt ');
  assert.equal(wav.fmtSize, 16);
  assert.equal(wav.audioFormat, 1);
  assert.equal(wav.numChannels, 1);
  assert.equal(wav.sampleRate, 24000);
  assert.equal(wav.byteRate, 48000);
  assert.equal(wav.blockAlign, 2);
  assert.equal(wav.bitsPerSample, 16);
  assert.equal(wav.dataTag, 'data');
  assert.equal(wav.dataBytes, 3 * 24000 * 2);
});

test('WAV encoder resamples both 48 kHz and 16 kHz inputs to 24 kHz', () => {
  for (const sr of [48000, 16000]) {
    const { dataUrl, durationSec } = encodeFloat32ToWav24kMonoDataUrl(sineWave(4, sr, 0.5), sr);
    const wav = decodeWavDataUrl(dataUrl);
    assert.equal(wav.sampleRate, 24000);
    assert.equal(durationSec, 4);
    assert.equal(wav.pcm.length, 4 * 24000);
  }
});

test('WAV encoder clamps recordings longer than 20 seconds to 20 seconds', () => {
  const { dataUrl, durationSec } = encodeFloat32ToWav24kMonoDataUrl(sineWave(25, 24000, 0.5), 24000);
  const wav = decodeWavDataUrl(dataUrl);
  assert.equal(durationSec, 20);
  assert.equal(wav.pcm.length, 20 * 24000);
});

test('WAV encoder rejects empty or sub-2-second inputs', () => {
  assert.throws(() => encodeFloat32ToWav24kMonoDataUrl(new Float32Array(0), 24000), /No audio samples/);
  assert.throws(() => encodeFloat32ToWav24kMonoDataUrl(sineWave(3, 24000), 0), /No audio samples/);
  assert.throws(() => encodeFloat32ToWav24kMonoDataUrl(sineWave(1.5, 24000), 24000), /too short/);
});

test('WAV encoder normalizes quiet speech to 0.85 peak and clips out-of-range samples', () => {
  const quiet = sineWave(3, 24000, 0.1);
  const quietWav = decodeWavDataUrl(encodeFloat32ToWav24kMonoDataUrl(quiet, 24000).dataUrl);
  const maxQuiet = Math.max(...Array.from(quietWav.pcm, (v) => Math.abs(v)));
  assert.ok(Math.abs(maxQuiet - Math.round(0.85 * 32767)) <= 5, `expected ~${Math.round(0.85 * 32767)}, got ${maxQuiet}`);

  const loud = new Float32Array(3 * 24000);
  loud.fill(2.5, 0, loud.length / 2);
  loud.fill(-2.5, loud.length / 2);
  const loudWav = decodeWavDataUrl(encodeFloat32ToWav24kMonoDataUrl(loud, 24000).dataUrl);
  assert.equal(loudWav.pcm[0], 32767);
  assert.equal(loudWav.pcm[loudWav.pcm.length - 1], -32768);
});
