import type { ComponentType } from "react";
import { Mic, MicOff, Square, Volume2, VolumeX, Video } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { WaveProps } from "@/lib/studio-types";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import { AVATAR_CHARACTERS } from "@/lib/voice-session";
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
    toggleSound, track, settings, updateBool, update, chooseEngine,
  } = studio;

  const isAvatarMode = Boolean(settings.avatarEnabled && settings.engine === "live");
  const activeAvatarChar =
    AVATAR_CHARACTERS.find((c) => c.id === (settings.avatarName || "auto")) ?? AVATAR_CHARACTERS[0];

  // Derived from real state rather than a bare `active` flag, so the stage never
  // claims to be connected while it is still dialling.
  const sessionHint =
    phase === "connecting"
      ? isAvatarMode
        ? "Connecting to Gemini 3.8 Live Avatar video stream\u2026"
        : "Connecting to your voice backend\u2026"
      : active
        ? `Connected via ${isAvatarMode ? "Gemini 3.8 Live Avatar" : engineName} with ${persona.agentName}. Speak naturally \u2014 you can interrupt anytime.`
        : `Click Start ${isAvatarMode ? "Live Avatar" : engineName} to talk.`;

  return (
    <div
      className={`conversation-stage phase-${phase}`}
      aria-labelledby="agent-heading"
    >
      <div className="stage-left">
        <div className="wave-container" aria-hidden="true">
          {Wave ? (
            <Wave
              audioTrack={source === "backend" ? track : null}
              isThinking={!reduced && active && (phase === "thinking" || phase === "connecting")}
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
          <button
            type="button"
            disabled={active}
            onClick={() => {
              const next = !settings.avatarEnabled;
              updateBool("avatarEnabled", next);
              if (next) {
                if (settings.engine !== "live") chooseEngine("live");
                update("model", "gemini-3.8-live");
              }
            }}
            className={`stage-avatar-toggle-chip ${isAvatarMode ? "active" : ""}`}
            title={
              active
                ? "Stop session to toggle Gemini 3.8 Live Avatar"
                : "Toggle Gemini 3.8 Live Avatar (opens 50% video stage below)"
            }
          >
            <Video size={13} />
            <span>
              {isAvatarMode
                ? `3.8 Avatar: ON (${activeAvatarChar.id === "auto" ? "Auto" : activeAvatarChar.name})`
                : "3.8 Avatar: Off"}
            </span>
          </button>
        </div>
        <div className="your-role">
          <span className="eyebrow">{custom ? "CUSTOM SESSION" : "YOUR ROLE"}</span>
          <p>{persona.userRole}</p>
        </div>
        <p className="preview-note">{sessionHint}</p>
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
              {isAvatarMode ? <Video size={18} /> : <Mic size={18} />}
              <span>Start {isAvatarMode ? "Live Avatar" : engineName}</span>
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
              {active
                ? muted
                  ? "Muted"
                  : "Interrupt anytime"
                : "Mic requested on start"}
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
