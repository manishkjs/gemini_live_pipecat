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
};

export function getDefaultBackendUrl(): string {
  if (typeof window !== "undefined") {
    if (window.location.port === "5173" || window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
      return `${window.location.protocol}//${window.location.hostname}:7860`;
    }
    return window.location.origin;
  }
  return "http://localhost:7860";
}

export const DEFAULT_SETTINGS: SessionSettings = {
  backendUrl: typeof window !== "undefined" ? getDefaultBackendUrl() : "http://localhost:7860",
  engine: "live", personaId: "debt-collector",
  model: "gemini-live-2.5-flash-native-audio", voice: "Aoede", language: "en-IN", instructions: "",
  sttModel: "gemini-3.5-transcribe-live-aistudio", llmModel: "gemini-3.5-flash-lite", ttsModel: "gemini-3.1-flash-tts-preview",
};
export const LANGUAGE_OPTIONS: [string, string][] = [["en-IN", "English"], ["hi-IN", "Hindi"], ["es-ES", "Spanish"], ["fr-FR", "French"]];

export function buildSessionInstructions(settings: SessionSettings): string {
  const persona = getPersona(settings.personaId);
  const language = LANGUAGE_OPTIONS.find(([value]) => value === settings.language)?.[1];
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
    url.search = new URLSearchParams({ bot_type: "gemini-live", model: settings.model, voice: settings.voice, language: settings.language, tts: "false", context_compression: "false" }).toString();
  } else if (settings.engine === "cascade") {
    url.search = new URLSearchParams({ bot_type: "tts-llm-stt", stt_model: settings.sttModel, llm_model: settings.llmModel, tts_model: settings.ttsModel, tts_voice: settings.voice, stt_language: settings.language, tts_pace: "1.0", skip_stt: "false" }).toString();
  } else throw new Error("Choose Gemini Live or Cascade.");
  return url;
}

export function buildConnectRequest(settings: SessionSettings) {
  const instructions = buildSessionInstructions(settings);
  return { url: buildConnectUrl(settings), body: instructions ? { system_instruction: instructions } : {} };
}

export function validateSocketUrl(value: unknown, backendUrl: string = getDefaultBackendUrl()): string {
  if (typeof value !== "string") throw new Error("The server did not return a ws_url.");
  const socket = new URL(value);
  const targetUrl = backendUrl?.trim() || getDefaultBackendUrl();
  const backend = new URL(targetUrl);
  if (!["ws:", "wss:"].includes(socket.protocol) || socket.username || socket.password) throw new Error("The server returned an invalid WebSocket URL.");
  
  const isLocal = (h: string) => h === "localhost" || h === "127.0.0.1";
  const hostsMatch = socket.host === backend.host || (isLocal(socket.hostname) && isLocal(backend.hostname) && (socket.port === backend.port || (!socket.port && !backend.port)));
  if (!hostsMatch) throw new Error("The WebSocket address must match your configured server host.");
  if (backend.protocol === "https:" && socket.protocol !== "wss:") throw new Error("An HTTPS server must return a secure wss:// address.");
  return socket.href;
}
