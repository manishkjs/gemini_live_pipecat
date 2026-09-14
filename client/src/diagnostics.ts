interface DiagnosticLogEntry {
  timestamp: string;
  level: string;
  message: string;
  ttfb_ms?: number | null;
}

class DiagnosticsApp {
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
    this.initElements();
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
        await fetch("/api/logs/clear", { method: "POST" });
        this.allLogs = [];
        this.renderLogs();
      } catch (e) {
        console.error("Failed to clear logs:", e);
      }
    });
  }

  private async fetchTelemetry() {
    try {
      // Fetch Logs
      const res = await fetch("/api/logs?limit=500");
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
      const traceRes = await fetch("/api/trace/current");
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
    const totalStat = summary.total_turnaround || {};
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
    let stageLabel = "Total Turnaround (E2E)";
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
    if (badgeEl) badgeEl.textContent = `${activeStat.count || 0} Turns (${stageLabel})`;

    const tbody = document.getElementById("full-latency-breakdown-tbody");
    if (tbody) {
      const rows = [
        { stageKey: "total", name: "🌟 Total Turnaround (End-to-End)", stat: totalStat, color: "#f472b6" },
        { stageKey: "llm", name: "🧠 LLM TTFB (Reasoning Stream)", stat: llmStat, color: "#c084fc" },
        { stageKey: "stt", name: "🎙️ STT Latency (Cloud Speech v2 Chirp)", stat: sttStat, color: "#fbbf24" },
        { stageKey: "tts", name: "🔊 TTS Latency (Audio Synthesis)", stat: ttsStat, color: "#4ade80" },
        { stageKey: "live_ttfb", name: "⚡ Gemini Live TTFB (Native Audio)", stat: liveStat, color: "#38bdf8" },
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
    let ttfbSum = 0;
    let ttfbCount = 0;
    let turns = 0;
    let interrupts = 0;
    let tools = 0;
    let tokens = 0;
    let inTokens = 0;
    let outTokens = 0;

    if (latencySummary) {
      this.renderLatencyBenchmarks(latencySummary);
    }

    for (const log of this.allLogs) {
      const msg = log.message || "";
      if (log.ttfb_ms) {
        ttfbSum += log.ttfb_ms;
        ttfbCount++;
      } else if (msg.includes("TTFB") || msg.includes("Latency") || msg.includes("turnaround")) {
        const match = msg.match(/(\d+(\.\d+)?)\s*ms/);
        if (match) {
          ttfbSum += parseFloat(match[1]);
          ttfbCount++;
        }
      }

      if (msg.includes("User Speech") || msg.includes("Bot Response")) {
        turns++;
      }
      if (msg.includes("Interrupted") || msg.includes("Interruption")) {
        interrupts++;
      }
      if (msg.includes("Tool Output") || msg.includes("Function call")) {
        tools++;
      }
      if (msg.includes("Turn Token Usage") || msg.includes("LLM Token Usage")) {
        const totalMatch = msg.match(/Total:\s*(\d+)/);
        const promptMatch = msg.match(/Prompt:\s*(\d+)/);
        const respMatch = msg.match(/Response:\s*(\d+)/);
        if (totalMatch) tokens += parseInt(totalMatch[1], 10);
        if (promptMatch) inTokens += parseInt(promptMatch[1], 10);
        if (respMatch) outTokens += parseInt(respMatch[1], 10);
      }
    }

    if (this.ttfbKpi) {
      this.ttfbKpi.textContent = ttfbCount > 0 ? `${Math.round(ttfbSum / ttfbCount)} ms` : "-- ms";
    }
    if (this.turnsKpi) this.turnsKpi.textContent = `${Math.ceil(turns / 2)}`;
    if (this.interruptsKpi) this.interruptsKpi.textContent = `${interrupts}`;
    if (this.toolsKpi) this.toolsKpi.textContent = `${tools}`;
    if (this.tokensKpi) this.tokensKpi.textContent = `${tokens.toLocaleString()}`;
    if (this.tokensSubKpi) this.tokensSubKpi.textContent = `In: ${inTokens.toLocaleString()} | Out: ${outTokens.toLocaleString()}`;
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
