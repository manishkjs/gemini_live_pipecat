import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import { formatVoiceShortLabel, getPipelineNodes, getScenarioStages } from "@/lib/call-console";
import { getPersonaPrompt } from "@/lib/personas";
import { estimateTokens } from "@/lib/pricing";
import { buildPersonaPromptUrl } from "@/lib/voice-session";
import { ChevronRightIcon, PlaySampleIcon, SlidersIcon, StopSampleIcon } from "./console-icons";

type PreCallTab = "scenario" | "prompt" | "pipeline";

const TAB_ORDER: readonly PreCallTab[] = ["scenario", "prompt", "pipeline"];

interface PreCallCardProps {
  readonly studio: VoiceStudio;
}

/** Persona-centered Pre-Call setup card with Scenario, System prompt, and Pipeline tabs. */
export default function PreCallCard({ studio }: PreCallCardProps) {
  const { persona, custom, settings, playingSample, showInlineEditor, setShowInlineEditor, toggleVoiceSample, update } = studio;
  const [activeTab, setActiveTab] = useState<PreCallTab>("scenario");
  const [copiedQuote, setCopiedQuote] = useState(false);
  const [portraitFailed, setPortraitFailed] = useState(false);
  const [serverPrompt, setServerPrompt] = useState<string | null>(null);
  const [serverTokenCount, setServerTokenCount] = useState<number | null>(null);
  const [promptHasMore, setPromptHasMore] = useState(false);
  const promptTextRef = useRef<HTMLDivElement | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setPortraitFailed(false);
    if (custom) {
      setActiveTab("prompt");
      setShowInlineEditor(true);
    }
  }, [custom, persona.id, setShowInlineEditor]);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    };
  }, []);

  // Fetch server-composed persona prompt preview for preset personas.
  useEffect(() => {
    if (custom || settings.instructions.trim()) {
      setServerPrompt(null);
      setServerTokenCount(null);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const fetchPreview = async () => {
      try {
        const url = buildPersonaPromptUrl(settings, studio.currentPhase || undefined);
        const res = await fetch(url, { signal: controller.signal });
        if (!res.ok) return;
        const payload = (await res.json()) as { prompt?: unknown; token_count?: unknown };
        if (cancelled) return;
        if (typeof payload.prompt === "string" && payload.prompt.trim()) {
          setServerPrompt(payload.prompt);
        }
        if (typeof payload.token_count === "number" && Number.isFinite(payload.token_count)) {
          setServerTokenCount(payload.token_count);
        }
      } catch {
        // Offline or local-only preview falls back to getPersonaPrompt(persona, settings.tone).
      }
    };
    void fetchPreview();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [
    custom,
    settings.personaId,
    settings.engine,
    settings.model,
    settings.tone,
    settings.language,
    settings.backendUrl,
    settings.instructions,
    studio.currentPhase,
  ]);

  const displayedPrompt = settings.instructions.trim()
    || serverPrompt
    || getPersonaPrompt(persona, settings.tone)
    || "";

  const promptTokens = settings.instructions.trim()
    ? estimateTokens(settings.instructions)
    : (serverTokenCount ?? estimateTokens(displayedPrompt));

  const syncPromptFade = useCallback(() => {
    const el = promptTextRef.current;
    if (!el) return;
    setPromptHasMore(el.scrollHeight - el.clientHeight - el.scrollTop > 4);
  }, []);

  useEffect(() => {
    if (activeTab !== "prompt" || showInlineEditor) return;
    syncPromptFade();
    const id = requestAnimationFrame(syncPromptFade);
    return () => cancelAnimationFrame(id);
  }, [activeTab, displayedPrompt, showInlineEditor, syncPromptFade]);

  const stages = getScenarioStages(persona);
  const pipelineNodes = getPipelineNodes(settings);
  const voiceCaption = `${formatVoiceShortLabel(settings.voice)} · ${settings.language}`;
  const isLockedPrompt = Boolean(persona.architectureLocked);
  const isMultistage = stages.length > 4;
  const timelineCols = stages.length === 3 ? "cols-3" : "cols-4";

  const handleCopyOpening = async () => {
    if (!persona.opening) return;
    try {
      await navigator.clipboard.writeText(persona.opening);
      setCopiedQuote(true);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedQuote(false), 1400);
    } catch {
      // Ignore clipboard permission blocks.
    }
  };

  const handleTabKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const idx = TAB_ORDER.indexOf(activeTab);
    let nextIdx = idx;
    if (e.key === "ArrowRight") nextIdx = (idx + 1) % TAB_ORDER.length;
    else if (e.key === "ArrowLeft") nextIdx = (idx - 1 + TAB_ORDER.length) % TAB_ORDER.length;
    else if (e.key === "Home") nextIdx = 0;
    else if (e.key === "End") nextIdx = TAB_ORDER.length - 1;
    const nextTab = TAB_ORDER[nextIdx];
    if (!nextTab) return;
    setActiveTab(nextTab);
    requestAnimationFrame(() => {
      document.getElementById(`cc-tab-${nextTab}`)?.focus();
    });
  };

  const panelClass = [
    "cc-panel",
    "scroll-area",
    activeTab === "scenario" && isMultistage ? "is-multistage" : "",
    activeTab === "prompt" ? "is-prompt-panel" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="call-card">
      <div className="cc-portrait-wrap">
        <div className={`cc-portrait${playingSample ? " is-speaking" : ""}`}>
          {persona.portrait && !portraitFailed ? (
            <img
              src={persona.portrait}
              alt={`${persona.agentName}, ${persona.name}`}
              width={152}
              height={152}
              decoding="async"
              onError={() => setPortraitFailed(true)}
            />
          ) : (
            <SlidersIcon size={36} />
          )}
        </div>
        <span className="cc-voice">{voiceCaption}</span>
        <button
          type="button"
          id="btn-sample"
          className="cc-sample"
          aria-pressed={playingSample}
          aria-label={
            playingSample
              ? "Stop browser speech preview"
              : "Preview opening line with browser speech synthesis"
          }
          title="Previews the opening line using browser speech synthesis"
          onClick={toggleVoiceSample}
        >
          {playingSample ? <StopSampleIcon /> : <PlaySampleIcon />}
          <span>{playingSample ? "Stop preview" : "Browser preview"}</span>
        </button>
      </div>

      <div className="cc-body">
        <div className="cc-header-row">
          <h1 className="cc-name">
            {custom ? persona.name : persona.agentName}
            {!custom && <small>· {persona.name}</small>}
          </h1>
        </div>

        <p className="cc-role">
          <strong>Your role:</strong> {persona.userRole}
        </p>

        {persona.opening ? (
          <div className="cc-quote">
            <div>
              <div className="cc-quote-label">Try opening with</div>
              <div className="cc-quote-text">“{persona.opening}”</div>
            </div>
            <button type="button" className="ghost-btn" id="btn-copy-opening" onClick={handleCopyOpening}>
              {copiedQuote ? "Copied" : "Copy"}
            </button>
          </div>
        ) : (
          <div className="cc-quote">
            <div>
              <div className="cc-quote-label">Custom voice agent</div>
              <div className="cc-quote-text">
                Author your system instructions below or leave blank to use the default backend prompt.
              </div>
            </div>
            <button
              type="button"
              className="ghost-btn"
              onClick={() => {
                setActiveTab("prompt");
                setShowInlineEditor(true);
              }}
            >
              Edit prompt
            </button>
          </div>
        )}

        <div className="cc-tabs" role="tablist" aria-label="Persona details" onKeyDown={handleTabKeyDown}>
          <button
            type="button"
            role="tab"
            id="cc-tab-scenario"
            aria-controls="cc-tabpanel"
            aria-selected={activeTab === "scenario"}
            tabIndex={activeTab === "scenario" ? 0 : -1}
            className="cc-tab"
            onClick={() => setActiveTab("scenario")}
          >
            Scenario · {stages.length} stages
          </button>
          <button
            type="button"
            role="tab"
            id="cc-tab-prompt"
            aria-controls="cc-tabpanel"
            aria-selected={activeTab === "prompt"}
            tabIndex={activeTab === "prompt" ? 0 : -1}
            className="cc-tab"
            onClick={() => setActiveTab("prompt")}
          >
            System prompt
          </button>
          <button
            type="button"
            role="tab"
            id="cc-tab-pipeline"
            aria-controls="cc-tabpanel"
            aria-selected={activeTab === "pipeline"}
            tabIndex={activeTab === "pipeline" ? 0 : -1}
            className="cc-tab"
            onClick={() => setActiveTab("pipeline")}
          >
            Pipeline
          </button>
        </div>

        <div
          id="cc-tabpanel"
          role="tabpanel"
          aria-labelledby={`cc-tab-${activeTab}`}
          className={panelClass}
        >
          {activeTab === "scenario" && (
            <ol className={`timeline ${timelineCols}`}>
              {stages.map((step) => (
                <li key={step.num} className="tl-step">
                  <div className="tl-num">{step.num}</div>
                  <div className="tl-title">{step.title}</div>
                  <div className="tl-detail">{step.detail}</div>
                </li>
              ))}
            </ol>
          )}

          {activeTab === "prompt" && (
            <div className="prompt-box">
              <div className="prompt-head">
                <div className="prompt-head-actions">
                  <span>System instructions</span>
                  <span className="mono-pill" id="tok-pill">
                    {promptTokens.toLocaleString()} / 4,000 tok
                  </span>
                </div>
                <div className="prompt-head-actions">
                  {isLockedPrompt ? (
                    <span className="mono-pill" title={persona.architectureNote}>
                      Managed · Dynamic SOP cards
                    </span>
                  ) : (
                    <>
                      {settings.instructions.trim() && !custom && (
                        <button
                          type="button"
                          className="ghost-btn"
                          onClick={() => {
                            update("instructions", "");
                            setShowInlineEditor(false);
                          }}
                        >
                          Reset
                        </button>
                      )}
                      <button
                        type="button"
                        id="btn-edit-prompt"
                        className="ghost-btn"
                        onClick={() => {
                          if (!showInlineEditor && !settings.instructions.trim() && !custom) {
                            update("instructions", displayedPrompt);
                          }
                          setShowInlineEditor(!showInlineEditor);
                        }}
                      >
                        {showInlineEditor ? "Done" : "Edit"}
                      </button>
                    </>
                  )}
                </div>
              </div>
              {showInlineEditor && !isLockedPrompt ? (
                <textarea
                  id="prompt-edit"
                  className="prompt-edit scroll-area"
                  aria-label="Custom system instructions"
                  placeholder="Write system instructions for this voice session..."
                  value={settings.instructions}
                  onChange={(e) => update("instructions", e.target.value)}
                />
              ) : (
                <div
                  ref={promptTextRef}
                  tabIndex={0}
                  role="region"
                  aria-label="System instructions preview"
                  className={`prompt-text scroll-area${promptHasMore ? " has-more" : ""}`}
                  onScroll={syncPromptFade}
                >
                  {displayedPrompt || "No preset instructions configured. Click Edit to add custom instructions."}
                </div>
              )}
            </div>
          )}

          {activeTab === "pipeline" && (
            <div className="pipe">
              {pipelineNodes.map((node, index) => (
                <div key={node.kind} style={{ display: "contents" }}>
                  {index > 0 && (
                    <span className="pipe-arrow" aria-hidden="true">
                      <ChevronRightIcon />
                    </span>
                  )}
                  <div className="pipe-node">
                    <div className="k">{node.kind}</div>
                    <div className="v">{node.title}</div>
                    <div className="m">{node.meta}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
