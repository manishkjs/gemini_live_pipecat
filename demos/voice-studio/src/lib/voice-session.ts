import { getPersona, type PersonaId } from "./personas.ts";

export type Engine = "live" | "cascade";
export type SessionSettings = {
  backendUrl: string;
  engine: Engine;
  personaId: PersonaId;
  model: string;
  voice: string;
  language: string;
  instructions: string;
  sttModel: string;
  llmModel: string;
  ttsModel: string;
  ttsPace?: number;
  tts?: boolean;
  skipStt?: boolean;
  vad?: boolean;
  contextCompression?: boolean;
  contextCompressionTokens?: number;
  toolsJson?: string;
  thinking?: boolean;
  thinkingBudget?: number;
  thinkingLevel?: "minimal" | "low" | "medium" | "high";
  customVoiceKey?: string;
};

export function getDefaultBackendUrl(): string {
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  return "http://localhost:7860";
}

export const DEFAULT_SETTINGS: SessionSettings = {
  backendUrl: typeof window !== "undefined" ? getDefaultBackendUrl() : "http://localhost:7860",
  engine: "live",
  personaId: "debt-collector",
  model: "gemini-3.5-flash-live-preview",
  voice: "Aoede",
  language: "hi-IN",
  instructions: "",
  sttModel: "gemini-3.5-transcribe-live-aistudio",
  llmModel: "gemini-3.5-flash-lite",
  ttsModel: "gemini-3.1-flash-tts-preview",
  ttsPace: 1.0,
  tts: false,
  skipStt: false,
  vad: true,
  contextCompression: false,
  contextCompressionTokens: 20000,
  toolsJson: "",
  thinking: false,
  thinkingBudget: 0,
  thinkingLevel: "minimal",
  customVoiceKey: "",
};

export const LANGUAGE_MAP: Record<string, string> = {
  "hi-IN": "Hindi",
  "en-IN": "English",
  "bn-IN": "Bengali",
  "te-IN": "Telugu",
  "mr-IN": "Marathi",
  "ta-IN": "Tamil",
  "gu-IN": "Gujarati",
  "kn-IN": "Kannada",
  "ml-IN": "Malayalam",
  "pa-IN": "Punjabi",
  "ur-IN": "Urdu",
  "en-US": "English",
  "es-ES": "Spanish",
  "fr-FR": "French",
  "de-DE": "German",
  "ja-JP": "Japanese",
};

export const LANGUAGE_OPTIONS: [string, string][] = [
  ["hi-IN", "Hindi (हिंदी)"],
  ["en-IN", "English (India)"],
  ["bn-IN", "Bengali (বাংলা)"],
  ["te-IN", "Telugu (తెలుగు)"],
  ["mr-IN", "Marathi (मराठी)"],
  ["ta-IN", "Tamil (தமிழ்)"],
  ["gu-IN", "Gujarati (ગુજરાતી)"],
  ["kn-IN", "Kannada (ಕನ್ನಡ)"],
  ["ml-IN", "Malayalam (മലയാളം)"],
  ["pa-IN", "Punjabi (ਪੰਜਾਬੀ)"],
  ["ur-IN", "Urdu (اردو)"],
  ["en-US", "English (US)"],
  ["es-ES", "Spanish"],
  ["fr-FR", "French"],
  ["de-DE", "German"],
  ["ja-JP", "Japanese"],
];

export const LIVE_MODELS: [string, string][] = [
  ["gemini-3.5-flash-live-preview", "gemini-3.5-flash-live-preview (Vertex AI Live - Default)"],
  ["gemini-3.5-flash-lite-live-preview", "gemini-3.5-flash-lite-live-preview (Vertex AI Live Lite)"],
  ["gemini-live-2.5-flash-native-audio", "gemini-live-2.5-flash-native-audio (Vertex AI)"],
  ["gemini-live-2.5-flash", "gemini-live-2.5-flash (Vertex AI Cascaded)"],
  ["gemini-3.5-live-preview", "gemini-3.5-live-preview (AI Studio)"],
  ["gemini-3.5-live-extended-thinking-preview", "gemini-3.5-live-extended-thinking-preview (AI Studio)"],
  ["gemini-3.1-flash-live-preview", "gemini-3.1-flash-live-preview (AI Studio)"],
];

export const CASCADE_STT_MODELS: [string, string][] = [
  ["gemini-3.5-transcribe-live-aistudio", "gemini-3.5-transcribe-live-aistudio (AI Studio Live STT - Default)"],
  ["gemini-3.5-transcribe-live-preview", "gemini-3.5-transcribe-live-preview (Vertex AI Live STT - Global)"],
  ["chirp_3", "chirp_3 (Cloud Speech v2 Multilingual - US)"],
  ["chirp_2", "chirp_2 (Cloud Speech v2 - us-central1)"],
  ["latest_long", "latest_long (General Long - US)"],
  ["telephony", "telephony (Telephony - US)"],
];

export const CASCADE_LLM_MODELS: [string, string][] = [
  ["gemini-3.5-flash-lite", "gemini-3.5-flash-lite (Default)"],
  ["gemini-3.7-flash", "gemini-3.7-flash"],
  ["gemini-2.5-flash", "gemini-2.5-flash"],
  ["gemini-2.5-flash-lite", "gemini-2.5-flash-lite"],
];

export const CASCADE_TTS_MODELS: [string, string][] = [
  ["gemini-3.1-flash-tts-preview", "gemini-3.1-flash-tts-preview (Gemini 3.1 Flash TTS - Default)"],
  ["gemini-2.5-flash-lite-preview-tts", "gemini-2.5-flash-lite-preview-tts (Gemini 2.5)"],
  ["gemini-2.5-flash-preview-tts", "gemini-2.5-flash-preview-tts (Gemini 2.5)"],
  ["gemini-2.5-pro-preview-tts", "gemini-2.5-pro-preview-tts (Gemini 2.5)"],
  ["google-tts", "Google TTS (Chirp 3 HD Indian Voices)"],
];

export const GEMINI_VOICES: [string, string][] = [
  ["Aoede", "Aoede (Female)"],
  ["Puck", "Puck (Male)"],
  ["Charon", "Charon (Male)"],
  ["Kore", "Kore (Female)"],
  ["Fenrir", "Fenrir (Male)"],
  ["Zephyr", "Zephyr (Female)"],
  ["Leda", "Leda (Female)"],
  ["Orus", "Orus (Male)"],
  ["Sulafat", "Sulafat (Female)"],
  ["Achird", "Achird (Male)"],
  ["Vindemiatrix", "Vindemiatrix (Female)"],
  ["Rasalgethi", "Rasalgethi (Male)"],
  ["Callirhoe", "Callirhoe (Female)"],
  ["Autonoe", "Autonoe (Female)"],
  ["Enceladus", "Enceladus (Male)"],
  ["Iapetus", "Iapetus (Male)"],
  ["Umbriel", "Umbriel (Male)"],
  ["Algieba", "Algieba (Male)"],
  ["Despina", "Despina (Female)"],
  ["Erinome", "Erinome (Female)"],
  ["Algenib", "Algenib (Male)"],
  ["Laomedeia", "Laomedeia (Female)"],
  ["Achernar", "Achernar (Female)"],
  ["Alnilam", "Alnilam (Male)"],
  ["Schedar", "Schedar (Male)"],
  ["Gacrux", "Gacrux (Female)"],
  ["Pulcherrima", "Pulcherrima (Female)"],
  ["Zubenelgenubi", "Zubenelgenubi (Male)"],
  ["Sadachbia", "Sadachbia (Male)"],
  ["Sadaltager", "Sadaltager (Male)"],
  ["Custom-Male", "Custom Clone Voice (Male)"],
  ["Custom-Female", "Custom Clone Voice (Female)"],
  ["Custom-Key", "Custom Voice Cloning Key"],
];

export const CHIRP_HD_VOICES: [string, string][] = [
  ["hi-IN-Chirp3-HD-Sulafat", "hi-IN-Chirp3-HD-Sulafat (Hindi Female)"],
  ["hi-IN-Chirp3-HD-Achird", "hi-IN-Chirp3-HD-Achird (Hindi Male)"],
  ["hi-IN-Chirp3-HD-Vindemiatrix", "hi-IN-Chirp3-HD-Vindemiatrix (Hindi Female)"],
  ["hi-IN-Chirp3-HD-Rasalgethi", "hi-IN-Chirp3-HD-Rasalgethi (Hindi Male)"],
  ["en-IN-Chirp3-HD-Aoede", "en-IN-Chirp3-HD-Aoede (Indian English Female)"],
  ["en-IN-Chirp3-HD-Zephyr", "en-IN-Chirp3-HD-Zephyr (Indian English Female)"],
  ["en-US-Chirp3-HD-Aoede", "en-US-Chirp3-HD-Aoede (US Female)"],
  ["en-US-Chirp3-HD-Charon", "en-US-Chirp3-HD-Charon (US Male)"],
  ["en-US-Chirp3-HD-Despina", "en-US-Chirp3-HD-Despina (US Female)"],
  ["en-US-Chirp3-HD-Gacrux", "en-US-Chirp3-HD-Gacrux (US Female)"],
  ["en-US-Chirp3-HD-Leda", "en-US-Chirp3-HD-Leda (US Female)"],
  ["en-US-Chirp3-HD-Puck", "en-US-Chirp3-HD-Puck (US Male)"],
  ["Custom-Male", "Custom Clone Voice (Male)"],
  ["Custom-Female", "Custom Clone Voice (Female)"],
];

export function buildSessionInstructions(settings: SessionSettings): string {
  const persona = getPersona(settings.personaId);
  const language = LANGUAGE_MAP[settings.language] || LANGUAGE_OPTIONS.find(([value]) => value === settings.language)?.[1];
  if (!language) throw new Error("Choose one of the supported session languages.");
  if (settings.instructions.length > 1000) throw new Error("Keep custom persona instructions under 1,000 characters.");
  const prompt = settings.instructions.trim() || persona.prompt;
  if (!prompt) return ""; // Leave the backend’s existing instructions intact in custom mode.
  return `${prompt} Speak in ${language}, unless the user requests another language.`;
}

function validatedBackendUrl(backendUrl: string): URL {
  const url = new URL(backendUrl.trim());
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new Error("Enter an HTTP or HTTPS server URL without credentials.");
  }
  if (url.search || url.hash) throw new Error("Use your server’s base URL without query parameters.");
  return url;
}

/** Open the existing backend pages without replacing them or sharing session state. */
export function buildBackendPageUrl(backendUrl: string, page: "original" | "diagnostics"): string {
  const url = validatedBackendUrl(backendUrl);
  url.pathname = `${url.pathname.replace(/\/$/, "")}/${page === "diagnostics" ? "diagnostics" : ""}`;
  return url.href;
}

export function buildConnectUrl(settings: SessionSettings): URL {
  buildSessionInstructions(settings);
  const targetUrl = settings.backendUrl?.trim() || getDefaultBackendUrl();
  const url = validatedBackendUrl(targetUrl);
  url.pathname = `${url.pathname.replace(/\/$/, "")}/connect`;
  if (settings.engine === "live") {
    const effectiveVoice = (settings.voice === "Custom-Key" && settings.customVoiceKey?.trim())
      ? settings.customVoiceKey.trim()
      : settings.voice;
    const params: Record<string, string> = {
      bot_type: "gemini-live",
      model: settings.model,
      voice: effectiveVoice,
      language: settings.language,
      tts: settings.tts ? "true" : "false",
      context_compression: settings.contextCompression ? "true" : "false",
    };
    if (settings.thinking) {
      params.thinking = "true";
      if (settings.thinkingBudget !== undefined && settings.thinkingBudget > 0) {
        params.thinking_budget = String(settings.thinkingBudget);
      }
      if (settings.thinkingLevel) {
        params.thinking_level = settings.thinkingLevel;
      }
    }
    if (settings.customVoiceKey?.trim()) {
      params.custom_voice_key = settings.customVoiceKey.trim();
    }
    url.search = new URLSearchParams(params).toString();
  } else if (settings.engine === "cascade") {
    const effectiveVoice = (settings.voice === "Custom-Key" && settings.customVoiceKey?.trim())
      ? settings.customVoiceKey.trim()
      : settings.voice;
    url.search = new URLSearchParams({
      bot_type: "tts-llm-stt",
      stt_model: settings.sttModel,
      llm_model: settings.llmModel,
      tts_model: settings.ttsModel,
      tts_voice: effectiveVoice,
      stt_language: settings.language,
      tts_pace: String(settings.ttsPace ?? "1.0"),
      skip_stt: settings.skipStt ? "true" : "false",
    }).toString();
  } else throw new Error("Choose Gemini Live or Cascade.");
  return url;
}

export function buildConnectRequest(settings: SessionSettings) {
  const instructions = buildSessionInstructions(settings);
  const body: Record<string, unknown> = {};
  if (instructions) body.system_instruction = instructions;
  if (settings.toolsJson?.trim()) {
    try {
      body.tools = JSON.parse(settings.toolsJson);
    } catch {
      body.tools = settings.toolsJson;
    }
  }
  if (settings.contextCompression) {
    body.context_compression = true;
    if (settings.contextCompressionTokens) {
      body.context_compression_trigger_tokens = settings.contextCompressionTokens;
    }
  }
  if (settings.thinking) {
    body.thinking = true;
    if (settings.thinkingBudget !== undefined && settings.thinkingBudget > 0) {
      body.thinking_budget = settings.thinkingBudget;
    }
    if (settings.thinkingLevel) {
      body.thinking_level = settings.thinkingLevel;
    }
  }
  if (settings.customVoiceKey?.trim()) {
    body.custom_voice_key = settings.customVoiceKey.trim();
  }
  return { url: buildConnectUrl(settings), body };
}

export function validateSocketUrl(value: unknown, backendUrl: string = getDefaultBackendUrl()): string {
  if (typeof value !== "string") throw new Error("The server did not return a ws_url.");
  const socket = new URL(value);
  const targetUrl = backendUrl?.trim() || getDefaultBackendUrl();
  const backend = new URL(targetUrl);
  if (!["ws:", "wss:"].includes(socket.protocol) || socket.username || socket.password) throw new Error("The server returned an invalid WebSocket URL.");
  
  if (typeof window !== "undefined") {
    const isLocalSocket = socket.hostname === "localhost" || socket.hostname === "127.0.0.1";
    const isLocalPage = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    
    // If the server returned 127.0.0.1/localhost (due to internal reverse proxying),
    // but the client is viewing the page through a remote hostname or Cloudtop web proxy,
    // route WebSocket traffic through the active page host (which reverse-proxies /ws).
    if (isLocalSocket && !isLocalPage) {
      socket.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket.host = window.location.host;
    } else if (window.location.protocol === "https:" && socket.protocol === "ws:") {
      socket.protocol = "wss:";
    }
  } else {
    const isLocal = (h: string) => h === "localhost" || h === "127.0.0.1";
    const hostsMatch = socket.host === backend.host || (isLocal(socket.hostname) && isLocal(backend.hostname) && (socket.port === backend.port || (!socket.port && !backend.port)));
    if (!hostsMatch) throw new Error("The WebSocket address must match your configured server host.");
    if (backend.protocol === "https:" && socket.protocol !== "wss:") throw new Error("An HTTPS server must return a secure wss:// address.");
  }
  return socket.href;
}
