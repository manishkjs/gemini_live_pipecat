"use client";

import { useEffect } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Wrench } from "lucide-react";
import type { ToolInjectionEvent } from "@/lib/tool-injection";

const VISIBLE_MS = 4200;

const VIA_LABEL: Record<ToolInjectionEvent["via"], string> = {
  context_update: "context_update",
  setup: "session setup",
  static: "static set: this model keeps every tool",
};

/** "TravellerDetailsTool" -> "TravellerDetails": the suffix is noise in a chip. */
const short = (name: string) => name.replace(/Tool$/, "");

interface ToolInjectionToastProps {
  event: ToolInjectionEvent | null;
  onDismiss: () => void;
}

export default function ToolInjectionToast({ event, onDismiss }: ToolInjectionToastProps) {
  useEffect(() => {
    if (!event) return;
    const timer = setTimeout(onDismiss, VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [event?.id, onDismiss]);

  // Keyboard users dismiss with Escape. A status toast must not take focus, so listen on the window.
  useEffect(() => {
    if (!event) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [event?.id, onDismiss]);

  return (
    <AnimatePresence>
      {event && (
        <motion.div
          key={event.id}
          className="tool-toast"
          initial={{ opacity: 0, y: 14, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -10, transition: { duration: 0.6, ease: "easeOut" } }}
          transition={{ type: "spring", stiffness: 360, damping: 28 }}
          role="status"
          aria-live="polite"
          onClick={onDismiss}
        >
          <div className="tool-toast-head">
            <Wrench size={12} aria-hidden />
            <span className="tool-toast-card">Card {event.card}</span>
            <span className="tool-toast-title">{event.title}</span>
          </div>
          <div className="tool-toast-chips">
            {event.declared.map((name) => (
              <span key={name} className={`tool-chip${event.added.includes(name) ? " is-added" : ""}`}>
                {event.added.includes(name) ? "+" : ""}{short(name)}
              </span>
            ))}
            {event.removed.map((name) => (
              <span key={`-${name}`} className="tool-chip is-removed">−{short(name)}</span>
            ))}
          </div>
          <div className={`tool-toast-via${event.status === "pending" ? " is-pending" : ""}`}>
            {event.status === "pending"
              ? "context_update send failed: retrying, then declared on reconnect"
              : event.status === "unchanged"
                ? "same tools as the previous card"
                : `via ${VIA_LABEL[event.via]}`}
          </div>
          <div className="tool-toast-fade" style={{ animationDuration: `${VISIBLE_MS}ms` }} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
