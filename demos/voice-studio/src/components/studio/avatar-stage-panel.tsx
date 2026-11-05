import { useRef, useState } from "react";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import { normalizeAvatarPortraitFile } from "@/lib/media-capture";
import { AVATAR_CHARACTERS, fallbackHeadline } from "@/lib/voice-session";
import { UploadIcon } from "./console-icons";

interface AvatarStagePanelProps {
  readonly studio: VoiceStudio;
}

/** Docked left 9:16 video stage for Gemini 3.8 Live Avatar streaming sessions. */
export default function AvatarStagePanel({ studio }: AvatarStagePanelProps) {
  const {
    active,
    persona,
    sound,
    settings,
    avatarStream,
    avatarFallbackNotice,
    setAvatarFallbackNotice,
    applyCustomAvatarAndStart,
    startBackend,
    update,
  } = studio;
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadBusy, setUploadBusy] = useState(false);

  const selectedChar = AVATAR_CHARACTERS.find((item) => item.id === settings.avatarName) ?? AVATAR_CHARACTERS[0];
  const isCustomWithoutImage = settings.avatarName === "custom" && !settings.avatarCustomImage?.trim();
  const posterSrc =
    settings.avatarName === "custom" && settings.avatarCustomImage?.trim()
      ? settings.avatarCustomImage
      : persona.portrait;

  const handleSelectCharacter = (charId: string) => {
    setAvatarFallbackNotice(null);
    update("avatarName", charId);
    if (charId === "custom" && !settings.avatarCustomImage?.trim()) {
      return;
    }
    if (active) {
      void startBackend("live", {
        engine: "live",
        avatarEnabled: true,
        avatarName: charId,
        model: "gemini-3.8-live",
      });
    }
  };

  const handlePhotoUpload = async (file: File | undefined) => {
    if (!file) return;
    setUploadBusy(true);
    try {
      const normalized = await normalizeAvatarPortraitFile(file);
      update("avatarCustomImage", normalized.dataUrl);
      update("avatarName", "custom");
      if (active) {
        await applyCustomAvatarAndStart(normalized.dataUrl);
      }
    } catch (err) {
      studio.setError(err instanceof Error ? err.message : "Could not process uploaded portrait.");
    } finally {
      setUploadBusy(false);
    }
  };

  return (
    <section className="avatar-pane" aria-label="Gemini 3.8 Live Avatar">
      <div className="ap-head">
        <div>
          <b>{selectedChar.name}</b> · 3.8 Live Avatar
        </div>
        <span className="mono-pill">9:16 fMP4 · 24 fps</span>
      </div>

      {avatarFallbackNotice && (
        <div className="compat-banner" role="status">
          <span>
            {fallbackHeadline("avatar", avatarFallbackNotice.fallbackAvatar, avatarFallbackNotice.code)}
          </span>
          <button type="button" className="ghost-btn" onClick={() => setAvatarFallbackNotice(null)}>
            Dismiss
          </button>
        </div>
      )}

      <div className="ap-frame-wrap">
        <div className="ap-frame">
          {isCustomWithoutImage ? (
            <div className="ap-empty">
              <p>Upload a portrait photo (normalized to 704×1280 PNG) to animate your custom avatar.</p>
              <button
                type="button"
                id="btn-avatar-upload"
                className="cc-sample"
                disabled={uploadBusy}
                onClick={() => uploadInputRef.current?.click()}
              >
                <UploadIcon />
                <span>{uploadBusy ? "Processing..." : "Upload portrait"}</span>
              </button>
            </div>
          ) : (
            <>
              {posterSrc && !avatarStream.hasVideoFrame && (
                <img src={posterSrc} alt={`${persona.agentName} avatar preview`} />
              )}
              <video
                ref={avatarStream.videoRef}
                className={`ap-video${avatarStream.hasVideoFrame ? " is-ready" : ""}`}
                autoPlay
                playsInline
                muted={!sound}
              />
              <div className="ap-overlay">
                <span className={`ap-live${avatarStream.hasVideoFrame ? "" : " waiting"}`}>
                  {avatarStream.hasVideoFrame ? "Lip-sync live" : active ? "Buffering stream..." : "Preview"}
                </span>
                <span className="mono-pill">704×1280</span>
              </div>
            </>
          )}
        </div>
      </div>

      <input
        ref={uploadInputRef}
        type="file"
        id="avatar-upload-input"
        accept="image/png,image/jpeg,image/webp"
        hidden
        onChange={(e) => {
          void handlePhotoUpload(e.target.files?.[0]);
          e.currentTarget.value = "";
        }}
      />

      <div className="ap-chars" role="group" aria-label="Avatar character">
        {AVATAR_CHARACTERS.map((char) => (
          <button
            key={char.id}
            type="button"
            className="ap-char"
            aria-pressed={settings.avatarName === char.id}
            onClick={() => handleSelectCharacter(char.id)}
          >
            {char.name}
          </button>
        ))}
        {settings.avatarName === "custom" && settings.avatarCustomImage?.trim() && (
          <button
            type="button"
            className="ap-char"
            onClick={() => uploadInputRef.current?.click()}
          >
            Replace photo
          </button>
        )}
      </div>
    </section>
  );
}
