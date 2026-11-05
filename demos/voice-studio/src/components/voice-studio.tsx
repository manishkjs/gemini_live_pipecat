import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useVoiceSession } from "@/hooks/use-voice-session";
import { getPersonaUiAccent } from "@/lib/call-console";
import {
  buildVisitsUrl,
  fallbackHeadline,
  getDefaultBackendUrl,
  newSessionId,
} from "@/lib/voice-session";
import ObservabilityDrawer from "./observability-drawer";
import CallDock from "./studio/call-dock";
import CastRail from "./studio/cast-rail";
import { BrandWaveIcon, CloseIcon, ConsoleActivityIcon, SlidersIcon } from "./studio/console-icons";
import ContextCompressionToast from "./studio/context-compression-toast";
import LiveCallStage from "./studio/live-call-stage";
import PreCallCard from "./studio/pre-call-card";
import SettingsDialog from "./studio/settings-dialog";
import ToolInjectionToast from "./studio/tool-injection-toast";
import "./voice-studio.css";

const PAGE_LOAD_VISIT_ID = newSessionId();

interface FlashNotice {
  readonly text: string;
  readonly tone: "info" | "warn";
}

function formatElapsed(sec: number): string {
  const safe = Math.max(0, Math.floor(sec));
  const mm = String(Math.floor(safe / 60)).padStart(2, "0");
  const ss = String(safe % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/** Root Voice Studio Call Console shell. */
export default function VoiceStudio({ sourceDownload = false }: { sourceDownload?: boolean }) {
  const studio = useVoiceSession();
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [visitCount, setVisitCount] = useState<number | null>(null);
  const [flash, setFlash] = useState<FlashNotice | null>(null);
  const [isMobileViewport, setIsMobileViewport] = useState<boolean>(() =>
    typeof window === "undefined" ? false : window.matchMedia("(max-width: 900px)").matches,
  );
  const mainColRef = useRef<HTMLDivElement | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const {
    active,
    phase,
    error,
    persona,
    settings,
    messages,
    elapsed,
    turnCount,
    tokenCount,
    tokenSplit,
    sessionCostUSD,
    sessionCostBounds,
    cascadeCost,
    interruptCount,
    settingsOpen,
    setSettingsOpen,
    setError,
    voiceFallbackNotice,
    setVoiceFallbackNotice,
    choosePersona,
    chooseEngine,
    endSession,
    startBackend,
    resetToSetup,
  } = studio;

  const triggerFlash = useCallback((text: string, tone: "info" | "warn" = "warn", ms = 2000) => {
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    setFlash({ text, tone });
    flashTimerRef.current = setTimeout(() => {
      setFlash(null);
      flashTimerRef.current = null;
    }, ms);
  }, []);

  useEffect(() => {
    return () => {
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    };
  }, []);

  // Sync dynamic --persona CSS custom property and body.is-live class.
  const personaAccent = getPersonaUiAccent(persona.id);
  const showLiveStage = active || messages.length > 0;
  const isPostCall = !active && messages.length > 0;

  useEffect(() => {
    document.documentElement.style.setProperty("--persona", personaAccent);
  }, [personaAccent]);

  useEffect(() => {
    document.body.classList.toggle("is-live", active);
    return () => {
      document.body.classList.remove("is-live");
    };
  }, [active]);

  // Track responsive <=900px breakpoint for Session console sheet behavior.
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 900px)");
    const sync = () => setIsMobileViewport(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  // Manage background inert state & Escape / Tab focus trap for modal layers.
  const mobileConsoleModal = consoleOpen && isMobileViewport && !settingsOpen;
  useEffect(() => {
    const mainEl = mainColRef.current;
    if (mainEl) {
      (mainEl as HTMLDivElement & { inert?: boolean }).inert = settingsOpen || mobileConsoleModal;
    }
  }, [settingsOpen, mobileConsoleModal]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (settingsOpen) {
          setSettingsOpen(false);
          requestAnimationFrame(() => document.getElementById("btn-settings")?.focus());
          return;
        }
        if (consoleOpen) {
          setConsoleOpen(false);
          requestAnimationFrame(() => document.getElementById("btn-console")?.focus());
        }
        return;
      }

      if (e.key === "Tab") {
        const modalRoot = settingsOpen
          ? document.getElementById("settings-dialog")
          : mobileConsoleModal
            ? document.getElementById("console-rail")
            : null;
        if (!modalRoot) return;
        const focusables = Array.from(
          modalRoot.querySelectorAll<HTMLElement>(
            'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, a[href], [tabindex="0"]',
          ),
        ).filter((el) => el.offsetParent !== null);
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [consoleOpen, mobileConsoleModal, setSettingsOpen, settingsOpen]);

  // Record studio visit non-blockingly.
  useEffect(() => {
    let cancelled = false;
    const targetBackend = settings.backendUrl?.trim() || getDefaultBackendUrl();
    let url: string;
    try {
      url = buildVisitsUrl(targetBackend);
    } catch {
      return;
    }
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_load_id: PAGE_LOAD_VISIT_ID }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { visits?: unknown } | null) => {
        if (!cancelled && data && typeof data.visits === "number") {
          setVisitCount(data.visits);
        }
      })
      .catch(() => {
        // Non-blocking telemetry.
      });
    return () => {
      cancelled = true;
    };
  }, [settings.backendUrl]);

  const isCascade = settings.engine === "cascade";
  const showAvatarCompatBanner = Boolean(settings.avatarEnabled) && isCascade;

  const handleEngineClick = (target: "live" | "cascade") => {
    if (target === settings.engine) return;
    if (active) {
      triggerFlash("End call first", "warn", 2200);
      return;
    }
    if (flashTimerRef.current) {
      clearTimeout(flashTimerRef.current);
      flashTimerRef.current = null;
    }
    setFlash(null);
    chooseEngine(target);
  };

  const handleEngineKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    if (active) {
      triggerFlash("End call first", "warn", 2200);
      return;
    }
    if (flashTimerRef.current) {
      clearTimeout(flashTimerRef.current);
      flashTimerRef.current = null;
    }
    setFlash(null);
    const next = settings.engine === "live" ? "cascade" : "live";
    chooseEngine(next);
    document.getElementById(next === "live" ? "seg-live" : "seg-cascade")?.focus();
  };

  const handleSwitchToLiveForAvatar = async () => {
    if (active) {
      await endSession();
      chooseEngine("live");
      await startBackend("live");
      triggerFlash("Switched to Gemini Live", "info", 1600);
    } else {
      chooseEngine("live");
      requestAnimationFrame(() => document.getElementById("seg-live")?.focus());
    }
  };

  const sessionChipText = flash
    ? flash.text
    : phase === "connecting"
      ? "Connecting..."
      : active
        ? `Live · ${formatElapsed(elapsed)}`
        : messages.length > 0
          ? `Ended · ${turnCount} ${turnCount === 1 ? "turn" : "turns"}`
          : "Ready";

  const sessionChipTone = flash
    ? flash.tone === "info"
      ? "is-info"
      : "is-warn"
    : active
      ? "is-live"
      : "";

  return (
    <>
      <div
        className={`app ${consoleOpen ? "has-console" : ""} ${active ? "is-in-call" : ""} ${isPostCall ? "is-post-call" : ""}`}
        id="app"
        style={{ "--persona": personaAccent } as CSSProperties}
      >
        <div ref={mainColRef} className="main-col" id="main-col">
          <header className="topbar">
            <a
              href="/"
              className="brand"
              aria-label="Voice Studio home"
              onClick={(e) => {
                if (!active && messages.length > 0) {
                  e.preventDefault();
                  resetToSetup();
                }
              }}
            >
              <span className="brand-mark" aria-hidden="true">
                <BrandWaveIcon />
              </span>
              <span className="brand-name">Voice Studio</span>
            </a>

            <div className="segmented-control" role="radiogroup" aria-label="Voice engine">
              <button
                type="button"
                role="radio"
                id="seg-live"
                aria-checked={!isCascade}
                aria-disabled={active && isCascade ? true : undefined}
                title={active && isCascade ? "End session to switch engine" : undefined}
                tabIndex={!isCascade ? 0 : -1}
                className="seg-btn"
                onClick={() => handleEngineClick("live")}
                onKeyDown={handleEngineKeyDown}
              >
                Gemini 3.8 Live
              </button>
              <button
                type="button"
                role="radio"
                id="seg-cascade"
                aria-checked={isCascade}
                aria-disabled={active && !isCascade ? true : undefined}
                title={active && !isCascade ? "End session to switch engine" : undefined}
                tabIndex={isCascade ? 0 : -1}
                className="seg-btn"
                onClick={() => handleEngineClick("cascade")}
                onKeyDown={handleEngineKeyDown}
              >
                Cascade STT · TTS
              </button>
            </div>

            <div className="topbar-right">
              <span
                className={`session-chip ${sessionChipTone}`}
                id="session-chip"
                role="status"
                aria-live="polite"
              >
                <span className="dot" aria-hidden="true" />
                <span id="session-chip-text">{sessionChipText}</span>
              </span>

              {sourceDownload && (
                <a href="/voice-studio-source.zip" download className="ghost-btn">
                  <span className="btn-text">Source</span>
                </a>
              )}

              <button
                type="button"
                className="ghost-btn"
                id="btn-console"
                aria-label="Observability"
                title="Observability"
                aria-expanded={consoleOpen}
                aria-controls="console-rail"
                onClick={() => {
                  const next = !consoleOpen;
                  setConsoleOpen(next);
                  if (next) {
                    requestAnimationFrame(() =>
                      document.getElementById("btn-close-console")?.focus(),
                    );
                  }
                }}
              >
                <ConsoleActivityIcon />
                <span className="btn-text">Observability</span>
              </button>

              <button
                type="button"
                className="ghost-btn"
                id="btn-settings"
                aria-expanded={settingsOpen}
                aria-haspopup="dialog"
                aria-controls="settings-dialog"
                onClick={() => setSettingsOpen(!settingsOpen)}
              >
                <SlidersIcon />
                <span className="btn-text">Settings</span>
              </button>
            </div>
          </header>

          <CastRail
            selectedPersonaId={settings.personaId}
            active={active}
            onSelectPersona={choosePersona}
            onLockedAttempt={() => triggerFlash("End call to switch persona", "warn", 2000)}
          />

          <main className="stage scroll-area" id="stage">
            {showLiveStage ? <LiveCallStage studio={studio} /> : <PreCallCard studio={studio} />}
          </main>

          {showAvatarCompatBanner && (
            <div className="compat-banner" id="compat-banner" role="status">
              <span>
                3.8 Avatar requires the native Gemini Live engine. Cascade runs audio-only with
                Chirp 3 HD or Gemini 3.8 TTS.
              </span>
              <button
                type="button"
                className="ghost-btn warn"
                id="btn-switch-to-live"
                onClick={() => void handleSwitchToLiveForAvatar()}
              >
                {active ? "Restart with Gemini Live" : "Switch to Gemini Live"}
              </button>
            </div>
          )}

          {voiceFallbackNotice && (
            <div className="compat-banner" role="status">
              <span>
                <strong>
                  {fallbackHeadline("voice", voiceFallbackNotice.fallbackVoice, voiceFallbackNotice.code)}
                </strong>
                {": "}
                {voiceFallbackNotice.reason}
              </span>
              <button
                type="button"
                className="ghost-btn"
                aria-label="Dismiss voice fallback notice"
                onClick={() => setVoiceFallbackNotice(null)}
              >
                <CloseIcon />
              </button>
            </div>
          )}

          {error && (
            <div className="compat-banner is-error" role="alert">
              <span>{error}</span>
              <button
                type="button"
                className="ghost-btn"
                aria-label="Dismiss error"
                onClick={() => setError("")}
              >
                <CloseIcon />
              </button>
            </div>
          )}

          <CallDock
            studio={studio}
            consoleOpen={consoleOpen}
            onAvatarCompatNotice={() =>
              triggerFlash("3.8 Avatar runs on Gemini Live", "warn", 2200)
            }
          />
        </div>

        <ObservabilityDrawer
          open={consoleOpen}
          onClose={() => {
            setConsoleOpen(false);
            requestAnimationFrame(() => document.getElementById("btn-console")?.focus());
          }}
          backendUrl={settings.backendUrl?.trim() || getDefaultBackendUrl()}
          engine={settings.engine}
          active={active}
          isMobileModal={mobileConsoleModal}
          inert={settingsOpen}
          persona={persona}
          settings={settings}
          messages={messages}
          sessionId={settings.sessionId}
          sessionTurnCount={turnCount}
          sessionTokens={tokenCount}
          sessionTokenSplit={tokenSplit}
          sessionCost={
            settings.engine === "cascade" ? Number(cascadeCost?.known_usd ?? 0) : sessionCostUSD
          }
          sessionCostBounds={sessionCostBounds}
          cascadeCost={cascadeCost}
          sessionInterrupts={interruptCount}
          visitCount={visitCount}
        />
      </div>

      <SettingsDialog studio={studio} />

      <ContextCompressionToast
        event={studio.compressionEvent}
        onDismiss={studio.dismissCompressionToast}
      />

      <ToolInjectionToast
        event={studio.toolInjection}
        onDismiss={studio.dismissToolInjection}
      />
    </>
  );
}
