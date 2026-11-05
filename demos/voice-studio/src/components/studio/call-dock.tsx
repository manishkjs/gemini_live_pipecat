import { useSyncExternalStore, type CSSProperties } from "react";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import {
  computeBubbleBarScale,
  computeBubblePillStretch,
  formatLatencySeconds,
  formatSessionCents,
  isFastTtfbSeconds,
  resolveVoiceBubbleState,
} from "@/lib/call-console";
import { formatTokens } from "@/lib/pricing";
import { isAvatarActive } from "@/lib/voice-session";
import {
  ArrowLeftIcon,
  MicOffIcon,
  MicOnIcon,
  PhoneEndIcon,
  SpeakerOffIcon,
  SpeakerOnIcon,
  VideoOffIcon,
  VideoOnIcon,
} from "./console-icons";

interface CallDockProps {
  readonly studio: VoiceStudio;
  readonly consoleOpen: boolean;
  readonly onAvatarCompatNotice: () => void;
}

const BAR_FACTORS = [0.55, 0.8, 1.0, 0.72, 1.15, 0.82, 1.0, 0.68, 0.5] as const;
const SERVER_AUDIO_LEVEL = () => 0;

interface VoiceBubbleProps {
  readonly active: boolean;
  readonly sound: boolean;
  readonly bubble: ReturnType<typeof resolveVoiceBubbleState>;
  readonly subscribeAudioLevel: VoiceStudio["subscribeAudioLevel"];
  readonly getAudioLevel: VoiceStudio["getAudioLevel"];
}

/** Isolated 14 Hz audio-level subscriber so live speech envelopes never re-render the rest of the studio. */
function VoiceBubble({
  active,
  sound,
  bubble,
  subscribeAudioLevel,
  getAudioLevel,
}: VoiceBubbleProps) {
  const audioLevel = useSyncExternalStore(subscribeAudioLevel, getAudioLevel, SERVER_AUDIO_LEVEL);
  const bubbleClasses = [
    "voice-bubble",
    bubble.isActive ? "is-active" : "",
    bubble.isSample ? "is-sample" : "",
    bubble.isListening ? "is-listening" : "",
    bubble.isMuted ? "is-muted" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const liveAudioReactive =
    active && ((bubble.isActive && sound) || (bubble.isListening && !bubble.isMuted));
  const clampedLevel = liveAudioReactive ? Math.max(0, Math.min(1, audioLevel)) : 0;
  const pillStretch = liveAudioReactive ? computeBubblePillStretch(clampedLevel) : 1;
  const bubbleStyle: CSSProperties = {
    "--vb-level": clampedLevel.toFixed(3),
    "--vb-stretch": pillStretch.toFixed(3),
  } as CSSProperties;

  return (
    <div
      className={bubbleClasses}
      id="voice-bubble"
      role="status"
      aria-label={bubble.ariaLabel}
      style={bubbleStyle}
    >
      <span className="vb-orb" aria-hidden="true" />
      <span className="vb-bars" aria-hidden="true">
        {BAR_FACTORS.map((factor, index) => {
          const dynamicScale = liveAudioReactive
            ? computeBubbleBarScale(clampedLevel, factor)
            : undefined;
          return (
            <i
              key={index}
              style={
                dynamicScale !== undefined
                  ? { transform: `scaleY(${dynamicScale.toFixed(3)})` }
                  : undefined
              }
            />
          );
        })}
      </span>
      <span className="vb-label" id="vb-label">
        {bubble.label}
      </span>
    </div>
  );
}

/** Bottom call dock with Mic/Speaker/Avatar controls, organic audio-stretch bubble, primary CTA, and live stats. */
export default function CallDock({ studio, consoleOpen, onAvatarCompatNotice }: CallDockProps) {
  const {
    active,
    phase,
    muted,
    sound,
    playingSample,
    subscribeAudioLevel,
    getAudioLevel,
    messages,
    persona,
    settings,
    tokenCount,
    sessionCostUSD,
    sessionCostBounds,
    cascadeCost,
    lastTTFB,
    session,
    setMuted,
    toggleSound,
    updateBool,
    startBackend,
    endSession,
    resetToSetup,
  } = studio;

  const isCascade = settings.engine === "cascade";
  const isPostCall = !active && messages.length > 0;
  const avatarEnabled = Boolean(settings.avatarEnabled);
  const avatarCompatPaused = avatarEnabled && isCascade;
  const avatarLiveActive = isAvatarActive(settings);

  const bubble = resolveVoiceBubbleState({
    active,
    phase,
    sound,
    muted,
    playingSample,
    agentName: persona.agentName,
  });

  const handleToggleMic = () => {
    const nextMuted = !muted;
    setMuted(nextMuted);
    session.current?.setMic(!nextMuted);
  };

  const handleToggleAvatar = () => {
    const next = !avatarEnabled;
    updateBool("avatarEnabled", next);
    if (next && isCascade) {
      onAvatarCompatNotice();
    }
  };

  const startLabel = isCascade
    ? "Start Cascade call"
    : avatarLiveActive
      ? "Start Live Avatar"
      : "Start Gemini Live";

  const sessionCostLabel = formatSessionCents({
    engine: settings.engine,
    model: settings.model,
    sessionCostUSD,
    cascadeCost,
    incomplete: sessionCostBounds.incomplete,
    estimated: sessionCostBounds.estimated,
  });

  const engineDisplay = isCascade
    ? settings.ttsModel === "google-tts"
      ? "cascade-chirp3"
      : settings.ttsModel
    : settings.model.replace(/-aistudio$/, "");

  const avatarAriaLabel = avatarCompatPaused
    ? "3.8 Live Avatar video (enabled, paused in Cascade mode)"
    : isCascade
      ? "3.8 Live Avatar video (Live mode only)"
      : "3.8 Live Avatar video";

  return (
    <footer className="call-dock" role="region" aria-label="Call controls">
      <div className="dock-left">
        <button
          type="button"
          className="round-btn"
          id="btn-mic"
          aria-pressed={muted}
          aria-label="Mute microphone"
          onClick={handleToggleMic}
        >
          {muted ? <MicOffIcon /> : <MicOnIcon />}
          <span className="round-lbl" aria-hidden="true">
            {muted ? "Muted" : "Mic"}
          </span>
        </button>

        <button
          type="button"
          className="round-btn"
          id="btn-spk"
          aria-pressed={!sound}
          aria-label="Mute speaker"
          onClick={toggleSound}
        >
          {sound ? <SpeakerOnIcon /> : <SpeakerOffIcon />}
          <span className="round-lbl" aria-hidden="true">
            {sound ? "Speaker" : "Spk off"}
          </span>
        </button>

        <button
          type="button"
          className={`round-btn${avatarCompatPaused ? " paused" : ""}`}
          id="btn-avatar"
          role="switch"
          aria-checked={avatarEnabled}
          aria-label={avatarAriaLabel}
          onClick={handleToggleAvatar}
        >
          {avatarEnabled ? <VideoOnIcon /> : <VideoOffIcon />}
          <span className="round-lbl" aria-hidden="true">
            {avatarCompatPaused ? "Paused" : "Avatar"}
          </span>
        </button>
      </div>

      <div className="dock-center">
        {(!isPostCall || muted || playingSample) && (
          <VoiceBubble
            active={active}
            sound={sound}
            bubble={bubble}
            subscribeAudioLevel={subscribeAudioLevel}
            getAudioLevel={getAudioLevel}
          />
        )}

        {isPostCall && (
          <button
            type="button"
            className="dock-secondary-cta"
            id="btn-dock-personas"
            onClick={resetToSetup}
          >
            <ArrowLeftIcon />
            <span>All personas</span>
          </button>
        )}

        {active ? (
          <button
            type="button"
            className="cta end"
            id="btn-cta"
            onClick={() => void endSession()}
          >
            <PhoneEndIcon />
            <span>End call</span>
          </button>
        ) : (
          <button
            type="button"
            className="cta"
            id="btn-cta"
            onClick={() => void startBackend()}
          >
            <MicOnIcon />
            <span>{startLabel}</span>
          </button>
        )}
      </div>

      <div className="dock-right" id="dock-right">
        {active && !consoleOpen ? (
          <>
            <div className="dock-stat">
              <span className="k">Tokens</span>
              <span className="v">{formatTokens(tokenCount)}</span>
            </div>
            <div className="dock-stat">
              <span className="k">Cost</span>
              <span className="v">{sessionCostLabel}</span>
            </div>
            <div className="dock-stat">
              <span className="k">Last TTFB</span>
              <span
                className={`v${
                  lastTTFB !== null
                    ? isFastTtfbSeconds(lastTTFB / 1000, settings.engine)
                      ? " fast"
                      : " warn"
                    : ""
                }`}
              >
                {lastTTFB !== null ? formatLatencySeconds(lastTTFB / 1000) : "--"}
              </span>
            </div>
          </>
        ) : (
          <>
            <div className="dock-stat">
              <span className="k">Engine</span>
              <span className="v">{engineDisplay}</span>
            </div>
            <div className="dock-stat">
              <span className="k">Audio</span>
              <span className="v">24 kHz</span>
            </div>
          </>
        )}
      </div>
    </footer>
  );
}
