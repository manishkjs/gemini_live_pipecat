import { getPersona, getPersonaPrompt, type PersonaId, type PersonaTone } from "./personas.ts";
import { estimateTokens } from "./pricing.ts";

export type Engine = "live" | "cascade";

/**
 * Gemini 3 replaced the numeric `thinking_budget` with discrete `thinking_level`
 * tiers. Sending both in one request is rejected with HTTP 400, so the studio
 * models reasoning as a single choice. "off" means send no thinking config at
 * all and let the model apply its own default.
 * See https://ai.google.dev/gemini-api/docs/thinking
 */
export type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high";

export const THINKING_LEVELS: [ThinkingLevel, string][] = [
  ["off", "Off (model default)"],
  ["minimal", "Minimal (lowest latency)"],
  ["low", "Low (brief reasoning)"],
  ["medium", "Medium (balanced)"],
  ["high", "High (deep reasoning)"],
];

export type VadMode = "both" | "gemini" | "silero";

export const VAD_MODES: [VadMode, string][] = [
  ["both", "Both (Silero VAD + Gemini Internal VAD)"],
  ["gemini", "Gemini Internal VAD Only (Server-Side)"],
  ["silero", "Silero VAD Only (Pipecat Local VAD)"],
];

export type AvatarCharacter = {
  id: string;
  name: string;
  role: string;
  gender: "female" | "male" | "auto" | "custom";
  accentColor: string;
  badge: string;
};

export const AVATAR_CHARACTERS: AvatarCharacter[] = [
  {
    id: "auto",
    name: "Auto-Match Persona",
    role: "Automatically pairs Kira, Vera, Ben, or Leo with the active persona & voice",
    gender: "auto",
    accentColor: "#1a73e8",
    badge: "Recommended",
  },
  {
    id: "Kira",
    name: "Kira",
    role: "Executive Advisor · Warm & Articulate",
    gender: "female",
    accentColor: "#9334e6",
    badge: "Female",
  },
  {
    id: "Ben",
    name: "Ben",
    role: "Concierge Specialist · Friendly & Grounded",
    gender: "male",
    accentColor: "#1a73e8",
    badge: "Male",
  },
  {
    id: "Vera",
    name: "Vera",
    role: "Multilingual Specialist · Expressive & Clear",
    gender: "female",
    accentColor: "#e8710a",
    badge: "Female",
  },
  {
    id: "Leo",
    name: "Leo",
    role: "Technical Architect · Composed & Precise",
    gender: "male",
    accentColor: "#1e8e3e",
    badge: "Male",
  },
  {
    id: "Sam",
    name: "Sam",
    role: "Support Specialist · Approachable & Calm",
    gender: "male",
    accentColor: "#12b5cb",
    badge: "Male",
  },
  {
    id: "Kai",
    name: "Kai",
    role: "Product Guide · Energetic & Modern",
    gender: "male",
    accentColor: "#f29900",
    badge: "Male",
  },
  {
    id: "Jay",
    name: "Jay",
    role: "Wealth Specialist · Confident & Direct",
    gender: "male",
    accentColor: "#3949ab",
    badge: "Male",
  },
  {
    id: "Paul",
    name: "Paul",
    role: "Senior Consultant · Authoritative & Steady",
    gender: "male",
    accentColor: "#5f6368",
    badge: "Male",
  },
  {
    id: "custom",
    name: "Custom Portrait",
    role: "Upload any portrait photo (customized_avatar with automatic prebuilt fallback)",
    gender: "custom",
    accentColor: "#d93025",
    badge: "Upload Photo",
  },
];

export type SessionSettings = {
  backendUrl: string;
  engine: Engine;
  personaId: PersonaId;
  /** Which register of the selected persona to run. Defaults to professional. */
  tone: PersonaTone;
  model: string;
  voice: string;
  language: string;
  instructions: string;
  sttModel: string;
  llmModel: string;
  ttsModel: string;
  ttsPace?: number;
  ttsStyle?: string;
  ttsAccent?: string;
  ttsPitch?: string;
  ttsPaceLabel?: string;
  ttsVoicePrompt?: string;
  tts?: boolean;
  skipStt?: boolean;
  vad?: boolean;
  vadMode?: VadMode;
  contextCompression?: boolean;
  contextCompressionTokens?: number;
  toolsJson?: string;
  thinkingLevel?: ThinkingLevel;
  customVoiceKey?: string;
  /** Whether Gemini 3.8 Live Avatar (lip-synced H.264/AAC MP4 stream) is active. Defaults to false. */
  avatarEnabled?: boolean;
  /** Selected prebuilt avatar ('auto', 'Ben', 'Kira', 'Leo', 'Vera', 'Sam', 'Kai', 'Jay', 'Paul', or 'custom'). */
  avatarName?: string;
  /** Optional base64 data URI for Custom Portrait upload (`customized_avatar`). */
  avatarCustomImage?: string;
  /**
   * Identifies this browser's session to the backend diagnostics buffer.
   *
   * The buffer is process-global, so without a session id the Observability
   * drawer shows every concurrent demoer's logs and blends their latency
   * percentiles together.
   */
  sessionId?: string;
};

/** A short, non-secret id used only to partition diagnostics by demoer. */
export function newSessionId(): string {
  const random = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2, 10);
  return `s_${random}`;
}

/** Resolve the reasoning tier to send, or null when the model default should stand. */
export function resolveThinkingLevel(settings: SessionSettings): ThinkingLevel | null {
  const level = settings.thinkingLevel;
  if (!level || level === "off") return null;
  return level;
}

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
  tone: "professional",
  model: "gemini-3.8-live",
  voice: "Gacrux",
  language: "hi-IN",
  instructions: "",
  sttModel: "gemini-3.5-transcribe-live-aistudio",
  llmModel: "gemini-3.5-flash-lite",
  ttsModel: "gemini-3.8-flash-lite-tts",
  ttsPace: 1.0,
  ttsStyle: "Empathetic",
  ttsAccent: "Indian",
  ttsPitch: "Default",
  ttsPaceLabel: "Natural",
  ttsVoicePrompt: "Empathetic yet firm collections specialist. Calm, reassuring Indian English cadence.",
  tts: false,
  skipStt: false,
  vad: true,
  vadMode: "both",
  contextCompression: false,
  contextCompressionTokens: 5000,
  toolsJson: "",
  thinkingLevel: "off",
  customVoiceKey: "",
  avatarEnabled: false,
  avatarName: "auto",
  avatarCustomImage: "",
  sessionId: "",
};

/**
 * The Live Avatar is a Gemini 3.8 Live feature. Cascade has no video path, so a
 * stored `avatarEnabled` flag is inert there: every UI surface, request
 * builder and event handler asks this one predicate instead of the raw flag.
 */
export function isAvatarActive(settings: Pick<SessionSettings, "engine" | "avatarEnabled">): boolean {
  return Boolean(settings.avatarEnabled) && settings.engine === "live";
}

export type PersonaVoiceDesign = {
  ttsStyle: string;
  ttsPaceLabel: string;
  ttsAccent: string;
  ttsPitch: string;
  ttsVoicePrompt: string;
};

export const PERSONA_VOICE_DESIGN_MAP: Record<string, PersonaVoiceDesign> = {
  pragya: {
    ttsStyle: "Warm & Friendly",
    ttsPaceLabel: "Natural",
    ttsAccent: "Indian",
    ttsPitch: "Default",
    ttsVoicePrompt: "Warm, confident luxury automotive concierge from Mumbai. Speak with a welcoming smile.",
  },
  "debt-collector": {
    ttsStyle: "Empathetic",
    ttsPaceLabel: "Natural",
    ttsAccent: "Indian",
    ttsPitch: "Default",
    ttsVoicePrompt: "Empathetic yet firm collections specialist. Calm, reassuring Indian English cadence.",
  },
  storyteller: {
    ttsStyle: "Expressive / Dramatic",
    ttsPaceLabel: "Conversational",
    ttsAccent: "Indian",
    ttsPitch: "Default",
    ttsVoicePrompt: "Expressive Indian storyteller. Rich theatrical modulation and warm emotional pacing.",
  },
  "mf-advisor": {
    ttsStyle: "Professional",
    ttsPaceLabel: "Natural",
    ttsAccent: "Indian",
    ttsPitch: "Default",
    ttsVoicePrompt: "Trusted wealth & mutual fund advisor. Articulate, reassuring, and clear with financial numbers.",
  },
  "glass-buddy": {
    ttsStyle: "Conversational",
    ttsPaceLabel: "Brisk",
    ttsAccent: "Indian",
    ttsPitch: "Default",
    ttsVoicePrompt: "Friendly smart-glasses AI companion. Crisp, upbeat, and helpful.",
  },
};

export function getPersonaVoiceDesign(personaId: string): PersonaVoiceDesign {
  return (
    PERSONA_VOICE_DESIGN_MAP[personaId] ?? {
      ttsStyle: "Empathetic",
      ttsPaceLabel: "Natural",
      ttsAccent: "Indian",
      ttsPitch: "Default",
      ttsVoicePrompt: "Warm, natural conversational tone.",
    }
  );
}

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

export const LIVE_MODEL_GROUPS: { label: string; options: [string, string][] }[] = [
  {
    label: "Vertex AI (Gemini Live)",
    options: [
      ["gemini-3.8-live", "gemini-3.8-live (Vertex AI Live - Default)"],
      ["gemini-3.8-live-extended-thinking-preview", "gemini-3.8-live-extended-thinking-preview (Vertex AI Thinking)"],
      ["gemini-live-2.5-flash-native-audio", "gemini-live-2.5-flash-native-audio (Vertex AI)"],
      ["gemini-live-2.5-flash", "gemini-live-2.5-flash (Vertex AI Cascaded)"],
    ],
  },
  {
    label: "AI Studio (Gemini Live)",
    options: [
      ["gemini-3.8-live-aistudio", "gemini-3.8-live (AI Studio)"],
      ["gemini-3.8-live-extended-thinking", "gemini-3.8-live-extended-thinking (AI Studio Thinking)"],
      ["gemini-3.1-flash-live-preview", "gemini-3.1-flash-live-preview (AI Studio)"],
      ["gemini-2.5-flash-native-audio-latest", "gemini-2.5-flash-native-audio-latest (AI Studio)"],
    ],
  },
];

export const LIVE_MODELS: [string, string][] = LIVE_MODEL_GROUPS.flatMap((group) => group.options);

export const CASCADE_STT_MODEL_GROUPS: { label: string; options: [string, string][] }[] = [
  {
    label: "Vertex AI & Google Cloud (STT)",
    options: [
      ["gemini-3.5-transcribe-live-preview", "gemini-3.5-transcribe-live-preview (Vertex AI Global)"],
      ["chirp_3", "chirp_3 (Vertex / Cloud Speech v2 Multilingual)"],
      ["chirp_2", "chirp_2 (Vertex / Cloud Speech v2 - us-central1)"],
      ["latest_long", "latest_long (Cloud Speech v2 Long)"],
      ["telephony", "telephony (Cloud Speech v2 Telephony)"],
    ],
  },
  {
    label: "AI Studio (Gemini Live STT)",
    options: [
      ["gemini-3.5-transcribe-live-aistudio", "gemini-3.5-transcribe-live (AI Studio - Default)"],
    ],
  },
];

export const CASCADE_STT_MODELS: [string, string][] = CASCADE_STT_MODEL_GROUPS.flatMap((group) => group.options);

export const CASCADE_LLM_MODEL_GROUPS: { label: string; options: [string, string][] }[] = [
  {
    label: "Vertex AI (Enterprise LLM)",
    options: [
      ["gemini-3.5-flash-lite", "gemini-3.5-flash-lite (Vertex AI - Default)"],
      ["gemini-3.8-flash", "gemini-3.8-flash (Vertex AI)"],
      ["gemini-3.7-flash", "gemini-3.7-flash (Vertex AI)"],
      ["gemini-2.5-flash", "gemini-2.5-flash (Vertex AI)"],
      ["gemini-2.5-flash-lite", "gemini-2.5-flash-lite (Vertex AI)"],
    ],
  },
  {
    label: "AI Studio (Gemini LLM)",
    options: [
      ["gemini-3.5-flash-lite-aistudio", "gemini-3.5-flash-lite (AI Studio)"],
      ["gemini-3.8-flash-aistudio", "gemini-3.8-flash (AI Studio)"],
    ],
  },
];

export const CASCADE_LLM_MODELS: [string, string][] = CASCADE_LLM_MODEL_GROUPS.flatMap((group) => group.options);

export const CASCADE_TTS_MODEL_GROUPS: { label: string; options: [string, string][] }[] = [
  {
    label: "AI Studio (Gemini 3.8 TTS)",
    options: [
      ["gemini-3.8-flash-lite-tts", "gemini-3.8-flash-lite-tts (AI Studio - $0.50/$6.00 - Default)"],
      ["gemini-3.8-flash-tts", "gemini-3.8-flash-tts (AI Studio Voice Design - $0.50/$9.00)"],
    ],
  },
  {
    label: "Vertex AI (Gemini TTS & Cloud TTS)",
    options: [
      ["gemini-3.1-flash-tts-preview", "gemini-3.1-flash-tts-preview (Vertex AI)"],
      ["gemini-2.5-flash-lite-preview-tts", "gemini-2.5-flash-lite-preview-tts (Vertex AI)"],
      ["gemini-2.5-flash-preview-tts", "gemini-2.5-flash-preview-tts (Vertex AI)"],
      ["gemini-2.5-pro-preview-tts", "gemini-2.5-pro-preview-tts (Vertex AI)"],
      ["google-tts", "Google Cloud TTS (Chirp 3 HD Indian Voices)"],
    ],
  },
];

export const CASCADE_TTS_MODELS: [string, string][] = CASCADE_TTS_MODEL_GROUPS.flatMap((group) => group.options);

export const TTS_STYLE_OPTIONS: [string, string][] = [
  ["Empathetic", "Empathetic (Warm & understanding)"],
  ["Conversational", "Conversational (Natural everyday tone)"],
  ["Warm & Friendly", "Warm & Friendly (Approachable & kind)"],
  ["Professional", "Professional (Crisp & authoritative)"],
  ["Cheerful", "Cheerful (Upbeat & enthusiastic)"],
  ["Calm & Soothing", "Calm & Soothing (Gentle & reassuring)"],
  ["Expressive / Dramatic", "Expressive / Dramatic (Storytelling & theatrical)"],
];

export const TTS_ACCENT_OPTIONS: [string, string][] = [
  ["Indian", "Indian"],
  ["American (Gen)", "American (Gen)"],
  ["British", "British"],
  ["Australian", "Australian"],
  ["Auto", "Auto (from language)"],
];

export const TTS_PITCH_OPTIONS: [string, string][] = [
  ["Default", "Default"],
  ["Low", "Low"],
  ["Medium", "Medium"],
  ["High", "High"],
];

export const TTS_PACE_OPTIONS: [string, string][] = [
  ["Natural", "Natural"],
  ["Conversational", "Conversational"],
  ["Brisk", "Brisk / Energetic"],
  ["Slow", "Slow / Calm"],
];

export const GEMINI_VOICES: [string, string][] = [
  ["Gacrux", "Gacrux (Female - Gemini 3.8 Default)"],
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
  ["Pulcherrima", "Pulcherrima (Female)"],
  ["Zubenelgenubi", "Zubenelgenubi (Male)"],
  ["Sadachbia", "Sadachbia (Male)"],
  ["Sadaltager", "Sadaltager (Male)"],
  ["Custom-Male", "Chirp 3 HD Voice Clone (Male)"],
  ["Custom-Female", "Chirp 3 HD Voice Clone (Female)"],
  ["Custom-Key", "Custom Voice Cloning Key"],
];

export const CHIRP_HD_VOICES: [string, string][] = [
  ["Custom-Male", "Chirp 3 HD Voice Clone (Male)"],
  ["Custom-Female", "Chirp 3 HD Voice Clone (Female)"],
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
];

/** Cloned-voice selections are backed by a voice cloning key rather than a named Gemini voice. */
export function isClonedVoice(voice: string): boolean {
  return voice === "Custom-Male" || voice === "Custom-Female" || voice === "Custom-Key";
}

/**
 * True when a separate TTS service renders the audio, rather than the model
 * emitting native audio itself.
 *
 * This mirrors `use_external_tts = tts or is_custom_voice` in
 * `server/agent_live.py`. It matters because speaking rate is a property of the
 * TTS request: native-audio Live has no pace parameter, so a pace control is
 * only honest when this returns true.
 */
export function usesExternalTts(settings: SessionSettings): boolean {
  if (settings.engine === "cascade") return true;
  return Boolean(settings.tts) || isClonedVoice(settings.voice);
}

export function buildSessionInstructions(settings: SessionSettings): string {
  const persona = getPersona(settings.personaId);
  const language = LANGUAGE_MAP[settings.language] || LANGUAGE_OPTIONS.find(([value]) => value === settings.language)?.[1];
  if (!language) throw new Error("Choose one of the supported session languages.");
  if (estimateTokens(settings.instructions) > 4000) throw new Error("Keep custom persona instructions under 4,000 tokens.");
  const prompt = settings.instructions.trim() || getPersonaPrompt(persona, settings.tone);
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

/**
 * Where to read the prompt the backend will actually run for a persona.
 *
 * Architecture-managed personas have their prompt composed server-side, so the
 * studio has to ask for it rather than display its own local copy.
 */
export function buildPersonaPromptUrl(settings: SessionSettings, phase?: string): string {
  const targetUrl = settings.backendUrl?.trim() || getDefaultBackendUrl();
  const url = validatedBackendUrl(targetUrl);
  const base = url.pathname.replace(/\/$/, "");
  url.pathname = `${base}/persona-prompt/${encodeURIComponent(settings.personaId)}`;
  const searchParams = new URLSearchParams();
  if (settings.engine) {
    searchParams.set("engine", settings.engine);
  }
  if (phase && settings.engine !== "cascade") {
    searchParams.set("phase", phase);
  }
  searchParams.set("tone", settings.tone);
  searchParams.set("language", settings.language);
  url.search = searchParams.toString();
  return url.href;
}



export function buildConnectUrl(settings: SessionSettings): URL {
  buildSessionInstructions(settings);
  const targetUrl = settings.backendUrl?.trim() || getDefaultBackendUrl();
  const url = validatedBackendUrl(targetUrl);
  url.pathname = `${url.pathname.replace(/\/$/, "")}/connect`;
  const effectiveVadMode: VadMode =
    settings.vad === false && (!settings.vadMode || settings.vadMode === "both")
      ? "gemini"
      : (settings.vadMode ?? "both");
  const effectiveVadStr = effectiveVadMode === "gemini" ? "false" : "true";
  if (settings.engine === "live") {
    const params: Record<string, string> = {
      bot_type: "gemini-live",
      model: settings.model,
      voice: settings.voice,
      language: settings.language,
      tts: settings.tts ? "true" : "false",
      vad: effectiveVadStr,
      vad_mode: effectiveVadMode,
      context_compression: settings.contextCompression ? "true" : "false",
      // Selects the persona's execution architecture server-side. The backend
      // routes on this id alone and never inspects prompt text, so editing a
      // prompt can no longer silently disable a persona's engine.
      persona_id: settings.personaId,
    };
    if (settings.sessionId) params.session_id = settings.sessionId;
    if (isAvatarActive(settings)) {
      params.avatar_enabled = "true";
      params.avatar_name = settings.avatarName || "auto";
    }
    // Native audio has no pace parameter, so only send one when a TTS service
    // is actually rendering the audio and can apply it.
    if (usesExternalTts(settings) && !isAvatarActive(settings)) {
      params.tts_pace = String(settings.ttsPace ?? 1.0);
    }
    const thinkingLevel = resolveThinkingLevel(settings);
    if (thinkingLevel) {
      params.thinking = "true";
      params.thinking_level = thinkingLevel;
    }
    url.search = new URLSearchParams(params).toString();
  } else if (settings.engine === "cascade") {
    const cascadeParams: Record<string, string> = {
      bot_type: "tts-llm-stt",
      stt_model: settings.sttModel,
      llm_model: settings.llmModel,
      tts_model: settings.ttsModel,
      tts_voice: settings.voice,
      stt_language: settings.language,
      tts_pace: String(settings.ttsPace ?? 1.0),
      vad: effectiveVadStr,
      vad_mode: effectiveVadMode,
      skip_stt: settings.skipStt ? "true" : "false",
      persona_id: settings.personaId,
    };
    if (settings.sessionId) cascadeParams.session_id = settings.sessionId;
    if (settings.ttsStyle) cascadeParams.tts_style = settings.ttsStyle;
    if (settings.ttsAccent) cascadeParams.tts_accent = settings.ttsAccent;
    if (settings.ttsPitch) cascadeParams.tts_pitch = settings.ttsPitch;
    if (settings.ttsPaceLabel) cascadeParams.tts_pace_label = settings.ttsPaceLabel;
    if (settings.ttsVoicePrompt?.trim()) cascadeParams.tts_voice_prompt = settings.ttsVoicePrompt.trim();
    url.search = new URLSearchParams(cascadeParams).toString();
  } else throw new Error("Choose Gemini Live or Cascade.");
  return url;
}

export function buildConnectRequest(settings: SessionSettings) {
  const instructions = buildSessionInstructions(settings);
  const body: Record<string, unknown> = {};
  if (instructions) body.system_instruction = instructions;
  if (!settings.instructions.trim() && settings.personaId !== "custom") {
    body.prompt_source = "preset";
    body.persona_tone = settings.tone;
  }
  if (settings.toolsJson?.trim()) {
    try {
      body.tools = JSON.parse(settings.toolsJson);
    } catch {
      body.tools = settings.toolsJson;
    }
  }
  if (settings.contextCompression) {
    const rawTokens = settings.contextCompressionTokens ?? 5000;
    body.context_compression_trigger_tokens = Math.max(5000, isNaN(rawTokens) ? 5000 : rawTokens);
  }
  if (isAvatarActive(settings) && settings.avatarName === "custom" && settings.avatarCustomImage?.trim()) {
    body.avatar_custom_image = settings.avatarCustomImage.trim();
  }
  // A voice cloning key is a credential. It travels in the POST body only, and
  // the server exchanges it for an opaque, short-lived voice_profile_id before
  // any WebSocket URL is minted — so it never reaches browser history, access
  // logs, or the in-app diagnostics buffer.
  if (isClonedVoice(settings.voice) && settings.engine === "cascade" && settings.ttsModel !== "google-tts") {
    throw new Error("Select Chirp 3 HD to use a cloned voice in Cascade.");
  }
  if (settings.voice === "Custom-Key" && !settings.customVoiceKey?.trim()) {
    throw new Error("Enter your voice cloning key or select another voice.");
  }
  if (settings.voice === "Custom-Key" && settings.customVoiceKey?.trim()) {
    body.custom_voice_key = settings.customVoiceKey.trim();
  }
  // NOTE: thinking_level intentionally travels only in the query string (see
  // buildConnectUrl). The backend appends body fields onto that same query, so
  // repeating it here would duplicate the parameter.
  return { url: buildConnectUrl(settings), body };
}

export function validateSocketUrl(value: unknown, backendUrl: string = getDefaultBackendUrl()): string {
  if (typeof value !== "string") throw new Error("The server did not return a ws_url.");
  const socket = new URL(value);
  const targetUrl = backendUrl?.trim() || getDefaultBackendUrl();
  const backend = new URL(targetUrl);
  if (!["ws:", "wss:"].includes(socket.protocol) || socket.username || socket.password) throw new Error("The server returned an invalid WebSocket URL.");
  
  if (typeof window !== "undefined") {
    const isLoopback = (host: string) => host === "localhost" || host === "127.0.0.1";
    const isLocalSocket = isLoopback(socket.hostname);
    const isLocalPage = isLoopback(window.location.hostname);

    // If the server returned 127.0.0.1/localhost (due to internal reverse proxying),
    // but the client is viewing the page through a remote hostname or Cloudtop web proxy,
    // route WebSocket traffic through the active page host (which reverse-proxies /ws).
    if (isLocalSocket && !isLocalPage) {
      socket.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      // Assign hostname and port separately: setting `host` to a portless value
      // leaves any existing port in place, which would carry the backend's
      // :7860 onto the proxy host and break the upgrade.
      socket.hostname = window.location.hostname;
      socket.port = window.location.port;
    } else {
      // Any other destination must live on the configured backend or the page
      // currently being viewed. Without this, a spoofed /connect response could
      // redirect the microphone stream to an attacker-controlled host.
      //
      // Compare hostnames, not host:port: the page and the WebSocket routinely
      // sit on different ports of the same machine (Vite on :5173 proxying to
      // the backend on :7860), and loopback is spelled both "localhost" and
      // "127.0.0.1" interchangeably.
      const sameAsPage = socket.hostname === window.location.hostname;
      const sameAsBackend = socket.hostname === backend.hostname;
      const bothLoopback = isLocalSocket && isLocalPage;
      if (!sameAsPage && !sameAsBackend && !bothLoopback) {
        throw new Error("The WebSocket address must match your configured server host.");
      }
      if (window.location.protocol === "https:" && socket.protocol === "ws:") {
        socket.protocol = "wss:";
      }
    }
  } else {
    const isLocal = (h: string) => h === "localhost" || h === "127.0.0.1";
    const hostsMatch = socket.host === backend.host || (isLocal(socket.hostname) && isLocal(backend.hostname) && (socket.port === backend.port || (!socket.port && !backend.port)));
    if (!hostsMatch) throw new Error("The WebSocket address must match your configured server host.");
    if (backend.protocol === "https:" && socket.protocol !== "wss:") throw new Error("An HTTPS server must return a secure wss:// address.");
  }
  return socket.href;
}
