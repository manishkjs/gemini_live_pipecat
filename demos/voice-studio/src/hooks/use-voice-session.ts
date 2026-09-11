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
import { calculateTurnCost } from "@/lib/pricing";
import type { Message, Phase } from "@/lib/studio-types";

/**
 * Owns a voice conversation: connection lifecycle, transcript, and the
 * per-turn telemetry the studio displays. The components below it are
 * presentational -- they read this and call back into it.
 */
export function useVoiceSession() {
  // Minted once per browser tab so this demoer's logs and latency percentiles
  // stay separate from anyone else connected to the same backend.
  const [settings, setSettings] = useState<SessionSettings>({ ...DEFAULT_SETTINGS, sessionId: newSessionId() });
  const [phase, setPhase] = useState<Phase>("idle");
  const [source, setSource] = useState<"preview" | "backend" | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [muted, setMuted] = useState(false);
  const [sound, setSound] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [complete, setComplete] = useState(false);
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
  const [sessionCostUSD, setSessionCostUSD] = useState<number>(0);
  const [interruptCount, setInterruptCount] = useState(0);

  const customInstructions = useRef("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const session = useRef<LiveSession | null>(null);
  const run = useRef(0);
  const soundRef = useRef(sound);
  const audio = useRef<HTMLAudioElement | null>(null);
  const transcript = useRef<HTMLDivElement | null>(null);
  const followTranscript = useRef(true);
  const reduced = useReducedMotion();
  const active = phase !== "idle";
  const persona = getPersona(settings.personaId);
  const custom = persona.id === "custom";
  const engineName = settings.engine === "live" ? "Gemini Live" : "Cascade";
  soundRef.current = sound;

  useEffect(() => {
    // Tear the session down if the tab navigates away mid-call; a dangling
    // websocket keeps the backend billing audio nobody is listening to.
    return () => {
      run.current++;
      timers.current.forEach(clearTimeout);
      window.speechSynthesis?.cancel();
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
        metrics,
      },
    ]);
  }, []);

  const endSession = useCallback(async () => {
    run.current++;
    timers.current.forEach(clearTimeout);
    timers.current = [];
    window.speechSynthesis?.cancel();
    const current = session.current;
    session.current = null;
    setPhase("idle");
    setTrack(null);
    setMuted(false);
    setPartialUser("");
    if (current) await current.disconnect();
  }, []);

  const resetConversation = () => {
    setError("");
    setMessages([]);
    setElapsed(0);
    setComplete(false);
    setLatency(null);
    setSource(null);
    setCopied(false);
    setTurnCount(0);
    setLastSTT(null);
    setLastTTFB(null);
    setLastTTS(null);
    setTokenCount(0);
    setSessionCostUSD(0);
    setInterruptCount(0);
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
    resetConversation();
  };

  const chooseEngine = (value: string) => {
    if (active) return;
    setSettings((current) => ({ ...current, engine: value as Engine }));
    resetConversation();
  };

  const startPreview = () => {
    resetConversation();
    setSource("preview");
    setPhase("thinking");
    const current = ++run.current;
    const playTurn = (index: number) => {
      if (run.current !== current) return;
      const item = persona.sample[index];
      if (!item) {
        setPhase("idle");
        setComplete(true);
        return;
      }
      setPhase(item.role === "user" ? "listening" : "speaking");
      addMessage(item.role, item.text);
      let finished = false;
      let fallback: ReturnType<typeof setTimeout>;
      const next = () => {
        if (finished || run.current !== current) return;
        finished = true;
        clearTimeout(fallback);
        setPhase("thinking");
        timers.current.push(setTimeout(() => playTurn(index + 1), 500));
      };
      if (soundRef.current && "speechSynthesis" in window) {
        const speech = new SpeechSynthesisUtterance(item.text);
        speech.lang = settings.language || "hi-IN";
        speech.rate = 1.04;
        speech.pitch = item.role === "user" ? 0.9 : 1.05;
        speech.onend = next;
        speech.onerror = next;
        fallback = setTimeout(() => {
          window.speechSynthesis.cancel();
          next();
        }, item.duration + 8000);
        timers.current.push(fallback);
        window.speechSynthesis.speak(speech);
      } else {
        fallback = setTimeout(next, item.duration);
        timers.current.push(fallback);
      }
    };
    playTurn(0);
  };

  const startBackend = async (engineOverride?: Engine) => {
    const targetEngine = engineOverride || settings.engine;
    const targetBackendUrl = settings.backendUrl?.trim() || getDefaultBackendUrl();
    const activeSettings: SessionSettings = {
      ...settings,
      engine: targetEngine,
      backendUrl: targetBackendUrl,
    };
    if (engineOverride && engineOverride !== settings.engine) {
      setSettings((current) => ({ ...current, engine: engineOverride }));
    }
    setSettingsOpen(false);
    resetConversation();
    setSource("backend");
    setPhase("connecting");
    const current = ++run.current;
    try {
      const live = await createLiveSession(activeSettings, {
        onPhase: (value) => {
          if (run.current === current) setPhase(value);
        },
        onMessage: (role, text, append, metrics) => {
          if (run.current !== current) return;
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
          if (append) {
            setMessages((items) => {
              const last = items.at(-1);
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
                return [...items.slice(0, -1), { ...last, text: last.text + separator + text, metrics: mergedMetrics }];
              }
              return [
                ...items,
                {
                  id: crypto.randomUUID(),
                  role,
                  text,
                  time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
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
          if (type === "turn_complete") {
            setTurnCount((c) => c + 1);
          } else if (type === "interruption") {
            setInterruptCount((c) => c + 1);
            if (val?.elapsed_ms !== undefined) {
              setMessages((items) => {
                const idx = items.findLastIndex((m) => m.role === "assistant");
                if (idx === -1) return items;
                const copy = [...items];
                copy[idx] = {
                  ...copy[idx],
                  metrics: { ...copy[idx].metrics, interruptedMs: val.elapsed_ms },
                };
                return copy;
              });
            }
          } else if (type === "stt_latency") {
            setLastSTT(Math.round(val * 1000));
            setMessages((items) => {
              const idx = items.findLastIndex((m) => m.role === "user");
              if (idx === -1) return items;
              const copy = [...items];
              copy[idx] = {
                ...copy[idx],
                metrics: { ...copy[idx].metrics, sttLatency: val },
              };
              return copy;
            });
          } else if (type === "llm_latency") {
            setLastTTFB(Math.round(val * 1000));
            setMessages((items) => {
              const idx = items.findLastIndex((m) => m.role === "assistant");
              if (idx === -1) return items;
              const copy = [...items];
              copy[idx] = {
                ...copy[idx],
                metrics: { ...copy[idx].metrics, llmLatency: val },
              };
              return copy;
            });
          } else if (type === "tts_latency") {
            setLastTTS(Math.round(val * 1000));
            setMessages((items) => {
              const idx = items.findLastIndex((m) => m.role === "assistant");
              if (idx === -1) return items;
              const copy = [...items];
              copy[idx] = {
                ...copy[idx],
                metrics: { ...copy[idx].metrics, ttsLatency: val },
              };
              return copy;
            });
          } else if (type === "usage") {
            if (val?.total_token_count) {
              setTokenCount((c) => c + val.total_token_count);
            }
            const turnCost = val?.turnCostUSD ?? (targetEngine === "live" ? calculateTurnCost(settings.model, val)?.totalUSD : undefined);
            if (turnCost) {
              setSessionCostUSD((c) => c + turnCost);
            }
            setMessages((items) => {
              const idx = items.findLastIndex((m) => m.role === "assistant");
              if (idx === -1) return items;
              const copy = [...items];
              copy[idx] = {
                ...copy[idx],
                metrics: { ...copy[idx].metrics, usage: val, turnCostUSD: turnCost ?? copy[idx].metrics?.turnCostUSD },
              };
              return copy;
            });
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
    idle: complete ? "Preview complete" : messages.length ? "Session ended" : "Ready to start",
    connecting: "Connecting…",
    listening: source === "preview" ? "You are speaking" : muted ? "Microphone muted" : "Listening",
    thinking: "Thinking",
    speaking: `${persona.agentName} is speaking`,
  }[phase];

  const duration = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;

  return {
    // state
    settings, phase, source, messages, elapsed, muted, sound, error, copied, complete,
    latency, track, partialUser, settingsOpen, showInlineEditor,
    turnCount, lastSTT, lastTTFB, lastTTS, tokenCount, sessionCostUSD, interruptCount,
    // setters the views drive directly
    setMuted, setError, setSettingsOpen, setShowInlineEditor,
    // refs
    session, audio, transcript, followTranscript,
    // derived
    active, persona, custom, engineName, phaseLabel, duration, reduced,
    // actions
    endSession, choosePersona, chooseEngine, startBackend, toggleSound,
    update, updateBool, updateNumber, copyTranscript,
    // Scripted persona playback. No control currently starts it -- the entry
    // point was dropped in a UI pass -- but the transcript still renders the
    // `source === "preview"` states, so the path is kept intact.
    startPreview,
  };
}

export type VoiceStudio = ReturnType<typeof useVoiceSession>;
