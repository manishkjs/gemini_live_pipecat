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
