import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { stageLabel, formatCacheHit, type CascadeCost } from "@/lib/cascade-cost";
import {
  computeTurnTtfbSeconds,
  formatCents,
  formatLatencySeconds,
  formatSessionCents,
  formatVoiceShortLabel,
  isFastTtfbSeconds,
} from "@/lib/call-console";
import {
  LOG_HEIGHT,
  clampLogHeight,
  dragLogHeight,
  keyLogHeight,
  readStoredLogHeight,
  toggleLogHeight,
  writeStoredLogHeight,
} from "@/lib/log-resize";
import type { Persona } from "@/lib/personas";
import { getLiveRateCard, totalIn, totalOut, type TokenSplit } from "@/lib/pricing";
import { diagnosticHeaders } from "@/lib/session-diagnostics";
import type { Message } from "@/lib/studio-types";
import type { UserEmotionReading } from "@/lib/pipecat-session";
import type { SessionSettings } from "@/lib/voice-session";

interface SessionCostBoundsView {
  readonly minUSD: number | null;
  readonly maxUSD: number | null;
  readonly estimated: boolean;
  readonly complete: boolean;
  readonly incomplete: boolean;
}

const CASCADE_STAGE_TITLES = {
  stt: "STT",
  llm: "LLM",
  tts: "TTS",
} as const;

interface LatencyStat {
  count: number;
  p50?: number;
  p90?: number;
  p95?: number;
  mean?: number;
  min?: number;
  max?: number;
}

interface LatencySummary {
  live_ttfb?: LatencyStat;
  llm?: LatencyStat;
  stt?: LatencyStat;
  tts?: LatencyStat;
  vad_stop_to_first_server_audio?: LatencyStat;
  turns?: Array<{ stage?: string; turn_id?: number; status?: string }>;
}

interface DiagnosticLog {
  timestamp: string;
  level: string;
  message: string;
  event_type?: string;
}

type StageKey = "total" | "llm" | "stt" | "tts" | "live_ttfb";
type LogFilter = "ALL" | "INFO" | "WARNING" | "ERROR";

export interface ObservabilityDrawerProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly backendUrl: string;
  readonly sessionId?: string;
  readonly engine?: "live" | "cascade";
  readonly active?: boolean;
  readonly isMobileModal?: boolean;
  readonly inert?: boolean;
  readonly persona?: Persona;
  readonly settings?: SessionSettings;
  readonly messages?: readonly Message[];
  readonly sessionTurnCount?: number;
  readonly sessionTokens?: number;
  readonly sessionTokenSplit?: TokenSplit;
  readonly sessionCost?: number;
  readonly sessionCostBounds?: SessionCostBoundsView;
  readonly cascadeCost?: CascadeCost | null;
  readonly sessionInterrupts?: number;
  readonly visitCount?: number | null;
  readonly liveEmotion?: UserEmotionReading | null;
  readonly emotionStats?: {
    readonly count: number;
    readonly totalInputTokens: number;
    readonly lastLatencyMs: number | null;
  };
}

function computeClientPercentiles(values: readonly number[]): LatencyStat {
  if (values.length === 0) return { count: 0 };
  const sorted = [...values].sort((a, b) => a - b);
  const pick = (q: number): number => {
    const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * q) - 1));
    return Math.round(sorted[idx]);
  };
  return {
    count: sorted.length,
    p50: pick(0.5),
    p90: pick(0.9),
    min: Math.round(sorted[0]),
    max: Math.round(sorted[sorted.length - 1]),
  };
}

function ttfbToneClass(
  ms: number | undefined,
  count: number,
  engine: "live" | "cascade",
  isTtfbStage: boolean,
): string {
  if (count <= 0 || ms === undefined) return "";
  if (isTtfbStage) {
    return isFastTtfbSeconds(ms / 1000, engine) ? "fast" : "warn";
  }
  return ms < 500 ? "fast" : "warn";
}

function formatLatencyStat(
  ms: number | undefined,
  count: number,
  isTtfbStage: boolean,
): string {
  if (count <= 0 || ms === undefined) return "—";
  if (isTtfbStage) {
    return formatLatencySeconds(ms / 1000);
  }
  return `${Math.round(ms)}ms`;
}

function faderStyle(ratio: number): CSSProperties {
  const clamped = Math.max(0, Math.min(100, Math.round(ratio * 100)));
  return { width: `${clamped}%` };
}

/** Docked right-hand Session console (and responsive mobile sheet) for live voice telemetry. */
export default function ObservabilityDrawer({
  open,
  onClose,
  backendUrl,
  sessionId,
  engine = "live",
  active = false,
  isMobileModal = false,
  inert = false,
  persona,
  settings,
  messages = [],
  sessionTurnCount = 0,
  sessionTokens = 0,
  sessionTokenSplit,
  sessionCost = 0,
  sessionCostBounds,
  cascadeCost = null,
  sessionInterrupts = 0,
  visitCount = null,
  liveEmotion = null,
  emotionStats,
}: ObservabilityDrawerProps) {
  const scope = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  const [logs, setLogs] = useState<DiagnosticLog[]>([]);
  const [latencySummary, setLatencySummary] = useState<LatencySummary | null>(null);
  const [traceUrl, setTraceUrl] = useState<string>(
    "https://smith.langchain.com/o/default/projects/p/gemini-live-pipecat",
  );
  const [selectedStage, setSelectedStage] = useState<StageKey>(
    engine === "live" ? "live_ttfb" : "total",
  );
  const [activeFilter, setActiveFilter] = useState<LogFilter>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [copiedTrace, setCopiedTrace] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [telemetryError, setTelemetryError] = useState(false);
  const logScrollRef = useRef<HTMLDivElement | null>(null);
  const railRef = useRef<HTMLElement | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [logHeight, setLogHeight] = useState<number>(() =>
    typeof window === "undefined"
      ? LOG_HEIGHT.initial
      : readStoredLogHeight(() => window.localStorage, window.innerHeight),
  );
  const logDragRef = useRef<{ startY: number; startHeight: number } | null>(null);

  useEffect(() => {
    writeStoredLogHeight(() => window.localStorage, logHeight);
  }, [logHeight]);

  useEffect(() => {
    const onResize = () => {
      setLogHeight((h) => clampLogHeight(h, window.innerHeight));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    const el = railRef.current;
    if (!el) return;
    (el as HTMLElement & { inert?: boolean }).inert = inert;
  }, [inert]);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    };
  }, []);

  const onLogHandlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      logDragRef.current = { startY: e.clientY, startHeight: logHeight };
    },
    [logHeight],
  );

  const onLogHandlePointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const drag = logDragRef.current;
    if (!drag) return;
    setLogHeight(dragLogHeight(drag.startHeight, drag.startY, e.clientY, window.innerHeight));
  }, []);

  const onLogHandlePointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    logDragRef.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
  }, []);

  const onLogHandleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (keyLogHeight(LOG_HEIGHT.initial, e.key, window.innerHeight) === null) return;
    e.preventDefault();
    setLogHeight((h) => keyLogHeight(h, e.key, window.innerHeight) ?? h);
  }, []);

  useEffect(() => {
    if (!open || !sessionId) {
      setLogs([]);
      setLatencySummary(null);
      return;
    }

    const base = backendUrl.replace(/\/$/, "");
    let mounted = true;

    const fetchTelemetry = async () => {
      try {
        const [logsRes, traceRes] = await Promise.allSettled([
          fetch(`${base}/api/logs?limit=500${scope}`, { headers: diagnosticHeaders(sessionId) }),
          fetch(`${base}/api/trace/current?${scope.replace(/^&/, "")}`, {
            headers: diagnosticHeaders(sessionId),
          }),
        ]);

        if (mounted && logsRes.status === "fulfilled" && logsRes.value.ok) {
          const data = (await logsRes.value.json()) as {
            logs?: DiagnosticLog[];
            latency_summary?: LatencySummary;
          };
          if (Array.isArray(data.logs)) {
            setLogs(data.logs);
          }
          if (data.latency_summary) {
            setLatencySummary(data.latency_summary);
          }
          setTelemetryError(false);
        } else if (mounted) {
          setTelemetryError(true);
        }

        if (mounted && traceRes.status === "fulfilled" && traceRes.value.ok) {
          const tData = (await traceRes.value.json()) as { trace_url?: string };
          if (tData.trace_url) {
            setTraceUrl(tData.trace_url);
          }
        }
      } catch {
        if (mounted) setTelemetryError(true);
      }
    };

    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      await fetchTelemetry();
      if (mounted) {
        timer = setTimeout(() => {
          void poll();
        }, 1500);
      }
    };
    void poll();

    return () => {
      mounted = false;
      if (timer) clearTimeout(timer);
    };
  }, [open, backendUrl, scope, sessionId]);

  useEffect(() => {
    if (logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
    }
  }, [logs]);

  useEffect(() => {
    if (engine === "live" && selectedStage !== "total" && selectedStage !== "live_ttfb") {
      setSelectedStage("live_ttfb");
    } else if (engine === "cascade" && selectedStage === "live_ttfb") {
      setSelectedStage("total");
    }
  }, [engine, selectedStage]);

  const clientTurnTtfbs = useMemo(() => {
    const vals: number[] = [];
    for (const msg of messages) {
      if (msg.role !== "assistant") continue;
      const sec = computeTurnTtfbSeconds(msg.metrics, engine);
      const ms = sec !== null ? Math.round(sec * 1000) : undefined;
      if (ms !== undefined && ms > 0) vals.push(ms);
    }
    return computeClientPercentiles(vals);
  }, [engine, messages]);

  const activeStat = useMemo((): LatencyStat => {
    const fallback = clientTurnTtfbs;
    if (engine === "live") {
      const primary =
        selectedStage === "total"
          ? latencySummary?.vad_stop_to_first_server_audio
          : latencySummary?.live_ttfb;
      return primary && primary.count > 0 ? primary : fallback;
    }
    switch (selectedStage) {
      case "stt":
        return latencySummary?.stt ?? { count: 0 };
      case "llm":
        return latencySummary?.llm ?? { count: 0 };
      case "tts":
        return latencySummary?.tts ?? { count: 0 };
      case "total":
      default:
        return latencySummary?.vad_stop_to_first_server_audio?.count
          ? latencySummary.vad_stop_to_first_server_audio
          : fallback;
    }
  }, [clientTurnTtfbs, engine, latencySummary, selectedStage]);

  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      const upper = log.level.toUpperCase();
      const levelMatches =
        activeFilter === "ALL" ||
        upper === activeFilter ||
        (activeFilter === "WARNING" && upper.includes("WARN"));
      const queryMatches =
        !searchQuery || log.message.toLowerCase().includes(searchQuery.toLowerCase());
      return levelMatches && queryMatches;
    });
  }, [logs, activeFilter, searchQuery]);

  const clearLogs = async () => {
    if (!sessionId) return;
    setIsClearing(true);
    try {
      const base = backendUrl.replace(/\/$/, "");
      const response = await fetch(`${base}/api/logs/clear?${scope.replace(/^&/, "")}`, {
        method: "POST",
        headers: diagnosticHeaders(sessionId),
      });
      if (response.ok) {
        setLogs([]);
        setLatencySummary(null);
      }
    } catch {
      // Ignore transient network errors when clearing diagnostics.
    } finally {
      setIsClearing(false);
    }
  };

  const copyTrace = async () => {
    try {
      await navigator.clipboard.writeText(traceUrl);
      setCopiedTrace(true);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedTrace(false), 1600);
    } catch {
      // Clipboard may be blocked in restricted contexts.
    }
  };

  const hasSessionTelemetry = active || sessionTurnCount > 0 || messages.length > 0 || logs.length > 0;

  const tokenRows = useMemo(() => {
    if (!sessionTokenSplit) return [];
    const inTotal = totalIn(sessionTokenSplit);
    const outTotal = totalOut(sessionTokenSplit);
    const denom = Math.max(1, sessionTokens || inTotal + outTotal);
    if (engine === "live") {
      return [
        { label: "Audio in", value: sessionTokenSplit.audioIn, ratio: sessionTokenSplit.audioIn / denom },
        { label: "Text in", value: sessionTokenSplit.textIn, ratio: sessionTokenSplit.textIn / denom },
        { label: "Cached", value: sessionTokenSplit.cachedIn, ratio: sessionTokenSplit.cachedIn / denom },
        { label: "Audio out", value: sessionTokenSplit.audioOut, ratio: sessionTokenSplit.audioOut / denom },
        { label: "Text out", value: sessionTokenSplit.textOut, ratio: sessionTokenSplit.textOut / denom },
      ].filter((r) => r.value > 0 || r.label === "Audio in" || r.label === "Audio out");
    }
    return [
      { label: "Input", value: inTotal, ratio: inTotal / denom },
      { label: "Cached", value: sessionTokenSplit.cachedIn, ratio: sessionTokenSplit.cachedIn / denom },
      { label: "Output", value: outTotal, ratio: outTotal / denom },
    ];
  }, [engine, sessionTokenSplit, sessionTokens]);

  const costRows = useMemo(() => {
    if (engine === "cascade" && cascadeCost) {
      const totalUsd = Math.max(0.000001, Number(cascadeCost.known_usd || 0));
      return cascadeCost.stages.map((st) => {
        const usd = Number(st.known_usd || 0);
        const cacheTag = formatCacheHit(st);
        const sub = st.disabled ? "off" : cacheTag ?? (st.complete ? "" : stageLabel(st));
        return {
          key: st.stage,
          label: `${CASCADE_STAGE_TITLES[st.stage]}${sub ? ` · ${sub}` : ""}`,
          value: st.disabled ? "off" : formatCents(usd),
          ratio: st.disabled ? 0 : usd / totalUsd,
        };
      });
    }

    if (engine === "live" && sessionTokenSplit && settings) {
      const rate = getLiveRateCard(settings.model);
      if (rate) {
        const uncachedAudioIn = Math.max(0, sessionTokenSplit.audioIn - sessionTokenSplit.cachedIn);
        const audioInUsd = (uncachedAudioIn / 1_000_000) * rate.audioInPerMillion;
        const cachedUsd = (sessionTokenSplit.cachedIn / 1_000_000) * (rate.textInPerMillion * 0.1);
        const textInUsd = (sessionTokenSplit.textIn / 1_000_000) * rate.textInPerMillion;
        const audioOutUsd = (sessionTokenSplit.audioOut / 1_000_000) * rate.audioOutPerMillion;
        const textOutUsd = (sessionTokenSplit.textOut / 1_000_000) * rate.textOutPerMillion;
        const denom = Math.max(0.000001, audioInUsd + cachedUsd + textInUsd + audioOutUsd + textOutUsd);
        return [
          { key: "audio-in", label: "Audio in", value: formatCents(audioInUsd), ratio: audioInUsd / denom },
          { key: "cached-in", label: "Context cache", value: formatCents(cachedUsd), ratio: cachedUsd / denom },
          { key: "text-in", label: "Text / tools in", value: formatCents(textInUsd), ratio: textInUsd / denom },
          { key: "audio-out", label: "Audio out", value: formatCents(audioOutUsd), ratio: audioOutUsd / denom },
          { key: "text-out", label: "Text / thoughts", value: formatCents(textOutUsd), ratio: textOutUsd / denom },
        ].filter((r) => r.ratio > 0 || r.key === "audio-in" || r.key === "audio-out");
      }
    }

    const assistantTurns = messages.filter(
      (m) => m.role === "assistant" && m.metrics?.turnCostUSD !== undefined,
    );
    const totalTurnUsd = Math.max(
      0.000001,
      assistantTurns.reduce((sum, m) => sum + (m.metrics?.turnCostUSD ?? 0), 0),
    );
    return assistantTurns.slice(-5).map((m, idx) => ({
      key: m.id,
      label: `Turn ${idx + 1}`,
      value: formatCents(m.metrics?.turnCostUSD ?? 0),
      ratio: (m.metrics?.turnCostUSD ?? 0) / totalTurnUsd,
    }));
  }, [cascadeCost, engine, messages, sessionTokenSplit, settings]);

  const vadLabel =
    settings?.vadMode === "gemini"
      ? "Server VAD only"
      : settings?.vadMode === "silero"
        ? "Silero local VAD"
        : "Silero + Server VAD";

  return (
    <>
      <div
        className="console-scrim"
        id="console-scrim"
        hidden={!open}
        onClick={onClose}
      />

      <aside
        ref={railRef}
        className="console-rail"
        id="console-rail"
        aria-label="Observability"
        role={isMobileModal ? "dialog" : undefined}
        aria-modal={isMobileModal ? true : undefined}
        hidden={!open}
      >
        <div className="console-head">
          <h2 className="console-title">Observability</h2>
          <button
            type="button"
            className="ghost-btn"
            id="btn-close-console"
            aria-label="Close observability"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        <div className="console-body scroll-area" id="console-body">
          {!hasSessionTelemetry && persona && settings ? (
            <>
              <section className="cs-sec">
                <h3>Session plan</h3>
                <div className="kv">
                  <span className="k">Engine</span>
                  <span className="v">
                    {engine === "cascade" ? "Cascade (STT · LLM · TTS)" : "Gemini Live (Native Audio)"}
                  </span>
                </div>
                <div className="kv">
                  <span className="k">Model</span>
                  <span className="v">
                    {engine === "cascade"
                      ? `${settings.llmModel} · ${settings.ttsModel}`
                      : settings.model}
                  </span>
                </div>
                <div className="kv">
                  <span className="k">Voice</span>
                  <span className="v">{formatVoiceShortLabel(settings.voice)}</span>
                </div>
                <div className="kv">
                  <span className="k">Language</span>
                  <span className="v">{settings.language} · 24 kHz</span>
                </div>
                <div className="kv">
                  <span className="k">VAD</span>
                  <span className="v">{vadLabel}</span>
                </div>
                <div className="kv">
                  <span className="k">Perception</span>
                  <span className="v">
                    {settings.emotionPerception !== false
                      ? "gemini-decision-1 (audio)"
                      : "Off"}
                  </span>
                </div>
                {visitCount !== null && (
                  <div className="kv">
                    <span className="k">Studio visits</span>
                    <span className="v">{visitCount.toLocaleString("en-IN")}</span>
                  </div>
                )}
              </section>

              <section className="cs-sec">
                <h3>Live meters</h3>
                <p className="cs-empty">
                  Audio-to-audio TTFB (P50 / P90 / Max), per-turn input/output/cached token counts,
                  session cost in ¢, and barge-in cuts stream here once the call starts.
                </p>
              </section>
            </>
          ) : (
            <>
              <section className="cs-sec">
                <h3>
                  <span>Audio-to-audio TTFB</span>
                  <span className="mono-pill">
                    {selectedStage === "total" || selectedStage === "live_ttfb"
                      ? engine === "cascade"
                        ? "<1.5s fast"
                        : "<0.5s fast"
                      : "<500ms fast"}
                  </span>
                </h3>
                <div className="cs-stage-pills" role="group" aria-label="Latency stage">
                  {engine === "live" ? (
                    <>
                      <button
                        type="button"
                        className="cs-stage-pill"
                        aria-pressed={selectedStage === "live_ttfb"}
                        onClick={() => setSelectedStage("live_ttfb")}
                      >
                        Live TTFB
                      </button>
                      <button
                        type="button"
                        className="cs-stage-pill"
                        aria-pressed={selectedStage === "total"}
                        onClick={() => setSelectedStage("total")}
                      >
                        VAD → Audio
                      </button>
                    </>
                  ) : (
                    <>
                      {(
                        [
                          ["total", "Total"],
                          ["stt", "STT"],
                          ["llm", "LLM"],
                          ["tts", "TTS"],
                        ] as const
                      ).map(([stageKey, label]) => (
                        <button
                          key={stageKey}
                          type="button"
                          className="cs-stage-pill"
                          aria-pressed={selectedStage === stageKey}
                          onClick={() => setSelectedStage(stageKey)}
                        >
                          {label}
                        </button>
                      ))}
                    </>
                  )}
                </div>
                <div className="pct-row">
                  <div className="pct">
                    <div className="k">P50</div>
                    <div
                      className={`v ${ttfbToneClass(
                        activeStat.p50,
                        activeStat.count,
                        engine,
                        selectedStage === "total" || selectedStage === "live_ttfb",
                      )}`}
                    >
                      {formatLatencyStat(
                        activeStat.p50,
                        activeStat.count,
                        selectedStage === "total" || selectedStage === "live_ttfb",
                      )}
                    </div>
                  </div>
                  <div className="pct">
                    <div className="k">P90</div>
                    <div
                      className={`v ${ttfbToneClass(
                        activeStat.p90,
                        activeStat.count,
                        engine,
                        selectedStage === "total" || selectedStage === "live_ttfb",
                      )}`}
                    >
                      {formatLatencyStat(
                        activeStat.p90,
                        activeStat.count,
                        selectedStage === "total" || selectedStage === "live_ttfb",
                      )}
                    </div>
                  </div>
                  <div className="pct">
                    <div className="k">Max</div>
                    <div
                      className={`v ${ttfbToneClass(
                        activeStat.max,
                        activeStat.count,
                        engine,
                        selectedStage === "total" || selectedStage === "live_ttfb",
                      )}`}
                    >
                      {formatLatencyStat(
                        activeStat.max,
                        activeStat.count,
                        selectedStage === "total" || selectedStage === "live_ttfb",
                      )}
                    </div>
                  </div>
                </div>
              </section>

              <section className="cs-sec">
                <h3>
                  <span>Tokens</span>
                  <span className="mono-pill">{sessionTokens.toLocaleString()} tok</span>
                </h3>
                {tokenRows.length > 0 ? (
                  tokenRows.map((row) => (
                    <div key={row.label} className="fader">
                      <span className="k">{row.label}</span>
                      <span className="bar">
                        <i style={faderStyle(row.ratio)} />
                      </span>
                      <span className="v">{row.value.toLocaleString()}</span>
                    </div>
                  ))
                ) : (
                  <p className="cs-empty">Waiting for first turn token usage.</p>
                )}
              </section>

              {settings?.emotionPerception !== false && (
                <section className="cs-sec" id="obs-emotion-sec">
                  <h3>
                    <span>Caller perception</span>
                    <span className="mono-pill">gemini-decision-1</span>
                  </h3>
                  {liveEmotion ? (
                    <>
                      <div className="kv">
                        <span className="k">Latest tone</span>
                        <span className="v">
                          {liveEmotion.emoji} {liveEmotion.title} (
                          {Math.round(liveEmotion.confidence * 100)}%)
                        </span>
                      </div>
                      <div className="kv">
                        <span className="k">Classifier</span>
                        <span className="v">
                          {emotionStats?.lastLatencyMs ?? liveEmotion.latencyMs}ms ·{" "}
                          {(emotionStats?.totalInputTokens ?? liveEmotion.inputTokens).toLocaleString()}{" "}
                          in · 0 out tok
                        </span>
                      </div>
                    </>
                  ) : (
                    <p className="cs-empty">
                      Streaming caller vocal tone reads appear as you speak.
                    </p>
                  )}
                </section>
              )}

              <section className="cs-sec">
                <h3>
                  <span>Cost</span>
                  <span className="mono-pill">
                    {formatSessionCents({
                      engine,
                      model: settings?.model ?? "gemini-3.8-live",
                      sessionCostUSD: sessionCost,
                      cascadeCost,
                      incomplete: Boolean(sessionCostBounds?.incomplete),
                      estimated: Boolean(sessionCostBounds?.estimated),
                    })}{" "}
                    session
                  </span>
                </h3>
                {costRows.length > 0 ? (
                  costRows.map((row) => (
                    <div key={row.key} className="fader">
                      <span className="k">{row.label}</span>
                      <span className="bar">
                        <i style={faderStyle(row.ratio)} />
                      </span>
                      <span className="v">{row.value}</span>
                    </div>
                  ))
                ) : (
                  <p className="cs-empty">Per-turn cost in ¢ updates after each reply.</p>
                )}
                {sessionCostBounds &&
                  sessionCostBounds.minUSD !== null &&
                  sessionCostBounds.maxUSD !== null &&
                  sessionCostBounds.maxUSD - sessionCostBounds.minUSD >= 0.0001 && (
                    <div className="kv">
                      <span className="k">Bounds</span>
                      <span className="v">
                        {formatCents(sessionCostBounds.minUSD)}–{formatCents(sessionCostBounds.maxUSD)}
                      </span>
                    </div>
                  )}
                {sessionInterrupts > 0 && (
                  <div className="kv">
                    <span className="k">Barge-ins</span>
                    <span className="v">{sessionInterrupts}</span>
                  </div>
                )}
              </section>

              <section className="cs-sec">
                <h3>
                  <span>Trace</span>
                  <span className="mono-pill">
                    {telemetryError
                      ? "offline"
                      : `${sessionTurnCount} ${sessionTurnCount === 1 ? "turn" : "turns"}`}
                  </span>
                </h3>
                <div className="kv">
                  <span className="k">LangSmith</span>
                  <span className="v">
                    <button type="button" className="ghost-btn" onClick={() => void copyTrace()}>
                      {copiedTrace ? "Copied" : "Copy"}
                    </button>{" "}
                    <a
                      href={traceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="ghost-btn"
                    >
                      Open
                    </a>
                  </span>
                </div>
              </section>

              <section className="cs-sec">
                <h3>
                  <span>Events</span>
                  <span className="mono-pill">
                    {sessionId ? sessionId.slice(0, 10) : "local"}
                  </span>
                </h3>

                <div className="cs-log-controls">
                  <input
                    type="search"
                    className="cs-log-search"
                    placeholder="Filter events"
                    aria-label="Filter diagnostic events"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                  <button
                    type="button"
                    className="ghost-btn"
                    disabled={isClearing || logs.length === 0}
                    onClick={() => void clearLogs()}
                  >
                    Clear
                  </button>
                </div>

                <div className="cs-stage-pills" role="group" aria-label="Event level filter">
                  {(["ALL", "INFO", "WARNING", "ERROR"] as const).map((lvl) => (
                    <button
                      key={lvl}
                      type="button"
                      className="cs-stage-pill"
                      aria-pressed={activeFilter === lvl}
                      onClick={() => setActiveFilter(lvl)}
                    >
                      {lvl}
                    </button>
                  ))}
                </div>

                <div
                  ref={logScrollRef}
                  className="log scroll-area"
                  style={{ height: `${logHeight}px`, maxHeight: `${logHeight}px` }}
                >
                  {filteredLogs.length === 0 ? (
                    <div className="log-line">
                      {logs.length === 0 ? "Waiting for session events..." : "No matching events."}
                    </div>
                  ) : (
                    filteredLogs.map((log, index) => {
                      const upper = log.level.toUpperCase();
                      const tone = upper.includes("ERR")
                        ? "e"
                        : upper.includes("WARN")
                          ? "w"
                          : "";
                      return (
                        <div key={`${log.timestamp}-${index}`} className={`log-line ${tone}`}>
                          {log.timestamp} {upper.padEnd(5, " ")} {log.message}
                        </div>
                      );
                    })
                  )}
                </div>

                <div
                  role="separator"
                  tabIndex={0}
                  aria-orientation="horizontal"
                  aria-label="Resize event log height"
                  className="log-resize-handle"
                  onPointerDown={onLogHandlePointerDown}
                  onPointerMove={onLogHandlePointerMove}
                  onPointerUp={onLogHandlePointerUp}
                  onKeyDown={onLogHandleKeyDown}
                  onDoubleClick={() => setLogHeight((h) => toggleLogHeight(h, window.innerHeight))}
                />
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
