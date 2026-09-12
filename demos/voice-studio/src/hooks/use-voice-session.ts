import { useCallback, useEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import {
  DEFAULT_SETTINGS,
  getDefaultBackendUrl,
  newSessionId,
  type Engine,
  type SessionSettings,
} from "@/lib/voice-session";
import { getPersona, type PersonaId } from "@/lib/personas";
import { createLiveSession, type LiveSession, type MessageMetrics } from "@/lib/pipecat-session";
import { calculateTurnCost, EMPTY_TOKEN_SPLIT, type TokenSplit } from "@/lib/pricing";
import { UsageLedger } from "@/lib/usage-ledger";
import type { Message, Phase } from "@/lib/studio-types";

/**
 * Owns a voice conversation: connection lifecycle, transcript, and the
 * per-turn telemetry the studio displays. The components below it are
 * presentational -- they read this and call back into it.
 */
export function useVoiceSession() {
  const [settings, setSettings] = useState<SessionSettings>({
    ...DEFAULT_SETTINGS,
    contextCompression: true,
    contextCompressionTokens: 2500,
    sessionId: newSessionId(),
  });
  const [phase, setPhase] = useState<Phase>("idle");
  const [source, setSource] = useState<"backend" | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [muted, setMuted] = useState(false);
  const [sound, setSound] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [latency, setLatency] = useState<number | null>(null);
  const [track, setTrack] = useState<MediaStreamTrack | null>(null);
  const [partialUser, setPartialUser] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showInlineEditor, setShowInlineEditor] = useState(false);
  // Live session metric counters
  const [turnCount, setTurnCount] = useState(0);
  const [lastSTT, setLastSTT] = useState<number | null>(null);
  const [lastTTFB, setLastTTFB] = useState<number | null>(null);
  const [lastTTS, setLastTTS] = useState<number | null>(null);
  const [tokenCount, setTokenCount] = useState(0);
  // Billed tokens split by direction and modality. The flat total hides the
  // only number that matters for cost: audio is 6x text on input and 6x on
  // output, so 16k "tokens" can mean very different bills.
  const [tokenSplit, setTokenSplit] = useState<TokenSplit>(EMPTY_TOKEN_SPLIT);
  const [sessionCostUSD, setSessionCostUSD] = useState<number>(0);
  const [sessionCostBounds, setSessionCostBounds] = useState({ minUSD: 0, maxUSD: 0, estimated: false, complete: true });
  const ledger = useRef(new UsageLedger());
  const responseMetrics = useRef(new Map<string, MessageMetrics>());
  const seenEvents = useRef(new Set<string>());
  const starting = useRef(false);
  const [interruptCount, setInterruptCount] = useState(0);

  // Persona Phase Tracking (e.g. Pragya JIT Phase Cards)
  const [currentPhase, setCurrentPhase] = useState<string>(
    settings.personaId === "lamborghini-concierge" ? "SOP_01_OPENING" : ""
  );
  const [visitedPhases, setVisitedPhases] = useState<string[]>(
    settings.personaId === "lamborghini-concierge" ? ["SOP_01_OPENING"] : []
  );
  const [phaseDirective, setPhaseDirective] = useState<string | null>(null);
  const [phaseDelivery, setPhaseDelivery] = useState<"pending" | "sent" | "failed" | null>(null);
  const phaseRevision = useRef(0);
  const [confirmedBooking, setConfirmedBooking] = useState<{
    booking_id?: string;
    center_name?: string;
    date?: string;
    time?: string;
    vehicle_variant?: string;
  } | null>(null);

  // Context Compression toast event state
  const [compressionEvent, setCompressionEvent] = useState<{
    id: string;
    tokens?: number;
    threshold?: number;
    message?: string;
  } | null>(null);
  const compressionTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const triggerCompressionToast = useCallback((payload?: { tokens?: number; threshold?: number; message?: string }) => {
    if (compressionTimeout.current) clearTimeout(compressionTimeout.current);
    const effectiveThreshold = Math.max(2000, payload?.threshold ?? settings.contextCompressionTokens ?? 2500);
    setCompressionEvent({
      id: crypto.randomUUID(),
      tokens: payload?.tokens,
      threshold: effectiveThreshold,
      message: payload?.message,
    });
    compressionTimeout.current = setTimeout(() => {
      setCompressionEvent(null);
    }, 4500);
  }, [settings.contextCompressionTokens]);

  const dismissCompressionToast = useCallback(() => {
    if (compressionTimeout.current) clearTimeout(compressionTimeout.current);
    setCompressionEvent(null);
  }, []);

  const customInstructions = useRef("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const session = useRef<LiveSession | null>(null);
  const run = useRef(0);
  const audio = useRef<HTMLAudioElement | null>(null);
  const transcript = useRef<HTMLDivElement | null>(null);
  const followTranscript = useRef(true);
  const reduced = useReducedMotion();
  const active = phase !== "idle";
  const persona = getPersona(settings.personaId);
  const custom = persona.id === "custom";
  const engineName = settings.engine === "live" ? "Gemini Live" : "Cascade";

  useEffect(() => {
    // Tear the session down if the tab navigates away mid-call; a dangling
    // websocket keeps the backend billing audio nobody is listening to.
    return () => {
      run.current++;
      timers.current.forEach(clearTimeout);
      void session.current?.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, [active]);

  useEffect(() => {
    if (followTranscript.current && transcript.current) {
      transcript.current.scrollTo({ top: transcript.current.scrollHeight, behavior: reduced ? "instant" : "smooth" });
    }
  }, [messages, partialUser, reduced]);

  useEffect(() => {
    if (audio.current) {
      audio.current.srcObject = track ? new MediaStream([track]) : null;
      if (track) {
        void audio.current
          .play()
          .catch(() => setError("Audio playback was blocked. Use the speaker control to enable sound."));
      }
    }
  }, [track]);

  const addMessage = useCallback((role: Message["role"], text: string, metrics?: MessageMetrics) => {
    setMessages((items) => [
      ...items,
      {
        id: crypto.randomUUID(),
        role,
        text,
        time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        createdAt: Date.now(),
        metrics,
      },
    ]);
  }, []);


  const endSession = useCallback(async () => {
    run.current++;
    timers.current.forEach(clearTimeout);
    timers.current = [];
    const current = session.current;
    session.current = null;
    setPhase("idle");
    setTrack(null);
    setMuted(false);
    setPartialUser("");
    starting.current = false;
    if (current) await current.disconnect();
  }, []);

  const resetConversation = (personaId = settings.personaId) => {
    setError("");
    setMessages([]);
    setElapsed(0);
    setLatency(null);
    setSource(null);
    setCopied(false);
    setTurnCount(0);
    setLastSTT(null);
    setLastTTFB(null);
    setLastTTS(null);
    setTokenCount(0);
    setTokenSplit(EMPTY_TOKEN_SPLIT);
    setSessionCostUSD(0);
    setInterruptCount(0);
    setCurrentPhase(personaId === "lamborghini-concierge" ? "SOP_01_OPENING" : "");
    setVisitedPhases(personaId === "lamborghini-concierge" ? ["SOP_01_OPENING"] : []);
    setPhaseDirective(null);
    setPhaseDelivery(null);
    phaseRevision.current = 0;
    setConfirmedBooking(null);
    ledger.current = new UsageLedger();
    responseMetrics.current.clear();
    seenEvents.current.clear();
    setSessionCostBounds({ minUSD: 0, maxUSD: 0, estimated: false, complete: true });
    starting.current = false;
    if (compressionTimeout.current) clearTimeout(compressionTimeout.current);
    setCompressionEvent(null);
    followTranscript.current = true;
  };

  const choosePersona = (value: string) => {
    if (active) return;
    const p = getPersona(value);
    if (settings.personaId === "custom") customInstructions.current = settings.instructions;
    setShowInlineEditor(false);
    setSettings((current) => ({
      ...current,
      personaId: value as PersonaId,
      voice: p.defaultVoice || current.voice,
      instructions: value === "custom" ? customInstructions.current : "",
    }));
    setCurrentPhase(value === "lamborghini-concierge" ? "SOP_01_OPENING" : "");
    setVisitedPhases(value === "lamborghini-concierge" ? ["SOP_01_OPENING"] : []);
    setPhaseDirective(null);
    setConfirmedBooking(null);
    resetConversation(value as PersonaId);
  };

  const chooseEngine = (value: string) => {
    if (active) return;
    setSettings((current) => ({ ...current, engine: value as Engine }));
    resetConversation();
  };

  const startBackend = async (engineOverride?: Engine) => {
    if (starting.current || session.current) return;
    const targetEngine = engineOverride || settings.engine;
    const targetBackendUrl = settings.backendUrl?.trim() || getDefaultBackendUrl();
    const activeSettings: SessionSettings = {
      ...settings,
      engine: targetEngine,
      backendUrl: targetBackendUrl,
      sessionId: newSessionId(),
    };
    setSettings((current) => ({ ...current, sessionId: activeSettings.sessionId }));
    if (engineOverride && engineOverride !== settings.engine) {
      setSettings((current) => ({ ...current, engine: engineOverride }));
    }
    setSettingsOpen(false);
    resetConversation();
    starting.current = true;
    setSource("backend");
    setPhase("connecting");
    const current = ++run.current;
    const updateResponse = (responseId: string, patch: MessageMetrics) => {
      const metrics = { ...responseMetrics.current.get(responseId), ...patch, responseId };
      responseMetrics.current.set(responseId, metrics);
      setMessages(items => items.map(item => item.role === "assistant" && item.metrics?.responseId === responseId
        ? { ...item, metrics: { ...item.metrics, ...metrics } } : item));
    };
    try {
      const live = await createLiveSession(activeSettings, {
        onPhase: (value) => {
          if (run.current === current) setPhase(value);
        },
        onMessage: (role, text, append, metrics) => {
          if (run.current !== current) return;
          if (metrics?.responseId) {
            metrics = { ...metrics, ...responseMetrics.current.get(metrics.responseId) };
          }
          if (role === "user") {
            setPartialUser("");
            if (metrics?.sttLatency !== undefined) {
              setLastSTT(Math.round(metrics.sttLatency * 1000));
            }
          } else {
            if (metrics?.llmLatency !== undefined) {
              setLastTTFB(Math.round(metrics.llmLatency * 1000));
            }
            if (metrics?.ttsLatency !== undefined) {
              setLastTTS(Math.round(metrics.ttsLatency * 1000));
            }
          }
          if (append || metrics?.responseId) {
            setMessages((items) => {
              const index = metrics?.responseId
                ? items.findIndex(m => m.role === role && m.metrics?.responseId === metrics?.responseId)
                : items.length - 1;
              const last = items[index];
              if (last?.role === "assistant") {
                const separator =
                  targetEngine === "cascade" && /\S$/.test(last.text) && /^[\p{L}\p{N}]/u.test(text) ? " " : "";
                const mergedMetrics = {
                  ...last.metrics,
                  ...metrics,
                  llmLatency: last.metrics?.llmLatency ?? metrics?.llmLatency,
                  sttLatency: last.metrics?.sttLatency ?? metrics?.sttLatency,
                  ttsLatency: last.metrics?.ttsLatency ?? metrics?.ttsLatency,
                  turnCostUSD: metrics?.turnCostUSD ?? last.metrics?.turnCostUSD,
                  usage: metrics?.usage ?? last.metrics?.usage,
                };
                return items.map((item, i) => i === index ? { ...last, text: last.text + separator + text, metrics: mergedMetrics } : item);
              }
              return [
                ...items,
                {
                  id: crypto.randomUUID(),
                  role,
                  text,
                  time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                  createdAt: Date.now(),
                  metrics,
                },
              ];
            });
          } else {
            addMessage(role, text, metrics);
          }
        },
        onReplaceMessage: (role, text) => {
          if (run.current !== current) return;
          setMessages((items) => {
            const idx = items.findLastIndex((m) => m.role === role);
            if (idx === -1) return items;
            const copy = [...items];
            copy[idx] = { ...copy[idx], text };
            return copy;
          });
        },
        onMetricUpdate: (type, val) => {
          if (run.current !== current) return;
          if (type === "phase_transition") {
            if (Number.isSafeInteger(val?.revision)) {
              if (val.revision <= phaseRevision.current) return;
              phaseRevision.current = val.revision;
            }
            const phaseId = val?.phase_id || val?.phase || "";
            if (phaseId) {
              setCurrentPhase(phaseId);
              setVisitedPhases((prev) => (prev.includes(phaseId) ? prev : [...prev, phaseId]));
            }
            if (val?.directive || val?.title) {
              setPhaseDirective(val.directive || val.title);
            }
            setPhaseDelivery(
              ["pending", "sent", "failed"].includes(val?.delivery_status)
                ? val.delivery_status
                : typeof val?.card_pushed === "boolean" ? (val.card_pushed ? "sent" : "failed") : null
            );
          } else if (type === "booking_confirmed") {
            setConfirmedBooking(val);
          } else if (type === "context_compression") {
            triggerCompressionToast(val);
          } else if (type === "turn_complete" || type === "interruption") {
            if (val?.event_id) {
              if (seenEvents.current.has(val.event_id)) return;
              seenEvents.current.add(val.event_id);
            }
            if (type === "turn_complete") setTurnCount(c => c + 1);
            else setInterruptCount(c => c + 1);
            if (val?.response_id && val.elapsed_ms !== undefined) {
              updateResponse(val.response_id, { interruptedMs: val.elapsed_ms });
            }
          } else if (["stt_latency", "llm_latency", "tts_latency"].includes(type)) {
            const value = typeof val === "number" ? val : val?.value;
            if (!Number.isFinite(value) || value < 0) return;
            const setter = type === "stt_latency" ? setLastSTT : type === "llm_latency" ? setLastTTFB : setLastTTS;
            setter(Math.round(value * 1000));
            if (val?.response_id && type !== "stt_latency") {
              updateResponse(val.response_id, { [type === "llm_latency" ? "llmLatency" : "ttsLatency"]: value });
            }
          } else if (type === "usage") {
            if (val?.session_id && val.session_id !== activeSettings.sessionId) return;
            if (!val || !ledger.current.ingest(val)) return;
            const totals = ledger.current.snapshot(targetEngine, activeSettings.model);
            setTokenCount(totals.tokens);
            setTokenSplit(totals.split);
            setSessionCostUSD(totals.costUSD);
            setSessionCostBounds({ minUSD: totals.minUSD, maxUSD: totals.maxUSD, estimated: totals.estimated, complete: totals.complete });
            if (val.response_id) {
              const cost = targetEngine === "live" ? calculateTurnCost(val.model ?? activeSettings.model, val) : null;
              updateResponse(val.response_id, {
                usage: val, turnCostUSD: cost?.totalUSD, costEstimated: cost?.estimated,
                costMinUSD: cost?.minUSD, costMaxUSD: cost?.maxUSD,
              });
            }
          }
        },
        onPartialUser: (text) => {
          if (run.current === current) setPartialUser(text);
        },
        onTrack: (value) => {
          if (run.current === current) setTrack(value);
        },
        onLevel: () => {},
        onLatency: (value) => {
          if (run.current === current) setLatency(value);
        },
        onError: (text) => {
          if (run.current === current) setError(text);
        },
        onDisconnected: () => {
          if (run.current !== current) return;
          setPhase("idle");
          setTrack(null);
          setMuted(false);
          setPartialUser("");
          session.current = null;
          starting.current = false;
        },
      });
      if (run.current !== current) {
        await live.disconnect();
        return;
      }
      session.current = live;
      await live.connect();
    } catch (e) {
      if (run.current !== current) return;
      const message = e instanceof Error ? e.message : "Unable to connect to your backend.";
      await endSession();
      setError(message);
    }
  };

  const toggleSound = () => {
    setSound((value) => !value);
    if (sound) window.speechSynthesis?.cancel();
    else if (audio.current && track)
      void audio.current.play().catch(() => setError("Your browser is blocking audio playback."));
  };

  const update = (key: keyof SessionSettings, value: string) =>
    setSettings((current) => ({ ...current, [key]: value }));

  const updateBool = (key: keyof SessionSettings, value: boolean) =>
    setSettings((current) => ({ ...current, [key]: value }));

  const updateNumber = (key: keyof SessionSettings, value: number) =>
    setSettings((current) => ({ ...current, [key]: value }));

  const copyTranscript = async () => {
    try {
      await navigator.clipboard.writeText(
        messages.map((m) => `${m.role === "user" ? "You" : persona.agentName}: ${m.text}`).join("\n\n")
      );
      setCopied(true);
      timers.current.push(setTimeout(() => setCopied(false), 1800));
    } catch {
      setError("Copy is unavailable in this browser. You can select the transcript text instead.");
    }
  };

  const phaseLabel = {
    idle: messages.length ? "Session ended" : "Ready to start",
    connecting: "Connecting…",
    listening: muted ? "Microphone muted" : "Listening",
    thinking: "Thinking",
    speaking: `${persona.agentName} is speaking`,
  }[phase];

  const duration = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;

  return {
    // state
    settings, phase, source, messages, elapsed, muted, sound, error, copied,
    latency, track, partialUser, settingsOpen, showInlineEditor,
    turnCount, lastSTT, lastTTFB, lastTTS, tokenCount, tokenSplit, sessionCostUSD, sessionCostBounds, interruptCount,
    compressionEvent, dismissCompressionToast, triggerCompressionToast,
    // phase tracking & booking
    currentPhase, visitedPhases, phaseDirective, phaseDelivery, confirmedBooking,
    // setters the views drive directly
    setMuted, setError, setSettingsOpen, setShowInlineEditor,
    // refs
    session, audio, transcript, followTranscript,
    // derived
    active, persona, custom, engineName, phaseLabel, duration, reduced,
    // actions
    endSession, choosePersona, chooseEngine, startBackend, toggleSound,
    update, updateBool, updateNumber, copyTranscript,
  };
}

export type VoiceStudio = ReturnType<typeof useVoiceSession>;
