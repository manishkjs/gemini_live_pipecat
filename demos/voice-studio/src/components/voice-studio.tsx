"use client";

import { useCallback, useEffect, useRef, useState, type ComponentType, type CSSProperties } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowRight, ArrowUpRight, AudioLines, BookOpen, ChartLine, Check, Coffee, Copy, Heart, Layers3, MessageSquare, Mic, MicOff, PanelsTopLeft, Play, Radio, RotateCcw, Settings2, SlidersHorizontal, Square, Volume2, VolumeX, Wallet, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { DEFAULT_SETTINGS, LANGUAGE_OPTIONS, buildBackendPageUrl, getDefaultBackendUrl, type Engine, type SessionSettings } from "@/lib/voice-session";
import { PERSONAS, getPersona, type Persona, type PersonaId } from "@/lib/personas";
import { createLiveSession, type LiveSession } from "@/lib/pipecat-session";
import "./voice-studio.css";

type Phase = "idle" | "connecting" | "listening" | "thinking" | "speaking";
type Message = { id: string; role: "user" | "assistant"; text: string; time: string };
type WaveProps = { audioTrack: MediaStreamTrack | null; isThinking: boolean; color1: string; color2: string; backgroundColor: string; rotationEnabled: boolean; numBars: number; sensitivity: number };
const icons = { "debt-collector": Wallet, "reservation-agent": Coffee, storyteller: BookOpen, "ai-companion": Heart, custom: SlidersHorizontal };


function PersonaAvatar({ persona, className = "" }: { persona: Persona; className?: string }) {
  const [failed, setFailed] = useState(false);
  const Icon = icons[persona.id];
  return <span className={`persona-avatar ${className}`}>{persona.portrait && !failed
    ? <img src={persona.portrait} alt={`AI-generated portrait of ${persona.agentName}`} width={128} height={128} decoding="async" onError={() => setFailed(true)} />
    : <Icon size={22} aria-hidden="true" />}</span>;
}

function Picker({ label, value, options, disabled, onChange }: { label: string; value: string; options: readonly (readonly [string, string])[]; disabled: boolean; onChange: (value: string) => void }) {
  const id = label.toLowerCase().replaceAll(" ", "-");
  return <div className="field"><label id={`${id}-label`}>{label}</label><Select value={value} onValueChange={onChange} disabled={disabled}><SelectTrigger aria-labelledby={`${id}-label`}><SelectValue /></SelectTrigger><SelectContent position="popper">{options.map(([v, l]) => <SelectItem value={v} key={v}>{l}</SelectItem>)}</SelectContent></Select></div>;
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
  let backendPages: { original: string; diagnostics: string } | null = null;
  try {
    const rawBackendUrl = settings.backendUrl?.trim() || getDefaultBackendUrl();
    backendPages = {
      original: buildBackendPageUrl(rawBackendUrl, "original"),
      diagnostics: buildBackendPageUrl(rawBackendUrl, "diagnostics"),
    };
  } catch { /* Page shortcuts fallback */ }
  soundRef.current = sound;

  useEffect(() => {
    let cancelled = false;
    import("@pipecat-ai/voice-ui-kit").then(({ CircularWaveform }) => {
      if (!cancelled) setWave(() => CircularWaveform as ComponentType<WaveProps>);
    }).catch(() => { /* Keep the accessible static fallback. */ });
    setAudioAvailable("speechSynthesis" in window);
    return () => { cancelled = true; run.current++; timers.current.forEach(clearTimeout); window.speechSynthesis?.cancel(); void session.current?.disconnect(); };
  }, []);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setElapsed(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, [active]);
  useEffect(() => {
    if (followTranscript.current && transcript.current) transcript.current.scrollTo({ top: transcript.current.scrollHeight, behavior: reduced ? "instant" : "smooth" });
  }, [messages, partialUser, reduced]);
  useEffect(() => {
    if (audio.current) { audio.current.srcObject = track ? new MediaStream([track]) : null; if (track) void audio.current.play().catch(() => setError("Audio playback was blocked. Use the speaker control to enable sound.")); }
  }, [track]);

  const addMessage = useCallback((role: Message["role"], text: string) => {
    setMessages(items => [...items, { id: crypto.randomUUID(), role, text, time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) }]);
  }, []);
  const endSession = useCallback(async () => {
    run.current++; timers.current.forEach(clearTimeout); timers.current = [];
    window.speechSynthesis?.cancel();
    const current = session.current; session.current = null;
    setPhase("idle"); setTrack(null); setMuted(false); setPartialUser("");
    if (current) await current.disconnect();
  }, []);
  const resetConversation = () => {
    setError(""); setMessages([]); setElapsed(0); setComplete(false); setLatency(null); setSource(null); setCopied(false); followTranscript.current = true;
  };
  const choosePersona = (value: string) => {
    if (active) return;
    const p = getPersona(value);
    if (settings.personaId === "custom") customInstructions.current = settings.instructions;
    setSettings(current => ({
      ...current,
      personaId: value as PersonaId,
      voice: p.defaultVoice || current.voice,
      instructions: value === "custom" ? customInstructions.current : "",
    }));
    resetConversation();
  };
  const chooseEngine = (value: string) => {
    if (active) return;
    setSettings(current => ({ ...current, engine: value as Engine })); resetConversation();
  };
  const startPreview = () => {
    resetConversation(); setSource("preview"); setPhase("thinking");
    const current = ++run.current;
    const playTurn = (index: number) => {
      if (run.current !== current) return;
      const item = persona.sample[index];
      if (!item) { setPhase("idle"); setComplete(true); return; }
      setPhase(item.role === "user" ? "listening" : "speaking"); addMessage(item.role, item.text);
      let finished = false;
      let fallback: ReturnType<typeof setTimeout>;
      const next = () => {
        if (finished || run.current !== current) return;
        finished = true; clearTimeout(fallback); setPhase("thinking");
        timers.current.push(setTimeout(() => playTurn(index + 1), 500));
      };
      if (soundRef.current && "speechSynthesis" in window) {
        const speech = new SpeechSynthesisUtterance(item.text);
        speech.lang = "en-IN"; speech.rate = 1.04; speech.pitch = item.role === "user" ? 0.9 : 1.05;
        speech.onend = next; speech.onerror = next;
        fallback = setTimeout(() => { window.speechSynthesis.cancel(); next(); }, item.duration + 8000);
        timers.current.push(fallback); window.speechSynthesis.speak(speech);
      } else { fallback = setTimeout(next, item.duration); timers.current.push(fallback); }
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
      setSettings(current => ({ ...current, engine: engineOverride }));
    }
    setSettingsOpen(false); resetConversation(); setSource("backend"); setPhase("connecting");
    const current = ++run.current;
    try {
      const live = await createLiveSession(activeSettings, {
        onPhase: value => { if (run.current === current) setPhase(value); },
        onMessage: (role, text, append) => {
          if (run.current !== current) return;
          if (role === "user") setPartialUser("");
          if (append) setMessages(items => {
            const last = items.at(-1);
            if (last?.role === "assistant") {
              // Cascade emits trimmed phrase chunks; Live preserves token whitespace.
              const separator = targetEngine === "cascade" && /\S$/.test(last.text) && /^[\p{L}\p{N}]/u.test(text) ? " " : "";
              return [...items.slice(0, -1), { ...last, text: last.text + separator + text }];
            }
            return [...items, { id: crypto.randomUUID(), role, text, time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) }];
          }); else addMessage(role, text);
        },
        onPartialUser: text => { if (run.current === current) setPartialUser(text); },
        onTrack: value => { if (run.current === current) setTrack(value); },
        onLevel: () => { /* Audio track drives the compact visualizer. */ },
        onLatency: value => { if (run.current === current) setLatency(value); },
        onError: text => { if (run.current === current) setError(text); },
        onDisconnected: () => {
          if (run.current !== current) return;
          setPhase("idle"); setTrack(null); setMuted(false); setPartialUser(""); session.current = null;
        },
      });
      if (run.current !== current) { await live.disconnect(); return; }
      session.current = live; await live.connect();
    } catch (e) {
      if (run.current !== current) return;
      const message = e instanceof Error ? e.message : "Unable to connect to your backend.";
      await endSession(); setError(message);
    }
  };
  const toggleSound = () => {
    setSound(value => !value);
    if (sound) window.speechSynthesis?.cancel();
    else if (audio.current && track) void audio.current.play().catch(() => setError("Your browser is blocking audio playback."));
  };
  const update = (key: keyof SessionSettings, value: string) => setSettings(current => ({ ...current, [key]: value }));
  const copyTranscript = async () => {
    try { await navigator.clipboard.writeText(messages.map(m => `${m.role === "user" ? "You" : persona.agentName}: ${m.text}`).join("\n\n")); setCopied(true); timers.current.push(setTimeout(() => setCopied(false), 1800)); }
    catch { setError("Copy is unavailable in this browser. You can select the transcript text instead."); }
  };
  const phaseLabel = { idle: complete ? "Preview complete" : messages.length ? "Session ended" : "Ready to start", connecting: "Connecting…", listening: source === "preview" ? "You are speaking" : muted ? "Microphone muted" : "Listening", thinking: "Thinking", speaking: `${persona.agentName} is speaking` }[phase];
  const duration = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;

  return <main className="studio-shell" style={{ "--persona-color": persona.color } as CSSProperties}>
    <audio ref={audio} autoPlay muted={!sound} />
    <header className="studio-header"><a href="/" className="studio-brand" aria-label="Voice Studio home"><span className="brand-mark"><AudioLines size={22} /></span>Voice<span className="brand-light">Studio</span><span className="demo-tag">DEMO</span></a><div className="header-actions">{backendPages ? <><Button asChild variant="outline" className="header-tool"><a href={backendPages.diagnostics} target="_blank" rel="noreferrer" aria-label="Open Observability dashboard" title="Open diagnostics dashboard in a new tab"><ChartLine size={16} /><span>Observability</span></a></Button><Button asChild variant="outline" className="header-tool"><a href={backendPages.original} target="_blank" rel="noreferrer" aria-label="Open original UI" title="Open the existing client with all its controls in a new tab"><PanelsTopLeft size={16} /><span>Original UI</span></a></Button></> : null}<Button className="header-tool" variant="outline" onClick={() => setSettingsOpen(true)} disabled={active} aria-label="Session settings"><Settings2 size={16} /><span>Settings</span></Button></div></header>

    <section className="persona-section" aria-labelledby="persona-heading"><div className="workspace-heading"><div><span className="eyebrow">01 / CHOOSE YOUR PERSONA</span><h1 id="persona-heading">Who will you talk to?</h1></div><p>Pick a persona and start speaking immediately with Gemini Live or Cascade.</p></div><RadioGroup aria-labelledby="persona-heading" value={settings.personaId} onValueChange={choosePersona} className="persona-grid" disabled={active}>{PERSONAS.map(item => {
      const isSelected = settings.personaId === item.id;
      return <label key={item.id} htmlFor={item.id} className={`persona-card ${item.id === "custom" ? "custom-card" : ""} ${isSelected ? "selected" : ""} ${active ? "locked" : ""}`} style={{ "--card-color": item.color } as CSSProperties}><div className="persona-card-top"><PersonaAvatar key={item.id} persona={item} className="card-portrait" /><RadioGroupItem id={item.id} value={item.id} aria-label={item.id === "custom" ? item.name : `${item.agentName}, ${item.name}`} /></div><strong>{item.id === "custom" ? item.name : item.agentName}</strong>{item.id !== "custom" && <span className="persona-role">{item.name}</span>}<span className="persona-description">{item.description}</span>{isSelected && !active && <div className="card-quick-actions"><span className="card-active-pill">Selected</span></div>}</label>;
    })}</RadioGroup></section>

    <div className="workspace-toolbar"><div className="engine-choice"><span className="eyebrow">02 / CHOOSE YOUR ENGINE</span><Tabs value={settings.engine} onValueChange={chooseEngine}><TabsList aria-label="Voice engine" className="engine-tabs"><TabsTrigger value="live" disabled={active}><Radio size={16} />Gemini Live</TabsTrigger><TabsTrigger value="cascade" disabled={active}><Layers3 size={16} />Cascade</TabsTrigger></TabsList></Tabs></div><p className="engine-description">{settings.engine === "live" ? "Native 2-way audio with bidirectional streaming." : "Speech recognition (STT) → language model (LLM) → voice (TTS)."}</p></div>

    <div className="session-grid"><section className={`conversation-stage phase-${phase}`} aria-labelledby="agent-heading"><div className="stage-top"><span className={`connection-state ${active ? "is-active" : ""}`}><span className="status-dot" />{phaseLabel}</span></div><div className="agent-stage"><div className="wave-container" aria-hidden="true">{Wave ? <Wave audioTrack={source === "backend" ? track : null} isThinking={!reduced && active && (source === "preview" || phase === "thinking" || phase === "connecting")} color1={persona.color} color2="#82b7a6" backgroundColor="transparent" rotationEnabled={!reduced && active} numBars={64} sensitivity={1.3} /> : <div className="wave-fallback" />}<div className="wave-core"><PersonaAvatar key={persona.id} persona={persona} className="stage-portrait" /></div></div><h2 id="agent-heading">{custom ? "Your agent. Your rules." : `Meet ${persona.agentName}.`}</h2><p>{custom ? "A blank canvas for your voice app" : persona.name}</p></div><div className="your-role"><span className="eyebrow">{custom ? "CUSTOM SESSION" : "YOUR ROLE"}</span><p>{persona.userRole}</p></div><div className="session-actions">{active ? <Button className="primary-call end-call" onClick={() => void endSession()}><Square size={15} fill="currentColor" />End Session</Button> : <div className="engine-action-buttons"><Button className={`primary-call call-live ${settings.engine === "live" ? "highlight-engine" : ""}`} onClick={() => void startBackend("live")}><Mic size={18} /><span>Talk via <strong>Gemini Live</strong></span></Button><Button variant="outline" className={`secondary-call call-cascade ${settings.engine === "cascade" ? "highlight-engine" : ""}`} onClick={() => void startBackend("cascade")}><Layers3 size={17} /><span>Talk via <strong>Cascade</strong></span></Button></div>}<div className="audio-controls"><Button variant="outline" size="icon" aria-label={muted ? "Unmute microphone" : "Mute microphone"} aria-pressed={muted} disabled={!active || source !== "backend" || phase === "connecting"} onClick={() => { session.current?.setMic(muted); setMuted(!muted); }}>{muted ? <MicOff size={17} /> : <Mic size={17} />}</Button><span>{active ? "Live audio active · Interrupt anytime" : "Microphone active on start"}</span><Button variant="outline" size="icon" aria-label={sound ? "Mute speaker" : "Enable speaker"} aria-pressed={!sound} onClick={toggleSound}>{sound ? <Volume2 size={17} /> : <VolumeX size={17} />}</Button></div></div><p className="preview-note">{active ? `Connected via ${engineName} with ${persona.agentName}. Speak into your microphone.` : `Ready to talk. Choose Gemini Live or Cascade to speak with ${custom ? "your agent" : persona.agentName}.`}</p></section>

      <section className="transcript-panel" aria-labelledby="transcript-heading"><div className="transcript-heading"><div><MessageSquare size={18} /><h2 id="transcript-heading">Conversation</h2><span className="transcript-badge">{source === "preview" ? "SCRIPTED PREVIEW" : engineName.toUpperCase()}</span></div><Button variant="ghost" size="icon" onClick={() => void copyTranscript()} disabled={!messages.length} aria-label={copied ? "Transcript copied" : "Copy transcript"}>{copied ? <Check size={17} /> : <Copy size={17} />}</Button></div><div className="transcript-scroll" ref={transcript} onScroll={e => { const el = e.currentTarget; followTranscript.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }} role={messages.length ? "log" : "region"} aria-label="Conversation transcript" aria-live={messages.length ? "polite" : "off"} aria-relevant="additions text"><AnimatePresence mode="wait">{!messages.length ? <motion.div key={persona.id} className="transcript-empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><PersonaAvatar key={persona.id} persona={persona} className="empty-portrait" />{custom ? <><h3>Start with your own instructions.</h3><p>Set the role, tone and goal for your agent. Both engines use the instructions you enter here.</p><div className="custom-prompt field"><label htmlFor="custom-instructions">System instructions <span className="optional-label">optional</span></label><Textarea id="custom-instructions" value={settings.instructions} onChange={e => update("instructions", e.target.value)} disabled={active} placeholder="You are a helpful voice assistant. Keep replies brief, ask one question at a time, and…" maxLength={1000} rows={5} /><p className="field-hint">{settings.instructions ? `${settings.instructions.length}/1000 characters` : "Leave blank to use your backend’s existing system instructions."}</p></div></> : <><h3>Step into the conversation.</h3><p>{phase === "connecting" ? `Connecting you with ${persona.agentName}…` : `Select Gemini Live or Cascade on the left to start talking directly with ${persona.agentName}.`}</p><div className="opening-cue"><span className="eyebrow">TRY SAYING</span><blockquote>“{persona.opening}”</blockquote></div><div className="journey"><span className="eyebrow">DEMO FOCUS</span><ol>{persona.journey.map((step, i) => <li key={step}><span>{i + 1}</span>{step}{i < persona.journey.length - 1 && <ArrowRight size={13} className="journey-arrow" />}</li>)}</ol></div></>}</motion.div> : <div className="message-list" key="messages">{messages.map(message => <motion.article layout={!reduced} initial={{ opacity: 0, y: reduced ? 0 : 6 }} animate={{ opacity: 1, y: 0 }} key={message.id} className={`message message-${message.role}`}><span className="message-avatar">{message.role === "assistant" ? <PersonaAvatar key={persona.id} persona={persona} className="transcript-portrait" /> : <Mic size={15} />}</span><div className="message-content"><div className="message-meta"><strong>{message.role === "assistant" ? persona.agentName : "You"}</strong><time>{message.time}</time></div><p>{message.text}</p></div></motion.article>)}{partialUser && <div className="partial-message">{partialUser}</div>}{active && phase === "thinking" && <div className="thinking-indicator"><span /><span /><span /><span className="sr-only">{persona.agentName} is thinking</span></div>}{complete && <div className="preview-complete"><Check size={16} /><span>Session complete. Ready to talk again?</span></div>}</div>}</AnimatePresence></div><div className="transcript-footer"><span><span className={`status-dot ${active ? "is-active" : ""}`} />{source === "preview" ? "Scripted persona preview · no API calls" : active ? "Live transcript" : "Your conversation will appear here"}</span><div><span className="session-clock">{duration}</span>{latency !== null && <span title="Measured from user transcript arrival to first response audio">Response {(latency / 1000).toFixed(2)}s</span>}</div></div></section></div>

    <AnimatePresence>{error && <motion.div className="error-banner" role="alert" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><span>{error}</span><Button variant="ghost" size="icon" aria-label="Dismiss error" onClick={() => setError("")}><X size={16} /></Button></motion.div>}</AnimatePresence>
    <footer className="studio-footer"><span><AudioLines size={15} /> Voice Studio <span className="footer-separator">/</span> Fictional agents · AI-generated portraits</span><div>{sourceDownload && <a href="/voice-studio-source.zip" download>Download source <ArrowUpRight size={14} /></a>}<a href="https://github.com/manishkjs/gemini_live_pipecat" target="_blank" rel="noreferrer">View project <ArrowUpRight size={14} /></a></div></footer>

    <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}><DialogContent className="studio-dialog"><DialogHeader><DialogTitle>Session settings</DialogTitle><DialogDescription>{persona.name} · {engineName}. {custom ? "Customize your instructions and parameters." : "Adjust voice and model parameters."}</DialogDescription></DialogHeader><div className="dialog-fields"><div className="settings-pair"><Picker label="Voice" value={settings.voice} disabled={active} onChange={value => update("voice", value)} options={["Aoede", "Puck", "Charon", "Fenrir", "Kore"].map(v => [v, v] as const)} /><Picker label="Language" value={settings.language} disabled={active} onChange={value => update("language", value)} options={LANGUAGE_OPTIONS} /></div>{settings.engine === "live" ? <Picker label="Live model" value={settings.model} disabled={active} onChange={value => update("model", value)} options={[["gemini-live-2.5-flash-native-audio", "Gemini 2.5 · Native audio"], ["gemini-3.5-flash-live-preview", "Gemini 3.5 · Live preview (Vertex AI)"], ["gemini-3.5-flash-lite-live-preview", "Gemini 3.5 · Lite preview"]]} /> : <div className="cascade-models"><p className="field-hint">Cascade uses three models. These defaults match your backend.</p>{([["sttModel", "Speech recognition model"], ["llmModel", "Language model"], ["ttsModel", "Voice model"]] as const).map(([key, label]) => <div className="field" key={key}><label htmlFor={key}>{label}</label><Input id={key} value={settings[key]} disabled={active} onChange={e => update(key, e.target.value)} /></div>)}</div>}<div className="field"><div className="instructions-label"><label htmlFor="instructions">{custom ? "System instructions" : "Persona instructions"}</label>{settings.instructions && <Button variant="ghost" size="sm" disabled={active} onClick={() => update("instructions", "")}>{custom ? "Use backend default" : "Restore preset"}</Button>}</div><Textarea id="instructions" placeholder={custom ? "Leave blank to use your backend’s existing system instructions." : persona.prompt} value={settings.instructions} onChange={e => update("instructions", e.target.value)} disabled={active} maxLength={1000} rows={4} /><p className="field-hint">{settings.instructions ? `${settings.instructions.length}/1000 characters${custom ? "" : " · replaces the persona preset"}` : custom ? "Using your backend’s existing system instructions." : `Using the ${persona.name} preset. Write here to customize it.`}</p></div><details className="advanced-url-toggle"><summary>Advanced: Custom Server URL (Optional)</summary><div className="field" style={{ marginTop: "10px" }}><Input id="backend-url" value={settings.backendUrl} onChange={e => update("backendUrl", e.target.value)} placeholder="http://localhost:7860" disabled={active} type="url" autoComplete="off" /><p className="field-hint">Defaults automatically to your backend on port 7860 or host origin. Override only if connecting to an external server.</p></div></details></div><div className="dialog-actions"><Button variant="outline" onClick={() => setSettingsOpen(false)}>Done</Button><Button className="primary-call" disabled={active} onClick={() => void startBackend()}><Mic size={16} />Start {engineName}</Button></div></DialogContent></Dialog>
  </main>;
}
