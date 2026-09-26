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

export type AvatarStreamController = {
  videoRef: (el: HTMLVideoElement | null) => void;
  hasVideoFrame: boolean;
  frameCount: number;
  pushChunk: (chunkB64: string, isInit: boolean, seq: number) => void;
  flushOnInterrupt: () => void;
  reset: () => void;
};

export function useAvatarStream(speakerMuted: boolean = false): AvatarStreamController {
  const videoElRef = useRef<HTMLVideoElement | null>(null);
  const mediaSourceRef = useRef<MediaSource | null>(null);
  const sourceBufferRef = useRef<SourceBuffer | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const appendQueueRef = useRef<{ bytes: Uint8Array; isInit: boolean }[]>([]);
  const initSegmentRef = useRef<Uint8Array | null>(null);
  const hasAppendedInitRef = useRef<boolean>(false);
  const isOpeningRef = useRef<boolean>(false);
  const lastRemovedStartRef = useRef<number>(-1);
  const [hasVideoFrame, setHasVideoFrame] = useState(false);
  const [frameCount, setFrameCount] = useState(0);

  const videoRef = useCallback(
    (el: HTMLVideoElement | null) => {
      videoElRef.current = el;
      if (el) {
        el.muted = speakerMuted;
        if (objectUrlRef.current && el.src !== objectUrlRef.current) {
          el.src = objectUrlRef.current;
          el.play().catch(() => {});
        }
      }
    },
    [speakerMuted],
  );

  useEffect(() => {
    if (videoElRef.current) {
      videoElRef.current.muted = speakerMuted;
    }
  }, [speakerMuted]);

  const drainQueue = useCallback(() => {
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

    if (appendQueueRef.current.length === 0) return;

    const next = appendQueueRef.current.shift()!;
    if (!hasAppendedInitRef.current && !next.isInit) {
      appendQueueRef.current.unshift(next);
      if (initSegmentRef.current) {
        try {
          hasAppendedInitRef.current = true;
          sb.appendBuffer(initSegmentRef.current as unknown as BufferSource);
        } catch {
          hasAppendedInitRef.current = false;
        }
      }
      return;
    }

    try {
      if (next.isInit) {
        hasAppendedInitRef.current = true;
      }
      sb.appendBuffer(next.bytes as unknown as BufferSource);
    } catch {
      // Never drop the segment: put it back at the head of the queue before evicting old buffer
      appendQueueRef.current.unshift(next);
      if (sb.buffered.length > 0) {
        try {
          const s = sb.buffered.start(0);
          sb.remove(s, s + 4);
        } catch {
          // Ignore
        }
      }
    }
  }, []);

  const ensureMediaSource = useCallback(() => {
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
      if (mediaSourceRef.current !== ms) return;
      isOpeningRef.current = false;
      try {
        const mime = resolveSupportedMimeCodec();
        const sb = ms.addSourceBuffer(mime);
        // Use "segments" mode so ISO-BMFF tfdt decode timestamps keep video (H.264) and audio (AAC) lip-synced
        sb.mode = "segments";
        sourceBufferRef.current = sb;
        sb.addEventListener("updateend", () => {
          const v = videoElRef.current;
          if (v && v.buffered.length > 0) {
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
            // Only jump playhead if tab lagged >2.5s behind live edge (avoid clipping normal speech)
            if (end - v.currentTime > 2.5) {
              v.currentTime = Math.max(0, end - 0.15);
            }
            if (v.paused) {
              v.play().catch(() => {});
            }
            setHasVideoFrame(true);
          }
          drainQueue();
        });
        drainQueue();
      } catch (err) {
        console.error("[AvatarMSE] Failed to create SourceBuffer:", err);
      }
    });
  }, [drainQueue, speakerMuted]);

  const pushChunk = useCallback(
    (chunkB64: string, isInit: boolean, _seq: number) => {
      if (!chunkB64) return;
      const bytes = decodeBase64ToUint8Array(chunkB64);
      if (isInit) {
        initSegmentRef.current = bytes;
        if (hasAppendedInitRef.current) {
          // A new fMP4 stream started mid-call (e.g. after session resumption reconnect) with tfdt=0:
          // recreate MediaSource so tfdt=0 plays immediately instead of landing behind currentTime.
          appendQueueRef.current = [];
          sourceBufferRef.current = null;
          mediaSourceRef.current = null;
          hasAppendedInitRef.current = false;
          isOpeningRef.current = false;
          lastRemovedStartRef.current = -1;
        }
      }
      ensureMediaSource();
      appendQueueRef.current.push({ bytes, isInit });
      setFrameCount((c) => c + 1);
      drainQueue();
    },
    [ensureMediaSource, drainQueue],
  );

  const flushOnInterrupt = useCallback(() => {
    // Never delete queued ISO-BMFF segments from appendQueueRef: Vertex AI streams a continuous
    // tfdt-indexed fMP4 timeline, and dropping segments creates unbuffered timeline gaps or
    // truncated boxes that stall MSE playback on subsequent turns.
    const v = videoElRef.current;
    if (v && v.buffered.length > 0) {
      try {
        const end = v.buffered.end(v.buffered.length - 1);
        if (end - v.currentTime > 0.35) {
          v.currentTime = Math.max(v.currentTime, end - 0.08);
        }
      } catch {
        // Ignore seek errors
      }
    }
  }, []);

  const reset = useCallback(() => {
    appendQueueRef.current = [];
    initSegmentRef.current = null;
    hasAppendedInitRef.current = false;
    isOpeningRef.current = false;
    lastRemovedStartRef.current = -1;
    setHasVideoFrame(false);
    setFrameCount(0);
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
      videoElRef.current.removeAttribute("src");
      videoElRef.current.load();
    }
  }, []);

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
      }
    };
  }, []);

  return {
    videoRef,
    hasVideoFrame,
    frameCount,
    pushChunk,
    flushOnInterrupt,
    reset,
  };
}
