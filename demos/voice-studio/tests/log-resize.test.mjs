import test from 'node:test';
import assert from 'node:assert/strict';
import { LOG_HEIGHT, clampLogHeight, dragLogHeight, keyLogHeight, toggleLogHeight } from '../src/lib/log-resize.ts';

test('the height stays between the minimum and most of the viewport', () => {
  assert.equal(clampLogHeight(50, 1000), LOG_HEIGHT.min);
  assert.equal(clampLogHeight(5000, 1000), 850);
  assert.equal(clampLogHeight(400, 1000), 400);
  assert.equal(clampLogHeight(Number.NaN, 1000), LOG_HEIGHT.initial);
});

test('dragging the handle down grows the log by the distance moved', () => {
  assert.equal(dragLogHeight(280, 100, 260, 1000), 440);
  assert.equal(dragLogHeight(280, 300, 100, 1000), LOG_HEIGHT.min);
});

test('arrow keys step the height and Home/End jump to the ends', () => {
  assert.equal(keyLogHeight(280, 'ArrowDown', 1000), 280 + LOG_HEIGHT.step);
  assert.equal(keyLogHeight(280, 'ArrowUp', 1000), 280 - LOG_HEIGHT.step);
  assert.equal(keyLogHeight(280, 'End', 1000), 850);
  assert.equal(keyLogHeight(280, 'Home', 1000), LOG_HEIGHT.min);
  assert.equal(keyLogHeight(280, 'a', 1000), null);
});

test('double-click expands, and a second double-click restores', () => {
  assert.equal(toggleLogHeight(280, 1000), 850);
  assert.equal(toggleLogHeight(850, 1000), LOG_HEIGHT.initial);
});

test('a stored height is read safely: blocked storage or junk falls back to the default', async () => {
  const { readStoredLogHeight, writeStoredLogHeight } = await import('../src/lib/log-resize.ts');
  const throwing = { getItem() { throw new Error('SecurityError'); }, setItem() { throw new Error('QuotaExceeded'); } };
  assert.equal(readStoredLogHeight(throwing, 1000), LOG_HEIGHT.initial);
  assert.doesNotThrow(() => writeStoredLogHeight(throwing, 400));
  const throwingGetter = () => { throw new Error('SecurityError: window.localStorage getter denied'); };
  assert.equal(readStoredLogHeight(throwingGetter, 1000), LOG_HEIGHT.initial);
  assert.doesNotThrow(() => writeStoredLogHeight(throwingGetter, 400));
  const store = new Map();
  const memory = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.equal(readStoredLogHeight(() => memory, 1000), LOG_HEIGHT.initial);
  memory.setItem('voice-studio.diagnostics-log-height', 'abc');
  assert.equal(readStoredLogHeight(() => memory, 1000), LOG_HEIGHT.initial);
  writeStoredLogHeight(() => memory, 5000);
  assert.equal(readStoredLogHeight(() => memory, 1000), 850); // re-clamped to this viewport
  assert.equal(readStoredLogHeight(undefined, 1000), LOG_HEIGHT.initial);
});

