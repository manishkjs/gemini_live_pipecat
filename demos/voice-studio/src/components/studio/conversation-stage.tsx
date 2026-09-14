import type { ComponentType } from "react";
import { Mic, MicOff, Square, Volume2, VolumeX, DollarSign } from "lucide-react";
import { Button } from "@/components/ui/button";
import { isLivePricingEligible, formatCost } from "@/lib/pricing";
import type { WaveProps } from "@/lib/studio-types";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import PersonaAvatar from "./persona-avatar";

/** The agent's stage: waveform, call controls and running cost. */
export default function ConversationStage({
  studio,
  Wave,
}: {
  studio: VoiceStudio;
  Wave: ComponentType<WaveProps> | null;
}) {
  const {
    active, complete, custom, endSession, engineName, messages, muted, persona, phase,
    reduced, sessionCostUSD, session, settings, setMuted, sound, source, startBackend,
    toggleSound, track, phaseLabel,
  } = studio;

  return (
    <section className={`conversation-stage phase-${phase}`} aria-labelledby="agent-heading">
      <div className="stage-top">
        <span className={`connection-state ${active ? "is-active" : ""}`}>
          <span className="status-dot" />
          {phaseLabel}
        </span>
      </div>

      <div className="agent-stage">
        <div className="wave-container" aria-hidden="true">
          {Wave ? (
            <Wave
              audioTrack={source === "backend" ? track : null}
              isThinking={!reduced && active && (source === "preview" || phase === "thinking" || phase === "connecting")}
              color1={persona.color}
              color2="#82b7a6"
              backgroundColor="transparent"
              rotationEnabled={!reduced && active}
              numBars={64}
              sensitivity={1.3}
            />
          ) : (
            <div className="wave-fallback" />
          )}
          <div className="wave-core">
            <PersonaAvatar key={persona.id} persona={persona} className="stage-portrait" />
          </div>
        </div>
        <h2 id="agent-heading">{custom ? "Your agent. Your rules." : `Meet ${persona.agentName}.`}</h2>
        <p>{custom ? "A blank canvas for your voice app" : persona.name}</p>
      </div>

      <div className="your-role">
        <span className="eyebrow">{custom ? "CUSTOM SESSION" : "YOUR ROLE"}</span>
        <p>{persona.userRole}</p>
      </div>

      <div className="session-actions">
        {active ? (
          <Button className="primary-call end-call" onClick={() => void endSession()}>
            <Square size={15} fill="currentColor" />Stop Session
          </Button>
        ) : (
          <Button
            className="primary-call"
            disabled={active}
            onClick={() => void startBackend()}
          >
            <Mic size={18} />
            <span>Start {engineName}</span>
          </Button>
        )}
        <div className="audio-controls">
          <Button
            variant="outline"
            size="icon"
            aria-label={muted ? "Unmute microphone" : "Mute microphone"}
            aria-pressed={muted}
            disabled={!active || source !== "backend" || phase === "connecting"}
            onClick={() => {
              session.current?.setMic(muted);
              setMuted(!muted);
            }}
          >
            {muted ? <MicOff size={17} /> : <Mic size={17} />}
          </Button>
          <span>{active ? "Live audio active · Interrupt anytime" : "Microphone active on start"}</span>
          <Button
            variant="outline"
            size="icon"
            aria-label={sound ? "Mute speaker" : "Enable speaker"}
            aria-pressed={!sound}
            onClick={toggleSound}
          >
            {sound ? <Volume2 size={17} /> : <VolumeX size={17} />}
          </Button>
        </div>
        {isLivePricingEligible(settings.engine, settings.model) && sessionCostUSD > 0 && (
          <div className="session-recap-pill">
            <DollarSign size={13} />
            <span>Session Live Cost: <strong>{formatCost(sessionCostUSD)}</strong></span>
          </div>
        )}
      </div>
      <p className="preview-note">
        {active
          ? `Connected via ${engineName} with ${persona.agentName}. Speak into your microphone.`
          : `Ready to talk. Click Start ${engineName} to speak with ${custom ? "your agent" : persona.agentName}.`}
      </p>
    </section>
  );
}
