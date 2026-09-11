"use client";

import { useEffect, useState, type ComponentType, type CSSProperties } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowUpRight, AudioLines, ChartLine, Settings2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getDefaultBackendUrl } from "@/lib/voice-session";
import type { WaveProps } from "@/lib/studio-types";
import { useVoiceSession } from "@/hooks/use-voice-session";
import ObservabilityDrawer from "./observability-drawer";
import PersonaPicker from "./studio/persona-picker";
import EngineToolbar from "./studio/engine-toolbar";
import ConversationStage from "./studio/conversation-stage";
import TranscriptPanel from "./studio/transcript-panel";
import SettingsDialog from "./studio/settings-dialog";
import "./voice-studio.css";

/** Loaded on demand so the waveform bundle never blocks first paint. */
function useWaveform() {
  const [Wave, setWave] = useState<ComponentType<WaveProps> | null>(null);
  useEffect(() => {
    let cancelled = false;
    import("@pipecat-ai/voice-ui-kit")
      .then(({ CircularWaveform }) => {
        if (!cancelled) setWave(() => CircularWaveform as ComponentType<WaveProps>);
      })
      .catch(() => {
        /* Accessible static fallback */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return Wave;
}

export default function VoiceStudio({ sourceDownload = false }: { sourceDownload?: boolean }) {
  const studio = useVoiceSession();
  const Wave = useWaveform();
  const [observabilityOpen, setObservabilityOpen] = useState(false);
  const {
    active, audio, error, persona, settings, setError, setSettingsOpen, sound, turnCount,
  } = studio;

  return (
  <main className="studio-shell" style={{ "--persona-color": persona.color } as CSSProperties}>
    <audio ref={audio} autoPlay muted={!sound} />


    {/* Header with Observability and Settings (Original UI removed) */}
    <header className="studio-header">
      <a href="/" className="studio-brand" aria-label="Voice Studio home">
        <span className="brand-mark">
          <AudioLines size={22} />
        </span>
        Voice<span className="brand-light">Studio</span>
        <span className="demo-tag">DEMO</span>
      </a>
      <div className="header-actions">
        <Button
          variant="outline"
          className="header-tool"
          onClick={() => setObservabilityOpen(true)}
          title="Open live telemetry and observability dashboard"
        >
          <ChartLine size={16} />
          <span>Observability</span>
          {turnCount > 0 && <span className="obs-badge">{turnCount}</span>}
        </Button>
        <Button
          className="header-tool"
          variant="outline"
          onClick={() => setSettingsOpen(true)}
          disabled={active}
          aria-label="Session settings"
        >
          <Settings2 size={16} />
          <span>Settings</span>
        </Button>
      </div>
    </header>

      <PersonaPicker selected={settings.personaId} active={active} onChoose={studio.choosePersona} />

      <EngineToolbar
        settings={settings}
        active={active}
        onEngineChange={studio.chooseEngine}
        onLanguageChange={(value) => studio.update("language", value)}
      />

      <div className="session-grid">
        <ConversationStage studio={studio} Wave={Wave} />
        <TranscriptPanel studio={studio} />
      </div>

    <AnimatePresence>
      {error && (
        <motion.div className="error-banner" role="alert" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <span>{error}</span>
          <Button variant="ghost" size="icon" aria-label="Dismiss error" onClick={() => setError("")}>
            <X size={16} />
          </Button>
        </motion.div>
      )}
    </AnimatePresence>

    <footer className="studio-footer">
      <span>
        <AudioLines size={15} /> Voice Studio <span className="footer-separator">/</span> Fictional agents · Indian languages
      </span>
      <div>
        {sourceDownload && (
          <a href="/voice-studio-source.zip" download>
            Download source <ArrowUpRight size={14} />
          </a>
        )}
        <a href="https://github.com/manishkjs/gemini_live_pipecat" target="_blank" rel="noreferrer">
          View project <ArrowUpRight size={14} />
        </a>
      </div>
    </footer>

      <SettingsDialog studio={studio} />

    {/* THEMED OBSERVABILITY DRAWER */}
    <ObservabilityDrawer
      open={observabilityOpen}
      onClose={() => setObservabilityOpen(false)}
      backendUrl={settings.backendUrl?.trim() || getDefaultBackendUrl()}
      engine={settings.engine}
      sessionId={settings.sessionId}
    />
  </main>
);
}
