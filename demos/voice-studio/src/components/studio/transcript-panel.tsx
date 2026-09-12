import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Check, Copy, Edit3, Lock, Mic, RotateCcw, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { isLivePricingEligible, formatCost, estimateTokens, formatTokens, totalIn, totalOut } from "@/lib/pricing";
import { getPersonaPrompt } from "@/lib/personas";
import { buildPersonaPromptUrl } from "@/lib/voice-session";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import PersonaAvatar from "./persona-avatar";

/** Live transcript, per-turn telemetry badges and the empty-state briefing. */
export default function TranscriptPanel({ studio }: { studio: VoiceStudio }) {
  const {
    active, copied, copyTranscript, custom, duration, engineName, followTranscript,
    latency, messages, partialUser, persona, phase, reduced, sessionCostUSD,
    settings, setShowInlineEditor, showInlineEditor, tokenCount, tokenSplit, transcript,
    update, currentPhase, visitedPhases,
  } = studio;

  // Resolve against the selected tone. Reading `persona.prompt` directly showed
  // the professional register even when Signature was selected, so the preview
  // disagreed with what the session actually ran.
  const presetPrompt = getPersonaPrompt(persona, settings.tone);
  const effectivePrompt = settings.instructions.trim() || presetPrompt;

  // Some personas' prompts are load-bearing for a server-side state machine. The
  // backend regenerates them regardless of what the client sends, so offering an
  // editor here would be a lie.
  const promptLocked = Boolean(persona.architectureLocked);

  // Canonical phase identifiers, emitted by the server's deterministic tracker
  // (server/supercar_phases.py). They are derived from what the caller says,
  // not from whether the model happened to call a tool, so the tracker keeps
  // moving even on a turn that uses no tools at all.
  const SOP_MAP: Record<string, number> = {
    SOP_01_OPENING: 0,
    SOP_02_DISCOVERY: 1,
    SOP_03_PINCODE: 2,
    SOP_04_BOOKED: 3,
  };

  const activeSopIndex = persona.id === "wealth-manager" && currentPhase
    ? (SOP_MAP[currentPhase] ?? 0)
    : 0;

  // ...and so would previewing our local copy. Ask the backend for the prompt it
  // will actually run. A stale preview is worse than a visibly pending one: it
  // teaches the demo audience the wrong thing about the architecture.
  const { personaId, backendUrl } = settings;
  const [serverPrompt, setServerPrompt] = useState<string | null>(null);
  const [serverPromptFailed, setServerPromptFailed] = useState(false);

  useEffect(() => {
    if (!promptLocked) {
      setServerPrompt(null);
      setServerPromptFailed(false);
      return;
    }
    let cancelled = false;
    setServerPrompt(null);
    setServerPromptFailed(false);
    fetch(buildPersonaPromptUrl(settings, currentPhase))
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data: { prompt?: string }) => {
        if (cancelled) return;
        const text = data.prompt?.trim();
        if (text) setServerPrompt(text);
        else setServerPromptFailed(true);
      })
      .catch(() => {
        if (!cancelled) setServerPromptFailed(true);
      });
    return () => {
      cancelled = true;
    };
    // Re-fetch when persona, backendUrl, or active phase card changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [promptLocked, personaId, backendUrl, currentPhase]);

  const previewPrompt = promptLocked
    ? serverPrompt
      ?? (serverPromptFailed
        ? "Backend unreachable — this persona's prompt is composed server-side and cannot be shown right now."
        : "Loading the prompt from the backend…")
    : effectivePrompt;


  return (
    <section className="transcript-panel" aria-labelledby="transcript-heading">
      <h2 id="transcript-heading" className="sr-only">Conversation</h2>


      {/* Live SOP Phase Engine / DEMO FOCUS tracker: stays mounted during calls */}
      {persona.journey && persona.journey.length > 0 && (
        <div className="transcript-sop-bar" aria-label="SOP journey tracker">
          <div className="sop-bar-header">
            <span className="eyebrow">{promptLocked ? "Prompt phase:" : "Demo focus:"}</span>
          </div>
          <ol className="phase-track">
            {persona.journey.map((step, i) => {
              const isActive = active ? i === activeSopIndex : i === 0;
              const isVisited = visitedPhases.some((p) => SOP_MAP[p] === i);
              return (
                <li
                  key={step}
                  className={`phase-step ${isActive ? "is-active" : isVisited ? "is-visited" : ""}`}
                >
                  <span className="step-num">{i + 1}</span>
                  <span className="step-text">{step}</span>
                  {i < persona.journey.length - 1 && <ArrowRight size={12} className="phase-arrow" />}
                </li>
              );
            })}
          </ol>
        </div>
      )}

      <div
        className="transcript-scroll"
        ref={transcript}
        onScroll={(e) => {
          const el = e.currentTarget;
          followTranscript.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        role={messages.length ? "log" : "region"}
        aria-label="Conversation transcript"
        aria-live={messages.length ? "polite" : "off"}
        aria-relevant="additions text"
      >
        <AnimatePresence mode="wait">
          {!messages.length ? (
            <motion.div
              key={persona.id}
              className="transcript-empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              {custom ? (
                <>
                  <h3>Start with your own instructions.</h3>
                  <p>Set the role, tone and goal for your agent. Both engines use the instructions you enter here.</p>
                  <div className="custom-prompt field">
                    <label htmlFor="custom-instructions">
                      System instructions <span className="optional-label">optional</span>
                    </label>
                    <Textarea
                      id="custom-instructions"
                      value={settings.instructions}
                      onChange={(e) => update("instructions", e.target.value)}
                      disabled={active}
                      placeholder="You are a helpful voice assistant. Keep replies brief, ask one question at a time, and…"
                      maxLength={16000}
                      rows={5}
                    />
                    <p className="field-hint">
                      {settings.instructions
                        ? `${estimateTokens(settings.instructions).toLocaleString()} / 4,000 tokens`
                        : "Leave blank to use your backend’s existing system instructions."}
                    </p>
                  </div>
                </>
              ) : (
                <>
                  <h3>Step into the conversation.</h3>
                  <p>
                    {phase === "connecting"
                      ? `Connecting you with ${persona.agentName}…`
                      : `Pick an engine, then press Start to talk directly with ${persona.agentName}.`}
                  </p>
                  <div className="opening-cue">
                    <span className="eyebrow">TRY SAYING</span>
                    <blockquote>“{persona.opening}”</blockquote>
                  </div>

                  <div className="persona-instruction-card">
                    <div className="persona-instruction-header">
                      <div className="instruction-header-left">
                        <span className="eyebrow">SYSTEM INSTRUCTIONS · {persona.agentName.toUpperCase()}</span>
                        {settings.instructions && (
                          <span className="customized-indicator-pill">Customized</span>
                        )}
                      </div>
                      <div className="instruction-header-right">
                        {promptLocked ? (
                          <span className="architecture-lock-pill" title="This prompt is generated by the backend phase engine. Edits here would be discarded on connect.">
                            <Lock size={12} />
                            <span>Architecture managed</span>
                          </span>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="edit-prompt-btn-pill"
                              disabled={active}
                              onClick={() => {
                                if (!settings.instructions) {
                                  update("instructions", presetPrompt);
                                }
                                setShowInlineEditor((prev) => !prev);
                              }}
                            >
                              <Edit3 size={12} />
                              <span>{showInlineEditor ? "Close Editor" : (settings.instructions ? "Edit Custom Prompt" : "Edit / Customize")}</span>
                            </button>
                            {settings.instructions && (
                              <button
                                type="button"
                                className="reset-prompt-btn-pill"
                                disabled={active}
                                onClick={() => {
                                  update("instructions", "");
                                  setShowInlineEditor(false);
                                }}
                              >
                                <RotateCcw size={12} />
                                <span>Reset</span>
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </div>

                    {showInlineEditor && !promptLocked ? (
                      <div className="main-prompt-editor">
                        <Textarea
                          value={settings.instructions}
                          onChange={(e) => update("instructions", e.target.value)}
                          disabled={active}
                          maxLength={16000}
                          rows={4}
                          className="main-prompt-textarea"
                          placeholder="Enter custom persona prompt..."
                          autoFocus
                        />
                        <div className="main-prompt-footer">
                          <span className="field-hint">
                            {estimateTokens(settings.instructions).toLocaleString()} / 4,000 tokens · Replaces default preset in Gemini Live and Cascade
                          </span>
                        </div>
                      </div>
                    ) : (
                      <>
                        <p className="persona-prompt-preview">
                          {previewPrompt}
                        </p>
                        {promptLocked && persona.architectureNote && (
                          <p className="architecture-note">
                            <Zap size={11} />
                            <span>{persona.architectureNote}</span>
                          </p>
                        )}
                      </>
                    )}

                  </div>
                </>
              )}
            </motion.div>
          ) : (
            <div className="message-list" key="messages">
              {messages.map((message, idx) => {
                const isFirstInGroup = idx === 0 || messages[idx - 1].role !== message.role;
                const firstCreatedAt = messages[0]?.createdAt;
                const relativeTime = firstCreatedAt && message.createdAt
                  ? `+${String(Math.floor((message.createdAt - firstCreatedAt) / 60000)).padStart(2, "0")}:${String(
                      Math.floor(((message.createdAt - firstCreatedAt) % 60000) / 1000)
                    ).padStart(2, "0")}`
                  : message.time;

                return (
                  <motion.article
                    layout={!reduced}
                    initial={{ opacity: 0, y: reduced ? 0 : 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    key={message.id}
                    className={`message message-${message.role} ${!isFirstInGroup ? "is-grouped" : ""}`}
                  >
                    <span className="message-avatar">
                      {isFirstInGroup ? (
                        message.role === "assistant" ? (
                          <PersonaAvatar key={persona.id} persona={persona} className="transcript-portrait" />
                        ) : (
                          <Mic size={15} />
                        )
                      ) : (
                        <span className="message-avatar-spacer" />
                      )}
                    </span>
                    <div className="message-content">
                      {isFirstInGroup && (
                        <div className="message-meta">
                          <strong>{message.role === "assistant" ? persona.agentName : "You"}</strong>
                          <time>{relativeTime}</time>
                        </div>
                      )}
                      <p>{message.text}</p>

                    {/* Latency & Telemetry Badges */}
                    {message.role === "user" && message.metrics?.sttLatency !== undefined && (
                      <div className="bubble-latency stt-badge">
                        <Zap size={11} />
                        <span>STT: {Math.round(message.metrics.sttLatency * 1000)}ms</span>
                      </div>
                    )}

                    {message.role === "assistant" && (
                      <div className="bubble-latency-group">
                        {settings.engine === "live" ? (
                          message.metrics?.llmLatency !== undefined ? (
                            <div className="bubble-latency live-badge">
                              <Zap size={11} />
                              <span>Live TTFB: {Math.round(message.metrics.llmLatency * 1000)}ms</span>
                              {message.metrics.usage?.total_token_count ? (
                                <span className="token-tag">{message.metrics.usage.total_token_count} tok</span>
                              ) : null}
                              {isLivePricingEligible(settings.engine, settings.model) &&
                                message.metrics?.turnCostUSD !== undefined &&
                                message.metrics.turnCostUSD > 0 && (
                                  <span className="cost-tag" title="Turn cost (audio/text tokens)">
                                    {formatCost(message.metrics.turnCostUSD)}
                                  </span>
                                )}
                            </div>
                          ) : null
                        ) : (
                          (message.metrics?.sttLatency !== undefined ||
                            message.metrics?.llmLatency !== undefined ||
                            message.metrics?.ttsLatency !== undefined) ? (
                            <div className="bubble-latency cascade-badge">
                              {message.metrics.sttLatency !== undefined && (
                                <span>STT: {Math.round(message.metrics.sttLatency * 1000)}ms</span>
                              )}
                              {message.metrics.sttLatency !== undefined &&
                                (message.metrics.llmLatency !== undefined || message.metrics.ttsLatency !== undefined) && (
                                  <span className="sep">|</span>
                                )}
                              {message.metrics.llmLatency !== undefined && (
                                <span>⚡ LLM TTFB: {Math.round(message.metrics.llmLatency * 1000)}ms</span>
                              )}
                              {message.metrics.ttsLatency !== undefined && <span className="sep">|</span>}
                              {message.metrics.ttsLatency !== undefined && (
                                <span>TTS: {Math.round(message.metrics.ttsLatency * 1000)}ms</span>
                              )}
                              {message.metrics.usage?.total_token_count ? (
                                <span className="token-tag">{message.metrics.usage.total_token_count} tok</span>
                              ) : null}
                            </div>
                          ) : null
                        )}
                        {message.metrics?.interruptedMs !== undefined && (
                          <div className="bubble-latency interrupted-badge">
                            ⚡ Interrupted after {Math.round(message.metrics.interruptedMs)}ms
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </motion.article>
              );
            })}
              {partialUser && (
                <div className="partial-message">
                  <span className="partial-pulse" />
                  <span>{partialUser}</span>
                </div>
              )}
              {active && phase === "thinking" && (
                <div className="thinking-indicator">
                  <span />
                  <span />
                  <span />
                  <span className="sr-only">{persona.agentName} is thinking</span>
                </div>
              )}
            </div>
          )}
        </AnimatePresence>
      </div>

      <div className="transcript-footer">
        <span>
          {active && <span className="status-dot is-active" />}
          {active ? `Live transcript · ${engineName}` : ""}
        </span>
        <div>
          <span className="session-clock">Total time: {duration}</span>
          <span
            title={
              `Input ${totalIn(tokenSplit).toLocaleString()} = audio ${tokenSplit.audioIn.toLocaleString()}` +
              ` + text ${tokenSplit.textIn.toLocaleString()}` +
              (tokenSplit.residualIn ? ` + ${tokenSplit.residualIn.toLocaleString()} unattributed by the server` : "") +
              `\nOutput ${totalOut(tokenSplit).toLocaleString()} = audio ${tokenSplit.audioOut.toLocaleString()}` +
              ` + text ${tokenSplit.textOut.toLocaleString()}` +
              (tokenSplit.residualOut ? ` + ${tokenSplit.residualOut.toLocaleString()} unattributed` : "")
            }
          >
            Tokens: {tokenCount.toLocaleString()}
            {tokenCount > 0 && (
              <span className="token-split">
                {" ("}
                <span className="tok-dir">in {formatTokens(totalIn(tokenSplit))}</span>
                <span className="tok-modality">
                  {" "}aud {formatTokens(tokenSplit.audioIn)} · txt {formatTokens(tokenSplit.textIn)}
                  {tokenSplit.residualIn > 0 && <> · ?{formatTokens(tokenSplit.residualIn)}</>}
                </span>
                {" | "}
                <span className="tok-dir">out {formatTokens(totalOut(tokenSplit))}</span>
                <span className="tok-modality">
                  {" "}aud {formatTokens(tokenSplit.audioOut)} · txt {formatTokens(tokenSplit.textOut)}
                </span>
                {")"}
              </span>
            )}
          </span>
          <span title="Total session live cost">Live cost: {formatCost(sessionCostUSD)}</span>
          {latency !== null && (
            <span title="Measured from user transcript arrival to first response audio">
              Response {(latency / 1000).toFixed(2)}s
            </span>
          )}
          {/* Lives here since the heading row was removed — this is now the only
              place session-wide controls and readouts belong. */}
          <Button
            variant="ghost"
            size="icon"
            className="footer-copy"
            onClick={() => void copyTranscript()}
            disabled={!messages.length}
            aria-label={copied ? "Transcript copied" : "Copy transcript"}
          >
            {copied ? <Check size={15} /> : <Copy size={15} />}
          </Button>
        </div>
      </div>
    </section>
  );
}
