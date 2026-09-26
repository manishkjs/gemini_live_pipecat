/**
 * Client-side media pre-processing for Gemini 3.8 Live Custom Avatars (`customized_avatar`)
 * and Custom Voice Cloning (`replicated_voice_config`).
 *
 * - Avatar portraits are normalized to 704×1280 (9:16 portrait) lossless RGB PNG (`<5 MB`)
 *   with upper-center head-and-shoulders framing, from either file upload or webcam capture.
 * - Voice samples are normalized to 24,000 Hz, 16-bit signed integer (`s16le`), mono WAV
 *   (`RIFF...WAVE`, clamped to 10–20s / <=20s), from either live browser microphone recording
 *   or uploaded audio files (`.wav`, `.mp3`, `.m4a`, `.webm`).
 */

export const VOICE_CLONE_READING_SCRIPT =
  "When the sunlight strikes raindrops in the air, they act like a prism and form a rainbow. " +
  "A rainbow is a division of white light into many beautiful colors. " +
  "These take the shape of a long round arch, with its path high above, and its two ends apparently beyond the horizon.";

const AVATAR_TARGET_W = 704;
const AVATAR_TARGET_H = 1280;

/**
 * Draw an image or video source into a 704x1280 (9:16) RGB PNG canvas with
 * upper-center (0.22) bust framing. Optionally mirror horizontally (for front-facing webcam).
 */
function renderSourceToAvatarPng(
  source: CanvasImageSource,
  origW: number,
  origH: number,
  mirrorHorizontal = false,
): { dataUrl: string; origDims: string } {
  const canvas = document.createElement("canvas");
  canvas.width = AVATAR_TARGET_W;
  canvas.height = AVATAR_TARGET_H;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("Canvas 2D context unavailable");
  }

  // Fill RGB dark slate backdrop in case source has transparent pixels
  ctx.fillStyle = "#121826";
  ctx.fillRect(0, 0, AVATAR_TARGET_W, AVATAR_TARGET_H);

  const scale = Math.max(AVATAR_TARGET_W / origW, AVATAR_TARGET_H / origH);
  const scaledW = origW * scale;
  const scaledH = origH * scale;
  const offsetX = (AVATAR_TARGET_W - scaledW) * 0.5;
  const offsetY = (AVATAR_TARGET_H - scaledH) * 0.22;

  ctx.save();
  if (mirrorHorizontal) {
    ctx.translate(AVATAR_TARGET_W, 0);
    ctx.scale(-1, 1);
  }
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(source, offsetX, offsetY, scaledW, scaledH);
  ctx.restore();

  return {
    dataUrl: canvas.toDataURL("image/png"),
    origDims: `${origW}×${origH}`,
  };
}

/**
 * Normalize any uploaded user photo into Vertex AI's required 704×1280 (9:16) RGB PNG.
 */
export async function normalizeAvatarPortraitFile(
  file: File,
): Promise<{ dataUrl: string; origDims: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Failed to read image file"));
    reader.onload = () => {
      const srcUrl = typeof reader.result === "string" ? reader.result : "";
      if (!srcUrl) {
        reject(new Error("Empty image data"));
        return;
      }
      const img = new Image();
      img.onload = () => {
        const origW = img.naturalWidth || img.width || AVATAR_TARGET_W;
        const origH = img.naturalHeight || img.height || AVATAR_TARGET_H;
        try {
          resolve(renderSourceToAvatarPng(img, origW, origH, false));
        } catch {
          resolve({ dataUrl: srcUrl, origDims: `${origW}×${origH}` });
        }
      };
      img.onerror = () => resolve({ dataUrl: srcUrl, origDims: "raw" });
      img.src = srcUrl;
    };
    reader.readAsDataURL(file);
  });
}

/**
 * Capture the current frame from a live webcam `<video>` element into a normalized
 * 704×1280 (9:16) RGB PNG data URL.
 */
export function captureVideoFrameToAvatarPng(
  videoEl: HTMLVideoElement,
  mirrorHorizontal = true,
): { dataUrl: string; origDims: string } {
  const origW = videoEl.videoWidth || 1280;
  const origH = videoEl.videoHeight || 720;
  return renderSourceToAvatarPng(videoEl, origW, origH, mirrorHorizontal);
}

function uint8ToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const sub = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...sub);
  }
  return btoa(binary);
}

/**
 * Resample Float32 mono audio to 24,000 Hz, clamp to <= 20s, peak-normalize gently
 * if quiet, and encode a standard 44-byte RIFF WAVE header + 16-bit signed PCM (`s16le`)
 * as a `data:audio/wav;base64,...` URL.
 */
export function encodeFloat32ToWav24kMonoDataUrl(
  samples: Float32Array,
  sourceSampleRate: number,
): { dataUrl: string; durationSec: number; byteLength: number } {
  const targetSr = 24000;
  if (!samples || samples.length === 0 || sourceSampleRate <= 0) {
    throw new Error("No audio samples captured.");
  }

  let resampled: Float32Array;
  if (sourceSampleRate === targetSr) {
    resampled = samples.slice();
  } else {
    const newLen = Math.max(1, Math.round((samples.length * targetSr) / sourceSampleRate));
    resampled = new Float32Array(newLen);
    const ratio = (samples.length - 1) / Math.max(1, newLen - 1);
    for (let i = 0; i < newLen; i++) {
      const pos = i * ratio;
      const idx = Math.floor(pos);
      const frac = pos - idx;
      const s0 = samples[idx] ?? 0;
      const s1 = samples[Math.min(samples.length - 1, idx + 1)] ?? s0;
      resampled[i] = s0 + (s1 - s0) * frac;
    }
  }

  const minSamples = targetSr * 2; // Minimum 2s
  if (resampled.length < minSamples) {
    throw new Error("Voice recording is too short. Please record at least 2–15 seconds of clear speech.");
  }

  const maxSamples = targetSr * 20; // Clamp to 20s max
  if (resampled.length > maxSamples) {
    resampled = resampled.subarray(0, maxSamples);
  }

  // Gentle peak normalization if speech is quiet
  let peak = 0;
  for (let i = 0; i < resampled.length; i++) {
    const abs = Math.abs(resampled[i]);
    if (abs > peak) peak = abs;
  }
  const gain = peak > 0.01 && peak < 0.35 ? 0.85 / peak : 1.0;

  const numSamples = resampled.length;
  const dataBytes = numSamples * 2;
  const buffer = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buffer);

  const writeAscii = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  };

  // RIFF WAVE header (24 kHz, 16-bit mono PCM)
  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(8, "WAVE");
  writeAscii(12, "fmt ");
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // AudioFormat = 1 (PCM)
  view.setUint16(22, 1, true); // NumChannels = 1 (mono)
  view.setUint32(24, targetSr, true); // SampleRate = 24000
  view.setUint32(28, targetSr * 2, true); // ByteRate = 48000
  view.setUint16(32, 2, true); // BlockAlign = 2
  view.setUint16(34, 16, true); // BitsPerSample = 16
  writeAscii(36, "data");
  view.setUint32(40, dataBytes, true);

  let offset = 44;
  for (let i = 0; i < numSamples; i++) {
    const clamped = Math.max(-1, Math.min(1, resampled[i] * gain));
    const int16 = clamped < 0 ? Math.round(clamped * 32768) : Math.round(clamped * 32767);
    view.setInt16(offset, int16, true);
    offset += 2;
  }

  const wavBytes = new Uint8Array(buffer);
  const b64 = uint8ToBase64(wavBytes);
  return {
    dataUrl: `data:audio/wav;base64,${b64}`,
    durationSec: Math.round((numSamples / targetSr) * 10) / 10,
    byteLength: wavBytes.byteLength,
  };
}

/**
 * Decode any uploaded audio file (.wav, .mp3, .m4a, .webm, .ogg) in the browser
 * and normalize it into a 24 kHz 16-bit mono `.wav` data URL for `replicated_voice_config`.
 */
export async function normalizeUploadedVoiceAudioFile(
  file: File,
): Promise<{ dataUrl: string; durationSec: number; byteLength: number }> {
  const arrayBuf = await file.arrayBuffer();
  const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new AudioCtx({ sampleRate: 24000 });
  try {
    const audioBuf = await ctx.decodeAudioData(arrayBuf.slice(0));
    const chCount = audioBuf.numberOfChannels;
    const len = audioBuf.length;
    const mono = new Float32Array(len);
    for (let ch = 0; ch < chCount; ch++) {
      const chData = audioBuf.getChannelData(ch);
      for (let i = 0; i < len; i++) {
        mono[i] += chData[i] / chCount;
      }
    }
    return encodeFloat32ToWav24kMonoDataUrl(mono, audioBuf.sampleRate);
  } finally {
    void ctx.close().catch(() => {});
  }
}
