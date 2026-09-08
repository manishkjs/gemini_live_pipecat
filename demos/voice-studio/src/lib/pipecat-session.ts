import { buildConnectRequest, validateSocketUrl, type SessionSettings } from "./voice-session";

type Phase = "idle" | "connecting" | "listening" | "thinking" | "speaking";
export type SessionEvents = {
  onPhase: (phase: Phase) => void;
  onMessage: (role: "user" | "assistant", text: string, append?: boolean) => void;
  onPartialUser: (text: string) => void;
  onTrack: (track: MediaStreamTrack | null) => void;
  onLevel: (level: number) => void;
  onLatency: (ms: number) => void;
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
    const data = body as { type?: string; participant?: string; text?: string; payload?: { type?: string; value?: number } };
    if (data.type === "transcription" && typeof data.text === "string" && data.text) {
      if (data.participant?.toLowerCase() === "user") {
        turnStarted = false; lastUserAt = performance.now();
        events.onMessage("user", data.text); events.onPhase("thinking");
      } else {
        events.onMessage("assistant", data.text, turnStarted); turnStarted = true;
      }
    } else if (data.type === "metrics") {
      if (data.payload?.type === "turn_complete") turnStarted = false;
      if (data.payload?.type === "interruption") {
        turnStarted = false; void media.userStartedSpeaking(); events.onPhase("listening");
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
