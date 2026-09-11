"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Layers, X, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface CompressionEventData {
  id: string;
  tokens?: number;
  threshold?: number;
  message?: string;
}

interface ContextCompressionToastProps {
  event: CompressionEventData | null;
  onDismiss: () => void;
}

export default function ContextCompressionToast({ event, onDismiss }: ContextCompressionToastProps) {
  const [progress, setProgress] = useState(100);

  useEffect(() => {
    if (!event) {
      setProgress(100);
      return;
    }
    setProgress(100);
    const start = performance.now();
    const duration = 4500;

    const frame = () => {
      const elapsed = performance.now() - start;
      const remaining = Math.max(0, 100 - (elapsed / duration) * 100);
      setProgress(remaining);
      if (remaining > 0) {
        requestAnimationFrame(frame);
      }
    };
    const req = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(req);
  }, [event?.id]);

  return (
    <AnimatePresence>
      {event && (
        <motion.div
          key={event.id}
          className="compression-toast-container"
          initial={{ opacity: 0, y: -28, scale: 0.92 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -20, scale: 0.94, transition: { duration: 0.45, ease: "easeInOut" } }}
          transition={{ type: "spring", stiffness: 380, damping: 26 }}
          role="status"
          aria-live="polite"
        >
          <div className="compression-toast-card">
            <div className="compression-toast-glow" />
            <div className="compression-toast-header">
              <div className="toast-badge-group">
                <span className="toast-pulse-icon">
                  <Layers size={15} />
                </span>
                <span className="toast-badge-title">CONTEXT COMPRESSION ACTIVE</span>
              </div>
              <div className="toast-actions">
                {event.tokens !== undefined && event.tokens > 0 && (
                  <span className="toast-tokens-pill">
                    {event.tokens.toLocaleString()} tok
                  </span>
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  className="toast-close-btn"
                  onClick={onDismiss}
                  aria-label="Dismiss notification"
                >
                  <X size={14} />
                </Button>
              </div>
            </div>

            <div className="compression-toast-body">
              <div className="toast-title-row">
                <Sparkles size={14} className="toast-sparkle" />
                <h4>Context Window Compressed</h4>
              </div>
              <p className="toast-desc">
                {event.message ||
                  "Sliding window applied. Earlier conversation history compacted to preserve low latency & token cache."}
              </p>
            </div>

            {/* Fading progress indicator bar */}
            <div className="toast-progress-track">
              <div
                className="toast-progress-bar"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
