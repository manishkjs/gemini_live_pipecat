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
    if (videoEl && sb.buffered.length > 0) {
      const start = sb.buffered.start(0);
      const current = videoEl.currentTime;
      if (current - start > 15) {
        try {
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
      // If SourceBuffer throws QuotaExceededError, evict oldest 4s and retry
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
    if (mediaSourceRef.current && mediaSourceRef.current.readyState !== "closed") {
      return;
    }

    const ms = new MediaSource();
    mediaSourceRef.current = ms;
    hasAppendedInitRef.current = false;

    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
    }
    const url = URL.createObjectURL(ms);
    objectUrlRef.current = url;

    if (videoElRef.current) {
      videoElRef.current.src = url;
      videoElRef.current.muted = speakerMuted;
    }

    ms.addEventListener("sourceopen", () => {
      if (mediaSourceRef.current !== ms) return;
      try {
        const mime = resolveSupportedMimeCodec();
        const sb = ms.addSourceBuffer(mime);
        // Use "segments" mode so ISO-BMFF tfdt decode timestamps keep video (H.264) and audio (AAC) lip-synced
        sb.mode = "segments";
        sourceBufferRef.current = sb;
        sb.addEventListener("updateend", () => {
          const v = videoElRef.current;
          if (v && v.buffered.length > 0) {
            const end = v.buffered.end(v.buffered.length - 1);
            // Keep playhead synced to live edge if it falls behind
            if (end - v.currentTime > 1.35) {
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
      }
      ensureMediaSource();
      appendQueueRef.current.push({ bytes, isInit });
      setFrameCount((c) => c + 1);
      drainQueue();
    },
    [ensureMediaSource, drainQueue],
  );

  const flushOnInterrupt = useCallback(() => {
    appendQueueRef.current = appendQueueRef.current.filter((item) => item.isInit);
    const v = videoElRef.current;
    if (v && v.buffered.length > 0) {
      try {
        const end = v.buffered.end(v.buffered.length - 1);
        if (end > v.currentTime) {
          v.currentTime = Math.max(0, end - 0.05);
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
