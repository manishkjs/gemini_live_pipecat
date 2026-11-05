import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { getPersonaCastRole } from "@/lib/call-console";
import { PERSONAS, type Persona } from "@/lib/personas";
import { SlidersIcon } from "./console-icons";

interface CastRailProps {
  readonly selectedPersonaId: string;
  readonly active: boolean;
  readonly onSelectPersona: (personaId: string) => void;
  readonly onLockedAttempt: () => void;
}

function CastPortrait({ persona }: { readonly persona: Persona }) {
  const [failed, setFailed] = useState(false);
  if (persona.portrait && !failed) {
    return (
      <img
        src={persona.portrait}
        alt=""
        width={56}
        height={56}
        decoding="async"
        onError={() => setFailed(true)}
      />
    );
  }
  return <SlidersIcon size={18} />;
}

/** Horizontal circular portrait rail for selecting one of the 9 Voice Studio personas. */
export default function CastRail({
  selectedPersonaId,
  active,
  onSelectPersona,
  onLockedAttempt,
}: CastRailProps) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);

  const syncOverflow = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setIsOverflowing(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  }, []);

  useEffect(() => {
    syncOverflow();
    const el = scrollerRef.current;
    const observer =
      el && typeof ResizeObserver !== "undefined" ? new ResizeObserver(syncOverflow) : null;
    if (el && observer) observer.observe(el);
    window.addEventListener("resize", syncOverflow);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", syncOverflow);
    };
  }, [syncOverflow]);

  useEffect(() => {
    const el = scrollerRef.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]');
    el?.scrollIntoView({ block: "nearest", inline: "nearest" });
    syncOverflow();
  }, [selectedPersonaId, syncOverflow]);

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    if (active) {
      onLockedAttempt();
      return;
    }
    const idx = PERSONAS.findIndex((item) => item.id === selectedPersonaId);
    if (idx < 0) return;
    let nextIdx = idx;
    if (e.key === "ArrowRight") nextIdx = (idx + 1) % PERSONAS.length;
    else if (e.key === "ArrowLeft") nextIdx = (idx - 1 + PERSONAS.length) % PERSONAS.length;
    else if (e.key === "Home") nextIdx = 0;
    else if (e.key === "End") nextIdx = PERSONAS.length - 1;
    const nextPersona = PERSONAS[nextIdx];
    if (!nextPersona) return;
    onSelectPersona(nextPersona.id);
    requestAnimationFrame(() => {
      const target = scrollerRef.current?.querySelector<HTMLButtonElement>(
        `[data-persona-id="${nextPersona.id}"]`,
      );
      target?.focus();
    });
  };

  return (
    <section className="cast-rail" aria-label="Voice personas">
      <div
        ref={scrollerRef}
        id="cast-scroller"
        className={`cast-scroller scroll-area${isOverflowing ? " is-overflowing" : ""}`}
        role="listbox"
        aria-orientation="horizontal"
        aria-label="Choose a persona"
        onScroll={syncOverflow}
        onKeyDown={handleKeyDown}
      >
        {PERSONAS.map((item) => {
          const selected = item.id === selectedPersonaId;
          const isCustom = item.id === "custom";
          const roleText = getPersonaCastRole(item);
          return (
            <button
              key={item.id}
              type="button"
              role="option"
              data-persona-id={item.id}
              aria-selected={selected}
              aria-disabled={active ? true : undefined}
              tabIndex={selected ? 0 : -1}
              className={`cast-item${isCustom ? " is-custom" : ""}`}
              onClick={() => {
                if (active) {
                  onLockedAttempt();
                  return;
                }
                onSelectPersona(item.id);
              }}
            >
              <span className="cast-portrait" aria-hidden="true">
                <CastPortrait persona={item} />
              </span>
              <span className="cast-name">{isCustom ? item.name : item.agentName}</span>
              <span className="cast-role">{roleText}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
