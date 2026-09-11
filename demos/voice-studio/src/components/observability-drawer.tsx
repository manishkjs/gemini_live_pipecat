"use client";

import { useEffect, useState, useRef, useMemo } from "react";
import { X, Trash2, Copy, ExternalLink, Search, Check, Activity, Zap, Radio, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";

type LatencyStat = {
  count: number;
  p50?: number;
  p90?: number;
  p95?: number;
  mean?: number;
  min?: number;
  max?: number;
};

type LatencySummary = {
  live_ttfb?: LatencyStat;
  llm?: LatencyStat;
  stt?: LatencyStat;
  tts?: LatencyStat;
  total_turnaround?: LatencyStat;
  turns?: any[];
};

type DiagnosticLog = {
  timestamp: string;
  level: string;
  message: string;
  ttfb_ms?: number | null;
};

type ObservabilityDrawerProps = {
  open: boolean;
  onClose: () => void;
  backendUrl: string;
  /**
   * Scopes the drawer to one demo session. The backend diagnostics buffer is
   * process-global, so without this the drawer shows every concurrent
   * demoer's logs and blends their latency percentiles together.
   */
  sessionId?: string;
  engine?: "live" | "cascade";
  sessionTurnCount?: number;
  sessionTokens?: number;
  sessionCost?: number;
  sessionInterrupts?: number;
};

export default function ObservabilityDrawer({
  open,
  onClose,
  backendUrl,
  sessionId,
  engine = "live",
  sessionTurnCount,
  sessionTokens,
  sessionCost,
  sessionInterrupts,
}: ObservabilityDrawerProps) {
  const scope = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  const [logs, setLogs] = useState<DiagnosticLog[]>([]);
  const [latencySummary, setLatencySummary] = useState<LatencySummary | null>(null);
  const [traceUrl, setTraceUrl] = useState<string>("https://smith.langchain.com/o/default/projects/p/gemini-live-pipecat");
  const [selectedStage, setSelectedStage] = useState<"total" | "llm" | "stt" | "tts" | "live_ttfb">(
    engine === "live" ? "live_ttfb" : "total"
  );
  const [activeFilter, setActiveFilter] = useState<"ALL" | "INFO" | "WARNING" | "ERROR">("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [copiedTrace, setCopiedTrace] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const logScrollRef = useRef<HTMLDivElement | null>(null);
  const autoScrollRef = useRef(true);

  // Poll diagnostic logs and trace info
  useEffect(() => {
    if (!open) return;

    const base = backendUrl.replace(/\/$/, "");
    let mounted = true;

    const fetchTelemetry = async () => {
      try {
        const [logsRes, traceRes] = await Promise.allSettled([
          fetch(`${base}/api/logs?limit=500${scope}`),
          fetch(`${base}/api/trace/current`),
        ]);

        if (mounted && logsRes.status === "fulfilled" && logsRes.value.ok) {
          const data = await logsRes.value.json();
          if (Array.isArray(data.logs)) {
            setLogs(data.logs);
          }
          if (data.latency_summary) {
            setLatencySummary(data.latency_summary);
          }
        }

        if (mounted && traceRes.status === "fulfilled" && traceRes.value.ok) {
          const tData = await traceRes.value.json();
          if (tData.trace_url) {
            setTraceUrl(tData.trace_url);
          }
        }
      } catch (e) {
        console.debug("Telemetry fetch error:", e);
      }
    };

    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 1500);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [open, backendUrl, scope]);

  // Auto-scroll logs
  useEffect(() => {
    if (autoScrollRef.current && logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
    }
  }, [logs]);

  // Aggregate metrics from logs if summary is not yet available
  const aggregatedMetrics = useMemo(() => {
    let turns = 0;
    let interrupts = 0;
    let tools = 0;
    let totalTokens = 0;
    let inTokens = 0;
    let outTokens = 0;

    for (const log of logs) {
      const msg = log.message || "";
      if (msg.includes("User Speech") || msg.includes("Bot Response")) turns++;
      if (msg.includes("Interrupted") || msg.includes("Interruption")) interrupts++;
      if (msg.includes("Tool Output") || msg.includes("Function call")) tools++;
      if (msg.includes("Turn Token Usage") || msg.includes("LLM Token Usage")) {
        const totalMatch = msg.match(/Total:\s*(\d+)/);
        const promptMatch = msg.match(/Prompt:\s*(\d+)/);
        const respMatch = msg.match(/Response:\s*(\d+)/);
        if (totalMatch) totalTokens += parseInt(totalMatch[1], 10);
        if (promptMatch) inTokens += parseInt(promptMatch[1], 10);
        if (respMatch) outTokens += parseInt(respMatch[1], 10);
      }
    }

    const totalStat = latencySummary?.total_turnaround || { count: 0 };
    const llmStat = latencySummary?.llm || { count: 0 };
    const sttStat = latencySummary?.stt || { count: 0 };
    const ttsStat = latencySummary?.tts || { count: 0 };
    const liveStat = latencySummary?.live_ttfb || { count: 0 };

    // Prefer exact session values tracked directly in client session state
    const displayTurns = sessionTurnCount !== undefined && sessionTurnCount > 0
      ? sessionTurnCount
      : (turns > 0 ? Math.ceil(turns / 2) : (engine === "live" ? (liveStat.count || 0) : (totalStat.count || 0)));

    const displayInterrupts = sessionInterrupts !== undefined && sessionInterrupts > 0
      ? sessionInterrupts
      : interrupts;

    const displayTokens = sessionTokens !== undefined && sessionTokens > 0
      ? sessionTokens
      : totalTokens;

    return {
      turns: displayTurns,
      interrupts: displayInterrupts,
      tools,
      totalTokens: displayTokens,
      inTokens,
      outTokens,
      totalStat,
      llmStat,
      sttStat,
      ttsStat,
      liveStat,
    };
  }, [logs, latencySummary, sessionTurnCount, sessionInterrupts, sessionTokens, engine]);

  const clearLogs = async () => {
    setIsClearing(true);
    try {
      const base = backendUrl.replace(/\/$/, "");
      // Scoped so clearing your own view cannot wipe another demoer's history.
      await fetch(`${base}/api/logs/clear?${scope.replace(/^&/, "")}`, { method: "POST" });
      setLogs([]);
      setLatencySummary(null);
    } catch (e) {
      console.error("Failed to clear logs", e);
    } finally {
      setIsClearing(false);
    }
  };

  const copyTrace = async () => {
    try {
      await navigator.clipboard.writeText(traceUrl);
      setCopiedTrace(true);
      setTimeout(() => setCopiedTrace(false), 2000);
    } catch (e) {
      console.error("Failed to copy trace", e);
    }
  };

  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      const levelMatches =
        activeFilter === "ALL" ||
        log.level.toUpperCase() === activeFilter ||
        (activeFilter === "WARNING" && log.level.toUpperCase().includes("WARN"));
      const queryMatches = !searchQuery || (log.message && log.message.toLowerCase().includes(searchQuery.toLowerCase()));
      return levelMatches && queryMatches;
    });
  }, [logs, activeFilter, searchQuery]);

  // For Gemini Live flow, liveStat is used, or fallback to llmStat if backend recorded as llm
  const effectiveLiveStat = (aggregatedMetrics.liveStat?.count || 0) > 0
    ? aggregatedMetrics.liveStat
    : aggregatedMetrics.llmStat;

  useEffect(() => {
    if (engine === "live" && selectedStage !== "total" && selectedStage !== "live_ttfb") {
      setSelectedStage("live_ttfb");
    } else if (engine === "cascade" && selectedStage === "live_ttfb") {
      setSelectedStage("total");
    }
  }, [engine, selectedStage]);

  const activeStat = useMemo(() => {
    if (engine === "live") {
      if (selectedStage === "total") {
        return { label: "Total Turnaround (End-to-End)", stat: aggregatedMetrics.totalStat, color: "#f472b6" };
      }
      return { label: "Gemini Live Native TTFB", stat: effectiveLiveStat, color: "#38bdf8" };
    }

    switch (selectedStage) {
      case "llm":
        return { label: "LLM TTFB (Reasoning Stream)", stat: aggregatedMetrics.llmStat, color: "#c084fc" };
      case "stt":
        return { label: "STT Chirp Latency", stat: aggregatedMetrics.sttStat, color: "#fbbf24" };
      case "tts":
        return { label: "TTS Audio Synthesis", stat: aggregatedMetrics.ttsStat, color: "#4ade80" };
      case "total":
      default:
        return { label: "Total Turnaround (End-to-End)", stat: aggregatedMetrics.totalStat, color: "#f472b6" };
    }
  }, [engine, selectedStage, aggregatedMetrics, effectiveLiveStat]);

  if (!open) return null;

  return (
    <div className="obs-backdrop" onClick={onClose}>
      <aside className="obs-drawer" onClick={(e) => e.stopPropagation()} aria-label="Observability Dashboard">
        {/* Header */}
        <div className="obs-header">
          <div className="obs-title-group">
            <span className="obs-brand-icon">
              <Zap size={18} />
            </span>
            <div>
              <h2>Live Observability & Diagnostics</h2>
              <span className="obs-status-tag">
                <span className="obs-pulse-dot" /> Live Telemetry
              </span>
            </div>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close observability">
            <X size={18} />
          </Button>
        </div>

        <div className="obs-body">
          {/* KPI Dashboard Cards */}
          <div className="obs-kpis">
            <div className="obs-kpi-card">
              <span className="kpi-label">Turns</span>
              <span className="kpi-value">{aggregatedMetrics.turns}</span>
              <span className="kpi-sub">Total user & bot turns</span>
            </div>
            <div className="obs-kpi-card">
              <span className="kpi-label">Interrupts</span>
              <span className="kpi-value" style={{ color: aggregatedMetrics.interrupts > 0 ? "#f59e0b" : "inherit" }}>
                {aggregatedMetrics.interrupts}
              </span>
              <span className="kpi-sub">User speech barge-ins</span>
            </div>
            <div className="obs-kpi-card">
              <span className="kpi-label">Tool Calls</span>
              <span className="kpi-value">{aggregatedMetrics.tools}</span>
              <span className="kpi-sub">Functions executed</span>
            </div>
            <div className="obs-kpi-card">
              <span className="kpi-label">Tokens</span>
              <span className="kpi-value">{aggregatedMetrics.totalTokens.toLocaleString()}</span>
              <span className="kpi-sub">
                In: {aggregatedMetrics.inTokens.toLocaleString()} | Out: {aggregatedMetrics.outTokens.toLocaleString()}
              </span>
            </div>
          </div>

          {/* Active Latency Spotlight Card */}
          <div className="obs-spotlight-card">
            <div className="spotlight-header">
              <div className="spotlight-title">
                <Activity size={16} />
                <span>Session Latency: <strong>{activeStat.label}</strong></span>
              </div>
              <span className="spotlight-count">
                {activeStat.stat.count || 0} Sample{activeStat.stat.count === 1 ? "" : "s"}
              </span>
            </div>

            {/* Stage filter pills */}
            <div className="obs-stage-pills">
              {(engine === "live"
                ? [
                    { id: "total", label: "🌟 Total (E2E)", count: aggregatedMetrics.totalStat.count },
                    { id: "live_ttfb", label: "⚡ Live TTFB", count: effectiveLiveStat.count },
                  ]
                : [
                    { id: "total", label: "🌟 Total (E2E)", count: aggregatedMetrics.totalStat.count },
                    { id: "llm", label: "🧠 LLM TTFB", count: aggregatedMetrics.llmStat.count },
                    { id: "stt", label: "🎙️ STT", count: aggregatedMetrics.sttStat.count },
                    { id: "tts", label: "🔊 TTS", count: aggregatedMetrics.ttsStat.count },
                  ]
              ).map((stage) => (
                <button
                  key={stage.id}
                  className={`stage-pill ${selectedStage === stage.id ? "selected" : ""}`}
                  onClick={() => setSelectedStage(stage.id as any)}
                >
                  {stage.label} <span className="pill-count">{stage.count || 0}</span>
                </button>
              ))}
            </div>

            <div className="spotlight-metrics">
              <div className="metric-box">
                <span className="m-label">p50</span>
                <strong className="m-val" style={{ color: "#38bdf8" }}>
                  {activeStat.stat.p50 !== undefined && activeStat.stat.count > 0 ? `${activeStat.stat.p50} ms` : "-- ms"}
                </strong>
              </div>
              <div className="metric-box">
                <span className="m-label">p90</span>
                <strong className="m-val" style={{ color: "#c084fc" }}>
                  {activeStat.stat.p90 !== undefined && activeStat.stat.count > 0 ? `${activeStat.stat.p90} ms` : "-- ms"}
                </strong>
              </div>
              <div className="metric-box">
                <span className="m-label">p95</span>
                <strong className="m-val" style={{ color: "#fbbf24" }}>
                  {activeStat.stat.p95 !== undefined && activeStat.stat.count > 0 ? `${activeStat.stat.p95} ms` : "-- ms"}
                </strong>
              </div>
              <div className="metric-box">
                <span className="m-label">Mean</span>
                <strong className="m-val" style={{ color: "#4ade80" }}>
                  {activeStat.stat.mean !== undefined && activeStat.stat.count > 0 ? `${activeStat.stat.mean} ms` : "-- ms"}
                </strong>
              </div>
              <div className="metric-box">
                <span className="m-label">Min - Max</span>
                <strong className="m-val" style={{ color: "#94a3b8" }}>
                  {activeStat.stat.count > 0 ? `${activeStat.stat.min} - ${activeStat.stat.max} ms` : "--"}
                </strong>
              </div>
            </div>
          </div>

          {/* Latency Benchmarks Detailed Table */}
          <div className="obs-table-section">
            <h3>Latency Breakdown by Pipeline Stage</h3>
            <div className="table-responsive">
              <table className="obs-table">
                <thead>
                  <tr>
                    <th>Pipeline Stage</th>
                    <th>p50</th>
                    <th>p90</th>
                    <th>p95</th>
                    <th>Mean</th>
                    <th>Range</th>
                    <th>Turns</th>
                  </tr>
                </thead>
                <tbody>
                  {(engine === "live"
                    ? [
                        { id: "live_ttfb", name: "⚡ Gemini Live TTFB (Native Audio)", stat: effectiveLiveStat, color: "#38bdf8" },
                        ...(aggregatedMetrics.totalStat?.count && aggregatedMetrics.totalStat.count > 0
                          ? [{ id: "total", name: "🌟 Total Turnaround (End-to-End)", stat: aggregatedMetrics.totalStat, color: "#f472b6" }]
                          : []),
                      ]
                    : [
                        { id: "total", name: "🌟 Total Turnaround (End-to-End)", stat: aggregatedMetrics.totalStat, color: "#f472b6" },
                        { id: "llm", name: "🧠 LLM TTFB (Reasoning Stream)", stat: aggregatedMetrics.llmStat, color: "#c084fc" },
                        { id: "stt", name: "🎙️ STT Latency (Cloud Speech v2 / AI Studio)", stat: aggregatedMetrics.sttStat, color: "#fbbf24" },
                        { id: "tts", name: "🔊 TTS Latency (Audio Synthesis)", stat: aggregatedMetrics.ttsStat, color: "#4ade80" },
                      ]
                  ).map((row) => (
                    <tr
                      key={row.id}
                      className={selectedStage === row.id ? "active-row" : ""}
                      onClick={() => setSelectedStage(row.id as any)}
                    >
                      <td style={{ color: row.color, fontWeight: 600 }}>{row.name}</td>
                      <td>{row.stat.p50 !== undefined && row.stat.count > 0 ? `${row.stat.p50} ms` : "--"}</td>
                      <td>{row.stat.p90 !== undefined && row.stat.count > 0 ? `${row.stat.p90} ms` : "--"}</td>
                      <td>{row.stat.p95 !== undefined && row.stat.count > 0 ? `${row.stat.p95} ms` : "--"}</td>
                      <td>{row.stat.mean !== undefined && row.stat.count > 0 ? `${row.stat.mean} ms` : "--"}</td>
                      <td>{row.stat.count > 0 ? `${row.stat.min} - ${row.stat.max} ms` : "--"}</td>
                      <td><strong>{row.stat.count || 0}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* LangSmith Active Tracing Card */}
          <div className="obs-trace-card">
            <div className="trace-info">
              <Radio size={16} className="trace-icon" />
              <div>
                <strong>LangSmith Session Trace</strong>
                <p className="trace-url-text">{traceUrl}</p>
              </div>
            </div>
            <div className="trace-actions">
              <Button variant="outline" size="sm" onClick={copyTrace} className="trace-btn">
                {copiedTrace ? <Check size={14} /> : <Copy size={14} />}
                <span>{copiedTrace ? "Copied" : "Copy URL"}</span>
              </Button>
              <Button asChild size="sm" className="trace-btn primary">
                <a href={traceUrl} target="_blank" rel="noreferrer">
                  <span>View Trace</span>
                  <ExternalLink size={14} />
                </a>
              </Button>
            </div>
          </div>

          {/* Diagnostic Log Viewer */}
          <div className="obs-logs-section">
            <div className="logs-header">
              <div className="logs-title">
                <Terminal size={16} />
                <h3>Live Diagnostics Log</h3>
                <span className="log-count">({filteredLogs.length} events)</span>
              </div>
              <div className="logs-controls">
                {/* Search Box */}
                <div className="logs-search">
                  <Search size={14} />
                  <input
                    type="text"
                    placeholder="Filter logs..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                </div>

                {/* Level Filter Pills */}
                <div className="level-pills">
                  {(["ALL", "INFO", "WARNING", "ERROR"] as const).map((lvl) => (
                    <button
                      key={lvl}
                      className={`lvl-pill ${activeFilter === lvl ? "active" : ""}`}
                      onClick={() => setActiveFilter(lvl)}
                    >
                      {lvl}
                    </button>
                  ))}
                </div>

                {/* Clear Logs Button */}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={clearLogs}
                  disabled={isClearing}
                  className="clear-btn"
                  title="Clear in-memory logs"
                >
                  <Trash2 size={14} />
                  <span>Clear</span>
                </Button>
              </div>
            </div>

            <div
              className="log-terminal"
              ref={logScrollRef}
              onScroll={(e) => {
                const el = e.currentTarget;
                autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
              }}
            >
              {filteredLogs.length === 0 ? (
                <div className="log-empty">No diagnostic logs found matching current filter.</div>
              ) : (
                filteredLogs.map((log, idx) => {
                  const lvl = log.level.toUpperCase();
                  const lvlClass = lvl.includes("ERR") ? "lvl-error" : lvl.includes("WARN") ? "lvl-warn" : "lvl-info";
                  return (
                    <div key={idx} className={`log-entry ${lvlClass}`}>
                      <span className="log-time">{log.timestamp}</span>
                      <span className={`log-tag ${lvlClass}`}>{lvl}</span>
                      <span className="log-msg">{log.message}</span>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
