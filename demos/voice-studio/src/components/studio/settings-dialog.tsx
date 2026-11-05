import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import {
  formatBackendUrlError,
  formatVoiceShortLabel,
  getPersonaCastRole,
  hasCustomBackendOrigin,
  reconcileCustomDetailsOpen,
} from "@/lib/call-console";
import {
  VOICE_CLONE_READING_SCRIPT,
  captureVideoFrameToAvatarPng,
  encodeFloat32ToWav24kMonoDataUrl,
  normalizeAvatarPortraitFile,
  normalizeUploadedVoiceAudioFile,
} from "@/lib/media-capture";
import { getPersonaPrompt, type PersonaTone } from "@/lib/personas";
import { estimateTokens, getLiveRateCard, isLivePricingEligible } from "@/lib/pricing";
import {
  AVATAR_CHARACTERS,
  CASCADE_LLM_MODEL_GROUPS,
  CASCADE_STT_MODEL_GROUPS,
  CASCADE_TTS_MODEL_GROUPS,
  CHIRP_HD_VOICES,
  GEMINI_38_LIBRARY_VOICES,
  GEMINI_CLONE_VOICES,
  GEMINI_VOICES,
  LANGUAGE_OPTIONS,
  LIVE_MODEL_GROUPS,
  THINKING_LEVELS,
  TTS_ACCENT_OPTIONS,
  TTS_PACE_OPTIONS,
  TTS_PITCH_OPTIONS,
  TTS_STYLE_OPTIONS,
  VAD_MODES,
  buildPersonaPromptUrl,
  getDefaultBackendUrl,
  isGeminiClonedVoice,
  isLibraryVoice,
  isLiveCustomVoice,
  parseToolsOverride,
  supportsCascadeAudioInput,
  supportsGeminiClone,
  usesExternalTts,
  type VadMode,
} from "@/lib/voice-session";
import { ChevronRightIcon, CloseIcon, ExpandIcon, MicOnIcon, StopSampleIcon } from "./console-icons";

interface SettingsDialogProps {
  readonly studio: VoiceStudio;
}

interface BackendToolDef {
  name?: string;
  description?: string;
  [key: string]: unknown;
}

/** Mode-dependent Session configuration modal for Gemini 3.8 Live and Cascade STT · TTS. */
export default function SettingsDialog({ studio }: SettingsDialogProps) {
  const {
    active,
    custom,
    persona,
    settings,
    settingsOpen,
    setSettingsOpen,
    chooseEngine,
    startBackend,
    endSession,
    applyCustomAvatarAndStart,
    update,
    updateBool,
    updateNumber,
    currentPhase,
  } = studio;

  const isCascade = settings.engine === "cascade";
  const isLive = !isCascade;
  const [isWide, setIsWide] = useState(false);
  const [modeLockFlash, setModeLockFlash] = useState<string | null>(null);
  const [bodyOverflowing, setBodyOverflowing] = useState(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const closeBtnRef = useRef<HTMLButtonElement | null>(null);

  // Webcam capture state for Custom Portrait (704×1280 9:16 RGB PNG)
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const [avatarProcessing, setAvatarProcessing] = useState(false);
  const cameraVideoRef = useRef<HTMLVideoElement | null>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);

  const bindCameraVideo = useCallback((el: HTMLVideoElement | null) => {
    cameraVideoRef.current = el;
    if (el && cameraStreamRef.current) {
      el.srcObject = cameraStreamRef.current;
      void el.play().catch(() => {});
    }
  }, []);

  const stopCamera = useCallback(() => {
    if (cameraStreamRef.current) {
      for (const track of cameraStreamRef.current.getTracks()) {
        track.stop();
      }
      cameraStreamRef.current = null;
    }
    if (cameraVideoRef.current) {
      cameraVideoRef.current.srcObject = null;
    }
    setCameraOpen(false);
  }, []);

  const startCamera = useCallback(async () => {
    setCameraError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
        audio: false,
      });
      cameraStreamRef.current = stream;
      setCameraOpen(true);
      if (cameraVideoRef.current) {
        cameraVideoRef.current.srcObject = stream;
        void cameraVideoRef.current.play().catch(() => {});
      }
    } catch (err) {
      setCameraError(err instanceof Error ? err.message : "Unable to access camera.");
      setCameraOpen(false);
    }
  }, []);

  const snapCameraPhoto = useCallback(() => {
    const videoEl = cameraVideoRef.current;
    if (!videoEl) return;
    try {
      setAvatarProcessing(true);
      setCameraError("");
      const { dataUrl } = captureVideoFrameToAvatarPng(videoEl, true);
      stopCamera();
      void applyCustomAvatarAndStart(dataUrl).finally(() => setAvatarProcessing(false));
    } catch (err) {
      setAvatarProcessing(false);
      setCameraError(err instanceof Error ? err.message : "Failed to capture frame.");
    }
  }, [applyCustomAvatarAndStart, stopCamera]);

  // Browser Microphone Recorder state for Custom Voice Clone (24 kHz 16-bit mono WAV)
  const [voiceRecording, setVoiceRecording] = useState(false);
  const [voiceRecordSec, setVoiceRecordSec] = useState(0);
  const [voiceMetaNote, setVoiceMetaNote] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const voiceAudioCtxRef = useRef<AudioContext | null>(null);
  const voiceStreamRef = useRef<MediaStream | null>(null);
  const voiceChunksRef = useRef<Float32Array[]>([]);
  const voiceSampleRateRef = useRef<number>(24000);
  const voiceTimerRef = useRef<number | null>(null);
  const voiceUploadInputRef = useRef<HTMLInputElement | null>(null);
  const avatarUploadInputRef = useRef<HTMLInputElement | null>(null);

  const cleanupVoiceRecordingResources = useCallback(() => {
    if (voiceTimerRef.current !== null) {
      window.clearInterval(voiceTimerRef.current);
      voiceTimerRef.current = null;
    }
    if (voiceStreamRef.current) {
      for (const t of voiceStreamRef.current.getTracks()) {
        t.stop();
      }
      voiceStreamRef.current = null;
    }
    if (voiceAudioCtxRef.current) {
      void voiceAudioCtxRef.current.close().catch(() => {});
      voiceAudioCtxRef.current = null;
    }
    setVoiceRecording(false);
  }, []);

  const stopVoiceRecording = useCallback(() => {
    const chunks = voiceChunksRef.current;
    const sr = voiceSampleRateRef.current;
    cleanupVoiceRecordingResources();
    const totalLen = chunks.reduce((acc, c) => acc + c.length, 0);
    if (totalLen === 0) return;
    const merged = new Float32Array(totalLen);
    let offset = 0;
    for (const c of chunks) {
      merged.set(c, offset);
      offset += c.length;
    }
    voiceChunksRef.current = [];
    try {
      const { dataUrl, durationSec, byteLength } = encodeFloat32ToWav24kMonoDataUrl(merged, sr);
      update("customVoiceAudio", dataUrl);
      update("model", "gemini-3.8-live");
      setVoiceMetaNote(`${durationSec}s · 24 kHz 16-bit mono WAV (${Math.round(byteLength / 1024)} KB)`);
      setVoiceError("");
    } catch (err) {
      setVoiceError(err instanceof Error ? err.message : "Failed to encode WAV sample.");
    }
  }, [cleanupVoiceRecordingResources, update]);

  const startVoiceRecording = useCallback(async () => {
    setVoiceError("");
    voiceChunksRef.current = [];
    setVoiceRecordSec(0);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
          channelCount: 1,
          sampleRate: 24000,
        },
        video: false,
      });
      voiceStreamRef.current = stream;
      const AudioCtx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new AudioCtx({ sampleRate: 24000 });
      voiceAudioCtxRef.current = ctx;
      voiceSampleRateRef.current = ctx.sampleRate || 24000;

      const source = ctx.createMediaStreamSource(stream);
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      const silentGain = ctx.createGain();
      silentGain.gain.value = 0;
      processor.onaudioprocess = (ev) => {
        const input = ev.inputBuffer.getChannelData(0);
        voiceChunksRef.current.push(new Float32Array(input));
      };
      source.connect(processor);
      processor.connect(silentGain);
      silentGain.connect(ctx.destination);

      setVoiceRecording(true);
      const startedAt = Date.now();
      voiceTimerRef.current = window.setInterval(() => {
        const elapsed = Math.round(((Date.now() - startedAt) / 1000) * 10) / 10;
        setVoiceRecordSec(elapsed);
        if (elapsed >= 18) {
          stopVoiceRecording();
        }
      }, 200);
    } catch (err) {
      cleanupVoiceRecordingResources();
      setVoiceError(err instanceof Error ? err.message : "Unable to access microphone.");
    }
  }, [cleanupVoiceRecordingResources, stopVoiceRecording]);

  const wasOpenRef = useRef(false);
  const cleanupRef = useRef({
    stopCamera,
    stopVoiceRecording,
    cleanupVoiceRecordingResources,
  });
  cleanupRef.current = {
    stopCamera,
    stopVoiceRecording,
    cleanupVoiceRecordingResources,
  };

  useEffect(() => {
    if (!settingsOpen) {
      wasOpenRef.current = false;
      setModeLockFlash(null);
      cleanupRef.current.stopCamera();
      if (voiceStreamRef.current) {
        cleanupRef.current.stopVoiceRecording();
      } else {
        cleanupRef.current.cleanupVoiceRecordingResources();
      }
      return;
    }
    if (wasOpenRef.current) return;
    wasOpenRef.current = true;
    const id = requestAnimationFrame(() => {
      closeBtnRef.current?.focus();
    });
    return () => cancelAnimationFrame(id);
  }, [settingsOpen]);

  // Fetch actual backend tool configuration and server-composed prompt for the selected persona
  const [backendTools, setBackendTools] = useState<BackendToolDef[]>([]);
  const [backendToolsJson, setBackendToolsJson] = useState("");
  const [backendToolsTokens, setBackendToolsTokens] = useState(0);
  const [backendPrompt, setBackendPrompt] = useState("");
  const [toolsEditable, setToolsEditable] = useState(true);
  const [toolsDraft, setToolsDraft] = useState<string | null>(null);
  const [backendUrlError, setBackendUrlError] = useState<string | null>(null);
  const [customDetailsOpen, setCustomDetailsOpen] = useState<boolean>(() =>
    hasCustomBackendOrigin(settings.backendUrl, getDefaultBackendUrl()),
  );
  const [compressionDraft, setCompressionDraft] = useState<string>(
    String(Math.max(5000, settings.contextCompressionTokens ?? 5000)),
  );
  const compressionFocusedRef = useRef(false);

  useEffect(() => {
    setToolsDraft(null);
  }, [persona.id, settingsOpen]);

  useEffect(() => {
    if (!compressionFocusedRef.current) {
      setCompressionDraft(String(Math.max(5000, settings.contextCompressionTokens ?? 5000)));
    }
  }, [settings.contextCompressionTokens]);

  useEffect(() => {
    setCustomDetailsOpen((prev) => reconcileCustomDetailsOpen(prev, backendUrlError));
  }, [backendUrlError]);

  useEffect(() => {
    if (!settingsOpen) return;
    let promptUrl: string;
    try {
      promptUrl = buildPersonaPromptUrl(settings, currentPhase);
      setBackendUrlError(null);
    } catch (err) {
      setBackendUrlError(formatBackendUrlError(err));
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(() => {
      fetch(promptUrl)
        .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
        .then(
          (data: {
            prompt?: string;
            tools?: BackendToolDef[];
            tools_token_count?: number;
            tools_editable?: boolean;
          }) => {
            if (cancelled) return;
            setToolsEditable(data.tools_editable !== false);
            setBackendPrompt(data.prompt?.trim() ?? "");
            if (Array.isArray(data.tools)) {
              setBackendTools(data.tools);
              const formatted = JSON.stringify(data.tools, null, 2);
              setBackendToolsJson(formatted);
              setBackendToolsTokens(data.tools_token_count ?? estimateTokens(formatted));
            } else {
              setBackendTools([]);
              setBackendToolsJson("[]");
              setBackendToolsTokens(0);
            }
          },
        )
        .catch(() => {
          if (!cancelled) {
            setToolsEditable(true);
            setBackendTools([]);
            setBackendToolsJson("");
            setBackendToolsTokens(0);
          }
        });
    }, 220);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [settingsOpen, settings.personaId, settings.engine, settings.model, settings.backendUrl, settings.tone, settings.language, currentPhase]);

  const syncBodyOverflow = useCallback(() => {
    const el = bodyRef.current;
    if (!el) return;
    setBodyOverflowing(el.scrollTop + el.clientHeight < el.scrollHeight - 4);
  }, []);

  useEffect(() => {
    if (!settingsOpen) return;
    syncBodyOverflow();
    const id = requestAnimationFrame(syncBodyOverflow);
    return () => cancelAnimationFrame(id);
  }, [settingsOpen, settings.engine, settings.avatarEnabled, settings.voice, settings.ttsModel, syncBodyOverflow]);

  if (!settingsOpen) return null;

  const effectivePresetPrompt = backendPrompt || getPersonaPrompt(persona, settings.tone) || "";
  const displayedInstructions = settings.instructions || effectivePresetPrompt;
  const instructionTokens = estimateTokens(displayedInstructions);

  const activeToolsOverride = toolsEditable
    ? toolsDraft !== null
      ? toolsDraft
      : settings.toolsJson
    : "";

  const effectiveToolsText = !toolsEditable
    ? backendToolsJson
    : toolsDraft !== null
      ? toolsDraft
      : settings.toolsJson?.trim()
        ? settings.toolsJson
        : backendToolsJson;
  const effectiveToolsTokens =
    toolsEditable && activeToolsOverride?.trim()
      ? estimateTokens(activeToolsOverride)
      : backendToolsTokens;

  const toolsValidationError = (() => {
    if (!toolsEditable || !activeToolsOverride?.trim()) return null;
    try {
      parseToolsOverride(activeToolsOverride);
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : "Invalid tool definitions JSON";
    }
  })();

  const effectiveToolCount = (() => {
    if (toolsEditable && activeToolsOverride?.trim()) {
      try {
        return parseToolsOverride(activeToolsOverride).length;
      } catch {
        return backendTools.length;
      }
    }
    return backendTools.length;
  })();

  const closeModal = () => {
    setSettingsOpen(false);
    requestAnimationFrame(() => {
      document.getElementById("btn-settings")?.focus();
    });
  };

  const handleEngineSwitch = (target: "live" | "cascade") => {
    if (target === settings.engine) return;
    if (active) {
      setModeLockFlash("End or restart the active call to switch engine mode.");
      return;
    }
    setModeLockFlash(null);
    chooseEngine(target);
    if (bodyRef.current) bodyRef.current.scrollTop = 0;
  };

  const handleModeTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    if (active) {
      setModeLockFlash("End or restart the active call to switch engine mode.");
      return;
    }
    const next = settings.engine === "live" ? "cascade" : "live";
    handleEngineSwitch(next);
    const nextId = next === "live" ? "cfg-mode-live" : "cfg-mode-cascade";
    document.getElementById(nextId)?.focus();
  };

  const handleStartOrRestart = async () => {
    if (active) {
      await endSession();
      setSettingsOpen(false);
      await startBackend(settings.engine);
    } else {
      await startBackend(settings.engine);
    }
  };

  const isChirpTts = settings.ttsModel === "google-tts";
  const canSkipStt = supportsCascadeAudioInput(settings.llmModel);
  const liveCard = isLivePricingEligible(settings.engine, settings.model)
    ? getLiveRateCard(settings.model)
    : null;
  const castRole = getPersonaCastRole(persona);
  const vadValue: VadMode = settings.vadMode ?? (settings.vad === false ? "gemini" : "both");

  return (
    <div
      className="modal-backdrop"
      id="settings-scrim"
      onClick={(e) => {
        if (e.target === e.currentTarget) closeModal();
      }}
    >
      <div
        className={`settings-dialog ${isWide ? "is-wide" : ""}`}
        id="settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
      >
        <div className="cfg-header">
          <div className="cfg-header-top">
            <h2 className="cfg-title" id="settings-title">
              Session configuration
            </h2>
            <div className="cfg-head-actions">
              <button
                type="button"
                className="ghost-btn"
                id="btn-settings-expand"
                aria-pressed={isWide}
                onClick={() => setIsWide((v) => !v)}
              >
                <ExpandIcon />
                <span>Wide view</span>
              </button>
              <button
                ref={closeBtnRef}
                type="button"
                className="ghost-btn"
                id="btn-settings-close"
                aria-label="Close"
                onClick={closeModal}
              >
                <CloseIcon />
              </button>
            </div>
          </div>

          <div className="segmented-control cfg-mode-tabs" role="tablist" aria-label="Engine mode">
            <button
              type="button"
              role="tab"
              id="cfg-mode-live"
              aria-controls="cfg-tabpanel"
              className="seg-btn"
              aria-selected={isLive}
              aria-disabled={active && isCascade ? true : undefined}
              tabIndex={isLive ? 0 : -1}
              onClick={() => handleEngineSwitch("live")}
              onKeyDown={handleModeTabKeyDown}
            >
              Gemini 3.8 Live
            </button>
            <button
              type="button"
              role="tab"
              id="cfg-mode-cascade"
              aria-controls="cfg-tabpanel"
              className="seg-btn"
              aria-selected={isCascade}
              aria-disabled={active && isLive ? true : undefined}
              tabIndex={isCascade ? 0 : -1}
              onClick={() => handleEngineSwitch("cascade")}
              onKeyDown={handleModeTabKeyDown}
            >
              Cascade STT · TTS
            </button>
          </div>
        </div>

        {active && (
          <div className="cfg-readonly-banner" role="status">
            {modeLockFlash ??
              "Session in progress: Engine mode is locked during a live call. Parameter updates apply on restart."}
          </div>
        )}

        <div
          ref={bodyRef}
          className={`cfg-body scroll-area ${bodyOverflowing ? "is-overflowing-y" : ""}`}
          id="cfg-tabpanel"
          role="tabpanel"
          aria-labelledby={isCascade ? "cfg-mode-cascade" : "cfg-mode-live"}
          onScroll={syncBodyOverflow}
        >
          {isLive ? (
            <>
              <section className="cfg-group">
                <h3 className="cfg-group-title">Gemini Live Engine</h3>
                <div className="cfg-field">
                  <label htmlFor="cfg-live-model">Live Model</label>
                  <select
                    id="cfg-live-model"
                    className="cfg-select"
                    value={settings.model}
                    disabled={active}
                    onChange={(e) => update("model", e.target.value)}
                  >
                    {LIVE_MODEL_GROUPS.map((group) => (
                      <optgroup key={group.label} label={group.label}>
                        {group.options.map(([val, lbl]) => (
                          <option key={val} value={val}>
                            {lbl}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </div>

                {liveCard && (
                  <div className="cfg-rate-strip" role="group" aria-label="Selected model token rates">
                    <div className="cfg-rate-item">
                      <span className="k">Audio In</span>
                      <span className="v">${liveCard.audioInPerMillion.toFixed(2)}/1M</span>
                    </div>
                    <div className="cfg-rate-item">
                      <span className="k">Audio Out</span>
                      <span className="v">${liveCard.audioOutPerMillion.toFixed(2)}/1M</span>
                    </div>
                    <div className="cfg-rate-item">
                      <span className="k">Text In</span>
                      <span className="v">${liveCard.textInPerMillion.toFixed(2)}/1M</span>
                    </div>
                    <div className="cfg-rate-item">
                      <span className="k">Text Out</span>
                      <span className="v">${liveCard.textOutPerMillion.toFixed(2)}/1M</span>
                    </div>
                  </div>
                )}

                <div className="cfg-grid-2">
                  <div className="cfg-field">
                    <label htmlFor="cfg-live-voice">Voice</label>
                    <select
                      id="cfg-live-voice"
                      className="cfg-select"
                      value={settings.voice}
                      disabled={active}
                      onChange={(e) => {
                        const nextVoice = e.target.value;
                        update("voice", nextVoice);
                        if (isGeminiClonedVoice(nextVoice) || isLiveCustomVoice(nextVoice)) {
                          update("model", "gemini-3.8-live");
                        }
                      }}
                    >
                      {GEMINI_VOICES.map(([val, lbl]) => (
                        <option key={val} value={val}>
                          {lbl}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="cfg-field">
                    <label htmlFor="cfg-language">Language</label>
                    <select
                      id="cfg-language"
                      className="cfg-select"
                      value={settings.language}
                      disabled={active}
                      onChange={(e) => update("language", e.target.value)}
                    >
                      {LANGUAGE_OPTIONS.map(([val, lbl]) => (
                        <option key={val} value={val}>
                          {lbl}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {settings.voice === "Gemini-Clone-Male" && (
                  <div className="cfg-subcard">
                    <div className="cfg-subcard-head">
                      <span className="cfg-subcard-title">
                        Manish · Gemini 3.8 Live Voice Clone (24 kHz 16-bit mono WAV)
                      </span>
                      <span className="mono-pill">ReplicatedVoiceConfig</span>
                    </div>
                    <p className="cfg-help">
                      Uses the pre-bundled 24 kHz 16-bit mono reference WAV natively on google/gemini-3.8-live.
                    </p>
                  </div>
                )}

                {settings.voice === "Custom-Live-Voice" && (
                  <div className="cfg-subcard">
                    <div className="cfg-subcard-head">
                      <span className="cfg-subcard-title">
                        Zero-Shot Voice Clone (10-20s Reference Audio)
                      </span>
                      <span className="mono-pill">ReplicatedVoiceConfig</span>
                    </div>
                    <p className="cfg-help">
                      Read aloud for 10 to 20 seconds in a quiet room: &ldquo;{VOICE_CLONE_READING_SCRIPT}&rdquo;
                    </p>
                    <div className="cfg-btn-row">
                      {!voiceRecording ? (
                        <button
                          type="button"
                          className="ghost-btn"
                          id="cfg-record-voice"
                          aria-pressed={false}
                          disabled={active}
                          onClick={() => void startVoiceRecording()}
                        >
                          <MicOnIcon />
                          <span>
                            {settings.customVoiceAudio
                              ? "Re-record 10-20s sample"
                              : "Record 10-20s sample"}
                          </span>
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="ghost-btn warn"
                          id="cfg-record-voice"
                          aria-pressed={true}
                          onClick={stopVoiceRecording}
                        >
                          <StopSampleIcon />
                          <span>Stop recording ({voiceRecordSec.toFixed(1)}s)</span>
                        </button>
                      )}

                      <button
                        type="button"
                        className="ghost-btn"
                        id="cfg-upload-voice-btn"
                        disabled={active || voiceRecording}
                        onClick={() => voiceUploadInputRef.current?.click()}
                      >
                        Upload WAV / MP3
                      </button>
                      <input
                        ref={voiceUploadInputRef}
                        type="file"
                        id="cfg-upload-voice-file"
                        accept="audio/wav,audio/x-wav,audio/mpeg,audio/mp3,audio/mp4,audio/x-m4a,audio/webm,audio/ogg,.wav,.mp3,.m4a"
                        hidden
                        onChange={async (e) => {
                          const file = e.currentTarget.files?.[0];
                          e.currentTarget.value = "";
                          if (!file) return;
                          try {
                            setVoiceError("");
                            const { dataUrl, durationSec, byteLength } =
                              await normalizeUploadedVoiceAudioFile(file);
                            update("customVoiceAudio", dataUrl);
                            update("model", "gemini-3.8-live");
                            setVoiceMetaNote(
                              `24 kHz · 16-bit mono WAV · ${durationSec.toFixed(1)}s (${Math.round(byteLength / 1024)} KB)`,
                            );
                          } catch (err) {
                            setVoiceError(
                              err instanceof Error ? err.message : "Failed to normalize audio file.",
                            );
                          }
                        }}
                      />

                      {settings.customVoiceAudio && (
                        <button
                          type="button"
                          className="ghost-btn"
                          disabled={active}
                          onClick={() => {
                            update("customVoiceAudio", "");
                            setVoiceMetaNote("");
                          }}
                        >
                          Clear sample
                        </button>
                      )}
                    </div>

                    {voiceError && <p className="cfg-error-note">{voiceError}</p>}

                    {settings.customVoiceAudio && (
                      <div className="cfg-audio-row">
                        <span className="mono-pill">
                          {voiceMetaNote || "24 kHz 16-bit Mono WAV"}
                        </span>
                        <audio
                          className="cfg-audio-preview"
                          controls
                          src={settings.customVoiceAudio}
                        />
                      </div>
                    )}
                  </div>
                )}

                {settings.voice === "Custom-Key" && (
                  <div className="cfg-subcard">
                    <div className="cfg-subcard-head">
                      <span className="cfg-subcard-title">Custom Voice Cloning Key</span>
                      <span className="mono-pill">Cloud TTS Clone</span>
                    </div>
                    <div className="cfg-field">
                      <label htmlFor="cfg-voice-key">Voice Key</label>
                      <input
                        type="password"
                        id="cfg-voice-key"
                        className="cfg-input"
                        autoComplete="off"
                        placeholder="Paste voice_key or projects/.../voices/my-voice"
                        value={settings.customVoiceKey ?? ""}
                        disabled={active}
                        onChange={(e) => update("customVoiceKey", e.target.value)}
                      />
                    </div>
                  </div>
                )}

                {usesExternalTts(settings) && (
                  <div className="cfg-field">
                    <div className="cfg-label-row">
                      <label htmlFor="cfg-tts-pace-live">Speaking rate</label>
                      <span className="mono-pill">{(settings.ttsPace ?? 1.0).toFixed(2)}x</span>
                    </div>
                    <input
                      type="range"
                      id="cfg-tts-pace-live"
                      className="cfg-range"
                      min="0.25"
                      max="2.0"
                      step="0.05"
                      value={settings.ttsPace ?? 1.0}
                      disabled={active}
                      onChange={(e) => updateNumber("ttsPace", parseFloat(e.target.value))}
                    />
                  </div>
                )}
              </section>

              <section className="cfg-group">
                <div className="cfg-card-head">
                  <div>
                    <div className="cfg-card-title-row">
                      <h3 className="cfg-group-title" id="cfg-avatar-heading">
                        Gemini 3.8 Live Avatar
                      </h3>
                      <span className="mono-pill">704×1280 · 24fps</span>
                    </div>
                    <p className="cfg-help">
                      Stream a real-time lip-synced Vertex AI video portrait alongside native audio.
                    </p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    id="cfg-avatar-switch"
                    className="switch-btn"
                    aria-checked={Boolean(settings.avatarEnabled)}
                    aria-labelledby="cfg-avatar-heading"
                    disabled={active}
                    onClick={() => {
                      const nextVal = !settings.avatarEnabled;
                      updateBool("avatarEnabled", nextVal);
                      if (nextVal) update("model", "gemini-3.8-live");
                    }}
                  >
                    <span className="switch-track" aria-hidden="true">
                      <span className="switch-thumb" />
                    </span>
                  </button>
                </div>

                {settings.avatarEnabled && (
                  <>
                    <div className="cfg-avatar-grid" role="group" aria-label="Avatar character">
                      {AVATAR_CHARACTERS.map((ch) => {
                        const selected = (settings.avatarName || "auto") === ch.id;
                        return (
                          <button
                            key={ch.id}
                            type="button"
                            id={`cfg-char-${ch.id}`}
                            className="cfg-char-btn"
                            aria-pressed={selected}
                            disabled={active}
                            onClick={() => update("avatarName", ch.id)}
                          >
                            <span className="cfg-char-name">{ch.name}</span>
                            <span className="cfg-char-sub">{ch.badge}</span>
                          </button>
                        );
                      })}
                    </div>

                    {settings.avatarName === "custom" && (
                      <div className="cfg-subcard">
                        <div className="cfg-subcard-head">
                          <span className="cfg-subcard-title">
                            Custom Portrait (704×1280 9:16 RGB PNG)
                          </span>
                          <span className="mono-pill">customized_avatar</span>
                        </div>
                        <p className="cfg-help">
                          Capture from your webcam or upload any portrait photo. Automatically cropped and normalized to 704×1280 PNG.
                        </p>
                        <div className="cfg-btn-row">
                          {!cameraOpen ? (
                            <button
                              type="button"
                              className="ghost-btn"
                              disabled={avatarProcessing}
                              onClick={() => void startCamera()}
                            >
                              Take photo (Camera)
                            </button>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="ghost-btn"
                                onClick={snapCameraPhoto}
                              >
                                Snap photo &amp; start
                              </button>
                              <button
                                type="button"
                                className="ghost-btn"
                                onClick={stopCamera}
                              >
                                Close camera
                              </button>
                            </>
                          )}

                          <button
                            type="button"
                            className="ghost-btn"
                            disabled={avatarProcessing}
                            onClick={() => avatarUploadInputRef.current?.click()}
                          >
                            {avatarProcessing
                              ? "Processing portrait..."
                              : settings.avatarCustomImage
                                ? "Replace portrait"
                                : "Upload portrait"}
                          </button>
                          <input
                            ref={avatarUploadInputRef}
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            hidden
                            onChange={async (e) => {
                              const file = e.currentTarget.files?.[0];
                              e.currentTarget.value = "";
                              if (!file) return;
                              try {
                                setCameraError("");
                                setAvatarProcessing(true);
                                const { dataUrl } = await normalizeAvatarPortraitFile(file);
                                await applyCustomAvatarAndStart(dataUrl);
                              } catch (err) {
                                setCameraError(
                                  err instanceof Error ? err.message : "Failed to process portrait.",
                                );
                              } finally {
                                setAvatarProcessing(false);
                              }
                            }}
                          />

                          {settings.avatarCustomImage && (
                            <button
                              type="button"
                              className="ghost-btn"
                              disabled={active}
                              onClick={() => update("avatarCustomImage", "")}
                            >
                              Clear portrait
                            </button>
                          )}
                        </div>

                        {cameraError && <p className="cfg-error-note">{cameraError}</p>}

                        {cameraOpen && (
                          <div className="cfg-webcam-box">
                            <video
                              ref={bindCameraVideo}
                              autoPlay
                              playsInline
                              muted
                              className="cfg-webcam-video"
                              onClick={snapCameraPhoto}
                            />
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </section>
            </>
          ) : (
            <section className="cfg-group">
              <h3 className="cfg-group-title">Cascade Engine</h3>

              <div className="cfg-field">
                <label htmlFor="cfg-stt-model">1. Speech Recognition (STT)</label>
                <select
                  id="cfg-stt-model"
                  className="cfg-select"
                  value={settings.sttModel}
                  disabled={active || (Boolean(settings.skipStt) && canSkipStt)}
                  onChange={(e) => update("sttModel", e.target.value)}
                >
                  {CASCADE_STT_MODEL_GROUPS.map((group) => (
                    <optgroup key={group.label} label={group.label}>
                      {group.options.map(([val, lbl]) => (
                        <option key={val} value={val}>
                          {lbl}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>

              <div className="cfg-switch-row">
                <div>
                  <div className="cfg-switch-label" id="lbl-skip-stt">
                    Skip STT (Send audio directly to LLM)
                  </div>
                  <div className="cfg-help">
                    {!canSkipStt
                      ? "Selected LLM accepts text input only; STT is required."
                      : "Stream 16 kHz PCM audio directly into Gemini Flash without a separate STT hop."}
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  id="cfg-skip-stt"
                  className="switch-btn"
                  aria-checked={Boolean(settings.skipStt) && canSkipStt}
                  aria-labelledby="lbl-skip-stt"
                  disabled={active || !canSkipStt}
                  onClick={() => updateBool("skipStt", !settings.skipStt)}
                >
                  <span className="switch-track" aria-hidden="true">
                    <span className="switch-thumb" />
                  </span>
                </button>
              </div>

              <div className="cfg-field">
                <label htmlFor="cfg-llm-model">2. Language Model (LLM)</label>
                <select
                  id="cfg-llm-model"
                  className="cfg-select"
                  value={settings.llmModel}
                  disabled={active}
                  onChange={(e) => {
                    const nextLlm = e.target.value;
                    update("llmModel", nextLlm);
                    if (!supportsCascadeAudioInput(nextLlm) && settings.skipStt) {
                      updateBool("skipStt", false);
                    }
                  }}
                >
                  {CASCADE_LLM_MODEL_GROUPS.map((group) => (
                    <optgroup key={group.label} label={group.label}>
                      {group.options.map(([val, lbl]) => (
                        <option key={val} value={val}>
                          {lbl}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>

              <div className="cfg-field">
                <label htmlFor="cfg-tts-model">3. Voice Model (TTS)</label>
                <select
                  id="cfg-tts-model"
                  className="cfg-select"
                  value={settings.ttsModel}
                  disabled={active}
                  onChange={(e) => update("ttsModel", e.target.value)}
                >
                  {CASCADE_TTS_MODEL_GROUPS.map((group) => (
                    <optgroup key={group.label} label={group.label}>
                      {group.options.map(([val, lbl]) => (
                        <option key={val} value={val}>
                          {lbl}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>

              <div className="cfg-grid-2">
                <div className="cfg-field">
                  <label htmlFor="cfg-cascade-voice">
                    {isChirpTts ? "Chirp 3 HD Voice Options" : "Gemini TTS Voice"}
                  </label>
                  <select
                    id="cfg-cascade-voice"
                    className="cfg-select"
                    value={settings.voice}
                    disabled={active}
                    onChange={(e) => update("voice", e.target.value)}
                  >
                    {isChirpTts ? (
                      CHIRP_HD_VOICES.map(([val, lbl]) => (
                        <option key={val} value={val}>
                          {lbl}
                        </option>
                      ))
                    ) : (
                      <>
                        <optgroup label="Gemini Standard & Cloned Voices">
                          {[
                            ...(supportsGeminiClone(settings.ttsModel) ? GEMINI_CLONE_VOICES : []),
                            ...GEMINI_VOICES.filter(
                              ([v]) => !v.startsWith("Custom") && !isGeminiClonedVoice(v),
                            ),
                          ].map(([val, lbl]) => (
                            <option key={val} value={val}>
                              {lbl}
                            </option>
                          ))}
                        </optgroup>
                        {supportsGeminiClone(settings.ttsModel) && (
                          <optgroup label="Indian English · Extended Voice Library">
                            {GEMINI_38_LIBRARY_VOICES.map(([val, lbl]) => (
                              <option key={val} value={val}>
                                {lbl}
                              </option>
                            ))}
                          </optgroup>
                        )}
                      </>
                    )}
                  </select>
                </div>

                <div className="cfg-field">
                  <label htmlFor="cfg-language">Language</label>
                  <select
                    id="cfg-language"
                    className="cfg-select"
                    value={settings.language}
                    disabled={active}
                    onChange={(e) => update("language", e.target.value)}
                  >
                    {LANGUAGE_OPTIONS.map(([val, lbl]) => (
                      <option key={val} value={val}>
                        {lbl}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {isChirpTts && settings.voice === "Custom-Key" && (
                <div className="cfg-subcard">
                  <div className="cfg-subcard-head">
                    <span className="cfg-subcard-title">Custom Voice Cloning Key</span>
                    <span className="mono-pill">Cloud TTS Clone</span>
                  </div>
                  <div className="cfg-field">
                    <label htmlFor="cfg-voice-key-cascade">Voice Key</label>
                    <input
                      type="password"
                      id="cfg-voice-key-cascade"
                      className="cfg-input"
                      autoComplete="off"
                      placeholder="Paste voice_key or projects/.../voices/my-voice"
                      value={settings.customVoiceKey ?? ""}
                      disabled={active}
                      onChange={(e) => update("customVoiceKey", e.target.value)}
                    />
                  </div>
                </div>
              )}

              {!isChirpTts && (
                <div className="cfg-voice-design-card">
                  <div className="cfg-vd-head">
                    <span className="cfg-vd-title">Voice Design &amp; Speaker Settings</span>
                    <span className="mono-pill">
                      {settings.ttsModel === "gemini-3.8-flash-tts"
                        ? "$0.50 / 1M in · $9.00 / 1M audio out"
                        : settings.ttsModel === "gemini-3.8-flash-lite-tts"
                          ? "$0.50 / 1M in · $6.00 / 1M audio out"
                          : "Vertex AI Gemini TTS"}
                    </span>
                  </div>
                  <div className="cfg-grid-2">
                    <div className="cfg-field">
                      <label htmlFor="cfg-tts-style">Style</label>
                      <select
                        id="cfg-tts-style"
                        className="cfg-select"
                        value={settings.ttsStyle ?? "Empathetic"}
                        disabled={active}
                        onChange={(e) => update("ttsStyle", e.target.value)}
                      >
                        {TTS_STYLE_OPTIONS.map(([val, lbl]) => (
                          <option key={val} value={val}>
                            {lbl}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="cfg-field">
                      <label htmlFor="cfg-tts-pace-label">Pace</label>
                      <select
                        id="cfg-tts-pace-label"
                        className="cfg-select"
                        value={settings.ttsPaceLabel ?? "Natural"}
                        disabled={active}
                        onChange={(e) => update("ttsPaceLabel", e.target.value)}
                      >
                        {TTS_PACE_OPTIONS.map(([val, lbl]) => (
                          <option key={val} value={val}>
                            {lbl}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="cfg-field">
                      <label htmlFor="cfg-tts-accent">Accent</label>
                      <select
                        id="cfg-tts-accent"
                        className="cfg-select"
                        value={settings.ttsAccent ?? "Indian"}
                        disabled={
                          active ||
                          (supportsGeminiClone(settings.ttsModel) &&
                            (isLibraryVoice(settings.voice) || isGeminiClonedVoice(settings.voice)))
                        }
                        onChange={(e) => update("ttsAccent", e.target.value)}
                      >
                        {TTS_ACCENT_OPTIONS.map(([val, lbl]) => (
                          <option key={val} value={val}>
                            {lbl}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="cfg-field">
                      <label htmlFor="cfg-tts-pitch">Pitch</label>
                      <select
                        id="cfg-tts-pitch"
                        className="cfg-select"
                        value={settings.ttsPitch ?? "Default"}
                        disabled={active}
                        onChange={(e) => update("ttsPitch", e.target.value)}
                      >
                        {TTS_PITCH_OPTIONS.map(([val, lbl]) => (
                          <option key={val} value={val}>
                            {lbl}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {!supportsGeminiClone(settings.ttsModel) && (
                    <div className="cfg-field">
                      <label htmlFor="cfg-tts-voice-prompt">
                        Persona Voice Design Prompt (Vertex 2.5 / 3.1 TTS)
                      </label>
                      <textarea
                        id="cfg-tts-voice-prompt"
                        className="cfg-textarea"
                        rows={2}
                        disabled={active}
                        placeholder="Automatically populated from persona, or customize here."
                        value={settings.ttsVoicePrompt ?? ""}
                        onChange={(e) => update("ttsVoicePrompt", e.target.value)}
                      />
                    </div>
                  )}

                  <p className="cfg-help">
                    Auto-matched to {castRole}. Tune delivery style, pace, accent, and pitch for Gemini TTS.
                  </p>
                </div>
              )}

              <div className="cfg-field">
                <div className="cfg-label-row">
                  <label htmlFor="cfg-tts-pace">Speaking rate</label>
                  <span className="mono-pill" id="cfg-pace-val">
                    {(settings.ttsPace ?? 1.0).toFixed(2)}x
                  </span>
                </div>
                <input
                  type="range"
                  id="cfg-tts-pace"
                  className="cfg-range"
                  min="0.25"
                  max="2.0"
                  step="0.05"
                  value={settings.ttsPace ?? 1.0}
                  disabled={active}
                  onChange={(e) => updateNumber("ttsPace", parseFloat(e.target.value))}
                />
              </div>
            </section>
          )}

          <section className="cfg-group">
            <h3 className="cfg-group-title">Agent Persona &amp; Instructions</h3>

            {!custom && persona.signaturePrompt && (
              <div className="cfg-field">
                <span className="cfg-label-text">Persona Tone</span>
                <div className="cfg-tone-row" role="group" aria-label="Persona tone">
                  <button
                    type="button"
                    id="cfg-tone-pro"
                    className="cfg-tone-btn"
                    aria-pressed={settings.tone === "professional"}
                    disabled={active || Boolean(settings.instructions)}
                    onClick={() => update("tone", "professional" as PersonaTone)}
                  >
                    Professional (default)
                  </button>
                  <button
                    type="button"
                    id="cfg-tone-sig"
                    className="cfg-tone-btn"
                    aria-pressed={settings.tone === "signature"}
                    disabled={active || Boolean(settings.instructions)}
                    onClick={() => update("tone", "signature" as PersonaTone)}
                  >
                    Signature ({persona.agentName} in character)
                  </button>
                </div>
              </div>
            )}

            <div className="cfg-field">
              <div className="cfg-label-row">
                <span className="cfg-label-left">
                  <label htmlFor="cfg-instructions">
                    {custom ? "System Instructions" : "Persona Instructions"}
                  </label>
                  <span className="mono-pill" id="cfg-tok-pill">
                    {instructionTokens.toLocaleString()} / 4,000 tok
                  </span>
                </span>
                {settings.instructions && (
                  <button
                    type="button"
                    className="ghost-btn"
                    id="cfg-restore-prompt"
                    disabled={active}
                    onClick={() => update("instructions", "")}
                  >
                    {custom ? "Use backend default" : "Restore preset"}
                  </button>
                )}
              </div>
              <textarea
                id="cfg-instructions"
                className="cfg-textarea"
                rows={4}
                maxLength={16000}
                disabled={active}
                placeholder={
                  custom
                    ? "Leave blank to use your backend default system instructions."
                    : effectivePresetPrompt
                }
                value={displayedInstructions}
                onFocus={() => {
                  if (!custom && !settings.instructions && effectivePresetPrompt) {
                    update("instructions", effectivePresetPrompt);
                  }
                }}
                onChange={(e) => update("instructions", e.target.value)}
              />
            </div>
          </section>

          <section className="cfg-group">
            <h3 className="cfg-group-title">Advanced Configuration</h3>

            <div className="cfg-field">
              <label htmlFor="cfg-vad-mode">Voice Activity Detection (VAD) Mode</label>
              <select
                id="cfg-vad-mode"
                className="cfg-select"
                value={vadValue}
                disabled={active}
                onChange={(e) => {
                  const nextMode = e.target.value as VadMode;
                  update("vadMode", nextMode);
                  updateBool("vad", nextMode !== "gemini");
                }}
              >
                {VAD_MODES.map(([val, lbl]) => (
                  <option key={val} value={val}>
                    {lbl}
                  </option>
                ))}
              </select>
            </div>

            {isLive && (
              <>
                <div className="cfg-switch-row">
                  <div>
                    <div className="cfg-switch-label" id="lbl-use-tts">
                      Use TTS for output modality
                    </div>
                    <div className="cfg-help">
                      Request text output from Gemini Live and synthesize audio with Chirp 3 HD or Gemini TTS.
                    </div>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    id="cfg-use-tts"
                    className="switch-btn"
                    aria-checked={Boolean(settings.tts)}
                    aria-labelledby="lbl-use-tts"
                    disabled={active}
                    onClick={() => updateBool("tts", !settings.tts)}
                  >
                    <span className="switch-track" aria-hidden="true">
                      <span className="switch-thumb" />
                    </span>
                  </button>
                </div>

                <div className="cfg-switch-row">
                  <div>
                    <div className="cfg-switch-label" id="lbl-compression">
                      Context Compression (SlidingWindow)
                    </div>
                    <div className="cfg-help">
                      Automatically compress older conversation turns once session context crosses threshold.
                    </div>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    id="cfg-compression"
                    className="switch-btn"
                    aria-checked={Boolean(settings.contextCompression)}
                    aria-labelledby="lbl-compression"
                    disabled={active}
                    onClick={() => updateBool("contextCompression", !settings.contextCompression)}
                  >
                    <span className="switch-track" aria-hidden="true">
                      <span className="switch-thumb" />
                    </span>
                  </button>
                </div>

                {settings.contextCompression && (
                  <div className="cfg-field">
                    <label htmlFor="cfg-compression-tokens">
                      Trigger Tokens Threshold (min 5,000)
                    </label>
                    <input
                      type="number"
                      id="cfg-compression-tokens"
                      className="cfg-input"
                      min={5000}
                      step={500}
                      disabled={active}
                      value={compressionDraft}
                      onFocus={() => {
                        compressionFocusedRef.current = true;
                      }}
                      onChange={(e) => {
                        const raw = e.target.value;
                        setCompressionDraft(raw);
                        const trimmed = raw.trim();
                        if (trimmed !== "") {
                          const num = Number(trimmed);
                          if (Number.isSafeInteger(num) && num >= 5000) {
                            updateNumber("contextCompressionTokens", num);
                          }
                        }
                      }}
                      onBlur={() => {
                        compressionFocusedRef.current = false;
                        const num = Number(compressionDraft.trim());
                        const clamped =
                          Number.isFinite(num) && num >= 5000 ? Math.round(num) : 5000;
                        setCompressionDraft(String(clamped));
                        updateNumber("contextCompressionTokens", clamped);
                      }}
                    />
                  </div>
                )}

                <div className="cfg-field">
                  <label htmlFor="cfg-thinking-level">
                    Gemini Live Thinking / Reasoning Level
                  </label>
                  <select
                    id="cfg-thinking-level"
                    className="cfg-select"
                    value={settings.thinkingLevel ?? "off"}
                    disabled={active}
                    onChange={(e) => update("thinkingLevel", e.target.value)}
                  >
                    {THINKING_LEVELS.map(([val, lbl]) => (
                      <option key={val} value={val}>
                        {lbl}
                      </option>
                    ))}
                  </select>
                </div>
              </>
            )}

            <div className="cfg-field">
              <div className="cfg-label-row">
                <span className="cfg-label-left">
                  <label htmlFor="cfg-tools-json">Dynamic Tool Definitions (JSON)</label>
                  <span className="mono-pill">
                    {effectiveToolCount} {effectiveToolCount === 1 ? "tool" : "tools"} ·{" "}
                    {effectiveToolsTokens.toLocaleString()} tok
                  </span>
                  {!toolsEditable && <span className="mono-pill">Managed per-card</span>}
                </span>
                {toolsEditable && (Boolean(settings.toolsJson) || toolsDraft !== null) && (
                  <button
                    type="button"
                    className="ghost-btn"
                    id="btn-restore-tools"
                    disabled={active}
                    onClick={() => {
                      setToolsDraft(null);
                      update("toolsJson", "");
                    }}
                  >
                    Restore backend tools
                  </button>
                )}
              </div>
              <textarea
                id="cfg-tools-json"
                className="cfg-textarea mono"
                rows={4}
                disabled={active || !toolsEditable}
                placeholder='[{"name": "lookup_order", "description": "Lookup order", "properties": {"id": {"type": "string"}}, "required": ["id"]}]'
                value={effectiveToolsText}
                onFocus={() => {
                  if (toolsEditable && toolsDraft === null) {
                    setToolsDraft(settings.toolsJson?.trim() ? settings.toolsJson : backendToolsJson);
                  }
                }}
                onChange={(e) => {
                  if (toolsEditable) {
                    setToolsDraft(e.target.value);
                    update("toolsJson", e.target.value);
                  }
                }}
              />
              {toolsValidationError && <p className="cfg-error-note">{toolsValidationError}</p>}
            </div>

            <details
              className="cfg-details"
              id="cfg-custom-details"
              open={customDetailsOpen}
              onToggle={(e) => setCustomDetailsOpen(e.currentTarget.open)}
            >
              <summary>
                <ChevronRightIcon className="pipe-arrow" />
                <span>Custom Server URL (Optional)</span>
              </summary>
              <div className="cfg-field">
                <label htmlFor="cfg-backend-url">Pipecat Backend WebSocket / HTTP Origin</label>
                <input
                  type="url"
                  id="cfg-backend-url"
                  className="cfg-input"
                  placeholder="http://localhost:7860"
                  disabled={active}
                  aria-invalid={Boolean(backendUrlError) || undefined}
                  aria-describedby={backendUrlError ? "cfg-backend-url-error" : undefined}
                  value={settings.backendUrl}
                  onChange={(e) => update("backendUrl", e.target.value)}
                />
                {backendUrlError && (
                  <p className="cfg-error-note" id="cfg-backend-url-error" role="alert">
                    {backendUrlError}
                  </p>
                )}
              </div>
            </details>
          </section>
        </div>

        <div className="cfg-footer">
          <span className="mono-pill">
            {castRole} · {formatVoiceShortLabel(settings.voice)} · {settings.language}
          </span>
          <div className="cfg-footer-btns">
            <button
              type="button"
              className="ghost-btn"
              id="btn-settings-done"
              onClick={closeModal}
            >
              Done
            </button>
            {active ? (
              <button
                type="button"
                className="ghost-btn"
                id="btn-settings-start"
                onClick={() => void handleStartOrRestart()}
              >
                Restart call with changes
              </button>
            ) : (
              <button
                type="button"
                className="cta cfg-cta"
                id="btn-settings-start"
                onClick={() => void handleStartOrRestart()}
              >
                <MicOnIcon />
                <span>{isCascade ? "Start Cascade call" : "Start Gemini Live"}</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
