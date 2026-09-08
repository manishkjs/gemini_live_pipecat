import { buildConnectRequest, validateSocketUrl, type SessionSettings } from "./voice-session";
import { calculateTurnCost } from "./pricing";

type Phase = "idle" | "connecting" | "listening" | "thinking" | "speaking";

export type MessageMetrics = {
  sttLatency?: number; // In seconds
  llmLatency?: number; // In seconds (TTFB)
  ttsLatency?: number; // In seconds
  interruptedMs?: number;
  turnCostUSD?: number;
  usage?: {
    total_token_count?: number;
    prompt_token_count?: number;
    response_token_count?: number;
    prompt_details?: { text?: number; audio?: number };
    response_details?: { text?: number; audio?: number };
  };
};

export type SessionEvents = {
  onPhase: (phase: Phase) => void;
  onMessage: (role: "user" | "assistant", text: string, append?: boolean, metrics?: MessageMetrics) => void;
  onReplaceMessage?: (role: "user" | "assistant", text: string) => void;
  onPartialUser: (text: string) => void;
  onTrack: (track: MediaStreamTrack | null) => void;
  onLevel: (level: number) => void;
  onLatency: (ms: number) => void;
  onMetricUpdate?: (metricType: string, value: any) => void;
  onError: (text: string) => void;
  onDisconnected: () => void;
};
export type LiveSession = {
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  setMic: (enabled: boolean) => void;
};

/** Connects to this repository's /connect + custom protobuf message contract.
 * Uses public Pipecat transport APIs because this backend does not emit the
 * bot-ready handshake that the higher-level PipecatClient.connect() waits for.
 */
export async function createLiveSession(settings: SessionSettings, events: SessionEvents): Promise<LiveSession> {
  const request = buildConnectRequest(settings);
  const endpoint = request.url;
  if (window.location.protocol === "https:" && endpoint.protocol !== "https:") {
    throw new Error("Use an HTTPS backend for this hosted demo. Run the demo locally to connect to localhost over HTTP.");
  }
  const [{ WebSocketTransport, DailyMediaManager }, { RTVIMessage }] = await Promise.all([
    import("@pipecat-ai/websocket-transport"), import("@pipecat-ai/client-js"),
  ]);
  let stopped = false;
  let initialized = false;
  let levelTimer: ReturnType<typeof setInterval> | null = null;
  let speakingTimer: ReturnType<typeof setTimeout> | null = null;
  let turnStarted = false;
  let lastUserAt: number | null = null;

  // Latency buffers according to canonical protocol invariants
  let pendingSTTLatency: number | null = null;
  let lastTurnSTTLatency: number | null = null;
  let pendingLLMLatency: number | null = null;
  let pendingTTSLatency: number | null = null;
  let lastTurnUsage: any = null;

  const controller = new AbortController();
  const sources = new Set<AudioBufferSourceNode>();
  let context: AudioContext | null = null;
  let destination: MediaStreamAudioDestinationNode | null = null;
  let analyser: AnalyserNode | null = null;
  let nextAudioAt = 0;

  // Pipecat's stock WebSocket player plays directly to the speaker and does not
  // expose a bot MediaStreamTrack. Route its decoded PCM through a destination
  // track so the Voice UI Kit visualizer and the muteable audio element share it.
  class StudioMediaManager extends DailyMediaManager {
    constructor() { super(false, true, undefined, undefined, 512, 16000, 24000); }
    bufferBotAudio(data: ArrayBuffer | Int16Array): Int16Array | undefined {
      if (stopped || !context || !destination || !analyser) return;
      const pcm = data instanceof Int16Array ? data : new Int16Array(data);
      if (!pcm.length) return pcm;
      const buffer = context.createBuffer(1, pcm.length, 24000);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768;
      const source = context.createBufferSource(); source.buffer = buffer;
      source.connect(analyser); sources.add(source);
      source.onended = () => { sources.delete(source); source.disconnect(); };
      nextAudioAt = Math.max(context.currentTime, nextAudioAt);
      source.start(nextAudioAt); nextAudioAt += buffer.duration;
      events.onPhase("speaking");
      if (lastUserAt !== null) { events.onLatency(performance.now() - lastUserAt); lastUserAt = null; }
      if (speakingTimer) clearTimeout(speakingTimer);
      speakingTimer = setTimeout(() => { if (!stopped) { events.onPhase("listening"); events.onLevel(0); } }, Math.max(150, (nextAudioAt - context.currentTime) * 1000 + 100));
      return pcm;
    }
    async userStartedSpeaking() {
      for (const source of sources) { try { source.stop(); } catch { /* Already ended. */ } source.disconnect(); }
      sources.clear(); nextAudioAt = 0;
      if (speakingTimer) clearTimeout(speakingTimer);
      events.onLevel(0);
    }
  }
  const media = new StudioMediaManager();
  const transport = new WebSocketTransport({ mediaManager: media, recorderSampleRate: 16000, playerSampleRate: 24000 });

  const disconnect = async () => {
    if (stopped) return;
    stopped = true; controller.abort();
    if (levelTimer) clearInterval(levelTimer);
    if (speakingTimer) clearTimeout(speakingTimer);
    await media.userStartedSpeaking();
    if (initialized) {
      try { transport.tracks().local?.audio?.stop(); } catch { /* Initialization may be incomplete. */ }
      try { await transport.disconnect(); } catch { /* Release the remaining local media below. */ }
    }
    destination?.stream.getTracks().forEach(track => track.stop());
    if (context && context.state !== "closed") await context.close();
    events.onTrack(null); events.onLevel(0);
  };

  transport.initialize({
    transport, enableMic: true, enableCam: false,
    callbacks: {
      onConnected: () => { if (!stopped) events.onPhase("listening"); },
      onDisconnected: () => { if (!stopped) { void disconnect(); events.onDisconnected(); } },
      onError: () => { if (!stopped) { events.onError("The voice connection closed. Check your backend and try again."); void disconnect(); events.onDisconnected(); } },
    },
  }, message => {
    if (stopped) return;
    const body = message.type === "server-message" ? message.data : message;
    if (!body || typeof body !== "object") return;
    const data = body as {
      type?: string;
      participant?: string;
      text?: string;
      ttft?: number;
      stt_latency?: number;
      payload?: { type?: string; value?: number; elapsed_ms?: number; count?: number; usage?: any; tool?: any };
    };

    if (data.type === "transcription" && typeof data.text === "string" && data.text) {
      if (data.participant?.toLowerCase() === "user") {
        turnStarted = false;
        lastUserAt = performance.now();
        const effStt = data.stt_latency !== undefined ? data.stt_latency : (pendingSTTLatency !== null ? pendingSTTLatency : undefined);
        pendingSTTLatency = null;
        lastTurnSTTLatency = effStt ?? null;
        events.onMessage("user", data.text, false, { sttLatency: effStt });
        events.onPhase("thinking");
      } else {
        const effLlm = data.ttft !== undefined ? data.ttft : (pendingLLMLatency !== null ? pendingLLMLatency : undefined);
        pendingLLMLatency = null;
        const effTts = pendingTTSLatency !== null ? pendingTTSLatency : undefined;
        pendingTTSLatency = null;
        const effStt = settings.engine === "cascade" ? (lastTurnSTTLatency ?? undefined) : undefined;
        lastTurnSTTLatency = null;
        const effUsage = lastTurnUsage ?? undefined;
        const turnCost = (settings.engine === "live" && effUsage) ? calculateTurnCost(settings.model, effUsage) : null;

        events.onMessage("assistant", data.text, turnStarted, {
          llmLatency: effLlm,
          ttsLatency: effTts,
          sttLatency: effStt,
          usage: effUsage,
          turnCostUSD: turnCost?.totalUSD,
        });
        turnStarted = true;
      }
    } else if (data.type === "transcription_replace" && typeof data.text === "string") {
      const role = data.participant?.toLowerCase() === "user" ? "user" : "assistant";
      if (events.onReplaceMessage) {
        events.onReplaceMessage(role, data.text);
      }
    } else if (data.type === "interim_transcription" || data.type === "interim_input_transcription") {
      if (typeof data.text === "string") {
        events.onPartialUser(data.text);
      }
    } else if (data.type === "metrics") {
      const p = data.payload;
      if (!p) return;
      if (p.type === "turn_complete") {
        turnStarted = false;
        events.onMetricUpdate?.("turn_complete", p);
      } else if (p.type === "interruption") {
        turnStarted = false;
        void media.userStartedSpeaking();
        events.onPhase("listening");
        events.onMetricUpdate?.("interruption", p);
      } else if (p.type === "stt_latency") {
        pendingSTTLatency = p.value ?? null;
        lastTurnSTTLatency = p.value ?? null;
        events.onMetricUpdate?.("stt_latency", p.value);
      } else if (p.type === "llm_latency") {
        pendingLLMLatency = p.value ?? null;
        events.onMetricUpdate?.("llm_latency", p.value);
      } else if (p.type === "tts_latency") {
        pendingTTSLatency = p.value ?? null;
        events.onMetricUpdate?.("tts_latency", p.value);
      } else if (p.type === "usage") {
        lastTurnUsage = p.usage ?? null;
        const turnCost = settings.engine === "live" ? calculateTurnCost(settings.model, p.usage) : null;
        events.onMetricUpdate?.("usage", {
          ...p.usage,
          turnCostUSD: turnCost?.totalUSD,
        });
      } else if (p.type === "tool_call") {
        events.onMetricUpdate?.("tool_call", p);
      }
    } else if (data.type === "error" || message.type === "error") {
      events.onError("Your backend reported an error. Check its logs and selected model.");
    }
  });

  return {
    async connect() {
      let response: Response;
      const timeout = setTimeout(() => controller.abort(), 20000);
      try {
        response = await fetch(endpoint, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request.body),
          signal: controller.signal,
        });
      } catch (error) {
        if (stopped) return;
        throw new Error(error instanceof DOMException && error.name === "AbortError"
          ? "The backend took too long to respond. Check the address and try again."
          : "Cannot reach your backend. Check its HTTPS address, CORS settings, and that it is running.");
      } finally { clearTimeout(timeout); }
      if (!response.ok) throw new Error(`Backend returned HTTP ${response.status}. Check that /connect is available.`);
      const result = await response.json() as { ws_url?: unknown };
      const wsUrl = validateSocketUrl(result.ws_url, settings.backendUrl);
      if (stopped) return;
      context = new AudioContext({ sampleRate: 24000 });
      destination = context.createMediaStreamDestination();
      analyser = context.createAnalyser(); analyser.fftSize = 256; analyser.connect(destination);
      await context.resume();
      initialized = true;
      try { await transport.initDevices(); }
      catch { throw new Error("Microphone access failed. Allow microphone access in your browser, then try again."); }
      if (stopped) {
        transport.tracks().local?.audio?.stop();
        await transport.disconnect();
        return;
      }
      events.onTrack(destination.stream.getAudioTracks()[0]);
      const values = new Float32Array(analyser.fftSize);
      levelTimer = setInterval(() => {
        if (!analyser || stopped) return;
        analyser.getFloatTimeDomainData(values);
        const rms = Math.sqrt(values.reduce((sum, value) => sum + value * value, 0) / values.length);
        events.onLevel(Math.min(1, rms * 6));
      }, 100);
      await transport.connect({ wsUrl });
      if (stopped) { await transport.disconnect(); return; }
      transport.sendReadyMessage();
      transport.sendMessage(new RTVIMessage("start_trigger", {}));
    },
    disconnect,
    setMic(enabled) { if (!stopped) transport.enableMic(enabled); },
  };
}
