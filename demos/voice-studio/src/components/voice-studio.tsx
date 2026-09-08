"use client";

import { useCallback, useEffect, useRef, useState, type ComponentType, type CSSProperties } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  BookOpen,
  ChartLine,
  Check,
  Coffee,
  Copy,
  Heart,
  Layers3,
  MessageSquare,
  Mic,
  MicOff,
  Radio,
  Settings2,
  SlidersHorizontal,
  Square,
  Volume2,
  VolumeX,
  Wallet,
  X,
  Zap,
  Globe2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  DEFAULT_SETTINGS,
  LANGUAGE_OPTIONS,
  LIVE_MODELS,
  CASCADE_STT_MODELS,
  CASCADE_LLM_MODELS,
  CASCADE_TTS_MODELS,
  GEMINI_VOICES,
  CHIRP_HD_VOICES,
  getDefaultBackendUrl,
  type Engine,
  type SessionSettings,
} from "@/lib/voice-session";
import { PERSONAS, getPersona, type Persona, type PersonaId } from "@/lib/personas";
import { createLiveSession, type LiveSession, type MessageMetrics } from "@/lib/pipecat-session";
import ObservabilityDrawer from "./observability-drawer";
import "./voice-studio.css";

type Phase = "idle" | "connecting" | "listening" | "thinking" | "speaking";
type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  time: string;
  metrics?: MessageMetrics;
};
type WaveProps = {
  audioTrack: MediaStreamTrack | null;
  isThinking: boolean;
  color1: string;
  color2: string;
  backgroundColor: string;
  rotationEnabled: boolean;
  numBars: number;
  sensitivity: number;
};
const icons = {
  "debt-collector": Wallet,
  "reservation-agent": Coffee,
  storyteller: BookOpen,
  "ai-companion": Heart,
  custom: SlidersHorizontal,
};

function PersonaAvatar({ persona, className = "" }: { persona: Persona; className?: string }) {
  const [failed, setFailed] = useState(false);
  const Icon = icons[persona.id];
  return (
    <span className={`persona-avatar ${className}`}>
      {persona.portrait && !failed ? (
        <img
          src={persona.portrait}
          alt={`AI-generated portrait of ${persona.agentName}`}
          width={128}
          height={128}
          decoding="async"
          onError={() => setFailed(true)}
        />
      ) : (
        <Icon size={22} aria-hidden="true" />
      )}
    </span>
  );
}

function Picker({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly (readonly [string, string])[];
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const id = label.toLowerCase().replaceAll(" ", "-");
  return (
    <div className="field">
      <label id={`${id}-label`}>{label}</label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger aria-labelledby={`${id}-label`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper">
          {options.map(([v, l]) => (
            <SelectItem value={v} key={v}>
              {l}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export default function VoiceStudio({ sourceDownload = false }: { sourceDownload?: boolean }) {
  const [settings, setSettings] = useState<SessionSettings>({ ...DEFAULT_SETTINGS });
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
  const [Wave, setWave] = useState<ComponentType<WaveProps> | null>(null);
  const [track, setTrack] = useState<MediaStreamTrack | null>(null);
  const [audioAvailable, setAudioAvailable] = useState(true);
  const [partialUser, setPartialUser] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [observabilityOpen, setObservabilityOpen] = useState(false);

  // Live session metric counters
  const [turnCount, setTurnCount] = useState(0);
  const [lastSTT, setLastSTT] = useState<number | null>(null);
  const [lastTTFB, setLastTTFB] = useState<number | null>(null);
  const [lastTTS, setLastTTS] = useState<number | null>(null);
  const [tokenCount, setTokenCount] = useState(0);
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
    let cancelled = false;
    import("@pipecat-ai/voice-ui-kit")
      .then(({ CircularWaveform }) => {
        if (!cancelled) setWave(() => CircularWaveform as ComponentType<WaveProps>);
      })
      .catch(() => {
        /* Accessible static fallback */
      });
    setAudioAvailable("speechSynthesis" in window);
    return () => {
      cancelled = true;
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
    setInterruptCount(0);
    followTranscript.current = true;
  };

  const choosePersona = (value: string) => {
    if (active) return;
    const p = getPersona(value);
    if (settings.personaId === "custom") customInstructions.current = settings.instructions;
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
            if (metrics?.usage?.total_token_count) {
              setTokenCount((c) => c + (metrics.usage?.total_token_count || 0));
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
            setMessages((items) => {
              const idx = items.findLastIndex((m) => m.role === "assistant");
              if (idx === -1) return items;
              const copy = [...items];
              copy[idx] = {
                ...copy[idx],
                metrics: { ...copy[idx].metrics, usage: val },
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

  return (
    <main className="studio-shell" style={{ "--persona-color": persona.color } as CSSProperties}>
      <audio ref={audio} autoPlay muted={!sound} />

      {/* Header with Observability and Settings (Original UI removed) */}
      <header className="studio-header">
        <a href="/" className="studio-brand" aria-label="Voice Studio home">
          <span className="brand-mark">
            <AudioLines size={22} />
          </span>
          Voice<span className="brand-light">Studio</span>
          <span className="demo-tag">DEMO</span>
        </a>
        <div className="header-actions">
          <Button
            variant="outline"
            className="header-tool"
            onClick={() => setObservabilityOpen(true)}
            title="Open live telemetry and observability dashboard"
          >
            <ChartLine size={16} />
            <span>Observability</span>
            {turnCount > 0 && <span className="obs-badge">{turnCount}</span>}
          </Button>
          <Button
            className="header-tool"
            variant="outline"
            onClick={() => setSettingsOpen(true)}
            disabled={active}
            aria-label="Session settings"
          >
            <Settings2 size={16} />
            <span>Settings</span>
          </Button>
        </div>
      </header>

      {/* 01 / CHOOSE YOUR PERSONA */}
      <section className="persona-section" aria-labelledby="persona-heading">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">01 / CHOOSE YOUR PERSONA</span>
            <h1 id="persona-heading">Who will you talk to?</h1>
          </div>
          <p>Pick an Indian persona and converse natively in Hindi or Indian regional languages with Gemini Live or Cascade.</p>
        </div>
        <RadioGroup
          aria-labelledby="persona-heading"
          value={settings.personaId}
          onValueChange={choosePersona}
          className="persona-grid"
          disabled={active}
        >
          {PERSONAS.map((item) => {
            const isSelected = settings.personaId === item.id;
            return (
              <label
                key={item.id}
                htmlFor={item.id}
                className={`persona-card ${item.id === "custom" ? "custom-card" : ""} ${isSelected ? "selected" : ""} ${
                  active ? "locked" : ""
                }`}
                style={{ "--card-color": item.color } as CSSProperties}
              >
                <div className="persona-card-top">
                  <PersonaAvatar key={item.id} persona={item} className="card-portrait" />
                  <RadioGroupItem
                    id={item.id}
                    value={item.id}
                    aria-label={item.id === "custom" ? item.name : `${item.agentName}, ${item.name}`}
                  />
                </div>
                <strong>{item.id === "custom" ? item.name : item.agentName}</strong>
                {item.id !== "custom" && <span className="persona-role">{item.name}</span>}
                <span className="persona-description">{item.description}</span>
                {isSelected && !active && (
                  <div className="card-quick-actions">
                    <span className="card-active-pill">Selected</span>
                  </div>
                )}
              </label>
            );
          })}
        </RadioGroup>
      </section>

      {/* 02 / ENGINE & 03 / LANGUAGE TOOLBAR */}
      <div className="workspace-toolbar">
        <div className="engine-choice">
          <span className="eyebrow">02 / CHOOSE YOUR ENGINE</span>
          <Tabs value={settings.engine} onValueChange={chooseEngine}>
            <TabsList aria-label="Voice engine" className="engine-tabs">
              <TabsTrigger value="live" disabled={active}>
                <Radio size={16} />Gemini Live
              </TabsTrigger>
              <TabsTrigger value="cascade" disabled={active}>
                <Layers3 size={16} />Cascade
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        <div className="language-choice">
          <span className="eyebrow">03 / LANGUAGE</span>
          <Select
            value={settings.language}
            onValueChange={(val) => update("language", val)}
            disabled={active}
          >
            <SelectTrigger className="language-select-trigger" aria-label="Select session language">
              <Globe2 size={15} />
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper">
              {LANGUAGE_OPTIONS.map(([v, l]) => (
                <SelectItem value={v} key={v}>
                  {l}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <p className="engine-description">
          {settings.engine === "live"
            ? "Native 2-way audio with bidirectional streaming & low-latency voice."
            : "Speech recognition (STT) → language model (LLM) → voice synthesis (TTS)."}
        </p>
      </div>

      {/* CONVERSATION STAGE + TRANSCRIPT */}
      <div className="session-grid">
        <section className={`conversation-stage phase-${phase}`} aria-labelledby="agent-heading">
          <div className="stage-top">
            <span className={`connection-state ${active ? "is-active" : ""}`}>
              <span className="status-dot" />
              {phaseLabel}
            </span>
          </div>

          <div className="agent-stage">
            <div className="wave-container" aria-hidden="true">
              {Wave ? (
                <Wave
                  audioTrack={source === "backend" ? track : null}
                  isThinking={!reduced && active && (source === "preview" || phase === "thinking" || phase === "connecting")}
                  color1={persona.color}
                  color2="#82b7a6"
                  backgroundColor="transparent"
                  rotationEnabled={!reduced && active}
                  numBars={64}
                  sensitivity={1.3}
                />
              ) : (
                <div className="wave-fallback" />
              )}
              <div className="wave-core">
                <PersonaAvatar key={persona.id} persona={persona} className="stage-portrait" />
              </div>
            </div>
            <h2 id="agent-heading">{custom ? "Your agent. Your rules." : `Meet ${persona.agentName}.`}</h2>
            <p>{custom ? "A blank canvas for your voice app" : persona.name}</p>
          </div>

          <div className="your-role">
            <span className="eyebrow">{custom ? "CUSTOM SESSION" : "YOUR ROLE"}</span>
            <p>{persona.userRole}</p>
          </div>

          <div className="session-actions">
            {active ? (
              <Button className="primary-call end-call" onClick={() => void endSession()}>
                <Square size={15} fill="currentColor" />End Session
              </Button>
            ) : (
              <div className="engine-action-buttons">
                <Button
                  className={`primary-call call-live ${settings.engine === "live" ? "highlight-engine" : ""}`}
                  onClick={() => void startBackend("live")}
                >
                  <Mic size={18} />
                  <span>Talk via <strong>Gemini Live</strong></span>
                </Button>
                <Button
                  variant="outline"
                  className={`secondary-call call-cascade ${settings.engine === "cascade" ? "highlight-engine" : ""}`}
                  onClick={() => void startBackend("cascade")}
                >
                  <Layers3 size={17} />
                  <span>Talk via <strong>Cascade</strong></span>
                </Button>
              </div>
            )}
            <div className="audio-controls">
              <Button
                variant="outline"
                size="icon"
                aria-label={muted ? "Unmute microphone" : "Mute microphone"}
                aria-pressed={muted}
                disabled={!active || source !== "backend" || phase === "connecting"}
                onClick={() => {
                  session.current?.setMic(muted);
                  setMuted(!muted);
                }}
              >
                {muted ? <MicOff size={17} /> : <Mic size={17} />}
              </Button>
              <span>{active ? "Live audio active · Interrupt anytime" : "Microphone active on start"}</span>
              <Button
                variant="outline"
                size="icon"
                aria-label={sound ? "Mute speaker" : "Enable speaker"}
                aria-pressed={!sound}
                onClick={toggleSound}
              >
                {sound ? <Volume2 size={17} /> : <VolumeX size={17} />}
              </Button>
            </div>
          </div>
          <p className="preview-note">
            {active
              ? `Connected via ${engineName} with ${persona.agentName}. Speak into your microphone.`
              : `Ready to talk. Choose Gemini Live or Cascade to speak with ${custom ? "your agent" : persona.agentName}.`}
          </p>
        </section>

        {/* TRANSCRIPT PANEL WITH LATENCY BADGES & TICKER */}
        <section className="transcript-panel" aria-labelledby="transcript-heading">
          <div className="transcript-heading">
            <div className="transcript-title-row">
              <MessageSquare size={18} />
              <h2 id="transcript-heading">Conversation</h2>
              <span className="transcript-badge">{source === "preview" ? "SCRIPTED PREVIEW" : engineName.toUpperCase()}</span>
              {active && (
                <div className="live-metrics-ticker">
                  <span className="ticker-pill">Turns: <strong>{turnCount}</strong></span>
                  {lastSTT !== null && <span className="ticker-pill">STT: <strong>{lastSTT}ms</strong></span>}
                  {lastTTFB !== null && <span className="ticker-pill">TTFB: <strong>{lastTTFB}ms</strong></span>}
                  {tokenCount > 0 && <span className="ticker-pill">Tokens: <strong>{tokenCount}</strong></span>}
                </div>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => void copyTranscript()}
              disabled={!messages.length}
              aria-label={copied ? "Transcript copied" : "Copy transcript"}
            >
              {copied ? <Check size={17} /> : <Copy size={17} />}
            </Button>
          </div>

          <div
            className="transcript-scroll"
            ref={transcript}
            onScroll={(e) => {
              const el = e.currentTarget;
              followTranscript.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
            }}
            role={messages.length ? "log" : "region"}
            aria-label="Conversation transcript"
            aria-live={messages.length ? "polite" : "off"}
            aria-relevant="additions text"
          >
            <AnimatePresence mode="wait">
              {!messages.length ? (
                <motion.div
                  key={persona.id}
                  className="transcript-empty"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  <PersonaAvatar key={persona.id} persona={persona} className="empty-portrait" />
                  {custom ? (
                    <>
                      <h3>Start with your own instructions.</h3>
                      <p>Set the role, tone and goal for your agent. Both engines use the instructions you enter here.</p>
                      <div className="custom-prompt field">
                        <label htmlFor="custom-instructions">
                          System instructions <span className="optional-label">optional</span>
                        </label>
                        <Textarea
                          id="custom-instructions"
                          value={settings.instructions}
                          onChange={(e) => update("instructions", e.target.value)}
                          disabled={active}
                          placeholder="You are a helpful voice assistant. Keep replies brief, ask one question at a time, and…"
                          maxLength={1000}
                          rows={5}
                        />
                        <p className="field-hint">
                          {settings.instructions
                            ? `${settings.instructions.length}/1000 characters`
                            : "Leave blank to use your backend’s existing system instructions."}
                        </p>
                      </div>
                    </>
                  ) : (
                    <>
                      <h3>Step into the conversation.</h3>
                      <p>
                        {phase === "connecting"
                          ? `Connecting you with ${persona.agentName}…`
                          : `Select Gemini Live or Cascade on the left to start talking directly with ${persona.agentName}.`}
                      </p>
                      <div className="opening-cue">
                        <span className="eyebrow">TRY SAYING</span>
                        <blockquote>“{persona.opening}”</blockquote>
                      </div>
                      <div className="journey">
                        <span className="eyebrow">DEMO FOCUS</span>
                        <ol>
                          {persona.journey.map((step, i) => (
                            <li key={step}>
                              <span>{i + 1}</span>
                              {step}
                              {i < persona.journey.length - 1 && <ArrowRight size={13} className="journey-arrow" />}
                            </li>
                          ))}
                        </ol>
                      </div>
                    </>
                  )}
                </motion.div>
              ) : (
                <div className="message-list" key="messages">
                  {messages.map((message) => (
                    <motion.article
                      layout={!reduced}
                      initial={{ opacity: 0, y: reduced ? 0 : 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      key={message.id}
                      className={`message message-${message.role}`}
                    >
                      <span className="message-avatar">
                        {message.role === "assistant" ? (
                          <PersonaAvatar key={persona.id} persona={persona} className="transcript-portrait" />
                        ) : (
                          <Mic size={15} />
                        )}
                      </span>
                      <div className="message-content">
                        <div className="message-meta">
                          <strong>{message.role === "assistant" ? persona.agentName : "You"}</strong>
                          <time>{message.time}</time>
                        </div>
                        <p>{message.text}</p>

                        {/* Latency & Telemetry Badges */}
                        {message.role === "user" && message.metrics?.sttLatency !== undefined && (
                          <div className="bubble-latency stt-badge">
                            <Zap size={11} />
                            <span>STT: {Math.round(message.metrics.sttLatency * 1000)}ms</span>
                          </div>
                        )}

                        {message.role === "assistant" && (
                          <div className="bubble-latency-group">
                            {settings.engine === "live" ? (
                              message.metrics?.llmLatency !== undefined ? (
                                <div className="bubble-latency live-badge">
                                  <Zap size={11} />
                                  <span>Live TTFB: {Math.round(message.metrics.llmLatency * 1000)}ms</span>
                                  {message.metrics.usage?.total_token_count ? (
                                    <span className="token-tag">{message.metrics.usage.total_token_count} tok</span>
                                  ) : null}
                                </div>
                              ) : null
                            ) : (
                              (message.metrics?.sttLatency !== undefined ||
                                message.metrics?.llmLatency !== undefined ||
                                message.metrics?.ttsLatency !== undefined) ? (
                                <div className="bubble-latency cascade-badge">
                                  {message.metrics.sttLatency !== undefined && (
                                    <span>STT: {Math.round(message.metrics.sttLatency * 1000)}ms</span>
                                  )}
                                  {message.metrics.sttLatency !== undefined &&
                                    (message.metrics.llmLatency !== undefined || message.metrics.ttsLatency !== undefined) && (
                                      <span className="sep">|</span>
                                    )}
                                  {message.metrics.llmLatency !== undefined && (
                                    <span>⚡ LLM TTFB: {Math.round(message.metrics.llmLatency * 1000)}ms</span>
                                  )}
                                  {message.metrics.ttsLatency !== undefined && <span className="sep">|</span>}
                                  {message.metrics.ttsLatency !== undefined && (
                                    <span>TTS: {Math.round(message.metrics.ttsLatency * 1000)}ms</span>
                                  )}
                                  {message.metrics.usage?.total_token_count ? (
                                    <span className="token-tag">{message.metrics.usage.total_token_count} tok</span>
                                  ) : null}
                                </div>
                              ) : null
                            )}
                            {message.metrics?.interruptedMs !== undefined && (
                              <div className="bubble-latency interrupted-badge">
                                ⚡ Interrupted after {Math.round(message.metrics.interruptedMs)}ms
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </motion.article>
                  ))}
                  {partialUser && <div className="partial-message">{partialUser}</div>}
                  {active && phase === "thinking" && (
                    <div className="thinking-indicator">
                      <span />
                      <span />
                      <span />
                      <span className="sr-only">{persona.agentName} is thinking</span>
                    </div>
                  )}
                  {complete && (
                    <div className="preview-complete">
                      <Check size={16} />
                      <span>Session complete. Ready to talk again?</span>
                    </div>
                  )}
                </div>
              )}
            </AnimatePresence>
          </div>

          <div className="transcript-footer">
            <span>
              <span className={`status-dot ${active ? "is-active" : ""}`} />
              {source === "preview"
                ? "Scripted persona preview · no API calls"
                : active
                ? `Live transcript · ${engineName}`
                : "Your conversation will appear here"}
            </span>
            <div>
              <span className="session-clock">{duration}</span>
              {latency !== null && (
                <span title="Measured from user transcript arrival to first response audio">
                  Response {(latency / 1000).toFixed(2)}s
                </span>
              )}
            </div>
          </div>
        </section>
      </div>

      <AnimatePresence>
        {error && (
          <motion.div className="error-banner" role="alert" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <span>{error}</span>
            <Button variant="ghost" size="icon" aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={16} />
            </Button>
          </motion.div>
        )}
      </AnimatePresence>

      <footer className="studio-footer">
        <span>
          <AudioLines size={15} /> Voice Studio <span className="footer-separator">/</span> Fictional agents · Indian languages
        </span>
        <div>
          {sourceDownload && (
            <a href="/voice-studio-source.zip" download>
              Download source <ArrowUpRight size={14} />
            </a>
          )}
          <a href="https://github.com/manishkjs/gemini_live_pipecat" target="_blank" rel="noreferrer">
            View project <ArrowUpRight size={14} />
          </a>
        </div>
      </footer>

      {/* ALL ENGINE CONFIGURATION OPTIONS IN SETTINGS DIALOG */}
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="studio-dialog">
          <DialogHeader>
            <DialogTitle>Session Configuration: {engineName}</DialogTitle>
            <DialogDescription>
              {persona.name} · {engineName}. All parameters of Google Cloud Speech and Gemini Live are configurable below.
            </DialogDescription>
          </DialogHeader>

          <div className="dialog-fields">
            {/* GEMINI LIVE CONFIGURATION */}
            {settings.engine === "live" && (
              <>
                <div className="settings-pair">
                  <Picker
                    label="Voice"
                    value={settings.voice}
                    disabled={active}
                    onChange={(value) => update("voice", value)}
                    options={GEMINI_VOICES}
                  />
                  <Picker
                    label="Language"
                    value={settings.language}
                    disabled={active}
                    onChange={(value) => update("language", value)}
                    options={LANGUAGE_OPTIONS}
                  />
                </div>

                <Picker
                  label="Live Model"
                  value={settings.model}
                  disabled={active}
                  onChange={(value) => update("model", value)}
                  options={LIVE_MODELS}
                />

                <div className="settings-slider-field">
                  <div className="slider-label-row">
                    <label htmlFor="live-pace-slider">Speaking Rate (Pace)</label>
                    <span className="slider-val">{(settings.ttsPace ?? 1.0).toFixed(2)}x</span>
                  </div>
                  <input
                    id="live-pace-slider"
                    type="range"
                    min="0.25"
                    max="2.0"
                    step="0.05"
                    value={settings.ttsPace ?? 1.0}
                    disabled={active}
                    onChange={(e) => updateNumber("ttsPace", parseFloat(e.target.value))}
                    className="range-slider"
                  />
                </div>

                <div className="advanced-toggles">
                  <label className="toggle-label">
                    <input
                      type="checkbox"
                      checked={settings.tts ?? false}
                      disabled={active}
                      onChange={(e) => updateBool("tts", e.target.checked)}
                    />
                    <span>Use TTS for output modality</span>
                  </label>
                  <label className="toggle-label">
                    <input
                      type="checkbox"
                      checked={settings.vad ?? true}
                      disabled={active}
                      onChange={(e) => updateBool("vad", e.target.checked)}
                    />
                    <span>Voice Activity Detection (VAD)</span>
                  </label>
                  <label className="toggle-label">
                    <input
                      type="checkbox"
                      checked={settings.contextCompression ?? false}
                      disabled={active}
                      onChange={(e) => updateBool("contextCompression", e.target.checked)}
                    />
                    <span>Context Compression</span>
                  </label>
                  {settings.contextCompression && (
                    <div className="field trigger-tokens-field">
                      <label htmlFor="comp-tokens">Trigger Tokens Threshold</label>
                      <Input
                        id="comp-tokens"
                        type="number"
                        min={5000}
                        step={1000}
                        value={settings.contextCompressionTokens ?? 20000}
                        disabled={active}
                        onChange={(e) => updateNumber("contextCompressionTokens", parseInt(e.target.value, 10))}
                      />
                    </div>
                  )}
                </div>
              </>
            )}

            {/* CASCADE (STT-LLM-TTS) CONFIGURATION */}
            {settings.engine === "cascade" && (
              <>
                <div className="settings-pair">
                  <Picker
                    label="Speech Recognition (STT)"
                    value={settings.sttModel}
                    disabled={active}
                    onChange={(value) => update("sttModel", value)}
                    options={CASCADE_STT_MODELS}
                  />
                  <Picker
                    label="Language"
                    value={settings.language}
                    disabled={active}
                    onChange={(value) => update("language", value)}
                    options={LANGUAGE_OPTIONS}
                  />
                </div>

                <label className="toggle-label" style={{ marginBottom: "12px" }}>
                  <input
                    type="checkbox"
                    checked={settings.skipStt ?? false}
                    disabled={active}
                    onChange={(e) => updateBool("skipStt", e.target.checked)}
                  />
                  <span>Skip STT (Send audio directly to LLM)</span>
                </label>

                <Picker
                  label="Language Model (LLM)"
                  value={settings.llmModel}
                  disabled={active}
                  onChange={(value) => update("llmModel", value)}
                  options={CASCADE_LLM_MODELS}
                />

                <div className="settings-pair">
                  <Picker
                    label="Voice Model (TTS)"
                    value={settings.ttsModel}
                    disabled={active}
                    onChange={(value) => {
                      update("ttsModel", value);
                      if (value === "google-tts" && !settings.voice.includes("Chirp")) {
                        update("voice", "hi-IN-Chirp3-HD-Sulafat");
                      } else if (value !== "google-tts" && settings.voice.includes("Chirp")) {
                        update("voice", "Aoede");
                      }
                    }}
                    options={CASCADE_TTS_MODELS}
                  />
                  <Picker
                    label="Voice"
                    value={settings.voice}
                    disabled={active}
                    onChange={(value) => update("voice", value)}
                    options={settings.ttsModel === "google-tts" ? CHIRP_HD_VOICES : GEMINI_VOICES}
                  />
                </div>

                <div className="settings-slider-field">
                  <div className="slider-label-row">
                    <label htmlFor="cascade-pace-slider">Speaking Rate (Pace)</label>
                    <span className="slider-val">{(settings.ttsPace ?? 1.0).toFixed(2)}x</span>
                  </div>
                  <input
                    id="cascade-pace-slider"
                    type="range"
                    min="0.25"
                    max="2.0"
                    step="0.05"
                    value={settings.ttsPace ?? 1.0}
                    disabled={active}
                    onChange={(e) => updateNumber("ttsPace", parseFloat(e.target.value))}
                    className="range-slider"
                  />
                </div>
              </>
            )}

            {/* DYNAMIC TOOL DEFINITIONS (JSON) */}
            <div className="field">
              <label htmlFor="tools-json">Dynamic Tool Definitions (JSON)</label>
              <Textarea
                id="tools-json"
                value={settings.toolsJson ?? ""}
                onChange={(e) => update("toolsJson", e.target.value)}
                disabled={active}
                placeholder='[{"name": "get_weather", "description": "Get weather", "properties": {"city": {"type": "string"}}, "required": ["city"]}]'
                rows={3}
                style={{ fontFamily: "ui-monospace, monospace", fontSize: "12px" }}
              />
              <p className="field-hint">Optional OpenAPI tool definitions executed live during conversational turns.</p>
            </div>

            {/* SYSTEM / PERSONA INSTRUCTIONS */}
            <div className="field">
              <div className="instructions-label">
                <label htmlFor="instructions">{custom ? "System instructions" : "Persona instructions"}</label>
                {settings.instructions && (
                  <Button variant="ghost" size="sm" disabled={active} onClick={() => update("instructions", "")}>
                    {custom ? "Use backend default" : "Restore preset"}
                  </Button>
                )}
              </div>
              <Textarea
                id="instructions"
                placeholder={custom ? "Leave blank to use your backend’s existing system instructions." : persona.prompt}
                value={settings.instructions}
                onChange={(e) => update("instructions", e.target.value)}
                disabled={active}
                maxLength={1000}
                rows={4}
              />
              <p className="field-hint">
                {settings.instructions
                  ? `${settings.instructions.length}/1000 characters${custom ? "" : " · replaces the persona preset"}`
                  : custom
                  ? "Using your backend’s existing system instructions."
                  : `Using the ${persona.name} preset. Write here to customize it.`}
              </p>
            </div>

            {/* CUSTOM SERVER URL OVERRIDE */}
            <details className="advanced-url-toggle">
              <summary>Advanced: Custom Server URL (Optional)</summary>
              <div className="field" style={{ marginTop: "10px" }}>
                <Input
                  id="backend-url"
                  value={settings.backendUrl}
                  onChange={(e) => update("backendUrl", e.target.value)}
                  placeholder="http://localhost:7860"
                  disabled={active}
                  type="url"
                  autoComplete="off"
                />
                <p className="field-hint">
                  Defaults automatically to your backend on port 7860 or host origin. Override only if connecting to an external server.
                </p>
              </div>
            </details>
          </div>

          <div className="dialog-actions">
            <Button variant="outline" onClick={() => setSettingsOpen(false)}>
              Done
            </Button>
            <Button className="primary-call" disabled={active} onClick={() => void startBackend()}>
              <Mic size={16} />
              Start {engineName}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* THEMED OBSERVABILITY DRAWER */}
      <ObservabilityDrawer
        open={observabilityOpen}
        onClose={() => setObservabilityOpen(false)}
        backendUrl={settings.backendUrl?.trim() || getDefaultBackendUrl()}
      />
    </main>
  );
}
