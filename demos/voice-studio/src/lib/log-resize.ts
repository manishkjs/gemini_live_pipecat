/**
 * Height maths for the resizable Live Diagnostics Log.
 *
 * The log can be dragged taller by the handle under it, stepped with the arrow keys, sent to
 * either end with Home/End, and expanded or restored with a double-click. It never shrinks
 * below `min`, and never grows past 85% of the viewport.
 */

export const LOG_HEIGHT = { initial: 280, min: 160, step: 40, viewportShare: 0.85 } as const;

export const LOG_HEIGHT_STORAGE_KEY = "voice-studio.diagnostics-log-height";

export function maxLogHeight(viewport: number): number {
  return Math.max(LOG_HEIGHT.min, Math.round(viewport * LOG_HEIGHT.viewportShare));
}

export function clampLogHeight(height: number, viewport: number): number {
  if (!Number.isFinite(height)) return LOG_HEIGHT.initial;
  return Math.min(maxLogHeight(viewport), Math.max(LOG_HEIGHT.min, Math.round(height)));
}

/** New height after the pointer moved from `startY` to `currentY`, starting at `startHeight`. */
export function dragLogHeight(startHeight: number, startY: number, currentY: number, viewport: number): number {
  return clampLogHeight(startHeight + (currentY - startY), viewport);
}

/** New height for a key on the handle, or null when the key does not resize. */
export function keyLogHeight(height: number, key: string, viewport: number): number | null {
  switch (key) {
    case "ArrowDown":
      return clampLogHeight(height + LOG_HEIGHT.step, viewport);
    case "ArrowUp":
      return clampLogHeight(height - LOG_HEIGHT.step, viewport);
    case "End":
      return maxLogHeight(viewport);
    case "Home":
      return LOG_HEIGHT.min;
    default:
      return null;
  }
}

/** Double-click: expand to the maximum, or restore the default when already expanded. */
export function toggleLogHeight(height: number, viewport: number): number {
  return height >= maxLogHeight(viewport) ? LOG_HEIGHT.initial : maxLogHeight(viewport);
}
