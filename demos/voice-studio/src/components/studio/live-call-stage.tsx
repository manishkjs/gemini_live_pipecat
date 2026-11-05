import { useCallback, useEffect, useRef, useState } from "react";
import type { VoiceStudio } from "@/hooks/use-voice-session";
import {
  formatCents,
  formatVoiceShortLabel,
  getPersonaCastRole,
  resolveStreamingAssistantState,
} from "@/lib/call-console";
import { accumulateSplit, EMPTY_TOKEN_SPLIT, totalIn, totalOut } from "@/lib/pricing";
import type { Message } from "@/lib/studio-types";
import { isAvatarActive } from "@/lib/voice-session";
import AvatarStagePanel from "./avatar-stage-panel";
import { SlidersIcon } from "./console-icons";

interface LiveCallStageProps {
  readonly studio: VoiceStudio;
}

function TurnMetricChips({
  message,
  isStreamingAssistant,
  isCascade,
}: {
  readonly message: Message;
  readonly isStreamingAssistant: boolean;
  readonly isCascade: boolean;
}) {
  const metrics = message.metrics;
  if (message.role === "user") {
    if (metrics?.sttLatency === undefined) return null;
    const sttMs = Math.round(metrics.sttLatency * 1000);
    return (
      <div className="chips">
        <span className={`chip ${sttMs < 500 ? "fast" : "warn"}`}>STT {sttMs}ms</span>
      </div>
    );
  }

  const ttfbMs = metrics?.llmLatency !== undefined ? Math.round(metrics.llmLatency * 1000) : null;
  const sttMs = metrics?.sttLatency !== undefined ? Math.round(metrics.sttLatency * 1000) : null;
  const ttsMs = metrics?.ttsLatency !== undefined ? Math.round(metrics.ttsLatency * 1000) : null;
  const split = metrics?.usage ? accumulateSplit(EMPTY_TOKEN_SPLIT, metrics.usage) : null;
  const inTok = split ? totalIn(split) : 0;
  const outTok = split ? totalOut(split) : 0;
  const cacheTok = split ? split.cachedIn : 0;
  const hasCost = typeof metrics?.turnCostUSD === "number" && metrics.turnCostUSD > 0;

  if (!isStreamingAssistant && ttfbMs === null && !split && !hasCost && metrics?.interruptedMs === undefined) {
    return null;
  }

  return (
    <div className="chips">
      {isStreamingAssistant && <span className="chip status">Speaking now</span>}
      {ttfbMs !== null && (
        <span className={`chip ${ttfbMs < 500 ? "fast" : "warn"}`}>TTFB {ttfbMs}ms</span>
      )}
      {isCascade && (sttMs !== null || ttfbMs !== null || ttsMs !== null) && (
        <span className="chip">
          STT {sttMs ?? "--"}ms · LLM {ttfbMs ?? "--"}ms · TTS {ttsMs ?? "--"}ms
        </span>
      )}
      {split && (inTok > 0 || outTok > 0) && (
        <span className="chip">
          in {inTok.toLocaleString()} · out {outTok.toLocaleString()}
          {cacheTok > 0 ? ` · cache ${cacheTok.toLocaleString()}` : ""} tok
        </span>
      )}
      {hasCost && metrics?.turnCostUSD !== undefined && (
        <span className="chip">
          {metrics.costEstimated ? "~" : ""}
          {formatCents(metrics.turnCostUSD)}
          {metrics.costIncomplete ? "+" : ""}
        </span>
      )}
      {metrics?.interruptedMs !== undefined && (
        <span className="chip barge">
          Interrupted at {Math.round(metrics.interruptedMs).toLocaleString()}ms
        </span>
      )}
    </div>
  );
}

/** Active and post-call conversation stage with SOP progress pills, optional 9:16 Avatar split, and smooth bubbles. */
export default function LiveCallStage({ studio }: LiveCallStageProps) {
  const {
    active,
    phase,
    muted,
    sound,
    persona,
    settings,
    messages,
    partialUser,
    copied,
    turnCount,
    currentPhase,
    visitedPhases,
    confirmedBooking,
    transcript,
    followTranscript,
    copyTranscript,
    resetToSetup,
  } = studio;

  const [portraitFailed, setPortraitFailed] = useState(false);
  const [scrolledTop, setScrolledTop] = useState(false);
  const [flowOverflowing, setFlowOverflowing] = useState(false);
  const flowRef = useRef<HTMLOListElement | null>(null);

  const showAvatarSplit = isAvatarActive(settings);
  const isCascade = settings.engine === "cascade";
  const roleSubtitle = getPersonaCastRole(persona);

  const syncFlowOverflow = useCallback(() => {
    const el = flowRef.current;
    if (!el) return;
    setFlowOverflowing(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  }, []);

  useEffect(() => {
    syncFlowOverflow();
    const el = flowRef.current;
    const observer =
      el && typeof ResizeObserver !== "undefined" ? new ResizeObserver(syncFlowOverflow) : null;
    if (el && observer) observer.observe(el);
    window.addEventListener("resize", syncFlowOverflow);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", syncFlowOverflow);
    };
  }, [persona.id, syncFlowOverflow]);

  let listenText = "Listening · barge-in ready";
  let listenTone = "";
  if (!active) {
    const endedTurns = turnCount || messages.length;
    listenText = `Call ended · ${endedTurns} ${endedTurns === 1 ? "turn" : "turns"}`;
    listenTone = "ended";
  } else if (phase === "connecting") {
    listenText = "Connecting…";
  } else if (phase === "speaking") {
    listenText = !sound
      ? "Speaking · speaker muted"
      : muted
        ? "Speaking · mic muted"
        : "Speaking · barge-in ready";
  } else if (phase === "thinking") {
    listenText = "Thinking…";
  } else if (muted) {
    listenText = "Mic muted · barge-in paused";
    listenTone = "muted";
  }

  const phaseIds = persona.phaseIds ?? [];
  const journey = persona.journey;
  const activePhaseIdx = currentPhase && phaseIds.length > 0 ? phaseIds.indexOf(currentPhase) : 0;

  const { streamingAssistantIndex, showPendingAssistantTurn } = resolveStreamingAssistantState(
    messages,
    active,
    phase,
  );

  return (
    <div className={`live-wrap${showAvatarSplit ? " is-split" : ""}`}>
      <header className="live-head">
        <div className="lh-left">
          <div className={`lh-ring${active && phase === "speaking" && sound ? " is-talking" : ""}`}>
            {persona.portrait && !portraitFailed ? (
              <img
                src={persona.portrait}
                alt=""
                width={44}
                height={44}
                onError={() => setPortraitFailed(true)}
              />
            ) : (
              <SlidersIcon size={18} />
            )}
          </div>
          <div>
            <h1 className="lh-name">
              {persona.id === "custom" ? persona.name : persona.agentName}{" "}
              <span className="lh-sub">
                · {roleSubtitle} · {formatVoiceShortLabel(settings.voice)}
              </span>
            </h1>
            <div className={`listen-pill${listenTone ? ` ${listenTone}` : ""}`}>{listenText}</div>
          </div>
        </div>

        <div className="lh-right">
          {journey.length > 0 && (
            <ol
              ref={flowRef}
              tabIndex={0}
              className={`flow-pills scroll-area${flowOverflowing ? " is-overflowing" : ""}`}
              aria-label="Scenario progress"
              onScroll={syncFlowOverflow}
            >
              {journey.map((stepTitle, idx) => {
                const phaseId = phaseIds[idx];
                const isNow = phaseIds.length > 0 ? idx === activePhaseIdx : idx === 0 && active;
                const isDone =
                  phaseIds.length > 0
                    ? (phaseId ? visitedPhases.includes(phaseId) && !isNow : idx < activePhaseIdx)
                    : false;
                return (
                  <li
                    key={`${stepTitle}-${idx}`}
                    className={`flow-pill${isNow ? " now" : isDone ? " done" : ""}`}
                    aria-current={isNow ? "step" : undefined}
                  >
                    <b>{idx + 1}</b>
                    <span>{stepTitle}</span>
                  </li>
                );
              })}
            </ol>
          )}

          {messages.length > 0 && (
            <button type="button" className="ghost-btn" onClick={() => void copyTranscript()}>
              {copied ? "Copied" : "Copy"}
            </button>
          )}
          {!active && (
            <button type="button" className="ghost-btn" id="btn-back-setup" onClick={resetToSetup}>
              Back to setup
            </button>
          )}
        </div>
      </header>

      {showAvatarSplit && <AvatarStagePanel studio={studio} />}

      <div
        ref={transcript}
        id="transcript"
        className={`transcript scroll-area${scrolledTop ? " is-scrolled-top" : ""}`}
        role="log"
        aria-live="polite"
        aria-label="Conversation transcript"
        onScroll={(e) => {
          const el = e.currentTarget;
          setScrolledTop(el.scrollTop > 6);
          const nearBottom = el.scrollHeight - el.clientHeight - el.scrollTop < 48;
          followTranscript.current = nearBottom;
        }}
      >
        <div className="transcript-inner">
          {messages.length === 0 && !partialUser && !showPendingAssistantTurn && (
            <div className="transcript-empty">
              {phase === "connecting"
                ? `Connecting to ${persona.agentName}…`
                : `Connected. Speak naturally or greet ${persona.agentName} to begin.`}
            </div>
          )}

          {messages.map((msg, idx) => {
            const isUser = msg.role === "user";
            const isStreamingAssistant = !isUser && idx === streamingAssistantIndex;
            return (
              <div key={msg.id} className={`turn${isUser ? " user" : ""}`}>
                <div className="turn-who">
                  <b>{isUser ? "You" : persona.agentName}</b>
                  <span>{msg.offsetLabel ?? msg.time}</span>
                </div>
                <div className="bubble">{msg.text}</div>
                <TurnMetricChips
                  message={msg}
                  isStreamingAssistant={isStreamingAssistant}
                  isCascade={isCascade}
                />
              </div>
            );
          })}

          {partialUser && (
            <div className="turn user">
              <div className="turn-who">
                <b>You</b>
                <span>speaking…</span>
              </div>
              <div className="bubble is-partial">{partialUser}</div>
            </div>
          )}

          {showPendingAssistantTurn && (
            <div className="turn" data-pending-assistant="true">
              <div className="turn-who">
                <b>{persona.agentName}</b>
                <span>speaking…</span>
              </div>
              <div className="bubble is-partial">…</div>
              <div className="chips">
                <span className="chip status">Speaking now</span>
              </div>
            </div>
          )}

          {confirmedBooking && (
            <div className="booking-card" role="status">
              <div className="booking-card-title">Booking Confirmed</div>
              <div className="booking-card-meta">
                {[
                  confirmedBooking.booking_id ? `Ref ${confirmedBooking.booking_id}` : "",
                  confirmedBooking.center_name ?? "",
                  confirmedBooking.vehicle_variant ?? "",
                  confirmedBooking.date ?? "",
                  confirmedBooking.time ?? "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
