import {
  RTVIClient,
  RTVIClientOptions,
  RTVIEvent,
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

      if (selectedModel.includes("native-audio")) {
        if (ttsToggle.checked) {
          ttsWarning.style.display = "block";
        } else {
          ttsWarning.style.display = "none";
        }
        if (selectedVoice.startsWith("Custom")) {
          voiceWarning.style.display = "block";
        } else {
          voiceWarning.style.display = "none";
        }
      } else {
        ttsWarning.style.display = "none";
        voiceWarning.style.display = "none";
      }
    };

    geminiModelSelect?.addEventListener("change", handleModelChange);
    geminiVoiceSelect?.addEventListener("change", handleModelChange);
    ttsToggle?.addEventListener("change", handleModelChange);

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
        this.activePipeline.textContent = "Active: TTS-LLM-STT Pipeline";
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

  // --- Observability Helpers ---

  private resetMetrics() {
      this.turnCount = 0;
      this.interruptCount = 0;
      this.toolCallCount = 0;
      this.tokenCount = 0;
      this.updateMetricDisplay();
      if (this.chatWindow) this.chatWindow.innerHTML = "";
  }

  private updateMetricDisplay() {
      if (this.metricTurnCount) this.metricTurnCount.textContent = this.turnCount.toString();
      if (this.metricInterruptCount) this.metricInterruptCount.textContent = this.interruptCount.toString();
      if (this.metricToolCallCount) this.metricToolCallCount.textContent = this.toolCallCount.toString();
      if (this.metricTokenCount) this.metricTokenCount.textContent = this.tokenCount.toString();
  }

  private appendChatMessage(role: "user" | "bot", text: string) {
    if (!this.chatWindow) return;
    
    const lastBubble = this.chatWindow.lastElementChild;
    if (lastBubble && lastBubble.classList.contains(role)) {
      const timestamp = lastBubble.querySelector(".timestamp");
      if (timestamp) {
        timestamp.before(document.createTextNode(text));
      } else {
        lastBubble.textContent += text;
      }
      this.chatWindow.scrollTop = this.chatWindow.scrollHeight;
      return;
    }

    const bubble = document.createElement("div");
    bubble.classList.add("chat-bubble", role);
    bubble.textContent = text;
    
    const timestamp = document.createElement("span");
    timestamp.classList.add("timestamp");
    timestamp.textContent = new Date().toLocaleTimeString();
    bubble.appendChild(timestamp);

    this.chatWindow.appendChild(bubble);
    this.chatWindow.scrollTop = this.chatWindow.scrollHeight;
  }

  private handleServerMessage(message: any) {
      // Handle Transcription
      if (message.type === "transcription") {
          const { participant, text } = message;
          // Pipecat usually sends "User" or "Assistant" or similar.
          // Map participant to role
          const role = (participant === "User" || participant === "user") ? "user" : "bot";
          this.appendChatMessage(role, text);
      }

      // Handle Metrics
      // Case 1: OutputTransportMessageFrame format
      if (message.type === "metrics") {
          const payload = message.payload;
          if (!payload) return;
          
          switch (payload.type) {
              case "interruption":
                  this.interruptCount += (payload.count || 1);
                  break;
              case "turn_complete":
                  this.turnCount++;
                  break;
              case "tool_call":
                  this.toolCallCount++;
                  // Optionally log tool details to chat or debug
                  this.log(`Tool Call: ${JSON.stringify(payload.tool)}`, "info");
                  break;
              case "usage":
                  if (payload.usage && payload.usage.total_token_count) {
                      // Is this cumulative or per turn? Usually per turn.
                      // But we want total for the session.
                      // Wait, API usage is per turn. So I should accumulate.
                      this.tokenCount += payload.usage.total_token_count;
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
                      if (data.usage && data.usage.total_token_count) {
                          // Is this cumulative or per turn? Usually per turn.
                          // But we want total for the session.
                          // Wait, API usage is per turn. So I should accumulate.
                          this.tokenCount += data.usage.total_token_count;
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

      let connectUrl = `/connect?bot_type=${this.activeTab}`;
      let systemInstructions = "";

      if (this.activeTab === "tts-llm-stt") {
        const ttsVoiceSelect = document.getElementById(
          "tts-voice-select"
        ) as HTMLSelectElement;
        const ttsModelSelect = document.getElementById(
          "tts-model-select"
        ) as HTMLSelectElement;
        const llmModelSelect = document.getElementById(
          "llm-model-select"
        ) as HTMLSelectElement;
        const sttModelSelect = document.getElementById(
          "stt-model-select"
        ) as HTMLSelectElement;
        const sttLanguageSelect = document.getElementById(
          "stt-language-select"
        ) as HTMLSelectElement;
        const systemInstructionsTextarea = document.getElementById(
          "tts-llm-stt-system-instructions-textarea"
        ) as HTMLTextAreaElement;
        const paceSlider = document.getElementById("tts-pace-slider") as HTMLInputElement;

        connectUrl += `&tts_voice=${ttsVoiceSelect.value}`;
        connectUrl += `&tts_model=${ttsModelSelect.value}`;
        connectUrl += `&tts_pace=${paceSlider.value}`;
        connectUrl += `&llm_model=${llmModelSelect.value}`;
        connectUrl += `&stt_model=${sttModelSelect.value}`;
        connectUrl += `&stt_language=${sttLanguageSelect.value}`;
        systemInstructions = systemInstructionsTextarea.value;
      } else {
        const geminiModelSelect = document.getElementById(
          "gemini-model-select"
        ) as HTMLSelectElement;
        const geminiVoiceSelect = document.getElementById(
          "gemini-voice-select"
        ) as HTMLSelectElement;
        const geminiLanguageSelect = document.getElementById(
          "gemini-language-select"
        ) as HTMLSelectElement;
        const geminiSystemInstructionsTextarea = document.getElementById(
          "system-instructions-textarea"
        ) as HTMLTextAreaElement;
        const ttsToggle = document.getElementById(
          "tts-toggle"
        ) as HTMLInputElement;
        const livePaceSlider = document.getElementById(
          "live-tts-pace-slider"
        ) as HTMLInputElement;

        connectUrl += `&model=${geminiModelSelect.value}`;
        connectUrl += `&voice=${geminiVoiceSelect.value}`;
        connectUrl += `&language=${geminiLanguageSelect.value}`;
        connectUrl += `&tts=${ttsToggle.checked}`;
        connectUrl += `&tts_pace=${livePaceSlider.value}`;
        systemInstructions = geminiSystemInstructionsTextarea.value;
      }

      if (systemInstructions) {
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
          onMessageError: (error) =>
            this.log(`Message error: ${error}`, "error"),
          onError: (error) => this.log(`Error: ${error}`, "error"),
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
}

declare global {
  interface Window {
    WebsocketClientApp: typeof WebsocketClientApp;
  }
}

window.addEventListener("DOMContentLoaded", () => {
  window.WebsocketClientApp = WebsocketClientApp;
  const app = new WebsocketClientApp();
  app.loadSystemPrompt();
});
