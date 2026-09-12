import type { MessageMetrics } from "@/lib/pipecat-session";

export type Phase = "idle" | "connecting" | "listening" | "thinking" | "speaking";
export type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  time: string;
  createdAt?: number;
  metrics?: MessageMetrics;
};
export type WaveProps = {
  audioTrack: MediaStreamTrack | null;
  isThinking: boolean;
  color1: string;
  color2: string;
  backgroundColor: string;
  rotationEnabled: boolean;
  numBars: number;
  sensitivity: number;
};
