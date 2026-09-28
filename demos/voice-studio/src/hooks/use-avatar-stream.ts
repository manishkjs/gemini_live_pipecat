import { useCallback, useEffect, useRef, useState } from "react";

const PREFERRED_MIME_CODECS = [
  'video/mp4; codecs="avc1.42c020, mp4a.40.2"',
  'video/mp4; codecs="avc1.42E01E, mp4a.40.2"',
  "video/mp4",
];

function resolveSupportedMimeCodec(): string {
  if (typeof window === "undefined" || typeof MediaSource === "undefined") {
    return PREFERRED_MIME_CODECS[0];
  }
  for (const codec of PREFERRED_MIME_CODECS) {
    try {
      if (MediaSource.isTypeSupported(codec)) {
        return codec;
      }
    } catch {
      // Ignore and try next
    }
  }
  return PREFERRED_MIME_CODECS[0];
}

function decodeBase64ToUint8Array(b64: string): Uint8Array {
  try {
    const binaryString = window.atob(b64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes;
  } catch {
    return new Uint8Array(0);
  }
}

const SEGMENT_DURATION_SEC = 1 / 24;
// Vertex AI Gemini 3.8 Live Avatar continues generating ~1.5-1.75s of unconditioned
// mouth/lip movements after Track 2 AAC switches to digital silence filler frames,
// before settling back into its calm closed-mouth idle loop.
const POST_SPEECH_PHANTOM_TAIL_SEC = 1.75;

export const MAX_QUEUED_BYTES = 8 * 1024 * 1024;
export const MAX_QUEUE_AGE_MS = 10_000;
export const MAX_SEGMENT_RETRIES = 3;

export type AvatarStreamController = {
  videoRef: (el: HTMLVideoElement | null) => void;
  hasVideoFrame: boolean;
  frameCount: number;
  avatarFailed: boolean;
  failureReason: string | null;
  queuedBytes: number;
  pushChunk: (
    chunkB64: string,
    isInit: boolean,
    seq: number,
    hasAudio?: boolean,
    tfdt?: number,
  ) => void;
  flushOnInterrupt: () => void;
  reset: () => void;
};

type QueuedSegment = {
  bytes: Uint8Array;
  isInit: boolean;
  hasAudio?: boolean;
  tfdt?: number;
  enqueuedAt: number;
  retries: number;
};

function nowTimestamp(): number {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}

export function useAvatarStream(
  speakerMuted: boolean = false,
  onSpeechEnded?: () => void,
  onFatalError?: (reason: string) => void,
): AvatarStreamController {
  const videoElRef = useRef<HTMLVideoElement | null>(null);
  const mediaSourceRef = useRef<MediaSource | null>(null);
  const sourceBufferRef = useRef<SourceBuffer | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const appendQueueRef = useRef<QueuedSegment[]>([]);
  const queuedBytesRef = useRef<number>(0);
  const queueAgeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failedRef = useRef<boolean>(false);
  const initSegmentRef = useRef<Uint8Array | null>(null);
  const hasAppendedInitRef = useRef<boolean>(false);
  const isOpeningRef = useRef<boolean>(false);
  const lastRemovedStartRef = useRef<number>(-1);

  const onSpeechEndedRef = useRef<(() => void) | undefined>(onSpeechEnded);
  onSpeechEndedRef.current = onSpeechEnded;

  const onFatalErrorRef = useRef<((reason: string) => void) | undefined>(onFatalError);
  onFatalErrorRef.current = onFatalError;

  const lastAppendedHasAudioRef = useRef<boolean>(false);
  const silentTailCountRef = useRef<number>(0);
  const speechEndTfdtRef = useRef<number | null>(null);
  const speechEndedNotifiedRef = useRef<boolean>(false);
  const holdingPostSpeechRef = useRef<boolean>(false);
  const resumeSpeechTfdtRef = useRef<number | null>(null);
  const pendingInterruptFlushRef = useRef<boolean>(false);

  const [hasVideoFrame, setHasVideoFrame] = useState(false);
  const [frameCount, setFrameCount] = useState(0);
  const [avatarFailed, setAvatarFailed] = useState(false);
  const [failureReason, setFailureReason] = useState<string | null>(null);
  const [queuedBytes, setQueuedBytes] = useState(0);

  const clearQueueAgeTimer = useCallback(() => {
    if (queueAgeTimerRef.current !== null) {
      clearTimeout(queueAgeTimerRef.current);
      queueAgeTimerRef.current = null;
    }
  }, []);

  const resetSpeechTracking = useCallback(() => {
    lastAppendedHasAudioRef.current = false;
    silentTailCountRef.current = 0;
    speechEndTfdtRef.current = null;
    speechEndedNotifiedRef.current = false;
    holdingPostSpeechRef.current = false;
    resumeSpeechTfdtRef.current = null;
    pendingInterruptFlushRef.current = false;
  }, []);

  const syncPlayhead = useCallback(() => {
    if (failedRef.current) return;
    const v = videoElRef.current;
    if (!v || v.buffered.length === 0) return;

    const firstStart = v.buffered.start(0);
    const end = v.buffered.end(v.buffered.length - 1);

    if (v.currentTime < firstStart) {
      v.currentTime = firstStart;
    } else if (v.buffered.length > 1) {
      // Bridge any tiny timestamp discontinuity between buffered ranges
      for (let i = 0; i < v.buffered.length - 1; i++) {
        const gapStart = v.buffered.end(i);
        const gapEnd = v.buffered.start(i + 1);
        if (v.currentTime >= gapStart - 0.05 && v.currentTime < gapEnd) {
          v.currentTime = gapEnd + 0.01;
          break;
        }
      }
    }

    // 1. Complete any pending interrupt seek as queued segments finish draining
    if (pendingInterruptFlushRef.current) {
      if (end - v.currentTime > 0.06) {
        try {
          v.currentTime = Math.max(v.currentTime, end - 0.04);
        } catch {
          // Ignore seek errors
        }
      }
      if (appendQueueRef.current.length === 0 && !sourceBufferRef.current?.updating) {
        pendingInterruptFlushRef.current = false;
      }
    }

    // 2. If a new spoken turn started while holding/skipping a previous turn's phantom tail,
    // jump directly over the silent gap to the start of the new speech.
    if (resumeSpeechTfdtRef.current !== null) {
      const target = resumeSpeechTfdtRef.current;
      if (end >= target) {
        if (target > v.currentTime + 0.08) {
          try {
            v.currentTime = Math.max(firstStart, target - 0.02);
          } catch {
            // Ignore seek errors
          }
        }
        resumeSpeechTfdtRef.current = null;
        holdingPostSpeechRef.current = false;
        if (v.paused) {
          v.play().catch(() => {});
        }
      }
    }

    // 3. Post-speech phantom lip-flap suppression:
    // At speechEndTfdt, all spoken audio has finished and the avatar's mouth is naturally closed.
    // Hold on that clean closed-mouth frame instead of playing the ~1.75s unconditioned phantom
    // lip-flap frames, then jump straight to the calm post-tail idle stream once buffered.
    const speechEnd = speechEndTfdtRef.current;
    const speechFinishedOnWire = speechEnd !== null && !lastAppendedHasAudioRef.current;

    if (speechFinishedOnWire && v.currentTime >= speechEnd - 0.04) {
      if (!speechEndedNotifiedRef.current) {
        speechEndedNotifiedRef.current = true;
        onSpeechEndedRef.current?.();
      }
      const calmIdleEdge = speechEnd + POST_SPEECH_PHANTOM_TAIL_SEC;
      if (end >= calmIdleEdge) {
        try {
          v.currentTime = Math.max(calmIdleEdge - 0.05, end - 0.08);
        } catch {
          // Ignore seek errors
        }
        holdingPostSpeechRef.current = false;
        speechEndTfdtRef.current = null;
        if (v.paused) {
          v.play().catch(() => {});
        }
      } else {
        holdingPostSpeechRef.current = true;
        if (!v.paused) {
          v.pause?.();
        }
        return;
      }
    }

    // 4. Catch-up logic:
    // - During active speech, only jump playhead if tab lagged >2.5s behind live edge (never clip speech).
    // - During idle silence, pin playhead within 350ms of live edge so buffer lag never accumulates.
    const inActiveSpeech =
      lastAppendedHasAudioRef.current ||
      (speechEnd !== null && v.currentTime < speechEnd - 0.04);

    const maxAllowedLag = inActiveSpeech ? 2.5 : 0.35;
    const targetLead = inActiveSpeech ? 0.15 : 0.08;
    if (end - v.currentTime > maxAllowedLag) {
      try {
        v.currentTime = Math.max(0, end - targetLead);
      } catch {
        // Ignore seek errors
      }
    }

    if (!holdingPostSpeechRef.current && v.paused) {
      v.play().catch(() => {});
    }
  }, []);

  const releasePlaybackResources = useCallback(() => {
    clearQueueAgeTimer();
    appendQueueRef.current = [];
    queuedBytesRef.current = 0;
    setQueuedBytes(0);
    initSegmentRef.current = null;
    hasAppendedInitRef.current = false;
    isOpeningRef.current = false;
    lastRemovedStartRef.current = -1;
    resetSpeechTracking();
    setHasVideoFrame(false);
    sourceBufferRef.current = null;
    if (mediaSourceRef.current) {
      try {
        if (mediaSourceRef.current.readyState === "open") {
          mediaSourceRef.current.endOfStream();
        }
      } catch {
        // Ignore
      }
      mediaSourceRef.current = null;
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    if (videoElRef.current) {
      videoElRef.current.pause?.();
      videoElRef.current.removeEventListener?.("timeupdate", syncPlayhead);
      videoElRef.current.removeAttribute("src");
      videoElRef.current.load();
    }
  }, [clearQueueAgeTimer, resetSpeechTracking, syncPlayhead]);

  const failStream = useCallback(
    (reason: string) => {
      if (failedRef.current) return;
      failedRef.current = true;
      setAvatarFailed(true);
      setFailureReason(reason);
      releasePlaybackResources();
      onFatalErrorRef.current?.(reason);
    },
    [releasePlaybackResources],
  );

  const syncQueueAgeWatchdog = useCallback(() => {
    clearQueueAgeTimer();
    if (failedRef.current || appendQueueRef.current.length === 0 || typeof setTimeout === "undefined") {
      return;
    }
    const oldestAge = Math.max(0, nowTimestamp() - appendQueueRef.current[0].enqueuedAt);
    const remainingMs = Math.max(0, MAX_QUEUE_AGE_MS - oldestAge + 1);
    queueAgeTimerRef.current = setTimeout(() => {
      queueAgeTimerRef.current = null;
      if (failedRef.current || appendQueueRef.current.length === 0) return;
      if (nowTimestamp() - appendQueueRef.current[0].enqueuedAt > MAX_QUEUE_AGE_MS) {
        failStream("Avatar video playback stalled for over 10 seconds. Please restart the call.");
      } else {
        syncQueueAgeWatchdog();
      }
    }, remainingMs);
  }, [clearQueueAgeTimer, failStream]);

  const videoRef = useCallback(
    (el: HTMLVideoElement | null) => {
      const prev = videoElRef.current;
      if (prev && prev !== el) {
        prev.removeEventListener?.("timeupdate", syncPlayhead);
      }
      videoElRef.current = el;
      if (el && !failedRef.current) {
        el.muted = speakerMuted;
        el.addEventListener?.("timeupdate", syncPlayhead);
        if (objectUrlRef.current && el.src !== objectUrlRef.current) {
          el.src = objectUrlRef.current;
          el.play().catch(() => {});
        }
      }
    },
    [speakerMuted, syncPlayhead],
  );

  useEffect(() => {
    if (videoElRef.current) {
      videoElRef.current.muted = speakerMuted;
    }
  }, [speakerMuted]);

  useEffect(() => {
    if (!hasVideoFrame || typeof setInterval === "undefined") return;
    const timer = setInterval(syncPlayhead, 33);
    return () => clearInterval(timer);
  }, [hasVideoFrame, syncPlayhead]);

  const drainQueue = useCallback(() => {
    if (failedRef.current) return;
    const sb = sourceBufferRef.current;
    const ms = mediaSourceRef.current;
    if (!sb || !ms || ms.readyState !== "open" || sb.updating) return;

    // 1. Trim old buffered history (>15s behind playhead) to keep memory footprint tiny
    const videoEl = videoElRef.current;
    if (hasAppendedInitRef.current && videoEl && sb.buffered.length > 0) {
      const start = sb.buffered.start(0);
      const current = videoEl.currentTime;
      if (current - start > 15 && Math.abs(start - lastRemovedStartRef.current) > 0.5) {
        try {
          lastRemovedStartRef.current = start;
          sb.remove(start, current - 6);
          return;
        } catch {
          // Proceed to append if remove fails
        }
      }
    }

    if (appendQueueRef.current.length === 0) {
      clearQueueAgeTimer();
      return;
    }

    const now = nowTimestamp();
    if (now - appendQueueRef.current[0].enqueuedAt > MAX_QUEUE_AGE_MS) {
      failStream("Avatar video playback stalled for over 10 seconds. Please restart the call.");
      return;
    }

    const next = appendQueueRef.current.shift()!;
    queuedBytesRef.current = Math.max(0, queuedBytesRef.current - next.bytes.byteLength);
    setQueuedBytes(queuedBytesRef.current);

    if (!hasAppendedInitRef.current && !next.isInit) {
      appendQueueRef.current.unshift(next);
      queuedBytesRef.current += next.bytes.byteLength;
      setQueuedBytes(queuedBytesRef.current);
      syncQueueAgeWatchdog();
      if (initSegmentRef.current) {
        try {
          hasAppendedInitRef.current = true;
          sb.appendBuffer(initSegmentRef.current as unknown as BufferSource);
        } catch {
          hasAppendedInitRef.current = false;
          failStream("Avatar initialization segment failed to append. Please restart the call.");
        }
      }
      return;
    }

    try {
      if (next.isInit) {
        hasAppendedInitRef.current = true;
        resetSpeechTracking();
      } else if (typeof next.hasAudio === "boolean") {
        const segTfdt = typeof next.tfdt === "number" ? next.tfdt : null;
        if (next.hasAudio) {
          if (!lastAppendedHasAudioRef.current) {
            if (
              holdingPostSpeechRef.current ||
              (speechEndTfdtRef.current !== null &&
                segTfdt !== null &&
                segTfdt - speechEndTfdtRef.current >= 0.35)
            ) {
              resumeSpeechTfdtRef.current = segTfdt;
            }
            holdingPostSpeechRef.current = false;
            speechEndedNotifiedRef.current = false;
          }
          lastAppendedHasAudioRef.current = true;
          silentTailCountRef.current = 0;
          if (segTfdt !== null) {
            speechEndTfdtRef.current = segTfdt + SEGMENT_DURATION_SEC;
          }
        } else if (lastAppendedHasAudioRef.current) {
          silentTailCountRef.current += 1;
          if (silentTailCountRef.current >= 2) {
            lastAppendedHasAudioRef.current = false;
            if (segTfdt !== null && speechEndTfdtRef.current === null) {
              speechEndTfdtRef.current = segTfdt;
            }
          }
        }
      } else {
        // Legacy/unannotated segments without hasAudio metadata: treat as active media
        lastAppendedHasAudioRef.current = true;
      }
      sb.appendBuffer(next.bytes as unknown as BufferSource);
      syncQueueAgeWatchdog();
    } catch {
      next.retries += 1;
      if (next.retries > MAX_SEGMENT_RETRIES) {
        failStream("Avatar video buffer failed repeatedly and could not recover. Please restart the call.");
        return;
      }
      // Transient QuotaExceededError: put segment back at head within retry cap and evict old buffer
      appendQueueRef.current.unshift(next);
      queuedBytesRef.current += next.bytes.byteLength;
      setQueuedBytes(queuedBytesRef.current);
      syncQueueAgeWatchdog();
      if (sb.buffered.length > 0) {
        try {
          const s = sb.buffered.start(0);
          sb.remove(s, s + 4);
        } catch {
          // Ignore
        }
      }
    }
  }, [clearQueueAgeTimer, failStream, resetSpeechTracking, syncQueueAgeWatchdog]);

  const ensureMediaSource = useCallback(() => {
    if (failedRef.current) return;
    if (typeof window === "undefined" || typeof MediaSource === "undefined") return;
    if (
      mediaSourceRef.current &&
      (mediaSourceRef.current.readyState === "open" || isOpeningRef.current)
    ) {
      return;
    }

    const ms = new MediaSource();
    mediaSourceRef.current = ms;
    sourceBufferRef.current = null;
    hasAppendedInitRef.current = false;
    isOpeningRef.current = true;

    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
    }
    const url = URL.createObjectURL(ms);
    objectUrlRef.current = url;

    if (videoElRef.current) {
      videoElRef.current.src = url;
      videoElRef.current.currentTime = 0;
      videoElRef.current.muted = speakerMuted;
    }

    ms.addEventListener("sourceopen", () => {
      if (mediaSourceRef.current !== ms || failedRef.current) return;
      isOpeningRef.current = false;
      try {
        const mime = resolveSupportedMimeCodec();
        const sb = ms.addSourceBuffer(mime);
        // Use "segments" mode so ISO-BMFF tfdt decode timestamps keep video (H.264) and audio (AAC) lip-synced
        sb.mode = "segments";
        sourceBufferRef.current = sb;
        sb.addEventListener("updateend", () => {
          if (failedRef.current || sourceBufferRef.current !== sb) return;
          syncPlayhead();
          if (videoElRef.current && videoElRef.current.buffered.length > 0) {
            setHasVideoFrame(true);
          }
          drainQueue();
        });
        drainQueue();
      } catch (err) {
        console.error("[AvatarMSE] Failed to create SourceBuffer:", err);
        failStream("Your browser could not initialize the Live Avatar video decoder. Please restart the call.");
      }
    });
  }, [drainQueue, failStream, speakerMuted, syncPlayhead]);

  const pushChunk = useCallback(
    (chunkB64: string, isInit: boolean, _seq: number, hasAudio?: boolean, tfdt?: number) => {
      if (failedRef.current || !chunkB64) return;
      const bytes = decodeBase64ToUint8Array(chunkB64);
      const now = nowTimestamp();

      if (isInit && hasAppendedInitRef.current) {
        // A new fMP4 stream started mid-call (e.g. after session resumption reconnect) with tfdt=0:
        // recreate MediaSource so tfdt=0 plays immediately instead of landing behind currentTime.
        clearQueueAgeTimer();
        appendQueueRef.current = [];
        queuedBytesRef.current = 0;
        setQueuedBytes(0);
        sourceBufferRef.current = null;
        mediaSourceRef.current = null;
        hasAppendedInitRef.current = false;
        isOpeningRef.current = false;
        lastRemovedStartRef.current = -1;
        resetSpeechTracking();
      }

      if (
        appendQueueRef.current.length > 0 &&
        now - appendQueueRef.current[0].enqueuedAt > MAX_QUEUE_AGE_MS
      ) {
        failStream("Avatar video playback stalled for over 10 seconds. Please restart the call.");
        return;
      }

      if (queuedBytesRef.current + bytes.byteLength > MAX_QUEUED_BYTES) {
        failStream("Avatar video buffer exceeded the 8 MB safety limit. Please restart the call.");
        return;
      }

      if (isInit) {
        initSegmentRef.current = bytes;
      }

      ensureMediaSource();
      if (failedRef.current) return;

      appendQueueRef.current.push({
        bytes,
        isInit,
        hasAudio,
        tfdt,
        enqueuedAt: now,
        retries: 0,
      });
      queuedBytesRef.current += bytes.byteLength;
      setQueuedBytes(queuedBytesRef.current);
      setFrameCount((c) => c + 1);
      syncQueueAgeWatchdog();
      drainQueue();
    },
    [clearQueueAgeTimer, ensureMediaSource, drainQueue, failStream, resetSpeechTracking, syncQueueAgeWatchdog],
  );

  const flushOnInterrupt = useCallback(() => {
    if (failedRef.current) return;
    // Never delete queued ISO-BMFF segments from appendQueueRef: Vertex AI streams a continuous
    // tfdt-indexed fMP4 timeline, and dropping segments creates unbuffered timeline gaps or
    // truncated boxes that stall MSE playback on subsequent turns.
    lastAppendedHasAudioRef.current = false;
    silentTailCountRef.current = 0;
    speechEndTfdtRef.current = null;
    speechEndedNotifiedRef.current = false;
    holdingPostSpeechRef.current = false;
    resumeSpeechTfdtRef.current = null;
    pendingInterruptFlushRef.current = true;

    const v = videoElRef.current;
    if (v && v.buffered.length > 0) {
      try {
        const end = v.buffered.end(v.buffered.length - 1);
        if (end - v.currentTime > 0.06) {
          v.currentTime = Math.max(v.currentTime, end - 0.04);
        }
        if (v.paused) {
          v.play().catch(() => {});
        }
      } catch {
        // Ignore seek errors
      }
    }
  }, []);

  const reset = useCallback(() => {
    failedRef.current = false;
    setAvatarFailed(false);
    setFailureReason(null);
    setFrameCount(0);
    releasePlaybackResources();
  }, [releasePlaybackResources]);

  useEffect(() => {
    return () => {
      clearQueueAgeTimer();
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
      }
    };
  }, [clearQueueAgeTimer]);

  return {
    videoRef,
    hasVideoFrame,
    frameCount,
    avatarFailed,
    failureReason,
    queuedBytes,
    pushChunk,
    flushOnInterrupt,
    reset,
  };
}

