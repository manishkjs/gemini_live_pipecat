import { createDiagnosticAccess, diagnosticHeaders } from "./session-diagnostics";
import { buildConnectRequest, isAvatarActive, validateSocketUrl, type SessionSettings } from "./voice-session";
import { calculateTurnCost, type UsageTokenData } from "./pricing";
import type { PipecatClientOptions, RTVIEventCallbacks, Tracks } from "@pipecat-ai/client-js";

type Phase = "idle" | "connecting" | "listening" | "thinking" | "speaking";

export type MessageMetrics = {
  responseId?: string;
  costEstimated?: boolean;
  costIncomplete?: boolean;
  costMinUSD?: number | null;
  costMaxUSD?: number | null;
  sttLatency?: number; // In seconds
  llmLatency?: number; // In seconds (TTFB)
  ttsLatency?: number; // In seconds
  interruptedMs?: number;
  turnCostUSD?: number;
  usage?: UsageTokenData;
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
  onAvatarVideo?: (chunkB64: string, isInit: boolean, seq: number, hasAudio?: boolean, tfdt?: number) => void;
  onAvatarInterrupted?: () => void;
  onAvatarFallback?: (fallbackAvatar: string, reason: string, code: string) => void;
  onVoiceFallback?: (fallbackVoice: string, reason: string, code: string) => void;
  onError: (text: string) => void;
  onDisconnected: () => void;
};

export type LiveSession = {
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  setMic: (enabled: boolean) => void;
  setSound: (enabled: boolean) => void;
};

/**
 * Clean, zero-bleed, zero-leak AudioWorklet processor for 16 kHz mono Int16 PCM capture.
 *
 * Replaces Pipecat's DailyMediaManager + MediaStreamRecorder, which:
 *   1. Spun up a Daily.co WebRTC call object even on plain WebSocket sessions,
 *      forcing macOS/Chrome into WebRTC VoiceProcessingIO communication ducking on Turn 2;
 *   2. Copied mic input to output inside AudioWorkletProcessor (causing Mac audio chop/bleed);
 *   3. Accumulated every mic chunk in `this.chunks` indefinitely (unbounded RAM leak).
 */
const STUDIO_MIC_WORKLET_CODE = `
class StudioMicPcm16Processor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this.targetRate = opts.targetSampleRate || 16000;
    this.chunkSamples = opts.chunkSamples || 512;
    this.buffer = new Int16Array(this.chunkSamples);
    this.writeIndex = 0;
    this.resamplePos = 0;
    this.sumAcc = 0;
    this.sumCount = 0;
  }

  pushSample(sample) {
    const s = Math.max(-1, Math.min(1, sample));
    this.buffer[this.writeIndex++] = s < 0 ? Math.round(s * 32768) : Math.round(s * 32767);
    if (this.writeIndex >= this.chunkSamples) {
      const out = this.buffer;
      this.buffer = new Int16Array(this.chunkSamples);
      this.writeIndex = 0;
      this.port.postMessage(out.buffer, [out.buffer]);
    }
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) {
      return true;
    }
    const ch = input[0];
    const inRate = sampleRate || this.targetRate;
    if (inRate === this.targetRate) {
      for (let i = 0; i < ch.length; i++) {
        this.pushSample(ch[i]);
      }
    } else if (inRate > this.targetRate) {
      // Anti-aliased boxcar downsampling when hardware AudioContext runs > 16 kHz (e.g. 48 kHz)
      const ratio = inRate / this.targetRate;
      for (let i = 0; i < ch.length; i++) {
        this.sumAcc += ch[i];
        this.sumCount += 1;
        this.resamplePos += 1;
        if (this.resamplePos >= ratio) {
          this.pushSample(this.sumAcc / this.sumCount);
          this.sumAcc = 0;
          this.sumCount = 0;
          this.resamplePos -= ratio;
        }
      }
    } else {
      const ratio = inRate / this.targetRate;
      for (let i = 0; i < ch.length; i++) {
        while (this.resamplePos < 1) {
          this.pushSample(ch[i]);
          this.resamplePos += ratio;
        }
        this.resamplePos -= 1;
      }
    }
    return true;
  }
}
registerProcessor("studio-mic-pcm16-processor", StudioMicPcm16Processor);
`;

/** Connects to this repository's /connect + custom protobuf message contract.
 * Uses public Pipecat transport APIs because this backend does not emit the
 * bot-ready handshake that the higher-level PipecatClient.connect() waits for.
 */
export async function createLiveSession(settings: SessionSettings, events: SessionEvents): Promise<LiveSession> {
  const request = buildConnectRequest(settings);
  if (settings.sessionId) createDiagnosticAccess(settings.sessionId);
  const endpoint = request.url;
  if (window.location.protocol === "https:" && endpoint.protocol !== "https:") {
    throw new Error("Use an HTTPS backend for this hosted demo. Run the demo locally to connect to localhost over HTTP.");
  }
  const [{ WebSocketTransport }, { RTVIMessage }] = await Promise.all([
    import("@pipecat-ai/websocket-transport"), import("@pipecat-ai/client-js"),
  ]);
  let stopped = false;
  let initialized = false;
  let soundEnabled = true;
  let levelTimer: ReturnType<typeof setInterval> | null = null;
  let speakingTimer: ReturnType<typeof setTimeout> | null = null;
  let turnStarted = false;
  let avatarSpeechInTurn = false;
  let lastUserAt: number | null = null;

  // Latency buffers according to canonical protocol invariants
  let pendingSTTLatency: number | null = null;
  let lastTurnSTTLatency: number | null = null;
  let pendingLLMLatency: number | null = null;
  let pendingTTSLatency: number | null = null;

  const controller = new AbortController();
  const sources = new Set<AudioBufferSourceNode>();
  let context: AudioContext | null = null;
  let speakerGain: GainNode | null = null;
  let destination: MediaStreamAudioDestinationNode | null = null;
  let analyser: AnalyserNode | null = null;
  let nextAudioAt = 0;

  /**
   * Direct WebAudio MediaManager without Daily.co WebRTC or `<audio srcObject>`.
   *
   * - Bot 24 kHz PCM plays directly to `context.destination` via `speakerGain`
   *   (the exact same direct hardware WebAudio path as Vertex / AI Studio Console),
   *   preventing Chrome/macOS from routing Turn 2+ playback through WebRTC
   *   VoiceProcessingIO communication ducking & EQ filters.
   * - A side-chain `AnalyserNode -> MediaStreamAudioDestinationNode` feeds
   *   `CircularWaveform` visualization only (never attached to an `<audio>` tag).
   * - User mic is captured via plain `getUserMedia` + `StudioMicPcm16Processor`
   *   at 16 kHz mono Int16 PCM with zero speaker bleed and zero buffer retention.
   */
  class StudioWebAudioMediaManager {
    private userAudioCb: ((data: ArrayBuffer) => void) | null = null;
    private clientOptions: PipecatClientOptions | null = null;
    private callbacks: RTVIEventCallbacks = {};
    private micEnabled = true;
    private streamingActive = false;
    private micStream: MediaStream | null = null;
    private micContext: AudioContext | null = null;
    private micSource: MediaStreamAudioSourceNode | null = null;
    private micWorklet: AudioWorkletNode | null = null;
    private micSilentGain: GainNode | null = null;
    private selectedMicDeviceId: string | undefined = undefined;

    setUserAudioCallback(cb: (data: ArrayBuffer) => void): void {
      this.userAudioCb = cb;
    }

    setClientOptions(options: PipecatClientOptions): void {
      this.clientOptions = options;
      this.callbacks = options.callbacks ?? {};
      this.micEnabled = options.enableMic ?? true;
    }

    async initialize(): Promise<void> {
      await this.acquireMic(this.selectedMicDeviceId);
    }

    private async acquireMic(deviceId?: string): Promise<void> {
      await this.releaseMic();
      const AudioCtx =
        window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const audioConstraints: MediaTrackConstraints = {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
        sampleRate: 16000,
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      };
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: audioConstraints,
        video: false,
      });
      this.micStream = stream;
      const track = stream.getAudioTracks()[0];
      if (track) {
        track.enabled = this.micEnabled;
        this.callbacks.onTrackStarted?.(track, { id: "local", name: "local", local: true });
      }

      const micCtx = new AudioCtx({ sampleRate: 16000, latencyHint: "interactive" });
      this.micContext = micCtx;
      const blob = new Blob([STUDIO_MIC_WORKLET_CODE], { type: "application/javascript" });
      const workletUrl = URL.createObjectURL(blob);
      try {
        await micCtx.audioWorklet.addModule(workletUrl);
      } finally {
        URL.revokeObjectURL(workletUrl);
      }
      if (micCtx.state === "suspended") {
        await micCtx.resume();
      }

      const sourceNode = micCtx.createMediaStreamSource(stream);
      const workletNode = new AudioWorkletNode(micCtx, "studio-mic-pcm16-processor", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: { targetSampleRate: 16000, chunkSamples: 512 },
      });
      const silentGain = micCtx.createGain();
      silentGain.gain.value = 0;

      workletNode.port.onmessage = (ev: MessageEvent<ArrayBuffer>) => {
        if (!this.streamingActive || !this.micEnabled || stopped) return;
        if (ev.data && ev.data.byteLength > 0) {
          this.userAudioCb?.(ev.data);
        }
      };

      sourceNode.connect(workletNode);
      workletNode.connect(silentGain);
      silentGain.connect(micCtx.destination);

      this.micSource = sourceNode;
      this.micWorklet = workletNode;
      this.micSilentGain = silentGain;
    }

    private async releaseMic(): Promise<void> {
      if (this.micWorklet) {
        this.micWorklet.port.onmessage = null;
        try { this.micWorklet.disconnect(); } catch { /* ignore */ }
        this.micWorklet = null;
      }
      if (this.micSource) {
        try { this.micSource.disconnect(); } catch { /* ignore */ }
        this.micSource = null;
      }
      if (this.micSilentGain) {
        try { this.micSilentGain.disconnect(); } catch { /* ignore */ }
        this.micSilentGain = null;
      }
      if (this.micStream) {
        for (const t of this.micStream.getTracks()) {
          try { t.stop(); } catch { /* ignore */ }
        }
        this.micStream = null;
      }
      if (this.micContext && this.micContext.state !== "closed") {
        try { await this.micContext.close(); } catch { /* ignore */ }
      }
      this.micContext = null;
    }

    async connect(): Promise<void> {
      this.streamingActive = true;
      if (this.micContext && this.micContext.state === "suspended") {
        await this.micContext.resume();
      }
    }

    async disconnect(): Promise<void> {
      this.streamingActive = false;
      await this.userStartedSpeaking();
      await this.releaseMic();
    }

    bufferBotAudio(data: ArrayBuffer | Int16Array): Int16Array | undefined {
      if (stopped || !context || !speakerGain || !analyser) return;
      const pcm =
        data instanceof Int16Array
          ? data
          : new Int16Array(data, 0, data.byteLength >> 1);
      if (!pcm.length) return pcm;
      if (context.state === "suspended") {
        void context.resume().catch(() => {});
      }
      const buffer = context.createBuffer(1, pcm.length, 24000);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < pcm.length; i++) {
        channel[i] = pcm[i] / 32768;
      }
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(speakerGain);
      source.connect(analyser);
      sources.add(source);
      source.onended = () => {
        sources.delete(source);
        source.disconnect();
      };
      const minStart = context.currentTime + (sources.size === 1 && nextAudioAt <= context.currentTime ? 0.015 : 0);
      nextAudioAt = Math.max(minStart, nextAudioAt);
      source.start(nextAudioAt);
      nextAudioAt += buffer.duration;
      events.onPhase("speaking");
      if (lastUserAt !== null) {
        events.onLatency(performance.now() - lastUserAt);
        lastUserAt = null;
      }
      if (speakingTimer) clearTimeout(speakingTimer);
      speakingTimer = setTimeout(() => {
        if (!stopped) {
          events.onPhase("listening");
          events.onLevel(0);
        }
      }, Math.max(150, (nextAudioAt - context.currentTime) * 1000 + 100));
      return pcm;
    }

    async userStartedSpeaking(): Promise<void> {
      for (const source of sources) {
        try { source.stop(); } catch { /* Already ended. */ }
        source.disconnect();
      }
      sources.clear();
      nextAudioAt = 0;
      if (speakingTimer) clearTimeout(speakingTimer);
      events.onLevel(0);
    }

    async getAllMics(): Promise<MediaDeviceInfo[]> {
      if (!navigator.mediaDevices?.enumerateDevices) return [];
      const devices = await navigator.mediaDevices.enumerateDevices();
      return devices.filter((d) => d.kind === "audioinput");
    }

    async getAllCams(): Promise<MediaDeviceInfo[]> {
      return [];
    }

    async getAllSpeakers(): Promise<MediaDeviceInfo[]> {
      if (!navigator.mediaDevices?.enumerateDevices) return [];
      const devices = await navigator.mediaDevices.enumerateDevices();
      return devices.filter((d) => d.kind === "audiooutput");
    }

    async updateMic(micId: string): Promise<void> {
      this.selectedMicDeviceId = micId;
      if (initialized && !stopped) {
        await this.acquireMic(micId);
      }
    }

    updateCam(_camId: string): void {}
    updateSpeaker(_speakerId: string): void {}

    get selectedMic(): MediaDeviceInfo | Record<string, never> {
      return {};
    }
    get selectedCam(): MediaDeviceInfo | Record<string, never> {
      return {};
    }
    get selectedSpeaker(): MediaDeviceInfo | Record<string, never> {
      return {};
    }

    enableMic(enable: boolean): void {
      this.micEnabled = enable;
      const track = this.micStream?.getAudioTracks()[0];
      if (track) track.enabled = enable;
    }

    enableCam(_enable: boolean): void {}
    enableScreenShare(_enable: boolean): void {}

    get isCamEnabled(): boolean {
      return false;
    }
    get isMicEnabled(): boolean {
      return this.micEnabled;
    }
    get isSharingScreen(): boolean {
      return false;
    }
    get supportsScreenShare(): boolean {
      return false;
    }

    tracks(): Tracks {
      const localAudio = this.micStream?.getAudioTracks()[0];
      const botAudio = destination?.stream.getAudioTracks()[0];
      return {
        local: { ...(localAudio ? { audio: localAudio } : {}) },
        ...(botAudio ? { bot: { audio: botAudio } } : {}),
      };
    }
  }

  const media = new StudioWebAudioMediaManager();
  const transport = new WebSocketTransport({
    mediaManager: media as any,
    recorderSampleRate: 16000,
    playerSampleRate: 24000,
  });

  const disconnect = async () => {
    if (stopped) return;
    stopped = true;
    controller.abort();
    if (levelTimer) clearInterval(levelTimer);
    if (speakingTimer) clearTimeout(speakingTimer);
    await media.userStartedSpeaking();
    if (initialized) {
      try { transport.tracks().local?.audio?.stop(); } catch { /* Initialization may be incomplete. */ }
      try { await transport.disconnect(); } catch { /* Release the remaining local media below. */ }
    }
    destination?.stream.getTracks().forEach((track) => track.stop());
    if (context && context.state !== "closed") await context.close();
    events.onTrack(null);
    events.onLevel(0);
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
      response_id?: string;
      participant?: string;
      text?: string;
      ttft?: number;
      stt_latency?: number;
      data?: string;
      is_init?: boolean;
      seq?: number;
      has_audio?: boolean;
      post_turn_decay?: boolean;
      tfdt?: number;
      payload?: { response_id?: string; event_id?: string; session_id?: string; type?: string; value?: number; elapsed_ms?: number; count?: number; usage?: any; tool?: any };
    };

    if (data.type === "avatar_video" && typeof data.data === "string") {
      if (data.has_audio === true && !data.post_turn_decay && isAvatarActive(settings)) {
        avatarSpeechInTurn = true;
        events.onPhase("speaking");
        if (lastUserAt !== null) {
          events.onLatency(performance.now() - lastUserAt);
          lastUserAt = null;
        }
      }
      events.onAvatarVideo?.(
        data.data,
        Boolean(data.is_init),
        Number(data.seq ?? 0),
        typeof data.has_audio === "boolean" ? data.has_audio : undefined,
        typeof data.tfdt === "number" ? data.tfdt : undefined,
      );
      return;
    }

    if (data.type === "avatar_interrupted") {
      avatarSpeechInTurn = false;
      events.onAvatarInterrupted?.();
      events.onPhase("listening");
      return;
    }

    if (data.type === "avatar_fallback" || data.type === "voice_fallback") {
      const notice = data as { fallback_avatar?: unknown; fallback_voice?: unknown; reason?: unknown; code?: unknown };
      const reason = typeof notice.reason === "string" ? notice.reason : "";
      const code = typeof notice.code === "string" ? notice.code : "rejected";
      if (data.type === "avatar_fallback") {
        const avatar = typeof notice.fallback_avatar === "string" ? notice.fallback_avatar : "Kira";
        events.onAvatarFallback?.(avatar, reason || "Custom avatar fallback active", code);
      } else {
        const voice = typeof notice.fallback_voice === "string" ? notice.fallback_voice : "a prebuilt voice";
        events.onVoiceFallback?.(voice, reason || "Custom voice fallback active", code);
      }
      return;
    }

    if (data.type === "transcription" && typeof data.text === "string") {
      if (!data.text) {
        events.onPartialUser("");
        return;
      }
      if (data.participant?.toLowerCase() === "user") {
        turnStarted = false;
        avatarSpeechInTurn = false;
        lastUserAt = performance.now();
        events.onPartialUser("");
        const effStt = data.stt_latency !== undefined ? data.stt_latency : (pendingSTTLatency !== null ? pendingSTTLatency : undefined);
        pendingSTTLatency = null;
        lastTurnSTTLatency = effStt ?? null;
        events.onMessage("user", data.text, false, { sttLatency: effStt });
        events.onPhase("thinking");
      } else {
        const effLlm = data.ttft !== undefined ? data.ttft : (!data.response_id && pendingLLMLatency !== null ? pendingLLMLatency : undefined);
        pendingLLMLatency = null;
        const effTts = !data.response_id && pendingTTSLatency !== null ? pendingTTSLatency : undefined;
        pendingTTSLatency = null;
        const effStt = settings.engine === "cascade" ? (lastTurnSTTLatency ?? undefined) : undefined;
        lastTurnSTTLatency = null;

        if (isAvatarActive(settings)) {
          events.onPhase("speaking");
          if (lastUserAt !== null) {
            events.onLatency(performance.now() - lastUserAt);
            lastUserAt = null;
          }
        }

        events.onMessage("assistant", data.text, turnStarted, {
          llmLatency: effLlm,
          ttsLatency: effTts,
          sttLatency: effStt,
          responseId: data.response_id,
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
        const hadAvatarSpeech = avatarSpeechInTurn;
        turnStarted = false;
        avatarSpeechInTurn = false;
        pendingLLMLatency = null;
        pendingTTSLatency = null;
        lastTurnSTTLatency = null;
        if (isAvatarActive(settings) && !hadAvatarSpeech) {
          events.onPhase("listening");
        }
        events.onMetricUpdate?.("turn_complete", p);
      } else if (p.type === "interruption") {
        turnStarted = false;
        avatarSpeechInTurn = false;
        void media.userStartedSpeaking();
        events.onAvatarInterrupted?.();
        events.onPhase("listening");
        events.onMetricUpdate?.("interruption", p);
      } else if (p.type === "stt_latency") {
        pendingSTTLatency = p.value ?? null;
        lastTurnSTTLatency = p.value ?? null;
        events.onMetricUpdate?.("stt_latency", p);
      } else if (p.type === "llm_latency") {
        pendingLLMLatency = p.value ?? null;
        events.onMetricUpdate?.("llm_latency", p);
      } else if (p.type === "tts_latency") {
        pendingTTSLatency = p.value ?? null;
        events.onMetricUpdate?.("tts_latency", p);
      } else if (p.type === "cascade_cost") {
        events.onMetricUpdate?.("cascade_cost", p);
      } else if (p.type === "usage") {
        const turnCost = settings.engine === "live" ? calculateTurnCost(settings.model, p.usage) : null;
        events.onMetricUpdate?.("usage", {
          ...p.usage,
          response_id: p.response_id ?? p.usage?.response_id,
          event_id: p.event_id ?? p.usage?.event_id,
          session_id: p.session_id ?? p.usage?.session_id,
          turnCostUSD: turnCost?.totalUSD,
          costEstimated: turnCost?.estimated,
          costIncomplete: turnCost?.incomplete,
          costMinUSD: turnCost?.minUSD,
          costMaxUSD: turnCost?.maxUSD,
        });
      } else if (p.type === "tool_call") {
        events.onMetricUpdate?.("tool_call", p);
      }
    } else if (data.type === "phase_transition") {
      events.onMetricUpdate?.("phase_transition", data);
    } else if (data.type === "call_state") {
      events.onMetricUpdate?.("call_state", data);
    } else if (data.type === "booking_confirmed") {
      events.onMetricUpdate?.("booking_confirmed", data);
    } else if (data.type === "context_compression") {
      events.onMetricUpdate?.("context_compression", data.payload);
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
          method: "POST",
          headers: { "Content-Type": "application/json", ...diagnosticHeaders(settings.sessionId) },
          credentials: "include",
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
      const AudioCtx =
        window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      context = new AudioCtx({ sampleRate: 24000, latencyHint: "interactive" });
      speakerGain = context.createGain();
      speakerGain.gain.value = soundEnabled ? 1 : 0;
      speakerGain.connect(context.destination);
      destination = context.createMediaStreamDestination();
      analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.connect(destination);
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

      // Prime connection to resolve SNI matching before establishing WebSocket
      if (typeof window !== "undefined" && window.location.protocol === "https:") {
        try {
          await fetch(window.location.origin + "/connect/system-prompt", { credentials: "include" });
        } catch {
          // ignore
        }
      }

      try {
        await transport.connect({ wsUrl });
      } catch (err: any) {
        if (stopped) return;
        const msg = err?.message || String(err);
        if (msg.includes("1006")) {
          throw new Error("WebSocket connection error (1006): the proxy or server closed the WebSocket upgrade unexpectedly.");
        }
        throw new Error(`Failed to connect to voice stream: ${msg}`);
      }
      if (stopped) { await transport.disconnect(); return; }
      transport.sendReadyMessage();
      transport.sendMessage(new RTVIMessage("start_trigger", {}));
    },
    disconnect,
    setMic(enabled) {
      if (!stopped) transport.enableMic(enabled);
    },
    setSound(enabled) {
      soundEnabled = enabled;
      if (speakerGain) {
        speakerGain.gain.value = enabled ? 1 : 0;
      }
      if (enabled && context && context.state === "suspended") {
        void context.resume().catch(() => {});
      }
    },
  };
}
