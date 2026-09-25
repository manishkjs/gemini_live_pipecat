import { Video, Sparkles, Settings2 } from "lucide-react";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import { AVATAR_CHARACTERS } from "@/lib/voice-session";
import PersonaAvatar from "./persona-avatar";

/**
 * Occupies the left half (50%) of the lower transcription workspace when
 * Gemini 3.8 Live Avatar is enabled, streaming the 704x1280 9:16 portrait
 * H.264 + 24 kHz AAC digital human side-by-side with the Live Transcript.
 */
export default function AvatarStagePanel({ studio }: { studio: VoiceStudio }) {
  const {
    active,
    phase,
    persona,
    sound,
    settings,
    avatarStream,
    avatarFallbackNotice,
    update,
    setSettingsOpen,
  } = studio;

  const activeAvatarChar =
    AVATAR_CHARACTERS.find((c) => c.id === (settings.avatarName || "auto")) ?? AVATAR_CHARACTERS[0];

  const displayCharLabel = avatarFallbackNotice
    ? `${avatarFallbackNotice.fallbackAvatar} (Fallback)`
    : activeAvatarChar.id === "auto"
      ? "Auto"
      : activeAvatarChar.name;

  const statusText =
    phase === "speaking"
      ? `${persona.agentName} is speaking`
      : phase === "thinking"
        ? "Thinking…"
        : phase === "connecting"
          ? "Connecting 3.8 Avatar…"
          : active
            ? "Connected · Live Video"
            : "3.8 Avatar Ready";

  return (
    <aside className={`avatar-half-panel phase-${phase}`} aria-label="Gemini 3.8 Live Avatar video stage">
      <div className="avatar-half-header">
        <div className="avatar-half-title">
          <span className="avatar-half-badge">
            <Sparkles size={11} /> Gemini 3.8 Live Avatar
          </span>
          <span className="avatar-half-spec">704×1280 HD · 24 kHz AAC</span>
        </div>
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className="avatar-half-config-btn"
          title="Open Avatar & Voice Settings"
        >
          <Settings2 size={13} />
          <span>Avatar Options</span>
        </button>
      </div>

      <div className="avatar-half-stage-center">
        <div className={`avatar-portrait-frame phase-${phase}`}>
          <div className="avatar-stage-glow" />
          <div className="avatar-stage-viewport">
            <video
              ref={avatarStream.videoRef}
              autoPlay
              playsInline
              muted={!sound}
              className={`avatar-stage-video ${avatarStream.hasVideoFrame ? "is-ready" : ""}`}
            />

            {!avatarStream.hasVideoFrame && (
              <div className="avatar-stage-placeholder">
                {settings.avatarName === "custom" && settings.avatarCustomImage ? (
                  <img
                    src={settings.avatarCustomImage}
                    alt="Custom portrait (704x1280 9:16 PNG)"
                    className="avatar-custom-stage-img"
                  />
                ) : (
                  <PersonaAvatar key={persona.id} persona={persona} className="stage-portrait" />
                )}
                <div className="avatar-placeholder-caption">
                  <strong>
                    {activeAvatarChar.id === "auto"
                      ? `${persona.agentName} (Auto Avatar)`
                      : `${activeAvatarChar.name} · ${persona.agentName}`}
                  </strong>
                  <span>
                    {phase === "connecting"
                      ? "Establishing Vertex AI 3.8 video stream…"
                      : active
                        ? "Streaming initialization segment…"
                        : "Click Start Live Avatar above to begin"}
                  </span>
                </div>
              </div>
            )}

            <div className="avatar-stage-overlay-top">
              <span className={`avatar-status-pill ${active ? "is-live" : ""}`}>
                <span className="avatar-status-dot" />
                {statusText}
              </span>
              <span className="avatar-char-badge-btn">
                <Video size={11} />
                <span>{displayCharLabel}</span>
              </span>
            </div>

            {avatarFallbackNotice && (
              <div className="avatar-stage-fallback-banner" role="status">
                {settings.avatarCustomImage && (
                  <img
                    src={settings.avatarCustomImage}
                    alt="Uploaded custom portrait"
                    className="avatar-fallback-pip"
                  />
                )}
                <div className="avatar-fallback-text">
                  <strong>Using {avatarFallbackNotice.fallbackAvatar} (Project Not Allowlisted for Custom Likeness)</strong>
                  <span>{avatarFallbackNotice.reason}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Quick Digital Human Character Switcher Bar (active before call starts) */}
      <div className="avatar-quick-switcher" role="radiogroup" aria-label="Quick select avatar character">
        {AVATAR_CHARACTERS.map((char) => {
          const isSelected = (settings.avatarName || "auto") === char.id;
          return (
            <button
              key={char.id}
              type="button"
              role="radio"
              aria-checked={isSelected}
              disabled={active}
              onClick={() => {
                update("avatarName", char.id);
                if (char.id === "custom" && !settings.avatarCustomImage) {
                  setSettingsOpen(true);
                }
              }}
              className={`avatar-quick-pill ${isSelected ? "selected" : ""}`}
              title={active ? "Stop session to change avatar character" : `${char.name} — ${char.role}`}
            >
              <span>
                {char.id === "auto" ? "✨ Auto" : char.id === "custom" ? "📷 Custom" : char.name}
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
