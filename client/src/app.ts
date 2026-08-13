import {
  RTVIClient,
  RTVIClientOptions,
  RTVIEvent,
  RTVIMessage,
} from "@pipecat-ai/client-js";
import { WebSocketTransport } from "@pipecat-ai/websocket-transport";

type LogLevel = "info" | "warning" | "error";

const getApiBaseUrl = () => {
  const host = window.location.hostname;
  const port = window.location.port;
  const protocol = window.location.protocol;
  return `${protocol}//${host}${port ? `:${port}` : ""}`;
};

class WebsocketClientApp {
  private rtviClient: RTVIClient | null = null;
  private connectBtn: HTMLButtonElement | null = null;
  private listenBtn: HTMLButtonElement | null = null;
  private stopBtn: HTMLButtonElement | null = null;
  private statusSpan: HTMLElement | null = null;
  private statusIndicator: HTMLElement | null = null;
  private debugLog: HTMLElement | null = null;
  private audioContext: AudioContext | null = null;
  private connectionLight: HTMLElement | null = null;
  private micLight: HTMLElement | null = null;
  private speakerLight: HTMLElement | null = null;
  private voiceStatus: HTMLElement | null = null;
  private listeningIndicator: HTMLElement | null = null;
  private speakingIndicator: HTMLElement | null = null;
  private dotsContainer: HTMLElement | null = null;
  private tabs: NodeListOf<HTMLButtonElement> | null = null;
  private configPanels: NodeListOf<HTMLElement> | null = null;
  private activeTab: string = "gemini-live";
  private selectedBotType: string = "gemini-live";
  private connectedBotType: string = "gemini-live";
  private activePipeline: HTMLElement | null = null;

  // Observability UI Elements
  private toolDefinitionsTextarea: HTMLTextAreaElement | null = null;
  private chatWindow: HTMLElement | null = null;
  private metricTurnCount: HTMLElement | null = null;
  private metricInterruptCount: HTMLElement | null = null;
  private metricToolCallCount: HTMLElement | null = null;
  private metricTokenCount: HTMLElement | null = null;


  // Observability State
  private turnCount = 0;
  private interruptCount = 0;
  private toolCallCount = 0;
  private tokenCount = 0;
  private lastLLMLatency: number | null = null;
  private lastTTSLatency: number | null = null;
  private lastTurnSTTLatency: number | null = null;
  private pendingLLMLatency: number | null = null;
  private pendingTTSLatency: number | null = null;
  private pendingSTTLatency: number | null = null;
  private lastTurnUsage: any = null;
  private lastPromptTokenCount = 0;

  // Voice Data
  private readonly GEMINI_VOICES = [
    { value: "Puck", label: "Puck (Male)" },
    { value: "Charon", label: "Charon (Male)" },
    { value: "Kore", label: "Kore (Female)" },
    { value: "Fenrir", label: "Fenrir (Male)" },
    { value: "Aoede", label: "Aoede (Female)" },
    { value: "Zephyr", label: "Zephyr (Female)" },
    { value: "Leda", label: "Leda (Female)" },
    { value: "Orus", label: "Orus (Male)" },
    { value: "Callirhoe", label: "Callirhoe (Female)" },
    { value: "Autonoe", label: "Autonoe (Female)" },
    { value: "Enceladus", label: "Enceladus (Male)" },
    { value: "Iapetus", label: "Iapetus (Male)" },
    { value: "Umbriel", label: "Umbriel (Male)" },
    { value: "Algieba", label: "Algieba (Male)" },
    { value: "Despina", label: "Despina (Female)" },
    { value: "Erinome", label: "Erinome (Female)" },
    { value: "Algenib", label: "Algenib (Male)" },
    { value: "Rasalgethi", label: "Rasalgethi (Male)" },
    { value: "Laomedeia", label: "Laomedeia (Female)" },
    { value: "Achernar", label: "Achernar (Female)" },
    { value: "Alnilam", label: "Alnilam (Male)" },
    { value: "Schedar", label: "Schedar (Male)" },
    { value: "Gacrux", label: "Gacrux (Female)" },
    { value: "Pulcherrima", label: "Pulcherrima (Female)" },
    { value: "Achird", label: "Achird (Male)" },
    { value: "Zubenelgenubi", label: "Zubenelgenubi (Male)" },
    { value: "Vindemiatrix", label: "Vindemiatrix (Female)" },
    { value: "Sadachbia", label: "Sadachbia (Male)" },
    { value: "Sadaltager", label: "Sadaltager (Male)" },
    { value: "Sulafat", label: "Sulafat (Female)" },
  ];

  private readonly GOOGLE_VOICES = [
    { value: "en-US-Chirp3-HD-Aoede", label: "en-US-Chirp3-HD-Aoede" },
    { value: "en-US-Chirp3-HD-Charon", label: "en-US-Chirp3-HD-Charon" },
    { value: "en-IN-Chirp3-HD-Zephyr", label: "en-IN-Chirp3-HD-Zephyr" },
    { value: "en-US-Chirp3-HD-Despina", label: "en-US-Chirp3-HD-Despina" },
    { value: "en-US-Chirp3-HD-Gacrux", label: "en-US-Chirp3-HD-Gacrux" },
    { value: "en-US-Chirp3-HD-Leda", label: "en-US-Chirp3-HD-Leda" },
    { value: "en-US-Chirp3-HD-Puck", label: "en-US-Chirp3-HD-Puck" },
    { value: "en-IN-Chirp3-HD-Aoede", label: "en-IN-Chirp3-HD-Aoede" },
    { value: "en-US-News-N", label: "en-US-News-N" },
    { value: "en-US-Wavenet-D", label: "en-US-Wavenet-D" },
    { value: "hi-IN-Chirp3-HD-Achird", label: "hi-IN-Chirp3-HD-Achird" },
    { value: "hi-IN-Chirp3-HD-Sulafat", label: "hi-IN-Chirp3-HD-Sulafat" },
    { value: "hi-IN-Chirp3-HD-Vindemiatrix", label: "hi-IN-Chirp3-HD-Vindemiatrix" },
    { value: "hi-IN-Chirp3-HD-Rasalgethi", label: "hi-IN-Chirp3-HD-Rasalgethi" },
    { value: "Custom-Male", label: "Custom clone voice - Male" },
    { value: "Custom-Female", label: "Custom clone voice - Female" },
  ];

  constructor() {
    this.setupDOMElements();
    this.setupEventListeners();
    this.setupFloatingDiagnosticDrawer();
  }

  private setupDOMElements(): void {
    this.connectBtn = document.getElementById(
      "connect-btn"
    ) as HTMLButtonElement;
    this.listenBtn = document.getElementById(
      "listen-btn"
    ) as HTMLButtonElement;
    this.stopBtn = document.getElementById("stop-btn") as HTMLButtonElement;
    this.statusSpan = document.getElementById("connection-status");
    this.statusIndicator = document.getElementById("status-indicator");
    this.debugLog = document.getElementById("debug-log");
    this.connectionLight = document.getElementById("connection-light");
    this.micLight = document.getElementById("mic-light");
    this.speakerLight = document.getElementById("speaker-light");
    this.voiceStatus = document.querySelector(".voice-status");
    this.listeningIndicator = document.getElementById("listening-indicator");
    this.speakingIndicator = document.getElementById("speaking-indicator");
    this.dotsContainer = document.getElementById("dots-container");
    this.tabs = document.querySelectorAll(".tab-btn");
    this.configPanels = document.querySelectorAll(".config-panel");
    this.activePipeline = document.querySelector(".active-pipeline");

    // Observability Elements
    this.toolDefinitionsTextarea = document.getElementById("tool-definitions-textarea") as HTMLTextAreaElement;
    this.chatWindow = document.getElementById("chat-window");
    this.metricTurnCount = document.getElementById("metric-turn-count");
    this.metricInterruptCount = document.getElementById("metric-interrupt-count");
    this.metricToolCallCount = document.getElementById("metric-tool-call-count");
    this.metricTokenCount = document.getElementById("metric-token-count");

  }

  private setupEventListeners(): void {
    this.connectBtn?.addEventListener("click", () => this.toggleConnection());
    this.listenBtn?.addEventListener("click", () => this.startListening());
    this.stopBtn?.addEventListener("click", () => this.stopListening());
    this.tabs?.forEach((tab) => {
      tab.addEventListener("click", () => this.switchTab(tab));
    });

    document.getElementById("copy-debug-btn")?.addEventListener("click", async () => {
      if (this.debugLog) {
        await navigator.clipboard.writeText(this.debugLog.innerText || "");
        const btn = document.getElementById("copy-debug-btn");
        if (btn) {
          const orig = btn.innerHTML;
          btn.innerHTML = '<i class="fas fa-check"></i> Copied';
          setTimeout(() => { btn.innerHTML = orig; }, 1500);
        }
      }
    });

    document.getElementById("clear-debug-btn")?.addEventListener("click", async () => {
      if (this.debugLog) this.debugLog.innerHTML = "";
      if (this.chatWindow) this.chatWindow.innerHTML = "";
      try {
        await fetch(`${getApiBaseUrl()}/api/logs/clear`, { method: "POST" });
      } catch (e) {}
      const feed = document.getElementById("diag-log-feed");
      if (feed) feed.innerHTML = '<div style="color: #64748b; font-style: italic; padding: 20px; text-align: center;">Logs cleared. Waiting for fresh items...</div>';
      const countSpan = document.getElementById("diag-log-count");
      if (countSpan) countSpan.innerText = "0";
    });

    const sttTrigger = document.getElementById("stt-language-trigger");
    const sttOptions = document.getElementById("stt-language-container");
    const sttDisplay = document.getElementById("stt-language-display");

    sttTrigger?.addEventListener("click", () => {
      sttOptions?.classList.toggle("active");
    });

    document.addEventListener("click", (e) => {
      if (sttTrigger && !sttTrigger.contains(e.target as Node) && sttOptions && !sttOptions.contains(e.target as Node)) {
        sttOptions.classList.remove("active");
      }
    });

    const checkboxes = sttOptions?.querySelectorAll('input[type="checkbox"]');
    checkboxes?.forEach((cb) => {
      cb.addEventListener("change", () => {
        const checked = Array.from(sttOptions?.querySelectorAll('input[type="checkbox"]:checked') || [])
          .map((c: any) => c.value);
        if (sttDisplay) {
          sttDisplay.textContent = checked.length > 0 ? checked.join(", ") : "Select Languages";
        }
      });
    });

    const skipSttToggle = document.getElementById("skip-stt-toggle") as HTMLInputElement;
    const sttTile = document.getElementById("stt-tile");

    skipSttToggle?.addEventListener("change", () => {
      sttTile?.classList.toggle("grayed-out", skipSttToggle.checked);
    });

    const contextCompressionToggle = document.getElementById("context-compression-toggle") as HTMLInputElement;
    const compressionTokensContainer = document.getElementById("compression-tokens-container");

    contextCompressionToggle?.addEventListener("change", () => {
      if (compressionTokensContainer) {
        compressionTokensContainer.style.display = contextCompressionToggle.checked ? "block" : "none";
      }
    });

    const paceSlider = document.getElementById("tts-pace-slider") as HTMLInputElement;
    const paceValue = document.getElementById("tts-pace-value");
    if (paceSlider && paceValue) {
      paceSlider.addEventListener("input", () => {
        paceValue.textContent = parseFloat(paceSlider.value).toFixed(2);
      });
    }

    const livePaceSlider = document.getElementById("live-tts-pace-slider") as HTMLInputElement;
    const livePaceValue = document.getElementById("live-tts-pace-value");
    if (livePaceSlider && livePaceValue) {
      livePaceSlider.addEventListener("input", () => {
        livePaceValue.textContent = parseFloat(livePaceSlider.value).toFixed(2);
      });
    }

    const shortPauseBtn = document.getElementById("pause-short-btn");
    const longPauseBtn = document.getElementById("pause-long-btn");
    const systemInstructionsTextarea = document.getElementById(
      "tts-llm-stt-system-instructions-textarea"
    ) as HTMLTextAreaElement;

    shortPauseBtn?.addEventListener("click", () => {
      systemInstructionsTextarea.value += " [pause short]";
    });

    longPauseBtn?.addEventListener("click", () => {
      systemInstructionsTextarea.value += " [pause long]";
    });

    const geminiModelSelect = document.getElementById("gemini-model-select") as HTMLSelectElement;
    const ttsWarning = document.getElementById("tts-warning") as HTMLDivElement;
    const voiceWarning = document.getElementById("voice-warning") as HTMLDivElement;
    const geminiVoiceSelect = document.getElementById("gemini-voice-select") as HTMLSelectElement;
    const ttsToggle = document.getElementById("tts-toggle") as HTMLInputElement;

    const handleModelChange = () => {
      const selectedModel = geminiModelSelect.value;
      const selectedVoice = geminiVoiceSelect.value;

      // Only gemini-live-2.5-flash (cascaded) supports TEXT modality / external TTS.
      const supportsTTS = selectedModel === "gemini-live-2.5-flash";

      if (!supportsTTS) {
        ttsToggle.checked = false;
        ttsToggle.disabled = true;
        ttsWarning.style.display = "none";

        if (selectedVoice.startsWith("Custom")) {
          geminiVoiceSelect.value = "Aoede";
          voiceWarning.style.display = "none";
        } else {
          voiceWarning.style.display = "none";
        }
      } else {
        ttsToggle.disabled = false;
        ttsWarning.style.display = "none";
        voiceWarning.style.display = "none";
      }
    };

    geminiModelSelect?.addEventListener("change", handleModelChange);
    geminiVoiceSelect?.addEventListener("change", handleModelChange);
    ttsToggle?.addEventListener("change", handleModelChange);

    // Run initially to sync UI state
    handleModelChange();

    // TTS Model Change Logic
    const ttsModelSelect = document.getElementById("tts-model-select") as HTMLSelectElement;
    const ttsVoiceSelect = document.getElementById("tts-voice-select") as HTMLSelectElement;

    const populateVoices = () => {
      const model = ttsModelSelect.value;
      ttsVoiceSelect.innerHTML = "";

      let voices: { value: string, label: string }[] = [];
      if (model.startsWith("gemini")) {
        voices = this.GEMINI_VOICES;
      } else {
        voices = this.GOOGLE_VOICES;
      }

      voices.forEach(voice => {
        const option = document.createElement("option");
        option.value = voice.value;
        option.textContent = voice.label;
        if (model.startsWith("gemini") && voice.value === "Aoede") {
          option.selected = true;
        }
        ttsVoiceSelect.appendChild(option);
      });
    };

    if (ttsModelSelect && ttsVoiceSelect) {
      ttsModelSelect.addEventListener("change", populateVoices);
      // Initial population
      populateVoices();
    }
  }

  public async loadSystemPrompt(): Promise<void> {
    try {
      const response = await fetch(`${getApiBaseUrl()}/connect/system-prompt`);
      const data = await response.json();
      const geminiSystemInstructionsTextarea = document.getElementById(
        "system-instructions-textarea"
      ) as HTMLTextAreaElement;
      if (geminiSystemInstructionsTextarea) {
        geminiSystemInstructionsTextarea.value = data.system_prompt;
      }

      const ttsLlmSttSystemInstructionsTextarea = document.getElementById(
        "tts-llm-stt-system-instructions-textarea"
      ) as HTMLTextAreaElement;
      if (ttsLlmSttSystemInstructionsTextarea) {
        ttsLlmSttSystemInstructionsTextarea.value = data.system_prompt;
      }
    } catch (error) {
      this.log(`Error loading system prompt: ${error}`, "error");
    }
  }

  private switchTab(tab: HTMLButtonElement): void {
    const tabId = tab.dataset.tab;
    if (!tabId) return;

    // Don't change activeTab if it's observability, unless we want to use it for config?
    // The user wants Observability as a separate tab.
    // If the user clicks "Observability", we show that panel.
    // But connection parameters depend on "gemini-live" or "tts-llm-stt".
    // So "Observability" is just a view, not a bot type.
    // I'll keep activeTab as the bot type, but show the Observability panel.
    // Wait, the connect logic uses this.activeTab to determine bot_type.
    // If activeTab is "observability", connect logic might break.
    // So "Observability" should probably NOT change activeTab if it's used for connection type.
    // OR, I should separate "View Tab" from "Bot Type".
    // For now, I'll assume Observability is just a view and doesn't change the underlying bot config type.
    // But visually, the "Gemini Live" tab becomes inactive.
    
    // Let's modify: if tab is observability, just show panel, don't change this.activeTab used for connection.
    
    if (tabId === "observability") {
        this.tabs?.forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        
        this.configPanels?.forEach((panel) => {
            if (panel.id === "observability-panel") {
                panel.classList.add("active");
            } else {
                panel.classList.remove("active");
            }
        });
        return;
    }

    this.selectedBotType = tabId;
    this.activeTab = tabId;

    this.tabs?.forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");

    this.configPanels?.forEach((panel) => {
      if (panel.id === `${tabId}-panel`) {
        panel.classList.add("active");
      } else {
        panel.classList.remove("active");
      }
    });

    if (this.activePipeline) {
      if (tabId === "tts-llm-stt") {
        this.activePipeline.textContent = "Active: STT-LLM-TTS Pipeline";
      } else if (tabId === "gemini-live") {
        this.activePipeline.textContent = "Active: Gemini Live Pipeline";
      }
    }
  }

  private log(message: string, level: LogLevel = "info"): void {
    console.log(`[${level.toUpperCase()}] ${message}`);
    
    if (!this.debugLog || level === "info") return;

    const entry = document.createElement("div");
    entry.classList.add("log-entry");

    const time = new Date().toLocaleTimeString();
    const timeEl = document.createElement("span");
    timeEl.classList.add("log-time");
    timeEl.textContent = time;

    const levelEl = document.createElement("span");
    levelEl.classList.add("log-level", level);
    levelEl.textContent = level;

    const messageEl = document.createElement("span");
    messageEl.textContent = message;

    entry.appendChild(timeEl);
    entry.appendChild(levelEl);
    entry.appendChild(messageEl);

    this.debugLog.appendChild(entry);
    this.debugLog.scrollTop = this.debugLog.scrollHeight;
  }

  private resetMetrics() {
      this.turnCount = 0;
      this.interruptCount = 0;
      this.toolCallCount = 0;
      this.tokenCount = 0;
      this.lastLLMLatency = null;
      this.lastTTSLatency = null;
      this.lastTurnSTTLatency = null;
      this.pendingLLMLatency = null;
      this.pendingTTSLatency = null;
      this.pendingSTTLatency = null;
      this.lastTurnUsage = null;
      this.lastPromptTokenCount = 0;
      this.updateMetricDisplay();
      if (this.chatWindow) this.chatWindow.innerHTML = "";
  }

  private updateMetricDisplay() {
      if (this.metricTurnCount) this.metricTurnCount.textContent = this.turnCount.toString();
      if (this.metricInterruptCount) this.metricInterruptCount.textContent = this.interruptCount.toString();
      if (this.metricToolCallCount) this.metricToolCallCount.textContent = this.toolCallCount.toString();
      if (this.metricTokenCount) this.metricTokenCount.textContent = this.tokenCount.toString();
  }

  private updateBubbleLatencyDisplay(bubble: HTMLElement, updates?: { llmLatency?: number; ttsLatency?: number; sttLatency?: number; usage?: any }) {
      if (!bubble) return;
      if (updates) {
          if (updates.llmLatency !== undefined) bubble.dataset.llmLatency = updates.llmLatency.toString();
          if (updates.ttsLatency !== undefined) bubble.dataset.ttsLatency = updates.ttsLatency.toString();
          if (updates.sttLatency !== undefined) bubble.dataset.sttLatency = updates.sttLatency.toString();
          if (updates.usage !== undefined) bubble.dataset.usage = JSON.stringify(updates.usage);
      }

      let latencyEl = bubble.querySelector(".loop-latencies, .ttft-latency") as HTMLElement;
      if (!latencyEl) {
          latencyEl = document.createElement("div");
          latencyEl.classList.add("loop-latencies");
          latencyEl.style.fontStyle = "italic";
          latencyEl.style.fontSize = "0.8em";
          latencyEl.style.opacity = "0.7";
          latencyEl.style.marginTop = "4px";
          bubble.appendChild(latencyEl);
      }

      const parts: string[] = [];
      const isCascade = this.connectedBotType === "tts-llm-stt";
      const llmLabel = isCascade ? "⚡ LLM TTFB" : "⚡ Live TTFB";

      const llmVal = bubble.dataset.llmLatency ? parseFloat(bubble.dataset.llmLatency) : null;
      const ttsVal = bubble.dataset.ttsLatency ? parseFloat(bubble.dataset.ttsLatency) : null;
      const sttVal = bubble.dataset.sttLatency ? parseFloat(bubble.dataset.sttLatency) : null;
      let usageVal: any = null;
      try {
          if (bubble.dataset.usage) usageVal = JSON.parse(bubble.dataset.usage);
      } catch (_) {}

      if (sttVal !== null && isCascade) {
          parts.push(`STT: ${Math.round(sttVal * 1000)}ms`);
      }
      if (llmVal !== null) {
          parts.push(`${llmLabel}: ${Math.round(llmVal * 1000)}ms`);
      }
      if (ttsVal !== null && isCascade) {
          parts.push(`TTS: ${Math.round(ttsVal * 1000)}ms`);
      }
      if (usageVal !== null) {
          const formatModality = (details: any) => {
              if (!details) return "";
              const list = [];
              if (details.text) list.push(`Text: ${details.text}`);
              if (details.audio) list.push(`Audio: ${details.audio}`);
              return list.length > 0 ? ` (${list.join(", ")})` : "";
          };
          const promptStr = `In: ${usageVal.prompt_token_count || 0}${formatModality(usageVal.prompt_details)}`;
          const responseStr = `Out: ${usageVal.response_token_count || 0}${formatModality(usageVal.response_details)}`;
          parts.push(`Tokens: ${usageVal.total_token_count || 0} [${promptStr} | ${responseStr}]`);
      }

      if (parts.length > 0) {
          latencyEl.textContent = parts.join(" | ");
      }
  }

  private updateUserBubbleSTT(bubble: HTMLElement, sttLatency: number) {
      bubble.dataset.sttLatency = sttLatency.toString();
      let sttEl = bubble.querySelector(".stt-latency") as HTMLElement;
      if (!sttEl) {
          sttEl = document.createElement("div");
          sttEl.classList.add("stt-latency");
          sttEl.style.fontStyle = "italic";
          sttEl.style.fontSize = "0.8em";
          sttEl.style.opacity = "0.7";
          sttEl.style.marginTop = "4px";
          bubble.appendChild(sttEl);
      }
      sttEl.textContent = `⚡ STT: ${Math.round(sttLatency * 1000)}ms`;
  }

  private appendChatMessage(role: "user" | "bot", text: string, ttft?: number, sttLatency?: number) {
    if (!this.chatWindow) return;

    if (role === "user") {
        this.pendingLLMLatency = null;
        this.pendingTTSLatency = null;
        if (sttLatency === undefined && this.pendingSTTLatency !== null) {
            sttLatency = this.pendingSTTLatency;
            this.pendingSTTLatency = null;
        }
    }
    
    const lastBubble = this.chatWindow.lastElementChild as HTMLElement | null;
    if (lastBubble && lastBubble.classList.contains(role)) {
      const timestamp = lastBubble.querySelector(".timestamp");
      if (timestamp) {
        const currentText = lastBubble.getAttribute('data-text') || '';
        const separator = (currentText && !currentText.endsWith(' ') && !text.startsWith(' ')) ? ' ' : '';
        const fullText = currentText + separator + text;
        lastBubble.setAttribute('data-text', fullText);
        
        const cleanText = fullText.replace(/\[.*?\]/g, '').replace(/<transcription>.*?<\/transcription>/g, '');
        const textNode = timestamp.previousSibling;
        if (textNode && textNode.nodeType === Node.TEXT_NODE) {
            textNode.textContent = cleanText;
        } else {
            timestamp.before(document.createTextNode(cleanText));
        }
      } else {
        const currentText = lastBubble.textContent || '';
        lastBubble.textContent = (currentText + text).replace(/\[.*?\]/g, '').replace(/<transcription>.*?<\/transcription>/g, '');
      }
      
      if (role === "bot") {
        const effTtft = ttft !== undefined ? ttft : (this.pendingLLMLatency !== null ? this.pendingLLMLatency : undefined);
        if (effTtft !== undefined) {
            this.pendingLLMLatency = null;
            this.updateBubbleLatencyDisplay(lastBubble, { llmLatency: effTtft });
        }
      }
      if (role === "user" && sttLatency !== undefined) {
        this.updateUserBubbleSTT(lastBubble, sttLatency);
      }
      
      this.chatWindow.scrollTop = this.chatWindow.scrollHeight;
      return;
    }

    const bubble = document.createElement("div");
    bubble.classList.add("chat-bubble", role);
    bubble.setAttribute('data-text', text);
    bubble.textContent = text.replace(/\[.*?\]/g, '').replace(/<transcription>.*?<\/transcription>/g, '');
    
    const timestamp = document.createElement("span");
    timestamp.classList.add("timestamp");
    timestamp.textContent = new Date().toLocaleTimeString();
    bubble.appendChild(timestamp);

    if (role === "bot") {
      const effTtft = ttft !== undefined ? ttft : (this.pendingLLMLatency !== null ? this.pendingLLMLatency : undefined);
      this.pendingLLMLatency = null;
      const effTts = this.pendingTTSLatency !== null ? this.pendingTTSLatency : undefined;
      this.pendingTTSLatency = null;
      const effStt = (this.connectedBotType === "tts-llm-stt") ? (this.lastTurnSTTLatency || undefined) : undefined;
      this.updateBubbleLatencyDisplay(bubble, { 
          llmLatency: effTtft, 
          ttsLatency: effTts,
          sttLatency: effStt 
      });
    } else if (role === "user") {
      const effStt = sttLatency !== undefined ? sttLatency : (this.pendingSTTLatency !== null ? this.pendingSTTLatency : undefined);
      this.pendingSTTLatency = null;
      if (effStt !== undefined) {
        this.updateUserBubbleSTT(bubble, effStt);
      }
    }

    this.chatWindow.appendChild(bubble);
    this.chatWindow.scrollTop = this.chatWindow.scrollHeight;
  }

  private replaceChatMessage(role: "user" | "bot", text: string) {
    if (!this.chatWindow) return;
    const bubbles = this.chatWindow.querySelectorAll(`.chat-bubble.${role}`);
    if (bubbles.length === 0) return;
    const lastBubble = bubbles[bubbles.length - 1] as HTMLElement;
    lastBubble.setAttribute('data-text', text);
    const timestamp = lastBubble.querySelector(".timestamp");
    if (timestamp) {
      const textNode = timestamp.previousSibling;
      if (textNode && textNode.nodeType === Node.TEXT_NODE) {
        textNode.textContent = text;
      } else {
        timestamp.before(document.createTextNode(text));
      }
    }
  }

  private markInterruptionLatency(elapsed_ms: number) {
      if (!this.chatWindow) return;
      const botBubbles = this.chatWindow.querySelectorAll(".chat-bubble.bot");
      if (botBubbles.length === 0) return;
      const lastBubble = botBubbles[botBubbles.length - 1] as HTMLElement;
      let latencyEl = lastBubble.querySelector(".loop-latencies, .ttft-latency") as HTMLElement;
      if (!latencyEl) {
          latencyEl = document.createElement("div");
          latencyEl.classList.add("loop-latencies");
          latencyEl.style.fontStyle = "italic";
          latencyEl.style.fontSize = "0.8em";
          latencyEl.style.opacity = "0.8";
          latencyEl.style.marginTop = "4px";
          lastBubble.appendChild(latencyEl);
      }
      latencyEl.textContent = `⚡ Interrupted after ${Math.round(elapsed_ms)}ms`;
      latencyEl.style.color = "#f59e0b";
  }

  private handleServerMessage(message: any) {
      // Handle Transcription
      if (message.type === "transcription") {
          const { participant, text, ttft, stt_latency } = message;
          const role = (participant === "User" || participant === "user") ? "user" : "bot";
          if (role === "user" && stt_latency !== undefined) {
              this.lastTurnSTTLatency = stt_latency;
          }
          this.appendChatMessage(role, text, ttft, stt_latency);
      }

      // Handle Transcription Replace (parallel STT updates the placeholder)
      if (message.type === "transcription_replace") {
          const { participant, text } = message;
          const role = (participant === "User" || participant === "user") ? "user" : "bot";
          this.replaceChatMessage(role, text);
      }

      // Handle LangSmith Trace URL
      if (message.type === "trace_url") {
          const url = message.url;
          const lsBtn = document.getElementById("diag-langsmith-btn") as HTMLAnchorElement;
          if (lsBtn && url) lsBtn.href = url;
          this.log(`LangSmith Trace active: ${url}`, "info");
      }

      // Handle Metrics
      // Case 1: OutputTransportMessageFrame format
      if (message.type === "metrics") {
          const payload = message.payload;
          if (!payload) return;
          
          const lastChild = this.chatWindow?.lastElementChild as HTMLElement | null;

          switch (payload.type) {
              case "interruption":
                  this.interruptCount += (payload.count || 1);
                  if (payload.elapsed_ms !== undefined) {
                      this.markInterruptionLatency(payload.elapsed_ms);
                  }
                  break;
              case "turn_complete":
                  this.turnCount++;
                  break;
              case "tool_call":
                  this.toolCallCount++;
                  this.log(`Tool Call: ${JSON.stringify(payload.tool)}`, "info");
                  break;
              case "usage":
                  if (payload.usage) {
                      const promptTokens = payload.usage.prompt_token_count || 0;
                      if (this.lastPromptTokenCount > 0 && promptTokens < this.lastPromptTokenCount) {
                          const diff = this.lastPromptTokenCount - promptTokens;
                          this.log(`Context compression triggered! Prompt tokens reduced by ${diff} (from ${this.lastPromptTokenCount} to ${promptTokens}).`, "warning");
                          this.appendChatMessage("bot", `[System Notice: Context window compressed! History reduced by ${diff} tokens to optimize performance.]`);
                      }
                      this.lastPromptTokenCount = promptTokens;

                      if (payload.usage.total_token_count) {
                          this.tokenCount += payload.usage.total_token_count;
                      }
                      if (lastChild && lastChild.classList.contains("bot")) {
                          this.updateBubbleLatencyDisplay(lastChild, { usage: payload.usage });
                      } else {
                          const botBubbles = this.chatWindow?.querySelectorAll(".chat-bubble.bot");
                          const lastBotBubble = botBubbles && botBubbles.length > 0 ? (botBubbles[botBubbles.length - 1] as HTMLElement) : null;
                          if (lastBotBubble) {
                              this.updateBubbleLatencyDisplay(lastBotBubble, { usage: payload.usage });
                          }
                      }
                  }
                  break;
              case "llm_latency":
                  if (lastChild && lastChild.classList.contains("bot")) {
                      this.updateBubbleLatencyDisplay(lastChild, { llmLatency: payload.value });
                  } else {
                      this.pendingLLMLatency = payload.value;
                  }
                  break;
              case "tts_latency":
                  if (lastChild && lastChild.classList.contains("bot")) {
                      this.updateBubbleLatencyDisplay(lastChild, { ttsLatency: payload.value });
                  } else {
                      this.pendingTTSLatency = payload.value;
                  }
                  break;
              case "stt_latency":
                  this.lastTurnSTTLatency = payload.value;
                  this.pendingSTTLatency = payload.value;
                  const userBubbles = this.chatWindow?.querySelectorAll(".chat-bubble.user");
                  const lastUserBubble = userBubbles && userBubbles.length > 0 ? (userBubbles[userBubbles.length - 1] as HTMLElement) : null;
                  if (lastUserBubble) {
                      this.updateUserBubbleSTT(lastUserBubble, payload.value);
                  }
                  break;
          }
          this.updateMetricDisplay();
          return;
      }

      // Handle JSON Metrics (sent as TextFrame) - Legacy/Fallback
      let jsonText = "";
      if (message.type === "text" && message.text.startsWith("JSON:")) {
          jsonText = message.text.substring(5);
      } else if (typeof message === "string" && message.startsWith("JSON:")) {
          jsonText = message.substring(5);
      }

      if (jsonText) {
          try {
              const data = JSON.parse(jsonText);
              switch (data.type) {
                  case "interruption":
                      this.interruptCount += (data.count || 1);
                      break;
                  case "turn_complete":
                      this.turnCount++;
                      break;
                  case "tool_call":
                      this.toolCallCount++;
                      // Optionally log tool details to chat or debug
                      this.log(`Tool Call: ${JSON.stringify(data.tool)}`, "info");
                      break;
                  case "usage":
                      if (data.usage) {
                          this.lastTurnUsage = data.usage;
                          const promptTokens = data.usage.prompt_token_count || 0;
                          if (this.lastPromptTokenCount > 0 && promptTokens < this.lastPromptTokenCount) {
                              const diff = this.lastPromptTokenCount - promptTokens;
                              this.log(`Context compression triggered (fallback)! Prompt tokens reduced by ${diff} (from ${this.lastPromptTokenCount} to ${promptTokens}).`, "warning");
                              this.appendChatMessage("bot", `[System Notice: Context window compressed! History reduced by ${diff} tokens to optimize performance.]`);
                          }
                          this.lastPromptTokenCount = promptTokens;

                          if (data.usage.total_token_count) {
                              this.tokenCount += data.usage.total_token_count;
                          }
                          const botBubbles = this.chatWindow?.querySelectorAll(".chat-bubble.bot");
                          const lastBotBubble = botBubbles && botBubbles.length > 0 ? (botBubbles[botBubbles.length - 1] as HTMLElement) : null;
                          if (lastBotBubble) {
                              this.updateBubbleLatencyDisplay(lastBotBubble, { usage: data.usage });
                          }
                      }
                      break;
              }
              this.updateMetricDisplay();
          } catch (e) {
              console.error("Failed to parse JSON metric:", e);
          }
      }
  }

  // -----------------------------

  private updateStatus(status: string): void {
    if (this.statusSpan) {
      this.statusSpan.textContent = status;
    }
    if (this.statusIndicator) {
      this.statusIndicator.className = status.toLowerCase();
    }
    if (this.connectionLight) {
      this.connectionLight.textContent =
        status === "Connected" ? "Active" : "Inactive";
      this.connectionLight.className = `light ${
        status === "Connected" ? "active" : "inactive"
      }`;
    }
    this.log(`Status: ${status}`);
  }

  private updateMicStatus(status: "idle" | "active"): void {
    if (this.micLight) {
      this.micLight.textContent = status === "active" ? "Active" : "Idle";
      this.micLight.className = `light ${status}`;
    }
    if (this.listeningIndicator) {
      this.listeningIndicator.classList.toggle("active", status === "active");
    }
    if (this.dotsContainer) {
      this.dotsContainer.classList.toggle("active", status === "active");
    }
    if (this.voiceStatus) {
      this.voiceStatus.textContent =
        status === "active" ? "Listening..." : "Click to start conversation";
    }
  }

  private updateSpeakerStatus(status: "silent" | "active"): void {
    if (this.speakerLight) {
      this.speakerLight.textContent = status === "active" ? "Active" : "Silent";
      this.speakerLight.className = `light ${status}`;
    }
    if (this.speakingIndicator) {
      this.speakingIndicator.classList.toggle("active", status === "active");
    }
    if (this.dotsContainer) {
      // Also show dots when speaking
      this.dotsContainer.classList.toggle("active", status === "active");
    }
  }

  private toggleConnection(): void {
    if (this.rtviClient) {
      this.disconnect();
    } else {
      this.connect();
    }
  }

  private startListening(): void {
    if (this.rtviClient) {
      const tracks = this.rtviClient.tracks();
      if (tracks.local?.audio) {
        tracks.local.audio.enabled = true;
        this.log("Microphone unmuted");
      }
      this.updateMicStatus("active");
      this.listenBtn!.disabled = true;
      this.stopBtn!.disabled = false;
      
      // Send the start trigger to start the bot greeting turn
      this.rtviClient.sendMessage(new RTVIMessage("start_trigger", {}));
    }
  }

  private stopListening(): void {
    if (this.rtviClient) {
      const tracks = this.rtviClient.tracks();
      if (tracks.local?.audio) {
        tracks.local.audio.enabled = false;
        this.log("Microphone muted");
      }
      this.updateMicStatus("idle");
      this.listenBtn!.disabled = false;
      this.stopBtn!.disabled = true;
    }
  }

  setupMediaTracks() {
    if (!this.rtviClient) return;
    const tracks = this.rtviClient.tracks();
    if (tracks.bot?.audio) {
      this.setupAudioTrack(tracks.bot.audio);
    }
  }

  setupTrackListeners() {
    if (!this.rtviClient) return;

    this.rtviClient.on(RTVIEvent.TrackStarted, (track, participant) => {
      if (!participant?.local && track.kind === "audio") {
        this.setupAudioTrack(track);
        this.updateSpeakerStatus("active");
      }
    });

    this.rtviClient.on(RTVIEvent.TrackStopped, (track, participant) => {
      this.log(
        `Track stopped: ${track.kind} from ${participant?.name || "unknown"}`
      );
      if (!participant?.local && track.kind === "audio") {
        this.updateSpeakerStatus("silent");
      }
    });
  }

  private setupAudioTrack(track: MediaStreamTrack): void {
    this.log("Setting up audio track");
    const audioEl = document.getElementById("bot-audio") as HTMLAudioElement;
    if (audioEl) {
      const stream = new MediaStream([track]);
      audioEl.srcObject = stream;
      audioEl.play().catch(e => this.log(`Audio play failed: ${e}`, "error"));
    }
  }

  public async connect(): Promise<void> {
    try {
      this.audioContext = new AudioContext();
      this.audioContext.resume();
      this.updateStatus("Connecting");
      this.resetMetrics(); // Reset metrics on connect

      const transport = new WebSocketTransport();

      const botTypeToConnect = this.selectedBotType || (this.activeTab !== "observability" ? this.activeTab : "gemini-live");
      this.connectedBotType = botTypeToConnect;

      let connectUrl = `/connect?bot_type=${botTypeToConnect}`;
      let systemInstructions = "";

      if (botTypeToConnect === "tts-llm-stt") {
        const ttsVoiceSelect = document.getElementById(
          "tts-voice-select"
        ) as HTMLSelectElement | null;
        const ttsModelSelect = document.getElementById(
          "tts-model-select"
        ) as HTMLSelectElement | null;
        const llmModelSelect = document.getElementById(
          "llm-model-select"
        ) as HTMLSelectElement | null;
        const sttModelSelect = document.getElementById(
          "stt-model-select"
        ) as HTMLSelectElement | null;
        const sttLanguageContainer = document.getElementById(
          "stt-language-container"
        ) as HTMLElement | null;
        const systemInstructionsTextarea = document.getElementById(
          "tts-llm-stt-system-instructions-textarea"
        ) as HTMLTextAreaElement | null;
        const paceSlider = document.getElementById("tts-pace-slider") as HTMLInputElement | null;
        const skipSttToggle = document.getElementById("skip-stt-toggle") as HTMLInputElement | null;

        connectUrl += `&tts_voice=${ttsVoiceSelect?.value || "Aoede"}`;
        connectUrl += `&tts_model=${ttsModelSelect?.value || "gemini-2.5-flash"}`;
        connectUrl += `&tts_pace=${paceSlider?.value || "1.0"}`;
        connectUrl += `&llm_model=${llmModelSelect?.value || "gemini-3.5-flash"}`;
        connectUrl += `&stt_model=${sttModelSelect?.value || "chirp_3"}`;
        connectUrl += `&skip_stt=${skipSttToggle?.checked || false}`;
        
        const checkedLanguages = Array.from(sttLanguageContainer?.querySelectorAll('input[type="checkbox"]:checked') || [])
            .map((cb: any) => cb.value);
        connectUrl += `&stt_language=${checkedLanguages.join(',') || 'en-IN,hi-IN'}`;
        systemInstructions = systemInstructionsTextarea?.value || "";
      } else {
        const geminiModelSelect = document.getElementById(
          "gemini-model-select"
        ) as HTMLSelectElement | null;
        const geminiVoiceSelect = document.getElementById(
          "gemini-voice-select"
        ) as HTMLSelectElement | null;
        const geminiLanguageSelect = document.getElementById(
          "gemini-language-select"
        ) as HTMLSelectElement | null;
        const geminiSystemInstructionsTextarea = document.getElementById(
          "system-instructions-textarea"
        ) as HTMLTextAreaElement | null;
        const ttsToggle = document.getElementById(
          "tts-toggle"
        ) as HTMLInputElement | null;
        const livePaceSlider = document.getElementById(
          "live-tts-pace-slider"
        ) as HTMLInputElement | null;

        const contextCompressionToggle = document.getElementById(
          "context-compression-toggle"
        ) as HTMLInputElement | null;
        const compressionTokensInput = document.getElementById(
          "compression-tokens-input"
        ) as HTMLInputElement | null;

        connectUrl += `&model=${geminiModelSelect?.value || "gemini-3.5-flash-live-preview"}`;
        connectUrl += `&voice=${geminiVoiceSelect?.value || "Aoede"}`;
        connectUrl += `&language=${geminiLanguageSelect?.value || "hi-IN"}`;
        connectUrl += `&tts=${ttsToggle?.checked || false}`;
        connectUrl += `&tts_pace=${livePaceSlider?.value || "1.0"}`;
        connectUrl += `&context_compression=${contextCompressionToggle?.checked || false}`;
        if (contextCompressionToggle?.checked && compressionTokensInput?.value?.trim()) {
          connectUrl += `&context_compression_trigger_tokens=${parseInt(compressionTokensInput.value)}`;
        }
        systemInstructions = geminiSystemInstructionsTextarea?.value || "";
      }

      // Only append system_instruction to URL if explicitly customized and brief (< 500 chars)
      // Default system prompt is automatically loaded server-side to prevent HTTP 400 (URL query line too long)
      if (systemInstructions && systemInstructions.length < 500) {
        connectUrl += `&system_instruction=${encodeURIComponent(
          systemInstructions
        )}`;
      }

      // Handle Dynamic Tools
      let tools = null;
      if (this.toolDefinitionsTextarea && this.toolDefinitionsTextarea.value.trim()) {
          try {
              tools = JSON.parse(this.toolDefinitionsTextarea.value);
              this.log("Loaded dynamic tools from configuration", "info");
          } catch(e) {
              this.log("Invalid JSON in Tool Definitions", "error");
              // Continue without tools or abort? Aborting seems safer if config is wrong.
              this.updateStatus("Error: Invalid Tool JSON");
              return;
          }
      }

      const RTVIConfig: RTVIClientOptions = {
        transport,
        params: {
          baseUrl: import.meta.env.VITE_WSS_URL || getApiBaseUrl(),
          endpoints: {
            connect: connectUrl,
          },
          // Send tools in params, hoping client sends it in body
          tools: tools
        },
        enableMic: true,
        enableCam: false,
        callbacks: {
          onConnected: () => {
            this.updateStatus("Connected");
            if (this.connectBtn) this.connectBtn.textContent = "Disconnect";
            if (this.listenBtn) this.listenBtn.disabled = false;
          },
          onDisconnected: () => {
            this.updateStatus("Disconnected");
            if (this.connectBtn) this.connectBtn.textContent = "Connect";
            if (this.listenBtn) this.listenBtn.disabled = true;
            if (this.stopBtn) this.stopBtn.disabled = true;
            this.updateMicStatus("idle");
            this.log("Client disconnected");
            this.rtviClient = null;
          },
          onBotReady: (data) => {
            this.log(`Bot ready: ${JSON.stringify(data)}`);
            this.setupMediaTracks();
          },
          onServerMessage: (message: any) => {
            this.log(`Server message: ${JSON.stringify(message)}`, "info");
            if (message.type === "server-message" && message.data) {
                this.handleServerMessage(message.data);
            } else {
                this.handleServerMessage(message);
            }
          },
          onMessageError: (error: any) => {
            if (error && (error.type === "error-response" || error.type === "error")) {
              if (!error.data || Object.keys(error.data).length === 0 || !error.data.message) {
                return;
              }
            }
            const errStr = typeof error === "object" ? JSON.stringify(error, Object.getOwnPropertyNames(error)) : error;
            this.log(`Message error: ${errStr}`, "error");
          },
          onError: (error) => {
            const errStr = typeof error === "object" ? JSON.stringify(error, Object.getOwnPropertyNames(error)) : error;
            this.log(`Error: ${errStr}`, "error");
          },
        },
      };

      this.rtviClient = new RTVIClient(RTVIConfig);
      this.setupTrackListeners();

      this.log("Initializing devices...");
      await this.rtviClient.initDevices();

      const localTracks = this.rtviClient.tracks().local;
      if (localTracks?.audio) {
        localTracks.audio.enabled = false;
        this.log("Microphone muted by default");
      }

      this.log("Connecting to bot...");
      await this.rtviClient.connect();
    } catch (error) {
      this.log(`Error connecting: ${(error as Error).message}`, "error");
      this.updateStatus("Error");
      if (this.rtviClient) {
        try {
          await this.rtviClient.disconnect();
        } catch (disconnectError) {
          this.log(`Error during disconnect: ${disconnectError}`, "error");
        }
        this.rtviClient = null;
      }
    }
  }

  public async disconnect(): Promise<void> {
    if (this.rtviClient) {
      try {
        await this.rtviClient.disconnect();
        this.rtviClient = null;
        if (this.audioContext) {
          this.audioContext.close();
          this.audioContext = null;
        }
      } catch (error) {
        this.log(`Error disconnecting: ${(error as Error).message}`, "error");
      }
    }
  }

  private setupFloatingDiagnosticDrawer(): void {
    if (document.getElementById("floating-diag-container")) return;

    const container = document.createElement("div");
    container.id = "floating-diag-container";
    container.style.cssText = "position: fixed; bottom: 20px; right: 20px; z-index: 99999; font-family: 'JetBrains Mono', 'Fira Code', monospace;";

    // Add custom pulse animation keyframes right inside the DOM
    const styleTag = document.createElement("style");
    styleTag.innerHTML = `
      @keyframes diag-pulse {
        0% { transform: scale(1); opacity: 1; box-shadow: 0 0 10px rgba(74, 222, 128, 0.4); }
        50% { transform: scale(1.15); opacity: 0.75; box-shadow: 0 0 20px rgba(74, 222, 128, 0.8); }
        100% { transform: scale(1); opacity: 1; box-shadow: 0 0 10px rgba(74, 222, 128, 0.4); }
      }
      @keyframes diag-glow {
        0% { border-color: rgba(56, 189, 248, 0.5); box-shadow: 0 0 20px rgba(56, 189, 248, 0.25); }
        50% { border-color: rgba(168, 85, 247, 0.6); box-shadow: 0 0 30px rgba(168, 85, 247, 0.35); }
        100% { border-color: rgba(56, 189, 248, 0.5); box-shadow: 0 0 20px rgba(56, 189, 248, 0.25); }
      }
      .diag-card { transition: background 0.15s ease; }
      .diag-card:hover { background: rgba(30, 41, 59, 0.7) !important; }
    `;
    document.head.appendChild(styleTag);

    const badge = document.createElement("div");
    badge.id = "floating-diag-badge";
    badge.style.cssText = "background: linear-gradient(135deg, rgba(15, 23, 42, 0.96) 0%, rgba(30, 41, 59, 0.96) 100%); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.6); border-radius: 50px; padding: 10px 18px; cursor: pointer; display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 700; transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1); animation: diag-glow 4s infinite ease-in-out; backdrop-filter: blur(10px);";
    badge.innerHTML = `
      <div style="width: 10px; height: 10px; background: #4ade80; border-radius: 50%; animation: diag-pulse 2s infinite;"></div>
      <span style="letter-spacing: 0.5px;">⚡ DIAGNOSTIC ENGINE</span>
      <div id="diag-ttfb-pill" style="background: rgba(56, 189, 248, 0.18); color: #7dd3fc; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 800; border: 1px solid rgba(56, 189, 248, 0.3); margin-left: 2px;">TTFB: -- ms</div>
      <a href="/diagnostics" target="_blank" onclick="event.stopPropagation()" style="background: linear-gradient(135deg, rgba(192, 132, 252, 0.25) 0%, rgba(56, 189, 248, 0.25) 100%); color: #e2e8f0; padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 700; border: 1px solid rgba(192, 132, 252, 0.4); text-decoration: none; margin-left: 4px; display: inline-flex; align-items: center; gap: 4px;"><span>↗ Full Dashboard</span></a>
    `;

    const dialog = document.createElement("div");
    dialog.id = "floating-diag-dialog";
    dialog.style.cssText = "display: none; width: 880px; height: 660px; max-height: 88vh; max-width: 94vw; background: rgba(15, 23, 42, 0.98); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.18); border-radius: 16px; box-shadow: 0 20px 50px rgba(0,0,0,0.7); overflow: hidden; flex-direction: column; margin-bottom: 16px;";

    dialog.innerHTML = `
      <div style="background: rgba(0,0,0,0.5); padding: 12px 18px; border-bottom: 1px solid rgba(255,255,255,0.12); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="color: #f8fafc; font-size: 13px; font-weight: 800; display: flex; align-items: center; gap: 6px;">
            <span>🖥️</span> Diagnostic Feed
          </span>
          <div style="display: inline-flex; background: rgba(0,0,0,0.45); padding: 2px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1);">
            <button id="diag-tab-logs-btn" style="background: rgba(56, 189, 248, 0.22); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; cursor: pointer;">📜 Logs (<span id="diag-log-count">0</span>)</button>
            <button id="diag-tab-latency-btn" style="background: transparent; color: #94a3b8; border: 1px solid transparent; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; cursor: pointer;">⚡ Latency Benchmarks</button>
          </div>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <a id="diag-langsmith-btn" href="https://smith.langchain.com/" target="_blank" style="background: linear-gradient(135deg, #0284c7 0%, #9333ea 100%); color: #ffffff; border-radius: 6px; padding: 5px 10px; font-size: 12px; font-weight: 700; text-decoration: none; display: inline-flex; align-items: center; gap: 4px;"><span>↗️ LangSmith Trace</span></a>
          <a href="/diagnostics" target="_blank" style="background: rgba(192,132,252,0.18); border: 1px solid rgba(192,132,252,0.35); color: #c084fc; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 600; text-decoration: none;">Full Console</a>
          <button id="diag-copy-btn" style="background: rgba(56,189,248,0.15); border: 1px solid rgba(56,189,248,0.3); color: #38bdf8; border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 12px; font-weight: 600;"><i class="fas fa-copy"></i> Copy</button>
          <button id="diag-clear-btn" style="background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.3); color: #f87171; border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 12px; font-weight: 600;"><i class="fas fa-trash"></i> Clear</button>
          <button id="diag-close-btn" style="background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15); color: #e2e8f0; border-radius: 50%; width: 28px; height: 28px; cursor: pointer; font-size: 14px; display: flex; align-items: center; justify-content: center;">✕</button>
        </div>
      </div>
      <div id="diag-log-feed" style="padding: 16px; overflow-y: auto; flex: 1; font-size: 13px; line-height: 1.6; color: #e2e8f0; background: rgba(0,0,0,0.15);">
        <div style="color: #64748b; font-style: italic; padding: 20px; text-align: center;">Connecting to Cloud Run live stream...</div>
      </div>
      <div id="diag-latency-panel" style="display: none; padding: 16px; overflow-y: auto; flex: 1; font-size: 13px; line-height: 1.5; color: #e2e8f0; background: rgba(0,0,0,0.15); flex-direction: column; gap: 16px;">
        <div style="background: rgba(30, 41, 59, 0.6); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 10px; padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
          <span id="latency-active-title" style="font-weight: 800; color: #38bdf8; display: flex; align-items: center; gap: 6px; font-size: 13px;">
            <span>📊</span> Session Latency Benchmarks (Total Turnaround)
          </span>
          <span id="latency-turn-count-badge" style="background: rgba(56, 189, 248, 0.15); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 20px; padding: 2px 10px; font-size: 11px; font-weight: 800;">0 Turns</span>
        </div>

        <!-- Interactive Stage Selector Pills -->
        <div id="latency-filter-pills" style="display: flex; gap: 6px; flex-wrap: wrap;">
          <button class="lat-stage-pill" data-stage="total" style="background: #0284c7; color: #ffffff; border: 1px solid #38bdf8; padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 5px; transition: all 0.15s ease;">
            <span>🌟 Total (E2E)</span>
            <span id="pill-count-total" style="background: rgba(255,255,255,0.25); border-radius: 10px; padding: 1px 6px; font-size: 10px;">0</span>
          </button>
          <button class="lat-stage-pill" data-stage="llm" style="background: rgba(30, 41, 59, 0.8); color: #cbd5e1; border: 1px solid rgba(192, 132, 252, 0.3); padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 5px; transition: all 0.15s ease;">
            <span style="color: #c084fc;">🧠 LLM TTFB</span>
            <span id="pill-count-llm" style="background: rgba(192, 132, 252, 0.2); color: #e9d5ff; border-radius: 10px; padding: 1px 6px; font-size: 10px;">0</span>
          </button>
          <button class="lat-stage-pill" data-stage="stt" style="background: rgba(30, 41, 59, 0.8); color: #cbd5e1; border: 1px solid rgba(251, 191, 36, 0.3); padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 5px; transition: all 0.15s ease;">
            <span style="color: #fbbf24;">🎙️ STT Chirp</span>
            <span id="pill-count-stt" style="background: rgba(251, 191, 36, 0.2); color: #fef08a; border-radius: 10px; padding: 1px 6px; font-size: 10px;">0</span>
          </button>
          <button class="lat-stage-pill" data-stage="tts" style="background: rgba(30, 41, 59, 0.8); color: #cbd5e1; border: 1px solid rgba(74, 222, 128, 0.3); padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 5px; transition: all 0.15s ease;">
            <span style="color: #4ade80;">🔊 TTS Audio</span>
            <span id="pill-count-tts" style="background: rgba(74, 222, 128, 0.2); color: #bbf7d0; border-radius: 10px; padding: 1px 6px; font-size: 10px;">0</span>
          </button>
          <button class="lat-stage-pill" data-stage="live_ttfb" style="background: rgba(30, 41, 59, 0.8); color: #cbd5e1; border: 1px solid rgba(56, 189, 248, 0.3); padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 5px; transition: all 0.15s ease;">
            <span style="color: #38bdf8;">⚡ Gemini Live TTFB</span>
            <span id="pill-count-live" style="background: rgba(56, 189, 248, 0.2); color: #bae6fd; border-radius: 10px; padding: 1px 6px; font-size: 10px;">0</span>
          </button>
        </div>

        <!-- 4 KPI Percentile Cards -->
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;">
          <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 10px; padding: 12px; text-align: center;">
            <div id="lat-p50-label" style="font-size: 11px; font-weight: 700; color: #38bdf8; text-transform: uppercase;">P50 (Median)</div>
            <div id="lat-p50-val" style="font-size: 1.5rem; font-weight: 800; color: #f8fafc; margin: 4px 0;">-- ms</div>
            <div style="font-size: 10px; color: #64748b;">50% faster than this</div>
          </div>
          <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(192, 132, 252, 0.3); border-radius: 10px; padding: 12px; text-align: center;">
            <div id="lat-p90-label" style="font-size: 11px; font-weight: 700; color: #c084fc; text-transform: uppercase;">P90 (Tail)</div>
            <div id="lat-p90-val" style="font-size: 1.5rem; font-weight: 800; color: #f8fafc; margin: 4px 0;">-- ms</div>
            <div style="font-size: 10px; color: #64748b;">90% faster than this</div>
          </div>
          <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(251, 191, 36, 0.3); border-radius: 10px; padding: 12px; text-align: center;">
            <div id="lat-p95-label" style="font-size: 11px; font-weight: 700; color: #fbbf24; text-transform: uppercase;">P95 (Peak Tail)</div>
            <div id="lat-p95-val" style="font-size: 1.5rem; font-weight: 800; color: #f8fafc; margin: 4px 0;">-- ms</div>
            <div style="font-size: 10px; color: #64748b;">95% faster than this</div>
          </div>
          <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(74, 222, 128, 0.3); border-radius: 10px; padding: 12px; text-align: center;">
            <div id="lat-mean-label" style="font-size: 11px; font-weight: 700; color: #4ade80; text-transform: uppercase;">Mean (Average)</div>
            <div id="lat-mean-val" style="font-size: 1.5rem; font-weight: 800; color: #f8fafc; margin: 4px 0;">-- ms</div>
            <div id="lat-minmax-val" style="font-size: 10px; color: #64748b;">Min: -- / Max: --</div>
          </div>
        </div>

        <!-- Stage Percentile Breakdown Table -->
        <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; overflow: hidden;">
          <div style="padding: 8px 12px; background: rgba(255,255,255,0.03); font-weight: 700; font-size: 12px; color: #cbd5e1; border-bottom: 1px solid rgba(255, 255, 255, 0.08); display: flex; justify-content: space-between; align-items: center;">
            <span>⚡ Pipeline Stage Statistical Breakdown</span>
            <span style="font-size: 10px; color: #94a3b8; font-weight: 600;">Click any row to filter</span>
          </div>
          <table style="width: 100%; border-collapse: collapse; font-size: 12px; text-align: left;">
            <thead>
              <tr style="background: rgba(0,0,0,0.3); color: #94a3b8; font-size: 11px; text-transform: uppercase;">
                <th style="padding: 8px 12px;">Stage / Metric</th>
                <th style="padding: 8px 12px; color: #38bdf8;">P50</th>
                <th style="padding: 8px 12px; color: #c084fc;">P90</th>
                <th style="padding: 8px 12px; color: #fbbf24;">P95</th>
                <th style="padding: 8px 12px; color: #4ade80;">Mean</th>
                <th style="padding: 8px 12px;">Min / Max</th>
                <th style="padding: 8px 12px;">Turns</th>
              </tr>
            </thead>
            <tbody id="latency-breakdown-tbody">
              <tr>
                <td colspan="7" style="padding: 16px; text-align: center; color: #64748b; font-style: italic;">No turn latencies recorded yet. Start speaking to populate.</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Turn Waterfall History -->
        <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; overflow: hidden;">
          <div style="padding: 8px 12px; background: rgba(255,255,255,0.03); font-weight: 700; font-size: 12px; color: #cbd5e1; border-bottom: 1px solid rgba(255, 255, 255, 0.08);">
            ⏱️ Chronological Turn Waterfall History
          </div>
          <table style="width: 100%; border-collapse: collapse; font-size: 12px; text-align: left;">
            <thead>
              <tr style="background: rgba(0,0,0,0.3); color: #94a3b8; font-size: 11px; text-transform: uppercase;">
                <th style="padding: 8px 12px;">Time</th>
                <th style="padding: 8px 12px;">Stage</th>
                <th style="padding: 8px 12px;">Latency (ms)</th>
                <th style="padding: 8px 12px;">Latency (sec)</th>
                <th style="padding: 8px 12px;">Details</th>
              </tr>
            </thead>
            <tbody id="latency-turns-tbody">
              <tr>
                <td colspan="5" style="padding: 16px; text-align: center; color: #64748b; font-style: italic;">Waiting for voice turns...</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    `;

    container.appendChild(dialog);
    container.appendChild(badge);
    document.body.appendChild(container);

    let isOpen = false;
    let activeTab: "logs" | "latency" = "logs";
    let selectedLatencyStage: string = "total"; // "total" | "llm" | "stt" | "tts" | "live_ttfb"

    const logsTabBtn = dialog.querySelector("#diag-tab-logs-btn") as HTMLElement;
    const latencyTabBtn = dialog.querySelector("#diag-tab-latency-btn") as HTMLElement;
    const logsFeed = dialog.querySelector("#diag-log-feed") as HTMLElement;
    const latencyPanel = dialog.querySelector("#diag-latency-panel") as HTMLElement;

    const setTab = (tab: "logs" | "latency") => {
      activeTab = tab;
      if (tab === "logs") {
        logsTabBtn.style.background = "rgba(56, 189, 248, 0.22)";
        logsTabBtn.style.color = "#38bdf8";
        logsTabBtn.style.borderColor = "rgba(56, 189, 248, 0.4)";
        latencyTabBtn.style.background = "transparent";
        latencyTabBtn.style.color = "#94a3b8";
        latencyTabBtn.style.borderColor = "transparent";
        logsFeed.style.display = "block";
        latencyPanel.style.display = "none";
      } else {
        latencyTabBtn.style.background = "rgba(192, 132, 252, 0.22)";
        latencyTabBtn.style.color = "#c084fc";
        latencyTabBtn.style.borderColor = "rgba(192, 132, 252, 0.4)";
        logsTabBtn.style.background = "transparent";
        logsTabBtn.style.color = "#94a3b8";
        logsTabBtn.style.borderColor = "transparent";
        logsFeed.style.display = "none";
        latencyPanel.style.display = "flex";
      }
    };

    logsTabBtn.addEventListener("click", () => setTab("logs"));
    latencyTabBtn.addEventListener("click", () => setTab("latency"));

    // Stage filter pills event listeners
    const updatePillStyles = (activeStage: string) => {
      selectedLatencyStage = activeStage;
      dialog.querySelectorAll(".lat-stage-pill").forEach(p => {
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
    };

    dialog.querySelectorAll(".lat-stage-pill").forEach(p => {
      p.addEventListener("click", (e) => {
        const stage = (e.currentTarget as HTMLElement).dataset.stage || "total";
        updatePillStyles(stage);
      });
    });

    badge.addEventListener("click", () => {
      isOpen = !isOpen;
      dialog.style.display = isOpen ? "flex" : "none";
    });

    dialog.querySelector("#diag-close-btn")?.addEventListener("click", () => {
      isOpen = false;
      dialog.style.display = "none";
    });

    dialog.querySelector("#diag-copy-btn")?.addEventListener("click", async (e) => {
      const textToCopy = activeTab === "logs" ? (logsFeed.innerText || "") : (latencyPanel.innerText || "");
      await navigator.clipboard.writeText(textToCopy);
      const btn = e.currentTarget as HTMLElement;
      const orig = btn.innerHTML;
      btn.innerHTML = '<i class="fas fa-check"></i> Copied';
      setTimeout(() => { btn.innerHTML = orig; }, 1500);
    });

    dialog.querySelector("#diag-clear-btn")?.addEventListener("click", async () => {
      try {
        await fetch(`${getApiBaseUrl()}/api/logs/clear`, { method: "POST" });
      } catch (err) {}
      logsFeed.innerHTML = '<div style="color: #64748b; font-style: italic; padding: 20px; text-align: center;">Logs cleared. Waiting for fresh items...</div>';
      const countSpan = document.getElementById("diag-log-count");
      if (countSpan) countSpan.innerText = "0";
      if (this.debugLog) this.debugLog.innerHTML = "";
    });

    setInterval(async () => {
      try {
        const res = await fetch(`${getApiBaseUrl()}/api/logs`);
        if (!res.ok) return;
        const data = await res.json();
        const logs: Array<{ timestamp: string; level: string; message: string; ttfb_ms?: number }> = data.logs || [];
        const latencySummary = data.latency_summary || null;

        // Check latest TTFB
        for (let i = logs.length - 1; i >= 0; i--) {
          if (logs[i].ttfb_ms && logs[i].ttfb_ms! > 0) {
            const pill = document.getElementById("diag-ttfb-pill");
            if (pill) pill.innerText = `TTFB: ${logs[i].ttfb_ms} ms`;
            break;
          }
        }

        const countSpan = document.getElementById("diag-log-count");
        if (countSpan) countSpan.innerText = String(logs.length);

        // Update Latency Benchmarks Dashboard with Stage Filtering
        if (latencySummary) {
          const liveStat = latencySummary.live_ttfb || {};
          const llmStat = latencySummary.llm || {};
          const sttStat = latencySummary.stt || {};
          const ttsStat = latencySummary.tts || {};
          const totalStat = latencySummary.total_turnaround || {};
          const turns: Array<{ timestamp: string; stage: string; value_ms: number; details: string }> = latencySummary.turns || [];

          // Update stage pill count badges
          const cTotal = document.getElementById("pill-count-total");
          const cLlm = document.getElementById("pill-count-llm");
          const cStt = document.getElementById("pill-count-stt");
          const cTts = document.getElementById("pill-count-tts");
          const cLive = document.getElementById("pill-count-live");
          if (cTotal) cTotal.innerText = String(totalStat.count || 0);
          if (cLlm) cLlm.innerText = String(llmStat.count || 0);
          if (cStt) cStt.innerText = String(sttStat.count || 0);
          if (cTts) cTts.innerText = String(ttsStat.count || 0);
          if (cLive) cLive.innerText = String(liveStat.count || 0);

          // Select stat according to active filter pill
          let activeStat = totalStat;
          let stageLabel = "Total Turnaround (E2E)";
          if (selectedLatencyStage === "llm") {
            activeStat = llmStat;
            stageLabel = "LLM TTFB (Reasoning Stream)";
          } else if (selectedLatencyStage === "stt") {
            activeStat = sttStat;
            stageLabel = "STT Chirp Latency";
          } else if (selectedLatencyStage === "tts") {
            activeStat = ttsStat;
            stageLabel = "TTS Audio Synthesis";
          } else if (selectedLatencyStage === "live_ttfb") {
            activeStat = liveStat;
            stageLabel = "Gemini Live Native TTFB";
          }

          const titleEl = document.getElementById("latency-active-title");
          if (titleEl) titleEl.innerHTML = `<span>📊</span> Session Latency: <span style="color: #f8fafc; margin-left: 4px;">${stageLabel}</span>`;

          const p50El = document.getElementById("lat-p50-val");
          const p90El = document.getElementById("lat-p90-val");
          const p95El = document.getElementById("lat-p95-val");
          const meanEl = document.getElementById("lat-mean-val");
          const minmaxEl = document.getElementById("lat-minmax-val");
          const badgeEl = document.getElementById("latency-turn-count-badge");

          if (p50El) p50El.innerText = activeStat.p50 !== undefined && activeStat.count > 0 ? `${activeStat.p50} ms` : "-- ms";
          if (p90El) p90El.innerText = activeStat.p90 !== undefined && activeStat.count > 0 ? `${activeStat.p90} ms` : "-- ms";
          if (p95El) p95El.innerText = activeStat.p95 !== undefined && activeStat.count > 0 ? `${activeStat.p95} ms` : "-- ms";
          if (meanEl) meanEl.innerText = activeStat.mean !== undefined && activeStat.count > 0 ? `${activeStat.mean} ms` : "-- ms";
          if (minmaxEl) minmaxEl.innerText = activeStat.count > 0 ? `Min: ${activeStat.min}ms / Max: ${activeStat.max}ms` : "Min: -- / Max: --";
          if (badgeEl) badgeEl.innerText = `${activeStat.count || 0} Turns (${stageLabel})`;

          // Populate Breakdown Table
          const tbody = document.getElementById("latency-breakdown-tbody");
          if (tbody) {
            const rows = [
              { stageKey: "total", name: "🌟 Total Turnaround (End-to-End)", stat: totalStat, color: "#f472b6" },
              { stageKey: "llm", name: "🧠 LLM TTFB (Reasoning Stream)", stat: llmStat, color: "#c084fc" },
              { stageKey: "stt", name: "🎙️ STT Latency (Cloud Speech v2 Chirp)", stat: sttStat, color: "#fbbf24" },
              { stageKey: "tts", name: "🔊 TTS Latency (Audio Synthesis)", stat: ttsStat, color: "#4ade80" },
              { stageKey: "live_ttfb", name: "⚡ Gemini Live TTFB (Native Duplex)", stat: liveStat, color: "#38bdf8" },
            ].filter(r => r.stat && r.stat.count > 0);

            if (rows.length > 0) {
              tbody.innerHTML = rows.map(r => `
                <tr class="lat-breakdown-row" data-stage="${r.stageKey}" style="border-bottom: 1px solid rgba(255,255,255,0.05); font-family: monospace; cursor: pointer; transition: background 0.15s ease;" onmouseover="this.style.background='rgba(255,255,255,0.05)'" onmouseout="this.style.background='transparent'">
                  <td style="padding: 8px 12px; font-weight: 700; color: ${r.color};">${r.name}</td>
                  <td style="padding: 8px 12px; font-weight: 800; color: #38bdf8;">${r.stat.p50} ms</td>
                  <td style="padding: 8px 12px; font-weight: 800; color: #c084fc;">${r.stat.p90} ms</td>
                  <td style="padding: 8px 12px; font-weight: 800; color: #fbbf24;">${r.stat.p95} ms</td>
                  <td style="padding: 8px 12px; font-weight: 800; color: #4ade80;">${r.stat.mean} ms</td>
                  <td style="padding: 8px 12px; color: #94a3b8;">${r.stat.min} - ${r.stat.max} ms</td>
                  <td style="padding: 8px 12px; color: #cbd5e1; font-weight: 700;">${r.stat.count}</td>
                </tr>
              `).join("");

              tbody.querySelectorAll(".lat-breakdown-row").forEach(row => {
                row.addEventListener("click", (e) => {
                  const stage = (e.currentTarget as HTMLElement).dataset.stage || "total";
                  updatePillStyles(stage);
                });
              });
            }
          }

          // Populate Waterfall Turns Table with Filter
          const turnsTbody = document.getElementById("latency-turns-tbody");
          if (turnsTbody) {
            const filteredTurns = turns.filter(t => {
              if (selectedLatencyStage === "total") return true;
              return t.stage === selectedLatencyStage;
            });

            if (filteredTurns.length === 0) {
              turnsTbody.innerHTML = `<tr><td colspan="5" style="padding: 16px; text-align: center; color: #64748b; font-style: italic;">No recorded turns for stage: ${stageLabel}</td></tr>`;
            } else {
              turnsTbody.innerHTML = [...filteredTurns].reverse().slice(0, 30).map(t => {
                let stageBadge = `<span style="background: rgba(56, 189, 248, 0.18); color: #38bdf8; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 700;">${t.stage.toUpperCase()}</span>`;
                if (t.stage === "llm") stageBadge = `<span style="background: rgba(192, 132, 252, 0.18); color: #c084fc; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 700;">LLM TTFB</span>`;
                if (t.stage === "stt") stageBadge = `<span style="background: rgba(251, 191, 36, 0.18); color: #fbbf24; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 700;">STT CHIRP</span>`;
                if (t.stage === "tts") stageBadge = `<span style="background: rgba(74, 222, 128, 0.18); color: #4ade80; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 700;">TTS AUDIO</span>`;

                return `
                  <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); font-family: monospace;">
                    <td style="padding: 6px 12px; color: #94a3b8; font-size: 11px;">⏱️ ${t.timestamp}</td>
                    <td style="padding: 6px 12px;">${stageBadge}</td>
                    <td style="padding: 6px 12px; font-weight: 800; color: #f8fafc;">${t.value_ms} ms</td>
                    <td style="padding: 6px 12px; color: #7dd3fc;">${(t.value_ms / 1000).toFixed(3)}s</td>
                    <td style="padding: 6px 12px; color: #94a3b8; font-size: 11px;">${t.details || "-"}</td>
                  </tr>
                `;
              }).join("");
            }
          }
        }

        if (!isOpen || activeTab !== "logs") return;

        const feed = document.getElementById("diag-log-feed");
        if (!feed) return;

        const isNearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;

        if (logs.length === 0) {
          feed.innerHTML = `<div style="color: #64748b; font-style: italic; padding: 20px; text-align: center;">No logs recorded yet...</div>`;
          return;
        }

        feed.innerHTML = logs.map((item) => {
          let cardBg = "rgba(15, 23, 42, 0.6)";
          let borderLeftColor = "#475569";
          let badgeText = item.level || "INFO";
          let badgeStyle = "background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.3);";

          if (item.level === "ERROR" || item.message.toLowerCase().includes("error") || item.message.toLowerCase().includes("exception")) {
            cardBg = "rgba(239, 68, 68, 0.12)";
            borderLeftColor = "#ef4444";
            badgeText = "ERROR";
            badgeStyle = "background: rgba(239, 68, 68, 0.25); color: #f87171; border: 1px solid #dc2626;";
          } else if (item.level === "WARNING" || item.message.toLowerCase().includes("warn")) {
            cardBg = "rgba(234, 179, 8, 0.08)";
            borderLeftColor = "#eab308";
            badgeText = "WARN";
            badgeStyle = "background: rgba(234, 179, 8, 0.2); color: #facc15; border: 1px solid #ca8a04;";
          } else if (item.ttfb_ms || item.message.includes("TTFB") || item.message.includes("Latency")) {
            cardBg = "rgba(56, 189, 248, 0.08)";
            borderLeftColor = "#38bdf8";
            badgeText = "⚡ LATENCY";
            badgeStyle = "background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid #0284c7;";
          }

          const textColor = item.level === "ERROR" ? "#fca5a5" : item.level === "WARNING" ? "#fde047" : "#f1f5f9";
          return `<div class="diag-card" style="margin-bottom: 10px; padding: 10px 14px; background: ${cardBg}; border-radius: 8px; border-left: 4px solid ${borderLeftColor}; border-top: 1px solid rgba(255,255,255,0.05); border-right: 1px solid rgba(255,255,255,0.05); border-bottom: 1px solid rgba(255,255,255,0.05);">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
              <span style="font-size: 11px; color: #94a3b8; font-weight: 600;">⏱️ ${item.timestamp}</span>
              <span style="padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 700; ${badgeStyle}">${badgeText}</span>
            </div>
            <div style="color: ${textColor}; word-break: break-word; font-family: monospace;">${item.message}</div>
          </div>`;
        }).join("");
        if (isNearBottom) {
          feed.scrollTop = feed.scrollHeight;
        }
      } catch (e) {
        // silently ignore fetch errors
      }
    }, 1500);
  }
}

declare global {
  interface Window {
    WebsocketClientApp: typeof WebsocketClientApp;
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  window.WebsocketClientApp = WebsocketClientApp;
  const app = new WebsocketClientApp();
  await app.loadSystemPrompt();
});
