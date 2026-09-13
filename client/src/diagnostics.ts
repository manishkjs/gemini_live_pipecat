interface DiagnosticLogEntry {
  timestamp: string;
  level: string;
  message: string;
  event_type?: string;
  ttfb_ms?: number | null;
}

class DiagnosticsApp {
  private sessionId = "";
  private token = "";
  private logFeed: HTMLElement | null = null;
  private ttfbKpi: HTMLElement | null = null;
  private tokensKpi: HTMLElement | null = null;
  private tokensSubKpi: HTMLElement | null = null;
  private turnsKpi: HTMLElement | null = null;
  private interruptsKpi: HTMLElement | null = null;
  private toolsKpi: HTMLElement | null = null;
  private traceUrlEl: HTMLElement | null = null;
  private langsmithBtn: HTMLAnchorElement | null = null;
  private copyTraceBtn: HTMLButtonElement | null = null;
  private clearLogsBtn: HTMLButtonElement | null = null;
  private searchInput: HTMLInputElement | null = null;

  private allLogs: DiagnosticLogEntry[] = [];
  private activeFilter: string = "ALL";
  private searchQuery: string = "";
  private currentTraceUrl: string = "https://smith.langchain.com/o/default/projects/p/gemini-live-pipecat";
  private selectedLatencyStage: string = "total"; // "total" | "llm" | "stt" | "tts" | "live_ttfb"

  // KPIs
  private lastTtfbList: number[] = [];
  private turnCount = 0;
  private interruptCount = 0;
  private toolCount = 0;
  private totalTokens = 0;
  private promptTokens = 0;
  private responseTokens = 0;

  constructor() {
    const receive = (event: MessageEvent) => {
      if (event.source !== window.opener || event.data?.type !== "diagnostic-access") return;
      if (typeof event.data.sessionId !== "string" || typeof event.data.token !== "string") return;
      this.sessionId = event.data.sessionId;
      this.token = event.data.token;
      window.removeEventListener("message", receive);
      this.fetchTelemetry();
    };
    window.addEventListener("message", receive);
    // This request contains no secret. The opener replies only to this window
    // at its known backend origin; credentials never enter the dashboard URL.
    window.opener?.postMessage({ type: "diagnostic-access-request" }, "*");

    this.initElements();
    if (!window.opener && this.logFeed) this.logFeed.textContent = "Open this dashboard from an active call’s observability panel.";
    this.bindEvents();
    this.startPolling();
  }

  private initElements() {
    this.logFeed = document.getElementById("log-feed");
    this.ttfbKpi = document.getElementById("kpi-ttfb");
    this.tokensKpi = document.getElementById("kpi-tokens");
    this.tokensSubKpi = document.getElementById("kpi-tokens-sub");
    this.turnsKpi = document.getElementById("kpi-turns");
    this.interruptsKpi = document.getElementById("kpi-interrupts");
    this.toolsKpi = document.getElementById("kpi-tools");
    this.traceUrlEl = document.getElementById("active-trace-url");
    this.langsmithBtn = document.getElementById("langsmith-trace-btn") as HTMLAnchorElement;
    this.copyTraceBtn = document.getElementById("copy-trace-btn") as HTMLButtonElement;
    this.clearLogsBtn = document.getElementById("clear-logs-btn") as HTMLButtonElement;
    this.searchInput = document.getElementById("log-search") as HTMLInputElement;
  }

  private bindEvents() {
    // Filter pills for logs
    document.querySelectorAll(".filter-pill").forEach(pill => {
      pill.addEventListener("click", (e) => {
        document.querySelectorAll(".filter-pill").forEach(p => p.classList.remove("active"));
        const target = e.currentTarget as HTMLElement;
        target.classList.add("active");
        this.activeFilter = target.dataset.filter || "ALL";
        this.renderLogs();
      });
    });

    // Stage filter pills for Latency Benchmarks
    const updatePillStyles = (activeStage: string) => {
      this.selectedLatencyStage = activeStage;
      document.querySelectorAll(".full-lat-pill").forEach(p => {
        const stage = (p as HTMLElement).dataset.stage;
        if (stage === activeStage) {
          (p as HTMLElement).style.background = "#0284c7";
          (p as HTMLElement).style.color = "#ffffff";
          (p as HTMLElement).style.borderColor = "#38bdf8";
        } else {
          (p as HTMLElement).style.background = "rgba(30, 41, 59, 0.8)";
          (p as HTMLElement).style.color = "#cbd5e1";
          (p as HTMLElement).style.borderColor = "rgba(255, 255, 255, 0.15)";
        }
      });
      this.fetchTelemetry();
    };

    document.querySelectorAll(".full-lat-pill").forEach(p => {
      p.addEventListener("click", (e) => {
        const stage = (e.currentTarget as HTMLElement).dataset.stage || "total";
        updatePillStyles(stage);
      });
    });

    // Search input
    this.searchInput?.addEventListener("input", () => {
      this.searchQuery = (this.searchInput?.value || "").toLowerCase();
      this.renderLogs();
    });

    // Copy trace button
    this.copyTraceBtn?.addEventListener("click", () => {
      if (this.currentTraceUrl && this.copyTraceBtn) {
        navigator.clipboard.writeText(this.currentTraceUrl);
        const originalText = this.copyTraceBtn.textContent;
        this.copyTraceBtn.textContent = "✅ Copied!";
        setTimeout(() => {
          if (this.copyTraceBtn) this.copyTraceBtn.textContent = originalText;
        }, 2000);
      }
    });

    // Clear logs button
    this.clearLogsBtn?.addEventListener("click", async () => {
      try {
        if (!this.sessionId) return;
        const response = await fetch(`/api/logs/clear?session_id=${encodeURIComponent(this.sessionId)}`, { method: "POST", headers: { "X-Session-Token": this.token } });
        if (!response.ok) throw new Error("Clear failed");
        this.allLogs = [];
        this.renderLogs();
      } catch (e) {
        console.error("Failed to clear logs:", e);
      }
    });
  }

  private async fetchTelemetry() {
    if (!this.sessionId) return;
    const scope = `session_id=${encodeURIComponent(this.sessionId)}`;
    const headers = { "X-Session-Token": this.token };
    try {
      // Fetch Logs
      const res = await fetch(`/api/logs?limit=500&${scope}`, { headers });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data.logs)) {
          this.allLogs = data.logs;
          this.computeMetrics(data.latency_summary);
          this.renderLogs();
        }
      }
    } catch (e) {
      console.debug("Telemetry polling error:", e);
    }

    try {
      // Fetch current trace URL
      const traceRes = await fetch(`/api/trace/current?${scope}`, { headers });
      if (traceRes.ok) {
        const traceData = await traceRes.json();
        if (traceData.trace_url && traceData.trace_url !== this.currentTraceUrl) {
          this.currentTraceUrl = traceData.trace_url;
          if (this.traceUrlEl) this.traceUrlEl.textContent = this.currentTraceUrl;
          if (this.langsmithBtn) this.langsmithBtn.href = this.currentTraceUrl;
        }
      }
    } catch (e) {
      console.debug("Trace URL fetch error:", e);
    }
  }

  private renderLatencyBenchmarks(summary: any) {
    if (!summary) return;

    const liveStat = summary.live_ttfb || {};
    const llmStat = summary.llm || {};
    const sttStat = summary.stt || {};
    const ttsStat = summary.tts || {};
    const totalStat = summary.vad_stop_to_first_server_audio || {};
    const turns = summary.turns || [];

    // Update pill counters
    const cTotal = document.getElementById("full-count-total");
    const cLlm = document.getElementById("full-count-llm");
    const cStt = document.getElementById("full-count-stt");
    const cTts = document.getElementById("full-count-tts");
    const cLive = document.getElementById("full-count-live");
    if (cTotal) cTotal.innerText = String(totalStat.count || 0);
    if (cLlm) cLlm.innerText = String(llmStat.count || 0);
    if (cStt) cStt.innerText = String(sttStat.count || 0);
    if (cTts) cTts.innerText = String(ttsStat.count || 0);
    if (cLive) cLive.innerText = String(liveStat.count || 0);

    // Select stat according to active filter
    let activeStat = totalStat;
    let stageLabel = "VAD stop → first server audio";
    if (this.selectedLatencyStage === "llm") {
      activeStat = llmStat;
      stageLabel = "LLM TTFB (Reasoning Stream)";
    } else if (this.selectedLatencyStage === "stt") {
      activeStat = sttStat;
      stageLabel = "STT Chirp Latency";
    } else if (this.selectedLatencyStage === "tts") {
      activeStat = ttsStat;
      stageLabel = "TTS Audio Synthesis";
    } else if (this.selectedLatencyStage === "live_ttfb") {
      activeStat = liveStat;
      stageLabel = "Gemini Live Native TTFB";
    }

    const titleEl = document.getElementById("full-lat-title");
    if (titleEl) titleEl.innerHTML = `⚡ Session Latency: <span style="color: #f8fafc;">${stageLabel}</span>`;

    const p50El = document.getElementById("full-lat-p50");
    const p90El = document.getElementById("full-lat-p90");
    const p95El = document.getElementById("full-lat-p95");
    const meanEl = document.getElementById("full-lat-mean");
    const minmaxEl = document.getElementById("full-lat-minmax");
    const badgeEl = document.getElementById("full-diag-turn-count-badge");

    if (p50El) p50El.textContent = activeStat.p50 !== undefined && activeStat.count > 0 ? `${activeStat.p50} ms` : "-- ms";
    if (p90El) p90El.textContent = activeStat.p90 !== undefined && activeStat.count > 0 ? `${activeStat.p90} ms` : "-- ms";
    if (p95El) p95El.textContent = activeStat.p95 !== undefined && activeStat.count > 0 ? `${activeStat.p95} ms` : "-- ms";
    if (meanEl) meanEl.textContent = activeStat.mean !== undefined && activeStat.count > 0 ? `${activeStat.mean} ms` : "-- ms";
    if (minmaxEl) minmaxEl.textContent = activeStat.count > 0 ? `Min: ${activeStat.min}ms / Max: ${activeStat.max}ms` : "Min: -- / Max: --";
    if (badgeEl) badgeEl.textContent = `${activeStat.count || 0} Samples (${stageLabel})`;

    const tbody = document.getElementById("full-latency-breakdown-tbody");
    if (tbody) {
      const rows = [
        { stageKey: "total", name: "🌟 VAD stop → first server audio", stat: totalStat, color: "#f472b6" },
        { stageKey: "llm", name: "🧠 LLM TTFB (Reasoning Stream)", stat: llmStat, color: "#c084fc" },
        { stageKey: "stt", name: "🎙️ STT Latency", stat: sttStat, color: "#fbbf24" },
        { stageKey: "tts", name: "🔊 TTS Latency (Audio Synthesis)", stat: ttsStat, color: "#4ade80" },
        { stageKey: "live_ttfb", name: "⚡ Gemini Live first output", stat: liveStat, color: "#38bdf8" },
      ].filter(r => r.stat && r.stat.count > 0);

      if (rows.length > 0) {
        tbody.innerHTML = rows.map(r => `
          <tr class="full-breakdown-row" data-stage="${r.stageKey}" style="border-bottom: 1px solid rgba(255,255,255,0.05); font-family: monospace; cursor: pointer; transition: background 0.15s ease;" onmouseover="this.style.background='rgba(255,255,255,0.05)'" onmouseout="this.style.background='transparent'">
            <td style="padding: 10px 14px; font-weight: 700; color: ${r.color};">${r.name}</td>
            <td style="padding: 10px 14px; font-weight: 800; color: #38bdf8;">${r.stat.p50} ms</td>
            <td style="padding: 10px 14px; font-weight: 800; color: #c084fc;">${r.stat.p90} ms</td>
            <td style="padding: 10px 14px; font-weight: 800; color: #fbbf24;">${r.stat.p95} ms</td>
            <td style="padding: 10px 14px; font-weight: 800; color: #4ade80;">${r.stat.mean} ms</td>
            <td style="padding: 10px 14px; color: #94a3b8;">${r.stat.min} - ${r.stat.max} ms</td>
            <td style="padding: 10px 14px; color: #cbd5e1; font-weight: 700;">${r.stat.count}</td>
          </tr>
        `).join("");

        tbody.querySelectorAll(".full-breakdown-row").forEach(row => {
          row.addEventListener("click", (e) => {
            const stage = (e.currentTarget as HTMLElement).dataset.stage || "total";
            this.selectedLatencyStage = stage;
            document.querySelectorAll(".full-lat-pill").forEach(p => {
              if ((p as HTMLElement).dataset.stage === stage) {
                (p as HTMLElement).style.background = "#0284c7";
                (p as HTMLElement).style.color = "#ffffff";
                (p as HTMLElement).style.borderColor = "#38bdf8";
              } else {
                (p as HTMLElement).style.background = "rgba(30, 41, 59, 0.8)";
                (p as HTMLElement).style.color = "#cbd5e1";
                (p as HTMLElement).style.borderColor = "rgba(255, 255, 255, 0.15)";
              }
            });
            this.renderLatencyBenchmarks(summary);
          });
        });
      }
    }
  }

  private computeMetrics(latencySummary?: any) {
    if (latencySummary) this.renderLatencyBenchmarks(latencySummary);
    const records = latencySummary?.turns ?? [];
    const turns = records.filter((r: any) => r.stage === "turn" && r.turn_id > 0);
    const stat = latencySummary?.live_ttfb?.count ? latencySummary.live_ttfb : latencySummary?.llm;
    if (this.ttfbKpi) this.ttfbKpi.textContent = stat?.count ? `${stat.mean} ms` : "-- ms";
    if (this.turnsKpi) this.turnsKpi.textContent = String(turns.length);
    if (this.interruptsKpi) this.interruptsKpi.textContent = String(turns.filter((r: any) => r.status === "interrupted").length);
    if (this.toolsKpi) this.toolsKpi.textContent = String(this.allLogs.filter(log => log.event_type === "Tool Output").length);
    const usage = latencySummary?.provider_usage;
    if (this.tokensKpi) this.tokensKpi.textContent = usage?.count ? String(usage.total_token_count) : "—";
    if (this.tokensSubKpi) this.tokensSubKpi.textContent = usage?.count
      ? `In: ${usage.prompt_token_count} · Out: ${usage.response_token_count} · retained responses`
      : "No provider usage received";
  }

  private renderLogs() {
    if (!this.logFeed) return;

    const filtered = this.allLogs.filter(log => {
      const msg = (log.message || "").toLowerCase();
      const level = (log.level || "").toUpperCase();

      // Pill filter
      if (this.activeFilter === "ERROR" && level !== "ERROR") return false;
      if (this.activeFilter === "LATENCY" && !msg.includes("ttfb") && !msg.includes("latency") && !msg.includes("stt") && !log.ttfb_ms) return false;
      if (this.activeFilter === "SPEECH" && !msg.includes("user speech") && !msg.includes("bot response")) return false;
      if (this.activeFilter === "TOOL" && !msg.includes("tool")) return false;

      // Text search
      if (this.searchQuery && !msg.includes(this.searchQuery) && !log.timestamp.toLowerCase().includes(this.searchQuery)) {
        return false;
      }

      return true;
    });

    if (filtered.length === 0) {
      this.logFeed.innerHTML = `<div style="color: #64748b; font-size: 13px; text-align: center; padding: 40px 0;">No matching telemetry logs found.</div>`;
      return;
    }

    this.logFeed.innerHTML = filtered.map(log => {
      const msg = log.message || "";
      let levelClass = "level-INFO";
      let levelBadge = log.level || "INFO";

      if (log.level === "ERROR" || msg.includes("Error") || msg.includes("exception")) {
        levelClass = "level-ERROR";
        levelBadge = "ERROR";
      } else if (log.ttfb_ms || msg.includes("TTFB") || msg.includes("Latency")) {
        levelClass = "level-LATENCY";
        levelBadge = "LATENCY";
      } else if (msg.includes("User Speech") || msg.includes("Bot Response")) {
        levelClass = "level-SPEECH";
        levelBadge = msg.includes("User") ? "USER" : "BOT";
      } else if (msg.includes("Tool")) {
        levelClass = "level-TOOL";
        levelBadge = "TOOL";
      }

      const ttfbTag = log.ttfb_ms ? `<span style="color: #fbbf24; font-weight: 700;">⚡ ${log.ttfb_ms}ms</span>` : "";

      return `
        <div class="log-card ${levelClass}">
          <div class="log-meta">
            <span>⏱️ ${log.timestamp}</span>
            <div style="display: flex; gap: 8px; align-items: center;">
              ${ttfbTag}
              <span class="log-badge">${levelBadge}</span>
            </div>
          </div>
          <div class="log-msg">${this.escapeHtml(msg)}</div>
        </div>
      `;
    }).join("");
  }

  private escapeHtml(str: string): string {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  private startPolling() {
    this.fetchTelemetry();
    setInterval(() => this.fetchTelemetry(), 1500);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  new DiagnosticsApp();
});
