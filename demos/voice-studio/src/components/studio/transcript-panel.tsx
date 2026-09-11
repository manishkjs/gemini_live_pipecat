import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Check, Copy, Edit3, MessageSquare, Mic, RotateCcw, Zap, DollarSign } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { isLivePricingEligible, formatCost, estimateTokens } from "@/lib/pricing";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import PersonaAvatar from "./persona-avatar";

/** Live transcript, per-turn telemetry badges and the empty-state briefing. */
export default function TranscriptPanel({ studio }: { studio: VoiceStudio }) {
  const {
    active, complete, copied, copyTranscript, custom, duration, engineName, followTranscript,
    lastSTT, lastTTFB, latency, messages, partialUser, persona, phase, reduced, sessionCostUSD,
    settings, setShowInlineEditor, showInlineEditor, source, tokenCount, transcript, turnCount,
    update,
  } = studio;

  return (
    <section className="transcript-panel" aria-labelledby="transcript-heading">
      <div className="transcript-heading">
        <div className="transcript-title-row">
          <MessageSquare size={18} />
          <h2 id="transcript-heading">Conversation</h2>
          <span className="transcript-badge">{source === "preview" ? "SCRIPTED PREVIEW" : engineName.toUpperCase()}</span>
          {active && (
            <div className="live-metrics-ticker">
              <span className="ticker-pill">Turns: <strong>{turnCount}</strong></span>
              {lastSTT !== null && <span className="ticker-pill">STT: <strong>{lastSTT}ms</strong></span>}
              {lastTTFB !== null && <span className="ticker-pill">TTFB: <strong>{lastTTFB}ms</strong></span>}
              {tokenCount > 0 && <span className="ticker-pill">Tokens: <strong>{tokenCount}</strong></span>}
              {isLivePricingEligible(settings.engine, settings.model) && sessionCostUSD > 0 && (
                <span className="ticker-pill cost-pill" title="Estimated live session token spend">
                  <DollarSign size={10} />
                  <span>{formatCost(sessionCostUSD)}</span>
                </span>
              )}
            </div>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => void copyTranscript()}
          disabled={!messages.length}
          aria-label={copied ? "Transcript copied" : "Copy transcript"}
        >
          {copied ? <Check size={17} /> : <Copy size={17} />}
        </Button>
      </div>

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
                      : `Select Gemini Live or Cascade on the left to start talking directly with ${persona.agentName}.`}
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
                        <button
                          type="button"
                          className="edit-prompt-btn-pill"
                          disabled={active}
                          onClick={() => {
                            if (!settings.instructions) {
                              update("instructions", persona.prompt);
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
                      </div>
                    </div>

                    {showInlineEditor ? (
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
                      <p className="persona-prompt-preview">
                        {settings.instructions || persona.prompt}
                      </p>
                    )}
                  </div>
                  <div className="journey">
                    <span className="eyebrow">DEMO FOCUS</span>
                    <ol>
                      {persona.journey.map((step, i) => (
                        <li key={step}>
                          <span>{i + 1}</span>
                          {step}
                          {i < persona.journey.length - 1 && <ArrowRight size={13} className="journey-arrow" />}
                        </li>
                      ))}
                    </ol>
                  </div>
                </>
              )}
            </motion.div>
          ) : (
            <div className="message-list" key="messages">
              {messages.map((message) => (
                <motion.article
                  layout={!reduced}
                  initial={{ opacity: 0, y: reduced ? 0 : 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  key={message.id}
                  className={`message message-${message.role}`}
                >
                  <span className="message-avatar">
                    {message.role === "assistant" ? (
                      <PersonaAvatar key={persona.id} persona={persona} className="transcript-portrait" />
                    ) : (
                      <Mic size={15} />
                    )}
                  </span>
                  <div className="message-content">
                    <div className="message-meta">
                      <strong>{message.role === "assistant" ? persona.agentName : "You"}</strong>
                      <time>{message.time}</time>
                    </div>
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
              ))}
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
              {complete && (
                <div className="preview-complete">
                  <Check size={16} />
                  <span>Session complete. Ready to talk again?</span>
                </div>
              )}
            </div>
          )}
        </AnimatePresence>
      </div>

      <div className="transcript-footer">
        <span>
          {(source === "preview" || active) && (
            <span className={`status-dot ${active ? "is-active" : ""}`} />
          )}
          {source === "preview"
            ? "Scripted persona preview · no API calls"
            : active
            ? `Live transcript · ${engineName}`
            : ""}
        </span>
        <div>
          <span className="session-clock">Total time: {duration}</span>
          <span title="Total session tokens consumed">Tokens: {tokenCount.toLocaleString()}</span>
          <span title="Total session live cost">Live cost: {formatCost(sessionCostUSD)}</span>
          {latency !== null && (
            <span title="Measured from user transcript arrival to first response audio">
              Response {(latency / 1000).toFixed(2)}s
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
