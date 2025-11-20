import { RTVIClient, RTVIEvent, } from "@pipecat-ai/client-js";
import { WebSocketTransport } from "@pipecat-ai/websocket-transport";
const getApiBaseUrl = () => {
    const host = window.location.hostname;
    const port = window.location.port;
    const protocol = window.location.protocol;
    return `${protocol}//${host}${port ? `:${port}` : ""}`;
};
class WebsocketClientApp {
    rtviClient = null;
    connectBtn = null;
    listenBtn = null;
    stopBtn = null;
    statusSpan = null;
    statusIndicator = null;
    debugLog = null;
    audioContext = null;
    connectionLight = null;
    micLight = null;
    speakerLight = null;
    voiceStatus = null;
    listeningIndicator = null;
    speakingIndicator = null;
    dotsContainer = null;
    tabs = null;
    configPanels = null;
    activeTab = "tts-llm-stt";
    activePipeline = null;
    constructor() {
        this.setupDOMElements();
        this.setupEventListeners();
    }
    setupDOMElements() {
        this.connectBtn = document.getElementById("connect-btn");
        this.listenBtn = document.getElementById("listen-btn");
        this.stopBtn = document.getElementById("stop-btn");
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
    }
    setupEventListeners() {
        this.connectBtn?.addEventListener("click", () => this.toggleConnection());
        this.listenBtn?.addEventListener("click", () => this.startListening());
        this.stopBtn?.addEventListener("click", () => this.stopListening());
        this.tabs?.forEach((tab) => {
            tab.addEventListener("click", () => this.switchTab(tab));
        });
        const paceSlider = document.getElementById("tts-pace-slider");
        const paceValue = document.getElementById("tts-pace-value");
        if (paceSlider && paceValue) {
            paceSlider.addEventListener("input", () => {
                paceValue.textContent = parseFloat(paceSlider.value).toFixed(2);
            });
        }
        const livePaceSlider = document.getElementById("live-tts-pace-slider");
        const livePaceValue = document.getElementById("live-tts-pace-value");
        if (livePaceSlider && livePaceValue) {
            livePaceSlider.addEventListener("input", () => {
                livePaceValue.textContent = parseFloat(livePaceSlider.value).toFixed(2);
            });
        }
        const shortPauseBtn = document.getElementById("pause-short-btn");
        const longPauseBtn = document.getElementById("pause-long-btn");
        const systemInstructionsTextarea = document.getElementById("tts-llm-stt-system-instructions-textarea");
        shortPauseBtn?.addEventListener("click", () => {
            systemInstructionsTextarea.value += " [pause short]";
        });
        longPauseBtn?.addEventListener("click", () => {
            systemInstructionsTextarea.value += " [pause long]";
        });
        const geminiModelSelect = document.getElementById("gemini-model-select");
        const ttsWarning = document.getElementById("tts-warning");
        const voiceWarning = document.getElementById("voice-warning");
        const geminiVoiceSelect = document.getElementById("gemini-voice-select");
        const ttsToggle = document.getElementById("tts-toggle");
        const handleModelChange = () => {
            const selectedModel = geminiModelSelect.value;
            const selectedVoice = geminiVoiceSelect.value;
            if (selectedModel.includes("native-audio")) {
                if (ttsToggle.checked) {
                    ttsWarning.style.display = "block";
                }
                else {
                    ttsWarning.style.display = "none";
                }
                if (selectedVoice.startsWith("Custom")) {
                    voiceWarning.style.display = "block";
                }
                else {
                    voiceWarning.style.display = "none";
                }
            }
            else {
                ttsWarning.style.display = "none";
                voiceWarning.style.display = "none";
            }
        };
        geminiModelSelect?.addEventListener("change", handleModelChange);
        geminiVoiceSelect?.addEventListener("change", handleModelChange);
        ttsToggle?.addEventListener("change", handleModelChange);
    }
    async loadSystemPrompt() {
        try {
            const response = await fetch(`${getApiBaseUrl()}/system-prompt`);
            const data = await response.json();
            const geminiSystemInstructionsTextarea = document.getElementById("system-instructions-textarea");
            if (geminiSystemInstructionsTextarea) {
                geminiSystemInstructionsTextarea.value = data.system_prompt;
            }
            const ttsLlmSttSystemInstructionsTextarea = document.getElementById("tts-llm-stt-system-instructions-textarea");
            if (ttsLlmSttSystemInstructionsTextarea) {
                ttsLlmSttSystemInstructionsTextarea.value = data.system_prompt;
            }
        }
        catch (error) {
            this.log(`Error loading system prompt: ${error}`, "error");
        }
    }
    switchTab(tab) {
        const tabId = tab.dataset.tab;
        if (!tabId)
            return;
        this.activeTab = tabId;
        this.tabs?.forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        this.configPanels?.forEach((panel) => {
            if (panel.id === `${tabId}-panel`) {
                panel.classList.add("active");
            }
            else {
                panel.classList.remove("active");
            }
        });
        if (this.activePipeline) {
            if (tabId === "tts-llm-stt") {
                this.activePipeline.textContent = "Active: TTS-LLM-STT Pipeline";
            }
            else if (tabId === "gemini-live") {
                this.activePipeline.textContent = "Active: Gemini Live Pipeline";
            }
        }
    }
    log(message, level = "info") {
        if (!this.debugLog)
            return;
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
        console.log(`[${level.toUpperCase()}] ${message}`);
    }
    updateStatus(status) {
        if (this.statusSpan) {
            this.statusSpan.textContent = status;
        }
        if (this.statusIndicator) {
            this.statusIndicator.className = status.toLowerCase();
        }
        if (this.connectionLight) {
            this.connectionLight.textContent =
                status === "Connected" ? "Active" : "Inactive";
            this.connectionLight.className = `light ${status === "Connected" ? "active" : "inactive"}`;
        }
        this.log(`Status: ${status}`);
    }
    updateMicStatus(status) {
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
    updateSpeakerStatus(status) {
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
    toggleConnection() {
        if (this.rtviClient) {
            this.disconnect();
        }
        else {
            this.connect();
        }
    }
    startListening() {
        if (this.rtviClient) {
            const tracks = this.rtviClient.tracks();
            if (tracks.local?.audio) {
                tracks.local.audio.enabled = true;
                this.log("Microphone unmuted");
            }
            this.updateMicStatus("active");
            this.listenBtn.disabled = true;
            this.stopBtn.disabled = false;
        }
    }
    stopListening() {
        if (this.rtviClient) {
            const tracks = this.rtviClient.tracks();
            if (tracks.local?.audio) {
                tracks.local.audio.enabled = false;
                this.log("Microphone muted");
            }
            this.updateMicStatus("idle");
            this.listenBtn.disabled = false;
            this.stopBtn.disabled = true;
        }
    }
    setupMediaTracks() {
        if (!this.rtviClient)
            return;
        const tracks = this.rtviClient.tracks();
        if (tracks.bot?.audio) {
            this.setupAudioTrack(tracks.bot.audio);
        }
    }
    setupTrackListeners() {
        if (!this.rtviClient)
            return;
        this.rtviClient.on(RTVIEvent.TrackStarted, (track, participant) => {
            if (!participant?.local && track.kind === "audio") {
                this.setupAudioTrack(track);
                this.updateSpeakerStatus("active");
            }
        });
        this.rtviClient.on(RTVIEvent.TrackStopped, (track, participant) => {
            this.log(`Track stopped: ${track.kind} from ${participant?.name || "unknown"}`);
            if (!participant?.local && track.kind === "audio") {
                this.updateSpeakerStatus("silent");
            }
        });
    }
    setupAudioTrack(track) {
        this.log("Setting up audio track");
        const audioEl = document.getElementById("bot-audio");
        if (audioEl) {
            const stream = new MediaStream([track]);
            audioEl.srcObject = stream;
            audioEl.play().catch(e => this.log(`Audio play failed: ${e}`, "error"));
        }
    }
    async connect() {
        try {
            this.audioContext = new AudioContext();
            this.audioContext.resume();
            this.updateStatus("Connecting");
            const transport = new WebSocketTransport();
            const apiKeyInput = document.getElementById("api-key-input");
            const apiKey = apiKeyInput.value;
            if (!apiKey) {
                this.log("No API key provided, attempting to use server-side credentials (Vertex AI)", "warning");
            }
            let connectUrl = `/connect?bot_type=${this.activeTab}&api_key=${apiKey}`;
            let systemInstructions = "";
            if (this.activeTab === "tts-llm-stt") {
                const ttsVoiceSelect = document.getElementById("tts-voice-select");
                const llmModelSelect = document.getElementById("llm-model-select");
                const sttModelSelect = document.getElementById("stt-model-select");
                const sttLanguageSelect = document.getElementById("stt-language-select");
                const systemInstructionsTextarea = document.getElementById("tts-llm-stt-system-instructions-textarea");
                const paceSlider = document.getElementById("tts-pace-slider");
                connectUrl += `&tts_voice=${ttsVoiceSelect.value}`;
                connectUrl += `&tts_pace=${paceSlider.value}`;
                connectUrl += `&llm_model=${llmModelSelect.value}`;
                connectUrl += `&stt_model=${sttModelSelect.value}`;
                connectUrl += `&stt_language=${sttLanguageSelect.value}`;
                systemInstructions = systemInstructionsTextarea.value;
            }
            else {
                const geminiModelSelect = document.getElementById("gemini-model-select");
                const geminiVoiceSelect = document.getElementById("gemini-voice-select");
                const geminiLanguageSelect = document.getElementById("gemini-language-select");
                const geminiSystemInstructionsTextarea = document.getElementById("system-instructions-textarea");
                const ttsToggle = document.getElementById("tts-toggle");
                const livePaceSlider = document.getElementById("live-tts-pace-slider");
                connectUrl += `&model=${geminiModelSelect.value}`;
                connectUrl += `&voice=${geminiVoiceSelect.value}`;
                connectUrl += `&language=${geminiLanguageSelect.value}`;
                connectUrl += `&tts=${ttsToggle.checked}`;
                connectUrl += `&tts_pace=${livePaceSlider.value}`;
                systemInstructions = geminiSystemInstructionsTextarea.value;
            }
            if (systemInstructions) {
                connectUrl += `&system_instruction=${encodeURIComponent(systemInstructions)}`;
            }
            const RTVIConfig = {
                transport,
                params: {
                    baseUrl: import.meta.env.VITE_WSS_URL || getApiBaseUrl(),
                    endpoints: {
                        connect: connectUrl,
                    },
                },
                enableMic: true,
                enableCam: false,
                callbacks: {
                    onConnected: () => {
                        this.updateStatus("Connected");
                        if (this.connectBtn)
                            this.connectBtn.textContent = "Disconnect";
                        if (this.listenBtn)
                            this.listenBtn.disabled = false;
                    },
                    onDisconnected: () => {
                        this.updateStatus("Disconnected");
                        if (this.connectBtn)
                            this.connectBtn.textContent = "Connect";
                        if (this.listenBtn)
                            this.listenBtn.disabled = true;
                        if (this.stopBtn)
                            this.stopBtn.disabled = true;
                        this.updateMicStatus("idle");
                        this.log("Client disconnected");
                    },
                    onBotReady: (data) => {
                        this.log(`Bot ready: ${JSON.stringify(data)}`);
                        this.setupMediaTracks();
                    },
                    onGenericMessage: (message) => {
                        this.log(`Generic message: ${JSON.stringify(message)}`);
                        if (message.type === "transcription") {
                            const { participant, text } = message;
                            this.log(`[${participant}] ${text}`, "info");
                        }
                    },
                    onMessageError: (error) => this.log(`Message error: ${error}`, "error"),
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
        }
        catch (error) {
            this.log(`Error connecting: ${error.message}`, "error");
            this.updateStatus("Error");
            if (this.rtviClient) {
                try {
                    await this.rtviClient.disconnect();
                }
                catch (disconnectError) {
                    this.log(`Error during disconnect: ${disconnectError}`, "error");
                }
            }
        }
    }
    async disconnect() {
        if (this.rtviClient) {
            try {
                await this.rtviClient.disconnect();
                this.rtviClient = null;
                if (this.audioContext) {
                    this.audioContext.close();
                    this.audioContext = null;
                }
            }
            catch (error) {
                this.log(`Error disconnecting: ${error.message}`, "error");
            }
        }
    }
}
window.addEventListener("DOMContentLoaded", () => {
    window.WebsocketClientApp = WebsocketClientApp;
    const app = new WebsocketClientApp();
    app.loadSystemPrompt();
});
