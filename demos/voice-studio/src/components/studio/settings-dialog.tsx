import { Edit3, Mic, RotateCcw, DollarSign } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  LANGUAGE_OPTIONS,
  LIVE_MODELS,
  CASCADE_STT_MODELS,
  CASCADE_LLM_MODELS,
  CASCADE_TTS_MODELS,
  GEMINI_VOICES,
  CHIRP_HD_VOICES,
  THINKING_LEVELS,
  usesExternalTts,
} from "@/lib/voice-session";
import { getPersonaPrompt, type PersonaTone } from "@/lib/personas";
import { isLivePricingEligible, getLiveRateCard, estimateTokens } from "@/lib/pricing";
import type { VoiceStudio } from "@/hooks/use-voice-session";

function Picker({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly (readonly [string, string])[];
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
          {options.map(([v, l]) => (
            <SelectItem value={v} key={v}>
              {l}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/** Every engine parameter the backend accepts, in one place. */
export default function SettingsDialog({ studio }: { studio: VoiceStudio }) {
  const {
    active, custom, engineName, persona, settings, settingsOpen, setSettingsOpen,
    startBackend, update, updateBool, updateNumber,
  } = studio;

  return (
  <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
    <DialogContent className="studio-dialog">
      <DialogHeader>
        <DialogTitle>Session Configuration: {engineName}</DialogTitle>
        <DialogDescription>
          {persona.name} · {engineName}. All parameters of Google Cloud Speech and Gemini Live are configurable below.
        </DialogDescription>
      </DialogHeader>

      <div className="dialog-fields">
        {/* GEMINI LIVE CONFIGURATION */}
        {settings.engine === "live" && (
          <>
            <Picker
              label="Live Model"
              value={settings.model}
              disabled={active}
              onChange={(value) => update("model", value)}
              options={LIVE_MODELS}
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
                <label htmlFor="custom-voice-key">Custom Voice Key / Replicated ID</label>
                <Input
                  id="custom-voice-key"
                  type="text"
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

            {/* GEMINI LIVE THINKING / REASONING CONFIGURATION */}
            <div style={{ padding: "12px", background: "rgba(16, 185, 129, 0.06)", border: "1px solid rgba(16, 185, 129, 0.22)", borderRadius: "10px", marginBottom: "12px" }}>
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

            {/* Native audio has no pace parameter — the model speaks it
                directly. Only show the control when a TTS service is
                rendering the audio and can honour it. */}
            {usesExternalTts(settings) && (
              <div className="settings-slider-field">
                <div className="slider-label-row">
                  <label htmlFor="live-pace-slider">Speaking Rate (Pace)</label>
                  <span className="slider-val">{(settings.ttsPace ?? 1.0).toFixed(2)}x</span>
                </div>
                <input
                  id="live-pace-slider"
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

            <div className="advanced-toggles">
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
                  checked={settings.vad ?? true}
                  disabled={active}
                  onChange={(e) => updateBool("vad", e.target.checked)}
                />
                <span>Voice Activity Detection (VAD)</span>
              </label>
              <p className="field-hint">
                {settings.vad === false
                  ? "Off — Gemini's server-side turn detection decides when you have finished speaking."
                  : "On — Silero detects your turn boundaries locally, which drives interruption handling."}
              </p>
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
            </div>
          </>
        )}

        {/* CASCADE (STT-LLM-TTS) CONFIGURATION */}
        {settings.engine === "cascade" && (
          <>
            <Picker
              label="Speech Recognition (STT)"
              value={settings.sttModel}
              disabled={active}
              onChange={(value) => update("sttModel", value)}
              options={CASCADE_STT_MODELS}
            />

            <label className="toggle-label" style={{ marginBottom: "12px" }}>
              <input
                type="checkbox"
                checked={settings.skipStt ?? false}
                disabled={active}
                onChange={(e) => updateBool("skipStt", e.target.checked)}
              />
              <span>Skip STT (Send audio directly to LLM)</span>
            </label>

            <Picker
              label="Language Model (LLM)"
              value={settings.llmModel}
              disabled={active}
              onChange={(value) => update("llmModel", value)}
              options={CASCADE_LLM_MODELS}
            />

            <Picker
              label="Voice Model (TTS)"
              value={settings.ttsModel}
              disabled={active}
              onChange={(value) => {
                update("ttsModel", value);
                if (value === "google-tts" && !settings.voice.includes("Chirp")) {
                  update("voice", "hi-IN-Chirp3-HD-Sulafat");
                } else if (value !== "google-tts" && settings.voice.includes("Chirp")) {
                  update("voice", "Aoede");
                }
              }}
              options={CASCADE_TTS_MODELS}
            />

            <div className="settings-pair">
              <Picker
                label="Voice"
                value={settings.voice}
                disabled={active}
                onChange={(value) => update("voice", value)}
                options={settings.ttsModel === "google-tts" ? CHIRP_HD_VOICES : GEMINI_VOICES}
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
                <label htmlFor="cascade-custom-voice-key">Custom Voice Key / Replicated ID</label>
                <Input
                  id="cascade-custom-voice-key"
                  type="text"
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

            <div className="settings-slider-field">
              <div className="slider-label-row">
                <label htmlFor="cascade-pace-slider">Speaking Rate (Pace)</label>
                <span className="slider-val">{(settings.ttsPace ?? 1.0).toFixed(2)}x</span>
              </div>
              <input
                id="cascade-pace-slider"
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

            <div className="advanced-toggles">
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={settings.vad ?? true}
                  disabled={active}
                  onChange={(e) => updateBool("vad", e.target.checked)}
                />
                <span>Voice Activity Detection (VAD)</span>
              </label>
              <p className="field-hint">
                {settings.vad === false
                  ? "Off — the STT service's own endpointing decides when your turn ends."
                  : "On — Silero gates audio into the STT service and marks turn boundaries."}
              </p>
            </div>
          </>
        )}

        {/* DYNAMIC TOOL DEFINITIONS (JSON) */}
        <div className="field">
          <label htmlFor="tools-json">Dynamic Tool Definitions (JSON)</label>
          <Textarea
            id="tools-json"
            value={settings.toolsJson ?? ""}
            onChange={(e) => update("toolsJson", e.target.value)}
            disabled={active}
            placeholder='[{"name": "get_weather", "description": "Get weather", "properties": {"city": {"type": "string"}}, "required": ["city"]}]'
            rows={3}
            style={{ fontFamily: "ui-monospace, monospace", fontSize: "12px" }}
          />
          <p className="field-hint">Optional OpenAPI tool definitions executed live during conversational turns.</p>
        </div>

        {/* PERSONA REGISTER */}
        {!custom && persona.signaturePrompt && (
          <div className="field">
            <label htmlFor="persona-tone">Persona tone</label>
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

        {/* SYSTEM / PERSONA INSTRUCTIONS */}
        <div className="field">
          <div className="instructions-label">
            <div className="instructions-title-group">
              <label htmlFor="instructions">{custom ? "System instructions" : "Persona instructions"}</label>
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
                  // Seed from the register currently in effect, not always the
                  // professional one, so editing does not silently revert tone.
                  onClick={() => update("instructions", getPersonaPrompt(persona, settings.tone))}
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
            placeholder={custom ? "Leave blank to use your backend’s existing system instructions." : persona.prompt}
            value={settings.instructions}
            onFocus={() => {
              if (!custom && !settings.instructions) {
                update("instructions", persona.prompt);
              }
            }}
            onChange={(e) => update("instructions", e.target.value)}
            disabled={active}
            maxLength={16000}
            rows={5}
            className="instructions-textarea"
          />
          <div className="instructions-footer">
            <p className="field-hint">
              {settings.instructions
                ? `${estimateTokens(settings.instructions).toLocaleString()} / 4,000 tokens · Replaces default preset`
                : custom
                ? "Using your backend’s existing system instructions."
                : `Using the ${persona.name} preset. Click inside or 'Customize / Edit' to modify it.`}
            </p>
            {!settings.instructions && !custom && (
              <button
                type="button"
                className="load-prompt-inline-link"
                onClick={() => update("instructions", persona.prompt)}
              >
                Load preset into editor
              </button>
            )}
          </div>
        </div>

        {/* CUSTOM SERVER URL OVERRIDE */}
        <details className="advanced-url-toggle">
          <summary>Advanced: Custom Server URL (Optional)</summary>
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

      <div className="dialog-actions">
        <Button variant="outline" onClick={() => setSettingsOpen(false)}>
          Done
        </Button>
        <Button className="primary-call" disabled={active} onClick={() => void startBackend()}>
          <Mic size={16} />
          Start {engineName}
        </Button>
      </div>
    </DialogContent>
  </Dialog>
  );
}
