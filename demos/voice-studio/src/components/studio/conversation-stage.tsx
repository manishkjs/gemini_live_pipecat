import type { ComponentType } from "react";
import { Mic, MicOff, Square, Volume2, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { WaveProps } from "@/lib/studio-types";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import PersonaAvatar from "./persona-avatar";

/** The agent's stage: waveform, call controls and persona role. */
export default function ConversationStage({
  studio,
  Wave,
}: {
  studio: VoiceStudio;
  Wave: ComponentType<WaveProps> | null;
}) {
  const {
    active, custom, endSession, engineName, muted, persona, phase,
    reduced, session, setMuted, sound, source, startBackend,
    toggleSound, track,
  } = studio;

  return (
    <div className={`conversation-stage phase-${phase}`} aria-labelledby="agent-heading">
      <div className="stage-left">
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
      </div>

      <div className="stage-center">
        <div className="agent-title-row">
          <h2 id="agent-heading">{custom ? "Your agent. Your rules." : `Meet ${persona.agentName}.`}</h2>
          <span className="agent-role-pill">{custom ? "Custom Agent" : persona.name}</span>
        </div>
        <div className="your-role">
          <span className="eyebrow">{custom ? "CUSTOM SESSION" : "YOUR ROLE"}</span>
          <p>{persona.userRole}</p>
        </div>
        <p className="preview-note">
          {active
            ? `Connected via ${engineName} with ${persona.agentName}. Speak into your microphone.`
            : `Click Start ${engineName} to talk.`}
        </p>
      </div>

      <div className="stage-right">
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
            <span className="mic-hint-text">
              {active ? (muted ? "Muted" : "Interrupt anytime") : "Mic ready"}
            </span>
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
        </div>
      </div>
    </div>
  );
}
