import { useEffect, useState, useRef, useCallback } from "react";
import { Edit3, Mic, RotateCcw, DollarSign, Maximize2, Minimize2, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  LANGUAGE_OPTIONS,
  LIVE_MODELS,
  LIVE_MODEL_GROUPS,
  CASCADE_STT_MODELS,
  CASCADE_STT_MODEL_GROUPS,
  CASCADE_LLM_MODELS,
  CASCADE_LLM_MODEL_GROUPS,
  CASCADE_TTS_MODELS,
  CASCADE_TTS_MODEL_GROUPS,
  TTS_STYLE_OPTIONS,
  TTS_ACCENT_OPTIONS,
  TTS_PITCH_OPTIONS,
  TTS_PACE_OPTIONS,
  GEMINI_VOICES,
  CHIRP_HD_VOICES,
  THINKING_LEVELS,
  VAD_MODES,
  type VadMode,
  usesExternalTts,
  buildPersonaPromptUrl,
} from "@/lib/voice-session";
import { getPersonaPrompt, type PersonaTone } from "@/lib/personas";
import { isLivePricingEligible, getLiveRateCard, estimateTokens } from "@/lib/pricing";
import type { VoiceStudio } from "@/hooks/use-voice-session";

function Picker({
  label,
  value,
  options,
  groups,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly (readonly [string, string])[];
  groups?: readonly { label: string; options: readonly (readonly [string, string])[] }[];
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const id = label.toLowerCase().replaceAll(" ", "-");
  return (
    <div className="field">
      <label id={`${id}-label`}>{label}</label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger aria-labelledby={`${id}-label`} className="w-full min-w-0 select-trigger">
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper">
          {groups
            ? groups.map((group, idx) => (
                <SelectGroup key={group.label}>
                  {idx > 0 && <SelectSeparator />}
                  <SelectLabel>{group.label}</SelectLabel>
                  {group.options.map(([v, l]) => (
                    <SelectItem value={v} key={v}>
                      {l}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))
            : options.map(([v, l]) => (
                <SelectItem value={v} key={v}>
                  {l}
                </SelectItem>
              ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/** Every engine parameter the backend accepts, in one place, organized logically. */
export default function SettingsDialog({ studio }: { studio: VoiceStudio }) {
  const {
    active, custom, engineName, persona, settings, settingsOpen, setSettingsOpen,
    startBackend, update, updateBool, updateNumber, currentPhase,
  } = studio;

  const isLive = settings.engine === "live";

  // Resizable dialog width (drag left/right edge or click expand button)
  const [dialogWidth, setDialogWidth] = useState<number>(760);
  const [isExpanded, setIsExpanded] = useState<boolean>(false);
  const dragRef = useRef<{ startX: number; startWidth: number; side: "left" | "right" } | null>(null);

  const startResize = useCallback((side: "left" | "right", e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragRef.current = { startX: e.clientX, startWidth: dialogWidth, side };

    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const delta = ev.clientX - dragRef.current.startX;
      // Since dialog is centered (translateX(-50%)), dragging either edge outward by delta changes width by 2 * delta
      const signedDelta = dragRef.current.side === "right" ? delta * 2 : -delta * 2;
      const maxW = Math.min(1440, window.innerWidth * 0.96);
      const next = Math.max(520, Math.min(maxW, dragRef.current.startWidth + signedDelta));
      setDialogWidth(next);
      setIsExpanded(next >= 1000);
    };

    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [dialogWidth]);

  const toggleExpand = useCallback(() => {
    if (isExpanded) {
      setDialogWidth(760);
      setIsExpanded(false);
    } else {
      setDialogWidth(Math.min(1160, Math.floor(window.innerWidth * 0.94)));
      setIsExpanded(true);
    }
  }, [isExpanded]);

  // Fetch actual backend tool configuration and server-composed prompt for the selected persona
  const [backendTools, setBackendTools] = useState<any[]>([]);
  const [backendToolsJson, setBackendToolsJson] = useState<string>("");
  const [backendToolsTokens, setBackendToolsTokens] = useState<number>(0);
  const [backendPrompt, setBackendPrompt] = useState<string>("");

  useEffect(() => {
    if (!settingsOpen) return;
    let cancelled = false;
    fetch(buildPersonaPromptUrl(settings, currentPhase))
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data: { prompt?: string; tools?: any[]; tools_token_count?: number }) => {
        if (cancelled) return;
        if (data.prompt?.trim()) {
          setBackendPrompt(data.prompt.trim());
        } else {
          setBackendPrompt("");
        }
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
      })
      .catch(() => {
        if (!cancelled) {
          setBackendTools([]);
          setBackendToolsJson("");
          setBackendToolsTokens(0);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [settingsOpen, settings.personaId, settings.engine, settings.backendUrl, settings.tone, settings.language, currentPhase]);

  const effectivePresetPrompt = backendPrompt || getPersonaPrompt(persona, settings.tone);
  const effectiveToolsText = settings.toolsJson?.trim() ? settings.toolsJson : backendToolsJson;
  const effectiveToolsTokens = settings.toolsJson?.trim()
    ? estimateTokens(settings.toolsJson)
    : backendToolsTokens;
  const effectiveToolCount = (() => {
    if (settings.toolsJson?.trim()) {
      try {
        const parsed = JSON.parse(settings.toolsJson);
        return Array.isArray(parsed) ? parsed.length : 1;
      } catch {
        return backendTools.length;
      }
    }
    return backendTools.length;
  })();

  return (
    <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
      <DialogContent
        className="studio-dialog"
        style={{
          width: `min(${dialogWidth}px, 96vw)`,
          maxWidth: `min(${dialogWidth}px, 96vw)`,
        }}
      >
        {/* Left & Right Drag Handles to Expand/Shrink Settings Slider */}
        <div
          className="studio-dialog-resize-handle left"
          onMouseDown={(e) => startResize("left", e)}
          title="Drag left edge to resize dialog"
        />
        <div
          className="studio-dialog-resize-handle right"
          onMouseDown={(e) => startResize("right", e)}
          title="Drag right edge to resize dialog"
        />

        <DialogHeader>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingRight: "28px" }}>
            <DialogTitle>Session Configuration: {engineName}</DialogTitle>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={toggleExpand}
              title={isExpanded ? "Restore standard width" : "Expand dialog width"}
              aria-label={isExpanded ? "Restore standard width" : "Expand dialog width"}
              style={{ height: "28px", width: "28px", color: "#a7b4a4" }}
            >
              {isExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </Button>
          </div>
          <DialogDescription>
            {persona.name} · {engineName}. Configure voice, persona, and runtime parameters below. Drag side borders to widen.
          </DialogDescription>
        </DialogHeader>

        {/* Mid-call Inspection Read-Only Notice */}
        {active && (
          <div className="settings-active-call-banner" role="status">
            <span>🔒 <strong>Session in progress:</strong> Settings are read-only. Available to edit after this session ends.</span>
          </div>
        )}

        <div className="dialog-fields">
          {/* GROUP 1: ENGINE & PIPELINE (TOP OF SETTINGS: STT -> LLM -> TTS) */}
          <div className="settings-group">
            <h3 className="settings-section-title">{engineName} Engine</h3>

            {isLive ? (
              <>
                <Picker
                  label="Live Model"
                  value={settings.model}
                  disabled={active}
                  onChange={(value) => update("model", value)}
                  options={LIVE_MODELS}
                  groups={LIVE_MODEL_GROUPS}
                />

                {isLivePricingEligible(settings.engine, settings.model) && (() => {
                  const card = getLiveRateCard(settings.model);
                  if (!card) return null;
                  return (
                    <div className="live-pricing-callout">
                      <div className="pricing-callout-head">
                        <span className="pricing-badge-title">
                          <DollarSign size={12} /> {card.displayName} Pricing
                        </span>
                        <span className="pricing-est-pill">{card.estHourlyUSD}</span>
                      </div>
                      <div className="pricing-rate-grid">
                        <div className="pricing-rate-col">
                          <span className="rate-lbl">Audio In:</span>
                          <span className="rate-val">${card.audioInPerMillion.toFixed(2)}/1M tok</span>
                        </div>
                        <div className="pricing-rate-col">
                          <span className="rate-lbl">Audio Out:</span>
                          <span className="rate-val">${card.audioOutPerMillion.toFixed(2)}/1M tok</span>
                        </div>
                        <div className="pricing-rate-col">
                          <span className="rate-lbl">Text In:</span>
                          <span className="rate-val">${card.textInPerMillion.toFixed(2)}/1M tok</span>
                        </div>
                        <div className="pricing-rate-col">
                          <span className="rate-lbl">Text Out:</span>
                          <span className="rate-val">${card.textOutPerMillion.toFixed(2)}/1M tok</span>
                        </div>
                      </div>
                    </div>
                  );
                })()}

                <div className="settings-pair">
                  <Picker
                    label="Voice"
                    value={settings.voice}
                    disabled={active}
                    onChange={(value) => update("voice", value)}
                    options={GEMINI_VOICES}
                  />
                  <Picker
                    label="Language"
                    value={settings.language}
                    disabled={active}
                    onChange={(value) => update("language", value)}
                    options={LANGUAGE_OPTIONS}
                  />
                </div>

                {settings.voice === "Custom-Key" && (
                  <div className="field" style={{ marginTop: "4px" }}>
                    <label htmlFor="settings-custom-voice-key">Custom Voice Key / Replicated ID</label>
                    <Input
                      id="settings-custom-voice-key"
                      type="password"
                      autoComplete="off"
                      placeholder="e.g. projects/.../voices/my-voice or voice_key"
                      value={settings.customVoiceKey ?? ""}
                      disabled={active}
                      onChange={(e) => update("customVoiceKey", e.target.value)}
                    />
                    <p className="field-hint">Enter your EAP Voice Replication Key or cloned voice identifier.</p>
                  </div>
                )}

                {settings.voice.startsWith("Custom") && (
                  <div style={{ padding: "8px 12px", background: "rgba(245, 158, 11, 0.1)", border: "1px solid rgba(245, 158, 11, 0.25)", borderRadius: "8px", fontSize: "12px", color: "#fbbf24", marginBottom: "8px" }}>
                    ℹ️ <strong>Custom Voice Mode:</strong> Synthesized via Google Cloud TTS voice cloning pipeline.
                  </div>
                )}

                {usesExternalTts(settings) && (
                  <div className="settings-slider-field">
                    <div className="slider-label-row">
                      <label htmlFor="settings-pace-slider-live">Speaking Rate Multiplier (Numeric)</label>
                      <span className="slider-val">{(settings.ttsPace ?? 1.0).toFixed(2)}x</span>
                    </div>
                    <input
                      id="settings-pace-slider-live"
                      type="range"
                      min="0.25"
                      max="2.0"
                      step="0.05"
                      value={settings.ttsPace ?? 1.0}
                      disabled={active}
                      onChange={(e) => updateNumber("ttsPace", parseFloat(e.target.value))}
                      className="range-slider"
                    />
                  </div>
                )}
              </>
            ) : (
              <>
                {/* 1. STT */}
                <Picker
                  label="1. Speech Recognition (STT)"
                  value={settings.sttModel}
                  disabled={active}
                  onChange={(value) => update("sttModel", value)}
                  options={CASCADE_STT_MODELS}
                  groups={CASCADE_STT_MODEL_GROUPS}
                />

                <label className="toggle-label" style={{ marginBottom: "10px" }}>
                  <input
                    type="checkbox"
                    checked={settings.skipStt ?? false}
                    disabled={active}
                    onChange={(e) => updateBool("skipStt", e.target.checked)}
                  />
                  <span>Skip STT (Send audio directly to LLM)</span>
                </label>

                {/* 2. LLM */}
                <Picker
                  label="2. Language Model (LLM)"
                  value={settings.llmModel}
                  disabled={active}
                  onChange={(value) => update("llmModel", value)}
                  options={CASCADE_LLM_MODELS}
                  groups={CASCADE_LLM_MODEL_GROUPS}
                />

                {/* 3. TTS */}
                <Picker
                  label="3. Voice Model (TTS)"
                  value={settings.ttsModel}
                  disabled={active}
                  onChange={(value) => {
                    update("ttsModel", value);
                    if (value === "google-tts" && !settings.voice.includes("Chirp") && !settings.voice.startsWith("Custom")) {
                      update("voice", "hi-IN-Chirp3-HD-Sulafat");
                    } else if (value !== "google-tts" && (settings.voice.includes("Chirp") || settings.voice.startsWith("Custom"))) {
                      update("voice", "Gacrux");
                    }
                  }}
                  options={CASCADE_TTS_MODELS}
                  groups={CASCADE_TTS_MODEL_GROUPS}
                />

                {settings.ttsModel !== "google-tts" && (
                  <>
                    <div className="settings-pair">
                      <Picker
                        label="Gemini TTS Voice"
                        value={settings.voice}
                        disabled={active}
                        onChange={(value) => update("voice", value)}
                        options={GEMINI_VOICES.filter(([voice]) => !voice.startsWith("Custom"))}
                      />
                      <Picker
                        label="Language"
                        value={settings.language}
                        disabled={active}
                        onChange={(value) => update("language", value)}
                        options={LANGUAGE_OPTIONS}
                      />
                    </div>

                    {/* Gemini 3.8 Speaker Settings (SpeechMetadata) - Auto-selected per Persona */}
                    <div
                      style={{
                        padding: "14px",
                        background: "rgba(56, 189, 248, 0.05)",
                        border: "1px solid rgba(56, 189, 248, 0.22)",
                        borderRadius: "10px",
                        marginTop: "6px",
                        display: "flex",
                        flexDirection: "column",
                        gap: "12px",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "6px" }}>
                        <span style={{ fontWeight: 600, fontSize: "13px", color: "#38bdf8" }}>
                          Voice Design & Speaker Settings (Auto-matched to {persona.name})
                        </span>
                        <span
                          style={{
                            fontSize: "11px",
                            padding: "2px 8px",
                            borderRadius: "999px",
                            background: "rgba(16, 185, 129, 0.14)",
                            border: "1px solid rgba(16, 185, 129, 0.3)",
                            color: "#34d399",
                            fontWeight: 600,
                          }}
                        >
                          {settings.ttsModel === "gemini-3.8-flash-tts"
                            ? "$0.50 / 1M in · $9.00 / 1M audio out"
                            : settings.ttsModel === "gemini-3.8-flash-lite-tts"
                              ? "$0.50 / 1M in · $6.00 / 1M audio out"
                              : "Vertex AI Gemini TTS"}
                        </span>
                      </div>

                      <div className="settings-pair">
                        <Picker
                          label="Style"
                          value={settings.ttsStyle ?? "Empathetic"}
                          disabled={active}
                          onChange={(value) => update("ttsStyle", value)}
                          options={TTS_STYLE_OPTIONS}
                        />
                        <Picker
                          label="Pace"
                          value={settings.ttsPaceLabel ?? "Natural"}
                          disabled={active}
                          onChange={(value) => update("ttsPaceLabel", value)}
                          options={TTS_PACE_OPTIONS}
                        />
                      </div>

                      <div className="settings-pair">
                        <Picker
                          label="Accent"
                          value={settings.ttsAccent ?? "Indian"}
                          disabled={active}
                          onChange={(value) => update("ttsAccent", value)}
                          options={TTS_ACCENT_OPTIONS}
                        />
                        <Picker
                          label="Pitch"
                          value={settings.ttsPitch ?? "Default"}
                          disabled={active}
                          onChange={(value) => update("ttsPitch", value)}
                          options={TTS_PITCH_OPTIONS}
                        />
                      </div>

                      <div className="field">
                        <label htmlFor="tts-voice-prompt">
                          Persona Voice Design Prompt (Auto-selected for {persona.name})
                        </label>
                        <Textarea
                          id="tts-voice-prompt"
                          rows={2}
                          disabled={active}
                          placeholder="Automatically populated based on active persona, or customize here."
                          value={settings.ttsVoicePrompt ?? ""}
                          onChange={(e) => update("ttsVoicePrompt", e.target.value)}
                          className="instructions-textarea"
                          style={{ minHeight: "52px" }}
                        />
                        <p className="field-hint" style={{ marginTop: "4px" }}>
                          <code>SpeechMetadata(style=&quot;Style: {settings.ttsStyle ?? "Empathetic"}. Pace: {settings.ttsPaceLabel ?? "Natural"}. Accent: {settings.ttsAccent ?? "Indian"}.{settings.ttsPitch && settings.ttsPitch !== "Default" ? ` Pitch: ${settings.ttsPitch}.` : ""}{settings.ttsVoicePrompt ? ` ${settings.ttsVoicePrompt}` : ""}&quot;)</code>
                        </p>
                      </div>
                    </div>
                  </>
                )}

                {settings.ttsModel === "google-tts" && (
                  <>
                    <div className="settings-pair">
                      <Picker
                        label="Chirp 3 HD Voice Options"
                        value={settings.voice}
                        disabled={active}
                        onChange={(value) => update("voice", value)}
                        options={CHIRP_HD_VOICES}
                      />
                      <Picker
                        label="Language"
                        value={settings.language}
                        disabled={active}
                        onChange={(value) => update("language", value)}
                        options={LANGUAGE_OPTIONS}
                      />
                    </div>

                    {settings.voice === "Custom-Key" && (
                      <div className="field" style={{ marginTop: "4px" }}>
                        <label htmlFor="settings-custom-voice-key-cascade">Custom Voice Key / Replicated ID</label>
                        <Input
                          id="settings-custom-voice-key-cascade"
                          type="password"
                          autoComplete="off"
                          placeholder="e.g. projects/.../voices/my-voice or voice_key"
                          value={settings.customVoiceKey ?? ""}
                          disabled={active}
                          onChange={(e) => update("customVoiceKey", e.target.value)}
                        />
                        <p className="field-hint">Enter your EAP Voice Replication Key or cloned voice identifier.</p>
                      </div>
                    )}

                    {settings.voice.startsWith("Custom") && (
                      <div style={{ padding: "8px 12px", background: "rgba(245, 158, 11, 0.1)", border: "1px solid rgba(245, 158, 11, 0.25)", borderRadius: "8px", fontSize: "12px", color: "#fbbf24", margin: "8px 0" }}>
                        ℹ️ <strong>Custom Voice Mode:</strong> Synthesized via Google Cloud TTS voice cloning pipeline.
                      </div>
                    )}
                  </>
                )}

                <div className="settings-slider-field">
                  <div className="slider-label-row">
                    <label htmlFor="settings-pace-slider">Speaking Rate Multiplier (Numeric)</label>
                    <span className="slider-val">{(settings.ttsPace ?? 1.0).toFixed(2)}x</span>
                  </div>
                  <input
                    id="settings-pace-slider"
                    type="range"
                    min="0.25"
                    max="2.0"
                    step="0.05"
                    value={settings.ttsPace ?? 1.0}
                    disabled={active}
                    onChange={(e) => updateNumber("ttsPace", parseFloat(e.target.value))}
                    className="range-slider"
                  />
                </div>
              </>
            )}
          </div>

          {/* GROUP 2: AGENT INSTRUCTIONS */}
          <div className="settings-group">
            <h3 className="settings-section-title">Agent Persona & Instructions</h3>

            {/* Persona tone selector */}
            {!custom && persona.signaturePrompt && (
              <div className="field">
                <label htmlFor="persona-tone">Persona Tone</label>
                <Select
                  value={settings.tone}
                  onValueChange={(value) => update("tone", value as PersonaTone)}
                  disabled={active || Boolean(settings.instructions)}
                >
                  <SelectTrigger id="persona-tone">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent position="popper">
                    <SelectItem value="professional">Professional (default)</SelectItem>
                    <SelectItem value="signature">Signature ({persona.agentName} in character)</SelectItem>
                  </SelectContent>
                </Select>
                <p className="field-hint">
                  {settings.instructions
                    ? "Custom instructions are in effect, so the persona register is not used."
                    : settings.tone === "signature"
                      ? `The original, high-character ${persona.name.toLowerCase()}. Best for audiences who know the demo.`
                      : "The same scenario played straight. Suited to a general audience."}
                </p>
              </div>
            )}

            {/* Persona / System Instructions Textarea */}
            <div className="field">
              <div className="instructions-label">
                <div className="instructions-title-group">
                  <label htmlFor="instructions">{custom ? "System Instructions" : "Persona Instructions"}</label>
                  <span
                    style={{
                      fontSize: "11px",
                      padding: "2px 8px",
                      borderRadius: "999px",
                      background: "rgba(213, 245, 128, 0.12)",
                      border: "1px solid rgba(213, 245, 128, 0.28)",
                      color: "#d5f580",
                      fontWeight: 600,
                    }}
                  >
                    {estimateTokens(settings.instructions || effectivePresetPrompt).toLocaleString()} tokens
                  </span>
                  {settings.instructions && (
                    <span className="customized-indicator-pill">Customized</span>
                  )}
                </div>
                <div className="instructions-btn-group">
                  {!custom && !settings.instructions && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={active}
                      onClick={() => update("instructions", effectivePresetPrompt)}
                      className="edit-instructions-btn"
                    >
                      <Edit3 size={12} />
                      <span>Customize / Edit prompt</span>
                    </Button>
                  )}
                  {settings.instructions && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={active}
                      onClick={() => update("instructions", "")}
                      className="restore-preset-btn"
                    >
                      <RotateCcw size={12} />
                      <span>{custom ? "Use backend default" : "Restore preset"}</span>
                    </Button>
                  )}
                </div>
              </div>
              <Textarea
                id="instructions"
                placeholder={custom ? "Leave blank to use your backend’s existing system instructions." : effectivePresetPrompt}
                value={settings.instructions || effectivePresetPrompt}
                onFocus={() => {
                  if (!custom && !settings.instructions) {
                    update("instructions", effectivePresetPrompt);
                  }
                }}
                onChange={(e) => update("instructions", e.target.value)}
                disabled={active}
                maxLength={16000}
                rows={6}
                className="instructions-textarea"
                style={{ resize: "vertical", minHeight: "120px" }}
              />
              <div className="instructions-footer">
                <p className="field-hint">
                  {settings.instructions
                    ? `${estimateTokens(settings.instructions).toLocaleString()} / 4,000 tokens · Replaces default preset`
                    : custom
                    ? "Using your backend’s existing system instructions."
                    : `${estimateTokens(effectivePresetPrompt).toLocaleString()} tokens · Active ${persona.name} backend prompt. Click inside or 'Customize / Edit' to modify it.`}
                </p>
                {!settings.instructions && !custom && (
                  <button
                    type="button"
                    className="load-prompt-inline-link"
                    onClick={() => update("instructions", effectivePresetPrompt)}
                  >
                    Load preset into editor
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* GROUP 4: ADVANCED CONFIGURATION */}
          <div className="settings-group">
            <h3 className="settings-section-title">Advanced Configuration</h3>

            {/* VAD Mode Selector */}
            <div className="field" style={{ marginBottom: "10px" }}>
              <Picker
                label="Voice Activity Detection (VAD) Mode"
                value={settings.vadMode ?? (settings.vad === false ? "gemini" : "both")}
                disabled={active}
                onChange={(value) => {
                  const nextMode = value as VadMode;
                  update("vadMode", nextMode);
                  updateBool("vad", nextMode !== "gemini");
                }}
                options={VAD_MODES}
              />
              <p className="field-hint">
                {(settings.vadMode ?? (settings.vad === false ? "gemini" : "both")) === "gemini"
                  ? isLive
                    ? "Gemini Internal VAD Only — Local Silero VAD is disabled; Gemini's server-side AutomaticActivityDetection decides turn boundaries."
                    : "Server Endpointing Only — Local Silero VAD is disabled; the STT service's server-side endpointing decides turn boundaries."
                  : (settings.vadMode ?? "both") === "silero"
                    ? isLive
                      ? "Silero VAD Only — Local Pipecat Silero VAD drives explicit ActivityStart/ActivityEnd signals; Gemini's internal VAD is disabled."
                      : "Silero VAD Only — Local Pipecat Silero VAD marks conversational turn boundaries."
                    : isLive
                      ? "Both Active — Local Silero VAD handles immediate barge-in and speech-end telemetry alongside Gemini's server-side AutomaticActivityDetection."
                      : "Both Active — Local Silero VAD runs alongside STT server-side endpointing."}
              </p>
            </div>

            <div className="advanced-toggles">

              {/* Gemini Live specific advanced options */}
              {isLive && (
                <>
                  <label className="toggle-label">
                    <input
                      type="checkbox"
                      checked={settings.tts ?? false}
                      disabled={active}
                      onChange={(e) => updateBool("tts", e.target.checked)}
                    />
                    <span>Use TTS for output modality</span>
                  </label>

                  <label className="toggle-label">
                    <input
                      type="checkbox"
                      checked={settings.contextCompression ?? false}
                      disabled={active}
                      onChange={(e) => updateBool("contextCompression", e.target.checked)}
                    />
                    <span>Context Compression</span>
                  </label>

                  {settings.contextCompression && (
                    <div className="field trigger-tokens-field">
                      <label htmlFor="comp-tokens">Trigger Tokens Threshold (min 5,000)</label>
                      <Input
                        id="comp-tokens"
                        type="number"
                        min={5000}
                        step={1000}
                        value={Math.max(5000, settings.contextCompressionTokens ?? 5000)}
                        disabled={active}
                        onChange={(e) => {
                          const val = parseInt(e.target.value, 10);
                          updateNumber("contextCompressionTokens", isNaN(val) ? 5000 : Math.max(5000, val));
                        }}
                        onBlur={(e) => {
                          const val = parseInt(e.target.value, 10);
                          if (isNaN(val) || val < 5000) {
                            updateNumber("contextCompressionTokens", 5000);
                          }
                        }}
                      />
                      <p className="field-hint">Minimum 5,000 tokens (Vertex AI Live API requires &ge; 5,000 tokens).</p>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Thinking / Reasoning Configuration (Live only) */}
            {isLive && (
              <div style={{ padding: "12px", background: "rgba(16, 185, 129, 0.06)", border: "1px solid rgba(16, 185, 129, 0.22)", borderRadius: "10px", margin: "12px 0" }}>
                <div style={{ marginBottom: "8px" }}>
                  <span style={{ fontWeight: 600, fontSize: "13px", color: "#34d399" }}>Gemini Live Thinking / Reasoning</span>
                  <p style={{ fontSize: "11px", color: "var(--muted-foreground)", margin: "2px 0 0 0" }}>
                    Internal reasoning effort before speech. Higher levels add latency.
                  </p>
                </div>
                <div className="field">
                  <label id="thinking-level-label">Reasoning Level</label>
                  <Select
                    value={settings.thinkingLevel ?? "off"}
                    onValueChange={(val) => update("thinkingLevel", val)}
                    disabled={active}
                  >
                    <SelectTrigger aria-labelledby="thinking-level-label" className="w-full min-w-0 select-trigger">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent position="popper">
                      {THINKING_LEVELS.map(([value, label]) => (
                        <SelectItem key={value} value={value}>{label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="field-hint">
                    Not every model supports every tier — unsupported levels fall back to the model default.
                  </p>
                </div>
              </div>
            )}

            {/* Dynamic Tool Definitions (JSON) showing live backend tool configuration + token count */}
            <div className="field" style={{ marginTop: "12px" }}>
              <div className="instructions-label">
                <div className="instructions-title-group">
                  <label htmlFor="tools-json" style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                    <Wrench size={13} />
                    <span>Dynamic Tool Definitions (JSON)</span>
                  </label>
                  <span
                    style={{
                      fontSize: "11px",
                      padding: "2px 8px",
                      borderRadius: "999px",
                      background: "rgba(56, 189, 248, 0.12)",
                      border: "1px solid rgba(56, 189, 248, 0.28)",
                      color: "#38bdf8",
                      fontWeight: 600,
                    }}
                  >
                    {effectiveToolCount} {effectiveToolCount === 1 ? "tool" : "tools"} · {effectiveToolsTokens.toLocaleString()} tokens
                  </span>
                  {settings.toolsJson && (
                    <span className="customized-indicator-pill">Customized</span>
                  )}
                </div>
                <div className="instructions-btn-group">
                  {!settings.toolsJson && backendToolsJson && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={active}
                      onClick={() => update("toolsJson", backendToolsJson)}
                      className="edit-instructions-btn"
                    >
                      <Edit3 size={12} />
                      <span>Customize / Edit tools</span>
                    </Button>
                  )}
                  {settings.toolsJson && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={active}
                      onClick={() => update("toolsJson", "")}
                      className="restore-preset-btn"
                    >
                      <RotateCcw size={12} />
                      <span>Restore backend tools</span>
                    </Button>
                  )}
                </div>
              </div>
              <Textarea
                id="tools-json"
                value={effectiveToolsText}
                onFocus={() => {
                  if (!settings.toolsJson && backendToolsJson) {
                    update("toolsJson", backendToolsJson);
                  }
                }}
                onChange={(e) => update("toolsJson", e.target.value)}
                disabled={active}
                placeholder='[{"name": "get_weather", "description": "Get weather", "properties": {"city": {"type": "string"}}, "required": ["city"]}]'
                rows={7}
                style={{ fontFamily: "ui-monospace, monospace", fontSize: "12px", resize: "vertical", minHeight: "150px" }}
              />
              <div className="instructions-footer">
                <p className="field-hint">
                  {settings.toolsJson
                    ? `${effectiveToolCount} tool definition(s) · ${effectiveToolsTokens.toLocaleString()} tokens · Custom OpenAPI tool configuration active.`
                    : `${effectiveToolCount} active backend tool(s) (${backendTools.map((t) => t.name).join(", ") || "none"}) · ${effectiveToolsTokens.toLocaleString()} tokens. Click inside or 'Customize / Edit tools' to modify.`}
                </p>
              </div>
            </div>

            {/* Custom Server URL Override */}
            <details className="advanced-url-toggle">
              <summary>Custom Server URL (Optional)</summary>
              <div className="field" style={{ marginTop: "10px" }}>
                <Input
                  id="backend-url"
                  value={settings.backendUrl}
                  onChange={(e) => update("backendUrl", e.target.value)}
                  placeholder="http://localhost:7860"
                  disabled={active}
                  type="url"
                  autoComplete="off"
                />
                <p className="field-hint">
                  Defaults automatically to your backend on port 7860 or host origin. Override only if connecting to an external server.
                </p>
              </div>
            </details>
          </div>
        </div>

        <div className="dialog-actions">
          <Button variant="outline" onClick={() => setSettingsOpen(false)}>
            Done
          </Button>
          {!active && (
            <Button className="primary-call" onClick={() => void startBackend()}>
              <Mic size={16} />
              Start {engineName}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
