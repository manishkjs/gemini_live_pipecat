import { initialPersonaPhase } from "@/lib/personas";
import { readToolInjection, type ToolInjectionEvent } from "@/lib/tool-injection";
import { useCallback, useEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import {
  DEFAULT_SETTINGS,
  getDefaultBackendUrl,
  getPersonaVoiceDesign,
  isGeminiClonedVoice,
  reconcileVoiceForEngine,
  reconcileVoiceForPersona,
  supportsGeminiClone,
  newSessionId,
  transcriptText,
  type Engine,
  type SessionSettings,
} from "@/lib/voice-session";
import { getPersona, type PersonaId } from "@/lib/personas";
import {
  createLiveSession,
  type LiveSession,
  type MessageMetrics,
  type UserEmotionReading,
} from "@/lib/pipecat-session";
import { calculateTurnCost, EMPTY_TOKEN_SPLIT, type TokenSplit } from "@/lib/pricing";
import { UsageLedger } from "@/lib/usage-ledger";
import { readCascadeCost, type CascadeCost } from "@/lib/cascade-cost";
import { computeTurnTtfbSeconds } from "@/lib/call-console";
import { useAvatarStream } from "@/hooks/use-avatar-stream";
import type { Message, Phase } from "@/lib/studio-types";

/** A transcript entry. Assistant text arrives as a raw script; the reader sees `transcriptText` of it. */
function transcriptMessage(
  role: Message["role"],
  text: string,
  metrics?: MessageMetrics,
  startedAtMs?: number | null,
): Message {
  const now = Date.now();
  const relSec = startedAtMs != null ? Math.max(0, Math.floor((now - startedAtMs) / 1000)) : 0;
  const offsetLabel = `+${String(Math.floor(relSec / 60)).padStart(2, "0")}:${String(relSec % 60).padStart(2, "0")}`;
  return {
    id: crypto.randomUUID(),
    role,
    ...(role === "assistant" ? { rawText: text, text: transcriptText(text) } : { text }),
    time: new Date(now).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    offsetLabel,
    createdAt: now,
    metrics,
  };
}

/**
 * Owns a voice conversation: connection lifecycle, transcript, and the
 * per-turn telemetry the studio displays. The components below it are
 * presentational -- they read this and call back into it.
 */
export function useVoiceSession() {
  const [settings, setSettings] = useState<SessionSettings>({
    ...DEFAULT_SETTINGS,
    contextCompression: true,
    contextCompressionTokens: 5000,
    sessionId: newSessionId(),
  });
  const [phase, setPhase] = useState<Phase>("idle");
  const [source, setSource] = useState<"backend" | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [muted, setMuted] = useState(false);
  const [sound, setSound] = useState(true);
  const avatarStream = useAvatarStream(
    !sound,
    () => {
      setPhase((current) => (current === "speaking" ? "listening" : current));
    },
    (reason) => {
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
      setError(reason);
      if (current) void current.disconnect();
    },
  );
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [latency, setLatency] = useState<number | null>(null);
  const [track, setTrack] = useState<MediaStreamTrack | null>(null);
  const [partialUser, setPartialUser] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showInlineEditor, setShowInlineEditor] = useState(false);
  const audioLevelRef = useRef(0);
  const audioLevelListeners = useRef(new Set<() => void>());
  const publishAudioLevel = useCallback((nextLevel: number) => {
    const clamped = Math.max(0, Math.min(1, nextLevel));
    if (Math.abs(audioLevelRef.current - clamped) < 0.0005 && (clamped !== 0 || audioLevelRef.current === 0)) {
      return;
    }
    audioLevelRef.current = clamped;
    for (const listener of audioLevelListeners.current) {
      listener();
    }
  }, []);
  const subscribeAudioLevel = useCallback((listener: () => void) => {
    audioLevelListeners.current.add(listener);
    return () => {
      audioLevelListeners.current.delete(listener);
    };
  }, []);
  const getAudioLevel = useCallback((): number => audioLevelRef.current, []);
  const [playingSample, setPlayingSample] = useState(false);
  const sampleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sampleToken = useRef(0);
  const lastLevelUpdateAt = useRef(0);
  const callStartedAt = useRef<number | null>(null);
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
  const [sessionCostBounds, setSessionCostBounds] = useState<{
    minUSD: number | null;
    maxUSD: number | null;
    estimated: boolean;
    complete: boolean;
    incomplete: boolean;
  }>({ minUSD: 0, maxUSD: 0, estimated: false, complete: true, incomplete: false });
  const ledger = useRef(new UsageLedger());
  const [cascadeCost, setCascadeCost] = useState<CascadeCost | null>(null);
  const cascadeCostRevision = useRef(-1);
  const responseMetrics = useRef(new Map<string, MessageMetrics>());
  const lastAssistantMetrics = useRef<MessageMetrics | null>(null);
  const pendingUserEmotion = useRef<UserEmotionReading | null>(null);
  const userTurnAwaitingFinalEmotion = useRef(false);
  const [liveEmotion, setLiveEmotion] = useState<UserEmotionReading | null>(null);
  const [emotionStats, setEmotionStats] = useState<{
    readonly count: number;
    readonly totalInputTokens: number;
    readonly lastLatencyMs: number | null;
  }>({ count: 0, totalInputTokens: 0, lastLatencyMs: null });
  const seenEvents = useRef(new Set<string>());
  const starting = useRef(false);
  const [interruptCount, setInterruptCount] = useState(0);

  // Persona Phase Tracking (e.g. Pragya JIT Phase Cards)
  const [currentPhase, setCurrentPhase] = useState<string>(
    initialPersonaPhase(settings.personaId)
  );
  const [visitedPhases, setVisitedPhases] = useState<string[]>(
    [initialPersonaPhase(settings.personaId)].filter(Boolean)
  );
  const [phaseDirective, setPhaseDirective] = useState<string | null>(null);
  const [phaseDelivery, setPhaseDelivery] = useState<"pending" | "sent" | "failed" | null>(null);
  const phaseRevision = useRef(0);
  const [callSlots, setCallSlots] = useState<Record<string, any>>({});
  const [confirmedBooking, setConfirmedBooking] = useState<{
    booking_id?: string;
    center_name?: string;
    date?: string;
    time?: string;
    vehicle_variant?: string;
  } | null>(null);

  // Tools registered with each prompt card (context_update personas): a small fading toast.
  const [toolInjection, setToolInjection] = useState<ToolInjectionEvent | null>(null);
  const dismissToolInjection = useCallback(() => setToolInjection(null), []);

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
    const effectiveThreshold = Math.max(5000, payload?.threshold ?? settings.contextCompressionTokens ?? 5000);
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

  const [avatarFallbackNotice, setAvatarFallbackNotice] = useState<{
    fallbackAvatar: string;
    reason: string;
    code: string;
  } | null>(null);
  const [voiceFallbackNotice, setVoiceFallbackNotice] = useState<{
    fallbackVoice: string;
    reason: string;
    code: string;
  } | null>(null);

  const customInstructions = useRef("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const session = useRef<LiveSession | null>(null);
  const mutedRef = useRef(muted);
  mutedRef.current = muted;
  const soundRef = useRef(sound);
  soundRef.current = sound;
  const run = useRef(0);
  const audio = useRef<HTMLAudioElement | null>(null);
  const transcript = useRef<HTMLDivElement | null>(null);
  const followTranscript = useRef(true);
  const reduced = useReducedMotion();
  const active = phase !== "idle";
  const persona = getPersona(settings.personaId);
  const custom = persona.id === "custom";
  const engineName = settings.engine === "live" ? "Gemini Live" : "Cascade";

  const stopVoiceSample = useCallback(() => {
    sampleToken.current++;
    if (sampleTimer.current) {
      clearTimeout(sampleTimer.current);
      sampleTimer.current = null;
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    setPlayingSample(false);
  }, []);

  const toggleVoiceSample = useCallback(() => {
    if (active) return;
    if (playingSample) {
      stopVoiceSample();
      return;
    }
    if (!sound) return;
    const token = ++sampleToken.current;
    setPlayingSample(true);
    if (sampleTimer.current) clearTimeout(sampleTimer.current);
    sampleTimer.current = setTimeout(() => {
      if (sampleToken.current !== token) return;
      sampleTimer.current = null;
      setPlayingSample(false);
    }, 3200);

    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      try {
        window.speechSynthesis.cancel();
        const sampleLine = persona.opening || `Hello, I am ${persona.agentName}. Ready when you are.`;
        const utterance = new SpeechSynthesisUtterance(sampleLine);
        utterance.lang = settings.language;
        utterance.rate = settings.ttsPace ?? 1.0;
        utterance.onstart = () => {
          if (sampleToken.current !== token) return;
          if (sampleTimer.current) clearTimeout(sampleTimer.current);
          sampleTimer.current = setTimeout(() => {
            if (sampleToken.current !== token) return;
            sampleTimer.current = null;
            setPlayingSample(false);
          }, 20000);
        };
        utterance.onend = () => {
          if (sampleToken.current !== token) return;
          stopVoiceSample();
        };
        utterance.onerror = (ev) => {
          if (sampleToken.current !== token) return;
          if (ev.error === "canceled" || ev.error === "interrupted") {
            stopVoiceSample();
          }
        };
        window.speechSynthesis.speak(utterance);
      } catch {
        // Fallback to visual timer preview when SpeechSynthesis is unavailable.
      }
    }
  }, [active, persona.agentName, persona.opening, playingSample, settings.language, settings.ttsPace, sound, stopVoiceSample]);

  useEffect(() => {
    // Tear the session down if the tab navigates away mid-call; a dangling
    // websocket keeps the backend billing audio nobody is listening to.
    return () => {
      run.current++;
      timers.current.forEach(clearTimeout);
      if (sampleTimer.current) clearTimeout(sampleTimer.current);
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
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
    session.current?.setSound?.(sound);
  }, [sound]);

  useEffect(() => {
    session.current?.setMic(!muted);
  }, [muted]);

  const addMessage = useCallback((role: Message["role"], text: string, metrics?: MessageMetrics) => {
    setMessages((items) => [...items, transcriptMessage(role, text, metrics, callStartedAt.current)]);
  }, []);

  const endSession = useCallback(async () => {
    stopVoiceSample();
    run.current++;
    timers.current.forEach(clearTimeout);
    timers.current = [];
    const current = session.current;
    session.current = null;
    setPhase("idle");
    setTrack(null);
    publishAudioLevel(0);
    setMuted(false);
    setPartialUser("");
    pendingUserEmotion.current = null;
    userTurnAwaitingFinalEmotion.current = false;
    starting.current = false;
    avatarStream.reset();
    if (current) await current.disconnect();
  }, [avatarStream, publishAudioLevel, stopVoiceSample]);

  const resetConversation = (personaId = settings.personaId) => {
    stopVoiceSample();
    callStartedAt.current = null;
    publishAudioLevel(0);
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
    setCascadeCost(null);
    cascadeCostRevision.current = -1;
    setInterruptCount(0);
    setCurrentPhase(initialPersonaPhase(personaId));
    setVisitedPhases([initialPersonaPhase(personaId)].filter(Boolean));
    setPhaseDirective(null);
    setPhaseDelivery(null);
    phaseRevision.current = 0;
    setCallSlots({});
    setConfirmedBooking(null);
    ledger.current = new UsageLedger();
    responseMetrics.current.clear();
    lastAssistantMetrics.current = null;
    pendingUserEmotion.current = null;
    userTurnAwaitingFinalEmotion.current = false;
    setLiveEmotion(null);
    setEmotionStats({ count: 0, totalInputTokens: 0, lastLatencyMs: null });
    seenEvents.current.clear();
    setSessionCostBounds({ minUSD: 0, maxUSD: 0, estimated: false, complete: true, incomplete: false });
    starting.current = false;
    avatarStream.reset();
    setAvatarFallbackNotice(null);
    setVoiceFallbackNotice(null);
    if (compressionTimeout.current) clearTimeout(compressionTimeout.current);
    setCompressionEvent(null);
    followTranscript.current = true;
  };

  const choosePersona = (value: string) => {
    if (active) return;
    getPersona(value);
    const vd = getPersonaVoiceDesign(value);
    if (settings.personaId === "custom") customInstructions.current = settings.instructions;
    setShowInlineEditor(false);
    setSettings((current) => ({
      ...current,
      personaId: value as PersonaId,
      voice: reconcileVoiceForPersona(current.voice, value),
      ttsStyle: vd.ttsStyle,
      ttsPaceLabel: vd.ttsPaceLabel,
      ttsAccent: vd.ttsAccent,
      ttsPitch: vd.ttsPitch,
      ttsVoicePrompt: vd.ttsVoicePrompt,
      instructions: value === "custom" ? customInstructions.current : "",
    }));
    setCurrentPhase(initialPersonaPhase(value));
    setVisitedPhases([initialPersonaPhase(value)].filter(Boolean));
    setPhaseDirective(null);
    setConfirmedBooking(null);
    resetConversation(value as PersonaId);
  };

  const chooseEngine = (value: string) => {
    if (active) return;
    const nextEngine = value as Engine;
    setSettings((current) => ({
      ...current,
      engine: nextEngine,
      voice: reconcileVoiceForEngine(current, nextEngine),
    }));
    resetConversation();
  };

  const startBackend = async (engineOverride?: Engine, overrides?: Partial<SessionSettings>) => {
    if (starting.current || session.current) {
      if (overrides) {
        await endSession();
      } else {
        return;
      }
    }
    const mergedSettings: SessionSettings = {
      ...settings,
      ...overrides,
    };
    const targetEngine = engineOverride || mergedSettings.engine;
    const targetVoice = reconcileVoiceForEngine(mergedSettings, targetEngine);
    const targetBackendUrl = mergedSettings.backendUrl?.trim() || getDefaultBackendUrl();
    const activeSettings: SessionSettings = {
      ...mergedSettings,
      engine: targetEngine,
      voice: targetVoice,
      backendUrl: targetBackendUrl,
      sessionId: newSessionId(),
    };
    setSettings((current) => ({
      ...current,
      ...overrides,
      engine: targetEngine,
      voice: targetVoice,
      sessionId: activeSettings.sessionId,
    }));
    setSettingsOpen(false);
    resetConversation();
    callStartedAt.current = null;
    starting.current = true;
    setSource("backend");
    setPhase("connecting");

    const current = ++run.current;
    const syncLastTtfb = (metrics: MessageMetrics | undefined): void => {
      const totalSec = computeTurnTtfbSeconds(metrics, targetEngine);
      if (totalSec !== null) {
        setLastTTFB(Math.round(totalSec * 1000));
      }
    };
    const updateResponse = (responseId: string, patch: MessageMetrics) => {
      const prev = responseMetrics.current.get(responseId);
      const metrics: MessageMetrics = {
        ...prev,
        ...patch,
        llmLatency: patch.llmLatency ?? prev?.llmLatency,
        ttsLatency: patch.ttsLatency ?? prev?.ttsLatency,
        sttLatency: patch.sttLatency ?? prev?.sttLatency,
        turnCostUSD: patch.turnCostUSD ?? prev?.turnCostUSD,
        costIncomplete: patch.costIncomplete ?? prev?.costIncomplete,
        usage: patch.usage ?? prev?.usage,
        responseId,
      };
      responseMetrics.current.set(responseId, metrics);
      if (
        !lastAssistantMetrics.current?.responseId ||
        lastAssistantMetrics.current.responseId === responseId
      ) {
        lastAssistantMetrics.current = metrics;
      }
      syncLastTtfb(metrics);
      setMessages(items => items.map(item => item.role === "assistant" && item.metrics?.responseId === responseId
        ? { ...item, metrics: { ...item.metrics, ...metrics } } : item));
    };
    try {
      const live = await createLiveSession(activeSettings, {
        onPhase: (value) => {
          if (run.current !== current) return;
          if (value !== "connecting" && value !== "idle" && callStartedAt.current === null) {
            callStartedAt.current = Date.now();
          }
          setPhase(value);
        },
        onMessage: (role, text, append, metrics) => {
          if (run.current !== current) return;
          if (metrics?.responseId) {
            const prev = responseMetrics.current.get(metrics.responseId);
            const merged: MessageMetrics = {
              ...prev,
              ...metrics,
              llmLatency: metrics.llmLatency ?? prev?.llmLatency,
              ttsLatency: metrics.ttsLatency ?? prev?.ttsLatency,
              sttLatency: metrics.sttLatency ?? prev?.sttLatency,
              turnCostUSD: metrics.turnCostUSD ?? prev?.turnCostUSD,
              costIncomplete: metrics.costIncomplete ?? prev?.costIncomplete,
              usage: metrics.usage ?? prev?.usage,
              responseId: metrics.responseId,
            };
            if (role === "assistant") {
              responseMetrics.current.set(metrics.responseId, merged);
            }
            metrics = merged;
          }
          if (role === "user") {
            lastAssistantMetrics.current = null;
            setPartialUser("");
            const queuedEmotion = pendingUserEmotion.current;
            pendingUserEmotion.current = null;
            if (queuedEmotion) {
              metrics = { ...metrics, userEmotion: queuedEmotion };
              userTurnAwaitingFinalEmotion.current = queuedEmotion.interim;
            } else {
              userTurnAwaitingFinalEmotion.current = true;
            }
            if (metrics?.sttLatency !== undefined) {
              setLastSTT(Math.round(metrics.sttLatency * 1000));
            }
          } else {
            userTurnAwaitingFinalEmotion.current = false;
            const nextAssistantMetrics: MessageMetrics = {
              ...(lastAssistantMetrics.current?.responseId &&
              metrics?.responseId &&
              lastAssistantMetrics.current.responseId !== metrics.responseId
                ? undefined
                : lastAssistantMetrics.current),
              ...metrics,
            };
            lastAssistantMetrics.current = nextAssistantMetrics;
            syncLastTtfb(nextAssistantMetrics);
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
                const raw = last.rawText ?? last.text;
                const separator =
                  targetEngine === "cascade" && /\S$/.test(raw) && /^[\p{L}\p{N}]/u.test(text) ? " " : "";
                const rawText = raw + separator + text;
                const mergedMetrics = {
                  ...last.metrics,
                  ...metrics,
                  llmLatency: last.metrics?.llmLatency ?? metrics?.llmLatency,
                  sttLatency: last.metrics?.sttLatency ?? metrics?.sttLatency,
                  ttsLatency: last.metrics?.ttsLatency ?? metrics?.ttsLatency,
                  turnCostUSD: metrics?.turnCostUSD ?? last.metrics?.turnCostUSD,
                  costIncomplete: metrics?.costIncomplete ?? last.metrics?.costIncomplete,
                  usage: metrics?.usage ?? last.metrics?.usage,
                };
                return items.map((item, i) => i === index
                  ? { ...last, rawText, text: transcriptText(rawText), metrics: mergedMetrics } : item);
              }
              return [...items, transcriptMessage(role, text, metrics, callStartedAt.current)];
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
            copy[idx] = role === "assistant" ? { ...copy[idx], rawText: text, text: transcriptText(text) } : { ...copy[idx], text };
            return copy;
          });
        },
        onMetricUpdate: (type, val) => {
          if (run.current !== current) return;
          if (type === "cascade_cost") {
            if (targetEngine !== "cascade") return;
            const cost = readCascadeCost(val, activeSettings.sessionId!, cascadeCostRevision.current);
            if (cost) {
              cascadeCostRevision.current = cost.revision;
              setCascadeCost(cost);
            }
          } else if (type === "phase_transition") {
            if (val?.session_id && val.session_id !== activeSettings.sessionId) return;
            if (Number.isSafeInteger(val?.revision)) {
              if (val.revision <= phaseRevision.current) return;
              phaseRevision.current = val.revision;
            }
            if (val?.slots && typeof val.slots === "object") {
              setCallSlots(val.slots);
            }
            const phaseId = val?.phase_id || val?.phase || "";
            const delivered = (val?.card_pushed === true || val?.delivery_status === "sent") && val?.card_pushed !== false && val?.delivery_status !== "failed";
            if (phaseId && delivered && getPersona(activeSettings.personaId).phaseIds?.includes(phaseId)) {
              setCurrentPhase(phaseId);
              setVisitedPhases((prev) => (prev.includes(phaseId) ? prev : [...prev, phaseId]));
            }
            if (delivered && (val?.directive || val?.title)) {
              setPhaseDirective(val.directive || val.title);
            }
            const injected = delivered ? readToolInjection(val) : null;
            if (injected) setToolInjection(injected);
            setPhaseDelivery(
              ["pending", "sent", "failed"].includes(val?.delivery_status)
                ? val.delivery_status
                : typeof val?.card_pushed === "boolean" ? (val.card_pushed ? "sent" : "failed") : null
            );
          } else if (type === "call_state") {
            if (val?.slots && typeof val.slots === "object") {
              setCallSlots(val.slots);
            }
          } else if (type === "booking_confirmed") {
            setConfirmedBooking(val);
          } else if (type === "context_compression") {
            triggerCompressionToast(val);
          } else if (type === "turn_complete" || type === "interruption") {
            if (val?.event_id) {
              if (seenEvents.current.has(val.event_id)) return;
              seenEvents.current.add(val.event_id);
            }
            if (type === "turn_complete") {
              setTurnCount(c => c + 1);
            } else {
              setInterruptCount(c => c + 1);
              if (typeof val?.elapsed_ms === "number") {
                if (val.response_id) {
                  updateResponse(val.response_id, { interruptedMs: val.elapsed_ms });
                } else {
                  if (lastAssistantMetrics.current) {
                    const updated: MessageMetrics = {
                      ...lastAssistantMetrics.current,
                      interruptedMs: val.elapsed_ms,
                    };
                    lastAssistantMetrics.current = updated;
                    if (updated.responseId) {
                      responseMetrics.current.set(updated.responseId, updated);
                    }
                    syncLastTtfb(updated);
                  }
                  setMessages((items) => {
                    const idx = items.findLastIndex((m) => m.role === "assistant");
                    if (idx === -1) return items;
                    const target = items[idx];
                    const next = [...items];
                    next[idx] = {
                      ...target,
                      metrics: { ...target.metrics, interruptedMs: val.elapsed_ms },
                    };
                    return next;
                  });
                }
              }
            }
          } else if (["stt_latency", "llm_latency", "tts_latency"].includes(type)) {
            const value = typeof val === "number" ? val : val?.value;
            if (!Number.isFinite(value) || value < 0) return;
            if (type === "stt_latency") {
              setLastSTT(Math.round(value * 1000));
              return;
            }
            if (type === "tts_latency") {
              setLastTTS(Math.round(value * 1000));
            }
            const field = type === "llm_latency" ? "llmLatency" : "ttsLatency";
            if (val?.response_id) {
              updateResponse(val.response_id, { [field]: value });
            } else {
              if (type === "llm_latency" && targetEngine === "live") {
                setLastTTFB(Math.round(value * 1000));
              }
              if (lastAssistantMetrics.current) {
                const mergedFallback: MessageMetrics = {
                  ...lastAssistantMetrics.current,
                  [field]: value,
                };
                lastAssistantMetrics.current = mergedFallback;
                if (mergedFallback.responseId) {
                  responseMetrics.current.set(mergedFallback.responseId, mergedFallback);
                }
                syncLastTtfb(mergedFallback);
              }
              setMessages((items) => {
                const last = items[items.length - 1];
                if (!last || last.role !== "assistant") return items;
                const mergedMetrics: MessageMetrics = {
                  ...last.metrics,
                  [field]: value,
                };
                const next = [...items];
                next[items.length - 1] = { ...last, metrics: mergedMetrics };
                return next;
              });
            }
          } else if (type === "usage") {
            if (val?.session_id && val.session_id !== activeSettings.sessionId) return;
            if (!val || !ledger.current.ingest(val)) return;
            const totals = ledger.current.snapshot(targetEngine, activeSettings.model);
            setTokenCount(totals.tokens);
            setTokenSplit(totals.split);
            setSessionCostUSD(totals.costUSD);
            setSessionCostBounds({
              minUSD: totals.minUSD,
              maxUSD: totals.maxUSD,
              estimated: totals.estimated,
              complete: totals.complete,
              incomplete: totals.incomplete,
            });
            if (val.response_id) {
              const cost = targetEngine === "live" ? calculateTurnCost(val.model ?? activeSettings.model, val) : null;
              updateResponse(val.response_id, {
                usage: val,
                turnCostUSD: cost?.totalUSD,
                costEstimated: cost?.estimated,
                costIncomplete: cost?.incomplete,
                costMinUSD: cost?.minUSD,
                costMaxUSD: cost?.maxUSD,
              });
            }
          } else if (type === "user_emotion") {
            if (val?.session_id && val.session_id !== activeSettings.sessionId) return;
            if (typeof val?.emoji !== "string" || typeof val?.title !== "string") return;
            const reading: UserEmotionReading = {
              emotion: typeof val.emotion === "string" ? val.emotion : "calm",
              emoji: val.emoji,
              title: val.title,
              confidence: Number.isFinite(val.confidence) ? Number(val.confidence) : 0,
              interim: Boolean(val.interim),
              latencyMs: Number.isFinite(val.latency_ms) ? Math.max(0, Math.round(Number(val.latency_ms))) : 0,
              inputTokens: Number.isFinite(val.input_tokens) ? Math.max(0, Math.round(Number(val.input_tokens))) : 0,
              model: typeof val.model === "string" ? val.model : "gemini-decision-1",
              seq: typeof val.seq === "number" ? val.seq : undefined,
              utteranceId: typeof val.utterance_id === "number" ? val.utterance_id : undefined,
            };
            setLiveEmotion(reading);
            setEmotionStats((prev) => ({
              count: prev.count + 1,
              totalInputTokens: prev.totalInputTokens + reading.inputTokens,
              lastLatencyMs: reading.latencyMs,
            }));
            if (userTurnAwaitingFinalEmotion.current) {
              if (!reading.interim) {
                userTurnAwaitingFinalEmotion.current = false;
                pendingUserEmotion.current = null;
              }
              setMessages((items) => {
                const idx = items.findLastIndex((m) => m.role === "user");
                if (idx === -1) return items;
                const target = items[idx];
                const next = [...items];
                next[idx] = {
                  ...target,
                  metrics: { ...target.metrics, userEmotion: reading },
                };
                return next;
              });
            } else {
              pendingUserEmotion.current = reading;
            }
          }
        },
        onPartialUser: (text) => {
          if (run.current === current) setPartialUser(text);
        },
        onTrack: (value) => {
          if (run.current === current) setTrack(value);
        },
        onLevel: (value) => {
          if (run.current !== current) return;
          const now = performance.now();
          if (now - lastLevelUpdateAt.current >= 70 || value === 0) {
            lastLevelUpdateAt.current = now;
            publishAudioLevel(value);
          }
        },
        onLatency: (value) => {
          if (run.current === current) setLatency(value);
        },
        onAvatarVideo: (chunkB64, isInit, seq, hasAudio, tfdt) => {
          if (run.current === current) avatarStream.pushChunk(chunkB64, isInit, seq, hasAudio, tfdt);
        },
        onAvatarInterrupted: () => {
          if (run.current === current) avatarStream.flushOnInterrupt();
        },
        onAvatarFallback: (fallbackAvatar, reason, code) => {
          if (run.current === current) setAvatarFallbackNotice({ fallbackAvatar, reason, code });
        },
        onVoiceFallback: (fallbackVoice, reason, code) => {
          if (run.current === current) setVoiceFallbackNotice({ fallbackVoice, reason, code });
        },
        onError: (text) => {
          if (run.current === current) setError(text);
        },
        onDisconnected: () => {
          if (run.current !== current) return;
          setPhase("idle");
          setTrack(null);
          publishAudioLevel(0);
          setMuted(false);
          setPartialUser("");
          session.current = null;
          starting.current = false;
          avatarStream.reset();
        },
      });
      if (run.current !== current) {
        await live.disconnect();
        return;
      }
      session.current = live;
      live.setMic(!mutedRef.current);
      live.setSound?.(soundRef.current);
      await live.connect();
      if (run.current === current) {
        live.setMic(!mutedRef.current);
        live.setSound?.(soundRef.current);
      }
      if (run.current === current && callStartedAt.current === null) {
        callStartedAt.current = Date.now();
      }
    } catch (e) {
      if (run.current !== current) return;
      const message = e instanceof Error ? e.message : "Unable to connect to your backend.";
      await endSession();
      setError(message);
    }
  };

  const toggleSound = useCallback(() => {
    if (sound) {
      stopVoiceSample();
    }
    setSound((value) => !value);
  }, [sound, stopVoiceSample]);

  const resetToSetup = () => {
    if (active) return;
    resetConversation();
  };

  const update = useCallback((key: keyof SessionSettings, value: string) => {
    setSettings((current) => {
      const next = { ...current, [key]: value };
      return {
        ...next,
        ...((key === "voice" && value !== "Custom-Key") || (key === "ttsModel" && value !== "google-tts") ? { customVoiceKey: "" } : {}),
        ...(key === "ttsModel" ? { voice: reconcileVoiceForEngine(next, current.engine) } : {}),
        ...(key === "customVoiceAudio" && value ? { model: "gemini-3.8-live" } : {}),
      };
    });
  }, []);

  const updateBool = useCallback((key: keyof SessionSettings, value: boolean) => {
    setSettings((current) => ({ ...current, [key]: value }));
  }, []);

  const updateNumber = useCallback((key: keyof SessionSettings, value: number) => {
    setSettings((current) => ({ ...current, [key]: value }));
  }, []);

  const copyTranscript = async () => {
    try {
      await navigator.clipboard.writeText(
        messages.map((m) => `${m.role === "user" ? "You" : persona.agentName}: ${m.text}`).join("\n\n")
      );
      setCopied(true);
      const timerId = setTimeout(() => {
        setCopied(false);
        timers.current = timers.current.filter((id) => id !== timerId);
      }, 1800);
      timers.current.push(timerId);
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

  const applyCustomAvatarAndStart = async (dataUrl: string) => {
    await startBackend("live", {
      engine: "live",
      avatarEnabled: true,
      avatarName: "custom",
      model: "gemini-3.8-live",
      avatarCustomImage: dataUrl,
    });
  };

  return {
    // state
    settings, phase, source, messages, elapsed, muted, sound, error, copied,
    latency, track, partialUser, settingsOpen, showInlineEditor,
    playingSample, subscribeAudioLevel, getAudioLevel,
    turnCount, lastSTT, lastTTFB, lastTTS, tokenCount, tokenSplit, sessionCostUSD, sessionCostBounds, cascadeCost, interruptCount,
    liveEmotion, emotionStats,
    compressionEvent, dismissCompressionToast, triggerCompressionToast,
    toolInjection, dismissToolInjection,
    avatarStream, avatarFallbackNotice, setAvatarFallbackNotice, voiceFallbackNotice, setVoiceFallbackNotice,
    // phase tracking & booking
    currentPhase, visitedPhases, phaseDirective, phaseDelivery, callSlots, confirmedBooking,
    // setters the views drive directly
    setMuted, setError, setSettingsOpen, setShowInlineEditor,
    // refs
    session, audio, transcript, followTranscript,
    // derived
    active, persona, custom, engineName, phaseLabel, duration, reduced,
    // actions
    endSession, choosePersona, chooseEngine, startBackend, applyCustomAvatarAndStart, toggleSound,
    toggleVoiceSample, stopVoiceSample, resetToSetup,
    update, updateBool, updateNumber, copyTranscript,
  };
}


export type VoiceStudio = ReturnType<typeof useVoiceSession>;
